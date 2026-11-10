"""Archive builds stay local and keep one episode's cues in flight."""
from __future__ import annotations

import csv
import json
import os
import socket
import sqlite3
import urllib.request
from datetime import date, timedelta

import pytest

from myzing import uoink_bridge
from myzing.channels import resurface_corpus as corpus
from myzing.factory import judge, source


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(urllib.request, "build_opener", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(uoink_bridge, "search_references", refuse)
    monkeypatch.setattr(uoink_bridge, "item_metadata", refuse)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def row(ident="one", **values):
    return {"id": ident, "title": "A test interview", "date": "2020-04-03", "transcript": ident + ".json", **values}


def cues():
    return [{"s": 0, "e": 20, "text": "A flight took months to prepare."},
            {"s": 20, "e": 40, "text": "We changed the engine after that test."},
            {"s": 40, "e": 60, "text": "The next launch worked."}]


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / "Test Show"
    write(root / "manifest.json", [row(duration=60)])
    write(root / "one.json", cues())
    return root


@pytest.mark.parametrize("fallback", [False, True])
def test_305_episodes_resume_and_detect_same_size_same_mtime_change(tmp_path, monkeypatch, fallback):
    root = tmp_path / "Test Show"
    rows = [row(f"ep{i:03}", date=(date(2020, 1, 1) + timedelta(days=i)).isoformat(), duration=60) for i in range(305)]
    write(root / "manifest.json", rows)
    for episode in rows:
        write(root / episode["transcript"], cues())
    calls, pending = [], []
    load, save = source.load_transcript, corpus._write

    def transcript(path, *args, **kwargs):
        assert not pending
        calls.append(path.name)
        pending.append(path.name)
        return load(path, *args, **kwargs)

    def persist(path, value):
        assert len(pending) == 1
        save(path, value)
        pending.clear()
    monkeypatch.setattr(source, "load_transcript", transcript)
    monkeypatch.setattr(corpus, "_write", persist)
    index = corpus.build(root, force_fallback=fallback)
    assert len(calls) == 305 and not pending
    assert index.report == {"indexed": 305, "unchanged": 0, "removed": 0, "errors": [], "backend": index.backend}
    assert index.path == root / ".zing" / "index.sqlite" and index.path.is_file()
    assert corpus.status(root) == {"episodes": 305, "cues": 915, "complete": 305, "incomplete": [],
                                  "oldest": "2020-01-01", "newest": "2020-10-31", "backend": index.backend, "errors": []}
    assert len(list(index.episodes())) == 305
    assert len(list(index.search("engine"))) == 305
    calls.clear()
    again = corpus.build(root, force_fallback=fallback)
    assert calls == [] and again.report["unchanged"] == 305 and again.report["indexed"] == 0
    path = root / "ep017.json"
    stat = path.stat()
    path.write_text(path.read_text(encoding="utf-8").replace("engine", "rocket"), encoding="utf-8")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    changed = corpus.build(root, force_fallback=fallback)
    assert calls == ["ep017.json"] and changed.report["indexed"] == 1 and changed.report["unchanged"] == 304
    assert [hit["episode_id"] for hit in changed.search("rocket")] == ["ep017"]
    assert len(list(changed.search("engine"))) == 304


@pytest.mark.parametrize("kind", ["json", "csv"])
def test_manifest_formats_and_metadata_without_fetching(tmp_path, kind):
    root = tmp_path / "Test Show"
    root.mkdir()
    values = row(guests="Ada Example; Lee Sample", url="http://127.0.0.1/episode",
                 media="https://example.org/video.mp4", description="A  talk\nabout &amp; engines", duration="60")
    if kind == "json":
        write(root / "manifest.json", [values])
    else:
        with (root / "manifest.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=values)
            writer.writeheader()
            writer.writerow(values)
    write(root / "one.json", cues())
    episode = next(corpus.build(root).episodes())
    assert episode["date"] == "2020-04-03" and episode["show"] == "Test Show"
    assert episode["guests"] == ["Ada Example", "Lee Sample"]
    assert episode["description"] == "A talk about & engines"
    assert episode["media"] == values["media"] and episode["url"] == values["url"]
    assert episode["complete"] is True and episode["covered_seconds"] == 60


@pytest.mark.parametrize("suffix,value,timing", [
    ("srt", "1\n00:00:00,000 --> 00:00:40,000\n<b>Ada</b> &amp;   Lee.\n", "captions"),
    ("vtt", "WEBVTT\n\n00:00.000 --> 00:40.000 align:start\n<b>Ada</b> &amp;   Lee.\n", "captions"),
    ("json", [{"s": 0, "e": 40, "text": "Ada &   Lee."}], "captions"),
    ("json", {"words": [{"s": 0, "e": 10, "w": "Ada"}, {"s": 10, "e": 20, "w": "&"},
                         {"s": 20, "e": 40, "w": "Lee."}]}, "words"),
    ("json", [{"start": 0, "end": 10, "text": "Ada"}, {"start": 10, "end": 20, "text": "&"},
              {"start": 20, "end": 40, "text": "Lee."}], "words"),
])
def test_reuses_transcript_formats(tmp_path, suffix, value, timing):
    write(tmp_path / "manifest.json", [row(transcript="one." + suffix)])
    path = tmp_path / ("one." + suffix)
    if suffix == "json":
        write(path, value)
    else:
        path.write_text(value, encoding="utf-8")
    index = corpus.build(tmp_path)
    assert next(index.episodes())["timing_source"] == timing
    assert " ".join(cue["text"] for cue in index.cues("one")) == "Ada & Lee."
    assert next(index.episodes())["complete"] is True


@pytest.mark.parametrize("spans,duration,covered,complete", [
    ([(0, 80)], 100, 80, True), ([(0, 79)], 100, 79, False),
    ([(90, 100)], 100, 10, False), ([(0, 40), (60, 100)], 100, 80, True),
    ([(0, 50), (25, 60)], 100, 60, False), ([(80, 120)], 100, 20, False),
    ([(0, 5)], None, 5, True),
])
def test_completeness_counts_coverage_not_last_timestamp(tmp_path, spans, duration, covered, complete):
    write(tmp_path / "manifest.json", [row(duration=duration)])
    write(tmp_path / "one.json", [{"s": a, "e": b, "text": f"Cue {i}."} for i, (a, b) in enumerate(spans)])
    episode = next(corpus.build(tmp_path).episodes())
    assert episode["covered_seconds"] == covered and episode["complete"] is complete
    assert corpus.status(tmp_path)["incomplete"] == ([] if complete else ["one"])


def test_bad_rows_are_reported_and_missing_transcript_can_be_repaired(archive):
    write(archive / "manifest.json", [row(), row(title="Duplicate"), row("no-date", date=""),
                                      row("missing"), row("bad"), None, row("short-date", date="20200403")])
    (archive / "bad.json").write_text("{bad", encoding="utf-8")
    index = corpus.build(archive)
    assert [episode["id"] for episode in index.episodes()] == ["bad", "missing", "one"]
    assert len(index.report["errors"]) == 6
    assert any("duplicate id" in error for error in index.report["errors"])
    assert any("missing date" in error for error in index.report["errors"])
    assert sum("unreadable transcript" in error for error in index.report["errors"]) == 2
    assert index.cues("missing") == [] and corpus.status(archive)["incomplete"] == ["bad", "missing"]
    write(archive / "missing.json", cues())
    assert "missing" not in corpus.status(corpus.build(archive).archive)["incomplete"]
    assert next(episode for episode in index.episodes() if episode["id"] == "one")["title"] == "A test interview"


@pytest.mark.parametrize("value", ["../outside.json", "/outside.json", "C:\\outside.json", "\\\\server\\share\\one.json",
                                    "https://example.org/transcript.srt", "one.txt", ""])
def test_transcripts_stay_in_archive(archive, value):
    write(archive / "manifest.json", [row(transcript=value)])
    index = corpus.build(archive)
    assert index.cues("one") == [] and len(index.report["errors"]) == 1
    assert "transcript must be" in index.report["errors"][0]


@pytest.mark.parametrize("bad", [[], {}, [{"s": -1, "e": 40, "text": "No."}],
                                [{"s": 0, "e": float("nan"), "text": "No."}],
                                [{"s": 5, "e": 1, "text": "No."}], [{"s": 0, "e": 40, "text": 3}]])
def test_invalid_cues_are_incomplete(archive, bad):
    write(archive / "one.json", bad)
    index = corpus.build(archive)
    assert corpus.status(archive)["incomplete"] == ["one"]
    assert len(index.report["errors"]) == 1 and list(index.search("No")) == []


def test_metadata_changes_and_removed_episodes_do_not_reload_transcripts(archive, monkeypatch):
    corpus.build(archive)
    write(archive / "two.json", cues())
    write(archive / "manifest.json", [row(), row("two")])
    corpus.build(archive)

    def refuse(*args):
        raise AssertionError("unchanged transcript was parsed again")
    monkeypatch.setattr(source, "load_transcript", refuse)
    write(archive / "manifest.json", [row(title="New title", guests=["New Guest"], duration=100)])
    index = corpus.build(archive)
    assert index.report["removed"] == 1 and index.report["unchanged"] == 1
    episode = next(index.episodes())
    assert episode["title"] == "New title" and episode["guests"] == ["New Guest"] and episode["complete"] is False
    assert index.cues("two") == [] and list(index.search("engine", "two")) == []


def test_fallback_updates_then_fts_rebuilds_from_saved_cues(archive, monkeypatch):
    corpus.build(archive)
    write(archive / "one.json", [{"s": 0, "e": 60, "text": "A new rocket."}])
    fallback = corpus.build(archive, force_fallback=True)
    assert fallback.backend == "json" and list(fallback.search("engine")) == []
    expected = list(fallback.search("rocket"))

    def refuse(*args):
        raise AssertionError("unchanged transcript was parsed again")
    monkeypatch.setattr(source, "load_transcript", refuse)
    restored = corpus.build(archive)
    assert list(restored.search("rocket")) == expected
    assert list(restored.search("engine")) == []


def test_missing_fts_module_uses_json(archive, monkeypatch):
    connect = sqlite3.connect

    class NoFTS(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql.startswith("CREATE VIRTUAL TABLE"):
                raise sqlite3.OperationalError("no such module: fts5")
            return super().execute(sql, *args, **kwargs)
    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: connect(*args, **kwargs, factory=NoFTS))
    index = corpus.build(archive)
    assert index.backend == "json" and len(list(index.search("engine"))) == 1


def test_empty_archive_and_uoink_seam(tmp_path):
    write(tmp_path / "manifest.json", [])
    index = corpus.build(tmp_path)
    assert list(index.episodes()) == [] and list(index.search("anyone")) == []
    assert corpus.status(tmp_path)["oldest"] is None and corpus.status(tmp_path)["newest"] is None
    with pytest.raises(ValueError, match="^Uoink cannot return timed cues yet$"):
        corpus.from_uoink("uoink://item/example")


def test_invalid_first_row_is_reported(archive):
    write(archive / "manifest.json", [None, row()])
    index = corpus.build(archive)
    assert len(index.report["errors"]) == 1 and "row 1" in index.report["errors"][0]
    assert len(list(index.episodes())) == 1


@pytest.mark.parametrize("broken", ["{broken", "{}", "[]"])
def test_damaged_cue_cache_is_rebuilt(archive, broken):
    index = corpus.build(archive)
    next((index.path.parent / "cues").glob("*.json")).write_text(broken, encoding="utf-8")
    rebuilt = corpus.build(archive)
    assert rebuilt.report["indexed"] == 1 and rebuilt.report["errors"] == []
    assert rebuilt.cues("one") == cues()


def test_interrupted_build_resumes_finished_episodes(archive, monkeypatch):
    write(archive / "two.json", cues())
    write(archive / "manifest.json", [row(), row("two")])
    load = source.load_transcript
    calls = []

    def interrupted(path):
        calls.append(path.name)
        if path.name == "two.json":
            raise KeyboardInterrupt
        return load(path)
    monkeypatch.setattr(source, "load_transcript", interrupted)
    with pytest.raises(KeyboardInterrupt):
        corpus.build(archive)
    assert calls == ["one.json", "two.json"]
    calls.clear()

    def resume(path):
        calls.append(path.name)
        return load(path)
    monkeypatch.setattr(source, "load_transcript", resume)
    index = corpus.build(archive)
    assert calls == ["two.json"] and index.report["unchanged"] == 1
    assert len(list(index.search("engine"))) == 2


@pytest.mark.parametrize("before,after", [(False, True), (True, False), (False, False)])
def test_interrupted_backend_change_keeps_search_current(archive, monkeypatch, before, after):
    write(archive / "two.json", cues())
    write(archive / "manifest.json", [row(), row("two")])
    corpus.build(archive, force_fallback=before)
    write(archive / "one.json", [{"s": 0, "e": 60, "text": "A rocket test."}])
    write(archive / "two.json", [{"s": 0, "e": 60, "text": "A booster test."}])
    load = source.load_transcript

    def interrupted(path):
        if path.name == "two.json":
            raise KeyboardInterrupt
        return load(path)
    monkeypatch.setattr(source, "load_transcript", interrupted)
    with pytest.raises(KeyboardInterrupt):
        corpus.build(archive, force_fallback=after)
    partial = corpus.Index(archive)
    assert partial.backend == "json"
    assert [hit["episode_id"] for hit in partial.search("rocket")] == ["one"]
    assert [hit["episode_id"] for hit in partial.search("engine")] == ["two"]
    calls = []

    def resume(path):
        calls.append(path.name)
        return load(path)
    monkeypatch.setattr(source, "load_transcript", resume)
    index = corpus.build(archive)
    assert calls == ["two.json"] and index.report["unchanged"] == 1
    assert [hit["episode_id"] for hit in index.search("rocket")] == ["one"]
    assert [hit["episode_id"] for hit in index.search("booster")] == ["two"]
    assert list(index.search("engine")) == []
