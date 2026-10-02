import json
import subprocess
import sys
import types
from pathlib import Path

from fastapi.testclient import TestClient

import web  # noqa: E402 — добавляет app/pipeline в sys.path
import report  # noqa: E402


def _job(job_id, video, mode, status="uploaded", out=None):
    return {
        "id": job_id, "name": "lesson.mp4", "path": str(video), "mode": mode,
        "status": status, "stage": "Готово к запуску", "created": "2026-09-01 18:00:00",
        "started": None, "finished": None, "out": out, "error": None,
    }


def test_transcript_job_needs_only_asr(tmp_path, monkeypatch):
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"test")
    monkeypatch.setattr(web, "Q", __import__("queue").Queue())
    monkeypatch.setattr(web, "JOBS_FILE", tmp_path / "jobs.json")
    monkeypatch.setattr(web, "JOBS", {"tr01": _job("tr01", video, "transcript")})
    # Ollama/VLM/LLM не проверяются вообще
    monkeypatch.setattr(web, "_missing_model_roles", lambda s: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(web, "_asr_status", lambda model=None: "ok")

    r = TestClient(web.app).post("/api/jobs/tr01/start")
    assert r.status_code == 200
    assert r.json()["models"] == web.MODEL_SETTINGS
    assert web.Q.get_nowait() == "tr01"


def test_transcript_job_refuses_without_asr_weights(tmp_path, monkeypatch):
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"test")
    monkeypatch.setattr(web, "Q", __import__("queue").Queue())
    monkeypatch.setattr(web, "JOBS_FILE", tmp_path / "jobs.json")
    monkeypatch.setattr(web, "JOBS", {"tr02": _job("tr02", video, "transcript")})
    monkeypatch.setattr(web, "_asr_status", lambda model=None: "partial")
    r = TestClient(web.app).post("/api/jobs/tr02/start")
    assert r.status_code == 409


def test_upload_accepts_transcript_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(web, "JOBS_FILE", tmp_path / "jobs.json")
    monkeypatch.setattr(web, "JOBS", {})
    r = TestClient(web.app).post("/api/upload", files={"file": ("пара.mp4", b"x", "video/mp4")},
                                 data={"mode": "transcript"})
    assert r.status_code == 200 and r.json()["mode"] == "transcript"
    r = TestClient(web.app).post("/api/upload", files={"file": ("пара.mp4", b"x", "video/mp4")},
                                 data={"mode": "nope"})
    assert r.status_code == 400


def test_transcript_download_named_after_video(tmp_path, monkeypatch):
    out_dir = tmp_path / "Алгоритмы_и_структуры_данных._Лекции_2026-09-29"
    out_dir.mkdir()
    md = out_dir / "транскрипция.md"
    md.write_text("# test", encoding="utf-8")
    monkeypatch.setattr(web, "JOBS", {"tr03": _job("tr03", "x", "transcript", "done", str(md))})
    r = TestClient(web.app).get("/api/jobs/tr03/download")
    assert r.status_code == 200
    assert "text/markdown" in r.headers["content-type"]
    assert "%D0%9B%D0%B5%D0%BA%D1%86%D0%B8%D0%B8_2026-09-29.md" in r.headers["content-disposition"]


def test_jobs_saved_as_utf8_and_old_cp1251_still_loads(tmp_path, monkeypatch):
    f = tmp_path / "jobs.json"
    old = [_job("old01", "C:\\видео.mp4", "full", "done", "C:\\output\\Лекция\\конспект.md")]
    f.write_bytes(json.dumps(old, ensure_ascii=False).encode("cp1251"))
    monkeypatch.setattr(web, "JOBS_FILE", f)
    monkeypatch.setattr(web, "JOBS", {})
    web._load_jobs()
    assert web.JOBS["old01"]["out"] == "C:\\output\\Лекция\\конспект.md"
    web._save_jobs()
    assert json.loads(f.read_bytes().decode("utf-8"))[0]["id"] == "old01"


def test_group_paragraphs():
    segs = [
        (0.0, 5.0, "Добрый вечер."), (5.2, 10.0, "Сегодня рекуррентные"), (10.1, 15.0, "соотношения."),
        (15.3, 20.0, "Начнём с примера."),                 # короткая пауза -> тот же абзац
        (23.0, 30.0, "Итак, пусть дана последовательность."),  # пауза 3 с при длине 20 с -> новый
        (45.0, 50.0, "Вопросы?"),                          # пауза 15 с -> новый
    ]
    paras = report.group_paragraphs(segs)
    assert [p[0] for p in paras] == [0.0, 23.0, 45.0]
    assert paras[0][1] == "Добрый вечер. Сегодня рекуррентные соотношения. Начнём с примера."
    # без пунктуации и без пауз абзац всё равно режется по hard_len
    flat = [(i * 10.0, i * 10.0 + 10.0, "слово слово") for i in range(30)]
    assert len(report.group_paragraphs(flat)) == 3


def test_transcribe_video_end_to_end(tmp_path, monkeypatch):
    """Реальный ffmpeg, фейковые VAD и GigaAM: проверяем склейку шагов и файл на выходе."""
    video = tmp_path / "Лекция 5.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=white:s=320x240:d=40:r=5",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=40", "-shortest", str(video)], check=True)

    sys.modules.setdefault("torch", types.ModuleType("torch"))  # audio.py импортирует torch на верхнем уровне
    import audio
    import main

    monkeypatch.setattr(audio, "vad_segments", lambda wav, threshold=0.5: [(1.0, 6.0), (6.6, 12.0), (20.0, 26.0)])

    class FakeASR:
        def __init__(self, cfg, log): pass
        def load(self): pass
        def unload(self): pass
        def transcribe_chunk(self, wav, offset):
            assert Path(wav).stat().st_size > 1000
            return types.SimpleNamespace(text=f"Фраза с {offset:.0f} секунды.")

    fake_asr = types.ModuleType("asr")
    fake_asr.GigaAMASR = FakeASR
    monkeypatch.setitem(sys.modules, "asr", fake_asr)
    monkeypatch.setattr(main, "ROOT", tmp_path)

    import logging
    cfg = {"asr": {"model": "v3_e2e_rnnt"}, "output": {"dir": str(tmp_path / "output")}}
    out = main.transcribe_video(video, cfg, logging.getLogger("t"))

    assert out.name == "транскрипция.md" and out.parent.name == "Лекция 5"
    text = out.read_text(encoding="utf-8")
    assert "**[00:01]** Фраза с 1 секунды. Фраза с 7 секунды." in text
    assert "**[00:20]** Фраза с 20 секунды." in text
    assert "Длительность: 00:40" in text
    assert "Источник: Лекция 5.mp4" in text
    assert not list((tmp_path / "runtime" / "tmp").iterdir())  # рабочая папка с WAV удалена
