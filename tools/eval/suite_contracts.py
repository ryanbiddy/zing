"""Exact, offline conformance checks for the ratified suite v1 contracts."""

from __future__ import annotations

import base64
import copy
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import quote, unquote, urlsplit


CONTRACT_FIXTURE_VERSION = 1
HERE = Path(__file__).resolve().parent
DEFAULT_SUITE_FIXTURES = HERE / "fixtures" / "suite_v1"
_MANIFEST_PATH = DEFAULT_SUITE_FIXTURES / "manifest.json"
_SHOT_LIST_LIMIT = 2 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9-]*\.[a-z0-9.-]+/[1-9][0-9]*$")
_WRITER_REF_RE = re.compile(r"^writer://script/([1-9][0-9]*)$")
_ZING_REF_RE = re.compile(
    r"^zing://breakdown/([a-z0-9][a-z0-9-]{0,99})$"
)
_ASCII_EVENT_RE = re.compile(r"^[\x20-\x7e]{1,128}$")
_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")

_SERVICE_SPECS = {
    "uoink": {
        "name": "Uoink",
        "default_port": 5179,
        "capabilities": (
            "uoink.corpus.read/1",
            "uoink.engagement.ingest/1",
            "uoink.media.handoff/1",
        ),
        "checks": ("core", "index", "corpus_paths"),
        "mcp_name": "uoink",
    },
    "writer": {
        "name": "Writer",
        "default_port": 5181,
        "capabilities": (
            "writer.api/1",
            "writer.shot-list/1",
        ),
        "checks": ("core", "database"),
        "mcp_name": "writer",
    },
}
_PEER_ERROR_RETRYABLE = {
    "invalid_configuration": False,
    "invalid_lease": False,
    "stale_lease": True,
    "wrong_service": False,
    "authentication_failed": False,
    "contract_mismatch": False,
    "peer_unhealthy": True,
    "timeout": True,
    "unavailable": True,
}
_MEDIA_ERROR_CODES = frozenset(
    {
        "invalid_request",
        "not_found",
        "unavailable",
        "provider_nonconformant",
    }
)
_IMPORT_ERROR_CODES = frozenset(
    {
        "invalid_file",
        "unsupported_version",
        "target_not_found",
        "conflict",
        "storage_unavailable",
    }
)
_MEDIA_TYPES = frozenset(
    {
        "video/mp4",
        "video/quicktime",
        "video/webm",
        "video/x-matroska",
    }
)
_SHOT_LIST_HEADINGS = (
    "## Hook",
    "## Beats",
    "## Script",
    "## CTA",
    "## Shots",
    "## Credits",
)
_MISSING = object()


def _issue(
    issues: list[dict[str, Any]],
    path: str,
    kind: str,
    **details: Any,
) -> None:
    issues.append({"path": path, "kind": kind, **details})


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _exact_mapping(
    value: Any,
    path: str,
    keys: Sequence[str],
    issues: list[dict[str, Any]],
) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        _issue(
            issues,
            path,
            "wrong_type",
            expected="object",
            actual=type(value).__name__,
        )
        return None
    expected = set(keys)
    actual = set(value)
    unknown = sorted(actual - expected)
    missing = sorted(expected - actual)
    if unknown:
        _issue(issues, path, "unknown_keys", keys=unknown)
    if missing:
        _issue(issues, path, "missing_keys", keys=missing)
    return value


def _expect_type(
    value: Any,
    path: str,
    expected: type | tuple[type, ...],
    issues: list[dict[str, Any]],
) -> bool:
    numeric = expected is int or (
        isinstance(expected, tuple)
        and any(item in (int, float) for item in expected)
    )
    if (numeric and isinstance(value, bool)) or not isinstance(value, expected):
        if isinstance(expected, tuple):
            name = " or ".join(item.__name__ for item in expected)
        else:
            name = expected.__name__
        _issue(
            issues,
            path,
            "wrong_type",
            expected=name,
            actual=type(value).__name__,
        )
        return False
    return True


def _expect_value(
    value: Any,
    expected: Any,
    path: str,
    issues: list[dict[str, Any]],
) -> None:
    if value != expected:
        _issue(
            issues,
            path,
            "invalid_value",
            expected=expected,
            actual=value,
        )


def _is_rfc3339(value: Any, *, utc_only: bool = False) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        return False
    return not utc_only or parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def _valid_uoink_ref(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("uoink://item/"):
        return False
    segment = value.removeprefix("uoink://item/")
    return (
        bool(segment)
        and "/" not in segment
        and quote(unquote(segment), safe="-._~") == segment
    )


def _valid_writer_ref(value: Any) -> bool:
    return isinstance(value, str) and bool(_WRITER_REF_RE.fullmatch(value))


def _valid_zing_ref(value: Any) -> bool:
    return isinstance(value, str) and bool(_ZING_REF_RE.fullmatch(value))


def _valid_http_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
    )


def _loopback_url(
    value: Any,
    path: str,
    issues: list[dict[str, Any]],
    *,
    expected_path: str | None = None,
) -> tuple[str, int] | None:
    if not isinstance(value, str):
        _issue(
            issues,
            path,
            "wrong_type",
            expected="str",
            actual=type(value).__name__,
        )
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        _issue(issues, path, "invalid_url", actual=value)
        return None
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        _issue(issues, path, "invalid_loopback_url", actual=value)
        return None
    if expected_path is not None and parsed.path != expected_path:
        _issue(
            issues,
            path,
            "invalid_url_path",
            expected=expected_path,
            actual=parsed.path,
        )
    return parsed.hostname, port


