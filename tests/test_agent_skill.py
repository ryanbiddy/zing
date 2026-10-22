"""Keep the portable agent kit tied to the installed CLI and MCP surface."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest

from myzing.cli import _COMMANDS
from myzing.mcp_server import build_server


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "zing"
DOCS = [SKILL / "SKILL.md", *sorted((SKILL / "references").glob("*.md"))]
SUITE_SKILL = ROOT / "skills" / "uoink-zing"


def test_skill_frontmatter_and_portable_references():
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: zing\ndescription: ")
    assert len(text.splitlines()) < 300
    assert text.split("---", 2)[1].strip().splitlines()[1].removeprefix(
        "description: "
    ).strip()
    for doc in DOCS:
        for target in re.findall(r"\]\(([^)]+)\)", doc.read_text(encoding="utf-8")):
            if "://" in target:
                continue
            path = (doc.parent / target.split("#", 1)[0]).resolve()
            assert path.is_relative_to(SKILL.resolve()), (doc.name, target)
            assert path.is_file(), (doc.name, target)


def test_every_skill_command_exists_in_cli():
    mentioned = set()
    for doc in DOCS:
        text = doc.read_text(encoding="utf-8")
        if text.startswith("---\n"):
            text = text.split("---", 2)[2]
        names = set(re.findall(r"\bzing\s+([a-z][a-z0-9-]*)", text))
        assert names <= _COMMANDS.keys(), (doc.name, names - _COMMANDS.keys())
        mentioned.update(names)
    # The command reference promises a complete catalog, not just valid examples.
    assert mentioned == _COMMANDS.keys()


def test_every_skill_mcp_tool_exists_in_server():
    pytest.importorskip("mcp")
    registered = {tool.name for tool in asyncio.run(build_server().list_tools())}
    mentioned = set()
    for doc in DOCS:
        text = doc.read_text(encoding="utf-8")
        # Bare snake_case inline names or inline calls identify MCP tools.
        # Fields/expressions such as events[].overlap.safe do not match.
        names = set(re.findall(r"`([a-z][a-z0-9]*_[a-z0-9_]+)(?:`|\()", text))
        assert names <= registered, (doc.name, names - registered)
        mentioned.update(names)
    assert mentioned == registered
    for doc in (ROOT / "README.md", SKILL / "references" / "mcp.md"):
        assert re.search(rf"\b{len(registered)}(?: MCP)? tools\b", doc.read_text(encoding="utf-8"))


def test_suite_skill_commands_tools_and_portable_references():
    pytest.importorskip("mcp")
    text = (SUITE_SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\nname: uoink-zing\ndescription: ")
    assert len(text.splitlines()) < 200
    body = text.split("---", 2)[2]
    names = set(re.findall(r"\bzing\s+([a-z][a-z0-9-]*)", body))
    assert names <= _COMMANDS.keys()
    registry = json.loads((SUITE_SKILL / "references" / "uoink-tools.json").read_text(encoding="utf-8"))
    assert re.fullmatch(r"[0-9a-f]{40}", registry["commit"])
    assert re.fullmatch(r"[0-9a-f]{64}", registry["source_sha256"])
    assert registry["source_path"] == "uoink_mcp_tools.py:TOOL_REGISTRY"
    uoink_names = set(registry["tools"])
    zing_names = {tool.name for tool in asyncio.run(build_server().list_tools())}
    tools = set(re.findall(r"`([a-z][a-z0-9]*_[a-z0-9_]+)(?:`|\()", body))
    assert tools <= zing_names | uoink_names
    assert {"search_uoinks", "list_recent_uoinks", "get_library_item"} <= tools & uoink_names
    assert {"push_to_uoink", "match_start", "get_breakdown"} <= tools & zing_names
    for target in re.findall(r"\]\(([^)]+)\)", body):
        if "://" not in target:
            path = (SUITE_SKILL / target).resolve()
            assert path.is_relative_to(SUITE_SKILL.resolve()) and path.is_file()


@pytest.mark.parametrize("command", [
    ["project", "init"], ["project", "find-reference"],
    ["project", "resolve-reference"], ["project", "study-reference"],
    ["plan", "choose"], ["inspect", "timeline"],
])
def test_suite_skill_subcommands_exist(command, capsys):
    from myzing.cli import main

    with pytest.raises(SystemExit) as exit_info:
        main([*command, "--help"])
    assert exit_info.value.code == 0
    assert "usage:" in capsys.readouterr().out


def test_readme_links_every_top_level_doc():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for doc in (ROOT / "docs").glob("*.md"):
        assert f"](docs/{doc.name})" in readme, doc.name


def test_readme_quickstart_has_five_commands():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    block = re.search(r"```powershell\n(.*?)```", readme, re.S).group(1)
    assert len([line for line in block.splitlines() if line.strip()]) == 5
    assert "--offline" in block
    assert "zing-workspace/" in block
