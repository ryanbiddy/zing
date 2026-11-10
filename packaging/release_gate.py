"""Require CI and find an earlier TestPyPI upload for the exact release commit."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def rows(path, key):
    result = subprocess.run(["gh", "api", "--paginate", "--slurp", path],
                            check=True, capture_output=True, text=True)
    return [row for page in json.loads(result.stdout) for row in page[key]]


def runs(repo, workflow, sha, event):
    found = rows(f"repos/{repo}/actions/workflows/{workflow}/runs?head_sha={sha}&event={event}&per_page=100", "workflow_runs")
    return [run for run in found if run["head_sha"] == sha and run["head_branch"] == "main" and run["event"] == event]


def check_ci(repo, sha):
    latest = max(runs(repo, "ci.yml", sha, "push"), key=lambda run: run["id"], default={})
    if latest.get("status") != "completed" or latest.get("conclusion") != "success":
        raise RuntimeError(f"CI has not succeeded for commit {sha}. Run ci.yml on this exact commit before publishing.")


def testpypi_published(repo, sha, current_run):
    for run in runs(repo, "release.yml", sha, "workflow_dispatch"):
        if str(run["id"]) == current_run:
            continue
        jobs = rows(f"repos/{repo}/actions/runs/{run['id']}/jobs?filter=latest&per_page=100", "jobs")
        if any(job["name"] == "testpypi" and job["conclusion"] == "success" and
               any(step["name"] == "Publish to TestPyPI using OIDC" and step["conclusion"] == "success"
                   for step in job.get("steps", [])) for job in jobs):
            return True
    return False


def main():
    repo, sha = os.environ["GITHUB_REPOSITORY"], os.environ["RELEASE_COMMIT"]
    try:
        check_ci(repo, sha)
        published = testpypi_published(repo, sha, os.environ["GITHUB_RUN_ID"])
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (subprocess.CalledProcessError, OSError, ValueError, KeyError):
        print("GitHub Actions history could not be checked. Publication is blocked.", file=sys.stderr)
        return 1
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"testpypi_published={str(published).lower()}\n")
    print(f"CI passed for commit {sha}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
