"""Phone takes wait for sync and the latest brief can travel with them."""
from __future__ import annotations

import html
import json
import os
import subprocess
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing.channels import brief, command, registry, watch
from myzing.factory import pipeline
from myzing.factory.tools import FactoryError
from test_channels_brief import Scripts, Tags, candidate, collect, folder, make as make_brief, series
from test_channels_recordings import NOW, channel, local, media, rows, seed, transcribe

DURATION = watch._duration
OPTIONS = {"settle_seconds": 120, "since": "2026-11-06", "max_seconds": 180, "require_match": True}


def test_absent_phone_settings_leave_roundtrip_unchanged(channel):
    path = registry.directory(channel["slug"]) / "channel.json"
    before = path.read_bytes()
    saved = registry.save(registry.load(channel["slug"]))
    assert path.read_bytes() == before
    assert not set(OPTIONS) & saved["sources"][0].keys()
    assert "phone_folder" not in saved


@pytest.mark.parametrize("field,value", [
    ("settle_seconds", 0), ("settle_seconds", 120), ("since", "2024-02-29"), ("since", "2026-11-06"),
    ("max_seconds", 180), ("max_seconds", 180.0), ("max_seconds", .5),
    ("require_match", True), ("require_match", False),
])
def test_valid_recording_settings_roundtrip(channel, field, value):
    channel["sources"][0][field] = value
    assert registry.save(channel) == registry.load(channel["slug"])
    saved = registry.load(channel["slug"])["sources"][0][field]
    assert saved == value and type(saved) is type(value)


@pytest.mark.parametrize("field,value", [
    ("settle_seconds", -1), ("settle_seconds", True), ("settle_seconds", False), ("settle_seconds", 1.0),
    ("settle_seconds", "120"), ("settle_seconds", None), ("since", True), ("since", 20261106),
    ("since", None), ("since", ""), ("since", "20261106"), ("since", "2026-11-31"),
    ("since", "2026-2-01"), ("since", "2026-11-06T00:00:00"), ("since", "2026-W45-5"),
    ("max_seconds", 0), ("max_seconds", -1), ("max_seconds", True), ("max_seconds", False),
    ("max_seconds", "180"), ("max_seconds", None), ("max_seconds", float("nan")),
    ("max_seconds", float("inf")), ("require_match", 0), ("require_match", 1),
    ("require_match", "true"), ("require_match", None),
])
def test_invalid_recording_settings(channel, field, value):
    channel["sources"][0][field] = value
    with pytest.raises(registry.ChannelError, match=field):
        registry.validate(channel)


@pytest.mark.parametrize("kind", [kind for kind in registry.KINDS if kind != "recordings"])
@pytest.mark.parametrize("field,value", OPTIONS.items())
def test_other_sources_reject_recording_settings(channel, kind, field, value):
    channel["sources"][0].update(kind=kind, **{field: value})
    with pytest.raises(registry.ChannelError, match=field):
        registry.validate(channel)


@pytest.mark.parametrize("value", ["", " \t", None, True, 2, []])
def test_phone_folder_requires_nonempty_text(channel, value):
    channel["phone_folder"] = value
    with pytest.raises(registry.ChannelError, match="phone_folder"):
        registry.validate(channel)


def test_check_and_show_keep_phone_settings(channel, tmp_path, capsys):
    channel["sources"][0].update(OPTIONS)
    channel["phone_folder"] = str(tmp_path / "phone briefs")
    saved = registry.save(channel)
    assert command.run(["check", channel["slug"]]) == 0
    assert json.loads(capsys.readouterr().out) == {"slug": channel["slug"], "problems": []}
    assert command.run(["show", channel["slug"]]) == 0
    assert json.loads(capsys.readouterr().out)["settings"] == saved


