"""Sprint 3 direction-format conformance and mutation gates."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from tools.eval.direction_format import (
    DEFAULT_CRITERION_INDEX,
    DEFAULT_JARGON_LIST,
    evaluate_direction_paths,
    load_criterion_ids,
    validate_direction,
)
from tools.eval.run import SAMPLE_DIRECTORY, evaluate


VALID_DIRECTION = {
    "verdict": "Keep the clear explanation, but refilm the opening.",
    "gaps": [
        {
            "criterion_id": "H1",
            "profile_evidence": "The profile begins speaking before 1.5 seconds.",
            "footage_evidence": "The first usable words begin at 6.2 seconds.",
            "severity": "high",
        }
    ],
    "shot_prompts": [
        {
            "n": 1,
            "instruction": (
                "Look at the camera and say the result first. "
                "Keep this take to two seconds."
            ),
            "closes_gap": "H1",
            "duration_hint": "2 seconds",
        }
    ],
    "keepers": [
        {
            "start": 8.0,
            "end": 15.2,
            "why": "The explanation is clear and has clean audio.",
        }
    ],
    "assembly_notes": "Open with shot 1, then use the keeper.",
}


def _missing(path: tuple[object, ...]):
    def mutate(direction: dict) -> None:
        target = direction
        for part in path[:-1]:
            target = target[part]
        del target[path[-1]]

    return mutate


def _set(path: tuple[object, ...], value):
    def mutate(direction: dict) -> None:
        target = direction
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = value

    return mutate


def test_index_parser_and_checked_in_direction_pass() -> None:
    criterion_ids = load_criterion_ids(DEFAULT_CRITERION_INDEX)

    assert {"H1", "G-TH-1", "U2a", "U2b"} <= criterion_ids
    assert "ID" not in criterion_ids
    table_ids = {
        line.split("|")[1].strip()
        for line in DEFAULT_CRITERION_INDEX.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.startswith("|")
        and line.split("|")[1].strip() not in {"ID", "---"}
    }
    assert criterion_ids == table_ids
    result = validate_direction(VALID_DIRECTION)

    assert result["passed"] is True
    assert result["failed_dimensions"] == []
    assert all(
        dimension["passed"] for dimension in result["dimensions"].values()
    )


@pytest.mark.parametrize(
    ("mutate", "failed_dimension", "issue_kind", "issue_path"),
    [
        (
            _missing(("verdict",)),
            "shape",
            "missing_key",
            "direct.verdict",
        ),
        (
            _missing(("gaps", 0, "severity")),
            "shape",
            "missing_key",
            "direct.gaps[0].severity",
        ),
        (
            _missing(("shot_prompts", 0, "duration_hint")),
            "shape",
            "missing_key",
            "direct.shot_prompts[0].duration_hint",
        ),
        (
            _missing(("keepers", 0, "why")),
            "shape",
            "missing_key",
            "direct.keepers[0].why",
        ),
        (
            _set(("shot_prompts", 0, "n"), "1"),
            "shape",
            "wrong_type",
            "direct.shot_prompts[0].n",
        ),
        (
            _set(("gaps", 0, "criterion_id"), "H99999"),
            "criterion_ids",
            "unknown_criterion_id",
            "direct.gaps[0].criterion_id",
        ),
        (
            _set(
                ("shot_prompts", 0, "instruction"),
                "Face the camera. State the result. Pause.",
            ),
            "shot_prompt_language",
            "too_many_sentences",
            "direct.shot_prompts[0].instruction",
        ),
        (
            _set(
                ("shot_prompts", 0, "instruction"),
                "Use a rack focus from the mug to your face.",
            ),
            "shot_prompt_language",
            "jargon",
            "direct.shot_prompts[0].instruction",
        ),
    ],
)
def test_direction_mutations_fail_only_the_targeted_conformance_dimension(
    mutate,
    failed_dimension: str,
    issue_kind: str,
    issue_path: str,
) -> None:
    direction = copy.deepcopy(VALID_DIRECTION)
    mutate(direction)

    result = validate_direction(direction)

    assert result["passed"] is False
    assert result["failed_dimensions"] == [failed_dimension]
    issues = result["dimensions"][failed_dimension]["issues"]
    assert [(issue["kind"], issue["path"]) for issue in issues] == [
        (issue_kind, issue_path)
    ]
    assert [
        name for name, dimension in result["dimensions"].items()
        if dimension["passed"]
    ] == [
        name for name in result["dimensions"] if name != failed_dimension
    ]


def test_direction_eval_records_contract_inputs_and_hashes(tmp_path: Path) -> None:
    direction_path = tmp_path / "direction.json"
    direction_path.write_text(
        json.dumps(
            {"judgment": {"direct": VALID_DIRECTION}},
            indent=2,
        ),
        encoding="utf-8",
    )

    result = evaluate_direction_paths([direction_path])

    assert result["available"] is True
    assert result["status"] == "scored"
    assert result["passed"] is True
    assert result["case_count"] == 1
    assert result["criterion_index"]["path"] == "docs/taste/INDEX.md"
    assert result["criterion_index"]["criterion_count"] > 100
    assert len(result["criterion_index"]["sha256"]) == 64
    assert result["jargon_list"]["path"] == "tools/eval/direction-jargon.json"
    assert result["jargon_list"]["term_count"] >= 5
    assert len(result["jargon_list"]["sha256"]) == 64
    assert len(result["cases"][0]["fixture_sha256"]) == 64


def test_eval_report_includes_direction_conformance(tmp_path: Path) -> None:
    direction_path = tmp_path / "direction.json"
    direction_path.write_text(
        json.dumps(VALID_DIRECTION),
        encoding="utf-8",
    )
    report_path = tmp_path / "report.json"

    report = evaluate(
        [SAMPLE_DIRECTORY],
        report_path,
        ffmpeg="not-installed-ffmpeg",
        direction_paths=[direction_path],
    )

    assert report["report_schema_version"] == 5
    assert report["passed"] is True
    assert report["direction_eval"]["passed"] is True
    assert report["direction_eval"]["cases"][0]["score"]["passed"] is True
    assert (
        json.loads(report_path.read_text(encoding="utf-8"))["direction_eval"]
        == report["direction_eval"]
    )


def test_direction_failure_gates_report_without_cross_failing_breakdown(
    tmp_path: Path,
) -> None:
    direction = copy.deepcopy(VALID_DIRECTION)
    direction["gaps"][0]["criterion_id"] = "NOT-IN-INDEX"
    direction_path = tmp_path / "invalid-direction.json"
    direction_path.write_text(json.dumps(direction), encoding="utf-8")

    report = evaluate(
        [SAMPLE_DIRECTORY],
        tmp_path / "report.json",
        ffmpeg="not-installed-ffmpeg",
        direction_paths=[direction_path],
    )

    assert report["passed"] is False
    assert report["cases"][0]["score"]["passed"] is True
    assert report["direction_eval"]["passed"] is False
    assert report["direction_eval"]["cases"][0]["score"][
        "failed_dimensions"
    ] == ["criterion_ids"]


def test_default_contract_inputs_are_checked_in() -> None:
    assert DEFAULT_CRITERION_INDEX.is_file()
    assert DEFAULT_JARGON_LIST.is_file()


def test_module_cli_can_score_checked_in_direction_fixture(
    tmp_path: Path,
) -> None:
    report_path = tmp_path / "direction-report.json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.eval.run",
            "--sample",
            "--directions",
            "--report",
            str(report_path),
            "--ffmpeg",
            "not-installed-ffmpeg",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["direction_eval"]["passed"] is True
    assert report["direction_eval"]["case_count"] == 1
