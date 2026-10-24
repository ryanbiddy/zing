"""Top-level CLI surface (final review FF-9: P2-6 help, P2-8 encoding)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

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
    and corrupted non-ASCII output. Keep a Unicode probe after CLI setup:
    the print-config header now uses ASCII punctuation, but user paths and
    media titles still need clean UTF-8 when redirected."""
    env = dict(os.environ)
    env.pop("PYTHONIOENCODING", None)
    env["PYTHONPATH"] = str(REPO / "src")
    env["UOINK_URL"] = "http://127.0.0.1:1"
    result = subprocess.run(
        [sys.executable, "-c", "from myzing import cli; "
         "cli.main(['serve-mcp', '--print-config']); print('caf\\u00e9')"],
        capture_output=True,
        env=env,
        timeout=60,
    )
    assert result.returncode == 0
    text = result.stdout.decode("utf-8")  # raises on non-UTF-8 bytes
    assert "caf\u00e9" in text  # the character survived the pipe
    assert "\N{EM DASH}" not in text
    assert "\N{REPLACEMENT CHARACTER}" not in text


def test_broken_install_names_the_missing_module(capsys, monkeypatch):
    monkeypatch.setitem(
        cli._COMMANDS, "ghostcmd", ("myzing.does_not_exist", "ghost")
    )
    assert cli.main(["ghostcmd"]) == 2
    out = capsys.readouterr().out
    assert "myzing.does_not_exist" in out and "reinstall" in out


def test_every_registered_command_appears_in_help(capsys):
    """SG-3: help renders FROM the command registry, so this holds by
    construction — the assertion documents the invariant that killed
    the hand-written-usage drift class (final review P2-6's sequel)."""
    cli.main(["--help"])
    out = capsys.readouterr().out
    for name, (_, help_line) in cli._COMMANDS.items():
        assert name in out and help_line in out


def test_version_flag_reports_the_installed_version(capsys):
    """Every product in the suite answers `--version`. Writer already did;
    zing used to reject it as an unknown command, which made the two CLIs
    disagree about a flag any user tries first."""
    assert cli.main(["--version"]) == 0
    out = capsys.readouterr().out.strip()
    assert out
    assert "unknown command" not in out
    # A version, not the usage block.
    assert out[0].isdigit()


def test_version_matches_what_the_mcp_server_advertises():
    """The CLI and the MCP server must never report different versions for
    the same install, so they resolve it the same way."""
    from myzing import mcp_server

    assert cli._version() == mcp_server._version()


@pytest.mark.parametrize("picking", [False, True])
@pytest.mark.parametrize("position", ["before", "after", "inherited"])
@pytest.mark.parametrize("fail", [False, True])
def test_still_workspace_is_scoped(tmp_path, monkeypatch, capsys, picking, position, fail):
    from myzing import storage
    from myzing.still import command

    inherited = tmp_path / "inherited"
    explicit = tmp_path / "explicit"
    seen = []

    def operation(*args, **kwargs):
        seen.append(storage.workspace_root())
        if fail:
            raise ValueError("operation failed")
        return {"workspace": str(storage.workspace_root())}

    monkeypatch.setattr(command, "create_stills", operation)
    monkeypatch.setattr(command, "pick_still", operation)
    argv = (["pick", "output", "--id", "concept"] if picking else
            ["--photos", "photos", "--topic", "bugs", "--out", "output"])
    if position == "before":
        argv = ["--workspace", str(explicit), *argv]
    elif position == "after":
        argv += ["--workspace", str(explicit)]
    with storage.use_workspace(inherited):
        assert cli.main(["still", *argv, "--json"]) == int(fail)
        assert seen == [inherited if position == "inherited" else explicit]
        assert storage.workspace_root() == inherited
    assert ('"ok": false' if fail else '"ok": true') in capsys.readouterr().out