def _capability_issues(
    value: Any,
    path: str,
    issues: list[dict[str, Any]],
    *,
    expected: Sequence[str] | None = None,
    allow_empty: bool = False,
) -> None:
    if not isinstance(value, list) or any(
        not isinstance(item, str) for item in value
    ):
        _issue(issues, path, "wrong_type", expected="list[str]")
        return
    if not allow_empty and not value:
        _issue(issues, path, "empty")
    if value != sorted(value) or len(value) != len(set(value)):
        _issue(issues, path, "not_sorted_unique")
    invalid = [item for item in value if not _CAPABILITY_RE.fullmatch(item)]
    if invalid:
        _issue(issues, path, "invalid_capabilities", values=invalid)
    if expected is not None and tuple(value) != tuple(expected):
        _issue(
            issues,
            path,
            "invalid_value",
            expected=list(expected),
            actual=value,
        )


def _ui_issues(
    value: Any,
    path: str,
    issues: list[dict[str, Any]],
) -> None:
    ui = _exact_mapping(value, path, ("home", "routes"), issues)
    if ui is None:
        return
    home = ui.get("home")
    if not isinstance(home, str) or not home.startswith("/"):
        _issue(issues, f"{path}.home", "invalid_relative_path")
    routes = ui.get("routes")
    if not isinstance(routes, Mapping) or any(
        not isinstance(key, str)
        or not isinstance(route, str)
        or not route.startswith("/")
        for key, route in (
            routes.items() if isinstance(routes, Mapping) else ()
        )
    ):
        _issue(issues, f"{path}.routes", "invalid_routes")


def _service_context(
    expected_service: str | None,
    path: str,
    issues: list[dict[str, Any]],
) -> Mapping[str, Any] | None:
    spec = _SERVICE_SPECS.get(expected_service or "")
    if spec is None:
        _issue(
            issues,
            path,
            "missing_validation_context",
            expected_service=expected_service,
        )
    return spec


