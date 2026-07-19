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


# -- resolve_kept_media (INTEGRATION-CONTRACT v1 §6.1) ------------------------

REF = "uoink://item/short-123"


def handoff_body(state="available", source_url="https://example.test/short/123",
                 media="default", **overrides):
    if media == "default":
        media = (
            {
                "path": "C:/Uoink/Shorts/short-123/video.mp4",
                "media_type": "video/mp4",
                "byte_length": 1234567,
                "sha256": "ab" * 32,
            }
            if state == "available"
            else None
        )
    body = {
        "ok": True,
        "contract": "uoink.media.handoff",
        "version": 1,
        "operation": "resolve",
        "data": {
            "item_ref": REF,
            "state": state,
            "source_url": source_url,
            "media": media,
            "provenance": {
                "kind": "uoink_sidecar",
                "sidecar_schema_version": 2,
                "field": "media_file",
            },
        },
    }
    body.update(overrides)
    return body


def serve(monkeypatch, body, capture=None):
    def fake_urlopen(request, timeout=0):
        if capture is not None:
            capture["url"] = request.full_url
            capture["token"] = request.get_header("X-uoink-token")
        return FakeResponse(json.dumps(body).encode("utf-8"))

    monkeypatch.setattr(uoink_bridge.urllib.request, "urlopen", fake_urlopen)


def test_resolve_rejects_paths_and_junk_refs(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(
        uoink_bridge.urllib.request, "urlopen",
        lambda *a, **k: calls.__setitem__("n", calls["n"] + 1),
    )
    for bad in ("C:\video.mp4", "/tmp/x.mp4", "writer://script/1", "uoink://item/"):
        result = uoink_bridge.resolve_kept_media(bad)
        assert result["ok"] is False
    assert calls["n"] == 0  # reference validation never touches the network


def test_resolve_without_token_is_unconfigured_and_offline(monkeypatch):
    monkeypatch.delenv(uoink_bridge.UOINK_TOKEN_ENV, raising=False)
    calls = {"n": 0}
    monkeypatch.setattr(
        uoink_bridge.urllib.request, "urlopen",
        lambda *a, **k: calls.__setitem__("n", calls["n"] + 1),
    )
    result = uoink_bridge.resolve_kept_media(REF)
    assert result["ok"] is False
    assert "UOINK_TOKEN" in result["error"]
    assert "never reads uoink's token file" in result["error"]
    assert calls["n"] == 0  # §3.3: unconfigured, not an empty-token attempt


def test_resolve_available_returns_contract_data(monkeypatch):
    monkeypatch.setenv(uoink_bridge.UOINK_TOKEN_ENV, "tok")
    captured = {}
    serve(monkeypatch, handoff_body(), captured)
    result = uoink_bridge.resolve_kept_media(REF)
    assert result["ok"] is True
    assert result["data"]["state"] == "available"
    assert result["data"]["media"]["sha256"] == "ab" * 32
    assert "/api/corpus/v1/items/short-123/kept-media" in captured["url"]
    assert captured["token"] == "tok"


def test_resolve_percent_encodes_the_item_id(monkeypatch):
    monkeypatch.setenv(uoink_bridge.UOINK_TOKEN_ENV, "tok")
    captured = {}
    serve(monkeypatch, handoff_body(), captured)
    uoink_bridge.resolve_kept_media("uoink://item/a b/c")
    assert "/items/a%20b%2Fc/kept-media" in captured["url"]


def test_resolve_not_kept_has_null_media(monkeypatch):
    monkeypatch.setenv(uoink_bridge.UOINK_TOKEN_ENV, "tok")
    serve(monkeypatch, handoff_body(state="not_kept", media=None))
    result = uoink_bridge.resolve_kept_media(REF)
    assert result["ok"] is True
    assert result["data"]["state"] == "not_kept"
    assert result["data"]["media"] is None


@pytest.mark.parametrize("mutate", [
    {"contract": "uoink.corpus.read"},
    {"version": 2},
    {"operation": "read"},
    {"extra_key": True},
])
def test_resolve_names_envelope_drift(monkeypatch, mutate):
    monkeypatch.setenv(uoink_bridge.UOINK_TOKEN_ENV, "tok")
    serve(monkeypatch, handoff_body(**mutate))
    result = uoink_bridge.resolve_kept_media(REF)
    assert result["ok"] is False
    assert "not contract-conformant" in result["error"]
    assert "drift" in result["error"]


def test_resolve_rejects_media_on_not_kept_state(monkeypatch):
    monkeypatch.setenv(uoink_bridge.UOINK_TOKEN_ENV, "tok")
    body = handoff_body(state="missing", media=None)
    body["data"]["media"] = {"path": "sneaky.mp4", "media_type": "video/mp4",
                             "byte_length": 1, "sha256": "ab" * 32}
    serve(monkeypatch, body)
    result = uoink_bridge.resolve_kept_media(REF)
    assert result["ok"] is False and "not contract-conformant" in result["error"]


def test_resolve_maps_contract_error_envelope(monkeypatch):
    monkeypatch.setenv(uoink_bridge.UOINK_TOKEN_ENV, "tok")
    serve(monkeypatch, {
        "ok": False,
        "contract": "uoink.media.handoff",
        "version": 1,
        "operation": "resolve",
        "error": {"code": "not_found", "message": "corpus item not found",
                  "retryable": False},
    })
    result = uoink_bridge.resolve_kept_media(REF)
    assert result["ok"] is False
    assert result["code"] == "not_found"
    assert "corpus item not found" in result["error"]


def test_resolve_auth_rejection_names_the_token(monkeypatch):
    monkeypatch.setenv(uoink_bridge.UOINK_TOKEN_ENV, "bad")

    def forbidden(request, timeout=0):
        raise urllib.error.HTTPError(request.full_url, 401, "no", {}, io.BytesIO())

    monkeypatch.setattr(uoink_bridge.urllib.request, "urlopen", forbidden)
    result = uoink_bridge.resolve_kept_media(REF)
    assert result["ok"] is False and "UOINK_TOKEN" in result["error"]


def test_resolve_helper_down_is_calm(monkeypatch):
    monkeypatch.setenv(uoink_bridge.UOINK_TOKEN_ENV, "tok")

    def down(request, timeout=0):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(uoink_bridge.urllib.request, "urlopen", down)
    result = uoink_bridge.resolve_kept_media(REF)
    assert result["ok"] is False
    assert "is Uoink running" in result["error"]


@pytest.mark.parametrize("bad", [
    "file:///C:/x.mp4", "C:/kept/video.mp4", "/tmp/x.mp4", "ftp://h/x",
])
def test_resolve_rejects_non_http_source_url(monkeypatch, bad):
    """FF-8 (final review, contract §5): source_url is null-or-HTTP(S) —
    a file:// or filesystem-shaped value would turn 'refetch from the
    source' into a local file read."""
    monkeypatch.setenv(uoink_bridge.UOINK_TOKEN_ENV, "tok")
    serve(monkeypatch, handoff_body(source_url=bad))
    result = uoink_bridge.resolve_kept_media(REF)
    assert result["ok"] is False
    assert "source_url" in result["error"]


def test_resolve_null_source_url_is_contract_legal(monkeypatch):
    monkeypatch.setenv(uoink_bridge.UOINK_TOKEN_ENV, "tok")
    serve(monkeypatch, handoff_body(state="not_kept", media=None, source_url=None))
    result = uoink_bridge.resolve_kept_media(REF)
    assert result["ok"] is True
    assert result["data"]["source_url"] is None
