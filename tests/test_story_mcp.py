"""Story MCP tools use local fixtures and fake workers, with no service calls."""
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest

from myzing import mcp_server
from myzing.story import StoryError, command, jobs
from test_story_command import story_file


def test_new_creates_a_starter_and_check_returns_json_problems(tmp_path):
    directory = tmp_path / "story"
    result = mcp_server.h_story_new(str(directory), "a paper moon")
    assert result["ok"] and (directory / "README-STORY.txt").is_file()
    checked = mcp_server.h_story_check(str(directory))
    assert checked["ok"] and checked["valid"] is False
    assert checked["problems"] == command.check_json(directory)
    assert any("replace this source" in problem["message"].lower() for problem in checked["problems"])
    assert all(set(problem) == {"path", "message"} for problem in checked["problems"])


def test_new_refuses_to_replace_an_existing_story(tmp_path):
    story_file(tmp_path)
    original = (tmp_path / "story.json").read_bytes()
    result = mcp_server.h_story_new(str(tmp_path), "another story")
    assert result["ok"] is False and result["error"]
    assert (tmp_path / "story.json").read_bytes() == original


def test_check_returns_all_contract_problems(tmp_path):
    value = story_file(tmp_path)
    value.update(topic="", sources=[])
    (tmp_path / "story.json").write_text(json.dumps(value), encoding="utf-8")
    result = mcp_server.h_story_check(str(tmp_path))
    assert result == {"ok": True, "valid": False, "problems": command.check_json(tmp_path)}
    assert {problem["path"] for problem in result["problems"]} >= {"topic", "sources"}


def test_check_reports_a_valid_story(tmp_path):
    story_file(tmp_path)
    assert mcp_server.h_story_check(str(tmp_path)) == {"ok": True, "valid": True, "problems": []}


def test_build_rejects_placeholder_before_starting_a_worker(tmp_path, monkeypatch):
    assert mcp_server.h_story_new(str(tmp_path), "a paper moon")["ok"]
    monkeypatch.setattr(command, "build", lambda *a, **kw: pytest.fail("placeholder build started"))
    result = mcp_server.h_story_build(str(tmp_path))
    assert result["ok"] is False and "replace this source" in result["error"].lower()
    assert not (tmp_path / jobs.STATUS_FILE).exists()


def test_build_runs_in_background_passes_options_and_reports_done(tmp_path, monkeypatch):
    story_file(tmp_path)
    entered, finish = threading.Event(), threading.Event()
    observed = {}

    def build(directory, **options):
        observed.update(directory=directory, **options)
        entered.set()
        assert finish.wait(5), "test did not release worker"
        return {"rendered": str(directory / "final.mp4"), "receipt": str(directory / "story-receipt.json")}

    monkeypatch.setattr(command, "build", build)
    try:
        result = mcp_server.h_story_build(str(tmp_path), provider="lines", voice="test-voice", speed=1.2,
                                        lines_dir=str(tmp_path / "lines"), out=str(tmp_path / "final.mp4"),
                                        synthetic_voice=True, no_sfx=True)
        assert result["ok"] and result["status"] == "started"
        assert entered.wait(5)
        thread = jobs._JOBS[str(tmp_path.resolve())]
        status = mcp_server.h_story_status(str(tmp_path))
        assert status["ok"] and status["state"] == "running" and status["running"]
        assert mcp_server.h_story_build(str(tmp_path))["status"] == "already_running"
        assert observed == {"directory": tmp_path.resolve(), "provider": "lines", "voice": "test-voice",
                            "speed": 1.2, "lines_dir": tmp_path / "lines", "out": tmp_path / "final.mp4",
                            "synthetic": True, "no_sfx": True}
    finally:
        finish.set()
        if "thread" in locals():
            thread.join(5)
    assert not thread.is_alive()
    status = mcp_server.h_story_status(str(tmp_path))
    assert status["ok"] and status["state"] == "done" and not status["running"]
    assert status["rendered"] == str(tmp_path / "final.mp4")
    assert status["receipt"] == str(tmp_path / "story-receipt.json")


@pytest.mark.parametrize("failure", [StoryError("missing voice setup"), RuntimeError("secret-request-header"),
                                      ValueError("secret-request-header")])
def test_failed_worker_reports_failure_without_unexpected_exception_details(tmp_path, monkeypatch, failure):
    story_file(tmp_path)
    release = threading.Event()

    def build(*args, **kwargs):
        assert release.wait(5)
        raise failure

    monkeypatch.setattr(command, "build", build)
    result = mcp_server.h_story_build(str(tmp_path))
    assert result["ok"]
    thread = jobs._JOBS[str(tmp_path.resolve())]
    release.set()
    thread.join(5)
    status = mcp_server.h_story_status(str(tmp_path))
    assert not thread.is_alive()
    assert status["ok"] is False and status["state"] == "failed" and not status["running"]
    assert "secret-request-header" not in json.dumps(status)
    assert ("missing voice setup" if isinstance(failure, StoryError) else type(failure).__name__) in status["error"]


def test_status_reports_draft_and_missing_folder(tmp_path):
    assert mcp_server.h_story_status(str(tmp_path))["ok"] is False
    story_file(tmp_path)
    assert mcp_server.h_story_status(str(tmp_path)) == {
        "ok": True, "state": "draft", "directory": str(tmp_path.resolve()), "running": False,
    }


def test_status_reports_interrupted_without_rewriting_state(tmp_path):
    story_file(tmp_path)
    path = tmp_path / jobs.STATUS_FILE
    path.write_text('{"state":"running"}', encoding="utf-8")
    before = path.read_bytes()
    result = mcp_server.h_story_status(str(tmp_path))
    assert result["state"] == "interrupted" and not result["running"]
    assert "story_build" in result["hint"]
    assert path.read_bytes() == before


@pytest.mark.parametrize("saved", ["{", "[]", '{"state":"unknown"}'])
def test_status_rejects_bad_saved_state_as_data(tmp_path, saved):
    story_file(tmp_path)
    (tmp_path / jobs.STATUS_FILE).write_text(saved, encoding="utf-8")
    result = mcp_server.h_story_status(str(tmp_path))
    assert result["ok"] is False and "story-status.json" in result["error"]


def test_story_tools_are_registered_with_expected_arguments_and_hints():
    pytest.importorskip("mcp")
    registered = {tool.name: tool for tool in asyncio.run(mcp_server.build_server().list_tools())}
    assert {"story_new", "story_check", "story_build", "story_status"} <= registered.keys()
    build = registered["story_build"]
    schema = build.model_dump(by_alias=True)["inputSchema"]
    assert schema["required"] == ["directory"]
    assert set(schema["properties"]) == {
        "directory", "provider", "voice", "speed", "lines_dir", "out", "synthetic_voice", "no_sfx",
    }
    assert build.annotations.open_world_hint is True
    assert build.annotations.destructive_hint is True
    for name in ("story_check", "story_status"):
        assert registered[name].annotations.read_only_hint is True
    assert registered["story_new"].annotations.destructive_hint is False
    root = Path(__file__).resolve().parents[1]
    for name in ("story_new", "story_check", "story_build", "story_status"):
        for filename in ("docs/CONNECT.md", "skills/zing/references/mcp.md"):
            assert f"`{name}`" in (root / filename).read_text(encoding="utf-8")
