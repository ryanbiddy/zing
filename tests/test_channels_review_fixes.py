"""Channel review regressions with local files and fake requests and judges."""
from __future__ import annotations

import json
import os
import random
import re
import shutil
import socket
import urllib.request
from datetime import datetime, timedelta, timezone
from itertools import permutations
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from myzing import uoink_bridge
from myzing.channels import bandit, digest, gate, kit, outcomes, publish, queue, registry, tick, watch, youtube
from myzing.factory import judge, pipeline, plan, postcopy, render, source
from myzing.playbook import feeds, sources, watch as playbook_watch
from myzing.playbook.common import append_jsonl

from test_channels_publish import Response, Transport, reply, session, token

NOW = datetime(2026, 11, 5, 18, tzinfo=timezone.utc)
CHANNEL = "UC" + "a" * 22
VIDEO = "abcdefghijk"


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    monkeypatch.setenv("ZING_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ZING_CHANNELS_HOME", str(tmp_path / "channels"))

    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")

    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(feeds, "request", refuse)
    monkeypatch.setattr(youtube, "_open", refuse)
    monkeypatch.setattr(uoink_bridge, "search_references", refuse)
    monkeypatch.setattr(uoink_bridge, "resolve_kept_media", refuse)
    monkeypatch.setattr(source, "transcribe_moments", lambda *a, **kw: [])
    monkeypatch.setattr(kit, "_video", lambda src, dest: shutil.copyfile(src, dest) and None)


@pytest.fixture
def channel():
    return registry.create("Stories", "Player stories", cadence={"timezone": "UTC+00:00"},
                           publish={"youtube": "private"},
                           youtube={"channel_id": CHANNEL, "title": "Stories", "connected_at": NOW.isoformat()},
                           sources=[{"id": "show", "kind": "podcast", "name": "Show", "url": "https://example.org/show",
                                     "rights": {"status": "permission", "grant": "Email"}}])


def episode(channel, name="episode", n=1, pack="zing"):
    project = registry.directory(channel["slug"]) / "projects" / name
    pipeline._write(project / "factory.json", {**pipeline.SETTINGS, "channel": channel["slug"], "source": "show",
                                              "rights": "permission", "pack": pack, "created": NOW.isoformat()})
    pipeline._write(project / "source.json", {"name": "Show", "url": "https://example.org/episode"})
    pipeline._write(project / "ratings.json", {f"clip{i:02d}": {"v": "post"} for i in range(1, n + 1)})
    for i in range(1, n + 1):
        d = project / f"clip{i:02d}"
        pipeline._write(d / "post.json", {key: "A story" for key in postcopy.FIELDS})
        pipeline._write(d / "context.json", {"flags": []})
        pipeline._write(d / "plan.json", {"hook": "Story", "shots": [{"from": 0, "layout": "solo"}]})
        pipeline._write(d / "cams.json", {})
        pipeline._write(d / "words.json", {"start": 0, "duration": 30, "words": [{"w": "Story.", "os": 0, "oe": 29.55}]})
        pipeline._write(d / "arms.json", {"archetype": "confession"})
        (d / f"clip{render.suffix('9x16', pack)}.mp4").write_bytes(b"video")
    return project


def ready(channel, pack="zing"):
    project = episode(channel, pack=pack)
    assert queue.build(channel["slug"], NOW)["added"] == 1
    assert kit.kit(channel["slug"])["made"] == 1
    return project, queue.read(channel["slug"])[0]


def client(monkeypatch, *responses):
    calls, responses = [], list(responses)

    class Client:
        token = {"project_id": "fixture-project", "channel_id": CHANNEL}

        def __init__(self, slug, **kwargs):
            self.slug = slug

        def checkpoint(self):
            registry.require_running(self.slug)

        def request(self, *args):
            calls.append(args)
            assert responses, "unexpected request"
            response = responses.pop(0)
            if isinstance(response, BaseException):
                raise response
            return 200, {}, json.dumps(response).encode()

    monkeypatch.setattr(youtube, "Client", Client)
    return calls


@pytest.mark.parametrize("context,message", [
    (None, "The context check has not finished."),
    ({"flags": [], "error": "bad answer"}, "The context check failed: bad answer."),
    ({"flags": [], "error": ""}, "The context check failed: ."),
])
def test_gate_requires_a_finished_context_check(channel, context, message):
    project = episode(channel)
    path = project / "clip01" / "context.json"
    if context is None:
        path.unlink()
    else:
        pipeline._write(path, context)
    assert gate.check(project, "clip01", channel, now=NOW) == {"publishable": False, "blockers": [message]}
    pipeline._write(path, {"flags": [], "skipped": "No transcript around this clip."})
    assert gate.check(project, "clip01", channel, now=NOW)["publishable"]


def test_gate_requires_a_brief_check_when_the_project_has_a_brief(channel):
    project = episode(channel)
    assert gate.check(project, "clip01", channel, now=NOW)["publishable"]
    pipeline._write(project / "brief.json", {})
    assert gate.check(project, "clip01", channel, now=NOW)["blockers"] == ["The brief check has not finished."]
    pipeline._write(project / "clip01" / "brief_check.json", {"errors": [], "flags": []})
    assert gate.check(project, "clip01", channel, now=NOW)["publishable"]


@pytest.mark.parametrize("rights", [
    {"status": "unknown", "grant": "Revoked"}, {"status": "permission", "grant": ""},
    {"status": "permission", "grant": "Email", "expires": "2026-11-04"},
])
def test_gate_uses_the_current_source_grant(channel, rights):
    project = episode(channel)
    channel["sources"][0]["rights"] = rights
    result = gate.check(project, "clip01", channel, now=NOW)
    assert not result["publishable"] and "Source rights are unknown." in result["blockers"]
    assert ("The source grant has expired." in result["blockers"]) == ("expires" in rights)
    assert pipeline._read(project / "factory.json")["rights"] == "permission"


