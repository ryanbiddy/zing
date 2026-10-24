"""The unpublished registry entry must stay aligned with package metadata."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts.check_registry_server_json import check


ROOT = Path(__file__).resolve().parents[1]


def test_registry_check_command():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_registry_server_json.py")],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "offline check only" in result.stdout


@pytest.fixture
def listing(tmp_path):
    for name in ("server.json", "pyproject.toml", "README.md"):
        shutil.copyfile(ROOT / name, tmp_path / name)
    return tmp_path / "server.json"


@pytest.mark.parametrize("key,value", [
    ("name", "io.github.example/other"),
    ("version", "999.0.0"),
    ("$schema", "https://example.com/schema.json"),
    ("description", "x" * 101),
    ("description", " "),
    ("description", None),
    ("packages", []),
])
def test_rejects_listing_drift(listing, key, value):
    data = json.loads(listing.read_text(encoding="utf-8"))
    data[key] = value
    listing.write_text(json.dumps(data), encoding="utf-8")
    assert check(listing)


@pytest.mark.parametrize("key,value", [
    ("registryType", "npm"),
    ("identifier", "zing"),
    ("version", "999.0.0"),
    ("transport", {"type": "streamable-http"}),
])
def test_rejects_package_drift(listing, key, value):
    data = json.loads(listing.read_text(encoding="utf-8"))
    data["packages"][0][key] = value
    listing.write_text(json.dumps(data), encoding="utf-8")
    assert check(listing)


def test_checks_actual_pypi_readme_source(listing):
    project = listing.parent / "pyproject.toml"
    project.write_text(project.read_text(encoding="utf-8").replace(
        'readme = "README.md"', 'readme = {file = "PYPI.md", content-type = "text/markdown"}'
    ), encoding="utf-8")
    pypi = listing.parent / "PYPI.md"
    pypi.write_text("No marker here", encoding="utf-8")
    assert any("PYPI.md" in error for error in check(listing))
    pypi.write_text("mcp-name: io.github.ryanbiddy/zing", encoding="utf-8")
    assert check(listing) == []
    (listing.parent / "README.md").write_text("No marker here", encoding="utf-8")
    assert any("README.md" in error for error in check(listing))


def test_version_is_compared_to_pyproject(listing):
    project = listing.parent / "pyproject.toml"
    project.write_text(project.read_text(encoding="utf-8").replace(
        'version = "1.0.0rc1"', 'version = "999.0.0"'
    ), encoding="utf-8")
    assert any("version" in error for error in check(listing))


def test_registry_workflow_is_manual_only_and_checks_before_login():
    # Read trigger keys without relying on an optional YAML parser or YAML 1.1's
    # interpretation of the GitHub Actions key "on" as a boolean.
    workflow = (ROOT / ".github/workflows/mcp-registry.yml").read_text(encoding="utf-8")
    triggers = workflow.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
    keys = [line.strip().split(":", 1)[0] for line in triggers.splitlines()
            if line.startswith("  ") and not line.startswith("   ")]
    assert keys == ["workflow_dispatch"]
    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert workflow.index("scripts/check_registry_server_json.py") < workflow.index("login github-oidc")
    assert workflow.index("PyPI marker missing") < workflow.index("login github-oidc")
    assert "id-token: write" in workflow
