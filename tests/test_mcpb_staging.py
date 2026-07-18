"""B-Q9: the .mcpb staging step is complete and correct (offline).

The npx pack step needs Node + network, so CI proves the part it can:
the staged tree contains exactly what the uv-type bundle needs, and the
manifest agrees with the layout it will run from.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packaging"))

import build_mcpb  # noqa: E402


def test_staged_tree_is_complete(tmp_path):
    staged = build_mcpb.stage(tmp_path / "stage")
    assert (staged / "manifest.json").is_file()
    assert (staged / "pyproject.toml").is_file()
    assert (staged / "LICENSE").is_file()
    assert (staged / "src" / "myzing" / "mcp_server.py").is_file()
    assert (staged / "prompts" / "study.md").is_file()
    assert not list(staged.rglob("__pycache__"))
    assert not list(staged.rglob("*.pyc"))


def test_manifest_agrees_with_staged_layout(tmp_path):
    staged = build_mcpb.stage(tmp_path / "stage")
    manifest = json.loads((staged / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["manifest_version"] == "0.4"
    assert manifest["name"] == "myzing"
    assert manifest["license"] == "MIT"
    server = manifest["server"]
    assert server["type"] == "uv"
    # entry_point must exist inside the bundle
    assert (staged / server["entry_point"]).is_file()
    # the run command must invoke the real CLI module with the mcp extra
    args = server["mcp_config"]["args"]
    assert "myzing.cli" in args and "serve-mcp" in args and "--extra" in args
    # the prompts pin must point inside the bundle
    env = server["mcp_config"]["env"]
    assert env["ZING_PROMPTS_DIR"].startswith("${__dirname}")
    assert (staged / "prompts").is_dir()


def test_manifest_version_matches_package(tmp_path):
    staged = build_mcpb.stage(tmp_path / "stage")
    manifest = json.loads((staged / "manifest.json").read_text(encoding="utf-8"))
    pyproject = (staged / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{manifest["version"]}"' in pyproject
