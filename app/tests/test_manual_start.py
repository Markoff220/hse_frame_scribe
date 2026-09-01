from pathlib import Path

from fastapi.testclient import TestClient

import web


def test_uploaded_job_waits_until_manual_start(tmp_path, monkeypatch):
    job_id = "manual01"
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"test")
    monkeypatch.setattr(web, "Q", __import__("queue").Queue())
    monkeypatch.setattr(web, "JOBS_FILE", tmp_path / "jobs.json")
    web.JOBS[job_id] = {
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

    client = TestClient(web.app)
    response = client.post(f"/api/jobs/{job_id}/start")

    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert web.Q.get_nowait() == job_id


def test_mts_link_job_is_queued_without_exposing_source_url(tmp_path, monkeypatch):
    monkeypatch.setattr(web, "Q", __import__("queue").Queue())
    monkeypatch.setattr(web, "JOBS_FILE", tmp_path / "jobs.json")
    monkeypatch.setattr(web, "JOBS", {})

    response = TestClient(web.app).post(
        "/api/mts-link",
        json={"url": "https://my.mts-link.ru/j/1/2/record-new/123456/token-value"},
    )

    assert response.status_code == 200
    assert response.json()["kind"] == "mts_download"
    assert "source_url" not in response.json()