def test_since_filters_by_utc_mtime_before_saving_rows(channel, monkeypatch):
    channel["sources"][0]["since"] = "2026-11-06"
    registry.save(channel)
    midnight = NOW.replace(hour=0).timestamp()
    old, today = media(channel, "old.mp4"), media(channel, "today.mp4")
    os.utime(old, (midnight - 1, midnight - 1))
    os.utime(today, (midnight, midnight))
    old.with_suffix(".info.json").write_text(json.dumps({"upload_date": "20261107"}), encoding="utf-8")
    today.with_suffix(".info.json").write_text(json.dumps({"upload_date": "20261101"}), encoding="utf-8")
    calls, _ = transcribe(monkeypatch)
    assert watch.run(channel["slug"], now=NOW) == {"found": 1, "started": 1, "errors": []}
    assert [row["media"] for row in rows(channel)] == [str(today)]
    assert [path for path, _ in calls] == [today]


def test_fresh_take_waits_each_tick_then_starts_at_settle_boundary(channel, monkeypatch):
    take = media(channel)
    os.utime(take, (NOW.timestamp(), NOW.timestamp()))
    calls, _ = transcribe(monkeypatch)
    probes = []
    monkeypatch.setattr(watch, "_duration", lambda path: probes.append(path) or 36)
    root = registry.directory(channel["slug"])
    for seconds in (0, 119):
        assert watch.run(channel["slug"], now=NOW + timedelta(seconds=seconds)) == {
            "found": int(seconds == 0), "started": 0, "errors": []}
        assert rows(channel)[0]["state"] == "found, still syncing"
        assert "skip" not in rows(channel)[0] and "project" not in rows(channel)[0]
        assert not list((root / "inbox").iterdir()) and not list((root / "projects").iterdir())
        assert not calls and not probes
    assert watch.run(channel["slug"], now=NOW + timedelta(seconds=120)) == {"found": 0, "started": 1, "errors": []}
    assert rows(channel)[0]["state"] == "ready"
    assert len(calls) == 1 and probes == [take]


@pytest.mark.parametrize("seconds", [0, 5])
def test_custom_settle_seconds(channel, monkeypatch, seconds):
    channel["sources"][0]["settle_seconds"] = seconds
    registry.save(channel)
    take = media(channel)
    os.utime(take, (NOW.timestamp(), NOW.timestamp()))
    calls, _ = transcribe(monkeypatch)
    assert watch.run(channel["slug"], now=NOW + timedelta(seconds=seconds))["started"] == 1
    assert len(calls) == 1


@pytest.mark.parametrize("limit,seconds,reason", [
    (None, 180.01, "longer than 180 seconds"), (45.5, 46, "longer than 45.5 seconds"),
])
def test_long_take_is_skipped_without_stage_or_transcript(channel, monkeypatch, limit, seconds, reason):
    if limit is not None:
        channel["sources"][0]["max_seconds"] = limit
        registry.save(channel)
    take = media(channel)
    calls, _ = transcribe(monkeypatch)
    probes = []
    monkeypatch.setattr(watch, "_duration", lambda path: probes.append(path) or seconds)
    root = registry.directory(channel["slug"])
    for i in range(2):
        assert watch.run(channel["slug"], now=NOW) == {"found": int(i == 0), "started": 0, "errors": []}
        row, = rows(channel)
        assert row["skip"] == {"reason": reason, "size": take.stat().st_size, "mtime_ns": take.stat().st_mtime_ns}
        assert row["state"] == f"skipped, {reason}" and "project" not in row
        assert not list((root / "projects").iterdir()) and not list((root / "inbox").iterdir())
    assert not calls and probes == [take]


@pytest.mark.parametrize("error", [OSError("unreadable"), ValueError("bad duration"), FactoryError("no ffprobe"),
                                  subprocess.CalledProcessError(1, "ffprobe"), subprocess.TimeoutExpired("ffprobe", 30)])
