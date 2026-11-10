"""Publication order, exact revisions and install coverage."""
import re

from test_release_packaging import ROOT, load


def jobs():
    text = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    return dict(re.findall(r"^  ([\w-]+):\n(.*?)(?=^  [\w-]+:|\Z)", text.split("\njobs:\n")[1], re.M | re.S))


def needs(job):
    value = re.search(r"^    needs: (.+)$", job, re.M)
    return set(value.group(1).strip("[]").replace(",", " ").split()) if value else set()


def test_ci_gates_every_upload_for_exact_commit():
    workflow = jobs()
    assert "check-ci" in workflow
    gate = workflow["check-ci"]
    assert "actions: read" in gate and "contents: read" in gate
    assert "write" not in gate
    assert "GH_TOKEN: ${{ github.token }}" in gate
    assert "RELEASE_COMMIT: ${{ github.sha }}" in gate
    assert "python packaging/release_gate.py" in gate
    for job in workflow.values():
        if "pypa/gh-action-pypi-publish@" in job:
            assert {"build", "fresh-install", "check-ci"} <= needs(job)


def test_pypi_requires_testpypi_success():
    workflow = jobs()
    assert "testpypi" in workflow
    assert "testpypi" in needs(workflow["publish"])
    assert "needs.testpypi.result == 'success'" in workflow["publish"]
    assert "needs.check-ci.outputs.testpypi_published == 'true'" in workflow["publish"]
    assert "name: testpypi" in workflow["testpypi"]
    assert "name: pypi" in workflow["publish"]
    assert "https://test.pypi.org/legacy/" in workflow["testpypi"]
    for gate in ("build", "fresh-install", "check-ci"):
        assert f"needs.{gate}.result == 'success'" in workflow["publish"]
    assert "always() && !cancelled() && inputs.target == 'pypi'" in workflow["publish"]


def test_build_tools_have_exact_versions():
    build = jobs()["build"]
    assert re.search(r"pip install uv==\d+\.\d+\.\d+\b", build)
    assert re.search(r"pip install .* twine==\d+\.\d+\.\d+\b", build)
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for pin in re.findall(r"(?:uv|twine)==\d+\.\d+\.\d+", build):
        assert pin in ci


def test_fresh_installs_cover_every_python_and_os():
    job = jobs()["fresh-install"]
    versions = re.search(r"^        python: \[(.+)\]$", job, re.M)
    assert versions
    assert set(re.findall(r"3\.\d+", versions.group(1))) == {"3.11", "3.12", "3.13", "3.14"}
    assert "os: [ubuntu-latest, windows-latest, macos-latest]" in job
    assert "python-version: ${{ matrix.python }}" in job
    assert "name: fresh-install-${{ matrix.os }}-${{ matrix.python }}" in job


def test_releasing_guide_covers_publication_prerequisites():
    text = (ROOT / "docs/RELEASING.md").read_text(encoding="utf-8")
    count = len(load("mcp_stdio_smoke").EXPECTED_TOOLS)
    assert f"{count} MCP tools" in text
    for phrase in ("Unreleased", "exact commit", "0.0.1", "single-use", ".devN", "pending publisher",
                   "test.pypi.org", "pypi.org", "required reviewer", "administrator bypass"):
        assert phrase in text