@pytest.mark.parametrize("global_pause", [False, True])
def test_track_checks_pause_before_loading_or_requesting(channel, monkeypatch, global_pause):
    root = registry.home() if global_pause else registry.directory(channel["slug"])
    (root / "PAUSE").touch()
    monkeypatch.setattr(registry, "load", lambda slug: pytest.fail("loaded a paused channel"))
    with pytest.raises(registry.ChannelError, match="paused"):
        outcomes.track(channel["slug"])


def test_track_checks_pause_between_resolve_and_feed(channel, monkeypatch):
    channel["handles"]["youtube"] = "@stories"
    registry.save(channel)
    root = registry.directory(channel["slug"])
    before = (root / "queue.jsonl").read_bytes()

    def resolve(*args, **kwargs):
        (root / "PAUSE").touch()
        return CHANNEL

    monkeypatch.setattr(feeds, "resolve", resolve)
    monkeypatch.setattr(feeds, "feed", lambda *a, **kw: pytest.fail("feed ran after pause"))
    with pytest.raises(registry.ChannelError, match="paused"):
        outcomes.track(channel["slug"], now=NOW)
    assert (root / "queue.jsonl").read_bytes() == before
    assert not (root / "snapshots.jsonl").exists() and not (root / "outcomes.jsonl").exists()


@pytest.mark.parametrize("pause", [False, True])
def test_watch_checks_stop_between_resolve_and_feed(channel, monkeypatch, pause):
    channel["sources"][0].update(kind="youtube", url="@stories")
    registry.save(channel)
    stopped = []

    def resolve(*args, **kwargs):
        stopped.append(True)
        if pause:
            (registry.directory(channel["slug"]) / "PAUSE").touch()
        return CHANNEL

    monkeypatch.setattr(feeds, "resolve", resolve)
    monkeypatch.setattr(feeds, "feed", lambda *a, **kw: pytest.fail("feed ran after stop"))
    result = watch.run(channel["slug"], stop=lambda: bool(stopped) and not pause)
    assert result == {"found": 0, "started": 0, "errors": []}


@pytest.mark.parametrize("kind", ["uoink", "youtube"])
@pytest.mark.parametrize("after", ["search", "resolve"])
def test_watch_checks_stop_before_each_kept_media_request(channel, monkeypatch, kind, after):
    channel["sources"][0].update(kind=kind, url="show" if kind == "uoink" else CHANNEL)
    registry.save(channel)
    monkeypatch.setattr(feeds, "feed", lambda *a, **kw: [{"id": VIDEO, "title": "Story", "published": NOW.isoformat()}])
    stopped, calls = [], []

    def search(query):
        calls.append("search")
        if after == "search":
            stopped.append(True)
        return {"ok": True, "results": [{"item_ref": "one"}, {"item_ref": "two"}]}

    def resolve(ref):
        calls.append(ref)
        stopped.append(True)
        return {"ok": False}

    result = watch.run(channel["slug"], search=search, resolve=resolve, stop=lambda: bool(stopped))
    assert calls == (["search"] if after == "search" else ["search", "one"])
    assert result["started"] == 0 and not result["errors"]


@pytest.mark.parametrize("status,reason", [(400, "uploadLimitExceeded"), (429, "quotaExceeded")])
def test_upload_records_quota_blocks_for_any_status(channel, monkeypatch, status, reason):
    ready(channel)
    calls = client(monkeypatch, youtube.Error(status, reason))
    assert reason in publish.upload(channel["slug"], now=NOW)["stopped"]
    assert pipeline._read(registry.directory(channel["slug"]) / "youtube-quota.json")["blocked"] == reason
    assert publish.upload(channel["slug"], now=NOW)["stopped"] == reason
    assert len(calls) == 1
    if reason == "quotaExceeded":
        assert pipeline._read(registry.home() / "youtube-quota.json")["projects"]["fixture-project"]["blocked"] == reason


def changed(project, row, field, pack="zing"):
    d, folder = project / row["clip"], Path(row["kit"])
    if field == "video":
        src, dest = d / f"clip{render.suffix('9x16', pack)}.mp4", folder / "video.mp4"
        src.write_bytes(b"new video")
    else:
        src, dest = d / "post.json", folder / "post.json"
        pipeline._write(src, {**pipeline._read(src), "youtube_title": "New title", "instagram": "New copy"})
    at = src.stat().st_mtime - 10
    os.utime(dest, (at, at))


@pytest.mark.parametrize("pack", ["zing", "documentary"])
@pytest.mark.parametrize("field", ["video", "post"])
def test_stale_kits_block_upload_and_rebuild_in_place(channel, field, pack):
    project, row = ready(channel, pack)
    folder = Path(row["kit"])
    changed(project, row, field, pack)
    result = publish.upload(channel["slug"], now=NOW, dry_run=True)
    assert result["uploads"] == []
    assert result["blocked"] == {row["id"]: ["The kit is older than the clip. Run zing channels kit."]}
    assert kit.kit(channel["slug"])["kits"] == [str(folder)]
    assert queue.read(channel["slug"])[0]["kit"] == str(folder)
    d = project / row["clip"]
    assert (folder / "video.mp4").read_bytes() == (d / f"clip{render.suffix('9x16', pack)}.mp4").read_bytes()
    post = pipeline._read(d / "post.json")
    assert all(pipeline._read(folder / "post.json")[k] == v for k, v in post.items())
    assert (folder / "youtube.txt").read_text(encoding="utf-8").startswith(post["youtube_title"] + "\n\n")
    assert kit.kit(channel["slug"])["made"] == 0
    assert len(publish.upload(channel["slug"], now=NOW, dry_run=True)["uploads"]) == 1


