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


# -- SG-2: durable delivery's failure paths (silent loss is the defect) ------

def _valid_response(submitted=1, accepted=1, duplicates=0, rejected=None):
    return {
        "ok": True,
        "contract": "uoink.engagement.ingest",
        "version": 1,
        "data": {
            "submitted": submitted,
            "accepted": accepted,
            "duplicates": duplicates,
            "rejected": rejected if rejected is not None else [],
        },
    }


def _serve(monkeypatch, payload, status=200):
    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    body = json.dumps(payload).encode("utf-8") if not isinstance(payload, bytes) else payload
    monkeypatch.setattr(
        engagement.urllib.request, "urlopen",
        lambda *a, **k: Resp(body),
    )


@pytest.mark.parametrize("payload,expect", [
    ("not an object", "not a JSON object"),
    ({"ok": True, "contract": "wrong", "version": 1, "data": {}}, "contract version 1"),
    ({"ok": True, "contract": "uoink.engagement.ingest", "version": 2, "data": {}},
     "contract version 1"),
], ids=["nondict", "wrong-contract", "wrong-version"])
def test_nonconformant_envelopes_are_named_contract_mismatch(payload, expect):
    with pytest.raises(engagement._DeliveryError) as e:
        engagement._validate_response(payload, status=200, event_id="evt-1")
    assert expect in str(e.value.message)
    assert e.value.code == "contract_mismatch"


@pytest.mark.parametrize("data,expect", [
    ({"submitted": 1}, "accounting is nonconformant"),
    ({"submitted": -1, "accepted": 0, "duplicates": 0, "rejected": []}, "counts"),
    ({"submitted": True, "accepted": 0, "duplicates": 0, "rejected": []}, "counts"),
    ({"submitted": 1, "accepted": 1, "duplicates": 0, "rejected": "no"}, "rejections"),
    ({"submitted": 5, "accepted": 1, "duplicates": 0, "rejected": []}, "inconsistent"),
], ids=["missing-keys", "negative", "bool-as-int", "rejected-type", "sums-wrong"])
def test_accounting_that_does_not_add_up_is_refused(data, expect):
    """The accounting IS the receipt: submitted must equal accepted +
    duplicates + rejected, or the peer is claiming something it cannot
    support and the event must not be marked delivered."""
    payload = {
        "ok": True, "contract": "uoink.engagement.ingest", "version": 1,
        "data": data,
    }
    with pytest.raises(engagement._DeliveryError) as e:
        engagement._validate_response(payload, status=200, event_id="evt-1")
    assert expect in str(e.value.message)


def test_malformed_rejection_entry_is_refused():
    payload = _valid_response(submitted=1, accepted=0, rejected=[{"code": "x"}])
    with pytest.raises(engagement._DeliveryError) as e:
        engagement._validate_response(payload, status=200, event_id="evt-1")
    assert "rejection is nonconformant" in str(e.value.message)






def test_invalid_uoink_url_never_attempts_delivery(monkeypatch, zing_workspace):
    monkeypatch.setenv(suite_peer_env := "UOINK_URL", "http://evil.example.com:80")
    monkeypatch.setattr(
        engagement.urllib.request, "urlopen",
        lambda *a, **k: pytest.fail("must not deliver to a non-loopback URL"),
    )
    receipt = engagement.record_opened("uoink://item/x", "ab" * 32)
    # REJECTED, not spooled — and that distinction is the module's whole
    # promise: "uncertain delivery is spooled; permanent rejection remains
    # durably visible". A bad URL cannot become good by waiting, so
    # spooling it would be a queue that pretends a retry might work. My
    # first draft asserted "spooled"; the code was right and I was wrong.
    assert receipt["state"] == "rejected"


def test_unreadable_spool_is_a_named_storage_error(zing_workspace, monkeypatch):
    """Storage trouble must be its own named error — never silently an
    empty spool, which would look like 'nothing was ever recorded'."""
    def boom(*a, **k):
        raise OSError("permission denied")

    monkeypatch.setattr(engagement.Path, "read_text", boom)
    with pytest.raises(engagement.EngagementStorageError, match="unreadable"):
        engagement._read_state()


def test_spool_with_an_unsupported_shape_is_refused(zing_workspace):
    path = engagement._state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pending": "not a map"}), encoding="utf-8")
    with pytest.raises(engagement.EngagementStorageError, match="unsupported shape"):
        engagement._read_state()


# -- SG-2: the delivery seam, actually reached ---------------------------------


class _Seam:
    """The HTTP transport, instrumented — and it refuses to go unused."""

    def __init__(self) -> None:
        self.calls = 0
        self._handler = None

    def serve(self, handler) -> None:
        self._handler = handler

    def __call__(self, request, timeout=0):
        self.calls += 1
        assert self._handler is not None, "seam called before serve()"
        return self._handler(request, timeout)


