from pathlib import Path

from fastapi.testclient import TestClient

import web


def test_uploaded_job_waits_until_manual_start(tmp_path, monkeypatch):
    job_id = "manual01"
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"test")
    monkeypatch.setattr(web, "Q", __import__("queue").Queue())
    monkeypatch.setattr(web, "JOBS_FILE", tmp_path / "jobs.json")
    monkeypatch.setattr(web, "JOBS", {job_id: {
        "id": job_id,
        "name": "lesson.mp4",
        "path": str(video),
        "status": "uploaded",
        "stage": "Готово к запуску",
        "created": "2026-09-01 18:00:00",
        "started": None,
        "finished": None,
        "out": None,
        "error": None,
    }})
    monkeypatch.setattr(web, "MODEL_SETTINGS", {
        "asr_model": "v3_e2e_rnnt",
        "vlm_model": "qwen2.5vl:3b",
        "llm_model": "qwen2.5:3b",
    })
    monkeypatch.setattr(web, "_missing_model_roles", lambda settings: [])

    client = TestClient(web.app)
    response = client.post(f"/api/jobs/{job_id}/start")

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert response.json()["models"] == web.MODEL_SETTINGS
    assert web.Q.get_nowait() == job_id


def test_uploaded_job_can_be_deleted_with_source_file(tmp_path, monkeypatch):
    job_id = "delete01"
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"test")
    monkeypatch.setattr(web, "JOBS_FILE", tmp_path / "jobs.json")
    monkeypatch.setattr(web, "JOBS", {
        job_id: {
            "id": job_id,
            "name": "lesson.mp4",
            "path": str(video),
            "status": "uploaded",
            "stage": "Готово к запуску",
            "created": "2026-09-01 18:00:00",
            "started": None,
            "finished": None,
            "out": None,
            "error": None,
        }
    })

    response = TestClient(web.app).delete(f"/api/jobs/{job_id}")

    assert response.status_code == 200
    assert job_id not in web.JOBS
    assert not video.exists()


def test_audio_job_starts_without_models(tmp_path, monkeypatch):
    job_id = "audio001"
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"test")
    monkeypatch.setattr(web, "Q", __import__("queue").Queue())
    monkeypatch.setattr(web, "JOBS_FILE", tmp_path / "jobs.json")
    monkeypatch.setattr(web, "JOBS", {job_id: {
        "id": job_id,
        "name": "lesson.mp4",
        "path": str(video),
        "mode": "audio",
        "status": "uploaded",
        "stage": "Готово к запуску",
        "created": "2026-09-01 18:00:00",
        "started": None,
        "finished": None,
        "out": None,
        "error": None,
    }})
    monkeypatch.setattr(web, "_missing_model_roles", lambda settings: (_ for _ in ()).throw(AssertionError()))

    response = TestClient(web.app).post(f"/api/jobs/{job_id}/start")

    assert response.status_code == 200
    assert "models" not in response.json()
    assert web.Q.get_nowait() == job_id
