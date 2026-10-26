"""«Остановить»: отмена задач в очереди и в работе."""
import json
import sys
import threading
import time
from queue import Queue

import pytest
from fastapi.testclient import TestClient

import web  # noqa: E402 — добавляет app/pipeline в sys.path
import common  # noqa: E402

LINK = "https://my.mts-link.ru/146049682/24264533545/record-new/23673458754/record-file/2104961441"


# --- cancel_scope / run ---------------------------------------------------------

def test_check_cancel_only_inside_scope():
    stop = threading.Event()
    stop.set()
    common.check_cancel()  # вне задачи флага нет
    with common.cancel_scope(stop):
        with pytest.raises(common.Cancelled):
            common.check_cancel()
    common.check_cancel()


def test_run_kills_process_on_cancel():
    stop = threading.Event()
    threading.Timer(0.3, stop.set).start()
    t = time.monotonic()
    with common.cancel_scope(stop), pytest.raises(common.Cancelled):
        common.run([sys.executable, "-c", "import time; time.sleep(30)"], poll=0.1)
    assert time.monotonic() - t < 5


def test_run_behaves_like_subprocess_run():
    r = common.run([sys.executable, "-c", "print('ок')"], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0 and r.stdout.strip() == "ок"
    with pytest.raises(__import__("subprocess").CalledProcessError):
        common.run([sys.executable, "-c", "raise SystemExit(3)"])


# --- веб: остановка задач ---------------------------------------------------------

@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "Q", Queue())
    monkeypatch.setattr(web, "JOBS", {})
    monkeypatch.setattr(web, "CANCEL", {})
    monkeypatch.setattr(web, "JOBS_FILE", tmp_path / "jobs.json")
    monkeypatch.setattr(web, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(web, "_asr_status", lambda model=None: "ok")
    monkeypatch.setitem(web.cfg["output"], "dir", str(tmp_path / "output"))
    (tmp_path / "uploads").mkdir()
    ids = []
    yield tmp_path, ids
    for job_id in ids:
        (web.ROOT / "runtime" / "logs" / f"job_{job_id}.log").unlink(missing_ok=True)


def _upload(client, ids, mode="transcript"):
    job = client.post("/api/upload", files={"file": ("пара.mp4", b"x", "video/mp4")}, data={"mode": mode}).json()
    ids.append(job["id"])
    return job["id"]


def _run_in_thread(job_id):
    th = threading.Thread(target=web._run_job, args=(job_id,))
    th.start()
    for _ in range(200):
        if web.JOBS[job_id]["status"] == "running" and job_id in web.CANCEL:
            break
        time.sleep(0.01)
    return th


def _wait_for_cancel(*args, **kwargs):
    """Подмена долгого шага: крутится, пока не нажмут «Остановить»."""
    for _ in range(500):
        common.check_cancel()
        time.sleep(0.01)
    raise AssertionError("не остановили")


def test_cancel_queued_job_returns_it_and_worker_skips(env):
    _, ids = env
    client = TestClient(web.app)
    job_id = _upload(client, ids)
    assert client.post(f"/api/jobs/{job_id}/start").json()["status"] == "queued"

    r = client.post(f"/api/jobs/{job_id}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "uploaded"
    web._run_job(web.Q.get_nowait())  # старая запись в очереди
    assert web.JOBS[job_id]["status"] == "uploaded" and web.JOBS[job_id]["started"] is None


def test_cancel_running_job_then_start_again(env, monkeypatch):
    _, ids = env
    client = TestClient(web.app)
    job_id = _upload(client, ids)
    client.post(f"/api/jobs/{job_id}/start")
    web.Q.get_nowait()
    monkeypatch.setattr(web, "transcribe_video", _wait_for_cancel)

    th = _run_in_thread(job_id)
    r = client.post(f"/api/jobs/{job_id}/cancel")
    assert r.status_code == 200 and r.json()["cancelling"] is True and r.json()["stage"] == "Останавливаю..."
    th.join(5)

    job = client.get("/api/jobs").json()[0]
    assert job["status"] == "uploaded" and job["stage"] == web.STOPPED_STAGE and "cancelling" not in job
    assert web.CANCEL == {}
    assert "Обработка остановлена" in client.get(f"/api/jobs/{job_id}/log").text
    # второй запуск идёт как обычно
    monkeypatch.setattr(web, "transcribe_video", lambda video, cfg, log: video)
    assert client.post(f"/api/jobs/{job_id}/start").status_code == 200
    web._run_job(web.Q.get_nowait())
    assert web.JOBS[job_id]["status"] == "done"


def test_cancel_only_for_active_jobs(env):
    _, ids = env
    client = TestClient(web.app)
    job_id = _upload(client, ids)
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 409
    assert client.post("/api/jobs/nope/cancel").status_code == 404


def test_cancelled_link_keeps_url_and_login_in_memory_only(env, monkeypatch):
    tmp_path, ids = env
    import mts_link as M

    client = TestClient(web.app)
    job_id = client.post("/api/mts-link", json={"url": LINK, "mode": "video", "session_id": "s3cr3t"}).json()["id"]
    ids.append(job_id)
    client.post(f"/api/jobs/{job_id}/start")
    web.Q.get_nowait()
    monkeypatch.setattr(M, "download_recording", lambda *a, **k: _wait_for_cancel())

    th = _run_in_thread(job_id)
    client.post(f"/api/jobs/{job_id}/cancel")
    th.join(5)

    job = web.JOBS[job_id]
    assert job["status"] == "uploaded" and job["source_url"] == LINK and job["session_id"] == "s3cr3t"
    saved = (tmp_path / "jobs.json").read_text(encoding="utf-8")
    assert "s3cr3t" not in saved and json.loads(saved)[0]["status"] == "uploaded"
    assert "s3cr3t" not in client.get("/api/jobs").text


def test_stop_without_anything_to_restart_is_error(env, monkeypatch):
    _, ids = env
    client = TestClient(web.app)
    job_id = _upload(client, ids)
    client.post(f"/api/jobs/{job_id}/start")
    web.Q.get_nowait()

    def gone(video, cfg, log):
        video.unlink()
        _wait_for_cancel()
    monkeypatch.setattr(web, "transcribe_video", gone)
    th = _run_in_thread(job_id)
    client.post(f"/api/jobs/{job_id}/cancel")
    th.join(5)
    assert web.JOBS[job_id]["status"] == "error" and web.JOBS[job_id]["error"] == "Остановлено"


def test_ui_has_stop_button_and_single_poll_loop():
    html = (web.BASE / "web" / "index.html").read_text(encoding="utf-8")
    assert "/cancel" in html and "data-stop" in html
    assert "setInterval(refresh" not in html  # цепочки опроса множились и душили лог


def test_vad_segments_stops_on_cancel(tmp_path):
    pytest.importorskip("torch")
    pytest.importorskip("silero_vad")
    import numpy as np
    import soundfile as sf
    import audio

    wav = tmp_path / "Учеба" / "пара.wav"
    wav.parent.mkdir()
    sf.write(str(wav), np.zeros(16000 * 5, dtype="float32"), 16000)
    assert audio.vad_segments(wav) == []
    stop = threading.Event()
    stop.set()
    with common.cancel_scope(stop), pytest.raises(common.Cancelled):
        audio.vad_segments(wav)
