"""Загрузка MP4 демонстрации экрана из публичной записи МТС Линк."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import urlparse

from common import ROOT


_SHARE_URL_RE = re.compile(
    r"^https?://my\.mts-link\.ru/j/\d+/\d+/record-new/(?P<record_id>\d+)/(?P<token>[^/?#]+)",
    re.IGNORECASE,
)


def parse_share_url(url: str) -> tuple[str, str]:
    """Возвращает ID записи и access-token из публичной ссылки МТС Линк."""
    match = _SHARE_URL_RE.match(url.strip())
    if not match:
        raise ValueError("Нужна публичная ссылка МТС Линк формата .../record-new/<id>/<token>")
    return match.group("record_id"), match.group("token")


def screen_share_urls(record: dict) -> list[str]:
    """Находит прямые MP4 только для потоков с демонстрацией экрана."""
    found: list[str] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            stream = value.get("stream")
            url = value.get("url")
            if isinstance(stream, dict) and "screensharing" in stream and isinstance(url, str):
                if url.startswith("https://") and url.lower().split("?", 1)[0].endswith(".mp4"):
                    found.append(url)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(record)
    return list(dict.fromkeys(found))


def download_screen_share(share_url: str, log: logging.Logger | None = None) -> list[Path]:
    """Скачивает доступные screen-share MP4 в runtime/tmp и возвращает их пути.

    Работает только с публичной ссылкой, access-token которой МТС Линк принимает
    для выдачи метаданных записи. Несколько MP4 означают отдельные screen-share
    сегменты и намеренно не склеиваются.
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
    urls = screen_share_urls(response.json())
    if not urls:
        raise RuntimeError("В записи не найдена доступная демонстрация экрана")

    destination = ROOT / "runtime" / "tmp" / "mts_link" / record_id
    destination.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for number, media_url in enumerate(urls, 1):
        host = urlparse(media_url).hostname or ""
        if not host.endswith(".webinar.ru"):
            raise RuntimeError(f"Неожиданный хост медиафайла: {host}")
        suffix = "" if len(urls) == 1 else f"_{number:02d}"
        output = destination / f"screenshare{suffix}.mp4"
        if output.exists() and output.stat().st_size > 0:
            paths.append(output)
            continue

        if log:
            log.info("Скачивание демонстрации экрана %d/%d...", number, len(urls))
        temporary = output.with_suffix(".part")
        with requests.get(media_url, stream=True, timeout=(10, 120)) as media:
            media.raise_for_status()
            with temporary.open("wb") as file:
                for chunk in media.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        file.write(chunk)
        temporary.replace(output)
        paths.append(output)
    return paths
