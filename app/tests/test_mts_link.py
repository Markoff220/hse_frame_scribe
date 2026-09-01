import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

from mts_link import parse_share_url, screen_share_urls


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
