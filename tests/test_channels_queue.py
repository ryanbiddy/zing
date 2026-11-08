"""Local gates, scheduling and post kits."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections import Counter
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import pytest

from myzing.channels import command, gate, kit, queue, registry
from myzing.factory import pipeline, tools

NOW = datetime(2026, 11, 5, 18, tzinfo=timezone.utc)
try:
    registry.zone("America/Los_Angeles")
    HAS_TZDATA = True
except registry.ChannelError:
    HAS_TZDATA = False


@pytest.fixture
def channel(tmp_path, monkeypatch):
    monkeypatch.setenv("ZING_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ZING_CHANNELS_HOME", str(tmp_path / "channels"))
    channel = registry.create("Stories", "Player stories", sources=[
        {"id": "club", "name": "Club", "kind": "podcast", "url": "https://example.org/show",
         "rights": {"status": "permission", "grant": "Email"}},
        {"id": "mine", "name": "My show", "kind": "own", "url": str(tmp_path),
         "rights": {"status": "own", "grant": "Recorded by me"}}])
    channel["cadence"]["timezone"] = "UTC-08:00"
    return registry.save(channel) or channel


def episode(channel, name="episode", n=1, *, source="club", rating="post", title="Story"):
    project = registry.directory(channel["slug"]) / "projects" / name
    pipeline._write(project / "factory.json", {**pipeline.SETTINGS, "channel": channel["slug"], "source": source,
                                              "rights": "permission", "show": channel["slug"]})
    pipeline._write(project / "source.json", {"name": "Club episode", "url": "https://example.org/episode"})
    pipeline._write(project / "ratings.json", {f"clip{i:02d}": {"v": rating} for i in range(1, n + 1)})
    for i in range(1, n + 1):
        d = project / f"clip{i:02d}"
        pipeline._write(d / "post.json", {"youtube_title": title, "instagram": "Caption <&>", "tiktok": "TikTok",
                                          "x": "X", "first_comment": "Full story", "extra": {"kept": True}})
        pipeline._write(d / "plan.json", {"visuals": {}})
        pipeline._write(d / "context.json", {"flags": []})
        pipeline._write(d / "brief_check.json", {"errors": [], "flags": []})
        (d / "clip.mp4").write_bytes(b"placeholder")
    return project


@pytest.mark.parametrize("file,value,message", [
    ("factory.json", {"rights": "unknown"}, "Source rights"),
    ("clip01/plan.json", {"visuals": {"a": {"rights": "editorial"}}}, "Picked visuals"),
    ("clip01/plan.json", {"visuals": {"a": {}}}, "Picked visuals"),
    ("clip01/context.json", {"flags": [{"why": "missing context"}]}, "Context flags"),
    ("clip01/brief_check.json", {"errors": ["length"]}, "Brief errors"),
    ("clip01/brief_check.json", {"flags": [{"why": "tag"}]}, "Brief flags"),
    ("clip01/clip.mp4", None, "9x16 render"), ("clip01/post.json", None, "Post copy"),
    ("ratings.json", {"clip01": {"v": "no"}}, "rated No"),
    ("ratings.json", {}, "Manual approval"), ("ratings.json", {"clip01": {"v": "fix"}}, "Manual approval"),
])
def test_each_gate_blocker(channel, file, value, message):
    project = episode(channel)
    assert gate.check(project, "clip01", channel, now=NOW)["publishable"]
    if value is None:
        (project / file).unlink()
    else:
        pipeline._write(project / file, value)
    result = gate.check(project, "clip01", channel, now=NOW)
    assert not result["publishable"] and any(message in b for b in result["blockers"])
    assert pipeline._read(project / "clip01" / "gate.json") == result


def test_visual_picks_and_fallbacks(channel):
    project = episode(channel)
    d = project / "clip01"
    pipeline._write(d / "visuals" / "manifest.json", {"a": [{"rights": "editorial"}, {"rights": "attribution"}]})
    pipeline._write(d / "visuals" / "picks.json", {"picks": {"a": {"pick": 1}}})
    assert gate.check(project, "clip01", channel)["publishable"]
    pipeline._write(d / "visuals" / "picks.json", {"picks": {"a": {"pick": 0}}})
    assert not gate.check(project, "clip01", channel)["publishable"]
    pipeline._write(d / "visuals" / "picks.json", {"picks": {"a": {"pick": None}}})
    assert gate.check(project, "clip01", channel)["publishable"]
    pipeline._write(d / "visuals" / "picks.json", {"picks": {}})
    assert not gate.check(project, "clip01", channel)["publishable"]
    pipeline._write(d / "visuals" / "manifest.json", {})
    (d / "plan.json").unlink()
    pipeline._write(d / "data.json", {"visuals": {"a": {"rights": "unknown"}}})
    assert not gate.check(project, "clip01", channel)["publishable"]


def test_expired_grant_blocks_an_existing_project(channel):
    project = episode(channel)
    channel["sources"][0]["rights"]["expires"] = "2026-11-04"
    assert "The source grant has expired." in gate.check(project, "clip01", channel, now=NOW)["blockers"]
    channel["sources"][0]["rights"] = {"status": "unknown", "grant": "", "expires": "2099-11-04"}
    assert not gate.check(project, "clip01", channel, now=NOW)["publishable"]


def test_missing_manifest_entries_and_unaccounted_render_visuals_block(channel):
    project = episode(channel)
    d = project / "clip01"
    pipeline._write(d / "visuals" / "picks.json", {"picks": {"lost": {"pick": 0}}})
    assert not gate.check(project, "clip01", channel)["publishable"]
    pipeline._write(d / "visuals" / "picks.json", {"picks": {"lost": {"pick": None}}})
    pipeline._write(d / "data.json", {"visuals": {"lost": {"src": "image.png"}}})
    assert not gate.check(project, "clip01", channel)["publishable"]
    pipeline._write(d / "plan.json", {"visuals": {"lost": {"rights": "cleared"}}})
    assert gate.check(project, "clip01", channel)["publishable"]


def test_veto_waits_from_render_and_never_approves_no_or_fix(channel):
    project = episode(channel, rating=None)
    channel["approval"].update(policy="veto", veto_hours=6)
    video = project / "clip01" / "clip.mp4"
    for hours, allowed in ((5.99, False), (6, True), (7, True), (-1, False)):
        stamp = (NOW - timedelta(hours=hours)).timestamp()
        os.utime(video, (stamp, stamp))
        assert gate.check(project, "clip01", channel, now=NOW)["publishable"] is allowed
    for vote, allowed in (("post", True), ("no", False), ("fix", False)):
        pipeline._write(project / "ratings.json", {"clip01": {"v": vote}})
        assert gate.check(project, "clip01", channel, now=NOW)["publishable"] is allowed


def test_auto_needs_manual_history_and_records_it_at_queue_time(channel):
    channel["approval"].update(policy="auto", manual_first=2)
    registry.save(channel)
    project = episode(channel, n=2)
    waiting = episode(channel, "waiting", rating=None)
    first = queue.build(channel["slug"], NOW)
    assert first["added"] == 2 and "waiting/clip01" in first["blocked"]
    assert all(r["manual"] for r in queue.read(channel["slug"]))
    pipeline._write(project / "ratings.json", {})
    rows = queue.read(channel["slug"])
    rows[0]["status"] = "kit"
    rows[1]["status"] = "posted"
    queue.write(channel["slug"], rows)
    assert gate.check(waiting, "clip01", channel, now=NOW)["publishable"]
    assert queue.build(channel["slug"], NOW)["added"] == 1
    assert not queue.read(channel["slug"])[-1]["manual"]
    queue.mark(channel["slug"], "episode/clip01", "skipped")
    assert not gate.check(waiting, "clip01", channel, now=NOW)["publishable"]


def test_auto_after_warmup_still_blocks_fix(channel):
    channel["approval"].update(policy="auto", manual_first=0)
    project = episode(channel, rating="fix")
    assert not gate.check(project, "clip01", channel)["publishable"]
    pipeline._write(project / "ratings.json", {})
    assert gate.check(project, "clip01", channel)["publishable"]


def test_slots_timezone_daily_cap_and_idempotence(channel):
    channel["cadence"]["per_day"] = 2
    registry.save(channel)
    episode(channel, "a", 3)
    episode(channel, "b", 3)
    assert queue.build(channel["slug"], NOW)["added"] == 6
    rows = queue.read(channel["slug"])
    slots = [datetime.fromisoformat(r["slot"]) for r in rows]
    assert len(set(slots)) == 6 and all(s >= NOW and s.utcoffset() == timedelta(hours=-8) for s in slots)
    assert max(Counter(s.date() for s in slots).values()) == 2
    assert {s.strftime("%H:%M") for s in slots} == {"12:00", "17:00"}
    assert rows[0]["slot"] == "2026-11-05T12:00:00-08:00"
    path = registry.directory(channel["slug"]) / "queue.jsonl"
    before = path.read_bytes()
    assert queue.build(channel["slug"], NOW)["added"] == 0
    assert path.read_bytes() == before
    queue.mark(channel["slug"], rows[0]["id"], "posted")
    episode(channel, "c", 1)
    assert queue.build(channel["slug"], NOW)["added"] == 1
    assert len({r["slot"] for r in queue.read(channel["slug"])}) == 7


@pytest.mark.skipif(not HAS_TZDATA, reason="needs an IANA time zone database (pip install tzdata)")
def test_slots_skip_past_and_nonexistent_times_and_do_not_repeat_fall_hour(channel):
    channel["cadence"].update(times=["01:30", "02:30", "03:30"], per_day=3, timezone="America/Los_Angeles")
    spring = datetime(2026, 3, 8, 9, tzinfo=timezone.utc)
    stream = queue.slots(channel, [], spring)
    assert [next(stream).isoformat() for _ in range(3)] == [
        "2026-03-08T01:30:00-08:00", "2026-03-08T03:30:00-07:00", "2026-03-09T01:30:00-07:00"]
    fall = datetime(2026, 11, 1, 9, tzinfo=timezone.utc)
    assert next(queue.slots(channel, [], fall)).isoformat() == "2026-11-01T02:30:00-08:00"
    channel["cadence"]["timezone"] = "UTC+05:30"
    assert next(queue.slots(channel, [], NOW)).utcoffset() == timedelta(hours=5, minutes=30)
    with pytest.raises(registry.ChannelError, match="now"):
        queue.build(channel["slug"], NOW.replace(tzinfo=None))


def test_daily_limit_still_uses_later_times(channel):
    channel["cadence"]["per_day"] = 1
    registry.save(channel)
    episode(channel, n=2)
    now = datetime(2026, 11, 5, 22, tzinfo=timezone.utc)
    assert queue.build(channel["slug"], now)["added"] == 2
    assert [r["slot"] for r in queue.read(channel["slug"])] == [
        "2026-11-05T17:00:00-08:00", "2026-11-06T12:00:00-08:00"]


def test_own_clips_leave_seeding_slots_between_them(channel):
    episode(channel, n=3, source="mine")
    assert queue.build(channel["slug"], NOW)["added"] == 3
    rows = queue.read(channel["slug"])
    all_slots = queue.slots(channel, [], NOW)
    positions = {next(all_slots).isoformat(): i for i in range(17)}
    assert [positions[r["slot"]] for r in rows] == [0, 8, 16]
    episode(channel, "other", 3)
    assert queue.build(channel["slug"], NOW)["added"] == 3
    assert all(not r["own"] for r in queue.read(channel["slug"])[3:])


def test_own_spacing_checks_reserved_slots_in_both_directions(channel):
    channel["seeding"]["every"] = 3
    registry.save(channel)
    episode(channel, "a", source="mine")
    queue.build(channel["slug"], NOW + timedelta(days=2))
    episode(channel, "b", 2, source="mine")
    assert queue.build(channel["slug"], NOW)["added"] == 2
    rows = sorted(queue.read(channel["slug"]), key=lambda r: r["slot"])
    assert len(rows) == 3
    for row in rows:
        assert queue._seed_ok(datetime.fromisoformat(row["slot"]), [r for r in rows if r != row], channel)


def test_episode_cap_waits_for_another_episode_across_builds(channel):
    episode(channel, "a", 7)
    first = queue.build(channel["slug"], NOW)
    assert first["added"] == 3 and len(first["blocked"]) == 4
    assert queue.build(channel["slug"], NOW + timedelta(days=3))["added"] == 0
    episode(channel, "b", 2)
    assert queue.build(channel["slug"], NOW)["added"] == 6
    projects = [r["project"] for r in queue.read(channel["slug"])]
    assert all(len(set(projects[i:i + 4])) > 1 for i in range(len(projects) - 3))


@pytest.mark.parametrize("all_channels", [False, True])
def test_pause_blocks_gate_queue_and_kit(channel, all_channels):
    project = episode(channel)
    target = ["--all"] if all_channels else [channel["slug"]]
    assert command.run(["pause", *target]) == 0
    assert registry.paused(channel["slug"])
    assert "The channel or network is paused." in gate.check(project, "clip01", channel)["blockers"]
    for operation in (queue.build, kit.kit):
        with pytest.raises(registry.ChannelError, match="paused"):
            operation(channel["slug"])
    assert command.run(["queue", channel["slug"]]) == 2
    assert command.run(["kit", channel["slug"]]) == 2
    assert command.run(["resume", *target]) == 0
    assert not registry.paused(channel["slug"])
    assert command.run(["pause"]) == command.run(["pause", channel["slug"], "--all"]) == 2


def test_local_resume_does_not_clear_network_pause(channel, capsys):
    command.run(["pause", "--all"])
    command.run(["pause", channel["slug"]])
    capsys.readouterr()
    command.run(["resume", channel["slug"]])
    assert registry.paused(channel["slug"])
    assert json.loads(capsys.readouterr().out)["paused"]


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    path = tmp_path_factory.mktemp("channel-video") / "clip.mp4"
    if shutil.which("ffmpeg"):
        subprocess.run([tools.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x112:r=10",
                        "-t", "0.2", "-c:v", "mpeg4", str(path)], check=True, capture_output=True)
    else:
        path.write_bytes(b"placeholder")
    return path


def test_kits_preserve_copy_metadata_and_escape_html(channel, video):
    channel["network"] = {"name": "Replay", "line": "Part of Replay.", "url": "https://example.org/network"}
    channel["handles"] = {"youtube": "@stories"}
    registry.save(channel)
    project = episode(channel, title='<script>alert("bad")</script>')
    shutil.copyfile(video, project / "clip01" / "clip.mp4")
    queue.build(channel["slug"], NOW)
    result = kit.kit(channel["slug"])
    assert result["made"] == 1 and not result["blocked"]
    folder = Path(result["kits"][0])
    assert folder.name == "2026-11-05-1200-episode-clip01"
    assert {p.name for p in folder.iterdir()} == {"video.mp4", "post.json", *[f"{f}.txt" for f in kit.TEXTS]}
    youtube = (folder / "youtube.txt").read_text(encoding="utf-8")
    assert youtube.startswith('<script>alert("bad")</script>\n\nCaption <&>\n')
    assert youtube.endswith("Source: Club episode https://example.org/episode\nPart of Replay.\nhttps://example.org/network\nMore from Stories: https://www.youtube.com/@stories\n")
    post = pipeline._read(folder / "post.json")
    original = pipeline._read(project / "clip01" / "post.json")
    assert all(post[k] == v for k, v in original.items())
    assert post["channel"] == channel["slug"] and post["rights"] == "permission" and post["source"] == "club"
    assert post["gate"] == {"publishable": True, "blockers": []}
    page = Path(result["index"]).read_text(encoding="utf-8")
    assert "&lt;script&gt;" in page and '<script>alert("bad")</script>' not in page

    class Tags(HTMLParser):
        tags = []

        def handle_starttag(self, tag, attrs):
            self.tags.append((tag, dict(attrs)))

    tags = Tags()
    tags.feed(page)
    assert sum(tag == "script" for tag, attrs in tags.tags) == 1
    assert sum(tag == "button" and "data-copy" in attrs for tag, attrs in tags.tags) == 6  # title + five texts
    assert any(tag == "input" and attrs.get("type") == "checkbox" for tag, attrs in tags.tags)
    src = next(attrs["src"] for tag, attrs in tags.tags if tag == "video")
    assert not src.startswith(("/", "http", "file:")) and (Path(result["index"]).parent / src).is_file()
    assert queue.read(channel["slug"])[0]["status"] == "kit"
    assert kit.kit(channel["slug"])["made"] == 0


def test_kit_video_is_remuxed_for_faststart(channel, video):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg not installed")
    project = episode(channel)
    shutil.copyfile(video, project / "clip01" / "clip.mp4")
    queue.build(channel["slug"], NOW)
    result = kit.kit(channel["slug"])
    made = (Path(result["kits"][0]) / "video.mp4").read_bytes()
    assert made.index(b"moov") < made.index(b"mdat")
    assert not result["warnings"]


def test_kit_without_ffmpeg_copies_and_reports_it(channel, monkeypatch, tmp_path):
    project = episode(channel)
    post = pipeline._read(project / "clip01" / "post.json")
    post["youtube"] = "YouTube description"
    pipeline._write(project / "clip01" / "post.json", post)

    def missing():
        raise tools.FactoryError("FFmpeg is missing")
    monkeypatch.setattr(tools, "ffmpeg", missing)
    queue.build(channel["slug"], NOW)
    result = kit.kit(channel["slug"], tmp_path / "custom")
    folder = Path(result["kits"][0])
    assert (folder / "video.mp4").read_bytes() == (project / "clip01" / "clip.mp4").read_bytes()
    assert "FFmpeg is missing" in result["warnings"][0]
    assert "\n\nYouTube description\n" in (folder / "youtube.txt").read_text(encoding="utf-8")
    assert result["index"] == str(tmp_path / "custom" / "index.html")
    assert "video.mp4" in Path(kit.kit(channel["slug"])["index"]).read_text(encoding="utf-8")


def test_kit_rechecks_gate_before_writing(channel):
    project = episode(channel)
    queue.build(channel["slug"], NOW)
    pipeline._write(project / "ratings.json", {"clip01": {"v": "no"}})
    result = kit.kit(channel["slug"])
    assert result["made"] == 0 and "episode/clip01" in result["blocked"]
    assert queue.read(channel["slug"])[0]["status"] == "queued"


def test_remux_failure_leaves_no_kit_and_retries(channel, monkeypatch, video):
    project = episode(channel)
    shutil.copyfile(video, project / "clip01" / "clip.mp4")
    queue.build(channel["slug"], NOW)

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "ffmpeg", stderr=b"bad video")
    monkeypatch.setattr(tools, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(tools, "run", fail)
    assert command.run(["kit", channel["slug"]]) == 2
    assert not list((registry.directory(channel["slug"]) / "kits").iterdir())
    assert queue.read(channel["slug"])[0]["status"] == "queued"


def test_posted_skip_and_cli_queue_show(channel, capsys):
    episode(channel, n=2)
    assert command.run(["queue", channel["slug"]]) == 0
    rows = queue.read(channel["slug"])
    assert command.run(["posted", channel["slug"], rows[0]["id"], "--url", "https://example.org/post"]) == 0
    assert command.run(["skip", channel["slug"], rows[1]["id"]]) == 0
    got = queue.read(channel["slug"])
    assert got[0]["status"] == "posted" and got[0]["url"] == "https://example.org/post"
    assert got[1]["status"] == "skipped"
    assert queue.build(channel["slug"], NOW)["added"] == 0
    capsys.readouterr()
    assert command.run(["show", channel["slug"]]) == 0
    assert json.loads(capsys.readouterr().out)["counts"] == {"posted": 1, "skipped": 1}
    assert command.run(["posted", channel["slug"], "missing/clip01"]) == 2
    assert command.run(["posted", channel["slug"], rows[0]["id"], "--url", "javascript:bad"]) == 2
