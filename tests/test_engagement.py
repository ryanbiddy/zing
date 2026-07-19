"""Contract and durability gates for Zing's opened-event delivery."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import pytest

from myzing import engagement, mcp_server, storage
from myzing.schemas import Breakdown, VideoMeta

ITEM_REF = "uoink://item/short-123"
SHA256 = "ab" * 32


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def accepted_response(*, accepted: int = 1, duplicates: int = 0) -> dict:
    return {
        "ok": True,
        "contract": "uoink.engagement.ingest",
        "version": 1,
        "data": {
            "submitted": 1,
            "accepted": accepted,
            "duplicates": duplicates,
            "rejected": [],
        },
    }


def test_opened_event_is_exact_and_accepted(
    zing_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}
    monkeypatch.setenv("UOINK_TOKEN", "local-token")

    def answer(request, timeout=0):
        captured["url"] = request.full_url
        captured["token"] = request.get_header("X-uoink-token")
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(
            json.dumps(accepted_response()).encode("utf-8"))

    monkeypatch.setattr(
        engagement.urllib.request, "urlopen", answer)

    receipt = engagement.record_opened(ITEM_REF, SHA256)

    assert receipt == {
        "event_id": engagement._event_id(ITEM_REF, SHA256),
        "state": "accepted",
        "submitted": 1,
        "accepted": 1,
        "duplicates": 0,
        "spooled": 0,
        "rejected": 0,
    }
    assert captured == {
        "url": (
            "http://127.0.0.1:5179/api/engagement/v1/events"
        ),
        "token": "local-token",
        "body": {
            "contract": "uoink.engagement.ingest",
            "version": 1,
            "events": [{
                "event_id": receipt["event_id"],
                "item_ref": ITEM_REF,
                "event_type": "opened",
                "source_product": "zing",
                "occurred_at": captured["body"]["events"][0][
                    "occurred_at"],
            }],
        },
    }
    assert captured["body"]["events"][0]["occurred_at"].endswith("Z")
    assert engagement.status() == {
        "pending": 0,
        "receipts": 1,
        "rejections": 0,
    }


def test_unconfigured_event_is_spooled_then_retried(
    zing_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("UOINK_TOKEN", raising=False)
    calls = {"count": 0}
    monkeypatch.setattr(
        engagement.urllib.request,
        "urlopen",
        lambda *args, **kwargs: calls.__setitem__(
            "count", calls["count"] + 1),
    )

    first = engagement.record_opened(ITEM_REF, SHA256)

    assert first["state"] == "spooled"
    assert first["spooled"] == 1
    assert calls["count"] == 0
    assert engagement.status()["pending"] == 1

    monkeypatch.setenv("UOINK_TOKEN", "local-token")

    def answer(request, timeout=0):
        calls["count"] += 1
        return FakeResponse(
            json.dumps(accepted_response()).encode("utf-8"))

    monkeypatch.setattr(
        engagement.urllib.request, "urlopen", answer)
    second = engagement.record_opened(ITEM_REF, SHA256)

    assert second["state"] == "accepted"
    assert calls["count"] == 1
    assert engagement.status()["pending"] == 0


def test_accepted_event_is_locally_idempotent(
    zing_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UOINK_TOKEN", "local-token")
    calls = {"count": 0}

    def answer(request, timeout=0):
        calls["count"] += 1
        return FakeResponse(
            json.dumps(accepted_response()).encode("utf-8"))

    monkeypatch.setattr(
        engagement.urllib.request, "urlopen", answer)

    first = engagement.record_opened(ITEM_REF, SHA256)
    second = engagement.record_opened(ITEM_REF, SHA256)

    assert second == first
    assert calls["count"] == 1


def test_retryable_rejection_remains_spooled(
    zing_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UOINK_TOKEN", "local-token")
    body = {
        "ok": True,
        "contract": "uoink.engagement.ingest",
        "version": 1,
        "data": {
            "submitted": 1,
            "accepted": 0,
            "duplicates": 0,
            "rejected": [{
                "event_id": engagement._event_id(
                    ITEM_REF, SHA256),
                "code": "busy",
                "message": "retry later",
                "retryable": True,
            }],
        },
    }
    monkeypatch.setattr(
        engagement.urllib.request,
        "urlopen",
        lambda *args, **kwargs: FakeResponse(
            json.dumps(body).encode("utf-8")),
    )

    receipt = engagement.record_opened(ITEM_REF, SHA256)

    assert receipt["state"] == "spooled"
    assert engagement.status() == {
        "pending": 1,
        "receipts": 0,
        "rejections": 0,
    }


def test_auth_failure_is_a_durable_rejection(
    zing_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UOINK_TOKEN", "wrong-token")
    body = {
        "ok": False,
        "contract": "uoink.engagement.ingest",
        "version": 1,
        "error": {
            "code": "authentication_failed",
            "message": "bad credential",
            "retryable": False,
        },
    }

    def reject(request, timeout=0):
        raise urllib.error.HTTPError(
            request.full_url,
            403,
            "forbidden",
            {},
            io.BytesIO(json.dumps(body).encode("utf-8")),
        )

    monkeypatch.setattr(
        engagement.urllib.request, "urlopen", reject)

    receipt = engagement.record_opened(ITEM_REF, SHA256)

    assert receipt["state"] == "rejected"
    assert receipt["rejected"] == 1
    assert engagement.status() == {
        "pending": 0,
        "receipts": 0,
        "rejections": 1,
    }


def test_contract_drift_is_not_silently_retried(
    zing_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UOINK_TOKEN", "local-token")
    drifted = accepted_response()
    drifted["unexpected"] = True
    monkeypatch.setattr(
        engagement.urllib.request,
        "urlopen",
        lambda *args, **kwargs: FakeResponse(
            json.dumps(drifted).encode("utf-8")),
    )

    receipt = engagement.record_opened(ITEM_REF, SHA256)

    assert receipt["state"] == "rejected"
    state = json.loads(
        (zing_workspace / "engagement.json").read_text(
            encoding="utf-8"))
    rejection = state["rejections"][receipt["event_id"]]
    assert rejection["code"] == "contract_mismatch"
    assert rejection["retryable"] is False


def test_corrupt_spool_is_never_overwritten(
    zing_workspace: Path,
) -> None:
    path = zing_workspace / "engagement.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{broken", encoding="utf-8")

    with pytest.raises(
        engagement.EngagementStorageError,
        match="not valid JSON",
    ):
        engagement.record_opened(ITEM_REF, SHA256)

    assert path.read_text(encoding="utf-8") == "{broken"


def test_study_emits_only_after_verified_kept_media(
    zing_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    expected_receipt = {
        "event_id": "zing-opened-short-123",
        "state": "spooled",
        "submitted": 1,
        "accepted": 0,
        "duplicates": 0,
        "spooled": 1,
        "rejected": 0,
    }
    monkeypatch.setattr(
        engagement,
        "record_opened",
        lambda item_ref, sha256: (
            calls.append((item_ref, sha256)) or expected_receipt
        ),
    )

    def measured(source, **kwargs):
        return Breakdown(
            meta=VideoMeta(
                source_url=source,
                platform="youtube",
                duration=4,
            ),
            provenance={
                "source_handoff": {
                    "contract": "uoink.media.handoff",
                    "version": 1,
                    "source_ref": ITEM_REF,
                    "acquisition": "kept_media",
                    "refetch": False,
                    "sha256": SHA256,
                },
            },
        )

    mcp_server._run_study(
        measured,
        "https://example.test/short/123",
        "example-test-123",
        zing_workspace,
        kept_media="kept.mp4",
        handoff={"source_ref": ITEM_REF, "sha256": SHA256},
    )

    saved = storage.load_breakdown("example-test-123")
    assert calls == [(ITEM_REF, SHA256)]
    assert saved.provenance["engagement"] == expected_receipt
    assert storage.read_status("example-test-123")["state"] == "done"


def test_refetched_study_emits_no_opened_event(
    zing_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        engagement,
        "record_opened",
        lambda *args: pytest.fail(
            "a refetched source is not a kept-media open"),
    )

    def measured(source, **kwargs):
        return Breakdown(
            meta=VideoMeta(
                source_url=source,
                platform="youtube",
                duration=4,
            ),
            provenance={
                "source_handoff": {
                    "contract": "uoink.media.handoff",
                    "version": 1,
                    "source_ref": ITEM_REF,
                    "acquisition": "source_refetch",
                    "refetch": True,
                    "reason": "integrity_mismatch",
                },
            },
        )

    mcp_server._run_study(
        measured,
        "https://example.test/short/123",
        "example-test-123",
        zing_workspace,
        kept_media="kept.mp4",
        handoff={"source_ref": ITEM_REF, "sha256": SHA256},
    )

    assert storage.read_status("example-test-123")["state"] == "done"