def test_stale_kit_needs_approval_before_rebuilding(channel):
    project, row = ready(channel)
    changed(project, row, "post")
    original = (Path(row["kit"]) / "post.json").read_bytes()
    pipeline._write(project / "ratings.json", {"clip01": {"v": "fix"}})
    result = kit.kit(channel["slug"])
    assert result["made"] == 0 and row["id"] in result["blocked"]
    assert queue.read(channel["slug"])[0]["status"] == "queued"
    assert (Path(row["kit"]) / "post.json").read_bytes() == original
    pipeline._write(project / "ratings.json", {"clip01": {"v": "post"}})
    assert kit.kit(channel["slug"])["made"] == 1


@pytest.mark.parametrize("failure", ["video", "rename"])
def test_failed_kit_replacement_keeps_the_complete_old_folder(channel, monkeypatch, failure):
    project, row = ready(channel)
    changed(project, row, "video")
    folder = Path(row["kit"])
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    rename = Path.rename

    def fail_video(src, dest):
        assert {p.name: p.read_bytes() for p in folder.iterdir()} == before
        raise OSError("remux failed")

    def fail_rename(path, target):
        if path.name == "ready":
            raise OSError("rename failed")
        return rename(path, target)

    if failure == "video":
        monkeypatch.setattr(kit, "_video", fail_video)
    else:
        monkeypatch.setattr(Path, "rename", fail_rename)
    with pytest.raises(OSError, match="failed"):
        kit.kit(channel["slug"])
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before
    assert queue.read(channel["slug"])[0] == row
    assert not list(folder.parent.glob(".kit-*"))


def test_kits_never_change_uploading_rows_or_files(channel):
    project, row = ready(channel)
    folder = Path(row["kit"])
    changed(project, row, "post")
    publish._save_outbox(channel["slug"], [{"id": row["id"], "state": "uploading", "kit": str(folder)}])
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in folder.iterdir()}
    saved = (registry.directory(channel["slug"]) / "outbox.jsonl").read_bytes()
    assert kit.kit(channel["slug"])["made"] == 0
    assert publish.upload(channel["slug"], now=NOW, dry_run=True)["blocked"] == {
        row["id"]: ["The kit is older than the clip. Run zing channels kit."]}
    assert queue.read(channel["slug"])[0] == row
    assert (registry.directory(channel["slug"]) / "outbox.jsonl").read_bytes() == saved
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in folder.iterdir()} == before


def test_caption_fixes_change_only_copy_and_option_text(channel):
    project = episode(channel)
    d = project / "clip01"
    pipeline._write(d / "words.json", {"words": [{"w": word, "os": i, "oe": i + .5}
                                                  for i, word in enumerate(("Name", "how", "own"))]})
    pipeline._write(d / "word-fixes.json", [{"index": i, "os": i, "oe": i + .5, "heard": heard, "meant": meant}
                                          for i, (heard, meant) in enumerate((("Name", "Naim"), ("how", "howe"), ("own", "owen")))])
    metadata = {"title_pattern": "name_claim", "title_candidates": ["name_claim", "how_why"],
                "title_policy": "name-how-own", "title_propensity": .25, "rights": "own", "other": {"text": "Name how own"}}
    post = {**{k: "Name how own" for k in postcopy.FIELDS}, **metadata,
            "title_options": [{"text": "Name how own", "pattern": "name_claim", "note": "Name how own"},
                              {"text": "How own", "pattern": "how_why"}]}
    pipeline._write(project / "brief.json", {"tags": ["#ad"]})
    pipeline._write(d / "post.json", post)
    plan.finalize(d, {"hook": "Story", "shots": [{"from": 0, "layout": "solo"}]}, {})
    fixed = pipeline._read(d / "post.json")
    assert all(fixed[k] == v for k, v in metadata.items())
    assert all(fixed[k] == "Naim howe owen" for k in postcopy.FIELDS if k != "youtube_title")
    assert fixed["youtube_title"] == fixed["title_options"][0]["text"] + " #ad"
    assert fixed["title_options"] == [{"text": "Naim howe owen", "pattern": "name_claim", "note": "Name how own"},
                                      {"text": "howe owen", "pattern": "how_why"}]


def titles():
    return [{"text": "Ada wrote it", "pattern": "name_claim"}, {"text": "How it worked", "pattern": "how_why"}]


@pytest.mark.parametrize("earlier", [4, 5])
@pytest.mark.parametrize("queued", [False, True])
def test_episode_title_history_includes_earlier_clips_once(channel, monkeypatch, earlier, queued):
    project = episode(channel, n=earlier + 2)
    for i in range(1, earlier + 1):
        pipeline._write(project / f"clip{i:02d}" / "arms.json", {"title_pattern": "name_claim"})
    pipeline._write(project / f"clip{earlier + 2:02d}" / "arms.json", {"title_pattern": "how_why"})
    if queued:
        queue.write(channel["slug"], [{"id": "episode/clip01", "project": str(project), "clip": "clip01", "status": "kit",
                                       "slot": NOW.isoformat(), "arms": {"title_pattern": "name_claim"}}])
    d = project / f"clip{earlier + 1:02d}"
    (d / "post.json").unlink()
    calls, choose = [], bandit.choose

    def record(dimension, candidates, rows, rng, **kwargs):
        calls.append((candidates, rows))
        return choose(dimension, candidates, rows, random.Random(31), **kwargs)

    class Copy:
        def ask(self, task, text, images=()):
            if task.endswith("copy"):
                return {**{k: "Story" for k in postcopy.FIELDS}, "titles": titles()}
            return {"hook": "Story", "shots": [{"from": 0, "layout": "solo"}]}

    monkeypatch.setattr(bandit, "choose", record)
    monkeypatch.setattr(render, "render", lambda *a, **kw: None)
    pipeline._clip(project, earlier + 1, {"hook": "Story", "start": 0, "end": 30}, Copy(), project / "media.mp4",
                   pipeline._read(project / "factory.json"), [], lambda m: None)
    candidates, history = calls[0]
    assert {r["id"] for r in history} == {f"episode/clip{i:02d}" for i in range(1, earlier + 1)}
    assert len(history) == earlier
    assert candidates == (["how_why"] if earlier == 5 else ["name_claim", "how_why"])
    assert pipeline._read(d / "post.json")["title_pattern"] == ("how_why" if earlier == 5 else "name_claim")


