"""Regression tests for required clean-install study coverage."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "packaging" / "clean_host_check.py"
)
SPEC = importlib.util.spec_from_file_location(
    "zing_clean_host_check", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
clean_host_check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(clean_host_check)


def _study(status: str) -> list[dict]:
    return [{
        "step": "study-cached-media",
        "status": status,
        "detail": "mutation",
        "output_tail": "",
    }]


def _mcp(status: str) -> list[dict]:
    return [{
        "step": "mcp-stdio",
        "status": status,
        "detail": "mutation",
        "output_tail": "",
    }]


def test_require_study_turns_a_skip_into_a_failure(tmp_path) -> None:
    report = tmp_path / "report.json"
    steps = _study("SKIP")

    result = clean_host_check._finish(
        steps, report, require_study=True
    )

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert result == 1
    assert payload["failed"] == 1
    assert payload["steps"][0]["status"] == "FAIL"
    assert "required study was skipped" in payload["steps"][0]["detail"]


def test_require_study_fails_when_the_step_was_not_reached() -> None:
    steps = []

    result = clean_host_check._finish(
        steps, None, require_study=True
    )

    assert result == 1
    assert steps == [{
        "step": "study-cached-media",
        "status": "FAIL",
        "detail": "required study step was not reached",
        "output_tail": "",
    }]


def test_optional_study_can_still_be_skipped() -> None:
    steps = _study("SKIP")

    result = clean_host_check._finish(steps, None)

    assert result == 0
    assert steps[0]["status"] == "SKIP"


def test_required_mcp_turns_a_skip_into_a_failure() -> None:
    steps = _mcp("SKIP")

    result = clean_host_check._finish(
        steps, None, require_mcp=True
    )

    assert result == 1
    assert steps[0]["status"] == "FAIL"
    assert "required MCP was skipped" in steps[0]["detail"]


def test_required_mcp_fails_when_the_step_was_not_reached() -> None:
    steps = _study("PASS")

    result = clean_host_check._finish(
        steps, None, require_mcp=True
    )

    assert result == 1
    assert steps[-1] == {
        "step": "mcp-stdio",
        "status": "FAIL",
        "detail": "required MCP step was not reached",
        "output_tail": "",
    }


def test_ci_invokes_the_required_mode() -> None:
    workflow = (
        clean_host_check.REPO / ".github" / "workflows" / "ci.yml"
    ).read_text(encoding="utf-8")

    assert (
        "python packaging/clean_host_check.py --require-study --report"
        in workflow
    )


def test_clean_host_gate_launches_installed_mcp_smoke() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")

    assert 'REPO / "packaging" / "mcp_stdio_smoke.py"' in source
    assert 'mcp_payload["tool_count"] == 19' in source
    assert "require_mcp=True" in source
