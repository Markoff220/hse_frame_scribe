"""VideoNotes web: FastAPI + очередь задач + drag&drop UI.

Запуск:  python app/web.py      (локально)
         docker compose up -d   (в контейнере)

API:
  GET  /                     — UI
  POST /api/upload           — загрузка видео (multipart, поле "file")
  GET  /api/jobs             — список задач
  GET  /api/jobs/{id}/log    — лог задачи
  GET  /api/jobs/{id}/download — конспект.md
  GET  /api/health           — здоровье (модели, очередь)
"""
import json
import logging
import os
import queue
import re
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / "pipeline"))

from common import ROOT, VIDEO_EXTS, load_config, sanitize, setup_logging  # noqa: E402
from main import process_video  # noqa: E402

app = FastAPI(title="VideoNotes")
cfg = load_config()
log = setup_logging(ROOT / "runtime" / "logs" / f"web_{datetime.now():%Y%m%d}.log")


def _ollama_tags(url: str) -> tuple[bool, set[str]]:
    """(Ollama доступен?, множество имён моделей)."""
    try:
        import requests
        r = requests.get(f"{url.rstrip('/')}/api/tags", timeout=5)
        r.raise_for_status()
        return True, {m.get("name", "") for m in r.json().get("models", [])}
    except Exception:
        return False, set()


def _model_present(need: str, present: set[str]) -> bool:
    if not need:
        return False
    if need in present:
        return True
    if ":" not in need:  # без тега — любая версия модели
        return any(p.split(":")[0] == need for p in present)
    return False


def _asr_status() -> str:
    """Статус весов GigaAM: ok | partial (скачана часть/обрубились) | missing."""
    model = cfg["asr"].get("model", "v3_e2e_rnnt")
    model_dir = Path(cfg["asr"].get("model_dir", "runtime/models/gigaam"))
    if not model_dir.is_absolute():
        model_dir = ROOT / model_dir
    files = [model_dir / f"{model}.ckpt"]
    if "e2e" in model:
        files.append(model_dir / f"{model}_tokenizer.model")
    if not any(f.exists() for f in files):
        return "missing"
    if all(f.exists() and f.stat().st_size > 0 for f in files):
        return "ok"
    return "partial"


_GPU: dict | None = None


def _gpu_info() -> dict:
    """GPU/CPU: {available, name}. Ленивый импорт torch, кэшируется."""
    global _GPU
    if _GPU is None:
        try:
            import torch
            if torch.cuda.is_available():
                _GPU = {"available": True, "name": torch.cuda.get_device_name(0)}
            else:
                _GPU = {"available": False, "name": "CPU"}
        except Exception:
            _GPU = {"available": False, "name": "CPU"}
    return _GPU


def _log_ollama_status() -> None:
    """Старт: показать, доступен ли Ollama и загружены ли нужные модели (не блокирует сервис)."""
    url = cfg["llm"].get("ollama_url", "").rstrip("/")
    ok, present = _ollama_tags(url)
    if not ok:
        log.warning("Ollama пока недоступна (%s) — ожидается сервис ollama/ollama-init", url)
        return
    missing = [n for n in sorted({cfg["llm"].get("vlm_model"), cfg["llm"].get("llm_model")})
               if not _model_present(n, present)]
    log.info("Ollama доступна: %s | модели: %s", url, ", ".join(sorted(present)) or "(нет)")
    if missing:
        log.warning("Модели ещё не готовы (ollama-init должен их подтянуть): %s", ", ".join(missing))
    else:
        log.info("Все нужные модели на месте")


_log_ollama_status()

UPLOAD_DIR = ROOT / "runtime" / "tmp" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

JOBS: dict[str, dict] = {}
JOBS_FILE = ROOT / "runtime" / "tmp" / "jobs.json"
Q: queue.Queue = queue.Queue()
LOCK = threading.Lock()


def _save_jobs() -> None:
    """Персистим состояние задач, чтобы ссылки пережили рестарт контейнера."""
    try:
        JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
        JOBS_FILE.write_text(json.dumps(list(JOBS.values()), ensure_ascii=False, indent=1))
    except Exception:  # noqa: BLE001
        pass


