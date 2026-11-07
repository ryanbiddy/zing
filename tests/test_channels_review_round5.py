"""Channel recovery and isolation regressions with local fixtures."""
from __future__ import annotations

import json
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing.channels import brief, gate, kit, outcomes, publish, queue, registry, tick, youtube
from myzing.factory import pipeline
from myzing.playbook import common, feeds, sources, watch
from test_channels_brief import Scripts, candidate, response, series
from test_channels_publish import Response, Transport, reply, session, token
from test_channels_review_fixes import CHANNEL, NOW, VIDEO, channel, episode, offline, ready


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setattr(youtube, "load_token", lambda slug: token())


@pytest.mark.parametrize("operation", ["build", "mark", "track", "metrics"])
def test_queue_and_outcome_commands_share_the_upload_lock(channel, monkeypatch, tmp_path, operation):
    slug = channel["slug"]
    episode(channel)
    queue.build(slug, NOW)
    channel["handles"]["youtube"] = CHANNEL
    registry.save(channel)
    monkeypatch.setattr(feeds, "feed", lambda *a, **kw: [])
    csv = tmp_path / "metrics.csv"
    csv.write_text("Content,Views,Average percentage viewed,Subscribers\n", encoding="utf-8")
    calls = {"build": lambda: queue.build(slug, NOW),
             "mark": lambda: queue.mark(slug, "episode/clip01", "skipped"),
             "track": lambda: outcomes.track(slug, now=NOW), "metrics": lambda: outcomes.metrics(slug, csv)}
    before = queue.read(slug)
    with youtube.lock(), pytest.raises(registry.ChannelError, match="Another YouTube command"):
        calls[operation]()
    assert queue.read(slug) == before


@pytest.mark.parametrize("module", [queue, outcomes])
def test_jsonl_writers_use_separate_temporary_files(channel, monkeypatch, module):
    slug = channel["slug"]
    row = {"id": "episode/clip01", "project": "episode", "clip": "clip01", "slot": NOW.isoformat(), "status": "kit"}
    replace, paths = Path.replace, []

    def interleave(path, target):
        paths.append(path)
        if len(paths) == 1:
            module.write(slug, [])
        return replace(path, target)

    monkeypatch.setattr(Path, "replace", interleave)
    module.write(slug, [row])
    assert module.read(slug) == [row]
    assert len(set(paths)) == 2 and not any(path.exists() for path in paths)


def test_finish_merges_only_its_row_into_the_current_queue(channel):
    slug = channel["slug"]
    _, row = ready(channel)
    stale = queue.read(slug)
    other = {**row, "id": "other/clip01", "project": str(Path(row["project"]).parent / "other"), "status": "skipped"}
    queue.write(slug, [{**row, "note": "keep this"}, other])
    entry = {"id": row["id"], "state": "uploading"}
    publish._finish(slug, stale, stale[0], [entry], entry, NOW, {"id": VIDEO})
    saved = queue.read(slug)
    assert saved[0]["status"] == "posted" and saved[0]["note"] == "keep this"
    assert saved[1] == other


def test_upload_honors_a_skip_saved_during_another_upload(channel):
    slug = channel["slug"]
    episode(channel, "first")
    episode(channel, "second")
    queue.build(slug, NOW)
    kit.kit(slug)

    def skip(request):
        rows = queue.read(slug)
        rows[1]["status"] = "skipped"
        queue.write(slug, rows)
        return reply("video")

    transport = Transport(session(), skip)
    assert publish.upload(slug, now=NOW, opener=transport)["uploaded"] == 1
    assert [r["status"] for r in queue.read(slug)] == ["posted", "skipped"]
    assert len(transport.requests) == 2


@pytest.mark.parametrize("status", [404, 410])
def test_expired_upload_sessions_restart(channel, status):
    slug = channel["slug"]
    ready(channel)
    with pytest.raises(KeyboardInterrupt):
        publish.upload(slug, now=NOW, opener=Transport(session(), KeyboardInterrupt()))
    transport = Transport(Response(status), session(), reply("video"))
    result = publish.upload(slug, now=NOW, opener=transport)
    assert result["uploaded"] == 1 and result["stopped"] is None
    assert [r.get_method() for r in transport.requests] == ["PUT", "POST", "PUT"]
    assert publish._outbox(slug)[0]["state"] == "done"
    assert pipeline._read(registry.directory(slug) / "youtube-quota.json")["uploads"] == 2


