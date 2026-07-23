"""Contract tests for the scheduled three-product family gate."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "suite-smoke.yml"
DOC = ROOT / "docs" / "SUITE-SMOKE-CI.md"
NODE24_ACTION_MAJORS = {
    "actions/checkout": 5,
    "actions/setup-python": 6,
    "actions/upload-artifact": 6,
}


def test_ci_workflows_use_node24_action_runtimes() -> None:
    seen: set[str] = set()
    for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
        text = workflow.read_text(encoding="utf-8")
        for action, major_text in re.findall(
            r"uses:\s+(actions/(?:checkout|setup-python|upload-artifact))@v(\d+)",
            text,
        ):
            seen.add(action)
            assert int(major_text) >= NODE24_ACTION_MAJORS[action], (
                f"{workflow.name} uses Node 20 action {action}@v{major_text}"
            )

    assert seen == set(NODE24_ACTION_MAJORS)


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
        "actions/upload-artifact@v6",
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
