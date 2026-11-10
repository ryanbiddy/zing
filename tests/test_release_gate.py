"""Release history is checked offline with GitHub replies supplied by fixtures."""
import json
import subprocess

import pytest

from test_release_packaging import load


@pytest.fixture
def gate(monkeypatch):
    module = load("release_gate")
    replies = {}
    calls = []

    def run(argv, **kwargs):
        assert argv[:4] == ["gh", "api", "--paginate", "--slurp"]
        assert kwargs == {"check": True, "capture_output": True, "text": True}
        calls.append(argv[-1])
        return subprocess.CompletedProcess(argv, 0, json.dumps(replies[argv[-1]]), "")

    monkeypatch.setattr(module.subprocess, "run", run)
    return module, replies, calls


def ci_run(**fields):
    return {"id": 12, "head_sha": "abc123", "head_branch": "main", "event": "push",
            "status": "completed", "conclusion": "success", **fields}


@pytest.mark.parametrize("runs", [[], [ci_run(head_sha="other")], [ci_run(conclusion="failure")],
                                      [ci_run(status="in_progress", conclusion=None)],
                                      [ci_run(event="pull_request")], [ci_run(head_branch="other")],
                                      [ci_run(id=10), ci_run(id=12, conclusion="failure")]])
def test_ci_requires_latest_success_on_exact_main_commit(gate, runs):
    module, replies, calls = gate
    replies["repos/owner/zing/actions/workflows/ci.yml/runs?head_sha=abc123&event=push&per_page=100"] = [{"workflow_runs": runs}]
    with pytest.raises(RuntimeError, match="CI has not succeeded for commit abc123"):
        module.check_ci("owner/zing", "abc123")
    assert len(calls) == 1


def test_ci_accepts_exact_commit_success(gate):
    module, replies, _ = gate
    replies["repos/owner/zing/actions/workflows/ci.yml/runs?head_sha=abc123&event=push&per_page=100"] = [{"workflow_runs": [ci_run()]}]
    module.check_ci("owner/zing", "abc123")


@pytest.mark.parametrize("job,expected", [
    ({"name": "testpypi", "conclusion": "success", "steps": [
        {"name": "Publish to TestPyPI using OIDC", "conclusion": "success"}]}, True),
    ({"name": "testpypi", "conclusion": "failure", "steps": []}, False),
    ({"name": "testpypi", "conclusion": "skipped", "steps": []}, False),
    ({"name": "testpypi", "conclusion": "success", "steps": []}, False),
    ({"name": "publish", "conclusion": "success", "steps": [
        {"name": "Publish to PyPI using OIDC", "conclusion": "success"}]}, False),
])
def test_testpypi_requires_successful_upload_step(gate, job, expected):
    module, replies, _ = gate
    replies["repos/owner/zing/actions/workflows/release.yml/runs?head_sha=abc123&event=workflow_dispatch&per_page=100"] = [
        {"workflow_runs": [ci_run(id=42, event="workflow_dispatch", conclusion="failure")]}]
    replies["repos/owner/zing/actions/runs/42/jobs?filter=latest&per_page=100"] = [{"jobs": []}, {"jobs": [job]}]
    assert module.testpypi_published("owner/zing", "abc123", "99") is expected


def test_other_commits_branches_and_current_run_cannot_satisfy_testpypi(gate):
    module, replies, calls = gate
    replies["repos/owner/zing/actions/workflows/release.yml/runs?head_sha=abc123&event=workflow_dispatch&per_page=100"] = [
        {"workflow_runs": [ci_run(id=99, event="workflow_dispatch"),
                           ci_run(id=41, event="workflow_dispatch", head_sha="other"),
                           ci_run(id=42, event="workflow_dispatch", head_branch="other"),
                           ci_run(id=43, event="push")]}]
    assert not module.testpypi_published("owner/zing", "abc123", "99")
    assert len(calls) == 1


@pytest.mark.parametrize("error", [RuntimeError("CI has not succeeded for commit abc123."),
                                 subprocess.CalledProcessError(1, "gh"), ValueError("invalid JSON")])
def test_gate_failure_exits_without_recording_success(gate, monkeypatch, tmp_path, capsys, error):
    module, _, _ = gate
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/zing")
    monkeypatch.setenv("RELEASE_COMMIT", "abc123")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    def fail(*args):
        raise error

    monkeypatch.setattr(module, "check_ci", fail)
    assert module.main() == 1
    assert not output.exists()
    assert capsys.readouterr().err


@pytest.mark.parametrize("published", [True, False])
def test_gate_records_verified_history(gate, monkeypatch, tmp_path, published):
    module, _, _ = gate
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/zing")
    monkeypatch.setenv("RELEASE_COMMIT", "abc123")
    monkeypatch.setenv("GITHUB_RUN_ID", "99")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setattr(module, "check_ci", lambda *args: None)
    monkeypatch.setattr(module, "testpypi_published", lambda *args: published)
    assert module.main() == 0
    assert output.read_text(encoding="utf-8") == f"testpypi_published={str(published).lower()}\n"