@pytest.mark.parametrize("alternative", [False, True])
def test_queue_reselects_a_fifth_title_pattern_when_an_alternative_is_allowed(channel, alternative):
    project = episode(channel)
    d = project / "clip01"
    rows = [{"id": f"old{i}/clip01", "project": str(project.parent / f"old{i}"), "clip": "clip01", "status": "posted",
             "slot": (NOW - timedelta(days=5 - i)).isoformat(), "arms": {"title_pattern": "name_claim"}} for i in range(4)]
    queue.write(channel["slug"], rows)
    post = {**pipeline._read(d / "post.json"), "youtube_title": "Ada wrote it", "title_pattern": "name_claim",
            "title_propensity": .25, "title_policy": "baseline", "title_options": titles() if alternative else titles()[:1]}
    pipeline._write(d / "post.json", post)
    pipeline._write(d / "arms.json", {"archetype": "confession", "title_pattern": "name_claim"})
    assert queue.build(channel["slug"], NOW, rng=random.Random(1))["added"] == 1
    fixed = pipeline._read(d / "post.json")
    row = queue.read(channel["slug"])[-1]
    if alternative:
        assert fixed["youtube_title"] == row["title"] == "How it worked"
        assert fixed["title_pattern"] == "how_why" and fixed["title_propensity"] == 1
        assert fixed["title_policy"] in ("explore", "bandit") and fixed["title_candidates"] == ["how_why"]
        assert all(row["arms"][k] == fixed[k] for k in ("title_pattern", "title_propensity", "title_policy", "title_candidates"))
        assert pipeline._read(d / "arms.json") == row["arms"]
    else:
        assert fixed == post and row["title"] == "Ada wrote it"


def test_queue_title_variety_drops_the_oldest_of_ten_and_skipped_rows(channel):
    project = episode(channel)
    rows = [{"id": f"old{i}/clip01", "project": str(project.parent / f"old{i}"), "clip": "clip01", "status": "posted",
             "slot": (NOW - timedelta(days=20 - i)).isoformat(),
             "arms": {"title_pattern": "name_claim" if i in (0, 7, 8, 9) else "quote"}} for i in range(10)]
    rows.append({**rows[-1], "id": "skip/clip01", "project": str(project.parent / "skip"), "status": "skipped"})
    queue.write(channel["slug"], rows)
    post = {**pipeline._read(project / "clip01" / "post.json"), "title_pattern": "name_claim", "title_options": titles()}
    pipeline._write(project / "clip01" / "post.json", post)
    assert queue.build(channel["slug"], NOW)["added"] == 1
    assert pipeline._read(project / "clip01" / "post.json") == post


@pytest.mark.parametrize("all_channels", [False, True])
def test_tick_keeps_going_after_an_invalid_slug(channel, all_channels):
    channel["publish"]["youtube"] = "off"
    registry.save(channel)
    if all_channels:
        pipeline._write(registry.home() / "BAD_SLUG" / "channel.json", {})
    result = tick.run(None if all_channels else ["BAD_SLUG", channel["slug"]],
                      watch_fn=lambda *a, **kw: {"found": 0, "started": 0}, now=NOW)
    assert result["channels"]["BAD_SLUG"]["errors"]
    assert not result["channels"][channel["slug"]]["errors"] and result["exit_code"] == 0


def test_tick_records_a_missing_source_and_advances_another_project(channel):
    channel["publish"]["youtube"] = "off"
    registry.save(channel)
    missing, good = episode(channel, "a-missing", n=0), episode(channel, "b-good", n=0)
    pipeline._write(missing / "factory.json", {**pipeline._read(missing / "factory.json"), "source": "gone"})
    called = []
    result = tick.run([channel["slug"]], runner=lambda p, *a, **kw: called.append(p) or {},
                      watch_fn=lambda *a, **kw: {"found": 0, "started": 0}, now=NOW)
    row = result["channels"][channel["slug"]]
    assert called == [good] and row["advanced"] == 1
    assert any("a-missing" in error and "gone" in error for error in row["errors"])
    assert (registry.directory(channel["slug"]) / "kits" / "index.html").is_file()


@pytest.mark.parametrize("status", [{"state": "failed"}, {"state": "done", "failed": {"clip01": "bad render"}},
                                    {"state": "waiting", "failed": {"clip01": "bad render"}}])
@pytest.mark.parametrize("raises", [False, True])
def test_tick_retries_failures_twice_then_advances_newer_episodes(channel, status, raises):
    channel["publish"]["youtube"] = "off"
    registry.save(channel)
    failed, newer = episode(channel, "a-failed", n=0), episode(channel, "b-newer", n=0)
    pipeline._write(failed / "status.json", status)
    calls = []

    def run(project, *args, **kwargs):
        calls.append(project)
        if project == failed:
            if raises:
                raise ValueError("still failed")
            return status
        return {}

    for _ in range(3):
        result = tick.run([channel["slug"]], runner=run, watch_fn=lambda *a, **kw: {"found": 0, "started": 0}, now=NOW)
    assert calls == [failed, failed, newer]
    assert pipeline._read(failed / "tick_attempts.json") == {"attempts": 2}
    assert result["channels"][channel["slug"]]["notes"] == ["a-failed skipped after two retries."]
    assert not (newer / "tick_attempts.json").exists()


@pytest.mark.parametrize("report", [{}, {"columnHeaders": [{"name": k} for k in ("video", "views", "averageViewPercentage", "subscribersGained")],
                                       "rows": [[VIDEO, 0, None, 0]]}])
