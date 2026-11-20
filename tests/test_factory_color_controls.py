"""Factory color survives CLI, channel inheritance, agent edits and resumed runs."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from myzing import mcp_server
from myzing.channels import command as channels_command, registry
from myzing.factory import color, command, edit, export, judge, pipeline, render, source
from myzing.factory.tools import FactoryError
from test_factory_uhd import clip


@pytest.fixture(autouse=True)
def isolated(monkeypatch, zing_workspace, tmp_path):
    monkeypatch.setenv("ZING_CHANNELS_HOME", str(tmp_path / "channels"))
    monkeypatch.setattr(source, "transcribe_moments", lambda *args, **kwargs: [])

    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")

    monkeypatch.setattr(judge.subprocess, "run", refuse)


@pytest.fixture
def media(tmp_path):
    path = tmp_path / "episode.mp4"
    path.write_bytes(b"test placeholder; never decoded")
    return path


def test_new_cli_and_mcp_save_color_without_processing_media(tmp_path, media, capsys):
    project = tmp_path / "cli"
    assert command.run(["new", str(project), "--media", str(media), "--color-look", "cinematic-cool",
                        "--color-strength", "0.35", "--color-exposure", ".2", "--color-temperature", "-.1"]) == 0
    settings = json.loads(capsys.readouterr().out)["settings"]
    assert settings["color_look"] == "cinematic-cool" and settings["color_strength"] == .35
    assert settings["color_exposure"] == .2 and settings["color_temperature"] == -.1
    result = mcp_server.h_factory_new(str(tmp_path / "mcp"), str(media), color_look="cinematic-cool",
                                    color_strength=.35, color_exposure=.2, color_temperature=-.1)
    assert result["ok"]
    assert color.normalize(result["settings"]) == color.normalize(settings)
    assert pipeline.init(tmp_path / "plain", media)["settings"]["color_look"] == "source"


@pytest.mark.parametrize("settings", [
    {"color_look": "teal"}, {"color_strength": 1.1}, {"color_strength": -1},
    {"color_strength": True}, {"color_strength": float("nan")}, {"color_exposure": float("inf")},
    {"color_exposure": 1.1}, {"color_temperature": -.3}, {"color_tint": ".1"},
])
def test_invalid_grade_never_creates_project(tmp_path, media, settings):
    project = tmp_path / "bad"
    with pytest.raises(FactoryError, match="color_"):
        pipeline.init(project, media, **settings)
    assert not project.exists()
    assert not mcp_server.h_factory_new(str(project), str(media), **settings)["ok"]
    assert not project.exists()


def test_configure_reads_without_writing_and_saves_partial_changes(tmp_path, media, capsys):
    project = tmp_path / "project"
    pipeline.init(project, media, color_look="cinematic-cool", color_temperature=.1)
    path = project / "factory.json"
    before = path.read_bytes(), path.stat().st_mtime_ns
    assert command.run(["color", str(project)]) == 0
    assert json.loads(capsys.readouterr().out)["color"]["color_look"] == "cinematic-cool"
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert command.run(["color", str(project), "--color-strength", ".25"]) == 0
    capsys.readouterr()
    saved = pipeline._read(path)
    assert saved["color_temperature"] == .1 and saved["color_strength"] == .25
    before = path.read_bytes()
    assert command.run(["color", str(project), "--color-tint", "2"]) == 2
    assert "color_tint" in capsys.readouterr().err
    assert path.read_bytes() == before
    assert command.run(["color", str(project), "--color-look", "source"]) == 0
    assert pipeline.configure_color(project)["color_look"] == "source"


def test_channel_cli_inheritance_and_project_override(tmp_path, media, capsys):
    assert channels_command.run(["new", "stories", "--name", "Stories", "--niche", "Interviews",
                                 "--color-look", "cinematic-cool", "--color-strength", ".4"]) == 0
    capsys.readouterr()
    path = registry.directory("stories") / "channel.json"
    before = path.read_bytes(), path.stat().st_mtime_ns
    assert channels_command.run(["color", "stories"]) == 0
    assert json.loads(capsys.readouterr().out)["color"]["color_strength"] == .4
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert channels_command.run(["color", "stories", "--color-temperature", ".05"]) == 0
    capsys.readouterr()
    assert command.run(["new", str(tmp_path / "inherited"), "--media", str(media), "--channel", "stories"]) == 0
    inherited = json.loads(capsys.readouterr().out)["settings"]
    assert inherited["color_strength"] == .4 and inherited["color_temperature"] == .05
    assert command.run(["new", str(tmp_path / "override"), "--media", str(media), "--channel", "stories",
                        "--color-look", "source", "--color-strength", "0"]) == 0
    overridden = json.loads(capsys.readouterr().out)["settings"]
    assert overridden["color_look"] == "source" and overridden["color_strength"] == 0
    assert registry.load("stories")["factory"]["color_look"] == "cinematic-cool"
    before = path.read_bytes()
    assert channels_command.run(["color", "stories", "--color-exposure", "2"]) == 2
    assert path.read_bytes() == before


def test_channel_rejects_invalid_saved_color_with_field_name():
    channel = registry.create("Stories", "Interviews")
    assert channel["factory"] == {}
    channel["factory"]["color_strength"] = 2
    with pytest.raises(registry.ChannelError, match=r"factory\.color_strength"):
        registry.save(channel)
    assert registry.load("stories")["factory"] == {}


def test_one_off_render_edit_and_export_pass_overrides_without_saving(tmp_path, media, capsys, monkeypatch):
    root = tmp_path / "project"
    pipeline.init(root, media, color_look="cinematic-cool", color_strength=.4)
    d = clip(root)
    before = (root / "factory.json").read_bytes()
    calls = []

    def rendered(d, shape, pack, **kwargs):
        calls.append(kwargs)
        return d / "clip.mp4"

    monkeypatch.setattr(render, "render", rendered)
    monkeypatch.setattr(export, "export", lambda d, shape, pack, **kw: {"forwarded": kw})
    assert command.run(["render", str(d), "--color-strength", ".7"]) == 0
    capsys.readouterr()
    assert calls[-1]["color_strength"] == .7 and "color_look" not in calls[-1]
    assert command.run(["edit", str(root), "clip01", "--render", "9x16", "--color-look", "source"]) == 0
    capsys.readouterr()
    assert calls[-1] == {"color_look": "source"}
    result = mcp_server.h_factory_edit(str(root), "clip01", "render", color_exposure=.25)
    assert result["ok"] and calls[-1] == {"color_exposure": .25}
    assert command.run(["export", str(d), "--color-strength", "0"]) == 0
    assert json.loads(capsys.readouterr().out)["forwarded"]["color_strength"] == 0
    assert (root / "factory.json").read_bytes() == before
    with pytest.raises(FactoryError, match="color options need"):
        edit.apply(root, "clip01", "rate", verdict="post", color_strength=.3)
    assert not (root / "ratings.json").exists()


def test_invalid_color_with_4k_does_not_save_resolution_or_probe(tmp_path, media, capsys, monkeypatch):
    root = tmp_path / "project"
    pipeline.init(root, media)
    d = clip(root)
    path = root / "factory.json"
    before = path.read_bytes()

    def refuse(*args, **kwargs):
        raise AssertionError("invalid color must fail before a probe or render")

    monkeypatch.setattr(render, "warn_uhd", refuse)
    monkeypatch.setattr(render, "render", refuse)
    assert command.run(["render", str(d), "--4k", "--color-strength", "2"]) == 2
    assert "color_strength" in capsys.readouterr().err
    assert path.read_bytes() == before


def test_resume_replaces_changed_grade_and_then_reuses_it(tmp_path, media, monkeypatch):
    root = tmp_path / "project"
    pipeline.init(root, media, shapes=["9x16", "1x1"])
    d = clip(root)
    pipeline._write(root / "moments.json", {"scouted": True, "moments": [
        {"start": 0, "end": 2, "hook": "A talk", "snapped": True}]})
    rendered = []

    def make(d, shape, pack):
        settings = color.normalize(pipeline._read(root / "factory.json"))
        rendered.append((shape, settings["color_look"], settings["color_strength"]))
        theme, assets, _ = render.pack_data(pack)
        tag = render.suffix(shape, pack)
        pipeline._write(d / f"data{tag}.json", {"theme": theme, **assets, "color": {
            "settings": settings, "active": settings["color_look"] != "source",
            "version": color.VERSION, "look_version": color.LOOK_VERSION}})
        out = d / f"clip{tag}.mp4"
        out.write_bytes(b"rendered")
        return out

    monkeypatch.setattr(render, "render", make)
    for _ in range(2):
        result = pipeline.run(root, judge.Judge(root), say=lambda message: None)
        assert not result.get("failed")
    assert rendered == [("9x16", "source", .5), ("1x1", "source", .5)]
    pipeline.configure_color(root, color_look="cinematic-cool", color_strength=.3)
    for _ in range(2):
        pipeline.run(root, judge.Judge(root), say=lambda message: None)
    assert rendered[2:] == [("9x16", "cinematic-cool", .3), ("1x1", "cinematic-cool", .3)]
    pipeline.configure_color(root, color_look="source")
    pipeline.run(root, judge.Judge(root), say=lambda message: None)
    assert rendered[-2:] == [("9x16", "source", .3), ("1x1", "source", .3)]


@pytest.fixture
def rendered_project(tmp_path, media, monkeypatch):
    root = tmp_path / "project"
    pipeline.init(root, media, shapes=["9x16"], color_look="cinematic-cool")
    d = clip(root)
    pipeline._write(root / "moments.json", {"scouted": True, "moments": [
        {"start": 0, "end": 2, "hook": "A talk", "snapped": True}]})
    calls = []
    data_file, out = d / "data.json", d / "clip.mp4"

    def make(d, shape, pack):
        cfg = pipeline._read(root / "factory.json")
        theme, assets, _ = render.pack_data(pack)
        normalized = color.normalize(cfg)
        active = normalized["color_look"] != "source" and (normalized["color_strength"] > 0 or any(
            normalized[key] for key in ("color_exposure", "color_temperature", "color_tint")))
        recipe = {"settings": normalized, "active": active,
                  "version": color.VERSION, "look_version": color.LOOK_VERSION}
        calls.append(recipe)
        pipeline._write(data_file, {"theme": theme, **assets, "color": recipe})
        out.write_bytes(b"rendered")
        return out

    monkeypatch.setattr(render, "render", make)

    def run():
        result = pipeline.run(root, judge.Judge(root), say=lambda message: None)
        assert not result.get("failed"), result

    def change_metadata(metadata):
        data = pipeline._read(data_file)
        if metadata == "missing":
            data.pop("color", None)
        else:
            data["color"] = metadata
        pipeline._write(data_file, data)
        # Metadata is deliberately older than the output, so only the color check invalidates it.
        after = data_file.stat().st_mtime_ns + 1_000_000
        os.utime(out, ns=(after, after))

    run()
    return root, calls, run, change_metadata


@pytest.mark.parametrize("constant", ["VERSION", "LOOK_VERSION"])
def test_resume_rebuilds_old_grade_version_once(rendered_project, monkeypatch, constant):
    root, calls, run, change_metadata = rendered_project
    assert len(calls) == 1
    run()
    assert len(calls) == 1
    monkeypatch.setattr(color, constant, getattr(color, constant) + 1)
    run()
    run()
    assert len(calls) == 2


@pytest.mark.parametrize("metadata", [None, [], "bad", {}, {"settings": None},
                                      {"settings": {"color_strength": "bad"}},
                                      {"settings": {}, "active": "false"}])
def test_resume_replaces_malformed_color_metadata(rendered_project, metadata):
    root, calls, run, change_metadata = rendered_project
    change_metadata(metadata)
    run()
    run()
    assert len(calls) == 2


def test_historical_source_render_stays_current_without_color_metadata(rendered_project, monkeypatch):
    root, calls, run, change_metadata = rendered_project
    pipeline.configure_color(root, color_look="source", color_strength=.2)
    run()
    assert len(calls) == 2
    change_metadata("missing")
    monkeypatch.setattr(color, "VERSION", color.VERSION + 1)
    monkeypatch.setattr(color, "LOOK_VERSION", color.LOOK_VERSION + 1)
    run()
    assert len(calls) == 2


def test_zero_strength_preset_still_replaces_legacy_pack_grade(rendered_project):
    root, calls, run, change_metadata = rendered_project
    pipeline.configure_color(root, color_look="source")
    run()
    assert len(calls) == 2
    change_metadata("missing")
    pipeline.configure_color(root, color_look="cinematic-cool", color_strength=0)
    run()
    run()
    assert len(calls) == 3 and calls[-1]["active"] is False
    pipeline.configure_color(root, color_look="source")
    run()
    run()
    assert len(calls) == 4 and calls[-1]["settings"]["color_look"] == "source"
    pipeline.configure_color(root, color_look="cinematic-cool")
    run()
    run()
    assert len(calls) == 5 and calls[-1]["active"] is False


def test_mcp_run_saves_color_and_refuses_changes_during_running_job(tmp_path, media, monkeypatch):
    root = tmp_path / "project"
    pipeline.init(root, media)

    class Thread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr(mcp_server, "_FACTORY_JOBS", {})
    monkeypatch.setattr(mcp_server.threading, "Thread", Thread)
    result = mcp_server.h_factory_run(str(root), color_look="cinematic-cool", color_strength=.3)
    assert result["status"] == "started"
    assert pipeline.configure_color(root)["color_strength"] == .3
    before = (root / "factory.json").read_bytes()
    result = mcp_server.h_factory_run(str(root), color_strength=.9)
    assert not result["ok"] and "finish before changing color" in result["error"]
    assert (root / "factory.json").read_bytes() == before
    assert mcp_server.h_factory_run(str(root))["status"] == "already_running"


def test_mcp_color_fields_are_optional_without_adding_tools():
    pytest.importorskip("mcp")
    tools = asyncio.run(mcp_server.build_server().list_tools())
    assert len(tools) == 48
    for name in ("factory_new", "factory_run", "factory_edit"):
        schema = next(t.model_dump(by_alias=True)["inputSchema"] for t in tools if t.name == name)
        assert {"color_look", "color_strength", "color_exposure", "color_temperature", "color_tint"} <= schema["properties"].keys()
        assert "color_look" not in schema.get("required", [])
