"""Publishing needs the suite workflow and GitHub's CodeQL result on the commit."""
import pytest

from test_release_gate import ci_run, gate

CI = "repos/owner/zing/actions/workflows/ci.yml/runs?head_sha=abc123&event=push&per_page=100"
SUITE = CI.replace("ci.yml", "suite-smoke.yml")
CODEQL = "repos/owner/zing/commits/abc123/check-runs?filter=all&per_page=100"


def codeql(**fields):
    return {"id": 20, "name": "CodeQL", "head_sha": "abc123", "status": "completed", "conclusion": "success",
            "app": {"slug": "github-code-scanning"}, **fields}


@pytest.mark.parametrize("runs", [[], [ci_run(head_sha="other")], [ci_run(conclusion="failure")],
                                  [ci_run(status="in_progress", conclusion=None)],
                                  [ci_run(id=10), ci_run(id=12, conclusion="cancelled")]])
def test_release_requires_suite_smoke(gate, runs):
    module, replies, _ = gate
    replies[CI] = [{"workflow_runs": [ci_run()]}]
    replies[SUITE] = [{"workflow_runs": runs}]
    with pytest.raises(RuntimeError, match="suite-smoke"):
        module.check_ci("owner/zing", "abc123")


@pytest.mark.parametrize("checks", [[], [codeql(head_sha="other")], [codeql(conclusion="failure")],
                                    [codeql(status="in_progress", conclusion=None)], [codeql(conclusion="neutral")],
                                    [codeql(app={"slug": "github-actions"})], [codeql(name="unrelated")],
                                    [codeql(id=10), codeql(id=20, conclusion="failure")]])
def test_release_requires_latest_code_scanning_success(gate, checks):
    module, replies, _ = gate
    for key in (CI, SUITE):
        replies[key] = [{"workflow_runs": [ci_run()]}]
    replies[CODEQL] = [{"check_runs": checks}]
    with pytest.raises(RuntimeError, match="CodeQL"):
        module.check_ci("owner/zing", "abc123")


def test_release_accepts_all_required_results_on_exact_commit(gate):
    module, replies, calls = gate
    for key in (CI, SUITE):
        replies[key] = [{"workflow_runs": [ci_run()]}]
    replies[CODEQL] = [{"check_runs": [codeql()]}]
    module.check_ci("owner/zing", "abc123")
    assert calls == [CI, SUITE, CODEQL]
