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


from conftest import FakeHTTPResponse as FakeResponse


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


# -- SG-2: envelope-validation and fallback edges -----------------------------

def test_resolve_http_error_with_unparseable_body(monkeypatch):
    monkeypatch.setenv(uoink_bridge.UOINK_TOKEN_ENV, "tok")

    def boom(request, timeout=0):
        raise urllib.error.HTTPError(
            request.full_url, 500, "boom", {}, io.BytesIO(b"<html>")
        )

    monkeypatch.setattr(uoink_bridge.urllib.request, "urlopen", boom)
    result = uoink_bridge.resolve_kept_media(REF)
    assert result["ok"] is False
    assert "HTTP 500" in result["error"]


def test_resolve_non_object_body_is_nonconformant(monkeypatch):
    monkeypatch.setenv(uoink_bridge.UOINK_TOKEN_ENV, "tok")
    serve(monkeypatch, ["an", "array"])
    result = uoink_bridge.resolve_kept_media(REF)
    assert "not contract-conformant" in result["error"]


def test_resolve_error_envelope_with_extra_keys_is_drift(monkeypatch):
    monkeypatch.setenv(uoink_bridge.UOINK_TOKEN_ENV, "tok")
    serve(monkeypatch, {
        "ok": False, "contract": "uoink.media.handoff", "version": 1,
        "operation": "resolve", "extra": True,
        "error": {"code": "not_found", "message": "x", "retryable": False},
    })
    result = uoink_bridge.resolve_kept_media(REF)
    assert "not contract-conformant" in result["error"]


def test_resolve_data_with_wrong_keys_is_drift(monkeypatch):
    monkeypatch.setenv(uoink_bridge.UOINK_TOKEN_ENV, "tok")
    body = handoff_body()
    del body["data"]["provenance"]
    serve(monkeypatch, body)
    result = uoink_bridge.resolve_kept_media(REF)
    assert "data keys" in result["error"]


def test_resolve_unknown_state_is_drift(monkeypatch):
    monkeypatch.setenv(uoink_bridge.UOINK_TOKEN_ENV, "tok")
    serve(monkeypatch, handoff_body(state="sideways", media=None))
    result = uoink_bridge.resolve_kept_media(REF)
    assert "unknown state" in result["error"]


def test_resolve_available_with_wrong_media_keys_is_drift(monkeypatch):
    monkeypatch.setenv(uoink_bridge.UOINK_TOKEN_ENV, "tok")
    body = handoff_body()
    del body["data"]["media"]["sha256"]
    serve(monkeypatch, body)
    result = uoink_bridge.resolve_kept_media(REF)
    assert "media keys" in result["error"]


def test_push_title_fallback_when_breakdown_unloadable(studied, monkeypatch):
    def broken_load(slug):
        raise ValueError("corrupt json")

    monkeypatch.setattr(uoink_bridge.storage, "load_breakdown", broken_load)
    captured = {}

    def fake_urlopen(request, timeout=0):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(json.dumps({"ok": True}).encode())

    monkeypatch.setattr(uoink_bridge.urllib.request, "urlopen", fake_urlopen)
    result = uoink_bridge.push_breakdown(SLUG)
    assert result["ok"] is True
    assert captured["body"]["title"] == f"Zing breakdown: {SLUG}"


def test_push_http_error_names_the_status(studied, monkeypatch):
    def teapot(request, timeout=0):
        raise urllib.error.HTTPError(request.full_url, 500, "boom", {}, None)

    monkeypatch.setattr(uoink_bridge.urllib.request, "urlopen", teapot)
    result = uoink_bridge.push_breakdown(SLUG)
    assert result["ok"] is False
    assert "HTTP 500" in result["error"]


# -- SG-3 / P3-3 residue: token guidance is installed-app-aware everywhere ----

def test_no_credential_error_names_the_installed_app_token_path(monkeypatch):
    """Final review P3-3 was fixed in doctor (#220) but survived here in
    three copies of the older source-checkout-only wording — the exact
    way a closed finding lives on. One TOKEN_LOCATION constant now."""
    monkeypatch.delenv(uoink_bridge.UOINK_TOKEN_ENV, raising=False)
    error = uoink_bridge.resolve_kept_media(REF)["error"]
    assert uoink_bridge.TOKEN_LOCATION in error
    assert "source checkout" in error


def test_rejected_credential_error_names_the_installed_app_token_path(monkeypatch):
    monkeypatch.setenv(uoink_bridge.UOINK_TOKEN_ENV, "bad")

    def forbidden(request, timeout=0):
        raise urllib.error.HTTPError(request.full_url, 403, "no", {}, io.BytesIO())

    monkeypatch.setattr(uoink_bridge.urllib.request, "urlopen", forbidden)
    error = uoink_bridge.resolve_kept_media(REF)["error"]
    assert uoink_bridge.TOKEN_LOCATION in error