@pytest.mark.parametrize("fallback", ["arms", "post", "old"])
def test_analytics_preserves_missing_metrics_and_falls_back_past_nulls(channel, monkeypatch, report, fallback):
    project = episode(channel)
    queue.build(channel["slug"], NOW)
    queue.mark(channel["slug"], "episode/clip01", "posted", "https://youtu.be/" + VIDEO)
    arms = {"title_propensity": .75 if fallback == "arms" else None, "title_policy": "arms" if fallback == "arms" else None}
    pipeline._write(project / "clip01" / "arms.json", arms)
    rows = queue.read(channel["slug"])
    rows[0]["arms"] = arms
    queue.write(channel["slug"], rows)
    pipeline._write(project / "clip01" / "post.json", {"title_propensity": .5 if fallback != "old" else None,
                                                        "title_policy": "post" if fallback != "old" else None})
    metrics = {"views": 120, "engaged_views": 80, "avg_view_pct": 90, "avg_view_duration": 24, "subs": 3}
    outcomes.write(channel["slug"], [{"id": "episode/clip01", **metrics, "views_24h": 50, "propensity": .25, "policy": "old"}])
    client(monkeypatch, report)
    publish.analytics(channel["slug"], now=NOW)
    saved, = outcomes.read(channel["slug"])
    assert {k: saved[k] for k in metrics} == (metrics if not report else {**metrics, "views": 0, "subs": 0})
    assert saved["views_24h"] == 50
    assert (saved["propensity"], saved["policy"]) == ({"arms": .75, "post": .5, "old": .25}[fallback], fallback)


@pytest.mark.parametrize("fallback", ["arms", "post", "old"])
def test_track_falls_back_past_null_propensity_and_policy(channel, monkeypatch, fallback):
    channel["handles"]["youtube"] = CHANNEL
    registry.save(channel)
    project = episode(channel)
    queue.build(channel["slug"], NOW)
    queue.mark(channel["slug"], "episode/clip01", "posted", "https://youtu.be/" + VIDEO)
    rows = queue.read(channel["slug"])
    rows[0]["arms"] = {"title_propensity": .75 if fallback == "arms" else None,
                       "title_policy": "arms" if fallback == "arms" else None}
    queue.write(channel["slug"], rows)
    pipeline._write(project / "clip01" / "post.json", {"title_propensity": .5 if fallback != "old" else None,
                                                        "title_policy": "post" if fallback != "old" else None})
    outcomes.write(channel["slug"], [{"id": "episode/clip01", "propensity": .25, "policy": "old"}])
    monkeypatch.setattr(feeds, "feed", lambda *a, **kw: [])
    outcomes.track(channel["slug"], now=NOW)
    saved, = outcomes.read(channel["slug"])
    assert (saved["propensity"], saved["policy"]) == ({"arms": .75, "post": .5, "old": .25}[fallback], fallback)


def test_pack_render_drives_gate_kits_upload_and_digest(channel):
    project = episode(channel, pack="documentary")
    d = project / "clip01"
    (d / "clip.mp4").write_bytes(b"old default pack")
    pipeline._write(d / "data.json", {"visuals": {"old": {"rights": "unknown"}}})
    pipeline._write(d / "data-documentary.json", {"visuals": {"new": {"rights": "unknown"}}})
    assert any("Picked visuals" in b for b in gate.check(project, "clip01", channel)["blockers"])
    pipeline._write(d / "data-documentary.json", {"visuals": {"new": {"rights": "cleared"}}})
    assert gate.check(project, "clip01", channel)["publishable"]
    at = datetime.now(timezone.utc)
    for name in ("clip.mp4", "clip-documentary.mp4"):
        os.utime(d / name, (at.timestamp(), at.timestamp()))
    assert "1 clip made." in digest.build([channel["slug"]], now=at)
    queue.build(channel["slug"], NOW)
    folder = Path(kit.kit(channel["slug"])["kits"][0])
    assert (folder / "video.mp4").read_bytes() == b"video"
    assert len(publish.upload(channel["slug"], dry_run=True, now=NOW)["uploads"]) == 1
    (d / "clip-documentary.mp4").unlink()
    assert "The 9x16 render is missing." in gate.check(project, "clip01", channel)["blockers"]


def test_pack_render_controls_approval_and_veto_age(channel):
    project = episode(channel, pack="documentary")
    d = project / "clip01"
    old = (NOW - timedelta(hours=7)).timestamp()
    for path in (d / "clip-documentary.mp4", d / "post.json"):
        os.utime(path, (old, old))
    (d / "clip.mp4").write_bytes(b"irrelevant newer file")
    pipeline._write(project / "ratings.json", {"clip01": {"v": "post", "at": NOW.isoformat()}})
    assert gate.check(project, "clip01", channel, now=NOW)["publishable"]
    os.utime(d / "clip-documentary.mp4", (NOW.timestamp() + 1, NOW.timestamp() + 1))
    assert "The clip was edited after approval." in gate.check(project, "clip01", channel, now=NOW)["blockers"]
    pipeline._write(project / "ratings.json", {})
    channel["approval"].update(policy="veto", veto_hours=6)
    assert "The veto window is still open." in gate.check(project, "clip01", channel, now=NOW)["blockers"]
    os.utime(d / "clip-documentary.mp4", (old, old))
    assert gate.check(project, "clip01", channel, now=NOW)["publishable"]


@pytest.mark.parametrize("kind", ["folder", "own"])
def test_folder_sources_never_put_local_paths_in_public_copy(channel, tmp_path, kind):
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    (incoming / "episode.mp4").write_bytes(b"media")
    channel["sources"][0].update(kind=kind, url=str(incoming))
    registry.save(channel)
    result = watch.run(channel["slug"], now=NOW)
    assert result["started"] == 1 and not result["errors"]
    item, = watch.read(registry.directory(channel["slug"]) / "sources" / "show.jsonl")
    project = Path(item["project"])
    assert item["url"] == pipeline._read(project / "source.json")["url"] == ""
    post = postcopy.finalize({k: "Full story {SOURCE_URL}" for k in postcopy.FIELDS}, {"start": 0},
                             pipeline._read(project / "source.json"))
    d = project / "clip01"
    pipeline._write(d / "post.json", post)
    pipeline._write(d / "context.json", {"flags": []})
    pipeline._write(project / "ratings.json", {"clip01": {"v": "post"}})
    (d / "clip.mp4").write_bytes(b"video")
    queue.build(channel["slug"], NOW)
    folder = Path(kit.kit(channel["slug"])["kits"][0])
    for path in (d / "post.json", folder / "post.json", folder / "youtube.txt"):
        text = path.read_text(encoding="utf-8")
        assert "file:" not in text and not re.search(r"[A-Za-z]:[/\\]", text)
        assert str(incoming) not in text and incoming.as_posix() not in text


