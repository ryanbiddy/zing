"""Channel settings and factory defaults without model calls."""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

import pytest

from myzing.channels import command, registry
from myzing.cli import main
from myzing.factory import campaign, judge, pipeline, postcopy
from myzing.factory.command import run
from myzing.factory.tools import FactoryError, NO_HOOK, data_path


@pytest.fixture(autouse=True)
def local(tmp_path, monkeypatch):
    monkeypatch.setenv("ZING_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ZING_CHANNELS_HOME", str(tmp_path / "channels"))

    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)


@pytest.fixture
def channel():
    return registry.create("Gridiron Lore", "Players telling stories")


def test_defaults_paths_and_roundtrip(channel, tmp_path, monkeypatch):
    assert channel["slug"] == "gridiron-lore"
    assert channel["factory"] == {}
    assert channel["approval"] == {"policy": "manual", "veto_hours": 6, "manual_first": 30}
    assert channel["cadence"] == {"per_day": 3, "times": ["12:00", "17:00", "20:00"], "timezone": "local"}
    assert channel["seeding"] == {"every": 8}
    root = registry.directory(channel["slug"])
    assert all((root / name).exists() for name in ("channel.json", "queue.jsonl", "projects", "kits"))
    assert registry.load(channel["slug"]) == channel
    with pytest.raises(registry.ChannelError, match="already exists"):
        registry.create(channel["name"], channel["niche"])
    monkeypatch.delenv("ZING_CHANNELS_HOME")
    assert registry.home() == tmp_path / "home" / "channels"


@pytest.mark.parametrize("field,value", [
    ("schema_version", 2), ("schema_version", True), ("name", ""), ("name", 1),
    ("slug", "../escape"), ("slug", "UPPER"), ("slug", "con"), ("slug", "a" * 61),
    ("niche", ""), ("niche", "a" * 201), ("created", "yesterday"), ("created", None),
    ("network", []), ("network.name", 2), ("network.url", "file:///secret"), ("network.url", "https://"),
    ("network.extra", "x"), ("handles.youtube", 1), ("handles.other", "@x"),
    ("factory", []), ("factory.pack", "missing-pack"), ("factory.pack", None),
    ("factory.mode", "bad"), ("factory.shapes", ["1x1"]), ("factory.shapes", ["9x16", "bad"]),
    ("factory.shapes", "9x16"), ("factory.shapes", ["9x16", "9x16"]), ("factory.shapes", [["9x16"]]),
    ("factory.moments", -1), ("factory.moments", True), ("factory.focus", ""), ("factory.focus", "x" * 301),
    ("factory.vocab", "word"), ("factory.vocab", [""]), ("factory.vocab", [4]),
    ("factory.brief", []), ("factory.brief", {"min_seconds": 10, "max_seconds": 3}),
    ("factory.brief", {"disclosure_seconds": 8}), ("factory.brief", {"tags": [1]}),
    ("factory.extra", 1), ("sources", {}), ("cadence", []),
    ("cadence.per_day", 0), ("cadence.per_day", 25), ("cadence.per_day", True),
    ("cadence.times", ["9:00"]), ("cadence.times", ["24:00"]), ("cadence.times", ["12:60"]),
    ("cadence.times", []), ("cadence.times", ["12:00", "12:00"]), ("cadence.times", [None]),
    ("cadence.timezone", "Not/AZone"), ("cadence.timezone", 4),
    ("approval.policy", "yes"), ("approval.veto_hours", -1), ("approval.veto_hours", float("nan")),
    ("approval.manual_first", -1), ("approval.manual_first", True), ("seeding.every", 0),
    ("seeding.every", 1.5), ("extra", 1),
])
def test_bad_settings_name_the_field(channel, field, value):
    data = copy.deepcopy(channel)
    parts = field.split(".")
    target = data
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value
    with pytest.raises(registry.ChannelError) as exc:
        registry.save(data)
    assert field in str(exc.value)
    assert registry.load(channel["slug"]) == channel
    pipeline._write(registry.directory(channel["slug"]) / "channel.json", data)
    with pytest.raises(registry.ChannelError):
        registry.load(channel["slug"])


def source():
    return {"id": "club", "name": "Club", "kind": "podcast", "url": "https://example.org/episode",
            "rights": {"status": "permission", "grant": "Email from owner", "expires": "", "note": ""}}


@pytest.mark.parametrize("field,value", [
    ("id", "../bad"), ("name", ""), ("kind", "bad"), ("url", 5), ("rights.status", "cleared"),
    ("rights.status", []), ("rights.grant", " "), ("rights.expires", "2026-2-03"),
    ("rights.expires", "2026-02-30"), ("rights.note", None), ("rights.extra", "x"),
])
def test_bad_sources(channel, field, value):
    src = source()
    target = src["rights"] if field.startswith("rights.") else src
    target[field.split(".")[-1]] = value
    channel["sources"] = [src]
    with pytest.raises(registry.ChannelError) as exc:
        registry.save(channel)
    assert f"sources[0].{field}" in str(exc.value)


