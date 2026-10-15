"""VideoNotes web: FastAPI + очередь задач + drag&drop UI.

Запуск:  python app/web.py      (локально)
         docker compose up -d   (в контейнере)

API:
   GET  /                     — UI
   GET  /api/models           — каталог и состояние моделей
   POST /api/models/pull      — скачать модель
   PUT  /api/settings/models  — применить модели
  POST /api/upload           — загрузка видео (multipart, поле "file")
  POST /api/mts-link         — задача из ссылки на запись МТС Линк
  GET  /api/jobs             — список задач
  GET  /api/jobs/{id}/log    — лог задачи
  GET  /api/jobs/{id}/download — конспект.md / транскрипция.md / audio.wav / MP4
  GET  /api/jobs/{id}/video  — MP4 записи МТС Линк
  GET  /api/health           — здоровье (модели, очередь)
"""
import json
import logging
import os
import queue
import re
import shutil
import sys
import threading
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / "pipeline"))

from common import ROOT, VIDEO_EXTS, load_config, sanitize, setup_logging  # noqa: E402
from main import extract_audio_track, process_video, save_video, transcribe_video  # noqa: E402

app = FastAPI(title="VideoNotes")
cfg = load_config()
log = setup_logging(ROOT / "runtime" / "logs" / f"web_{datetime.now():%Y%m%d}.log")

MODEL_CATALOG = {
    "asr": [
        {"name": "v3_e2e_rnnt", "label": "GigaAM v3 E2E RNN-T", "size": "449,2 МБ", "note": "Рекомендуется: пунктуация и нормализация текста."},
        {"name": "v3_e2e_ctc", "label": "GigaAM v3 E2E CTC", "size": "442,6 МБ", "note": "Альтернативная end-to-end модель."},
        {"name": "v3_ctc", "label": "GigaAM v3 CTC", "size": "441,7 МБ", "note": "Базовая CTC-модель распознавания."},
    ],
    "vlm": [
        {"name": "qwen2.5vl:3b", "label": "Qwen 2.5 VL 3B", "size": "3,2 ГБ", "note": "Экономный анализ кадров."},
        {"name": "qwen2.5vl:7b", "label": "Qwen 2.5 VL 7B", "size": "6,0 ГБ", "note": "Более точный анализ кадров."},
    ],
    "llm": [
        {"name": "qwen2.5:3b", "label": "Qwen 2.5 3B", "size": "1,9 ГБ", "note": "Быстрый, экономный конспект."},
        {"name": "qwen2.5:7b", "label": "Qwen 2.5 7B", "size": "4,7 ГБ", "note": "Баланс качества и скорости."},
        {"name": "qwen2.5:14b-instruct-q4_K_M", "label": "Qwen 2.5 14B Instruct Q4", "size": "9,0 ГБ", "note": "Максимальное качество конспекта."},
    ],
}
SETTINGS_FILE = ROOT / "runtime" / "tmp" / "model_settings.json"
MODEL_PULLS: dict[str, dict] = {}
MODEL_LOCK = threading.Lock()


def _catalog_names(role: str) -> set[str]:
    return {item["name"] for item in MODEL_CATALOG[role]}


def _load_model_settings() -> dict:
    defaults = {
        "asr_model": cfg["asr"].get("model", "v3_e2e_rnnt"),
        "vlm_model": cfg["llm"].get("vlm_model", "qwen2.5vl:3b"),
        "llm_model": cfg["llm"].get("llm_model", "qwen2.5:3b"),
    }
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    for key, role in (("asr_model", "asr"), ("vlm_model", "vlm"), ("llm_model", "llm")):
        if saved.get(key) in _catalog_names(role):
            defaults[key] = saved[key]
    return defaults


MODEL_SETTINGS = _load_model_settings()


def _apply_model_settings(target: dict, settings: dict) -> dict:
    target["asr"]["model"] = settings["asr_model"]
    target["llm"]["vlm_model"] = settings["vlm_model"]
    target["llm"]["llm_model"] = settings["llm_model"]
    return target


_apply_model_settings(cfg, MODEL_SETTINGS)


def _save_model_settings(settings: dict) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def _ollama_tags(url: str) -> tuple[bool, set[str]]:
    """(Ollama доступен?, множество имён моделей)."""
    try:
        import requests
        r = requests.get(f"{url.rstrip('/')}/api/tags", timeout=5)
        r.raise_for_status()
        return True, {m.get("name", "") for m in r.json().get("models", [])}
    except Exception:
        return False, set()