@pytest.mark.parametrize("url", ["file:///D:/shows/episode.mp4", "D:\\shows\\episode.mp4", "/srv/shows/episode.mp4", "search words"])
def test_source_url_substitution_and_credits_allow_only_web_urls(channel, url):
    project = episode(channel)
    channel["sources"][0].update(kind="uoink", url="search words")
    registry.save(channel)
    assert registry.project_settings(channel["slug"], "show", url=url)["url"] == ""
    assert registry.project_settings(channel["slug"], url=url)["url"] == ""
    pipeline._write(project / "source.json", {"name": "Show", "url": url})
    post = postcopy.finalize({k: "Full {SOURCE_URL}" for k in postcopy.FIELDS}, {"start": 5}, {"url": url})
    assert all(post[k] == "Full " for k in postcopy.FIELDS)
    assert url not in kit._youtube(post, project, channel, "show")
    public = "https://example.org/episode"
    channel["sources"][0]["url"] = public
    registry.save(channel)
    assert registry.project_settings(channel["slug"], "show", url=url)["url"] == public
    assert public in kit._youtube(post, project, channel, "show")


@pytest.mark.parametrize("per_day,allowed", [(1, False), (2, True)])
def test_seeding_counts_at_most_the_daily_cap_in_each_day(channel, per_day, allowed):
    channel["cadence"].update(per_day=per_day, times=["12:00", "17:00", "20:00"])
    channel["seeding"]["every"] = 3
    first = NOW.replace(hour=12)
    second = first + timedelta(days=1)
    rows = [{"slot": first.isoformat(), "own": True, "status": "queued"}]
    assert queue._seed_ok(second, rows, channel) is allowed
    rows[0]["slot"] = second.isoformat()
    assert queue._seed_ok(first, rows, channel) is allowed


def test_channel_id_shaped_handles_resolve_the_handle_page(tmp_path):
    resolved = "UC" + "b" * 22
    calls = []

    def fetch(url):
        calls.append(url)
        return f'<link rel="canonical" href="https://www.youtube.com/channel/{resolved}">'

    assert feeds.resolve(CHANNEL, fetch, root=tmp_path) == CHANNEL and not calls
    assert feeds.resolve("@" + CHANNEL, fetch, root=tmp_path) == resolved
    assert feeds.resolve("@" + CHANNEL, fetch, root=tmp_path) == resolved
    assert calls == ["https://www.youtube.com/@" + CHANNEL]


@pytest.mark.parametrize("text,blocked", [
    ("Full episode: file:///E:/shows/ep.mp4 (at 3:05)", True),
    ("Saved at D:\\shows\\ep.mp4", True),
    ("From E:/AI/inbox/ep.mp4", True),
    ("Full episode: https://example.org/episode?t=185s (at 3:05)", False),
])
def test_gate_blocks_local_paths_in_post_copy(channel, text, blocked):
    project = episode(channel)
    post = pipeline._read(project / "clip01" / "post.json")
    pipeline._write(project / "clip01" / "post.json", {**post, "first_comment": text})
    blockers = gate.check(project, "clip01", channel, now=NOW)["blockers"]
    assert ("Post copy contains a local file path." in blockers) is blocked


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_jsonl_readers_preserve_unicode_separators(channel, ending):
    project, row = ready(channel)
    slug, root = channel["slug"], registry.directory(channel["slug"])
    title = "A\u2028story\u2029with\u0085breaks"
    row["title"] = title
    queue.write(slug, [row])
    entries = [{"id": row["id"], "state": "uploading", "metadata": {"snippet": {"title": title}}}]
    publish._save_outbox(slug, entries)
    results = [{"id": row["id"], "title": title, "views_24h": 10}]
    outcomes.write(slug, results)
    watched = [{"id": VIDEO, "title": title}]
    watch._write(root / "sources" / "show.jsonl", watched)
    ledger = project / "answers" / "_usage.jsonl"
    append_jsonl(ledger, [{"task": "clip01-copy", "title": title, "cost_usd": .25}])
    show = pipeline._show_file("Stories")
    history = [{"clip": "clip01", "hook": title, "v": "post"}]
    append_jsonl(show, history)
    append_jsonl(root / "snapshots.jsonl", [{"id": VIDEO, "channel": slug, "channel_id": CHANNEL, "title": title,
                 "published": (NOW - timedelta(hours=1)).isoformat(), "at": NOW.isoformat(), "views": 10, "short": True}])
    for path in (root / "queue.jsonl", root / "outbox.jsonl", root / "outcomes.jsonl", root / "sources" / "show.jsonl",
                 ledger, show, root / "snapshots.jsonl"):
        text = path.read_text(encoding="utf-8")
        assert title in text
        path.write_bytes((ending + text.replace("\n", ending) + ending).encode("utf-8"))
    assert queue.read(slug) == [row]
    assert publish._outbox(slug) == entries
    assert outcomes.read(slug) == results
    assert watch.read(root / "sources" / "show.jsonl") == watched
    assert judge.Judge(project).usage() == {"calls": 1, "cost_usd": .25}
    assert pipeline.taste(project, {"show": "Stories"}) == history
    assert playbook_watch.velocity(root)["videos"][0]["views"]["1h"] == 10


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_ytdlp_jsonl_preserves_unicode_separators(monkeypatch, ending):
    title = "A\u2028story\u2029with\u0085breaks"
    row = {"id": VIDEO, "title": title, "timestamp": (NOW - timedelta(days=1)).timestamp(), "view_count": 10}
    output = SimpleNamespace(returncode=0, stdout=ending + json.dumps(row, ensure_ascii=False) + ending)
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return output

    monkeypatch.setattr(feeds.doctor, "resolve_ytdlp_argv", lambda: ["yt-dlp"])
    rows = feeds.listing(CHANNEL, runner=run, now=NOW)
    assert len(calls) == 3
    assert [v["title"] for v in rows] == [title, title]
    assert {v["short"] for v in rows} == {False, True}
    monkeypatch.setattr(sources.proc, "run", run)
    assert sources.list_channel(CHANNEL) == [row]