def test_expiry_and_unique_sources(channel):
    src = source()
    src["rights"]["expires"] = "2026-11-05"
    now = datetime(2026, 11, 5, tzinfo=timezone.utc)
    assert registry.effective_rights(src, now) == "permission"
    assert registry.effective_rights(src, now.replace(day=6)) == "unknown"
    channel["sources"] = [src, src]
    with pytest.raises(registry.ChannelError, match="id must be unique"):
        registry.save(channel)
    with pytest.raises(registry.ChannelError, match="source absent"):
        registry.source(channel, "absent")


def test_brief_validation_is_shared(tmp_path, channel):
    brief = {"tags": [" #ad ", "#ad"], "min_seconds": 3, "max_seconds": 30}
    path = tmp_path / "brief.json"
    pipeline._write(path, brief)
    channel["factory"]["brief"] = brief
    assert registry.save(channel)["factory"]["brief"] == campaign.load(path) == campaign.validate(copy.deepcopy(brief))
    pipeline._write(path, {"bogus": True})
    with pytest.raises(FactoryError, match="unknown brief fields"):
        campaign.load(path)


def test_factory_inherits_and_flags_win(channel, tmp_path, capsys):
    channel["network"] = {"name": "Replay Network", "line": "Part of Replay.", "url": "https://example.org"}
    channel["factory"] = {"pack": "swiss", "mode": "fun", "shapes": ["9x16"], "moments": 6,
                          "focus": "Player stories", "vocab": ["Shannon"], "brief": {"tags": ["#ad"]}}
    channel["sources"] = [source()]
    registry.save(channel)
    media = tmp_path / "episode.mp4"
    media.write_bytes(b"media")
    args = ["new", "--media", str(media), "--channel", channel["slug"], "--source", "club"]
    assert run(args) == 0
    project = registry.directory(channel["slug"]) / "projects" / "episode"
    cfg = pipeline._read(project / "factory.json")
    assert {key: cfg[key] for key in channel["factory"] if key != "brief"} == {key: value for key, value in channel["factory"].items() if key != "brief"}
    assert cfg["channel"] == cfg["show"] == channel["slug"] and cfg["source"] == "club"
    assert cfg["rights"] == "permission"
    assert cfg["brand"] == {"name": "Replay Network", "cta": "Part of Replay.", "url": "https://example.org"}
    assert pipeline._read(project / "brief.json") == {"tags": ["#ad"]}
    explicit = tmp_path / "explicit"
    assert run(args + [str(explicit), "--pack", "zing", "--mode", "context", "--moments", "0", "--shapes", "9x16,1x1",
                       "--vocab", "Ryan", "--rights", "own", "--brand-name", "Ryan", "--brand-url", "https://example.net",
                       "--cta", "More stories", "--focus", "Coaches", "--show", "ignored"]) == 0
    cfg = pipeline._read(explicit / "factory.json")
    assert (cfg["pack"], cfg["mode"], cfg["moments"], cfg["rights"], cfg["vocab"]) == ("zing", "context", 0, "own", ["Ryan"])
    assert cfg["shapes"] == ["9x16", "1x1"] and cfg["focus"] == "Coaches"
    assert cfg["brand"] == {"name": "Ryan", "url": "https://example.net", "cta": "More stories"}
    assert cfg["show"] == channel["slug"]
    assert run(["new", str(tmp_path / "old"), "--media", str(media)]) == 0
    cfg = pipeline._read(tmp_path / "old" / "factory.json")
    assert cfg["channel"] is cfg["source"] is None
    assert cfg["mode"] == "context" and cfg["rights"] == "unknown"
    assert run(["new", "--media", str(media)]) == 2
    assert run(["new", str(tmp_path / "bad"), "--media", str(media), "--source", "club"]) == 2


def test_expired_source_and_partial_brand_override(channel, tmp_path):
    src = source()
    src["rights"]["expires"] = "2001-01-01"
    channel["sources"] = [src]
    registry.save(channel)
    media = tmp_path / "episode.mp4"
    media.write_bytes(b"media")
    assert run(["new", "--media", str(media), "--channel", channel["slug"], "--source", "club", "--cta", "Read more"]) == 0
    cfg = pipeline._read(registry.directory(channel["slug"]) / "projects" / "episode" / "factory.json")
    assert cfg["rights"] == "unknown"
    assert cfg["brand"] == {"name": channel["name"], "url": "", "cta": "Read more"}


