"""One source-URL rule for every Zing ingestion boundary."""

from __future__ import annotations

import pytest

from myzing import urls

HOSTILE_SOURCE_URLS = [
    "",
    "http://",
    "https:// host.example/x",
    "http://host.example\\..\\secret",
    "https:///missing-host",
    "https://host.example:abc/x",
    "file:///tmp/video.mp4",
    "ftp://host.example/video.mp4",
    "C:/video.mp4",
]

VALID_SOURCE_URLS = [
    "http://host.example/video",
    "https://host.example/video?q=1#part",
    "http://host.example:8080/video",
    "http://[::1]:61234/video",
]


@pytest.mark.parametrize("value", HOSTILE_SOURCE_URLS)
def test_hostile_source_urls_are_rejected(value: str) -> None:
    assert urls.is_http_url(value) is False


@pytest.mark.parametrize("value", VALID_SOURCE_URLS)
def test_absolute_http_source_urls_are_accepted(value: str) -> None:
    assert urls.is_http_url(value) is True
