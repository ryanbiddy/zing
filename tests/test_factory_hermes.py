"""The portable Hermes package and its host-judge handoff, without external work."""
from __future__ import annotations

import ast
import asyncio
import json
import re
from pathlib import Path

import pytest

from myzing import mcp_server
from myzing.factory import judge, pipeline, postcopy, source

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/hermes-zing"


def read(name):
    return (PLUGIN / name).read_text(encoding="utf-8")


def test_package_is_portable_data_and_uses_the_installed_command():
    assert {p.relative_to(PLUGIN).as_posix() for p in PLUGIN.rglob("*") if p.is_file()} == {
        "plugin.json", "mcp.json", "skills/zing/SKILL.md", "README.md", "LICENSE"}
    assert not any(p.is_symlink() for p in PLUGIN.rglob("*"))
    manifest = json.loads(read("plugin.json"))
    assert manifest["$schema"] == "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
    assert (manifest["name"], manifest["version"], manifest["author"]["name"]) == ("zing", "0.1.0", "Ryan Biddy")
    assert manifest["homepage"] == manifest["repository"] == "https://github.com/ryanbiddy/zing"
    assert manifest["license"] == "MIT" and manifest["keywords"]
    assert (PLUGIN / "LICENSE").read_bytes() == (ROOT / "LICENSE").read_bytes()
    config = json.loads(read("mcp.json"))
    assert config["$schema"] == "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
    assert set(config["mcpServers"]) == {"zing"}
    server = config["mcpServers"]["zing"]
    assert set(server) == {"type", "command", "args", "env"}
    assert (server["type"], server["command"], server["args"]) == ("stdio", "zing", ["serve-mcp"])
    env = server["env"]
    assert env["PYTHONIOENCODING"] == "utf-8" and env["PYTHONUTF8"] == "1"
    optional = {"ZING_HOME", "ZING_FACTORY_SIDECAR", "ZING_BROWSER_PATH", "UOINK_URL", "UOINK_TOKEN",
                "PEXELS_API_KEY", "PIXABAY_API_KEY", "EXA_API_KEY"}
    assert set(env) == optional | {"PYTHONIOENCODING", "PYTHONUTF8"}
    assert all(env[name] == "${" + name + "}" for name in optional)


def test_server_requires_an_executable_on_every_supported_platform():
    servers = json.loads(read("plugin.json"))["extensions"]["com.nousresearch.hermes"]["servers"]
    assert set(servers) == {"zing"}
    server = servers["zing"]
    assert server["trust"] == "untrusted" and server["timeout"] == 7200
    assert server["requires"] == {"app": True}
    assert set(server["app"]) == {"win32", "darwin", "linux"}
    for platform, app in server["app"].items():
        path = "%USERPROFILE%/.local/bin/zing.exe" if platform == "win32" else "~/.local/bin/zing"
        assert app == {"presence": "executable", "location": [{"kind": "command", "name": "zing"}, path]}


def test_skill_and_permissions_match_the_existing_mcp_surface():
    module = ast.parse((ROOT / "packaging/mcp_stdio_smoke.py").read_text(encoding="utf-8"))
    expected = next(ast.literal_eval(n.value) for n in module.body
                    if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "EXPECTED_TOOLS"
                                                        for t in n.targets))
    tools = asyncio.run(mcp_server.build_server().list_tools())
    assert {t.name for t in tools} == expected and len(expected) == 44
    read_only = {t.name for t in tools if t.annotations and t.annotations.read_only_hint is True}
    assert len(read_only) == 14 and "14 marked read-only" in read("README.md")   # the README states the count
    assert not read_only & {"zing_status", "get_breakdown", "get_render", "match_status", "zing_studio"}
    text = read("skills/zing/SKILL.md")
    assert text.startswith("---\nname: zing\ndescription: ")
    front, body = text.split("---", 2)[1:]
    description = next(line.removeprefix("description: ") for line in front.splitlines()
                       if line.startswith("description: "))
    assert 1 <= len(description) <= 1024 and len(text.splitlines()) < 120
    names = set(re.findall(r"`([a-z][a-z0-9]*_[a-z0-9_]+)(?:`|\()", body))
    assert names <= expected
    assert {"factory_new", "factory_run", "factory_status", "factory_prompt", "factory_answer",
            "factory_clip", "factory_edit", "study_video", "zing_status", "render_edl", "get_render",
            "meme_render", "study_uoink_item", "push_to_uoink"} <= names
    assert "44 tools" in read("README.md")