def _ollama_models(url: str) -> tuple[bool, list[dict]]:
    try:
        import requests
        response = requests.get(f"{url.rstrip('/')}/api/tags", timeout=5)
        response.raise_for_status()
        return True, response.json().get("models", [])
    except Exception:
        return False, []


def _model_present(need: str, present: set[str]) -> bool:
    if not need:
        return False
    if need in present:
        return True
    if ":" not in need:  # без тега — любая версия модели
        return any(p.split(":")[0] == need for p in present)
    return False


def _asr_status(model: str | None = None) -> str:
    """Статус весов GigaAM: ok | partial (скачана часть/обрубились) | missing."""
    model = model or cfg["asr"].get("model", "v3_e2e_rnnt")
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
            elif getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
                _GPU = {"available": True, "name": "Apple Silicon (MPS)"}
            else:
                _GPU = {"available": False, "name": "CPU"}
        except Exception:
            _GPU = {"available": False, "name": "CPU"}
    return _GPU


def _log_ollama_status() -> None:
    """Старт: показать состояние Ollama, не блокируя сервис."""
    url = cfg["llm"].get("ollama_url", "").rstrip("/")
    ok, present = _ollama_tags(url)
    if not ok:
        log.warning("Ollama пока недоступна (%s)", url)
        return
    missing = [n for n in sorted({cfg["llm"].get("vlm_model"), cfg["llm"].get("llm_model")})
               if not _model_present(n, present)]
    log.info("Ollama доступна: %s | модели: %s", url, ", ".join(sorted(present)) or "(нет)")
    if missing:
        log.warning("Выбранные модели ещё не скачаны: %s", ", ".join(missing))
    else:
        log.info("Все нужные модели на месте")


_log_ollama_status()

UPLOAD_DIR = ROOT / "runtime" / "tmp" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

JOBS: dict[str, dict] = {}
JOBS_FILE = ROOT / "runtime" / "tmp" / "jobs.json"
Q: queue.Queue = queue.Queue()
LOCK = threading.Lock()


# Служебные поля задачи: не отдаются в API. sessionId МТС Линк ещё и не пишется на диск.
_HIDDEN_KEYS = {"path", "source_url", "session_id", "video"}
_UNSAVED_KEYS = {"session_id"}


def _public(job: dict) -> dict:
    item = {k: v for k, v in job.items() if k not in _HIDDEN_KEYS}
    video = job.get("video")
    item["has_video"] = bool(video) and Path(video).is_file()
    return item


def _save_jobs() -> None:
    """Персистим состояние задач, чтобы ссылки пережили рестарт контейнера."""
    try:
        JOBS_FILE.parent.mkdir(parents=True, exist_ok=True)
        items = [{k: v for k, v in j.items() if k not in _UNSAVED_KEYS} for j in JOBS.values()]
        JOBS_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _load_jobs() -> None:
    if not JOBS_FILE.exists():
        return
    try:
        raw = JOBS_FILE.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:  # старые версии писали в кодировке системы (cp1251 на Windows)
            text = raw.decode("cp1251", errors="replace")
        for j in json.loads(text):
            jid = j.get("id")
            if not jid or jid in JOBS:
                continue
            if j.get("status") == "running":
                j["status"] = "error"
                j["error"] = "Прервана перезапуском сервиса"
                j["stage"] = "Прервана перезапуском сервиса"
            j.setdefault("mode", "full")
            JOBS[jid] = j
    except Exception:  # noqa: BLE001
        pass


_load_jobs()
STAGE_RE = re.compile(r"\[(\d+)/(\d+)\]")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _start_model_pull(role: str, model: str) -> dict:
    operation = {
        "id": uuid.uuid4().hex[:8],
        "role": role,
        "model": model,
        "status": "queued",
        "detail": "В очереди",
        "completed": 0,
        "total": 0,
        "error": None,
    }
    with MODEL_LOCK:
        if any(item["model"] == model and item["status"] in {"queued", "downloading"}
               for item in MODEL_PULLS.values()):
            raise HTTPException(409, "Эта модель уже скачивается")
        MODEL_PULLS[operation["id"]] = operation
    threading.Thread(target=_pull_model, args=(operation["id"],), daemon=True).start()
    return operation