@pytest.mark.parametrize("mode", ["context", "launch"])
def test_no_voice_keeps_the_exact_old_prompt(channel, mode):
    moment, words, src = {"hook": ""}, {"words": [{"w": "Story"}]}, {"name": "Show"}
    expected = data_path("prompts", "copy-launch.md" if mode == "launch" else "copy.md").read_text(encoding="utf-8")
    for key, value in {"{SOURCE}": "Show", "{HOOK}": NO_HOOK, "{DATE}": "unknown", "{BRAND}": "none given",
                       "{NEWS}": "none given", "{TEXT}": "Story"}.items():
        expected = expected.replace(key, value)
    assert postcopy.prompt(moment, words, src, mode, voice=registry.voice(channel["slug"])) == expected
    assert postcopy.prompt(moment, words, src, mode, voice="Use short titles.") == expected + "\n\nCHANNEL VOICE\nUse short titles."


def test_pipeline_passes_voice_to_the_copy_judge(channel):
    root = registry.directory(channel["slug"])
    (root / "voice.md").write_text("Use short titles.", encoding="utf-8")
    project = root / "projects" / "episode"
    d = project / "clip01"
    pipeline._write(d / "cams.json", {})
    pipeline._write(d / "words.json", {"start": 0, "duration": 1, "words": [{"w": "Story", "os": 0, "oe": 1}]})

    class Copy:
        def ask(self, task, text, images=()):
            if task.endswith("-copy"):
                assert text.endswith("CHANNEL VOICE\nUse short titles.")
                return {key: "Story" for key in postcopy.FIELDS}
            raise judge.NeedsAnswer(task, project / "pending" / f"{task}.md")

    cfg = {**pipeline.SETTINGS, "channel": channel["slug"]}
    pipeline._clip(project, 1, {"hook": "Story"}, Copy(), project / "media.mp4", cfg, [], lambda m: None)
    assert (d / "post.json").is_file()
    (root / "voice.md").write_text("x" * 4001, encoding="utf-8")
    with pytest.raises(registry.ChannelError, match="voice.md"):
        registry.load(channel["slug"])
    with pytest.raises(registry.ChannelError, match="voice.md"):
        registry.save(channel)


def test_channel_ratings_share_factory_history(channel):
    root = registry.directory(channel["slug"])
    for name, vote in (("one", "post"), ("two", "no")):
        project = root / "projects" / name
        pipeline._write(project / "factory.json", {"show": channel["slug"]})
        pipeline._write(project / "moments.json", {"moments": [{"hook": name, "topic": "stories"}]})
        pipeline.rate(project, "clip01", vote)
    got = pipeline.taste(root / "projects" / "three", {"show": channel["slug"]})
    assert {r["v"] for r in got} == {"post", "no"}


def test_cli_new_source_show_check_and_errors(tmp_path, capsys):
    assert main(["channels", "new", "stories", "--name", "Stories", "--niche", "Player stories"]) == 0
    args = ["source", "stories", "--id", "club", "--name", "Club", "--kind", "podcast", "--url", "https://example.org",
            "--rights", "permission", "--grant", "Email"]
    assert command.run(args) == 0
    assert command.run(args + ["--note", "Updated"]) == 0
    assert len(registry.load("stories")["sources"]) == 1
    assert registry.load("stories")["sources"][0]["rights"]["note"] == "Updated"
    assert command.run(["list"]) == 0
    capsys.readouterr()
    assert command.run(["show", "stories"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["counts"] == {} and not shown["paused"] and shown["next_slot"]
    assert command.run(["check", "stories"]) == 0
    (registry.directory("stories") / "channel.json").write_text("{}", encoding="utf-8")
    capsys.readouterr()
    assert command.run(["check", "stories"]) == 1
    assert "schema_version" in json.loads(capsys.readouterr().out)["problems"][0]
    assert command.run(["show", "absent"]) == 2
    assert "zing channels:" in capsys.readouterr().err


def test_zones_work_without_tzdata():
    from datetime import datetime, timedelta, timezone as tz
    assert registry.zone("UTC-08:00").utcoffset(None) == timedelta(hours=-8)
    assert registry.zone("UTC+05:30").utcoffset(None) == timedelta(hours=5, minutes=30)
    local = datetime(2026, 7, 1, 12, tzinfo=registry.zone("local"))
    assert local.utcoffset() == datetime(2026, 7, 1, 12).astimezone().utcoffset()
    assert local.astimezone(tz.utc).astimezone(registry.LOCAL) == local
    for bad in ("UTC+15:00", "UTC-08:60", "Not/AZone"):
        with pytest.raises(registry.ChannelError, match="timezone"):
            registry.zone(bad)