@pytest.fixture
def delivery_seam(monkeypatch, zing_workspace):
    """Deliver for real: credential configured, transport counted, and
    teardown fails the test if the transport was never reached.

    This guards a CLASS of vacuous test, not one instance. Two tests here
    asserted ``receipt["state"] == "spooled"`` with no credential set, so
    record_opened spooled as *unconfigured* and never reached the network
    at all — both passed against a mutant with the timeout handler and the
    response size cap deleted. A seam that was never called cannot have
    tested delivery.
    """
    monkeypatch.setenv("UOINK_TOKEN", "local-token")
    seam = _Seam()
    monkeypatch.setattr(engagement.urllib.request, "urlopen", seam)
    yield seam
    assert seam.calls > 0, (
        "this test never reached the transport, so it proves nothing about "
        "delivery — drive the seam, or do not take this fixture"
    )


def _spool_entry(item_ref: str, sha: str = SHA256):
    """(pending, rejection) for one event — where the error CODE lives.

    The receipt carries counts only, so a test that asserts on the receipt
    alone cannot tell two different failures apart.
    """
    event_id = engagement._event_id(item_ref, sha)
    state = engagement._read_state()
    return (
        state["pending"].get(event_id, {}),
        state["rejections"].get(event_id, {}),
    )


def _flood() -> bytes:
    return (
        b'{"ok": true, "pad": "'
        + b"x" * (engagement._MAX_RESPONSE_BYTES + 10)
        + b'"}'
    )


def test_timeout_and_unavailable_are_distinct_and_retryable(delivery_seam):
    """Both spool — but under DIFFERENT codes.

    The previous version asserted only ``state == "spooled"`` for both,
    which cannot tell them apart, and never reached the transport.
    """
    for error, expected in (
        (TimeoutError("slow"), "timeout"),
        (urllib.error.URLError("down"), "unavailable"),
    ):
        def raise_it(request, timeout=0, _e=error):
            raise _e

        item = f"uoink://item/{expected}"
        delivery_seam.serve(raise_it)
        receipt = engagement.record_opened(item, SHA256)

        # Uncertain delivery spools: never claims success, never raises.
        assert receipt["state"] == "spooled"
        pending, _ = _spool_entry(item)
        assert pending["last_error_code"] == expected


def test_oversized_200_is_refused_by_size_and_durably_rejected(delivery_seam):
    """Refused before JSON parsing (the lease-cap doctrine), and because a
    200 is not a server-side fault the refusal is DURABLE.

    The old test asserted "spooled" here; against a real transport that is
    wrong, which is what a test that never delivers cannot notice.
    """
    delivery_seam.serve(lambda request, timeout=0: FakeResponse(_flood()))
    receipt = engagement.record_opened(ITEM_REF, SHA256)

    assert receipt["state"] == "rejected"
    _, rejection = _spool_entry(ITEM_REF)
    assert rejection["code"] == "response_too_large"


def test_oversized_500_spools_because_the_fault_is_the_peers(delivery_seam):
    """The control for the test above: identical oversized body, 5xx
    status. Retryability keys off the status, so this one spools."""

    def flood(request, timeout=0):
        raise urllib.error.HTTPError(
            request.full_url, 500, "too much", {}, io.BytesIO(_flood()))

    delivery_seam.serve(flood)
    receipt = engagement.record_opened(ITEM_REF, SHA256)

    assert receipt["state"] == "spooled"
    pending, _ = _spool_entry(ITEM_REF)
    assert pending["last_error_code"] == "response_too_large"


def test_unparseable_body_is_named_never_guessed_at(delivery_seam):
    delivery_seam.serve(
        lambda request, timeout=0: FakeResponse(b"<html>not json</html>"))
    receipt = engagement.record_opened(ITEM_REF, SHA256)

    assert receipt["state"] == "rejected"
    _, rejection = _spool_entry(ITEM_REF)
    assert rejection["code"] == "contract_mismatch"


def test_malformed_error_envelope_is_contract_drift(delivery_seam):
    """A peer that answers with a wrongly-typed error is drift, not an
    error Zing pretends to understand."""
    body = json.dumps({
        "ok": False,
        "contract": "uoink.engagement.ingest",
        "version": 1,
        "error": {"code": "x", "message": 123, "retryable": "no"},
    }).encode("utf-8")
    delivery_seam.serve(lambda request, timeout=0: FakeResponse(body))
    receipt = engagement.record_opened(ITEM_REF, SHA256)

    assert receipt["state"] == "rejected"
    _, rejection = _spool_entry(ITEM_REF)
    assert rejection["code"] == "contract_mismatch"


