"""Zing-owned durable delivery of Uoink ``opened`` engagement events.

The study result stays primary. Before Zing reports that it accepted a
verified kept-media handoff, this module either obtains an accounted Uoink
receipt or persists the exact event in Zing's workspace. Uncertain delivery
is ``spooled``; permanent rejection remains durably visible.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from myzing import storage, suite_peer

_STATE_VERSION = 1
_MAX_RESPONSE_BYTES = 1024 * 1024
_TIMEOUT = 5.0
_LOCK = threading.RLock()
_TOP_KEYS = {"ok", "contract", "version", "data"}
_ERROR_TOP_KEYS = {"ok", "contract", "version", "error"}
_DATA_KEYS = {"submitted", "accepted", "duplicates", "rejected"}
_ERROR_KEYS = {"code", "message", "retryable"}
_EVENT_KEYS = {
    "event_id",
    "item_ref",
    "event_type",
    "source_product",
    "occurred_at",
}


class EngagementStorageError(RuntimeError):
    """The local durability boundary could not be read or committed."""


class _DeliveryError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def _state_path() -> Path:
    return storage.workspace_root() / "engagement.json"


def _empty_state() -> dict[str, Any]:
    return {
        "version": _STATE_VERSION,
        "pending": {},
        "receipts": {},
        "rejections": {},
    }


def _read_state() -> dict[str, Any]:
    path = _state_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _empty_state()
    except OSError as error:
        raise EngagementStorageError(
            "Zing's engagement spool is unreadable") from error
    try:
        state = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EngagementStorageError(
            "Zing's engagement spool is not valid JSON") from error
    if (
        not isinstance(state, dict)
        or set(state) != {
            "version", "pending", "receipts", "rejections"}
        or state.get("version") != _STATE_VERSION
        or not all(
            isinstance(state.get(key), dict)
            for key in ("pending", "receipts", "rejections")
        )
    ):
        raise EngagementStorageError(
            "Zing's engagement spool has an unsupported shape")
    return state


def _write_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=".engagement-",
        suffix=".json",
        dir=path.parent,
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(
                state,
                stream,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(50):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 49:
                    raise
                time.sleep(0.002)
    except OSError as error:
        Path(temporary).unlink(missing_ok=True)
        raise EngagementStorageError(
            "Zing could not commit its engagement spool") from error


def _event_id(item_ref: str, sha256: str) -> str:
    identity = f"zing:opened:{item_ref}:{sha256}"
    return "zing-" + str(uuid.uuid5(uuid.NAMESPACE_URL, identity))


def _receipt(
    event_id: str,
    state: str,
    *,
    accepted: int = 0,
    duplicates: int = 0,
    spooled: int = 0,
    rejected: int = 0,
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "state": state,
        "submitted": 1,
        "accepted": accepted,
        "duplicates": duplicates,
        "spooled": spooled,
        "rejected": rejected,
    }


def _validate_response(
    payload: Any,
    *,
    status: int,
    event_id: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _DeliveryError(
            "contract_mismatch",
            "Uoink engagement response is not a JSON object",
            retryable=status >= 500,
        )
    expected = _TOP_KEYS if payload.get("ok") is True else _ERROR_TOP_KEYS
    if set(payload) != expected:
        raise _DeliveryError(
            "contract_mismatch",
            "Uoink engagement response has unexpected fields",
            retryable=status >= 500,
        )
    if (
        payload.get("contract") != "uoink.engagement.ingest"
        or payload.get("version") != 1
    ):
        raise _DeliveryError(
            "contract_mismatch",
            "Uoink engagement response is not contract version 1",
            retryable=False,
        )
    if payload.get("ok") is not True:
        error = payload.get("error")
        if (
            not isinstance(error, dict)
            or set(error) != _ERROR_KEYS
            or not isinstance(error.get("code"), str)
            or not isinstance(error.get("message"), str)
            or not isinstance(error.get("retryable"), bool)
        ):
            raise _DeliveryError(
                "contract_mismatch",
                "Uoink engagement error is nonconformant",
                retryable=status >= 500,
            )
        raise _DeliveryError(
            error["code"],
            error["message"],
            retryable=error["retryable"],
        )
    data = payload.get("data")
    if not isinstance(data, dict) or set(data) != _DATA_KEYS:
        raise _DeliveryError(
            "contract_mismatch",
            "Uoink engagement accounting is nonconformant",
            retryable=False,
        )
    for key in ("submitted", "accepted", "duplicates"):
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _DeliveryError(
                "contract_mismatch",
                "Uoink engagement counts are nonconformant",
                retryable=False,
            )
    rejected = data.get("rejected")
    if not isinstance(rejected, list):
        raise _DeliveryError(
            "contract_mismatch",
            "Uoink engagement rejections are nonconformant",
            retryable=False,
        )
    for item in rejected:
        if (
            not isinstance(item, dict)
            or set(item) != {"event_id", "code", "message", "retryable"}
            or item.get("event_id") != event_id
            or not isinstance(item.get("code"), str)
            or not isinstance(item.get("message"), str)
            or not isinstance(item.get("retryable"), bool)
        ):
            raise _DeliveryError(
                "contract_mismatch",
                "Uoink engagement rejection is nonconformant",
                retryable=False,
            )
    if (
        data["submitted"] != 1
        or data["submitted"]
        != data["accepted"] + data["duplicates"] + len(rejected)
    ):
        raise _DeliveryError(
            "contract_mismatch",
            "Uoink engagement accounting is inconsistent",
            retryable=False,
        )
    return data


def _post(event: dict[str, Any]) -> dict[str, Any]:
    try:
        base = suite_peer.resolve_uoink_base().base
    except suite_peer.UoinkResolutionError as error:
        raise _DeliveryError(
            error.code,
            str(error),
            retryable=error.retryable,
        ) from error
    token = os.environ.get(
        suite_peer.UOINK_TOKEN_ENV, "").strip()
    if not token:
        raise _DeliveryError(
            "unconfigured",
            "No Uoink credential is configured",
            retryable=True,
        )
    body = json.dumps({
        "contract": "uoink.engagement.ingest",
        "version": 1,
        "events": [event],
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        base.rstrip("/") + "/api/engagement/v1/events",
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Uoink-Token": token,
        },
        method="POST",
    )
    status = 200
    try:
        with urllib.request.urlopen(
            request, timeout=_TIMEOUT) as response:
            status = int(response.status)
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        status = int(error.code)
        raw = error.read(_MAX_RESPONSE_BYTES + 1)
    except (TimeoutError, socket.timeout) as error:
        raise _DeliveryError(
            "timeout",
            "Uoink engagement delivery timed out",
            retryable=True,
        ) from error
    except (urllib.error.URLError, OSError) as error:
        raise _DeliveryError(
            "unavailable",
            "Uoink engagement delivery is unavailable",
            retryable=True,
        ) from error
    if len(raw) > _MAX_RESPONSE_BYTES:
        raise _DeliveryError(
            "response_too_large",
            "Uoink engagement response exceeded the safety limit",
            retryable=status >= 500,
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _DeliveryError(
            "contract_mismatch",
            "Uoink engagement response is not valid JSON",
            retryable=status >= 500,
        ) from error
    return _validate_response(
        payload,
        status=status,
        event_id=str(event["event_id"]),
    )


def record_opened(item_ref: str, sha256: str) -> dict[str, Any]:
    """Account for one verified kept-media handoff and return its receipt."""
    event_id = _event_id(item_ref, sha256)
    with _LOCK:
        state = _read_state()
        completed = state["receipts"].get(event_id)
        if isinstance(completed, dict):
            return _receipt(
                event_id,
                "accepted",
                accepted=int(completed.get("accepted") or 0),
                duplicates=int(completed.get("duplicates") or 0),
            )
        rejection = state["rejections"].get(event_id)
        if isinstance(rejection, dict):
            return _receipt(event_id, "rejected", rejected=1)
        pending = state["pending"].get(event_id)
        if not isinstance(pending, dict):
            event = {
                "event_id": event_id,
                "item_ref": item_ref,
                "event_type": "opened",
                "source_product": "zing",
                "occurred_at": _now(),
            }
            pending = {
                "event": event,
                "attempts": 0,
                "last_error_code": "",
            }
            state["pending"][event_id] = pending
            _write_state(state)
        event = pending.get("event")
        if not isinstance(event, dict) or set(event) != _EVENT_KEYS:
            raise EngagementStorageError(
                "Zing's pending engagement event is nonconformant")
        try:
            result = _post(event)
        except _DeliveryError as error:
            pending["attempts"] = int(
                pending.get("attempts") or 0) + 1
            pending["last_error_code"] = error.code
            if error.retryable:
                state["pending"][event_id] = pending
                _write_state(state)
                return _receipt(
                    event_id, "spooled", spooled=1)
            state["pending"].pop(event_id, None)
            state["rejections"][event_id] = {
                "code": error.code,
                "message": error.message,
                "retryable": False,
                "rejected_at": _now(),
            }
            _write_state(state)
            return _receipt(
                event_id, "rejected", rejected=1)
        rejected = result["rejected"]
        if rejected:
            rejection = rejected[0]
            if rejection["retryable"]:
                pending["attempts"] = int(
                    pending.get("attempts") or 0) + 1
                pending["last_error_code"] = rejection["code"]
                state["pending"][event_id] = pending
                _write_state(state)
                return _receipt(
                    event_id, "spooled", spooled=1)
            state["pending"].pop(event_id, None)
            state["rejections"][event_id] = {
                **rejection,
                "rejected_at": _now(),
            }
            _write_state(state)
            return _receipt(
                event_id, "rejected", rejected=1)
        state["pending"].pop(event_id, None)
        state["receipts"][event_id] = {
            "accepted": result["accepted"],
            "duplicates": result["duplicates"],
            "recorded_at": _now(),
        }
        _write_state(state)
        return _receipt(
            event_id,
            "accepted",
            accepted=result["accepted"],
            duplicates=result["duplicates"],
        )


def status() -> dict[str, int]:
    """Path-free durable counts for ``zing_status`` and doctor surfaces."""
    with _LOCK:
        state = _read_state()
    return {
        "pending": len(state["pending"]),
        "receipts": len(state["receipts"]),
        "rejections": len(state["rejections"]),
    }