def _pull_model(operation_id: str) -> None:
    operation = MODEL_PULLS[operation_id]
    operation["status"] = "downloading"
    try:
        if operation["role"] == "asr":
            from asr import GigaAMASR
            asr_cfg = deepcopy(cfg["asr"])
            asr_cfg["model"] = operation["model"]
            asr = GigaAMASR(asr_cfg, log)
            asr.load()
            asr.unload()
        else:
            import requests
            response = requests.post(
                f"{cfg['llm']['ollama_url'].rstrip('/')}/api/pull",
                json={"model": operation["model"], "stream": True}, stream=True, timeout=(5, None),
            )
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                update = json.loads(line)
                operation["detail"] = update.get("status", operation["detail"])
                operation["completed"] = update.get("completed", operation["completed"])
                operation["total"] = update.get("total", operation["total"])
                if update.get("error"):
                    raise RuntimeError(update["error"])
        operation["status"] = "success"
    except Exception as error:  # noqa: BLE001
        operation["status"] = "error"
        operation["error"] = str(error)
        log.exception("Не удалось скачать модель %s: %s", operation["model"], error)


def _job_config(job: dict) -> dict:
    process_cfg = deepcopy(cfg)
    _apply_model_settings(process_cfg, job.get("models", MODEL_SETTINGS))
    return process_cfg


def _missing_model_roles(settings: dict) -> list[str]:
    ollama_ok, present = _ollama_tags(cfg["llm"].get("ollama_url", ""))
    missing = []
    if _asr_status(settings["asr_model"]) != "ok":
        missing.append("ASR")
    if not ollama_ok or not _model_present(settings["vlm_model"], present):
        missing.append("VLM")
    if not ollama_ok or not _model_present(settings["llm_model"], present):
        missing.append("LLM")
    return missing


