"""Contract tests for the scheduled three-product family gate."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "suite-smoke.yml"
DOC = ROOT / "docs" / "SUITE-SMOKE-CI.md"


def test_suite_smoke_workflow_runs_the_safe_family_gate() -> None:
    assert WORKFLOW.is_file()
    text = WORKFLOW.read_text(encoding="utf-8")

    for trigger in (
        "schedule:",
        "workflow_dispatch:",
        "pull_request:",
        "push:",
    ):
        assert trigger in text
    assert re.search(r"cron:\s*[\"']\d+ \d+ \* \* \*[\"']", text)

    for checkout in (
        "repository: ryanbiddy/uoink",
        "repository: ryanbiddy/writer",
        "path: uoink",
        "path: writer",
        "path: zing",
    ):
        assert checkout in text

    for gate in (
        "--mode deterministic_ci",
        "python -m tools.eval.suite_smoke",
        "suite-smoke.json",
        "suite-smoke-eval.json",
        "actions/upload-artifact@v4",
        "if: always()",
        "if-no-files-found: error",
        "retention-days:",
    ):
        assert gate in text

    assert "HF_HUB_OFFLINE: \"1\"" in text
    assert "TRANSFORMERS_OFFLINE: \"1\"" in text
    assert "timeout-minutes:" in text
    # GitHub's runner context is unavailable while a job-level env block is
    # evaluated. Using it there rejects the workflow before any job exists.
    job_prelude = text.split("steps:", maxsplit=1)[0]
    assert "${{ runner." not in job_prelude
    assert "real_capture" not in text
    assert "--source-url" not in text
    assert "secrets." not in text


def test_suite_smoke_ci_doc_states_what_the_runner_does_not_prove() -> None:
    assert DOC.is_file()
    text = DOC.read_text(encoding="utf-8")

    for required in (
        "deterministic_ci",
        "real_capture",
        "suite-smoke.json",
        "suite-smoke-eval.json",
        "Uoink",
        "Writer",
        "Zing",
        "does not prove",
        "download an AI model",
        "publish",
        "post",
        "spend",
    ):
        assert required in text
