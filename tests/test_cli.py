"""Top-level CLI surface (final review FF-9: P2-6 help, P2-8 encoding)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from myzing import cli

REPO = Path(__file__).resolve().parents[1]


def test_help_is_user_facing_not_process_notes(capsys):
    """P2-6: the first CLI touch used to print lane-orchestration
    docstring notes. Help must be a usage synopsis."""
    assert cli.main(["--help"]) == 0
    out = capsys.readouterr().out
    assert "usage: zing" in out
    assert "doctor" in out and "serve-mcp" in out and "setup" in out
    for jargon in ("Lane A", "Lane B", "Lane C", "conflict-free", "handoff"):
        assert jargon not in out


def test_unknown_command_lists_commands(capsys):
    assert cli.main(["frobnicate"]) == 2
    out = capsys.readouterr().out
    assert "unknown command" in out and "doctor" in out


def test_redirected_output_is_utf8_not_mojibake():
    """P2-8: piped/redirected output on Windows got the legacy codepage
    and turned em dashes into mojibake — including the print-config
    header users pipe into a file. A piped child process is exactly the
    redirect case; its bytes must be clean UTF-8 with the em dash
    intact, no replacement characters."""
    env = dict(os.environ)
    env.pop("PYTHONIOENCODING", None)
    env["PYTHONPATH"] = str(REPO / "src")
    result = subprocess.run(
        [sys.executable, "-m", "myzing.cli", "serve-mcp", "--print-config"],
        capture_output=True,
        env=env,
        timeout=60,
    )
    assert result.returncode == 0
    text = result.stdout.decode("utf-8")  # raises on non-UTF-8 bytes
    assert "\N{EM DASH}" in text  # the character survived the pipe
    assert "\N{REPLACEMENT CHARACTER}" not in text
