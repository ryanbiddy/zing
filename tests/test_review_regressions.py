"""Review regressions with local feeds, judges and render fakes."""
from __future__ import annotations

import hashlib
import os
import socket
import subprocess
from datetime import timedelta
from itertools import islice
from pathlib import Path

import pytest

from myzing.captions.presets import apply_preset
from myzing.channels import brief, queue, registry
from myzing.composition import AssetRef, CompositionAudio, CompositionCaption
from myzing.composition.encoding import DeliveryEncoding
from myzing.factory import pipeline as factory
from myzing.music import measurement
from myzing.music.models import MusicPlan, attach
from myzing.playbook import distill
from myzing.project import probe
from myzing.render import composition, encoding, framing, pipeline
from myzing.render.validation import MediaInfo
from myzing.schemas import Word
from myzing.screen import api, render

from test_channels_brief import Scripts
from test_channels_queue import NOW, channel, episode
from test_channels_updates import item, rss, series
from test_playbook_review_fixes import library
from test_render_review_round5 import fake_render, plan
from test_review_fixes_layout_captions import overlapping_plan


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def test_own_clip_reaches_slot_65_after_existing_schedule(channel):
    channel["seeding"]["every"] = 5
    registry.save(channel)
    episode(channel, source="mine")
    slots = list(islice(queue.slots(channel, [], NOW), 66))
    root = registry.directory(channel["slug"]) / "projects"
    rows = [{"id": f"old{i}/clip01", "project": str(root / f"old{i}"), "clip": "clip01",
             "status": "queued", "own": True, "slot": slots[i].isoformat(), "arms": {"archetype": "other"}}
            for i in range(0, 61, 5)]
    queue.write(channel["slug"], rows)

    result = queue.build(channel["slug"], NOW)

    assert result["added"] == 1 and result["blocked"] == {}
    saved = queue.read(channel["slug"])
    assert saved[:-1] == rows
    assert saved[-1]["id"] == "episode/clip01"
    assert saved[-1]["slot"] == slots[65].isoformat()


@pytest.mark.parametrize("seen_before", [False, True])
def test_news_respects_legacy_seen_id_and_keeps_new_ids(channel, seen_before):
    channel["series"] = [series()]
    registry.save(channel)
    url = "https://www.youtube.com/watch?v=abCDef12_-3"
    legacy = "news-" + hashlib.sha256(url.encode()).hexdigest()[:16]
    seen = registry.directory(channel["slug"]) / "brief" / "seen.json"
    before = {legacy: "2026-11-04"} if seen_before else {}
    factory._write(seen, before)
    feed = rss([item("video", url=url, published=NOW.isoformat())])
    judge = Scripts()

    result = brief.make(channel["slug"], now=NOW, fetch=lambda url: feed, judge=judge)

    assert result["errors"] == []
    assert [row["id"] for row in result["items"]] == ([] if seen_before else ["yt-abCDef12_-3"])
    assert len(judge.calls) == (0 if seen_before else 1)
    assert factory._read(seen) == (before if seen_before else {"yt-abCDef12_-3": result["date"]})
    again = brief.make(channel["slug"], now=NOW + timedelta(days=1), fetch=lambda url: feed, judge=judge)
    assert again["items"] == [] and again["errors"] == []


@pytest.mark.parametrize("stage", ["write", "replace"])
def test_failed_distill_report_removes_temporary_file(tmp_path, monkeypatch, stage):
    library(tmp_path, "A")
    target = tmp_path / "WHATS-WORKING-v0.md"
    target.write_bytes(b"previous report")
    temporary = target.with_suffix(".md.tmp")
    write_text, replace = Path.write_text, Path.replace

    def write(path, text, *args, **kwargs):
        if path == temporary:
            write_text(path, text[:12], *args, **kwargs)
            raise OSError("report write failed")
        return write_text(path, text, *args, **kwargs)

    def publish(path, destination):
        if path == temporary:
            raise OSError("report replace failed")
        return replace(path, destination)

    monkeypatch.setattr(Path, "write_text" if stage == "write" else "replace", write if stage == "write" else publish)
    with pytest.raises(OSError, match=f"report {stage} failed"):
        distill.distill(tmp_path)
    assert target.read_bytes() == b"previous report"
    assert not list(tmp_path.glob("*.tmp"))


