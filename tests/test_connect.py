"""Offline client recipes and the unchanged legacy connection command."""
from __future__ import annotations

import base64
import builtins
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import sys
from types import SimpleNamespace
import tomllib
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from myzing import cli, connect, doctor, mcp_server


class Runtime(SimpleNamespace):
    @property
    def stderr(self):
        return sys.stderr


@pytest.fixture(params=("win32", "darwin", "linux"))
def platform(request, tmp_path, monkeypatch):
    python = tmp_path / "Python install 雪" / "python.exe"
    monkeypatch.setattr(connect, "sys", Runtime(platform=request.param, executable=str(python)))
    monkeypatch.delenv("ZING_HOME", raising=False)
    monkeypatch.setenv("UOINK_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("UOINK_TOKEN", "not-a-real-credential")
    monkeypatch.setenv("UNRELATED_SETTING", "keep-out-of-config")
    return request.param


@pytest.mark.parametrize("client", connect.CLIENTS)
@pytest.mark.parametrize("home", (None, "workspace with spaces 雪"))
def test_every_client_renders_on_every_platform(platform, client, home, monkeypatch, capsys):
    if home is not None:
        monkeypatch.setenv("ZING_HOME", home)
    assert cli.main(["connect", client, "--json"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    result = json.loads(captured.out)
    assert set(result) == {"client", "format", "location", "entry", "note", "guide", "source"}
    assert result["client"] == client and result["location"]
    assert result["source"]["checked"] == "2026-10-21"
    assert result["source"]["urls"] and all(url.startswith("https://") for url in result["source"]["urls"])
    assert result["source"]["verified"] or result["source"]["reason"]
    for forbidden in ("UOINK_URL", "UOINK_TOKEN", "not-a-real-credential", "UNRELATED_SETTING", "keep-out-of-config"):
        assert forbidden not in captured.out
    spec = connect.CLIENTS[client]
    if result["format"] == "text":
        assert result["entry"] is None and result["guide"]
        assert "<ENTRY>" not in result["guide"] and "<SHELL_COMMAND>" not in result["guide"]
        if platform not in spec.platforms:
            assert "No documented recipe" in result["guide"]
            assert result["source"]["verified"] is False
        elif spec.guide == connect.UI_FIELDS:
            entry = json.loads(result["guide"][result["guide"].index("{"):])
            assert entry["command"] == connect.sys.executable
            assert entry["args"] == ["-m", "myzing.cli", "serve-mcp"]
            assert entry["env"] == ({"ZING_HOME": str(Path(home).absolute())} if home is not None else {})
        elif client == "perplexity":
            command = shlex.split(result["guide"].splitlines()[2])
            assert command == ["/usr/bin/env", *([f"ZING_HOME={Path(home).absolute()}"] if home is not None else []),
                               connect.sys.executable, "-m", "myzing.cli", "serve-mcp"]
        return
    output = result["entry"]
    assert output == connect.render(client) and result["guide"] == ""
    env = {"ZING_HOME": str(Path(home).absolute())} if home is not None else {}
    if result["format"] == "shell":
        tokens = shlex.split(output)
        assert tokens[:5] == ["claude", "mcp", "add", "--scope", "user"]
        assert tokens[5:tokens.index("--transport")] == [part for k, v in env.items() for part in ("-e", f"{k}={v}")]
        assert tokens[tokens.index("--transport"):] == ["--transport", "stdio", "zing", "--", connect.sys.executable,
                                                       "-m", "myzing.cli", "serve-mcp"]
    elif result["format"] == "crushrc":
        assert shlex.split(output) == ["mcp", "add", "zing", "--command", connect.sys.executable,
                                       "--args", "-m", "myzing.cli", "serve-mcp",
                                       *(part for k, v in env.items() for part in ("--env", k, v))]
    else:
        data = tomllib.loads(output) if result["format"] == "toml" else json.loads(output)
        entry = data if spec.shape == "entry" else data["mcpServers"][0] if spec.shape == "list" else data[spec.shape]["zing"]
        if spec.shape == "mcp":
            assert entry["command"] == [connect.sys.executable, "-m", "myzing.cli", "serve-mcp"]
        else:
            assert entry.get("command", entry.get("cmd")) == connect.sys.executable
            assert entry["args"] == ["-m", "myzing.cli", "serve-mcp"]
        assert entry.get("env", entry.get("envs", entry.get("environment"))) == env


def test_client_table_covers_the_uoink_catalog():
    assert set(connect.CLIENTS) == {
        "claude-code", "claude-desktop", "cursor", "codex", "gemini", "vscode", "windsurf", "cline", "zed", "goose",
        "opencode", "lm-studio", "hermes", "warp", "junie", "amp", "roo", "kilo", "kilo-legacy", "cherry-studio",
        "jan", "librechat", "msty", "boltai", "continue", "raycast", "open-webui", "anythingllm", "ollama",
        "smithery-local", "windows-odr", "obsidian", "n8n", "make", "zapier", "autohotkey", "powertoys", "alfred",
        "kiro", "copilot-cli", "auggie", "factory-droid", "qwen-code", "crush", "antigravity", "chatbox", "dive", "perplexity",
    }
    for name in ("zed", "kilo-legacy", "smithery-local", "open-webui", "n8n", "make", "zapier", "windows-odr",
                 "obsidian", "autohotkey", "powertoys", "alfred"):
        assert connect.CLIENTS[name].verified is False
        assert connect.CLIENTS[name].reason


def test_list_has_one_row_per_client_and_os_locations(platform, capsys):
    assert cli.main(["connect"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    rows = dict((name, (format, location)) for name, format, location in (line.split("\t") for line in captured.out.splitlines()))
    assert rows.keys() == connect.CLIENTS.keys()
    if platform == "win32":
        assert rows["claude-desktop"] == ("json", "%APPDATA%/Claude/claude_desktop_config.json")
        assert rows["codex"] == ("toml", "%USERPROFILE%/.codex/config.toml")
    elif platform == "darwin":
        assert rows["claude-desktop"] == ("json", "~/Library/Application Support/Claude/claude_desktop_config.json")
        assert rows["codex"] == ("toml", "~/.codex/config.toml")
    else:
        assert rows["zed"] == ("json", "~/.config/zed/settings.json")
        assert rows["goose"] == ("yaml", "~/.config/goose/config.yaml")
        assert rows["claude-desktop"][0] == "text"
        assert "Library" not in captured.out and "%APPDATA%" not in captured.out
    assert rows["vscode"] == ("json", "Project .vscode/mcp.json")


@pytest.mark.parametrize("client", connect.CLIENTS)
def test_plain_output_keeps_config_separate_from_location(platform, client, capsys):
    assert cli.main(["connect", client]) == 0
    captured = capsys.readouterr()
    assert captured.out == connect.render(client) + "\n"
    assert connect.client_spec(client).location in captured.err
    assert "2026-10-21" in captured.err


@pytest.mark.parametrize("client", ("n8n", "open-webui", "make", "zapier"))
def test_http_only_clients_have_no_config(platform, client, capsys):
    assert cli.main(["connect", client]) == 0
    assert capsys.readouterr().out == "Zing has no HTTP endpoint, so this client cannot launch it.\n"
    assert cli.main(["connect", client, "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["format"] == "text" and result["entry"] is None
    assert result["guide"] == connect.HTTP_GUIDE and result["source"]["verified"] is False


@pytest.mark.parametrize("client", ("cursor", "vscode"))
@pytest.mark.parametrize("home", (None, "O'Brien & spaces + 雪"))
def test_install_links_round_trip(platform, client, home, monkeypatch, capsys):
    if home is not None:
        monkeypatch.setenv("ZING_HOME", home)
    assert cli.main(["connect", client, "--deeplink"]) == 0
    link = capsys.readouterr().out.strip()
    assert link == connect.deeplink(client)
    if client == "cursor":
        query = parse_qs(urlsplit(link).query)
        assert query["name"] == ["zing"]
        entry = json.loads(base64.b64decode(query["config"][0]).decode("utf-8"))
    else:
        entry = json.loads(unquote(link.split("?", 1)[1]))
        assert entry.pop("name") == "zing" and entry.pop("type") == "stdio"
    assert entry == connect.server_entry()
    assert cli.main(["connect", client, "--deeplink", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["entry"] == link and result["format"] == "deeplink"


def test_shell_escaping_keeps_literal_path_characters(platform, tmp_path, monkeypatch):
    python = str(tmp_path / "O'Brien & $spaces ` + 雪" / "python.exe")
    monkeypatch.setattr(connect.sys, "executable", python)
    monkeypatch.setenv("ZING_HOME", "O'Brien & $workspace ` + 雪")
    output = connect.render("claude-code")
    if platform == "win32":
        tokens = [s.replace("''", "'") for s in re.findall(r"'((?:[^']|'')*)'", output)]
        assert tokens == ["--scope", "user", "-e", f"ZING_HOME={Path(connect.os.environ['ZING_HOME']).absolute()}",
                          "--transport", "stdio", "zing", "--", python, "-m", "myzing.cli", "serve-mcp"]
    else:
        tokens = shlex.split(output)
        assert tokens[tokens.index("-e") + 1] == f"ZING_HOME={Path(connect.os.environ['ZING_HOME']).absolute()}"
        assert tokens[tokens.index("--") + 1:] == [python, "-m", "myzing.cli", "serve-mcp"]
    assert shlex.split(connect.render("crush"))[4] == python


def test_workspace_expands_home_and_python_keeps_venv_path(platform, tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("ZING_HOME", "~/workspace")
    def refuse(*args, **kwargs):
        raise AssertionError("Do not resolve the venv interpreter")
    monkeypatch.setattr(Path, "resolve", refuse)
    entry = connect.server_entry()
    assert entry["command"] == connect.sys.executable
    assert entry["env"] == {"ZING_HOME": str(tmp_path / "workspace")}


@pytest.mark.parametrize("home", ("", "   "))
def test_empty_workspace_uses_the_server_default(home, monkeypatch):
    monkeypatch.setenv("ZING_HOME", home)
    assert connect.server_entry()["env"] == {}


def test_connect_only_prints(platform, monkeypatch, capsys):
    def refuse(*args, **kwargs):
        raise AssertionError("connect must only print")
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", refuse)
        patch.setattr(Path, "open", refuse)
        patch.setattr(socket, "socket", refuse)
        patch.setattr(subprocess, "Popen", refuse)
        for client in connect.CLIENTS:
            assert connect.run([client, "--json"]) == 0
    capsys.readouterr()


def test_client_schema_details(platform):
    assert json.loads(connect.render("vscode"))["servers"]["zing"]["type"] == "stdio"
    assert json.loads(connect.render("amp"))["amp.mcpServers"]["zing"]["command"] == connect.sys.executable
    assert json.loads(connect.render("copilot-cli"))["mcpServers"]["zing"]["tools"] == ["*"]
    assert json.loads(connect.render("dive"))["mcpServers"]["zing"]["enabled"] is True
    assert json.loads(connect.render("factory-droid"))["mcpServers"]["zing"]["type"] == "stdio"
    assert json.loads(connect.render("librechat"))["mcpServers"]["zing"]["type"] == "stdio"
    assert json.loads(connect.render("goose"))["extensions"]["zing"] == {
        "name": "zing", "type": "stdio", "enabled": True, "cmd": connect.sys.executable,
        "args": ["-m", "myzing.cli", "serve-mcp"], "envs": {}, "timeout": 300,
    }
    assert json.loads(connect.render("continue")) == {
        "name": "Zing", "version": "1.0.0", "schema": "v1", "mcpServers": [{"name": "zing", **connect.server_entry()}],
    }


@pytest.mark.parametrize("argv", (["x"], ["x", "--json"], ["x", "--deeplink"]))
def test_unknown_client_exits_two(argv, capsys):
    assert cli.main(["connect", *argv]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "unknown client 'x'. Run zing connect to list them.\n"


@pytest.mark.parametrize("client, code", (("codex", 0), ("x", 2)))
def test_cli_runs_without_site_packages(client, code):
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
           "PYTHONDONTWRITEBYTECODE": "1", "UOINK_URL": "http://127.0.0.1:1"}
    result = subprocess.run([sys.executable, "-S", "-m", "myzing.cli", "connect", client, "--json"],
                            env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == code
    if code == 0:
        entry = tomllib.loads(json.loads(result.stdout)["entry"])["mcp_servers"]["zing"]
        assert entry["command"] == sys.executable and entry["args"] == ["-m", "myzing.cli", "serve-mcp"]
        assert result.stderr == ""
    else:
        assert result.stderr == "unknown client 'x'. Run zing connect to list them.\n" and result.stdout == ""


@pytest.mark.parametrize("argv", (["--json"], ["--deeplink"], ["codex", "--deeplink"]))
def test_flags_require_the_right_client(argv, capsys):
    assert cli.main(["connect", *argv]) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "requires" in captured.err


def test_help_lists_connect_beside_serve_mcp(capsys):
    assert cli.main(["--help"]) == 0
    lines = capsys.readouterr().out.splitlines()
    index = next(i for i, line in enumerate(lines) if line.lstrip().startswith("serve-mcp "))
    assert lines[index + 1].lstrip().startswith("connect ")
    with pytest.raises(SystemExit) as exit:
        cli.main(["connect", "--help"])
    assert exit.value.code == 0
    assert "--json" in capsys.readouterr().out


@pytest.mark.parametrize("target", ("", "desktop", "code"))
@pytest.mark.parametrize("defect", (None, "MCP SDK is missing"))
def test_print_config_output_stays_byte_for_byte(target, defect, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ZING_HOME", str(tmp_path / "workspace"))
    monkeypatch.setattr(mcp_server, "mcp_sdk_defect", lambda: defect)
    monkeypatch.setattr(doctor, "check_uoink", lambda: SimpleNamespace(data={"peer": {"state": "absent"}}, fix="suite fix"))
    monkeypatch.setattr(doctor, "uoink_suite_hint", lambda state: "suite hint")
    desktop = ("# Claude Desktop - merge into claude_desktop_config.json\n"
               "# (Windows: %APPDATA%\\Claude\\  macOS: ~/Library/Application Support/Claude/)\n"
               + json.dumps({"mcpServers": {"zing": {"command": sys.executable,
                                                     "args": ["-m", "myzing.cli", "serve-mcp"]}}}, indent=2) + "\n")
    code = f'# Claude Code - run this once:\nclaude mcp add zing -- "{sys.executable}" -m myzing.cli serve-mcp\n'
    expected = desktop + "\n" + code if not target else desktop if target == "desktop" else code
    if defect:
        expected += f"\n# NOTE: {defect}\n# Do this before connecting a client, or the server will exit at launch.\n"
    expected += "\n# suite hint\n# suite fix\n"
    assert cli.main(["serve-mcp", "--print-config", *([target] if target else [])]) == 0
    captured = capsys.readouterr()
    assert captured.out.encode("utf-8") == expected.encode("utf-8") and captured.err == ""
