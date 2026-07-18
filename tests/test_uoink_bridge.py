"""Uoink bridge: offline tests — every network call is mocked."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from myzing import storage, uoink_bridge
from myzing.schemas import Breakdown, VideoMeta

SLUG = "tiktok-42"


@pytest.fixture
def studied(zing_workspace):
    b = Breakdown(
        meta=VideoMeta(
            source_url="https://www.tiktok.com/@a/video/42",
            platform="tiktok",
            title="How to price",
        )
    )
    storage.save_breakdown(b, slug=SLUG, markdown="# Breakdown\n\ncontent\n")
    return b


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_push_without_markdown_is_actionable(zing_workspace):
    result = uoink_bridge.push_breakdown("ghost")
    assert result["ok"] is False
    assert "study the video first" in result["error"]


def test_push_success_sends_note_with_token(studied, monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["token"] = request.get_header("X-uoink-token")
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(
            json.dumps(
                {"ok": True, "video_id": "v1", "slug": "note-zing", "title": "t"}
            ).encode()
        )

    monkeypatch.setenv(uoink_bridge.UOINK_TOKEN_ENV, "secret-token")
    monkeypatch.setattr(uoink_bridge.urllib.request, "urlopen", fake_urlopen)
    result = uoink_bridge.push_breakdown(SLUG)
    assert result["ok"] is True
    assert result["uoink_id"] == "v1"
    assert captured["url"].endswith("/notes")
    assert captured["token"] == "secret-token"
    assert captured["body"]["author"] == "Zing"
    assert captured["body"]["title"] == "Zing breakdown: How to price"
    assert "content" in captured["body"]["text"]


def test_push_auth_rejection_names_the_token(studied, monkeypatch):
    def forbidden(request, timeout=0):
        raise urllib.error.HTTPError(request.full_url, 403, "forbidden", {}, None)

    monkeypatch.setattr(uoink_bridge.urllib.request, "urlopen", forbidden)
    result = uoink_bridge.push_breakdown(SLUG)
    assert result["ok"] is False
    assert "UOINK_TOKEN" in result["error"] and "token.txt" in result["error"]


def test_push_helper_down_is_calm(studied, monkeypatch):
    def down(request, timeout=0):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(uoink_bridge.urllib.request, "urlopen", down)
    result = uoink_bridge.push_breakdown(SLUG)
    assert result["ok"] is False
    assert "works fine without it" in result["error"]


def test_push_declined_by_uoink_reports_its_error(studied, monkeypatch):
    def declined(request, timeout=0):
        return FakeResponse(
            json.dumps({"ok": False, "error": "note text required"}).encode()
        )

    monkeypatch.setattr(uoink_bridge.urllib.request, "urlopen", declined)
    result = uoink_bridge.push_breakdown(SLUG)
    assert result["ok"] is False
    assert "note text required" in result["error"]


@pytest.mark.parametrize(
    "bad", ["../../escape", "..\\..\\escape", "/etc/passwd", "C:\\Windows\\escape"]
)
def test_push_rejects_traversal_slug_as_data(zing_workspace, bad, monkeypatch):
    """F-02: a traversal slug gets the envelope, not a traceback or a read."""
    def no_network(*a, **k):
        raise AssertionError("a traversal slug must never reach the network")

    monkeypatch.setattr(uoink_bridge.urllib.request, "urlopen", no_network)
    result = uoink_bridge.push_breakdown(bad)
    assert result["ok"] is False
    assert "slug" in result["error"]


def test_url_override(monkeypatch):
    monkeypatch.setenv(uoink_bridge.UOINK_URL_ENV, "http://127.0.0.1:9999")
    assert uoink_bridge.helper_url() == "http://127.0.0.1:9999"