def _close_job_logger(job_id: str) -> None:
    """Закрыть файл лога задачи: на Windows открытый файл нельзя удалить."""
    logger = logging.getLogger(f"videonotes.job.{job_id}")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


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
    _close_job_logger(job_id)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    logger.addHandler(StageHandler())
    fh = logging.FileHandler(ROOT / "runtime" / "logs" / f"job_{job_id}.log", encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    return logger


def _download_mts(job: dict, jlog: logging.Logger) -> None:
    """Ссылка МТС Линк -> MP4 в runtime/tmp/uploads/<id>/; дальше задача идёт как загруженное видео."""
    from mts_link import download_recording
    job["stage"] = "Скачивание записи МТС Линк..."
    session_id = job.pop("session_id", None)  # нужен только для запроса данных записи
    video = download_recording(job.pop("source_url"), UPLOAD_DIR / job["id"], session_id=session_id,
                               log=jlog, on_title=lambda title: job.update(name=title))
    job["path"] = job["video"] = str(video)
    _save_jobs()


def _keep_video_with_results(job: dict, jlog: logging.Logger) -> None:
    """MP4 записи кладём рядом с результатом: output/<имя>/запись.mp4."""
    src, dest = Path(job["video"]), Path(job["out"]).parent / "запись.mp4"
    if src != dest:
        try:
            shutil.move(str(src), str(dest))
        except OSError as e:
            jlog.warning("Видео записи осталось в %s: не удалось перенести (%s)", src, e)
            return
        job["path"] = job["video"] = str(dest)
        jlog.info("Видео записи: %s", dest)
    shutil.rmtree(UPLOAD_DIR / job["id"], ignore_errors=True)


def _run_job(job_id: str) -> None:
    job = JOBS[job_id]
    jlog = _job_logger(job_id)
    job["status"] = "running"
    job["started"] = _now()
    try:
        if job.get("source") == "mts":
            _download_mts(job, jlog)
        mode = job.get("mode", "full")
        if mode == "video":
            job["stage"] = "Сохранение видео..."
            job["out"] = job["video"] = str(save_video(Path(job["path"]), _job_config(job), jlog))
            job["path"] = job["out"]
        elif mode == "audio":
            job["stage"] = "Извлечение аудиодорожки..."
            job["out"] = str(extract_audio_track(Path(job["path"]), _job_config(job), jlog))
        elif mode == "transcript":
            job["stage"] = "Загрузка модели распознавания..."
            job["out"] = str(transcribe_video(Path(job["path"]), _job_config(job), jlog))
        else:
            job["stage"] = "Загрузка моделей..."
            job["out"] = str(process_video(Path(job["path"]), _job_config(job), jlog))
        if job.get("source") == "mts":
            _keep_video_with_results(job, jlog)
        job["status"] = "done"
        job["stage"] = "Готово"
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = str(e)
        job["stage"] = f"Ошибка: {str(e)[:120]}"
        jlog.exception("Job %s failed: %s", job_id, e)
    finally:
        # ссылка (в публичной — токен) и sessionId нужны были только для скачивания
        job.pop("session_id", None)
        job.pop("source_url", None)
        _close_job_logger(job_id)
    job["finished"] = _now()
    _save_jobs()


def worker() -> None:
    while True:
        job_id = Q.get()
        try:
            _run_job(job_id)
        finally:
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


@app.get("/api/models")
def models() -> dict:
    """Каталог, выбранные модели и состояние их загрузки."""
    ollama_ok, local_models = _ollama_models(cfg["llm"].get("ollama_url", ""))
    present = {model.get("name", "") for model in local_models}
    with MODEL_LOCK:
        pulls = list(MODEL_PULLS.values())
    return {
        "catalog": MODEL_CATALOG,
        "settings": MODEL_SETTINGS,
        "ollama_available": ollama_ok,
        "ollama_models": local_models,
        "installed": {
            "asr": {name: _asr_status(name) for name in _catalog_names("asr")},
            "vlm": {name: _model_present(name, present) for name in _catalog_names("vlm")},
            "llm": {name: _model_present(name, present) for name in _catalog_names("llm")},
        },
        "pulls": pulls,
    }


@app.post("/api/models/pull")
def pull_model(payload: dict) -> dict:
    role = str(payload.get("role", ""))
    model = str(payload.get("model", ""))
    if role not in MODEL_CATALOG or model not in _catalog_names(role):
        raise HTTPException(400, "Неизвестная модель или её роль")
    return _start_model_pull(role, model)


@app.put("/api/settings/models")
def save_models(payload: dict) -> dict:
    global MODEL_SETTINGS
    settings = {
        "asr_model": str(payload.get("asr_model", "")),
        "vlm_model": str(payload.get("vlm_model", "")),
        "llm_model": str(payload.get("llm_model", "")),
    }
    for key, role in (("asr_model", "asr"), ("vlm_model", "vlm"), ("llm_model", "llm")):
        if settings[key] not in _catalog_names(role):
            raise HTTPException(400, f"Недопустимая модель для {role}")

    missing = _missing_model_roles(settings)
    if missing:
        raise HTTPException(409, f"Сначала скачайте модели: {', '.join(missing)}")

    MODEL_SETTINGS = settings
    _apply_model_settings(cfg, MODEL_SETTINGS)
    _save_model_settings(MODEL_SETTINGS)
    return {"settings": MODEL_SETTINGS}


JOB_MODES = {"full", "transcript", "audio"}
LINK_MODES = JOB_MODES | {"video"}  # «Только видео» имеет смысл только для ссылок


@app.post("/api/upload")
async def upload(file: UploadFile = File(...), mode: str = Form("full")) -> dict:
    name = file.filename or "video.mp4"
    if Path(name).suffix.lower() not in VIDEO_EXTS:
        raise HTTPException(400, f"Не видео: {name} (допустимо: {', '.join(sorted(VIDEO_EXTS))})")
    if mode == "video":
        raise HTTPException(400, "Режим «Только видео» работает только со ссылками МТС Линк")
    if mode not in JOB_MODES:
        raise HTTPException(400, "Неизвестный режим обработки")
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
            "mode": mode,
            "status": "uploaded",
            "stage": "Готово к запуску",
            "created": _now(),
            "started": None,
            "finished": None,
            "out": None,
            "error": None,
        }
    _save_jobs()
    log.info("Загружено %s (%.1f МБ, режим %s) -> job %s; ожидает ручного запуска", name, dest.stat().st_size / 1e6, mode, job_id)
    return _public(JOBS[job_id])