def test_push_auth_error_names_the_installed_app_token_path(studied, monkeypatch):
    def forbidden(request, timeout=0):
        raise urllib.error.HTTPError(request.full_url, 401, "no", {}, None)

    monkeypatch.setattr(uoink_bridge.urllib.request, "urlopen", forbidden)
    error = uoink_bridge.push_breakdown(SLUG)["error"]
    assert uoink_bridge.TOKEN_LOCATION in error
    assert uoink_bridge.UOINK_TOKEN_ENV in error


def test_every_failure_envelope_has_the_house_shape(monkeypatch, zing_workspace):
    """The envelope shape is now built in one place; assert the contract
    it guarantees rather than trusting 15 hand-written literals."""
    monkeypatch.delenv(uoink_bridge.UOINK_TOKEN_ENV, raising=False)
    failures = [
        uoink_bridge.resolve_kept_media("C:/not/a/ref.mp4"),
        uoink_bridge.resolve_kept_media("uoink://item/"),
        uoink_bridge.resolve_kept_media(REF),
        uoink_bridge.push_breakdown("../../escape"),
        uoink_bridge.push_breakdown("tiktok-nothing-here"),
    ]
    for envelope in failures:
        assert envelope["ok"] is False
        assert isinstance(envelope["error"], str) and envelope["error"]
        assert "\n" not in envelope["error"]  # one actionable line, not a dump


def test_token_location_names_all_three_contract_locations():
    """INTEGRATION-CONTRACT §3.2 lists Windows, macOS, and development
    locations. The first version of this constant listed only Windows +
    checkout — consolidating duplicated wording (#280) made the guidance
    CONSISTENT without making it COMPLETE, and a macOS user would have
    been handed a Windows path. Found by reviewing Codex's CX-4 edit to
    CONNECT.md, whose doc text was more complete than my code."""
    loc = uoink_bridge.TOKEN_LOCATION
    assert "%LOCALAPPDATA%" in loc and "Windows" in loc
    assert "~/Library/Application Support/Uoink/token.txt" in loc
    assert "server.py" in loc


def test_doctor_and_bridge_share_one_token_location(monkeypatch):
    """Two surfaces, one string — the #280 lesson enforced rather than
    trusted."""
    from myzing import doctor, suite_peer

    doctor._peer_cache.clear()
    monkeypatch.setattr(
        suite_peer, "probe_uoink",
        lambda: ({"ok": True, "contract": "ryan.suite.peer", "version": 1,
                  "peer": "uoink", "state": "unconfigured", "capabilities": []},
                 "manifest read: uoink 3.6.0"),
    )
    check = doctor.check_uoink()
    doctor._peer_cache.clear()
    assert uoink_bridge.TOKEN_LOCATION in check.fix


# -- SG-3: the contract rules, exercised directly ----------------------------

@pytest.mark.parametrize("mutate,expect", [
    (lambda b: b.__setitem__("contract", "wrong"), "contract="),
    (lambda b: b.__setitem__("version", 2), "version="),
    (lambda b: b.__setitem__("operation", "read"), "envelope keys"),
    (lambda b: b.__setitem__("extra", 1), "envelope keys"),
    (lambda b: b["data"].pop("provenance"), "data keys"),
    (lambda b: b["data"].__setitem__("state", "sideways"), "unknown state"),
    (lambda b: b["data"].__setitem__("source_url", "file:///c/x.mp4"), "source_url"),
    (lambda b: b["data"]["media"].pop("sha256"), "media keys"),
], ids=["contract", "version", "operation", "extra-key", "data-keys",
        "state", "file-url", "media-keys"])
def test_handoff_defect_names_each_contract_violation(mutate, expect):
    """The extraction's whole point: §6.1's rules are now exercisable
    WITHOUT a fake HTTP layer standing between the test and the rule."""
    body = handoff_body()
    mutate(body)
    defect = uoink_bridge.handoff_defect(body)
    assert defect is not None and expect in defect


def test_handoff_defect_accepts_every_legal_state():
    assert uoink_bridge.handoff_defect(handoff_body()) is None
    for state in ("not_kept", "missing"):
        assert uoink_bridge.handoff_defect(
            handoff_body(state=state, media=None)
        ) is None
    assert uoink_bridge.handoff_defect(
        handoff_body(state="not_kept", media=None, source_url=None)
    ) is None


def test_handoff_defect_rejects_non_objects():
    for bad in (None, [], "text", 7):
        assert uoink_bridge.handoff_defect(bad) is not None