@pytest.mark.parametrize("saved_id", [False, True])
def test_track_does_not_match_uploads_or_reuse_their_saved_video_ids(channel, monkeypatch, saved_id):
    slug = channel["slug"]
    channel["handles"]["youtube"] = CHANNEL
    registry.save(channel)
    episode(channel, n=2)
    queue.build(slug, NOW)
    rows = queue.read(slug)
    rows[1]["title"] = "Saved title"
    queue.write(slug, rows)
    entry = {"id": rows[0]["id"], "state": "uploading"}
    if saved_id:
        entry["video_id"] = VIDEO
    publish._save_outbox(slug, [entry])
    videos = [{"id": ident, "title": title, "published": NOW.isoformat(), "channel_id": CHANNEL,
               "short": True, "views": 20} for ident, title in (("oldvideo123", "A story"), (VIDEO, "Saved title"))]
    monkeypatch.setattr(feeds, "feed", lambda *a, **kw: videos)
    result = outcomes.track(slug, now=NOW)
    saved = queue.read(slug)
    assert saved[0] == rows[0]
    assert result["matched"] == (0 if saved_id else 1)
    assert publish._outbox(slug) == [entry]


def test_mark_posted_without_a_url_keeps_the_video_id(channel):
    slug = channel["slug"]
    _, row = ready(channel)
    queue.write(slug, [{**row, "video_id": VIDEO}])
    assert queue.mark(slug, row["id"], "posted")["video_id"] == VIDEO
    assert queue.mark(slug, row["id"], "posted", "https://youtu.be/oldvideo123")["video_id"] == "oldvideo123"


@pytest.mark.parametrize("policy", ["manual", "veto", "auto"])
def test_title_rotation_keeps_timestamped_approval(channel, policy):
    slug = channel["slug"]
    channel["approval"]["policy"] = policy
    registry.save(channel)
    project = episode(channel)
    post = project / "clip01" / "post.json"
    pipeline._write(post, {"youtube_title": "Ada wrote it", "title_pattern": "name_claim", "title_options": [
        {"text": "Ada wrote it", "pattern": "name_claim"}, {"text": "How it worked", "pattern": "how_why"}]})
    old = (NOW - timedelta(hours=1)).timestamp()
    for path in (post, project / "clip01" / "clip.mp4"):
        os.utime(path, (old, old))
    stamp = post.stat().st_mtime_ns
    pipeline._write(project / "ratings.json", {"clip01": {"v": "post", "at": NOW.isoformat()}})
    queue.write(slug, [{"id": f"old{i}/clip01", "project": str(project.parent / f"old{i}"), "clip": "clip01",
                        "status": "posted", "slot": (NOW - timedelta(days=5 - i)).isoformat(),
                        "arms": {"title_pattern": "name_claim"}} for i in range(4)])
    assert queue.build(slug, NOW, rng=random.Random(1))["added"] == 1
    assert pipeline._read(post)["youtube_title"] == "How it worked"
    assert post.stat().st_mtime_ns == stamp
    assert gate.check(project, "clip01", channel, now=NOW)["publishable"]
    assert kit.kit(slug)["made"] == 1
    assert len(publish.upload(slug, now=NOW, dry_run=True)["uploads"]) == 1


@pytest.mark.parametrize("explicit", [False, True])
def test_tick_uses_fresh_stage_times_unless_now_is_explicit(channel, monkeypatch, explicit):
    slug = channel["slug"]
    channel["cadence"].update(times=["12:00", "13:00"], per_day=2)
    channel["handles"]["youtube"] = CHANNEL
    registry.save(channel)
    project = episode(channel)
    pipeline._write(project / "status.json", {"state": "done"})
    start = NOW.replace(hour=11, minute=45)
    wall, calls = [start], {}

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return wall[0]

    def watched(*args, **kwargs):
        wall[0] += timedelta(minutes=20)
        return {"found": 0, "started": 0}

    def stage(name, result):
        def call(*args, **kwargs):
            calls[name] = kwargs.get("now")
            wall[0] += timedelta(minutes=1)
            return result
        return call

    monkeypatch.setattr(tick, "datetime", Clock)
    monkeypatch.setattr(kit, "kit", stage("kit", {"made": 0, "blocked": {}}))
    monkeypatch.setattr(publish, "upload", stage("upload", {"uploaded": 0, "blocked": {}, "stopped": None}))
    monkeypatch.setattr(publish, "analytics", stage("analytics", {"matched": 0}))
    monkeypatch.setattr(outcomes, "track", stage("track", {"matched": 0}))
    result = tick.run([slug], now=start if explicit else None, watch_fn=watched)
    assert not result["channels"][slug]["errors"]
    assert datetime.fromisoformat(queue.read(slug)[0]["slot"]).hour == (12 if explicit else 13)
    for name, minutes in (("kit", 20), ("upload", 21), ("track", 23)):
        assert calls[name] == (start if explicit else start + timedelta(minutes=minutes))
    if explicit:
        assert calls["analytics"] == start


