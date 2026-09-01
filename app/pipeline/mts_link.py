"""Загрузка MP4 демонстрации экрана из публичной записи МТС Линк."""
from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from common import ROOT


_SHARE_URL_RE = re.compile(
    r"^https?://my\.mts-link\.ru/j/\d+/\d+/record-new/(?P<record_id>\d+)/(?P<token>[^/?#]+)",
    re.IGNORECASE,
)


class MediaAsset:
    def __init__(self, url: str, time: float, kind: str, source_id: str | None = None):
        self.url = url
        self.time = time
        self.kind = kind
        self.source_id = source_id


def parse_share_url(url: str) -> tuple[str, str]:
    """Возвращает ID записи и access-token из публичной ссылки МТС Линк."""
    match = _SHARE_URL_RE.match(url.strip())
    if not match:
        raise ValueError("Нужна публичная ссылка МТС Линк формата .../record-new/<id>/<token>")
    return match.group("record_id"), match.group("token")


def recording_sources(record: dict) -> tuple[MediaAsset, list[MediaAsset]]:
    """Возвращает один screen-share поток и аудиопотоки конференции."""
    audio_source_ids: set[str] = set()
    for event in record.get("eventLogs", []):
        if event.get("module") not in {"conference.add", "conference.update"}:
            continue
        data = event.get("data", {})
        if isinstance(data, dict) and data.get("hasAudio") and data.get("id") is not None:
            audio_source_ids.add(str(data["id"]))

    found: list[MediaAsset] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            stream = value.get("stream")
            url = value.get("url")
            if isinstance(stream, dict) and isinstance(url, str):
                if url.startswith("https://") and url.lower().split("?", 1)[0].endswith(".mp4"):
                    if isinstance(stream.get("screensharing"), dict):
                        found.append(MediaAsset(url, float(value.get("time", 0)), "screen"))
                    elif isinstance(stream.get("conference"), dict):
                        source_id = stream["conference"].get("id")
                        if source_id is not None and str(source_id) in audio_source_ids:
                            found.append(MediaAsset(url, float(value.get("time", 0)), "audio", str(source_id)))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(record)
    unique: dict[str, MediaAsset] = {asset.url: asset for asset in found}
    screens = [asset for asset in unique.values() if asset.kind == "screen"]
    if len(screens) != 1:
        raise RuntimeError(f"Ожидалась одна демонстрация экрана, найдено: {len(screens)}")
    return screens[0], sorted(
        (asset for asset in unique.values() if asset.kind == "audio"), key=lambda asset: asset.time
    )


def screen_share_urls(record: dict) -> list[str]:
    """Совместимый помощник: прямой MP4 демонстрации экрана."""
    screen, _ = recording_sources(record)
    return [screen.url]


def _download(url: str, output: Path, label: str, log: logging.Logger | None) -> Path:
    import requests

    host = urlparse(url).hostname or ""
    if not host.endswith(".webinar.ru"):
        raise RuntimeError(f"Неожиданный хост медиафайла: {host}")
    if output.exists() and output.stat().st_size > 0:
        return output

    if log:
        log.info("Скачивание %s...", label)
    temporary = output.with_suffix(".part")
    with requests.get(url, stream=True, timeout=(10, 120)) as media:
        media.raise_for_status()
        total = int(media.headers.get("content-length", 0))
        received = 0
        next_progress = 0.1
        with temporary.open("wb") as file:
            for chunk in media.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                file.write(chunk)
                received += len(chunk)
                if log and total and received / total >= next_progress:
                    log.info("  %s: %d%%", label, min(100, int(received * 100 / total)))
                    next_progress += 0.1
    temporary.replace(output)
    return output


def _has_audio(path: Path) -> bool:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(result.stdout.strip())


def _duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(result.stdout.strip())


def download_recording(share_url: str, log: logging.Logger | None = None) -> Path:
    """Скачивает демонстрацию экрана и смешивает звук конференции в один MP4.

    Работает только с публичной ссылкой, access-token которой МТС Линк принимает
    для выдачи метаданных записи.
    """
    record_id, token = parse_share_url(share_url)
    import requests

    api_url = f"https://gw.mts-link.ru/api/eventsessions/{record_id}/record"
    response = requests.get(
        api_url,
        params={"withoutCuts": "false", "recordAccessToken": token},
        timeout=30,
    )
    response.raise_for_status()
    screen, audio_assets = recording_sources(response.json())
    if not audio_assets:
        raise RuntimeError("В записи не найдены аудиопотоки конференции")

    destination = ROOT / "runtime" / "tmp" / "mts_link" / record_id
    destination.mkdir(parents=True, exist_ok=True)
    legacy_screen = destination / "screenshare.mp4"
    screen_file = legacy_screen if legacy_screen.exists() else destination / "screen.mp4"
    screen_file = _download(screen.url, screen_file, "демонстрации экрана", log)

    audio_files: list[tuple[MediaAsset, Path]] = []
    for number, asset in enumerate(audio_assets, 1):
        audio_file = _download(asset.url, destination / f"audio_{number:02d}.mp4", f"аудиодорожки {number}/{len(audio_assets)}", log)
        if _has_audio(audio_file):
            audio_files.append((asset, audio_file))
    if not audio_files:
        raise RuntimeError("Скачанные конференц-потоки не содержат аудио")

    output = destination / "recording.mp4"
    duration = _duration(screen_file)
    command = ["ffmpeg", "-y", "-i", str(screen_file)]
    for asset, audio_file in audio_files:
        command += ["-itsoffset", f"{asset.time - screen.time:.3f}", "-i", str(audio_file)]
    inputs = "".join(f"[{index}:a]" for index in range(1, len(audio_files) + 1))
    command += [
        "-filter_complex", f"{inputs}amix=inputs={len(audio_files)}:duration=longest:normalize=0,apad[audio]",
        "-map", "0:v:0", "-map", "[audio]", "-t", f"{duration:.3f}",
        "-c:v", "copy", "-c:a", "aac", "-movflags", "+faststart", str(output),
    ]
    if log:
        log.info("Сборка MP4: экран + %d аудиодорожек...", len(audio_files))
    subprocess.run(command, check=True)
    return output
