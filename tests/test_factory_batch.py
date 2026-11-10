"""Folder batches without transcription, rendering or judge calls."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing.factory import batch, command, judge, pipeline, source, visuals


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(visuals.urllib.request, "urlopen", refuse)
    monkeypatch.setattr(source, "transcribe_episode", refuse)
    monkeypatch.setattr("myzing.project.probe.probe_file", lambda media: SimpleNamespace(duration=3600.0))
    monkeypatch.setattr(source, "transcribe_moments", lambda media, pieces: [])
    monkeypatch.setattr(batch.time, "sleep", lambda seconds: None)


@pytest.fixture
def folders(tmp_path):
    inbox, out = tmp_path / "inbox", tmp_path / "projects"
    inbox.mkdir()
    return inbox, out


def episode(inbox: Path, name="episode.mp4", *, mtime=1) -> Path:
    media = inbox / name
    media.write_bytes(b"video")
    os.utime(media, (mtime, mtime))
    media.with_suffix(".srt").write_text("1\n00:00:01,000 --> 00:00:31,000\nHello.\n", encoding="utf-8")
    return media


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_new_and_batch_save_the_same_settings(folders, monkeypatch, capsys):
    inbox, out = folders
    media = episode(inbox)
    media.with_suffix(".info.json").write_text(json.dumps({"title": "Other", "webpage_url": "https://example.org/other",
                                                          "upload_date": "bad", "uploader": "Other"}), encoding="utf-8")
    transcript = inbox / "supplied.vtt"
    transcript.write_text("WEBVTT\n\n00:00:02.000 --> 00:00:32.000\nSupplied.\n", encoding="utf-8")
    options = ["--transcript", str(transcript), "--offset", "2.5", "--name", "Show", "--url", "https://example.org/show",
               "--date", "May 2026", "--tag", "Source", "--moments", "3", "--focus", "pricing", "--show", "Weekly",
               "--mode", "launch", "--shapes", "16x9,1x1", "--pack", "launch", "--4k", "--brand-name", "Product",
               "--brand-url", "example.org", "--cta", "Try it", "--news-peg", "An update", "--news", "https://example.org/a",
               "--news", "https://example.org/b", "--public", "--no-parallax", "--cutout", "--no-upscale",
               "--vocab", "One,Two", "--vocab", "Three"]
    single = out / "single"
    assert command.run(["new", str(single), "--media", str(media), *options]) == 0
    capsys.readouterr()
    called = []

    def run(project, ask, *, say):
        called.append((project, ask.backend))
        say("resuming episode")
        return pipeline.status(project)

    monkeypatch.setattr(pipeline, "run", run)
    assert command.run(["batch", str(inbox), "--out", str(out), "--judge", "claude", *options]) == 0
    root = out / "episode"
    cfg, expected = read(root / "factory.json"), read(single / "factory.json")
    cfg.pop("created")
    expected.pop("created")
    assert cfg == expected
    assert cfg["vocab"] == ["One", "Two", "Three"]
    assert cfg["brand"] == {"name": "Product", "url": "example.org", "cta": "Try it"}
    assert cfg["news"] == {"peg": "An update", "links": ["https://example.org/a", "https://example.org/b"]}
    assert read(root / "source.json") == read(single / "source.json")
    assert read(root / "transcript.json") == [{"s": 4.5, "e": 34.5, "text": "Supplied."}]
    assert called == [(root, "claude")]
    captured = capsys.readouterr()
    assert json.loads(captured.out)["episodes"][0]["project"] == str(root)
    assert captured.err == "resuming episode\n"


@pytest.mark.parametrize("ext", [".srt", ".vtt", ".json"])
@pytest.mark.parametrize("author", ["uploader", "channel"])
def test_sidecars_and_host_pending_summary(folders, capsys, ext, author):
    inbox, out = folders
    media = episode(inbox, "episode.01.MP4")
    media.with_suffix(".srt").unlink()
    caption = {".srt": "1\n00:00:01,000 --> 00:00:31,000\nHello.\n",
               ".vtt": "WEBVTT\n\n00:00:01.000 --> 00:00:31.000\nHello.\n",
               ".json": json.dumps({"words": [{"w": "Hello.", "s": 1, "e": 31}]})}[ext]
    media.with_suffix(ext).write_text(caption, encoding="utf-8")
    media.with_suffix(".info.json").write_text(json.dumps({"title": "Weekly episode", "webpage_url": "https://example.org/1",
                                                          "upload_date": "20261104", author: "The channel"}), encoding="utf-8-sig")
    assert command.run(["batch", str(inbox), "--out", str(out)]) == 0
    root = out / "episode.01"
    assert read(root / "source.json") == {"media": str(media), "name": "Weekly episode", "url": "https://example.org/1",
                                          "date": "2026-11-04", "tag": "The channel"}
    assert read(root / "transcript.json") == [{"s": 1, "e": 31, "text": "Hello."}]
    assert (root / "words.json").exists() == (ext == ".json")
    summary = json.loads(capsys.readouterr().out)
    assert set(summary) == {"at", "episodes"}
    assert datetime.fromisoformat(summary["at"]).utcoffset().total_seconds() == 0
    assert summary["episodes"] == [{"file": str(media), "project": str(root), "state": "waiting", "clips": 0,
                                     "pending": ["scout"], "cost_usd": 0, "error": None}]
    assert read(out / "batch.jsonl") == summary


def test_caption_order_and_filename_fallback(folders):
    inbox, out = folders
    media = episode(inbox, "My show!.mov")
    media.with_suffix(".vtt").write_text("WEBVTT\n\n00:01.000 --> 00:31.000\nVTT.\n", encoding="utf-8")
    media.with_suffix(".json").write_text('[{"w":"Words.","s":1,"e":31}]', encoding="utf-8")
    batch.run(inbox, out)
    root = out / "My-show"
    assert read(root / "source.json")["name"] == "My show!"
    assert read(root / "transcript.json")[0]["text"] == "Hello."
    assert not (root / "words.json").exists()


def test_done_is_skipped_and_other_projects_resume(folders, monkeypatch):
    inbox, out = folders
    saved = {}
    for i, state in enumerate(("done", "waiting", "failed")):
        media = episode(inbox, state + ".mkv", mtime=i + 1)
        root = out / state
        pipeline.init(root, media, transcript=media.with_suffix(".srt"), moments=2)
        pipeline._write(root / "status.json", {"state": state})
        saved[state] = (root / "factory.json").read_bytes()
    called = []

    def run(project, ask, **kwargs):
        called.append(project.name)
        return pipeline.status(project)

    def refuse(*args, **kwargs):
        raise AssertionError("existing projects must not be recreated")

    monkeypatch.setattr(pipeline, "init", refuse)
    monkeypatch.setattr(pipeline, "run", run)
    result = batch.run(inbox, out, moments=9)
    assert called == ["waiting", "failed"]
    assert [r["state"] for r in result["episodes"]] == ["waiting", "failed"]
    assert all((out / state / "factory.json").read_bytes() == data for state, data in saved.items())


@pytest.mark.parametrize("change", ["size", "mtime"])
def test_a_changing_file_waits_for_a_stable_pass(folders, monkeypatch, change):
    inbox, out = folders
    media = episode(inbox)
    before = media.stat()
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 1:
            if change == "size":
                media.write_bytes(b"growing video")
                os.utime(media, ns=(before.st_atime_ns, before.st_mtime_ns))
            else:
                os.utime(media, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))

    monkeypatch.setattr(batch.time, "sleep", sleep)
    assert batch.run(inbox, out)["episodes"] == []
    assert not (out / "episode").exists()
    assert batch.run(inbox, out)["episodes"][0]["state"] == "waiting"
    assert sleeps == [3, 3]
    assert len((out / "batch.jsonl").read_text().splitlines()) == 2


def test_limit_counts_new_attempts_in_mtime_order_and_still_resumes(folders, monkeypatch):
    inbox, out = folders
    episode(inbox, "a.m4v", mtime=3)
    episode(inbox, "z.webm", mtime=2)
    existing = episode(inbox, "resume.mp4", mtime=4)
    pipeline.init(out / "resume", existing, transcript=existing.with_suffix(".srt"))
    (inbox / "nested").mkdir()
    episode(inbox / "nested", "nested.mp4")
    (inbox / "not-media.mp3").write_bytes(b"audio")
    (inbox / "folder.mp4").mkdir()

    def run(project, ask, **kwargs):
        pipeline._write(project / "status.json", {"state": "done"})
        return pipeline.status(project)

    monkeypatch.setattr(pipeline, "run", run)
    first = batch.run(inbox, out, limit=1)
    assert [Path(r["file"]).name for r in first["episodes"]] == ["z.webm", "resume.mp4"]
    assert not (out / "a").exists()
    assert [Path(r["file"]).name for r in batch.run(inbox, out, limit=1)["episodes"]] == ["a.m4v"]
    assert batch.run(inbox, out)["episodes"] == []


@pytest.mark.parametrize("failure", [RuntimeError("render failed"), RuntimeError()])
def test_one_failure_does_not_stop_others_and_keeps_partial_usage(folders, monkeypatch, failure):
    inbox, out = folders
    for i, name in enumerate(("init", "run", "good")):
        episode(inbox, name + ".mp4", mtime=i + 1)
    initialize = pipeline.init

    def init(project, media, **settings):
        if media.stem == "init":
            raise OSError("could not create project")
        return initialize(project, media, **settings)

    def run(project, ask, **kwargs):
        if project.name == "run":
            pipeline._write(project / "moments.json", {"moments": [{"hook": "One", "start": 1, "end": 10},
                                                                   {"hook": "Two", "start": 11, "end": 30}]})
            clip = project / "clip01"
            clip.mkdir()
            for shape in ("9x16", "1x1"):
                (clip / f"clip-{shape}.mp4").write_bytes(b"render")
            ask._ledger("clip01-plan", {"total_cost_usd": 0.125})
            with pytest.raises(judge.NeedsAnswer):
                ask.ask("clip02-plan", "Plan this clip")
            raise failure
        return {"state": "done", "clips": [], "pending": [], "usage": {"cost_usd": 0}}

    monkeypatch.setattr(pipeline, "init", init)
    monkeypatch.setattr(pipeline, "run", run)
    rows = batch.run(inbox, out)["episodes"]
    assert [r["state"] for r in rows] == ["failed", "failed", "done"]
    assert rows[0]["error"] == "could not create project"
    assert rows[1] == {"file": str(inbox / "run.mp4"), "project": str(out / "run"), "state": "failed", "clips": 1,
                       "pending": ["clip02-plan"], "cost_usd": 0.125, "error": str(failure) or "RuntimeError"}
    assert rows[2]["error"] is None


def test_failed_new_attempt_uses_the_limit(folders):
    inbox, out = folders
    bad = episode(inbox, "bad.mp4", mtime=1)
    bad.with_suffix(".info.json").write_text("[]", encoding="utf-8")
    episode(inbox, "good.mp4", mtime=2)
    rows = batch.run(inbox, out, limit=1)["episodes"]
    assert len(rows) == 1 and rows[0]["state"] == "failed"
    assert not (out / "good").exists()


def test_without_sidecars_the_pipeline_gets_its_usual_transcription(folders, monkeypatch):
    inbox, out = folders
    media = episode(inbox)
    media.with_suffix(".srt").unlink()
    called = []

    def transcribe(path, model):
        called.append((path, model))
        return [{"w": "Hello.", "s": 1, "e": 31}]

    monkeypatch.setattr(source, "scout_model", lambda: None)
    monkeypatch.setattr(source, "transcribe_episode", transcribe)
    assert batch.run(inbox, out, say=lambda m: None)["episodes"][0]["state"] == "waiting"
    assert called == [(media, None)]
    assert read(out / "episode" / "source.json") == {"media": str(media), "name": "episode", "url": "", "date": "", "tag": ""}


def test_colliding_stems_cannot_resume_the_wrong_episode(folders):
    inbox, out = folders
    first = episode(inbox, "a b.mp4", mtime=1)
    second = episode(inbox, "a-b.mov", mtime=2)
    rows = batch.run(inbox, out)["episodes"]
    assert [r["state"] for r in rows] == ["waiting", "waiting"]      # the second file gets its own project
    assert read(out / "a-b" / "source.json")["media"] == str(first)
    other, = [p for p in out.glob("a-b-*") if p.is_dir()]
    assert read(other / "source.json")["media"] == str(second)
    assert batch._project(out, Path("CON.mp4")) == out / "_CON"
    assert batch._project(out, Path("...mp4")) == out / "episode"


@pytest.mark.parametrize("options,every", [([], 60), (["--every", "7"], 7)])
def test_watch_logs_one_line_per_episode_and_stops_cleanly(folders, monkeypatch, capsys, options, every):
    inbox, out = folders
    episode(inbox, "first.mp4")
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        if seconds == every:
            if sleeps.count(every) == 1:
                episode(inbox, "second.mp4", mtime=2)
                episode(inbox, "third.mp4", mtime=3)
            else:
                raise KeyboardInterrupt

    def run(project, ask, **kwargs):
        pipeline._write(project / "status.json", {"state": "done"})
        return pipeline.status(project)

    monkeypatch.setattr(batch.time, "sleep", sleep)
    monkeypatch.setattr(pipeline, "run", run)
    assert command.run(["batch", str(inbox), "--out", str(out), "--watch", "--limit", "1", *options]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [Path(r["file"]).name for r in rows] == ["first.mp4", "second.mp4"]
    assert all(r["state"] == "done" and datetime.fromisoformat(r["at"]) for r in rows)
    assert [json.loads(line) for line in (out / "batch.jsonl").read_text().splitlines()] == rows
    assert sleeps == [3, every, 3, every]
    assert not (out / "third").exists()


def test_watch_can_be_interrupted_during_an_episode(folders, monkeypatch, capsys):
    inbox, out = folders
    episode(inbox)

    def stop(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(pipeline, "run", stop)
    assert command.run(["batch", str(inbox), "--out", str(out), "--watch"]) == 0
    assert capsys.readouterr().out == ""
    assert (out / "episode" / "factory.json").is_file()


@pytest.mark.parametrize("options", [["--every", "0"], ["--every", "-1"], ["--every", "nan"], ["--every", "inf"],
                                     ["--limit", "-1"]])
def test_invalid_batch_options_fail_before_creating_projects(folders, capsys, options):
    inbox, out = folders
    episode(inbox)
    assert command.run(["batch", str(inbox), "--out", str(out), *options]) == 2
    assert not out.exists()
    assert capsys.readouterr().out == ""


def test_empty_inbox_and_zero_limit(folders):
    inbox, out = folders
    assert batch.run(inbox, out)["episodes"] == []
    episode(inbox)
    assert batch.run(inbox, out, limit=0)["episodes"] == []
    assert not (out / "episode").exists()