def test_kit_uses_the_explicit_gate_time(channel):
    slug = channel["slug"]
    channel["approval"].update(policy="veto", veto_hours=6)
    registry.save(channel)
    project = episode(channel)
    pipeline._write(project / "ratings.json", {})
    video = project / "clip01" / "clip.mp4"
    os.utime(video, (NOW.timestamp(), NOW.timestamp()))
    queue.build(slug, NOW + timedelta(hours=7))
    assert kit.kit(slug, now=NOW + timedelta(hours=1))["made"] == 0
    assert kit.kit(slug, now=NOW + timedelta(hours=7))["made"] == 1


def test_episode_failure_does_not_stop_later_tick_stages(channel, monkeypatch):
    slug = channel["slug"]
    channel["handles"]["youtube"] = CHANNEL
    registry.save(channel)
    episode(channel, "a-failed", n=0)
    episode(channel, "b-good")
    called = []

    def fail(*args, **kwargs):
        raise RuntimeError("transcription failed")

    monkeypatch.setattr(publish, "upload", lambda *a, **kw: called.append("upload") or
                        {"uploaded": 0, "blocked": {}, "stopped": None})
    monkeypatch.setattr(publish, "analytics", lambda *a, **kw: called.append("analytics") or {"matched": 0})
    monkeypatch.setattr(outcomes, "track", lambda *a, **kw: called.append("track") or {"matched": 0})
    row = tick.run([slug], now=NOW, runner=fail, watch_fn=lambda *a, **kw: {"found": 0, "started": 0})["channels"][slug]
    assert row["queued"] == row["kits"] == 1
    assert called == ["upload", "analytics", "track"]
    assert any("a-failed" in e and "transcription failed" in e for e in row["errors"])


@pytest.mark.parametrize("file", ["factory.json", "status.json", "tick_attempts.json"])
def test_tick_skips_corrupt_projects_and_advances_a_good_one(channel, file):
    slug = channel["slug"]
    channel["publish"]["youtube"] = "off"
    registry.save(channel)
    bad, good = episode(channel, "a-bad", n=0), episode(channel, "b-good")
    (bad / file).write_text("{bad json", encoding="utf-8")
    called = []
    row = tick.run([slug], now=NOW, runner=lambda p, *a, **kw: called.append(p) or {},
                   watch_fn=lambda *a, **kw: {"found": 0, "started": 0})["channels"][slug]
    assert called == [good] and row["advanced"] == row["kits"] == 1
    assert any("a-bad" in e for e in row["errors"])


@pytest.mark.parametrize("file", ["factory.json", "clip01/post.json", "clip01/context.json", "clip01/arms.json"])
def test_queue_reports_corrupt_inputs_and_keeps_good_clips(channel, file):
    slug = channel["slug"]
    project = episode(channel, "a-bad", n=2)
    episode(channel, "b-good")
    (project / file).write_text("{bad json", encoding="utf-8")
    result = queue.build(slug, NOW)
    assert result["added"] == (1 if file == "factory.json" else 2)
    assert any(ident.startswith("a-bad") for ident in result["blocked"])
    assert "b-good/clip01" in {r["id"] for r in queue.read(slug)}


def test_kit_index_uses_a_file_uri_for_other_drives(channel, monkeypatch, tmp_path):
    _, row = ready(channel)

    def cross_drive(*args):
        raise ValueError("path is on another mount")

    monkeypatch.setattr(kit.os.path, "relpath", cross_drive)
    out = tmp_path / "index"
    out.mkdir()
    path = kit._index(out, channel, [row])
    assert (Path(row["kit"]) / "video.mp4").as_uri() in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("failure", ["timeout", "short", "long"])