def test_unreadable_take_is_skipped_and_not_reprobed(channel, monkeypatch, error):
    take = media(channel)
    calls, _ = transcribe(monkeypatch)
    probes = []

    def probe(path):
        probes.append(path)
        raise error
    monkeypatch.setattr(watch, "_duration", probe)
    for i in range(2):
        assert watch.run(channel["slug"], now=NOW) == {"found": int(i == 0), "started": 0, "errors": []}
        row, = rows(channel)
        assert row["state"] == "skipped, could not read the video"
        assert row["skip"] == {"reason": "could not read the video", "size": take.stat().st_size,
                               "mtime_ns": take.stat().st_mtime_ns}
    assert not calls and probes == [take]
    assert not list((registry.directory(channel["slug"]) / "inbox").iterdir())


@pytest.mark.parametrize("output", ["36.5\n", "", "N/A", "nan", "inf", "0", "-1"])
def test_duration_uses_one_ffprobe_and_requires_positive_finite_seconds(monkeypatch, tmp_path, output):
    calls = []
    monkeypatch.setattr(watch, "ffprobe", lambda: "local-ffprobe")

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(stdout=output)
    monkeypatch.setattr(watch.subprocess, "run", run)
    path = tmp_path / "take.mp4"
    if output == "36.5\n":
        assert DURATION(path) == 36.5
    else:
        with pytest.raises(ValueError):
            DURATION(path)
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ["local-ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]
    assert kwargs["check"] and kwargs["timeout"] == 30


@pytest.mark.parametrize("required", [None, False])
def test_unmatched_take_still_starts_when_match_is_optional(channel, monkeypatch, required):
    if required is not None:
        channel["sources"][0]["require_match"] = required
        registry.save(channel)
    media(channel)
    calls, _ = transcribe(monkeypatch)
    monkeypatch.setattr(brief, "match", lambda *args: None)
    assert watch.run(channel["slug"], now=NOW) == {"found": 1, "started": 1, "errors": []}
    row, = rows(channel)
    assert len(calls) == 1 and row["series"] is None and "skip" not in row
    assert (Path(row["project"]) / "factory.json").is_file()


def test_required_match_skips_unmatched_take_and_removes_stage(channel, monkeypatch):
    channel["sources"][0]["require_match"] = True
    registry.save(channel)
    take = media(channel)
    calls, _ = transcribe(monkeypatch)
    probes = []
    monkeypatch.setattr(watch, "_duration", lambda path: probes.append(path) or 36)
    monkeypatch.setattr(brief, "match", lambda *args: None)
    root = registry.directory(channel["slug"])
    for i in range(2):
        assert watch.run(channel["slug"], now=NOW) == {"found": int(i == 0), "started": 0, "errors": []}
        row, = rows(channel)
        assert row["state"] == "skipped, matched no brief item" and "project" not in row
        assert row["skip"] == {"reason": "matched no brief item", "size": take.stat().st_size,
                               "mtime_ns": take.stat().st_mtime_ns}
        assert not list((root / "projects").iterdir()) and not list((root / "inbox").iterdir())
    assert len(calls) == 1 and probes == [take]


@pytest.mark.parametrize("change", ["size", "mtime"])
def test_changed_skipped_take_retries_and_can_match(channel, monkeypatch, change):
    channel["sources"][0]["require_match"] = True
    registry.save(channel)
    path, chosen = seed(channel)
    take = media(channel)
    calls, _ = transcribe(monkeypatch)
    monkeypatch.setattr(brief, "match", lambda *args: None)
    assert watch.run(channel["slug"], now=NOW)["started"] == 0
    stat = take.stat()
    if change == "size":
        take.write_bytes(b"a changed take")
        os.utime(take, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    else:
        os.utime(take, (NOW.timestamp(), NOW.timestamp()))
        assert watch.run(channel["slug"], now=NOW)["started"] == 0
        assert rows(channel)[0]["state"] == "found, still syncing" and "skip" not in rows(channel)[0]
        assert len(calls) == 1
    monkeypatch.setattr(brief, "match", lambda *args: ("2026-11-06", chosen))
    assert watch.run(channel["slug"], now=NOW + timedelta(seconds=120)) == {"found": 0, "started": 1, "errors": []}
    row, = rows(channel)
    assert row["state"] == "ready" and "skip" not in row and len(calls) == 2
    assert row["brief"] == "2026-11-06" and row["series"] == chosen["series"]
    assert pipeline._read(path)["items"][0]["status"] == "recorded"
    assert not list((registry.directory(channel["slug"]) / "inbox").iterdir())


@pytest.mark.parametrize("ready", [True, False])
def test_phone_copy_matches_latest_and_has_no_local_links(channel, tmp_path, ready):
    channel["series"] = [series()]
    channel["phone_folder"] = str(tmp_path / "sync" / "briefs")
    registry.save(channel)
    result = make_brief(channel, judge=Scripts() if ready else None)
    phone = Path(channel["phone_folder"]) / f"{channel['slug']}-brief.html"
    assert phone.read_bytes() == (folder(channel) / "brief.html").read_bytes() == (folder(channel).parent / "latest.html").read_bytes()
    assert not phone.with_suffix(".html.tmp").exists() and not result["errors"]
    page = phone.read_text(encoding="utf-8")
    tags = Tags()
    tags.feed(page)
    assert [(tag, key, value) for tag, attrs in tags.tags for key, value in attrs.items() if key in ("src", "href")] == [
        ("a", "href", result["items"][0]["facts"]["url"])]
    assert "@import" not in page and "url(" not in page
    if not ready:
        assert html.escape(result["items"][0]["pending"]) in page


@pytest.mark.parametrize("url", ["file:///private/take.mp4", "../take.mp4", "C:/takes/take.mp4"])
def test_phone_page_escapes_local_paths_as_text(channel, tmp_path, url):
    channel["phone_folder"] = str(tmp_path / "sync")
    pending = "C:/takes/<draft>&.md"
    path, _ = seed(channel, script=None, facts={"url": url}, pending=pending, receipt=url)
    brief._page(path.parent, channel, pipeline._read(path))
    page = (Path(channel["phone_folder"]) / f"{channel['slug']}-brief.html").read_text(encoding="utf-8")
    tags = Tags()
    tags.feed(page)
    assert not [(tag, key) for tag, attrs in tags.tags for key in attrs if key in ("src", "href")]
    assert pending not in page and html.escape(pending) in page and html.escape(url) in page


def test_older_brief_does_not_replace_phone_copy(channel, tmp_path):
    channel["series"] = [series()]
    channel["phone_folder"] = str(tmp_path / "sync")
    registry.save(channel)
    make_brief(channel, judge=Scripts())
    phone = Path(channel["phone_folder"]) / f"{channel['slug']}-brief.html"
    before = phone.read_bytes()
    brief.make(channel["slug"], now=NOW - timedelta(days=1), judge=Scripts(),
               collectors={"breakdown": collect(candidate("older"))})
    assert phone.read_bytes() == before
    assert (folder(channel, "2026-11-05") / "brief.html").is_file()


@pytest.mark.parametrize("operation", ["mkdir", "write_text", "replace"])
def test_phone_copy_failure_is_saved_once_and_brief_still_finishes(channel, tmp_path, monkeypatch, operation):
    channel["series"] = [series()]
    channel["phone_folder"] = str(tmp_path / "sync")
    registry.save(channel)
    phone = Path(channel["phone_folder"]) / f"{channel['slug']}-brief.html"
    phone.parent.mkdir()
    phone.write_text("previous brief", encoding="utf-8")
    original = getattr(Path, operation)

    def fail(path, *args, **kwargs):
        if path in (phone.parent, phone.with_suffix(".html.tmp")):
            raise OSError("sync unavailable")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, operation, fail)
    for _ in range(2):
        result = make_brief(channel, judge=Scripts())
        assert result["items"][0]["script"] and result["errors"] == ["phone_folder sync unavailable"]
        assert pipeline._read(folder(channel) / "brief.json") == result
        assert (folder(channel) / "brief.html").read_bytes() == (folder(channel).parent / "latest.html").read_bytes()
        assert phone.read_text(encoding="utf-8") == "previous brief"