@pytest.mark.parametrize("status", [400, 500])
def test_failed_session_refunds_daily_slot_before_a_later_success(channel, status):
    ready(channel)
    slug = channel["slug"]
    channel["youtube_daily_cap"] = 1
    registry.save(channel)
    youtube.save_token(slug, token())
    failed = Transport(*[Response(status) for _ in range(4 if status == 500 else 1)])
    result = publish.upload(slug, opener=failed, now=NOW, sleep=lambda _: None)
    assert str(status) in result["stopped"] and result["uploaded"] == 0
    assert publish._outbox(slug) == []
    assert pipeline._read(registry.directory(slug) / "youtube-quota.json")["uploads"] == 0
    assert pipeline._read(registry.home() / "youtube-quota.json")["projects"]["fixture-project"]["uploads"] == 0
    succeeded = Transport(session(), reply("video"))
    assert publish.upload(slug, opener=succeeded, now=NOW)["uploaded"] == 1
    assert [r.get_method() for r in succeeded.requests] == ["POST", "PUT"]
    assert pipeline._read(registry.directory(slug) / "youtube-quota.json")["uploads"] == 1
    assert pipeline._read(registry.home() / "youtube-quota.json")["projects"]["fixture-project"]["uploads"] == 1


def test_saved_session_keeps_daily_slot_after_transfer_failure(channel):
    ready(channel)
    slug = channel["slug"]
    channel["youtube_daily_cap"] = 1
    registry.save(channel)
    youtube.save_token(slug, token())
    failed = Transport(session(), *[Response(500) for _ in range(4)])
    result = publish.upload(slug, opener=failed, now=NOW, sleep=lambda _: None)
    assert result["uploaded"] == 0 and "500" in result["stopped"]
    assert publish._outbox(slug)[0]["state"] == "uploading"
    resumed = Transport(reply("video"))
    assert publish.upload(slug, opener=resumed, now=NOW)["uploaded"] == 1
    assert [r.get_method() for r in resumed.requests] == ["PUT"]
    assert pipeline._read(registry.directory(slug) / "youtube-quota.json")["uploads"] == 1
    assert pipeline._read(registry.home() / "youtube-quota.json")["projects"]["fixture-project"]["uploads"] == 1


@pytest.mark.parametrize("reason", ["quotaExceeded", "uploadLimitExceeded"])
def test_refund_preserves_quota_reason_block(channel, monkeypatch, reason):
    ready(channel)
    client(monkeypatch, youtube.Error(403, reason))
    slug = channel["slug"]
    assert reason in publish.upload(slug, now=NOW)["stopped"]
    local = pipeline._read(registry.directory(slug) / "youtube-quota.json")
    shared = pipeline._read(registry.home() / "youtube-quota.json")["projects"]["fixture-project"]
    assert local == {"day": publish._day(NOW), "uploads": 0, "blocked": reason}
    assert shared["uploads"] == 0
    assert shared.get("blocked") == (reason if reason == "quotaExceeded" else None)


@pytest.mark.parametrize("failure", ["session", "outbox"])
def test_unsaved_session_refunds_daily_slot(channel, monkeypatch, failure):
    ready(channel)
    slug = channel["slug"]
    youtube.save_token(slug, token())

    def fail_save(*args):
        raise OSError("outbox write failed")

    if failure == "outbox":
        monkeypatch.setattr(publish, "_save_outbox", fail_save)
    with pytest.raises(OSError if failure == "outbox" else registry.ChannelError):
        publish.upload(slug, opener=Transport(session() if failure == "outbox" else Response()), now=NOW)
    assert publish._outbox(slug) == []
    assert pipeline._read(registry.directory(slug) / "youtube-quota.json")["uploads"] == 0
    assert pipeline._read(registry.home() / "youtube-quota.json")["projects"]["fixture-project"]["uploads"] == 0


@pytest.mark.parametrize("mode", ["scheduled", "private"])
@pytest.mark.parametrize("slot,now,expected", [
    ("2026-11-05T17:00:00+00:00", NOW.replace(second=17), "2026-11-05T18:16:00Z"),
    ("2026-11-05T18:05:00+00:00", NOW.replace(microsecond=1), "2026-11-05T18:16:00Z"),
    ("2026-11-05T18:15:00+00:00", NOW, "2026-11-05T18:15:00Z"),
    ("2026-11-05T12:00:00-08:00", NOW, "2026-11-05T20:00:00Z"),
    ("2026-11-05T20:00:01+00:00", NOW, "2026-11-05T20:01:00Z"),
])
def test_scheduled_metadata_always_has_a_future_whole_minute(channel, mode, slot, now, expected):
    _, row = ready(channel)
    row["slot"] = slot
    channel["publish"]["youtube"] = mode
    status = publish._metadata(row, channel, now)["status"]
    assert status["privacyStatus"] == "private"
    if mode == "scheduled":
        assert status["publishAt"] == expected
    else:
        assert "publishAt" not in status
    assert row["slot"] == slot


@pytest.mark.parametrize("at,end", [("2026-11-05T23:30:00+00:00", "2026-11-05"),
                                   ("2026-11-06T01:30:00+00:00", "2026-11-05")])