def test_automated_brief_failures_retry_three_times_before_manual_fallback(channel, failure):
    channel.update(judge="claude", series=[series()])
    registry.save(channel)
    slug = channel["slug"]

    class Fails:
        def ask(self, task, prompt):
            if failure == "timeout":
                raise TimeoutError("judge timed out")
            return response(script="word " * (59 if failure == "short" else 121))

    for attempt in range(1, 4):
        made = brief.make(slug, now=NOW, judge=Fails(), collectors={"breakdown": lambda *a, **kw: [candidate()]})
        item, = made["items"]
        assert item["attempts"] == attempt
        assert bool(item["pending"]) is (attempt == 3)
        assert brief.due(slug, NOW) is (attempt < 3)
    pending = Path(item["pending"])
    assert pending.is_file()
    brief.Judge(pending.parent.parent).save("script-1", response())
    assert brief.make(slug, now=NOW)["items"][0]["script"] == response()["script"]


def test_automated_brief_can_recover_on_the_second_attempt(channel):
    channel.update(judge="claude", series=[series()])
    registry.save(channel)
    slug = channel["slug"]
    brief.make(slug, now=NOW, judge=Scripts(**{"script-1": response(script="too short")}),
               collectors={"breakdown": lambda *a, **kw: [candidate()]})
    assert brief.due(slug, NOW)
    made = brief.make(slug, now=NOW, judge=Scripts())
    assert made["items"][0]["script"] and not made["items"][0]["pending"] and not made["errors"]
    assert not brief.due(slug, NOW)


@pytest.mark.parametrize("stage", ["resolve", "feed"])
def test_playbook_watch_records_one_channel_failure_and_continues(tmp_path, monkeypatch, stage):
    def resolve(handle, *args, **kwargs):
        if handle == "@bad" and stage == "resolve":
            raise ValueError("HTTP 404")
        return "UC" + ("b" if handle == "@bad" else "a") * 22

    def feed(ident, *args, **kwargs):
        if ident != CHANNEL:
            raise OSError("HTTP 503")
        return [{"id": VIDEO, "title": "Story", "published": NOW.isoformat(), "channel_id": CHANNEL,
                 "views": 10, "short": True}]

    monkeypatch.setattr(feeds, "resolve", resolve)
    monkeypatch.setattr(feeds, "feed", feed)
    result = watch.watch(tmp_path, ["@bad", "@good"], now=NOW)
    assert result["channels"]["@bad"]["status"] == "failed"
    assert result["entries"] == 1 and result["channels"]["@good"]["entries"] == 1
    assert len((tmp_path / "snapshots.jsonl").read_text().splitlines()) == 1


def test_playbook_listing_allows_dotted_handles_and_isolates_invalid_ones(tmp_path, monkeypatch):
    calls = []

    def listing(argv, **kwargs):
        calls.append(argv)
        rows = [{"id": f"v{len(calls)}{i:09d}", "title": "Story", "view_count": i + 1} for i in range(40)]
        return SimpleNamespace(returncode=0, stdout="\n".join(json.dumps(r) for r in rows))

    monkeypatch.setattr(sources.doctor, "resolve_ytdlp_argv", lambda: ["yt-dlp"])
    monkeypatch.setattr(sources.proc, "run", listing)
    result = sources.build(tmp_path, ["@bad/handle", "@some.one", "@good"], skip_newest=0)
    assert result["channels"]["bad/handle"]["status"] == "failed"
    assert result["channels"]["some.one"]["status"] == result["channels"]["good"]["status"] == "listed"
    assert "https://www.youtube.com/@some.one/shorts" == calls[0][-1]
    assert any(row["channel"] == "some.one" for row in result["entries"])
    assert (tmp_path / "channels" / "some_one.json").is_file()
    assert not (tmp_path / "channels" / "bad").exists()
    assert common.library(tmp_path) == result


@pytest.mark.parametrize("watch_only", [False, True])
def test_feed_skips_malformed_entry_dates_and_ids(watch_only):
    entries = [("bad-date", "not a date"), ("bad/id", NOW.isoformat()), (VIDEO, NOW.isoformat())]
    xml = ('<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015" '
           'xmlns:media="http://search.yahoo.com/mrss/">' + "".join(
               f'<entry><yt:videoId>{ident}</yt:videoId><published>{published}</published>'
               '<link href="https://www.youtube.com/watch?v=abcdefghijk"/>'
               '<media:statistics views="10"/></entry>' for ident, published in entries) + '</feed>')
    assert [r["id"] for r in feeds.feed(CHANNEL, lambda url: xml, watch_only=watch_only)] == [VIDEO]