def _validate_runtime_lease(
    payload: Any,
    *,
    expected_service: str | None,
    live_pids: Sequence[int] | None,
    pid_is_live: Callable[[int], bool] | None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    lease = _exact_mapping(
        payload,
        "$",
        (
            "contract",
            "version",
            "service_id",
            "service_version",
            "api_version",
            "base_url",
            "health_url",
            "manifest_url",
            "capabilities",
            "ui",
            "pid",
            "started_at",
        ),
        issues,
    )
    spec = _service_context(expected_service, "$.service_id", issues)
    if lease is None:
        return issues
    _expect_value(
        lease.get("contract"),
        "ryan.suite.runtime-lease",
        "$.contract",
        issues,
    )
    _expect_value(lease.get("version"), 1, "$.version", issues)
    if expected_service is not None:
        _expect_value(
            lease.get("service_id"),
            expected_service,
            "$.service_id",
            issues,
        )
    if not isinstance(lease.get("service_version"), str):
        _issue(issues, "$.service_version", "wrong_type", expected="str")
    if not _is_int(lease.get("api_version")):
        _issue(issues, "$.api_version", "wrong_type", expected="int")
    base = _loopback_url(lease.get("base_url"), "$.base_url", issues)
    health = _loopback_url(
        lease.get("health_url"),
        "$.health_url",
        issues,
        expected_path="/api/suite/v1/health",
    )
    manifest = _loopback_url(
        lease.get("manifest_url"),
        "$.manifest_url",
        issues,
        expected_path="/.well-known/suite-service.json",
    )
    if base and health and base != health:
        _issue(issues, "$.health_url", "origin_mismatch")
    if base and manifest and base != manifest:
        _issue(issues, "$.manifest_url", "origin_mismatch")
    if spec is not None:
        _capability_issues(
            lease.get("capabilities"),
            "$.capabilities",
            issues,
            expected=spec["capabilities"],
        )
    _ui_issues(lease.get("ui"), "$.ui", issues)
    pid = lease.get("pid")
    if not _is_int(pid) or pid <= 0:
        _issue(issues, "$.pid", "invalid_pid", actual=pid)
    elif pid_is_live is not None:
        if not pid_is_live(pid):
            _issue(issues, "$.pid", "dead_pid", actual=pid)
    elif live_pids is not None:
        if pid not in live_pids:
            _issue(issues, "$.pid", "dead_pid", actual=pid)
    else:
        _issue(issues, "$.pid", "liveness_unchecked", actual=pid)
    if not _is_rfc3339(lease.get("started_at")):
        _issue(issues, "$.started_at", "invalid_rfc3339")
    return issues


def _validate_service(
    payload: Any,
    *,
    expected_service: str | None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    envelope = _exact_mapping(
        payload,
        "$",
        ("ok", "contract", "version", "service"),
        issues,
    )
    spec = _service_context(expected_service, "$.service.id", issues)
    if envelope is None:
        return issues
    _expect_value(envelope.get("ok"), True, "$.ok", issues)
    _expect_value(
        envelope.get("contract"),
        "ryan.suite.service",
        "$.contract",
        issues,
    )
    _expect_value(envelope.get("version"), 1, "$.version", issues)
    service = _exact_mapping(
        envelope.get("service"),
        "$.service",
        (
            "id",
            "name",
            "service_version",
            "api_version",
            "resident",
            "default_port",
            "health",
            "capabilities",
            "ui",
            "mcp",
        ),
        issues,
    )
    if service is None or spec is None:
        return issues
    _expect_value(
        service.get("id"),
        expected_service,
        "$.service.id",
        issues,
    )
    _expect_value(
        service.get("name"),
        spec["name"],
        "$.service.name",
        issues,
    )
    if not isinstance(service.get("service_version"), str):
        _issue(issues, "$.service.service_version", "wrong_type", expected="str")
    if not _is_int(service.get("api_version")):
        _issue(issues, "$.service.api_version", "wrong_type", expected="int")
    _expect_value(service.get("resident"), True, "$.service.resident", issues)
    _expect_value(
        service.get("default_port"),
        spec["default_port"],
        "$.service.default_port",
        issues,
    )
    health = _exact_mapping(
        service.get("health"),
        "$.service.health",
        ("contract", "version", "href"),
        issues,
    )
    if health is not None:
        _expect_value(
            health.get("contract"),
            "ryan.suite.health",
            "$.service.health.contract",
            issues,
        )
        _expect_value(
            health.get("version"),
            1,
            "$.service.health.version",
            issues,
        )
        _expect_value(
            health.get("href"),
            "/api/suite/v1/health",
            "$.service.health.href",
            issues,
        )
    _capability_issues(
        service.get("capabilities"),
        "$.service.capabilities",
        issues,
        expected=spec["capabilities"],
    )
    _ui_issues(service.get("ui"), "$.service.ui", issues)
    mcp = _exact_mapping(
        service.get("mcp"),
        "$.service.mcp",
        ("name", "transport"),
        issues,
    )
    if mcp is not None:
        _expect_value(
            mcp.get("name"),
            spec["mcp_name"],
            "$.service.mcp.name",
            issues,
        )
        _expect_value(
            mcp.get("transport"),
            "stdio",
            "$.service.mcp.transport",
            issues,
        )
    return issues


def _validate_health(
    payload: Any,
    *,
    expected_service: str | None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    health = _exact_mapping(
        payload,
        "$",
        (
            "ok",
            "contract",
            "version",
            "service_id",
            "service_version",
            "state",
            "checks",
        ),
        issues,
    )
    spec = _service_context(expected_service, "$.service_id", issues)
    if health is None:
        return issues
    _expect_value(
        health.get("contract"),
        "ryan.suite.health",
        "$.contract",
        issues,
    )
    _expect_value(health.get("version"), 1, "$.version", issues)
    if expected_service is not None:
        _expect_value(
            health.get("service_id"),
            expected_service,
            "$.service_id",
            issues,
        )
    if not isinstance(health.get("service_version"), str):
        _issue(issues, "$.service_version", "wrong_type", expected="str")
    state = health.get("state")
    if state not in {"ready", "ready_with_limits", "needs_attention"}:
        _issue(issues, "$.state", "invalid_value", actual=state)
    checks = health.get("checks")
    statuses: list[str] = []
    ids: list[str] = []
    if not isinstance(checks, list):
        _issue(issues, "$.checks", "wrong_type", expected="list")
    else:
        for index, raw_check in enumerate(checks):
            check = _exact_mapping(
                raw_check,
                f"$.checks[{index}]",
                ("id", "required", "status"),
                issues,
            )
            if check is None:
                continue
            check_id = check.get("id")
            if isinstance(check_id, str):
                ids.append(check_id)
            else:
                _issue(
                    issues,
                    f"$.checks[{index}].id",
                    "wrong_type",
                    expected="str",
                )
            _expect_value(
                check.get("required"),
                True,
                f"$.checks[{index}].required",
                issues,
            )
            status = check.get("status")
            if status not in {"ready", "busy", "degraded", "failed"}:
                _issue(
                    issues,
                    f"$.checks[{index}].status",
                    "invalid_value",
                    actual=status,
                )
            elif isinstance(status, str):
                statuses.append(status)
    if spec is not None and tuple(ids) != tuple(spec["checks"]):
        _issue(
            issues,
            "$.checks",
            "invalid_check_ids",
            expected=list(spec["checks"]),
            actual=ids,
        )
    expected_ok = not any(status == "failed" for status in statuses)
    expected_state = (
        "needs_attention"
        if not expected_ok
        else (
            "ready_with_limits"
            if any(status in {"busy", "degraded"} for status in statuses)
            else "ready"
        )
    )
    _expect_value(health.get("ok"), expected_ok, "$.ok", issues)
    _expect_value(state, expected_state, "$.state", issues)
    return issues


def _validate_peer(
    payload: Any,
    *,
    expected_peer: str | None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not isinstance(payload, Mapping):
        _issue(issues, "$", "wrong_type", expected="object")
        return issues
    state = payload.get("state")
    keys = (
        ("ok", "contract", "version", "peer", "state", "error")
        if state == "unhealthy"
        else ("ok", "contract", "version", "peer", "state", "capabilities")
    )
    peer = _exact_mapping(payload, "$", keys, issues)
    if peer is None:
        return issues
    _expect_value(
        peer.get("contract"),
        "ryan.suite.peer",
        "$.contract",
        issues,
    )
    _expect_value(peer.get("version"), 1, "$.version", issues)
    if expected_peer not in _SERVICE_SPECS:
        _issue(
            issues,
            "$.peer",
            "missing_validation_context",
            expected_peer=expected_peer,
        )
    else:
        _expect_value(peer.get("peer"), expected_peer, "$.peer", issues)
    if state not in {"available", "absent", "unconfigured", "unhealthy"}:
        _issue(issues, "$.state", "invalid_value", actual=state)
        return issues
    if state == "unhealthy":
        _expect_value(peer.get("ok"), False, "$.ok", issues)
        error = _exact_mapping(
            peer.get("error"),
            "$.error",
            ("code", "message", "retryable"),
            issues,
        )
        if error is not None:
            code = error.get("code")
            if code not in _PEER_ERROR_RETRYABLE:
                _issue(issues, "$.error.code", "invalid_value", actual=code)
            else:
                _expect_value(
                    error.get("retryable"),
                    _PEER_ERROR_RETRYABLE[code],
                    "$.error.retryable",
                    issues,
                )
            if not isinstance(error.get("message"), str):
                _issue(issues, "$.error.message", "wrong_type", expected="str")
    else:
        _expect_value(peer.get("ok"), True, "$.ok", issues)
        capabilities = peer.get("capabilities")
        if state in {"absent", "unconfigured"}:
            _expect_value(capabilities, [], "$.capabilities", issues)
        else:
            _capability_issues(
                capabilities,
                "$.capabilities",
                issues,
                allow_empty=False,
            )
    return issues


def _validate_media_handoff(payload: Any) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not isinstance(payload, Mapping):
        _issue(issues, "$", "wrong_type", expected="object")
        return issues
    ok = payload.get("ok")
    keys = (
        ("ok", "contract", "version", "operation", "data")
        if ok is True
        else ("ok", "contract", "version", "operation", "error")
    )
    envelope = _exact_mapping(payload, "$", keys, issues)
    if envelope is None:
        return issues
    _expect_value(
        envelope.get("contract"),
        "uoink.media.handoff",
        "$.contract",
        issues,
    )
    _expect_value(envelope.get("version"), 1, "$.version", issues)
    _expect_value(envelope.get("operation"), "resolve", "$.operation", issues)
    if ok is True:
        data = _exact_mapping(
            envelope.get("data"),
            "$.data",
            ("item_ref", "state", "source_url", "media", "provenance"),
            issues,
        )
        if data is None:
            return issues
        if not _valid_uoink_ref(data.get("item_ref")):
            _issue(issues, "$.data.item_ref", "invalid_reference")
        state = data.get("state")
        if state not in {"available", "not_kept", "missing"}:
            _issue(issues, "$.data.state", "invalid_value", actual=state)
        source_url = data.get("source_url")
        if source_url is not None and not _valid_http_url(source_url):
            _issue(issues, "$.data.source_url", "invalid_http_url")
        media = data.get("media")
        if state == "available":
            media_payload = _exact_mapping(
                media,
                "$.data.media",
                ("path", "media_type", "byte_length", "sha256"),
                issues,
            )
            if media_payload is not None:
                media_path = media_payload.get("path")
                if not isinstance(media_path, str) or not (
                    PureWindowsPath(media_path).is_absolute()
                    or PurePosixPath(media_path).is_absolute()
                ):
                    _issue(issues, "$.data.media.path", "not_absolute")
                if media_payload.get("media_type") not in _MEDIA_TYPES:
                    _issue(
                        issues,
                        "$.data.media.media_type",
                        "unsupported_media_type",
                    )
                byte_length = media_payload.get("byte_length")
                if not _is_int(byte_length) or byte_length < 0:
                    _issue(
                        issues,
                        "$.data.media.byte_length",
                        "invalid_value",
                        actual=byte_length,
                    )
                if not _valid_sha256(media_payload.get("sha256")):
                    _issue(issues, "$.data.media.sha256", "invalid_sha256")
        elif media is not None:
            _issue(
                issues,
                "$.data.media",
                "invalid_value",
                expected=None,
                actual=media,
            )
        provenance = _exact_mapping(
            data.get("provenance"),
            "$.data.provenance",
            ("kind", "sidecar_schema_version", "field"),
            issues,
        )
        if provenance is not None:
            _expect_value(
                provenance.get("kind"),
                "uoink_sidecar",
                "$.data.provenance.kind",
                issues,
            )
            if not _is_int(provenance.get("sidecar_schema_version")):
                _issue(
                    issues,
                    "$.data.provenance.sidecar_schema_version",
                    "wrong_type",
                    expected="int",
                )
            _expect_value(
                provenance.get("field"),
                "media_file",
                "$.data.provenance.field",
                issues,
            )
    else:
        _expect_value(ok, False, "$.ok", issues)
        error = _exact_mapping(
            envelope.get("error"),
            "$.error",
            ("code", "message", "retryable"),
            issues,
        )
        if error is not None:
            if error.get("code") not in _MEDIA_ERROR_CODES:
                _issue(
                    issues,
                    "$.error.code",
                    "invalid_value",
                    actual=error.get("code"),
                )
            if not isinstance(error.get("message"), str):
                _issue(issues, "$.error.message", "wrong_type", expected="str")
            if not isinstance(error.get("retryable"), bool):
                _issue(
                    issues,
                    "$.error.retryable",
                    "wrong_type",
                    expected="bool",
                )
    return issues


def _validate_shot_list(payload: Any) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if isinstance(payload, str):
        raw = payload.encode("utf-8")
    elif isinstance(payload, bytes):
        raw = payload
    else:
        _issue(
            issues,
            "$",
            "wrong_type",
            expected="str or bytes",
            actual=type(payload).__name__,
        )
        return issues
    if len(raw) > _SHOT_LIST_LIMIT:
        _issue(
            issues,
            "$",
            "oversized",
            maximum_bytes=_SHOT_LIST_LIMIT,
            actual_bytes=len(raw),
        )
        return issues
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        _issue(issues, "$", "non_utf8")
        return issues
    lines = text.splitlines()
    if len(lines) < 6 or lines[0] != "---" or lines[5] != "---":
        _issue(issues, "$.front_matter", "malformed")
        return issues
    front_matter_lines = lines[1:5]
    expected_keys = (
        "document_type",
        "schema_version",
        "generated_at",
        "source_script_id",
    )
    parsed: dict[str, str] = {}
    seen: list[str] = []
    for index, line in enumerate(front_matter_lines, start=1):
        if ":" not in line:
            _issue(
                issues,
                f"$.front_matter[{index}]",
                "malformed",
                actual=line,
            )
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        seen.append(key)
        if key in parsed:
            _issue(
                issues,
                f"$.front_matter[{index}]",
                "duplicate_key",
                key=key,
            )
        parsed[key] = value.strip()
    if tuple(seen) != expected_keys:
        _issue(
            issues,
            "$.front_matter",
            "invalid_key_order",
            expected=list(expected_keys),
            actual=seen,
        )
    _expect_value(
        parsed.get("document_type"),
        "writer.shot-list",
        "$.front_matter.document_type",
        issues,
    )
    _expect_value(
        parsed.get("schema_version"),
        "1",
        "$.front_matter.schema_version",
        issues,
    )
    if not _is_rfc3339(parsed.get("generated_at")):
        _issue(
            issues,
            "$.front_matter.generated_at",
            "invalid_rfc3339",
        )
    script_id = parsed.get("source_script_id", "")
    if not re.fullmatch(r"[1-9][0-9]*", script_id):
        _issue(
            issues,
            "$.front_matter.source_script_id",
            "invalid_positive_decimal",
            actual=script_id,
        )
    headings = [
        line
        for line in lines[6:]
        if line.startswith("# ") or line.startswith("## ")
    ]
    expected_headings = ("# Fixture script", *_SHOT_LIST_HEADINGS)
    if not headings or not headings[0].startswith("# "):
        _issue(issues, "$.headings", "missing_title")
    elif not headings[0].removeprefix("# ").strip():
        _issue(issues, "$.headings[0]", "empty_title")
    if len(headings) == len(expected_headings):
        normalized = ("# Fixture script", *headings[1:])
    else:
        normalized = tuple(headings)
    if normalized != expected_headings:
        _issue(
            issues,
            "$.headings",
            "invalid_heading_order",
            expected=list(expected_headings),
            actual=headings,
        )
    return issues


def _path_free_issues(value: Any, path: str = "$") -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    forbidden_keys = {
        "path",
        "input_path",
        "source_path",
        "token",
        "credential",
        "secret",
        "password",
    }
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if str(key).lower() in forbidden_keys:
                _issue(issues, child_path, "forbidden_private_key")
            issues.extend(_path_free_issues(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            issues.extend(_path_free_issues(child, f"{path}[{index}]"))
    elif isinstance(value, str) and "://" not in value and (
        _WINDOWS_ABSOLUTE_RE.match(value)
        or value.startswith("\\\\")
        or PurePosixPath(value).is_absolute()
    ):
        _issue(issues, path, "absolute_path")
    return issues


def _validate_import(payload: Any) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not isinstance(payload, Mapping):
        _issue(issues, "$", "wrong_type", expected="object")
        return issues
    ok = payload.get("ok")
    keys = (
        ("ok", "contract", "version", "data")
        if ok is True
        else ("ok", "contract", "version", "error")
    )
    envelope = _exact_mapping(payload, "$", keys, issues)
    if envelope is None:
        return issues
    _expect_value(
        envelope.get("contract"),
        "zing.shot-list.import",
        "$.contract",
        issues,
    )
    _expect_value(envelope.get("version"), 1, "$.version", issues)
    if ok is True:
        data = _exact_mapping(
            envelope.get("data"),
            "$.data",
            ("state", "document", "target_ref", "warnings"),
            issues,
        )
        if data is not None:
            _expect_value(
                data.get("state"),
                "imported",
                "$.data.state",
                issues,
            )
            document = _exact_mapping(
                data.get("document"),
                "$.data.document",
                ("type", "version", "sha256", "source_ref"),
                issues,
            )
            if document is not None:
                _expect_value(
                    document.get("type"),
                    "writer.shot-list",
                    "$.data.document.type",
                    issues,
                )
                _expect_value(
                    document.get("version"),
                    1,
                    "$.data.document.version",
                    issues,
                )
                if not _valid_sha256(document.get("sha256")):
                    _issue(
                        issues,
                        "$.data.document.sha256",
                        "invalid_sha256",
                    )
                if not _valid_writer_ref(document.get("source_ref")):
                    _issue(
                        issues,
                        "$.data.document.source_ref",
                        "invalid_reference",
                    )
            if not _valid_zing_ref(data.get("target_ref")):
                _issue(issues, "$.data.target_ref", "invalid_reference")
            warnings = data.get("warnings")
            if not isinstance(warnings, list) or any(
                not isinstance(item, str) for item in warnings
            ):
                _issue(
                    issues,
                    "$.data.warnings",
                    "wrong_type",
                    expected="list[str]",
                )
    else:
        _expect_value(ok, False, "$.ok", issues)
        error = _exact_mapping(
            envelope.get("error"),
            "$.error",
            ("code", "message", "retryable"),
            issues,
        )
        if error is not None:
            if error.get("code") not in _IMPORT_ERROR_CODES:
                _issue(
                    issues,
                    "$.error.code",
                    "invalid_value",
                    actual=error.get("code"),
                )
            if not isinstance(error.get("message"), str):
                _issue(issues, "$.error.message", "wrong_type", expected="str")
            if not isinstance(error.get("retryable"), bool):
                _issue(
                    issues,
                    "$.error.retryable",
                    "wrong_type",
                    expected="bool",
                )
    issues.extend(_path_free_issues(payload))
    return issues


def _validate_engagement(payload: Any) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not isinstance(payload, Mapping):
        _issue(issues, "$", "wrong_type", expected="object")
        return issues
    is_request = "events" in payload
    keys = (
        ("contract", "version", "events")
        if is_request
        else ("ok", "contract", "version", "data")
    )
    envelope = _exact_mapping(payload, "$", keys, issues)
    if envelope is None:
        return issues
    _expect_value(
        envelope.get("contract"),
        "uoink.engagement.ingest",
        "$.contract",
        issues,
    )
    _expect_value(envelope.get("version"), 1, "$.version", issues)
    if is_request:
        events = envelope.get("events")
        if not isinstance(events, list) or not 1 <= len(events) <= 100:
            _issue(
                issues,
                "$.events",
                "invalid_batch_size",
                actual=len(events) if isinstance(events, list) else None,
            )
            return issues
        event_ids: list[str] = []
        for index, raw_event in enumerate(events):
            event = _exact_mapping(
                raw_event,
                f"$.events[{index}]",
                (
                    "event_id",
                    "item_ref",
                    "event_type",
                    "source_product",
                    "occurred_at",
                ),
                issues,
            )
            if event is None:
                continue
            event_id = event.get("event_id")
            if not isinstance(event_id, str) or not _ASCII_EVENT_RE.fullmatch(
                event_id
            ):
                _issue(
                    issues,
                    f"$.events[{index}].event_id",
                    "invalid_ascii_id",
                )
            else:
                event_ids.append(event_id)
            if not _valid_uoink_ref(event.get("item_ref")):
                _issue(
                    issues,
                    f"$.events[{index}].item_ref",
                    "invalid_reference",
                )
            if event.get("event_type") not in {
                "opened",
                "search_hit",
                "search_click",
                "paste",
                "cite",
            }:
                _issue(
                    issues,
                    f"$.events[{index}].event_type",
                    "invalid_value",
                )
            if event.get("source_product") not in {"writer", "zing"}:
                _issue(
                    issues,
                    f"$.events[{index}].source_product",
                    "invalid_value",
                )
            if not _is_rfc3339(event.get("occurred_at"), utc_only=True):
                _issue(
                    issues,
                    f"$.events[{index}].occurred_at",
                    "invalid_utc_rfc3339",
                )
        if len(event_ids) != len(set(event_ids)):
            _issue(issues, "$.events", "duplicate_event_id")
    else:
        _expect_value(envelope.get("ok"), True, "$.ok", issues)
        data = _exact_mapping(
            envelope.get("data"),
            "$.data",
            ("submitted", "accepted", "duplicates", "rejected"),
            issues,
        )
        if data is None:
            return issues
        counts: dict[str, int] = {}
        for key in ("submitted", "accepted", "duplicates"):
            value = data.get(key)
            if not _is_int(value) or value < 0:
                _issue(
                    issues,
                    f"$.data.{key}",
                    "invalid_nonnegative_integer",
                    actual=value,
                )
            else:
                counts[key] = value
        rejected = data.get("rejected")
        if not isinstance(rejected, list):
            _issue(issues, "$.data.rejected", "wrong_type", expected="list")
            rejected_count = 0
        else:
            rejected_count = len(rejected)
            for index, raw_rejection in enumerate(rejected):
                rejection = _exact_mapping(
                    raw_rejection,
                    f"$.data.rejected[{index}]",
                    ("event_id", "code", "message", "retryable"),
                    issues,
                )
                if rejection is None:
                    continue
                if not isinstance(rejection.get("event_id"), str):
                    _issue(
                        issues,
                        f"$.data.rejected[{index}].event_id",
                        "wrong_type",
                        expected="str",
                    )
                if not isinstance(rejection.get("code"), str):
                    _issue(
                        issues,
                        f"$.data.rejected[{index}].code",
                        "wrong_type",
                        expected="str",
                    )
                if not isinstance(rejection.get("message"), str):
                    _issue(
                        issues,
                        f"$.data.rejected[{index}].message",
                        "wrong_type",
                        expected="str",
                    )
                if not isinstance(rejection.get("retryable"), bool):
                    _issue(
                        issues,
                        f"$.data.rejected[{index}].retryable",
                        "wrong_type",
                        expected="bool",
                    )
        if len(counts) == 3 and (
            counts["submitted"]
            != counts["accepted"] + counts["duplicates"] + rejected_count
        ):
            _issue(
                issues,
                "$.data",
                "inconsistent_accounting",
                submitted=counts["submitted"],
                accounted=(
                    counts["accepted"]
                    + counts["duplicates"]
                    + rejected_count
                ),
            )
    return issues


def validate_contract_payload(
    contract: str,
    payload: Any,
    *,
    expected_service: str | None = None,
    expected_peer: str | None = None,
    live_pids: Sequence[int] | None = None,
    pid_is_live: Callable[[int], bool] | None = None,
) -> dict[str, Any]:
    """Validate one raw payload without calling a product or opening its data."""
    if contract == "ryan.suite.runtime-lease/1":
        issues = _validate_runtime_lease(
            payload,
            expected_service=expected_service,
            live_pids=live_pids,
            pid_is_live=pid_is_live,
        )
    elif contract == "ryan.suite.service/1":
        issues = _validate_service(
            payload,
            expected_service=expected_service,
        )
    elif contract == "ryan.suite.health/1":
        issues = _validate_health(
            payload,
            expected_service=expected_service,
        )
    elif contract == "ryan.suite.peer/1":
        issues = _validate_peer(payload, expected_peer=expected_peer)
    elif contract == "uoink.media.handoff/1":
        issues = _validate_media_handoff(payload)
    elif contract == "writer.shot-list/1":
        issues = _validate_shot_list(payload)
    elif contract == "zing.shot-list.import/1":
        issues = _validate_import(payload)
    elif contract == "uoink.engagement.ingest/1":
        issues = _validate_engagement(payload)
    else:
        issues = [
            {
                "path": "$",
                "kind": "unknown_contract",
                "actual": contract,
            }
        ]
    return {
        "contract": contract,
        "passed": not issues,
        "issues": issues,
    }


def _mutate(payload: Any, mutation: Mapping[str, Any]) -> None:
    operation = mutation["op"]
    path = mutation.get("path", [])
    target = payload
    for part in path[:-1]:
        target = target[part]
    if operation == "set":
        target[path[-1]] = copy.deepcopy(mutation["value"])
    elif operation == "delete":
        del target[path[-1]]
    elif operation == "append":
        target[path[-1]].append(copy.deepcopy(mutation["value"]))
    else:
        raise ValueError(f"unsupported fixture mutation: {operation}")


def _decode_case_payload(case: Mapping[str, Any]) -> Any:
    if "payload" in case:
        return copy.deepcopy(case["payload"])
    if "payload_text" in case:
        return case["payload_text"]
    if "payload_base64" in case:
        return base64.b64decode(case["payload_base64"], validate=True)
    if "payload_repeat" in case:
        repeat = case["payload_repeat"]
        prefix = repeat.get("prefix", "").encode("utf-8")
        unit = repeat["unit"].encode("utf-8")
        return prefix + unit * int(repeat["count"])
    return _MISSING


@lru_cache(maxsize=1)
def _expanded_fixture_bundle() -> tuple[
    Mapping[str, Any],
    Mapping[str, Mapping[str, Any]],
]:
    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    cases_by_global_id: dict[str, Mapping[str, Any]] = {}
    for entry in manifest["case_files"]:
        path = DEFAULT_SUITE_FIXTURES / entry["path"]
        document = json.loads(path.read_text(encoding="utf-8"))
        contract = document["contract"]
        raw_cases = {case["id"]: case for case in document["cases"]}
        expanded_local: dict[str, dict[str, Any]] = {}

        def expand(case_id: str) -> dict[str, Any]:
            if case_id in expanded_local:
                return copy.deepcopy(expanded_local[case_id])
            raw = raw_cases[case_id]
            if "base" in raw:
                result = expand(raw["base"])
                result["id"] = case_id
                result["context"] = {
                    **result.get("context", {}),
                    **raw.get("context", {}),
                }
                result["expected_valid"] = raw.get(
                    "expected_valid",
                    result["expected_valid"],
                )
                if "behavior" in raw:
                    result["behavior"] = copy.deepcopy(raw["behavior"])
                for mutation in raw.get("mutations", []):
                    _mutate(result["payload"], mutation)
            else:
                payload = _decode_case_payload(raw)
                if payload is _MISSING:
                    raise ValueError(
                        f"fixture case has no payload: {entry['path']}#{case_id}"
                    )
                result = {
                    "id": case_id,
                    "contract": contract,
                    "payload": payload,
                    "context": copy.deepcopy(raw.get("context", {})),
                    "expected_valid": raw["expected_valid"],
                    "behavior": copy.deepcopy(raw.get("behavior")),
                }
            expanded_local[case_id] = copy.deepcopy(result)
            return result

        for case_id in raw_cases:
            case = expand(case_id)
            global_id = f"{entry['alias']}_{case_id}"
            cases_by_global_id[global_id] = case
    return manifest, cases_by_global_id


def load_fixture_case(case_id: str) -> dict[str, Any]:
    """Load one expanded, detached fixture case by its global ID."""
    _, cases = _expanded_fixture_bundle()
    try:
        return copy.deepcopy(cases[case_id])
    except KeyError:
        raise KeyError(f"unknown suite fixture case: {case_id}") from None


def _behavior_issues(
    contract: str,
    case_id: str,
    payload: Any,
    behavior: Any,
) -> list[dict[str, Any]]:
    if behavior is None:
        return []
    issues: list[dict[str, Any]] = []
    if contract == "uoink.media.handoff/1":
        if case_id in {"traversal", "outside_folder_symlink"}:
            data = payload.get("data", {}) if isinstance(payload, Mapping) else {}
            unsafe_input_is_present = (
                case_id == "traversal"
                and behavior.get("sidecar_media_file", "").startswith("../")
            ) or (
                case_id == "outside_folder_symlink"
                and behavior.get("sidecar_is_outside_folder_symlink") is True
            )
            if (
                data.get("state") != "missing"
                or data.get("media") is not None
                or behavior.get("sidecar_accepted") is not False
                or not unsafe_input_is_present
            ):
                _issue(issues, "$.behavior", "unsafe_media_resolution")
        elif case_id in {"hash_mismatch", "size_mismatch"}:
            media = (
                payload.get("data", {}).get("media", {})
                if isinstance(payload, Mapping)
                else {}
            )
            mismatch_is_present = (
                case_id == "hash_mismatch"
                and behavior.get("actual_sha256") != media.get("sha256")
            ) or (
                case_id == "size_mismatch"
                and behavior.get("actual_byte_length")
                != media.get("byte_length")
            )
            if not mismatch_is_present or behavior.get("consumer_outcome") != {
                "acquisition": "source_refetch",
                "refetch": True,
                "reason": "integrity_mismatch",
            }:
                _issue(issues, "$.behavior", "dishonest_integrity_fallback")
    elif contract == "zing.shot-list.import/1":
        if case_id == "duplicate_import" and (
            behavior.get("receipts_equal") is not True
            or behavior.get("persisted_copy_count") != 1
        ):
            _issue(issues, "$.behavior", "non_idempotent_duplicate")
        if case_id == "path_free_receipt" and _path_free_issues(payload):
            _issue(issues, "$.behavior", "receipt_contains_path")
    elif contract == "uoink.engagement.ingest/1":
        if case_id == "transaction_rollback" and (
            behavior.get("transaction_committed") is not False
            or behavior.get("persisted_event_ids") != []
            or sorted(behavior.get("spooled_event_ids", []))
            != sorted(behavior.get("submitted_event_ids", []))
        ):
            _issue(issues, "$.behavior", "partial_transaction")
    return issues


def _fixture_privacy_report(
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    scanned_files = 1
    private_markers = (
        "E:\\AI\\",
        "C:\\Users\\hello\\",
        "/Users/hello/",
        "/home/hello/",
    )
    for entry in manifest["case_files"]:
        path = DEFAULT_SUITE_FIXTURES / entry["path"]
        scanned_files += 1
        text = path.read_text(encoding="utf-8")
        for marker in private_markers:
            if marker.lower() in text.lower():
                _issue(
                    issues,
                    entry["path"],
                    "private_machine_path",
                    marker=marker,
                )
        document = json.loads(text)

        def walk(value: Any, location: str) -> None:
            if isinstance(value, Mapping):
                for key, child in value.items():
                    lower = str(key).lower()
                    child_location = f"{location}.{key}"
                    if any(
                        marker in lower
                        for marker in ("token", "credential", "secret", "password")
                    ) and (
                        not isinstance(child, str)
                        or not child.startswith("synthetic-forbidden-")
                    ):
                        _issue(
                            issues,
                            child_location,
                            "non_synthetic_credential_fixture",
                        )
                    walk(child, child_location)
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    walk(child, f"{location}[{index}]")
            elif isinstance(value, str) and "://" not in value and (
                _WINDOWS_ABSOLUTE_RE.match(value)
                or value.startswith("\\\\")
                or value.startswith(
                    (
                        "/Users/",
                        "/home/",
                        "/var/",
                        "/tmp/",
                        "/etc/",
                    )
                )
            ) and not value.startswith("C:\\SuiteFixture\\"):
                _issue(
                    issues,
                    location,
                    "non_synthetic_absolute_path",
                )

        walk(document, entry["path"])
    return {
        "passed": not issues,
        "issues": issues,
        "scanned_files": scanned_files,
    }


def evaluate_fixture_bundle(
    fixture_root: Path = DEFAULT_SUITE_FIXTURES,
) -> dict[str, Any]:
    """Check fixture coverage and every expected accept/reject outcome."""
    if fixture_root != DEFAULT_SUITE_FIXTURES:
        raise ValueError(
            "custom suite fixture roots are not supported by contract v1"
        )
    manifest, cases = _expanded_fixture_bundle()
    contract_reports: dict[str, dict[str, Any]] = {}
    suite_smoke_cases: list[dict[str, Any]] = []
    for global_id, case in cases.items():
        contract = case["contract"]
        if contract == "zing.suite-smoke/1":
            from tools.eval.suite_smoke import evaluate_suite_record

            smoke_report = evaluate_suite_record(case["payload"])
            outcome_matches = smoke_report["passed"] is case["expected_valid"]
            suite_smoke_cases.append(
                {
                    "fixture_id": global_id,
                    "case_id": case["id"],
                    "expected_valid": case["expected_valid"],
                    "actual_valid": smoke_report["passed"],
                    "passed": outcome_matches,
                    "issues": [
                        issue
                        for assertion in smoke_report["assertions"].values()
                        for issue in assertion["issues"]
                    ],
                }
            )
            continue
        validation = validate_contract_payload(
            contract,
            case["payload"],
            **case.get("context", {}),
        )
        behavior_issues = _behavior_issues(
            contract,
            case["id"],
            case["payload"],
            case.get("behavior"),
        )
        outcome_matches = (
            validation["passed"] is case["expected_valid"]
            and not behavior_issues
        )
        report = contract_reports.setdefault(
            contract,
            {
                "passed": True,
                "case_ids": [],
                "failed_case_ids": [],
                "cases": [],
            },
        )
        report["case_ids"].append(case["id"])
        report["cases"].append(
            {
                "fixture_id": global_id,
                "case_id": case["id"],
                "expected_valid": case["expected_valid"],
                "actual_valid": validation["passed"],
                "passed": outcome_matches,
                "issues": validation["issues"] + behavior_issues,
            }
        )
        if not outcome_matches:
            report["passed"] = False
            report["failed_case_ids"].append(case["id"])
    privacy = _fixture_privacy_report(manifest)
    return {
        "passed": (
            all(report["passed"] for report in contract_reports.values())
            and all(case["passed"] for case in suite_smoke_cases)
            and privacy["passed"]
        ),
        "fixture_version": manifest["fixture_version"],
        "contract_source": manifest["contract_source"],
        "contracts": contract_reports,
        "suite_smoke_cases": suite_smoke_cases,
        "privacy": privacy,
    }