@pytest.mark.parametrize("posted", [True, False])
def test_analytics_uses_pacific_dates_for_both_ends(channel, monkeypatch, at, end, posted):
    _, row = ready(channel)
    row.update(status="posted", video_id=VIDEO, slot="2026-11-04T01:30:00+00:00")
    if posted:
        row.update(posted_at="2026-11-03T01:30:00+00:00")
    queue.write(channel["slug"], [row])
    calls = client(monkeypatch, {})
    publish.analytics(channel["slug"], now=datetime.fromisoformat(at))
    query = parse_qs(urlsplit(calls[0][1]).query)
    assert query["endDate"] == [end]
    assert query["startDate"] == ["2026-11-02" if posted else "2026-11-03"]


@pytest.mark.parametrize("complete,minutes,due", [(False, 59, False), (False, 60, True), (False, 61, True),
                                                (True, 60, False), (True, 61, False), (True, 1440, True)])
def test_incomplete_analytics_retries_after_an_hour(channel, complete, minutes, due):
    slug = channel["slug"]
    pipeline._write(registry.directory(slug) / "youtube-analytics.json", {"last_run": NOW.isoformat(), "complete": complete})
    assert publish.analytics_due(slug, NOW + timedelta(minutes=minutes)) is due


@pytest.mark.parametrize("failed", [False, True])
def test_tick_tracks_manual_posts_before_upload(channel, monkeypatch, failed):
    _, row = ready(channel)
    channel["handles"]["youtube"] = "@stories"
    registry.save(channel)
    calls = []
    monkeypatch.setattr(tick.brief, "due", lambda *a: False)
    monkeypatch.setattr(tick, "_advance", lambda *a: None)
    monkeypatch.setattr(queue, "build", lambda *a, **kw: {"added": 0, "blocked": {}})
    monkeypatch.setattr(kit, "kit", lambda *a, **kw: calls.append("kit") or {"made": 0, "blocked": {}})
    monkeypatch.setattr(publish, "analytics_due", lambda *a: True)
    monkeypatch.setattr(publish, "analytics", lambda *a, **kw: calls.append("analytics") or {"matched": 1})

    def track(slug, **kwargs):
        calls.append("track")
        if failed:
            raise registry.ChannelError("tracking failed")
        row.update(status="posted", video_id=VIDEO)
        queue.write(slug, [row])
        return {"matched": 1}

    def upload(slug, **kwargs):
        calls.append("upload")
        assert queue.read(slug)[0]["status"] == "posted"
        return {"uploaded": 0, "blocked": {}, "stopped": None}

    monkeypatch.setattr(outcomes, "track", track)
    monkeypatch.setattr(publish, "upload", upload)
    result = tick.run([channel["slug"]], watch_fn=lambda *a, **kw: {"found": 0, "started": 0}, now=NOW)
    saved = result["channels"][channel["slug"]]
    assert calls == (["kit", "track"] if failed else ["kit", "track", "upload", "analytics"])
    assert saved["errors"] == (["tracking failed"] if failed else [])
    if not failed:
        assert (saved["tracked"], saved["uploaded"], saved["analytics"]) == (1, 0, 1)


def test_queue_build_writes_all_rows_without_appending(channel, monkeypatch):
    episode(channel, n=2)
    write, opened, calls = queue.write, Path.open, []

    def save(slug, rows):
        calls.append([r["id"] for r in rows])
        write(slug, rows)

    def open_file(path, mode="r", *args, **kwargs):
        assert path.name != "queue.jsonl" or "a" not in mode
        return opened(path, mode, *args, **kwargs)

    monkeypatch.setattr(queue, "write", save)
    monkeypatch.setattr(Path, "open", open_file)
    assert queue.build(channel["slug"], NOW)["added"] == 2
    assert calls == [["episode/clip01", "episode/clip02"]]
    assert [r["id"] for r in queue.read(channel["slug"])] == calls[0]


def test_failed_queue_build_write_keeps_the_old_queue(channel, monkeypatch):
    _, old = ready(channel)
    episode(channel, name="another")
    root = registry.directory(channel["slug"])
    before = (root / "queue.jsonl").read_bytes()
    write = Path.write_text

    def fail_write(path, text, *args, **kwargs):
        if path.name.startswith(".queue-"):
            write(path, text[:10], *args, **kwargs)
            raise OSError("disk full")
        return write(path, text, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_write)
    with pytest.raises(OSError, match="disk full"):
        queue.build(channel["slug"], NOW)
    assert (root / "queue.jsonl").read_bytes() == before
    assert queue.read(channel["slug"]) == [old]
    assert not list(root.glob(".queue-*.tmp"))


@pytest.mark.parametrize("order", list(permutations(range(3))))
@pytest.mark.parametrize("status", ["kit", "posted"])
def test_duplicate_feed_ids_match_once_and_prefer_exact_shorts(order, status):
    row = {"id": "episode/clip01", "status": status, "title": "A story"}
    if status == "posted":
        row["video_id"] = VIDEO
    video = {"id": VIDEO, "title": "A story"}
    videos = [{**video, "approximate": True, "short": True, "published": "2026-11-04T00:00:00+00:00"},
              {**video, "approximate": False, "short": False, "published": "2026-11-05T17:00:00+00:00"},
              {**video, "short": True, "published": NOW.isoformat()}]
    assert outcomes._match([row], [videos[i] for i in order]) == 1
    assert row["status"] == "posted" and row["video_id"] == VIDEO
    assert row["url"] == "https://www.youtube.com/shorts/" + VIDEO
    assert row["posted_at"] == NOW.isoformat()


def test_exact_feed_entry_wins_over_an_approximate_short():
    row = {"id": "episode/clip01", "status": "kit", "title": "A story"}
    video = {"id": VIDEO, "title": "A story", "published": NOW.isoformat()}
    assert outcomes._match([row], [{**video, "short": False}, {**video, "short": True, "approximate": True}]) == 1
    assert row["url"] == "https://www.youtube.com/watch?v=" + VIDEO