def _load_jobs() -> None:
    if not JOBS_FILE.exists():
        return
    try:
        for j in json.loads(JOBS_FILE.read_text(encoding="utf-8")):
            jid = j.get("id")
            if not jid or jid in JOBS:
                continue
            if j.get("status") == "running":
                j["status"] = "error"
                j["error"] = "Прервана перезапуском сервиса"
                j["stage"] = "Прервана перезапуском сервиса"
            JOBS[jid] = j
    except Exception:  # noqa: BLE001
        pass


_load_jobs()
STAGE_RE = re.compile(r"\[(\d)/5\]")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _job_logger(job_id: str) -> logging.Logger:
    job = JOBS[job_id]

    class StageHandler(logging.Handler):
        def emit(self, record):
            message = record.getMessage()
            m = STAGE_RE.search(message)
            if m:
                job["stage"] = message
            elif message.startswith(("Скачивание ", "Сборка MP4")) or "аудиодорожки " in message:
                job["stage"] = message.strip()

    logger = logging.getLogger(f"videonotes.job.{job_id}")
    logger.setLevel(logging.INFO)
    logger.propagate = False  # свой stdout-хендлер есть — без дублей в docker logs
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    logger.addHandler(StageHandler())
    fh = logging.FileHandler(ROOT / "runtime" / "logs" / f"job_{job_id}.log", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


def worker() -> None:
    while True:
        job_id = Q.get()
        job = JOBS[job_id]
        jlog = _job_logger(job_id)
        job["status"] = "running"
        job["started"] = _now()
        try:
            if job.get("kind") == "mts_download":
                job["stage"] = "Скачивание записи экрана со звуком..."
                from mts_link import download_recording
                job["out"] = str(download_recording(job["source_url"], jlog))
                job["stage"] = "MP4 со звуком скачан"
            else:
                job["stage"] = "Загрузка моделей..."
                job["out"] = str(process_video(Path(job["path"]), cfg, jlog))
            job["status"] = "done"
            if job.get("kind") != "mts_download":
                job["stage"] = "Готово"
        except Exception as e:  # noqa: BLE001
            job["status"] = "error"
            job["error"] = str(e)
            job["stage"] = f"Ошибка: {str(e)[:120]}"
            jlog.exception("Job %s failed: %s", job_id, e)
        job["finished"] = _now()
        _save_jobs()
        Q.task_done()


threading.Thread(target=worker, daemon=True).start()


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (BASE / "web" / "index.html").read_text(encoding="utf-8")


@app.get("/api/health")
def health() -> dict:
    """Статус стека для панели индикаторов: ASR-веса, VLM/LLM-модели, GPU/CPU."""
    ollama_ok, present = _ollama_tags(cfg["llm"].get("ollama_url", ""))

    def _llm_status(model: str) -> str:
        if not ollama_ok:
            return "unavailable"
        return "ok" if _model_present(model, present) else "missing"

    return {
        "ok": True,
        "queued": Q.qsize(),
        "asr": {"model": cfg["asr"].get("model"), "status": _asr_status()},
        "vlm": {"model": cfg["llm"].get("vlm_model"), "status": _llm_status(cfg["llm"].get("vlm_model", ""))},
        "llm": {"model": cfg["llm"].get("llm_model"), "status": _llm_status(cfg["llm"].get("llm_model", ""))},
        "gpu": _gpu_info(),
        "ollama_url": cfg["llm"].get("ollama_url"),
        # Хостовый путь к папке конспектов (для UI: показывать путь на хосте, а не /app/output)
        "output_dir": os.environ.get("OUTPUT_HOST_DIR", ""),
    }


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    name = file.filename or "video.mp4"
    if Path(name).suffix.lower() not in VIDEO_EXTS:
        raise HTTPException(400, f"Не видео: {name} (допустимо: {', '.join(sorted(VIDEO_EXTS))})")
    job_id = uuid.uuid4().hex[:8]
    base = sanitize(name)
    stem, ext = Path(base).stem, Path(base).suffix
    dest = UPLOAD_DIR / base
    n = 2
    while dest.exists():
        dest = UPLOAD_DIR / f"{stem}_{n}{ext}"
        n += 1
    with dest.open("wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)
    if dest.stat().st_size > 8 * 1024**3:
        dest.unlink(missing_ok=True)
        raise HTTPException(413, "Файл больше 8 ГБ")
    with LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "name": name,
            "path": str(dest),
            "status": "uploaded",
            "stage": "Готово к запуску",
            "created": _now(),
            "started": None,
            "finished": None,
            "out": None,
            "error": None,
        }
    _save_jobs()
    log.info("Загружено %s (%.1f МБ) -> job %s; ожидает ручного запуска", name, dest.stat().st_size / 1e6, job_id)
    return JOBS[job_id]


@app.post("/api/mts-link")
def add_mts_link(payload: dict) -> dict:
    """Ставит в очередь загрузку screen-share MP4 из публичной ссылки МТС Линк."""
    url = str(payload.get("url", ""))
    try:
        from mts_link import parse_share_url
        record_id, _ = parse_share_url(url)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    job_id = uuid.uuid4().hex[:8]
    with LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "name": f"МТС Линк: запись экрана со звуком #{record_id}",
            "kind": "mts_download",
            "source_url": url,
            "status": "queued",
            "stage": "В очереди",
            "created": _now(),
            "started": None,
            "finished": None,
            "out": None,
            "error": None,
        }
        Q.put(job_id)
        _save_jobs()
    log.info("МТС Линк #%s поставлена в очередь: job %s", record_id, job_id)
    return {k: v for k, v in JOBS[job_id].items() if k != "source_url"}


