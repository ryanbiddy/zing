"""Cheap checks for public documentation that repeats repository facts."""

from pathlib import Path
import re

from myzing.cli import _COMMANDS


ROOT = Path(__file__).resolve().parents[1]
DOCS = [
    ROOT / "README.md",
    *sorted((ROOT / "docs").glob("*.md")),
    *sorted((ROOT / "skills" / "zing").rglob("*.md")),
    *sorted((ROOT / "tools" / "eval").glob("*.md")),
]


def test_documented_ffmpeg_counts_match_full_ci_gate():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    counts = re.findall(r"pytest -q -m ffmpeg --expected-ffmpeg-tests (\d+)", workflow)
    assert counts and len(set(counts)) == 1
    expected = counts[0]
    quoted = []
    for doc in DOCS:
        text = doc.read_text(encoding="utf-8")
        values = re.findall(r"--expected-ffmpeg-tests (\d+)", text)
        values += re.findall(r"\b(\d+)-test FFmpeg gate", text)
        values += re.findall(r"CI FFmpeg baseline remains \*\*(\d+)\*\*", text)
        for value in values:
            assert value == expected, (doc.relative_to(ROOT), value, expected)
        quoted.extend(values)
    assert quoted, "Keep a runnable full-gate example in the developer guide"


def test_command_catalog_covers_cli_registry():
    text = (ROOT / "skills/zing/references/commands.md").read_text(encoding="utf-8")
    catalog = set(re.findall(r"^\| `zing ([a-z-]+)(?: [a-z-]+)?` \|", text, re.M))
    assert catalog == set(_COMMANDS)


def test_extras_tables_match_package():
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    section = project.split("[project.optional-dependencies]", 1)[1].split("\n[", 1)[0]
    extras = set(re.findall(r"^([a-z]+) =", section, re.M))
    assert extras
    for name in ("README.md", "skills/zing/references/commands.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        table = text.split("| Extra | Enables |", 1)[1].split("\n\n", 1)[0]
        documented = set(re.findall(r"^\| `?([a-z]+)`? \|", table, re.M))
        assert documented == extras, (name, documented ^ extras)


def test_local_markdown_links_exist():
    for doc in DOCS:
        for target in re.findall(r"\]\(([^)\s]+)(?:\s+[^)]*)?\)", doc.read_text(encoding="utf-8")):
            if ":" in target or target.startswith("#"):
                continue
            path = target.split("#", 1)[0]
            assert (doc.parent / path).exists(), (doc.relative_to(ROOT), target)
