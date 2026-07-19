"""Independent assertions over the path-free Sprint 6 family-smoke record."""

from __future__ import annotations

import argparse
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

from tools.eval.suite_contracts import validate_contract_payload


SUITE_SMOKE_RECORD_VERSION = 1
SUITE_SMOKE_ASSERTION_IDS = (
    "record_metadata",
    "step_timing",
    "direct_mcp_identity",
    "resident_contracts",
    "stable_references",
    "kept_media_zero_refetch",
    "same_uoink_source",
    "writer_workflow",
    "shot_list_import_identity",
    "same_zing_breakdown",
    "measured_keeper_spans",
    "draft_provenance",
    "engagement_accounting",
    "optional_peer_fail_calm",
    "recorded_assertions",
    "cleanup",
    "record_privacy",
)
_REQUIRED_STEP_IDS = (
    "launch_products",
    "validate_discovery",
    "capture_kept_media",
    "study_kept_media",
    "create_zing_direction",
    "writer_create",
    "export_shot_list",
    "import_shot_list",
    "assemble_render",
    "account_engagement",
    "stop_optional_peer",
)
_REQUIRED_RECORDED_ASSERTIONS = (
    "leases_exact",
    "manifests_exact",
    "health_exact",
    "mcp_direct",
    "kept_media_verified",
    "zero_refetch",
    "same_uoink_source",
    "writer_file_only",
    "import_path_free",
    "measured_spans_only",
    "engagement_visible",
    "peer_stop_fail_calm",
)
_TOP_LEVEL_KEYS = {
    "record_contract",
    "version",
    "mode",
    "sources",
    "environment",
    "steps",
    "contracts",
    "peer_states",
    "mcp_identities",
    "references",
    "artifacts",
    "handoff",
    "writer_flow",
    "zing_flow",
    "engagement",
    "optional_peer_stop",
    "assertions",
    "failure_code",
    "cleanup",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_UOINK_REF_RE = re.compile(r"^uoink://item/[^/]+$")
_WRITER_REF_RE = re.compile(r"^writer://script/[1-9][0-9]*$")
_ZING_REF_RE = re.compile(
    r"^zing://breakdown/[a-z0-9][a-z0-9-]{0,99}$"
)
_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_MISSING = object()


def _get(value: Any, path: Sequence[object]) -> Any:
    target = value
    for part in path:
        if isinstance(part, int):
            if not isinstance(target, list) or part >= len(target):
                return _MISSING
            target = target[part]
        else:
            if not isinstance(target, Mapping) or part not in target:
                return _MISSING
            target = target[part]
    return target


def _problem(path: str, kind: str, **details: Any) -> dict[str, Any]:
    return {"path": path, "kind": kind, **details}


def _missing_or_wrong(
    record: Any,
    path: Sequence[object],
    expected: type,
) -> tuple[Any, list[dict[str, Any]]]:
    value = _get(record, path)
    display = "$." + ".".join(str(part) for part in path)
    if value is _MISSING:
        return value, [_problem(display, "missing")]
    if not isinstance(value, expected):
        return value, [
            _problem(
                display,
                "wrong_type",
                expected=expected.__name__,
                actual=type(value).__name__,
            )
        ]
    return value, []


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def _metadata_issues(record: Any) -> list[dict[str, Any]]:
    if not isinstance(record, Mapping):
        return [_problem("$", "wrong_type", expected="object")]
    issues: list[dict[str, Any]] = []
    unknown = sorted(set(record) - _TOP_LEVEL_KEYS)
    missing = sorted(_TOP_LEVEL_KEYS - set(record))
    if unknown:
        issues.append(_problem("$", "unknown_keys", keys=unknown))
    if missing:
        issues.append(_problem("$", "missing_keys", keys=missing))
    expected_values = {
        "record_contract": "zing.suite-smoke",
        "version": SUITE_SMOKE_RECORD_VERSION,
    }
    for key, expected in expected_values.items():
        if record.get(key) != expected:
            issues.append(
                _problem(
                    f"$.{key}",
                    "invalid_value",
                    expected=expected,
                    actual=record.get(key),
                )
            )
    if record.get("mode") not in {"deterministic_ci", "real_capture"}:
        issues.append(
            _problem("$.mode", "invalid_value", actual=record.get("mode"))
        )
    sources = record.get("sources")
    if not isinstance(sources, Mapping) or set(sources) != {
        "uoink",
        "writer",
        "zing",
    }:
        issues.append(_problem("$.sources", "invalid_product_set"))
    else:
        for product, value in sources.items():
            if not isinstance(value, Mapping) or set(value) != {
                "revision",
                "installed_version",
            }:
                issues.append(
                    _problem(f"$.sources.{product}", "invalid_shape")
                )
            elif not all(
                isinstance(value.get(key), str) and value.get(key)
                for key in ("revision", "installed_version")
            ):
                issues.append(
                    _problem(f"$.sources.{product}", "empty_version")
                )
    environment = record.get("environment")
    if not isinstance(environment, Mapping) or set(environment) != {
        "platform",
        "python_version",
    }:
        issues.append(_problem("$.environment", "invalid_shape"))
    if record.get("failure_code") is not None:
        issues.append(
            _problem(
                "$.failure_code",
                "smoke_reported_failure",
                actual=record.get("failure_code"),
            )
        )
    return issues


def _timing_issues(record: Any) -> list[dict[str, Any]]:
    steps, issues = _missing_or_wrong(record, ("steps",), list)
    if issues:
        return issues
    step_ids: list[str] = []
    for index, step in enumerate(steps):
        path = f"$.steps[{index}]"
        if not isinstance(step, Mapping) or set(step) != {
            "id",
            "started_at",
            "ended_at",
            "duration_seconds",
            "passed",
        }:
            issues.append(_problem(path, "invalid_shape"))
            continue
        step_id = step.get("id")
        if isinstance(step_id, str):
            step_ids.append(step_id)
        else:
            issues.append(_problem(f"{path}.id", "wrong_type"))
        started = _parse_time(step.get("started_at"))
        ended = _parse_time(step.get("ended_at"))
        duration = step.get("duration_seconds")
        if started is None:
            issues.append(_problem(f"{path}.started_at", "invalid_rfc3339"))
        if ended is None:
            issues.append(_problem(f"{path}.ended_at", "invalid_rfc3339"))
        if (
            not isinstance(duration, (int, float))
            or isinstance(duration, bool)
            or not math.isfinite(float(duration))
            or duration < 0
        ):
            issues.append(_problem(f"{path}.duration_seconds", "invalid"))
        elif started is not None and ended is not None:
            elapsed = (ended - started).total_seconds()
            if elapsed < 0 or not math.isclose(
                float(duration),
                elapsed,
                abs_tol=0.001,
            ):
                issues.append(
                    _problem(
                        f"{path}.duration_seconds",
                        "does_not_match_timestamps",
                        expected=elapsed,
                        actual=duration,
                    )
                )
        if step.get("passed") is not True:
            issues.append(_problem(f"{path}.passed", "step_failed"))
    if tuple(step_ids) != _REQUIRED_STEP_IDS:
        issues.append(
            _problem(
                "$.steps",
                "invalid_step_order",
                expected=list(_REQUIRED_STEP_IDS),
                actual=step_ids,
            )
        )
    return issues


def _mcp_issues(record: Any) -> list[dict[str, Any]]:
    identities = _get(record, ("mcp_identities",))
    if identities != ["uoink", "writer", "zing"]:
        return [
            _problem(
                "$.mcp_identities",
                "not_three_direct_products",
                expected=["uoink", "writer", "zing"],
                actual=identities,
            )
        ]
    return []


def _resident_contract_issues(record: Any) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    contracts = _get(record, ("contracts",))
    expected = {
        "runtime_lease": "ryan.suite.runtime-lease/1",
        "service_manifest": "ryan.suite.service/1",
        "health": "ryan.suite.health/1",
        "peer": "ryan.suite.peer/1",
        "media_handoff": "uoink.media.handoff/1",
        "corpus_read": "uoink.corpus.read/1",
        "shot_list": "writer.shot-list/1",
        "shot_list_import": "zing.shot-list.import/1",
        "engagement": "uoink.engagement.ingest/1",
    }
    if contracts != expected:
        issues.append(
            _problem(
                "$.contracts",
                "invalid_contract_versions",
                expected=expected,
                actual=contracts,
            )
        )
    peer_states = _get(record, ("peer_states",))
    if peer_states != {
        "uoink": "available",
        "writer": "available",
    }:
        issues.append(
            _problem(
                "$.peer_states",
                "initial_peers_not_available",
                actual=peer_states,
            )
        )
    return issues


def _reference_issues(record: Any) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    references = _get(record, ("references",))
    if not isinstance(references, Mapping) or set(references) != {
        "uoink_item",
        "writer_script",
        "zing_breakdown",
    }:
        return [_problem("$.references", "invalid_shape")]
    checks = (
        ("uoink_item", _UOINK_REF_RE),
        ("writer_script", _WRITER_REF_RE),
        ("zing_breakdown", _ZING_REF_RE),
    )
    for key, pattern in checks:
        value = references.get(key)
        if not isinstance(value, str) or not pattern.fullmatch(value):
            issues.append(
                _problem(f"$.references.{key}", "invalid_reference")
            )
    artifacts = _get(record, ("artifacts",))
    if not isinstance(artifacts, list) or not artifacts:
        issues.append(_problem("$.artifacts", "invalid_shape"))
    else:
        ids: list[str] = []
        for index, artifact in enumerate(artifacts):
            if not isinstance(artifact, Mapping):
                issues.append(
                    _problem(f"$.artifacts[{index}]", "invalid_shape")
                )
                continue
            artifact_id = artifact.get("id")
            if isinstance(artifact_id, str):
                ids.append(artifact_id)
            else:
                issues.append(
                    _problem(f"$.artifacts[{index}].id", "wrong_type")
                )
            if not _valid_hash(artifact.get("sha256")):
                issues.append(
                    _problem(
                        f"$.artifacts[{index}].sha256",
                        "invalid_sha256",
                    )
                )
        if len(ids) != len(set(ids)):
            issues.append(_problem("$.artifacts", "duplicate_id"))
        if not {"kept_media", "shot_list", "render"} <= set(ids):
            issues.append(_problem("$.artifacts", "missing_required_artifact"))
    return issues


def _artifact_hash(record: Any, artifact_id: str) -> Any:
    artifacts = _get(record, ("artifacts",))
    if not isinstance(artifacts, list):
        return _MISSING
    for artifact in artifacts:
        if isinstance(artifact, Mapping) and artifact.get("id") == artifact_id:
            return artifact.get("sha256", _MISSING)
    return _MISSING


def _handoff_issues(record: Any) -> list[dict[str, Any]]:
    handoff = _get(record, ("handoff",))
    expected = {
        "contract": "uoink.media.handoff",
        "version": 1,
        "source_ref": _get(record, ("references", "uoink_item")),
        "acquisition": "kept_media",
        "refetch": False,
        "sha256": _artifact_hash(record, "kept_media"),
    }
    if handoff != expected:
        return [
            _problem(
                "$.handoff",
                "not_verified_zero_refetch",
                expected=expected,
                actual=handoff,
            )
        ]
    return []


def _same_source_issues(record: Any) -> list[dict[str, Any]]:
    expected = _get(record, ("references", "uoink_item"))
    observations = {
        "$.handoff.source_ref": _get(record, ("handoff", "source_ref")),
        "$.writer_flow.corpus_item_ref": _get(
            record,
            ("writer_flow", "corpus_item_ref"),
        ),
        "$.writer_flow.shot_list.source_credit_ref": _get(
            record,
            ("writer_flow", "shot_list", "source_credit_ref"),
        ),
    }
    return [
        _problem(path, "source_identity_mismatch", expected=expected, actual=value)
        for path, value in observations.items()
        if value != expected
    ]


def _writer_issues(record: Any) -> list[dict[str, Any]]:
    flow = _get(record, ("writer_flow",))
    if not isinstance(flow, Mapping):
        return [_problem("$.writer_flow", "invalid_shape")]
    issues: list[dict[str, Any]] = []
    expected_bools = (
        "source_snapshot_path_free",
        "script_saved",
        "critique_saved",
        "voice_dna_scanned",
    )
    for key in expected_bools:
        if flow.get(key) is not True:
            issues.append(_problem(f"$.writer_flow.{key}", "not_proven"))
    if flow.get("corpus_contract") != "uoink.corpus.read/1":
        issues.append(
            _problem("$.writer_flow.corpus_contract", "invalid_contract")
        )
    script_id = flow.get("script_id")
    expected_ref = (
        f"writer://script/{script_id}"
        if isinstance(script_id, int)
        and not isinstance(script_id, bool)
        and script_id > 0
        else None
    )
    if expected_ref is None:
        issues.append(_problem("$.writer_flow.script_id", "invalid"))
    shot_list = flow.get("shot_list")
    if not isinstance(shot_list, Mapping):
        issues.append(_problem("$.writer_flow.shot_list", "invalid_shape"))
    else:
        if shot_list.get("source_ref") != expected_ref:
            issues.append(
                _problem(
                    "$.writer_flow.shot_list.source_ref",
                    "script_identity_mismatch",
                )
            )
        if shot_list.get("sha256") != _artifact_hash(record, "shot_list"):
            issues.append(
                _problem(
                    "$.writer_flow.shot_list.sha256",
                    "artifact_hash_mismatch",
                )
            )
        if shot_list.get("zing_call_count") != 0:
            issues.append(
                _problem(
                    "$.writer_flow.shot_list.zing_call_count",
                    "writer_called_zing",
                )
            )
        if shot_list.get("absolute_paths") != []:
            issues.append(
                _problem(
                    "$.writer_flow.shot_list.absolute_paths",
                    "writer_export_contains_path",
                )
            )
    return issues


def _import_issues(record: Any) -> list[dict[str, Any]]:
    receipt = _get(record, ("zing_flow", "import_receipt"))
    validation = validate_contract_payload(
        "zing.shot-list.import/1",
        receipt,
    )
    issues = [
        _problem(
            f"$.zing_flow.import_receipt{issue['path'].removeprefix('$')}",
            issue["kind"],
        )
        for issue in validation["issues"]
    ]
    expected_hash = _artifact_hash(record, "shot_list")
    expected_ref = _get(record, ("references", "writer_script"))
    observed_hash = _get(
        receipt,
        ("data", "document", "sha256"),
    )
    observed_ref = _get(
        receipt,
        ("data", "document", "source_ref"),
    )
    if observed_hash != expected_hash:
        issues.append(
            _problem(
                "$.zing_flow.import_receipt.data.document.sha256",
                "artifact_hash_mismatch",
                expected=expected_hash,
                actual=observed_hash,
            )
        )
    if observed_ref != expected_ref:
        issues.append(
            _problem(
                "$.zing_flow.import_receipt.data.document.source_ref",
                "writer_identity_mismatch",
                expected=expected_ref,
                actual=observed_ref,
            )
        )
    return issues


def _same_breakdown_issues(record: Any) -> list[dict[str, Any]]:
    expected = _get(record, ("references", "zing_breakdown"))
    observations = {
        "$.zing_flow.breakdown_ref": _get(
            record,
            ("zing_flow", "breakdown_ref"),
        ),
        "$.zing_flow.import_receipt.data.target_ref": _get(
            record,
            ("zing_flow", "import_receipt", "data", "target_ref"),
        ),
    }
    return [
        _problem(
            path,
            "breakdown_identity_mismatch",
            expected=expected,
            actual=value,
        )
        for path, value in observations.items()
        if value != expected
    ]


def _keeper_issues(record: Any) -> list[dict[str, Any]]:
    flow = _get(record, ("zing_flow",))
    if not isinstance(flow, Mapping):
        return [_problem("$.zing_flow", "invalid_shape")]
    issues: list[dict[str, Any]] = []
    for key in ("breakdown_created", "profile_created", "direction_created"):
        if flow.get(key) is not True:
            issues.append(_problem(f"$.zing_flow.{key}", "not_proven"))
    spans = flow.get("keeper_spans")
    if not isinstance(spans, list) or not spans:
        issues.append(_problem("$.zing_flow.keeper_spans", "empty"))
        return issues
    last_end = -math.inf
    for index, span in enumerate(spans):
        path = f"$.zing_flow.keeper_spans[{index}]"
        if not isinstance(span, Mapping) or set(span) != {"start", "end"}:
            issues.append(_problem(path, "invalid_shape"))
            continue
        start = span.get("start")
        end = span.get("end")
        if (
            not isinstance(start, (int, float))
            or isinstance(start, bool)
            or not isinstance(end, (int, float))
            or isinstance(end, bool)
            or not math.isfinite(float(start))
            or not math.isfinite(float(end))
            or start < 0
            or end <= start
        ):
            issues.append(_problem(path, "invalid_span"))
        elif start < last_end:
            issues.append(_problem(path, "overlap"))
        else:
            last_end = end
    return issues


def _draft_issues(record: Any) -> list[dict[str, Any]]:
    provenance = _get(record, ("zing_flow", "draft_provenance"))
    expected = {
        "breakdown_ref": _get(record, ("references", "zing_breakdown")),
        "writer_source_ref": _get(record, ("references", "writer_script")),
        "shot_list_sha256": _artifact_hash(record, "shot_list"),
        "keeper_span_source": "zing_direction",
        "keeper_spans": _get(record, ("zing_flow", "keeper_spans")),
    }
    issues: list[dict[str, Any]] = []
    if provenance != expected:
        issues.append(
            _problem(
                "$.zing_flow.draft_provenance",
                "invalid_provenance",
                expected=expected,
                actual=provenance,
            )
        )
    if _get(record, ("zing_flow", "rendered")) is not True:
        issues.append(_problem("$.zing_flow.rendered", "not_proven"))
    if _get(record, ("zing_flow", "render_sha256")) != _artifact_hash(
        record,
        "render",
    ):
        issues.append(
            _problem("$.zing_flow.render_sha256", "artifact_hash_mismatch")
        )
    return issues


def _engagement_issues(record: Any) -> list[dict[str, Any]]:
    engagement = _get(record, ("engagement",))
    if not isinstance(engagement, Mapping):
        return [_problem("$.engagement", "invalid_shape")]
    submitted = engagement.get("submitted_event_ids")
    receipts = engagement.get("receipts")
    spool = engagement.get("visible_spool")
    rejections = engagement.get("durable_rejections")
    if not all(
        isinstance(value, list)
        for value in (submitted, receipts, spool, rejections)
    ):
        return [_problem("$.engagement", "invalid_shape")]
    issues: list[dict[str, Any]] = []
    submitted_ids = [item for item in submitted if isinstance(item, str)]
    if (
        len(submitted_ids) != len(submitted)
        or len(submitted_ids) != len(set(submitted_ids))
    ):
        issues.append(_problem("$.engagement.submitted_event_ids", "invalid"))
    accounted: list[str] = []
    for index, receipt in enumerate(receipts):
        if (
            not isinstance(receipt, Mapping)
            or set(receipt) != {"event_id", "state"}
            or receipt.get("state")
            not in {"accepted", "duplicate", "rejected"}
        ):
            issues.append(
                _problem(f"$.engagement.receipts[{index}]", "invalid_shape")
            )
            continue
        accounted.append(receipt["event_id"])
    for index, event in enumerate(spool):
        if (
            not isinstance(event, Mapping)
            or event.get("event_id") not in submitted_ids
            or event.get("state") != "spooled"
        ):
            issues.append(
                _problem(
                    f"$.engagement.visible_spool[{index}]",
                    "invalid_shape",
                )
            )
            continue
        accounted.append(event["event_id"])
    for index, rejection in enumerate(rejections):
        if (
            not isinstance(rejection, Mapping)
            or rejection.get("event_id") not in submitted_ids
            or not isinstance(rejection.get("code"), str)
        ):
            issues.append(
                _problem(
                    f"$.engagement.durable_rejections[{index}]",
                    "invalid_shape",
                )
            )
            continue
        accounted.append(rejection["event_id"])
    if sorted(accounted) != sorted(submitted_ids):
        issues.append(
            _problem(
                "$.engagement",
                "unaccounted_events",
                submitted=submitted_ids,
                accounted=accounted,
            )
        )
    return issues


def _peer_stop_issues(record: Any) -> list[dict[str, Any]]:
    peer_stop = _get(record, ("optional_peer_stop",))
    if not isinstance(peer_stop, Mapping):
        return [_problem("$.optional_peer_stop", "invalid_shape")]
    issues: list[dict[str, Any]] = []
    if peer_stop.get("stopped_peer") not in {"uoink", "writer"}:
        issues.append(
            _problem("$.optional_peer_stop.stopped_peer", "invalid_value")
        )
    remaining = peer_stop.get("remaining_products")
    if not isinstance(remaining, list) or not remaining:
        issues.append(
            _problem("$.optional_peer_stop.remaining_products", "empty")
        )
        return issues
    for index, product in enumerate(remaining):
        path = f"$.optional_peer_stop.remaining_products[{index}]"
        if not isinstance(product, Mapping) or set(product) != {
            "product",
            "peer_state",
            "standalone_ok",
        }:
            issues.append(_problem(path, "invalid_shape"))
            continue
        if product.get("peer_state") not in {"absent", "unhealthy"}:
            issues.append(_problem(f"{path}.peer_state", "invalid_value"))
        if product.get("standalone_ok") is not True:
            issues.append(_problem(f"{path}.standalone_ok", "core_failed"))
    return issues


def _recorded_assertion_issues(record: Any) -> list[dict[str, Any]]:
    assertions = _get(record, ("assertions",))
    if not isinstance(assertions, list):
        return [_problem("$.assertions", "invalid_shape")]
    ids: list[str] = []
    issues: list[dict[str, Any]] = []
    for index, assertion in enumerate(assertions):
        if not isinstance(assertion, Mapping) or set(assertion) != {
            "id",
            "passed",
        }:
            issues.append(_problem(f"$.assertions[{index}]", "invalid_shape"))
            continue
        if isinstance(assertion.get("id"), str):
            ids.append(assertion["id"])
        if assertion.get("passed") is not True:
            issues.append(
                _problem(f"$.assertions[{index}].passed", "reported_failure")
            )
    if tuple(ids) != _REQUIRED_RECORDED_ASSERTIONS:
        issues.append(
            _problem(
                "$.assertions",
                "invalid_assertion_set",
                expected=list(_REQUIRED_RECORDED_ASSERTIONS),
                actual=ids,
            )
        )
    return issues


def _cleanup_issues(record: Any) -> list[dict[str, Any]]:
    cleanup = _get(record, ("cleanup",))
    if cleanup != {"passed": True, "residual_processes": 0}:
        return [
            _problem(
                "$.cleanup",
                "cleanup_failed",
                actual=cleanup,
            )
        ]
    return []


def _privacy_issues(record: Any) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    forbidden_key_fragments = (
        "token",
        "credential",
        "secret",
        "password",
        "absolute_path",
    )

    def walk(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                lower = str(key).lower()
                empty_path_inventory = lower == "absolute_paths" and child == []
                if not empty_path_inventory and (
                    lower == "path"
                    or any(
                        fragment in lower
                        for fragment in forbidden_key_fragments
                    )
                ):
                    issues.append(
                        _problem(f"{path}.{key}", "forbidden_private_key")
                    )
                walk(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")
        elif isinstance(value, str) and "://" not in value and (
            _WINDOWS_ABSOLUTE_RE.match(value)
            or value.startswith("\\\\")
            or PurePosixPath(value).is_absolute()
        ):
            issues.append(_problem(path, "absolute_path"))

    walk(record, "$")
    return issues


_ASSERTION_CHECKS: Mapping[str, Callable[[Any], list[dict[str, Any]]]] = {
    "record_metadata": _metadata_issues,
    "step_timing": _timing_issues,
    "direct_mcp_identity": _mcp_issues,
    "resident_contracts": _resident_contract_issues,
    "stable_references": _reference_issues,
    "kept_media_zero_refetch": _handoff_issues,
    "same_uoink_source": _same_source_issues,
    "writer_workflow": _writer_issues,
    "shot_list_import_identity": _import_issues,
    "same_zing_breakdown": _same_breakdown_issues,
    "measured_keeper_spans": _keeper_issues,
    "draft_provenance": _draft_issues,
    "engagement_accounting": _engagement_issues,
    "optional_peer_fail_calm": _peer_stop_issues,
    "recorded_assertions": _recorded_assertion_issues,
    "cleanup": _cleanup_issues,
    "record_privacy": _privacy_issues,
}


def evaluate_suite_record(record: Any) -> dict[str, Any]:
    """Score the family record from evidence, not its claimed overall result."""
    assertions: dict[str, dict[str, Any]] = {}
    for assertion_id in SUITE_SMOKE_ASSERTION_IDS:
        issues = _ASSERTION_CHECKS[assertion_id](record)
        assertions[assertion_id] = {
            "passed": not issues,
            "issues": issues,
        }
    failed = [
        assertion_id
        for assertion_id, assertion in assertions.items()
        if not assertion["passed"]
    ]
    return {
        "suite_smoke_eval_version": 1,
        "passed": not failed,
        "failed_assertions": failed,
        "assertions": assertions,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate one path-free Sprint 6 suite-smoke JSON record.",
    )
    parser.add_argument("record", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    record = json.loads(args.record.read_text(encoding="utf-8"))
    report = evaluate_suite_record(record)
    serialized = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.report is not None:
        args.report.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI
    raise SystemExit(main())
