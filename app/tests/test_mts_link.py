import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

from mts_link import parse_share_url, recording_sources, screen_share_urls


def test_parse_mts_link_share_url():
    record_id, token = parse_share_url(
        "https://my.mts-link.ru/j/1/2/record-new/123456/token-value?ignored=true"
    )

    assert record_id == "123456"
    assert token == "token-value"


def test_parse_mts_link_rejects_unrelated_url():
    with pytest.raises(ValueError):
        parse_share_url("https://example.com/video.mp4")


def test_screen_share_urls_ignores_conference_and_deduplicates():
    screen_share = "https://events-storage.webinar.ru/api-storage/files/a.mp4"
    record = {
        "eventLogs": [
            {"data": {"url": "https://events-storage.webinar.ru/api-storage/files/camera.mp4", "stream": {"conference": {}}}},
            {"data": {"url": screen_share, "stream": {"screensharing": {}}}},
            {"snapshot": {"data": {"url": screen_share, "stream": {"screensharing": {}}}}},
        ]
    }

    assert screen_share_urls(record) == [screen_share]


def test_recording_sources_selects_only_audio_enabled_conference_streams():
    screen = "https://events-storage.webinar.ru/api-storage/files/screen.mp4"
    audio = "https://events-storage.webinar.ru/api-storage/files/audio.mp4"
    silent = "https://events-storage.webinar.ru/api-storage/files/silent.mp4"
    record = {
        "eventLogs": [
            {"module": "conference.add", "data": {"id": "speaker", "hasAudio": True}},
            {"module": "conference.add", "data": {"id": "silent", "hasAudio": False}},
            {"module": "mediasession.add", "data": {"url": screen, "time": 10, "stream": {"screensharing": {}}}},
            {"module": "mediasession.add", "data": {"url": audio, "time": 0, "stream": {"conference": {"id": "speaker"}}}},
            {"module": "mediasession.add", "data": {"url": silent, "time": 0, "stream": {"conference": {"id": "silent"}}}},
        ]
    }

    screen_asset, audio_assets = recording_sources(record)

    assert screen_asset.url == screen
    assert [asset.url for asset in audio_assets] == [audio]