@app.post("/api/mts-link")
def add_mts_link(payload: dict) -> dict:
    """Задача из ссылки на запись МТС Линк. Скачивание и склейка начнутся после «Запустить»."""
    from mts_link import clean_session_id, parse_url
    url = str(payload.get("url") or "").strip()
    mode = str(payload.get("mode") or "full")
    if mode not in LINK_MODES:
        raise HTTPException(400, "Неизвестный режим обработки")
    try:
        link = parse_url(url)
        session_id = clean_session_id(str(payload.get("session_id") or ""))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    job_id = uuid.uuid4().hex[:8]
    with LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "name": f"МТС Линк · запись {link.record_id or link.event_session}",
            "source": "mts",
            "source_url": url,
            "path": None,
            "mode": mode,
            "status": "uploaded",
            "stage": "Готово к запуску",
            "created": _now(),
            "started": None,
            "finished": None,
            "out": None,
            "error": None,
        }
        if session_id:
            JOBS[job_id]["session_id"] = session_id
    _save_jobs()
    log.info("Ссылка МТС Линк (сессия %s, режим %s%s) -> job %s; ожидает ручного запуска",
             link.event_session, mode, ", с sessionId" if session_id else "", job_id)
    return _public(JOBS[job_id])


@app.post("/api/jobs/{job_id}/start")
def start_job(job_id: str) -> dict:
    """Ставим ранее загруженное видео в очередь только по явному действию пользователя."""
    with LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(404, f"Нет такой задачи: {job_id}")
        if job["status"] != "uploaded":
            raise HTTPException(409, f"Задачу нельзя запустить: {job.get('stage')}")
        if job.get("mode", "full") == "full":
            missing = _missing_model_roles(MODEL_SETTINGS)
            if missing:
                raise HTTPException(409, f"Скачайте выбранные модели: {', '.join(missing)}")
            job["models"] = deepcopy(MODEL_SETTINGS)
        elif job.get("mode") == "transcript":
            if _asr_status(MODEL_SETTINGS["asr_model"]) != "ok":
                raise HTTPException(409, "Скачайте модель ASR в «Настройках моделей»")
            job["models"] = deepcopy(MODEL_SETTINGS)
        job["status"] = "queued"
        job["stage"] = "В очереди"
        Q.put(job_id)
        _save_jobs()
    log.info("Ручной запуск %s -> job %s", job["name"], job_id)
    return _public(job)


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict:
    """Удаляет подготовленную, завершённую или ошибочную заявку."""
    with LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(404, f"Нет такой задачи: {job_id}")
        if job["status"] not in {"uploaded", "done", "error"}:
            raise HTTPException(409, "Нельзя удалить задачу во время обработки")
        del JOBS[job_id]
        _save_jobs()
    if job["status"] == "uploaded" and job.get("path"):
        Path(job["path"]).unlink(missing_ok=True)
    if job.get("source") == "mts" and job["status"] in {"uploaded", "error"}:
        shutil.rmtree(UPLOAD_DIR / job_id, ignore_errors=True)  # недоделанный MP4 записи
    _close_job_logger(job_id)
    (ROOT / "runtime" / "logs" / f"job_{job_id}.log").unlink(missing_ok=True)
    return {"ok": True}


@app.get("/api/jobs")
def jobs() -> list[dict]:
    with LOCK:
        items = [_public(j) for j in sorted(JOBS.values(), key=lambda x: x["created"], reverse=True)]
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
        raise HTTPException(409, f"Результат ещё не готов: {detail}")
    dest = Path(job["out"])
    if not dest.is_file():
        raise HTTPException(
            410,
            "Файл результата не найден на диске (удалён или переименован). Запустите задачу заново.",
        )
    if job.get("mode", "full") == "audio":
        return FileResponse(dest, media_type="audio/wav", filename="audio.wav")
    if job.get("mode") == "video":
        return FileResponse(dest, media_type="video/mp4", filename=f"{dest.parent.name}.mp4")
    if job.get("mode") == "transcript":
        # имя файла = имя видео, чтобы несколько скачанных пар не назывались одинаково
        return FileResponse(dest, media_type="text/markdown", filename=f"{dest.parent.name}.md")
    return FileResponse(dest, media_type="text/markdown", filename="конспект.md")


@app.get("/api/jobs/{job_id}/video")
def job_video(job_id: str) -> FileResponse:
    """MP4 записи МТС Линк: доступен и после ошибки обработки, если запись успела скачаться."""
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, f"Нет такой задачи: {job_id}")
    video = job.get("video")
    if not video or not Path(video).is_file():
        raise HTTPException(404, "Видео этой задачи нет на диске")
    return FileResponse(video, media_type="video/mp4", filename=f"{sanitize(job.get('name') or 'запись')}.mp4")


def run(port: int = 8090, host: str = "0.0.0.0") -> None:
    log.info("VideoNotes web: http://%s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    run(port=int(sys.argv[1]) if len(sys.argv) > 1 else 8090)