def test_settled_rejection_is_never_re_delivered(zing_workspace, monkeypatch):
    """A durable rejection is final: replaying the same event answers from
    the spool without touching the network.

    Deliberately not using delivery_seam — the POINT is that the second
    call reaches no transport, which that fixture would flag.
    """
    monkeypatch.setenv("UOINK_TOKEN", "local-token")
    calls = {"n": 0}

    def reject(request, timeout=0):
        calls["n"] += 1
        return FakeResponse(b"<html>not json</html>")

    monkeypatch.setattr(engagement.urllib.request, "urlopen", reject)

    first = engagement.record_opened(ITEM_REF, SHA256)
    assert first["state"] == "rejected"
    assert calls["n"] == 1

    second = engagement.record_opened(ITEM_REF, SHA256)
    assert second["state"] == "rejected"
    assert second["rejected"] == 1
    assert calls["n"] == 1, "a settled rejection must not be re-delivered"


def test_corrupt_pending_event_is_named_not_delivered(
    zing_workspace, monkeypatch
):
    """A spool entry whose event lost keys is a storage fault, reported as
    one — never posted as-is, never silently rebuilt around."""
    monkeypatch.setenv("UOINK_TOKEN", "local-token")
    event_id = engagement._event_id(ITEM_REF, SHA256)
    state = engagement._read_state()
    state["pending"][event_id] = {
        "event": {"event_id": event_id},  # missing every other required key
        "attempts": 0,
        "last_error_code": "",
    }
    engagement._write_state(state)

    def never(request, timeout=0):
        raise AssertionError("a nonconformant event must not be delivered")

    monkeypatch.setattr(engagement.urllib.request, "urlopen", never)
    with pytest.raises(engagement.EngagementStorageError):
        engagement.record_opened(ITEM_REF, SHA256)


def test_uncommittable_spool_is_a_named_storage_error(
    zing_workspace, monkeypatch
):
    """If the spool cannot be committed, say so — never report an event as
    recorded when it was not."""

    def refuse(src, dst):
        raise OSError("no space left on device")

    monkeypatch.setattr(engagement.os, "replace", refuse)
    with pytest.raises(engagement.EngagementStorageError) as caught:
        engagement._write_state(engagement._empty_state())
    assert "commit" in str(caught.value)


def test_briefly_locked_spool_is_retried_not_failed(
    zing_workspace, monkeypatch
):
    """Windows: a scanner or indexer can hold the file for a moment, and
    os.replace raises PermissionError. The commit retries rather than
    losing the event — this is the one platform-specific durability rule
    in the spool, and it was previously unexercised."""
    attempts = {"n": 0}
    real_replace = engagement.os.replace

    def flaky(src, dst):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise PermissionError("locked by another process")
        return real_replace(src, dst)

    monkeypatch.setattr(engagement.os, "replace", flaky)
    # Built by the module, not by hand: _read_state demands an exact key
    # set including "version", so a hand-rolled dict round-trips into an
    # "unsupported shape" error that looks like a code defect and is not.
    engagement._write_state(engagement._empty_state())

    assert attempts["n"] == 3, "a transient lock must be retried, not fatal"
    assert engagement._read_state()["pending"] == {}


def test_permanently_locked_spool_gives_up_and_says_so(
    zing_workspace, monkeypatch
):
    """The retry is BOUNDED. A file locked forever ends in a named storage
    error — never an unbounded loop, and never a silent success that
    reports an event as spooled when nothing was written."""
    monkeypatch.setattr(engagement.time, "sleep", lambda seconds: None)

    def always_locked(src, dst):
        raise PermissionError("held open")

    monkeypatch.setattr(engagement.os, "replace", always_locked)
    with pytest.raises(engagement.EngagementStorageError) as caught:
        engagement._write_state(engagement._empty_state())
    assert "commit" in str(caught.value)


def test_permanent_rejection_in_the_response_settles_durably(delivery_seam):
    """A non-retryable rejection carried in an otherwise valid response
    moves the event out of pending and into rejections — the counterpart
    to test_retryable_rejection_remains_spooled."""
    body = _valid_response(accepted=0, rejected=[{
        "event_id": engagement._event_id(ITEM_REF, SHA256),
        "code": "unknown_item",
        "message": "no such item",
        "retryable": False,
    }])
    delivery_seam.serve(
        lambda request, timeout=0: FakeResponse(
            json.dumps(body).encode("utf-8")))

    receipt = engagement.record_opened(ITEM_REF, SHA256)

    assert receipt["state"] == "rejected"
    pending, rejection = _spool_entry(ITEM_REF)
    assert pending == {}, "a settled event must not stay pending"
    assert rejection["code"] == "unknown_item"
    assert engagement.status() == {
        "pending": 0, "receipts": 0, "rejections": 1}