@app.post("/api/jobs/{job_id}/start")
def start_job(job_id: str) -> dict:
    """Ставим ранее загруженное видео в очередь только по явному действию пользователя."""
    with LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(404, f"Нет такой задачи: {job_id}")
        if job["status"] != "uploaded":
            raise HTTPException(409, f"Задачу нельзя запустить: {job.get('stage')}")
        job["status"] = "queued"
        job["stage"] = "В очереди"
        Q.put(job_id)
        _save_jobs()
    log.info("Ручной запуск %s -> job %s", job["name"], job_id)
    return job


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict:
    """Удаляет завершённую или ошибочную заявку и её лог, сохраняя результат на диске."""
    with LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(404, f"Нет такой задачи: {job_id}")
        if job["status"] not in {"done", "error"}:
            raise HTTPException(409, "Можно удалить только завершённую или ошибочную задачу")
        del JOBS[job_id]
        _save_jobs()
    (ROOT / "runtime" / "logs" / f"job_{job_id}.log").unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/jobs")
def jobs() -> list[dict]:
    with LOCK:
        items = [
            {k: v for k, v in j.items() if k not in ("path", "source_url")}
            for j in sorted(JOBS.values(), key=lambda x: x["created"], reverse=True)
        ]
    return items


@app.get("/api/jobs/{job_id}/log", response_class=PlainTextResponse)
def job_log(job_id: str) -> str:
    f = ROOT / "runtime" / "logs" / f"job_{job_id}.log"
    if not f.exists():
        return "(лог ещё не создан)"
    lines = f.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[-300:])


@app.get("/api/jobs/{job_id}/download")
def job_download(job_id: str) -> FileResponse:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, f"Нет такой задачи: {job_id}")
    if job["status"] != "done" or not job.get("out"):
        detail = job.get("error") or job.get("stage") or "в процессе"
        raise HTTPException(409, f"Конспект ещё не готов: {detail}")
    dest = Path(job["out"])
    if not dest.is_file():
        raise HTTPException(
            410,
            "Файл результата не найден на диске (удалён или переименован). Запустите задачу заново.",
        )
    if job.get("kind") == "mts_download":
        return FileResponse(dest, media_type="video/mp4", filename=dest.name)
    return FileResponse(dest, media_type="text/markdown", filename="конспект.md")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    log.info("VideoNotes web: http://0.0.0.0:%d", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