def test_package_links_resolve_within_the_package():
    for name in ("README.md", "skills/zing/SKILL.md"):
        for target in re.findall(r"\]\(([^)\s]+)\)", read(name)):
            if ":" in target or target.startswith("#"):
                continue
            path = (PLUGIN / name).parent / target.split("#", 1)[0]
            assert path.is_file(), (name, target)
            assert path.resolve().is_relative_to(PLUGIN.resolve())


@pytest.fixture
def project(tmp_path, monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")

    def clip(root, i, moment, host, *args, **kwargs):
        assert host.backend == "host"
        folder = root / f"clip{i:02}"
        folder.mkdir(exist_ok=True)
        try:
            answer = host.ask(f"{folder.name}-copy", "Write copy grounded in the transcript.")
        except judge.NeedsAnswer:
            return
        pipeline._write(folder / "post.json", answer)

    monkeypatch.setattr(judge.Judge, "_claude", refuse)
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(source, "transcribe_moments", lambda *a, **kw: [])
    monkeypatch.setattr(pipeline, "_clip", clip)
    monkeypatch.setattr(pipeline.review, "build", lambda *a: None)
    media, captions = tmp_path / "episode.mp4", tmp_path / "episode.srt"
    media.write_bytes(b"synthetic")
    captions.write_text("1\n00:00:00,000 --> 00:01:30,000\nWe built a local editor.\n", encoding="utf-8")
    root = tmp_path / "clips"
    assert mcp_server.h_factory_new(str(root), str(media), str(captions), moments=1, offline=True)["ok"]
    return str(root.resolve())


def advance(project):
    assert mcp_server.h_factory_run(project)["status"] == "started"
    with mcp_server._JOBS_LOCK:
        thread = mcp_server._FACTORY_JOBS.get(project)
    if thread:
        thread.join(5)
        assert not thread.is_alive()
    status = mcp_server.h_factory_status(project)
    assert status["ok"] and not status["running"]
    return status


def test_documented_factory_handoff_resumes_after_the_agent_answers(project):
    status = advance(project)
    assert status["state"] == "waiting" and [p["task"] for p in status["pending"]] == ["scout"]
    prompt = mcp_server.h_factory_prompt(project, "scout")
    assert prompt["ok"] and "We built a local editor." in prompt["prompt"]
    assert not mcp_server.h_factory_answer(project, "scout", {"moments": []})["ok"]
    assert mcp_server.h_factory_prompt(project, "scout")["ok"]
    answer = {"moments": [{"start": 10, "end": 40, "hook": "A local editor", "why": "A complete point"}]}
    assert mcp_server.h_factory_answer(project, "scout", answer)["saved"]
    status = advance(project)
    assert status["state"] == "waiting" and [p["task"] for p in status["pending"]] == ["clip01-copy"]
    assert mcp_server.h_factory_prompt(project, "clip01-copy")["ok"]
    assert mcp_server.h_factory_answer(project, "clip01-copy", {key: "Local editor" for key in postcopy.FIELDS})["ok"]
    assert advance(project)["state"] == "done"
    result = mcp_server.h_factory_edit(project, "clip01", "rate", verdict="post")
    assert result["ok"] and result["verdict"] == "post"
    assert mcp_server.h_factory_clip(project, start=45, end=75)["clip"] == "clip02"
    status = advance(project)
    assert [p["task"] for p in status["pending"]] == ["clip02-copy"]
    assert mcp_server.h_factory_answer(project, "clip02-copy", {key: "Another clip" for key in postcopy.FIELDS})["ok"]
    status = advance(project)
    assert status["state"] == "done" and len(status["clips"]) == 2
    assert status["network"]["summary"] == "offline: nothing fetched"
