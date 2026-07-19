"""Sprint 6 suite-contract conformance and cross-product flow gates."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tools.eval.suite_contracts import (
    CONTRACT_FIXTURE_VERSION,
    DEFAULT_SUITE_FIXTURES,
    evaluate_fixture_bundle,
    load_fixture_case,
    validate_contract_payload,
)
from tools.eval.suite_smoke import (
    SUITE_SMOKE_ASSERTION_IDS,
    evaluate_suite_record,
)


CONTRACT_SOURCE_SHA256 = (
    "bbb1dc212088dac69f08ba83a33e2ce97ce03223dfe01d07aa601b89f14cf182"
)
REQUIRED_CONFORMANCE_CASES = {
    "ryan.suite.runtime-lease/1": {
        "valid_uoink",
        "valid_writer",
        "unknown_key",
        "non_loopback_url",
        "token_field",
        "path_field",
        "command_field",
        "wrong_identity",
        "dead_pid",
    },
    "ryan.suite.service/1": {
        "valid_uoink",
        "valid_writer",
        "wrong_service",
        "wrong_version",
        "unknown_key",
        "command_field",
        "token_field",
    },
    "ryan.suite.health/1": {
        "valid_uoink",
        "valid_writer",
        "wrong_identity",
        "inconsistent_ok_checks",
        "path_field",
        "content_field",
        "unknown_state",
    },
    "ryan.suite.peer/1": {
        "available",
        "absent",
        "unconfigured",
        "authentication_failed",
        "wrong_service",
        "contract_drift",
        "timeout",
    },
    "uoink.media.handoff/1": {
        "available",
        "not_kept",
        "missing",
        "traversal",
        "outside_folder_symlink",
        "hash_mismatch",
        "size_mismatch",
        "unknown_item",
    },
    "writer.shot-list/1": {
        "valid",
        "wrong_front_matter",
        "duplicate_front_matter",
        "wrong_heading_order",
        "invalid_id",
        "invalid_time",
        "oversized",
        "non_utf8",
    },
    "zing.shot-list.import/1": {
        "imported",
        "duplicate_import",
        "absent_target",
        "unsupported_version",
        "path_free_receipt",
    },
    "uoink.engagement.ingest/1": {
        "accepted",
        "duplicate_id",
        "partial_rejection_accounting",
        "permanent_rejection",
        "retryable_rejection",
        "transaction_rollback",
    },
}


def _set(path: tuple[object, ...], value: Any):
    def mutate(record: dict[str, Any]) -> None:
        target: Any = record
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = value

    return mutate


def _delete(path: tuple[object, ...]):
    def mutate(record: dict[str, Any]) -> None:
        target: Any = record
        for part in path[:-1]:
            target = target[part]
        del target[path[-1]]

    return mutate


def _append(path: tuple[object, ...], value: Any):
    def mutate(record: dict[str, Any]) -> None:
        target: Any = record
        for part in path:
            target = target[part]
        target.append(value)

    return mutate


def _set_invalid_keeper_span(record: dict[str, Any]) -> None:
    record["zing_flow"]["keeper_spans"][0]["end"] = 1.0
    record["zing_flow"]["draft_provenance"]["keeper_spans"][0]["end"] = 1.0


def test_checked_in_fixture_bundle_covers_the_ratified_contract() -> None:
    report = evaluate_fixture_bundle()

    assert CONTRACT_FIXTURE_VERSION == 1
    assert DEFAULT_SUITE_FIXTURES.is_dir()
    assert report["passed"] is True
    assert report["fixture_version"] == CONTRACT_FIXTURE_VERSION
    assert report["contract_source"] == {
        "contract": "ryan.suite.integration",
        "version": 1,
        "sha256": CONTRACT_SOURCE_SHA256,
    }
    assert set(report["contracts"]) == set(REQUIRED_CONFORMANCE_CASES)
    for contract, required_cases in REQUIRED_CONFORMANCE_CASES.items():
        contract_report = report["contracts"][contract]
        assert contract_report["passed"] is True
        assert required_cases <= set(contract_report["case_ids"])
        assert contract_report["failed_case_ids"] == []


@pytest.mark.parametrize(
    ("case_id", "contract"),
    [
        ("runtime_lease_valid_uoink", "ryan.suite.runtime-lease/1"),
        ("service_valid_uoink", "ryan.suite.service/1"),
        ("health_valid_uoink", "ryan.suite.health/1"),
        ("peer_available", "ryan.suite.peer/1"),
        ("media_available", "uoink.media.handoff/1"),
        ("import_imported", "zing.shot-list.import/1"),
        ("engagement_accepted", "uoink.engagement.ingest/1"),
    ],
)
def test_json_contracts_fail_closed_on_unknown_keys_and_higher_versions(
    case_id: str,
    contract: str,
) -> None:
    case = load_fixture_case(case_id)
    payload = copy.deepcopy(case["payload"])
    context = case.get("context", {})

    payload["unexpected"] = True
    unknown_key = validate_contract_payload(contract, payload, **context)
    assert unknown_key["passed"] is False
    assert unknown_key["issues"][0]["kind"] == "unknown_keys"

    payload = copy.deepcopy(case["payload"])
    payload["version"] = 2
    higher_version = validate_contract_payload(contract, payload, **context)
    assert higher_version["passed"] is False
    assert any(
        issue["kind"] == "invalid_value"
        and issue["path"] == "$.version"
        for issue in higher_version["issues"]
    )


def test_checked_in_suite_smoke_record_passes_every_independent_assertion() -> None:
    record = load_fixture_case("suite_smoke_pass")["payload"]

    report = evaluate_suite_record(record)

    assert report["passed"] is True
    assert report["failed_assertions"] == []
    assert set(report["assertions"]) == set(SUITE_SMOKE_ASSERTION_IDS)
    assert all(
        assertion["passed"] for assertion in report["assertions"].values()
    )


@pytest.mark.parametrize(
    ("mutate", "failed_assertion"),
    [
        (
            _set(("handoff", "refetch"), True),
            "kept_media_zero_refetch",
        ),
        (
            _set(
                ("writer_flow", "corpus_item_ref"),
                "uoink://item/other-source",
            ),
            "same_uoink_source",
        ),
        (
            _set(
                ("zing_flow", "import_receipt", "data", "document", "sha256"),
                "f" * 64,
            ),
            "shot_list_import_identity",
        ),
        (
            _set(
                ("zing_flow", "import_receipt", "data", "target_ref"),
                "zing://breakdown/other",
            ),
            "same_zing_breakdown",
        ),
        (
            _set_invalid_keeper_span,
            "measured_keeper_spans",
        ),
        (
            _set(
                ("zing_flow", "draft_provenance", "keeper_span_source"),
                "writer_shot_list",
            ),
            "draft_provenance",
        ),
        (
            _delete(("engagement", "receipts", 1)),
            "engagement_accounting",
        ),
        (
            _set(
                (
                    "optional_peer_stop",
                    "remaining_products",
                    0,
                    "standalone_ok",
                ),
                False,
            ),
            "optional_peer_fail_calm",
        ),
        (
            _set(("steps", 0, "duration_seconds"), 99.0),
            "step_timing",
        ),
        (
            _set(("mcp_identities", 2), "suite-proxy"),
            "direct_mcp_identity",
        ),
        (
            _append(
                ("artifacts",),
                {
                    "id": "private-path",
                    "sha256": "a" * 64,
                    "path": "C:\\Users\\Ryan\\private.mp4",
                },
            ),
            "record_privacy",
        ),
    ],
)
def test_suite_smoke_mutations_fail_only_the_targeted_assertion(
    mutate,
    failed_assertion: str,
) -> None:
    record = copy.deepcopy(load_fixture_case("suite_smoke_pass")["payload"])
    mutate(record)

    report = evaluate_suite_record(record)

    assert report["passed"] is False
    assert report["failed_assertions"] == [failed_assertion]
    assert report["assertions"][failed_assertion]["issues"]
    assert [
        assertion_id
        for assertion_id, assertion in report["assertions"].items()
        if assertion["passed"]
    ] == [
        assertion_id
        for assertion_id in SUITE_SMOKE_ASSERTION_IDS
        if assertion_id != failed_assertion
    ]


def test_fixture_bundle_contains_no_private_absolute_paths_or_credentials() -> None:
    report = evaluate_fixture_bundle()

    assert report["privacy"]["passed"] is True
    assert report["privacy"]["issues"] == []
    assert report["privacy"]["scanned_files"] >= 9
    for path in DEFAULT_SUITE_FIXTURES.rglob("*"):
        if path.is_file():
            assert path.resolve().is_relative_to(DEFAULT_SUITE_FIXTURES)


def test_malformed_contracts_and_family_record_fail_without_crashing() -> None:
    contexts = {
        "ryan.suite.runtime-lease/1": {
            "expected_service": "uoink",
            "live_pids": [],
        },
        "ryan.suite.service/1": {"expected_service": "uoink"},
        "ryan.suite.health/1": {"expected_service": "uoink"},
        "ryan.suite.peer/1": {"expected_peer": "uoink"},
    }
    for contract in REQUIRED_CONFORMANCE_CASES:
        report = validate_contract_payload(
            contract,
            None,
            **contexts.get(contract, {}),
        )
        assert report["passed"] is False
        assert report["issues"]

    smoke_report = evaluate_suite_record(None)
    assert smoke_report["passed"] is False
    assert smoke_report["failed_assertions"]


def test_suite_smoke_cli_writes_the_same_machine_readable_report(
    tmp_path: Path,
) -> None:
    record_path = tmp_path / "suite-smoke.json"
    report_path = tmp_path / "suite-smoke-eval.json"
    record_path.write_text(
        json.dumps(load_fixture_case("suite_smoke_pass")["payload"]),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.eval.suite_smoke",
            str(record_path),
            "--report",
            str(report_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    printed = json.loads(completed.stdout)
    written = json.loads(report_path.read_text(encoding="utf-8"))
    assert printed == written == evaluate_suite_record(
        load_fixture_case("suite_smoke_pass")["payload"]
    )