def test_screen_render_uses_probe_file_duration_for_mkv(tmp_path, monkeypatch):
    source = tmp_path / "screen.mkv"
    source.write_bytes(b"screen")
    info = probe.parse_probe({"streams": [
        {"codec_type": "video", "width": 960, "height": 540, "avg_frame_rate": "30/1",
         "tags": {"DURATION": "00:00:10.000000000"}}, {"codec_type": "audio"}],
        "format": {"duration": "10.5"}})
    calls = []

    def source_probe(path):
        calls.append(path)
        return info

    monkeypatch.setattr(probe, "probe_file", source_probe)
    monkeypatch.setattr(api.analysis, "freezes", lambda *args: [])
    monkeypatch.setattr(api.analysis, "activity", lambda *args: [])
    screen = api.plan_screen(source, caption_preset="none")
    assert screen.duration == 10.5
    monkeypatch.setattr(framing, "probe_dimensions", lambda *args: (960, 540))
    monkeypatch.setattr(pipeline, "probe_media", lambda path, ffprobe: MediaInfo(10.5, True, True, video_duration=10.))
    monkeypatch.setattr(pipeline, "filter_script_args", lambda ffmpeg, script: ["-filter_complex_script", str(script)])

    def encode(command, **kwargs):
        Path(command[-1]).write_bytes(b"rendered")
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr(render.subprocess, "run", encode)
    result = render.render_screen(screen, tmp_path / "out.mp4", short_side=180)
    assert calls == [source, source]
    assert result["duration"] == screen.duration
    assert Path(result["video"]).read_bytes() == b"rendered"


@pytest.mark.parametrize("old_encoding,old_music", [(False, False), (True, False), (False, True), (True, True)])
@pytest.mark.parametrize("failure", ["video", "music", "encoding"])
def test_failed_publish_restores_receipts(fake_render, tmp_path, monkeypatch, old_encoding, old_music, failure):
    music = tmp_path / "music.wav"
    music.write_bytes(b"music")
    p = plan(fake_render)
    p.delivery = DeliveryEncoding(video_bitrate_kbps=1000)
    p.assets.append(AssetRef("m", str(music), None))
    p.audio = [CompositionAudio(str(music), "music", id="music", asset_id="m", role="music")]
    attach(p, MusicPlan(tracks=[{"id": "music"}]))
    output = tmp_path / "out.mp4"
    output.write_bytes(b"previous video")
    previous = {output.with_suffix(".encoding.json"): b'{ "encoding": "previous" }\r\n' if old_encoding else None,
                output.with_suffix(".music.json"): b'{ "music": "previous" }\r\n' if old_music else None}
    for path, data in previous.items():
        if data is not None:
            path.write_bytes(data)
    monkeypatch.setattr(pipeline, "probe_media", lambda path, *a, **k: MediaInfo(10, path == fake_render, path == music))
    monkeypatch.setattr(encoding, "_audio_bytes", lambda *a: 0)
    monkeypatch.setattr("myzing.audio.media.numpy", lambda: None)
    monkeypatch.setattr(measurement, "measure_mix", lambda *a, **k: {"warnings": []})

    def run(command, **kwargs):
        Path(command[command.index("-f") + 2]).write_bytes(b"rendered")
        return subprocess.CompletedProcess(command, 0, "", "")

    replace = os.replace
    error = PermissionError("publish target is locked")
    published = []
    target = output if failure == "video" else output.with_suffix(f".{failure}.json")

    def publish(source, destination):
        if destination == target:
            if failure == "video":
                assert published == list(previous)
                assert all(path.read_bytes() != data for path, data in previous.items())
            raise error
        replace(source, destination)
        published.append(destination)

    monkeypatch.setattr(pipeline.subprocess, "run", run)
    monkeypatch.setattr(pipeline.os, "replace", publish)
    with pytest.raises(pipeline.RenderError, match="publish target is locked") as raised:
        composition.render_composition(p, output, work_dir=tmp_path / "work")
    assert raised.value.__cause__ is error
    assert output.read_bytes() == b"previous video"
    for path, data in previous.items():
        assert path.read_bytes() == data if data is not None else not path.exists()
    assert not list(tmp_path.glob(".render-*"))


@pytest.mark.parametrize("preset", ["clean", "punch", "box"])
@pytest.mark.parametrize("start,end,owner", [(1.9, 2.3, "B"), (1.6, 1.9, "A")])
def test_caption_owner_keeps_the_longest_overlap(preset, start, end, owner):
    p = overlapping_plan()
    word = Word("Hello", start, end)
    p.captions = [CompositionCaption("Hello", start, end, id="words", words=[word])]
    apply_preset(p, preset, vad=False)
    assert len(p.captions) == 1
    assert p.captions[0].id.startswith(owner + "-")
    assert [(w.text, w.start, w.end) for w in p.captions[0].words] == [("Hello", start, end)]


@pytest.mark.parametrize("preset", ["clean", "punch", "box"])
def test_caption_hard_cut_ownership_is_unchanged(preset):
    p = overlapping_plan()
    p.transitions = []
    p.clips[1].timeline_start = 2
    p.clips[2].timeline_start = 4
    p.captions = [CompositionCaption("Hello", 1.9, 2.3, id="words", words=[Word("Hello", 1.9, 2.3)])]
    apply_preset(p, preset, vad=False)
    assert len(p.captions) == 1
    assert p.captions[0].id.startswith("A-")
    assert [(w.text, w.start, w.end) for w in p.captions[0].words] == [("Hello", 1.9, 2)]
