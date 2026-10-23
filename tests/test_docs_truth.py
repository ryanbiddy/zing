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


def test_ci_ffmpeg_gate_counts_match_collected_tests():
    """Lock every CI gate count (full gate and the macOS subset) to collection.

    The conftest option fails collection unless exactly that many tests are
    selected, so a stale count in ci.yml fails here, not only on its runner.
    """
    import shlex
    import subprocess
    import sys

    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    commands = [line.split("run:", 1)[1] for line in workflow.splitlines()
                if "run: pytest" in line and "--expected-ffmpeg-tests" in line]
    assert len(commands) >= 3 and any("tests/" in c for c in commands)
    for command in dict.fromkeys(commands):
        args = shlex.split(command)[1:]
        result = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-p", "no:cacheprovider", *args],
                                cwd=ROOT, capture_output=True, text=True, timeout=300)
        assert result.returncode == 0, (command, (result.stdout + result.stderr)[-800:])


def test_command_catalog_covers_cli_registry():
    text = (ROOT / "skills/zing/references/commands.md").read_text(encoding="utf-8")
    catalog = set(re.findall(r"^\| `zing ([a-z-]+)(?: [a-z-]+)?` \|", text, re.M))
    assert catalog == set(_COMMANDS)


def test_studio_entry_point_and_mcp_counts():
    import ast
    from myzing.cli import _usage
    module = ast.parse((ROOT / "packaging/mcp_stdio_smoke.py").read_text(encoding="utf-8"))
    tools = next(ast.literal_eval(n.value) for n in module.body
                 if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "EXPECTED_TOOLS" for t in n.targets))
    assert {"zing_studio", "zing_studio_run"} <= tools
    for file in ("README.md", "docs/CONNECT.md", "skills/zing/references/mcp.md"):
        text = (ROOT / file).read_text(encoding="utf-8")
        counts = re.findall(r"\b(\d+) (?:MCP )?tools\b", text)
        assert counts and all(int(n) == len(tools) for n in counts), (file, counts)
    assert _usage().startswith("Start here: zing studio")
    assert (ROOT / "docs/STUDIO.md").is_file()

def test_explain_documented_surface():
    assert "zing_explain" in (ROOT / "docs/CONNECT.md").read_text(encoding="utf-8")
    assert "zing explain" in (ROOT / "README.md").read_text(encoding="utf-8")
    assert "explain_video(source, out_dir, *, transitions=True, offline=True)" in (ROOT / "docs/EXPLAIN.md").read_text(encoding="utf-8")


def test_extras_tables_match_package():
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    section = project.split("[project.optional-dependencies]", 1)[1].split("\n[", 1)[0]
    extras = set(re.findall(r"^([a-z][a-z-]*) =", section, re.M))
    assert extras
    for name in ("README.md", "skills/zing/references/commands.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        table = text.split("| Extra | Enables |", 1)[1].split("\n\n", 1)[0]
        documented = set(re.findall(r"^\| `?([a-z][a-z-]*)`? \|", table, re.M))
        assert documented == extras, (name, documented ^ extras)


def test_local_markdown_links_exist():
    for doc in DOCS:
        for target in re.findall(r"\]\(([^)\s]+)(?:\s+[^)]*)?\)", doc.read_text(encoding="utf-8")):
            if ":" in target or target.startswith("#"):
                continue
            path = target.split("#", 1)[0]
            assert (doc.parent / path).exists(), (doc.relative_to(ROOT), target)
