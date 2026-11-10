"""Current docs must describe the release and the registered MCP surface."""
import asyncio
from pathlib import Path
import re
import tomllib

import pytest


ROOT = Path(__file__).resolve().parents[1]
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
HISTORY = {"CHANGELOG.md"}
DOCS = [path for path in [
    ROOT / "README.md", ROOT / "CHANGELOG.md", *sorted(ROOT.glob("llms*.md")),
    *sorted((ROOT / "docs").rglob("*.md")),
    *sorted((ROOT / "skills").rglob("*.md")),
    *sorted((ROOT / "plugins").rglob("*.md")),
] if path.relative_to(ROOT).as_posix() not in HISTORY]
NUMBERS = dict(zip(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen".split(), range(20)))
for value, word in enumerate("twenty thirty forty fifty sixty seventy eighty ninety".split(), 2):
    NUMBERS[word] = value * 10
    for unit, name in enumerate("one two three four five six seven eight nine".split(), 1):
        NUMBERS[f"{word}-{name}"] = value * 10 + unit
        NUMBERS[f"{word} {name}"] = value * 10 + unit
TOOL_COUNT = re.compile(
    r"\b(\d+|" + "|".join(sorted(NUMBERS, key=len, reverse=True))
    + r")(?:[\s-]+(?:(?:MCP|Zing)[\s-]+)?tools\b|-tool\b|"
    r"\s+tool names\b|\s+(?:MCP|Zing)\s+tool\b)", re.I)


@pytest.fixture(scope="module")
def tool_count():
    pytest.importorskip("mcp", reason="mcp SDK not installed")
    from myzing.mcp_server import build_server

    return len(asyncio.run(build_server().list_tools()))


def test_user_docs_have_no_stale_release_wording():
    stale = []
    for path in DOCS:
        text = path.read_text(encoding="utf-8")
        matches = re.findall(
            r"\b(?:pre[\s-]alpha|not\s+(?:yet\s+)?on\s+pypi|"
            r"not\s+(?:yet\s+|been\s+)?published\s+to\s+pypi)\b", text, re.I)
        if matches:
            stale.append((path.relative_to(ROOT).as_posix(), matches))
    assert not stale, stale


def test_user_docs_tool_counts_match_server(tool_count):
    stale = []
    for path in DOCS:
        text = re.sub(r"[`*_]", "", path.read_text(encoding="utf-8"))
        for match in TOOL_COUNT.finditer(text):
            value = match.group(1).lower()
            count = int(value) if value.isdigit() else NUMBERS[value]
            if count != tool_count:
                stale.append((path.relative_to(ROOT).as_posix(), match.group(), tool_count))
    assert not stale, stale


@pytest.mark.parametrize("name", [
    "llms-install.md", "plugins/hermes-zing/README.md", "docs/CONNECT.md",
    "docs/QUICKSTART.md", "docs/DIRECTORY-SUBMISSIONS.md",
])
def test_install_docs_name_candidate_and_pinned_install(name):
    text = (ROOT / name).read_text(encoding="utf-8")
    assert "release candidate" in text.lower() and VERSION in text
    assert any(f'{command} "myzing[all]=={VERSION}"' in text
               for command in ("pipx install", "uv tool install"))


def test_hermes_uses_packaged_factory_setup():
    text = (ROOT / "plugins/hermes-zing/README.md").read_text(encoding="utf-8")
    assert "Node.js 20" in text and "zing factory setup" in text
    assert "npm ci" not in text and "git+https://" not in text


@pytest.mark.parametrize("section", [
    "Text to paste", "Cursor Directory", "LobeHub", "MCP Market",
    "Cline marketplace", "GitHub MCP Registry", "awesome-mcp-servers",
])
def test_directory_descriptions_explain_factory(section, tool_count):
    text = (ROOT / "docs/DIRECTORY-SUBMISSIONS.md").read_text(encoding="utf-8")
    block = text.split(f"## {section}\n", 1)[1].split("\n## ", 1)[0]
    copy = " ".join(re.findall(r"^> ?(.*)$", block, re.M))
    if section == "awesome-mcp-servers":
        copy = re.search(r"```markdown\n(.*?)```", block, re.S).group(1)
    for term in ("release candidate", "episode", "Shorts", "receipt", "adds",
                 "sources", "licenses", "context check", "meaning", "review page",
                 "nothing is posted", f"{tool_count} MCP tools"):
        assert term.lower() in copy.lower(), (section, term)


def test_rc1_includes_round_two_release_fixes():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    section = text.split("## 1.0.0rc1\n", 1)[1].split("\n## ", 1)[0]
    assert "#576" not in section
    bullet = next((item for item in re.findall(r"^- .*(?:\n  .*)*", section, re.M)
                   if "round 2" in item.lower()), "")
    for term in ("PyAV", "19", "3.12", "decode", "doctor", "fresh-install",
                 "sync probe", "silence", "nonzero", "face model", "install method",
                 "suite-smoke", "CodeQL", "counter timing", "panel fill",
                 "hook banner", "credit contrast", "smaller files"):
        assert term in bullet, term
    assert "PRs #401 through #584" in section
