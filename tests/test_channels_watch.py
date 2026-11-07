"""Unattended channels with local fixtures and fake external work."""
from __future__ import annotations

import io
import json
import os
import socket
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from myzing import uoink_bridge
from myzing.channels import command, digest, gate, kit, outcomes, queue, registry, tick, watch
from myzing.factory import judge, network, pipeline, render, source, visuals

UC = "UC" + "a" * 22
RSS = '''<rss><channel>
<item><guid>video/one</guid><title>Video episode</title><link>https://example.org/one</link>
<pubDate>Thu, 05 Nov 2026 08:00:00 GMT</pubDate><enclosure url="https://cdn.example.org/one.mp4" type="video/mp4"/></item>
<item><guid>audio</guid><title>Audio episode</title><enclosure url="https://cdn.example.org/two.mp3" type="audio/mpeg"/></item>
<item><guid>text</guid><enclosure url="https://example.org/text" type="text/plain"/></item>
</channel></rss>'''
FEED = '''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"
xmlns:media="http://search.yahoo.com/mrss/">''' + "".join(
    f'''<entry><yt:videoId>{ident}</yt:videoId><title>{title}</title><published>2026-11-05T08:00:00Z</published>
    <link href="https://www.youtube.com/{path}"/><media:group><media:community><media:statistics views="40"/>
    </media:community></media:group></entry>'''
    for ident, title, path in (("video_one", "First video", "watch?v=video_one"),
                               ("short_one", "Short", "shorts/short_one"), ("other", "Other", "embed/other"))) + "</feed>"


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
    monkeypatch.setattr(source, "transcribe_episode", refuse)
    monkeypatch.setattr(uoink_bridge, "search_references", lambda query: {"ok": True, "results": []})
    monkeypatch.setattr(uoink_bridge, "resolve_kept_media", refuse)


@pytest.fixture
def channel():
    return registry.create("Stories", "Player stories", cadence={"timezone": "UTC-08:00"})


def add(channel, kind, url, rights="permission", ident="source", expires=""):
    src = {"id": ident, "name": "Show", "kind": kind, "url": str(url),
           "rights": {"status": rights, "grant": "Recorded grant" if rights != "unknown" else "", "expires": expires}}
    channel["sources"].append(src)
    registry.save(channel)
    return src


def media(tmp_path, name="episode.mp4"):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"local media")
    return path


def rows(channel, ident="source"):
    return watch.read(registry.directory(channel["slug"]) / "sources" / f"{ident}.jsonl")


def episode(channel, tmp_path, name="episode"):
    path = registry.directory(channel["slug"]) / "projects" / name
    pipeline.init(path, media(tmp_path, name + ".mp4"), rights="permission", channel=channel["slug"])
    return path


def clip(project, now=None):
    now = now or datetime.now(timezone.utc)
    d = project / "clip01"
    pipeline._write(d / "post.json", {"youtube_title": "A story", "x": "Caption"})
    pipeline._write(d / "context.json", {"flags": []})
    pipeline._write(d / "brief_check.json", {"errors": [], "flags": []})
    video = d / f"clip{render.suffix('9x16', pipeline._read(project / 'factory.json')['pack'])}.mp4"
    video.write_bytes(b"video")
    for p in (d / "post.json", video):
        stamp = (now - timedelta(seconds=2)).timestamp()
        os.utime(p, (stamp, stamp))
    pipeline._write(project / "ratings.json", {"clip01": {"v": "post", "at": now.isoformat()}})
    return d


@pytest.mark.parametrize("kind", ["folder", "own"])
def test_local_sources_dedupe_and_inherit_settings(channel, tmp_path, kind):
    folder = tmp_path / "incoming"
    path = media(folder, "A story.MP4")
    media(folder, "ignore.mp3")
    path.with_suffix(".vtt").write_text("WEBVTT\n\n00:00.000 --> 00:04.000\nA story.\n", encoding="utf-8")
    channel["factory"] = {"mode": "fun", "pack": "swiss", "shapes": ["9x16"], "moments": 3,
                          "focus": "Stories", "vocab": ["Ryan"], "brief": {"tags": ["#ad"]}}
    channel["network"] = {"name": "Replay", "url": "https://example.org", "line": "Part of Replay."}
    add(channel, kind, folder, rights="own" if kind == "own" else "permission")
    got = watch.run(channel["slug"])
    assert got == {"found": 1, "started": 1, "errors": []}
    row, = rows(channel)
    assert row["state"] == "ready" and row["media"] == str(path.resolve())
    assert row["own"] is (kind == "own")
    project = Path(row["project"])
    assert project.parent == registry.directory(channel["slug"]) / "projects"
    cfg = pipeline._read(project / "factory.json")
    assert {k: cfg[k] for k in channel["factory"] if k != "brief"} == {k: v for k, v in channel["factory"].items() if k != "brief"}
    assert cfg["show"] == cfg["channel"] == channel["slug"] and cfg["source"] == "source"
    assert cfg["brand"] == {"name": "Replay", "url": "https://example.org", "cta": "Part of Replay."}
    assert pipeline._read(project / "brief.json") == {"tags": ["#ad"]}
    assert (project / "transcript.json").is_file()
    src = pipeline._read(project / "source.json")
    assert (src["name"], src["url"], src["date"]) == (row["title"], row["url"], row["published"][:10])
    before = rows(channel)
    assert watch.run(channel["slug"]) == {"found": 0, "started": 0, "errors": []}
    assert rows(channel) == before
    clip(project)
    assert queue.build(channel["slug"])["added"] == 1
    assert queue.read(channel["slug"])[0]["own"] is (kind == "own")


@pytest.mark.parametrize("rights,expires", [("unknown", ""), ("permission", "2001-01-01")])
def test_unknown_or_expired_rights_record_then_start_after_grant(channel, tmp_path, rights, expires):
    path = media(tmp_path / "incoming")
    src = add(channel, "folder", path.parent, rights, expires=expires)
    assert watch.run(channel["slug"])["started"] == 0
    row, = rows(channel)
    assert row["state"] == "found, needs rights" and "project" not in row
    assert not list((registry.directory(channel["slug"]) / "projects").iterdir())
    src["rights"].update(status="permission", grant="New grant", expires="")
    registry.save(channel)
    assert watch.run(channel["slug"]) == {"found": 0, "started": 1, "errors": []}
    assert len(rows(channel)) == 1


@pytest.mark.parametrize("value", ["@stories", UC, "https://www.youtube.com/@stories/videos", "https://youtube.com/channel/" + UC,
                                   "https://youtube.com/channel/" + UC + "/videos"])
def test_youtube_only_watch_items_and_local_inbox(channel, value):
    add(channel, "youtube", value)
    calls = []

    def fetch(url):
        calls.append(url)
        return FEED if "/feeds/" in url else f'<link rel="canonical" href="https://www.youtube.com/channel/{UC}">'
    assert watch.run(channel["slug"], fetch=fetch) == {"found": 1, "started": 0, "errors": []}
    row, = rows(channel)
    assert row["id"] == "video_one" and row["state"] == "found"
    path = media(registry.directory(channel["slug"]) / "inbox", "video_one.webm")
    assert watch.run(channel["slug"], fetch=lambda url: FEED)["started"] == 1
    assert rows(channel)[0]["media"] == str(path)
    assert len(rows(channel)) == 1 and sum("/feeds/" in u for u in calls) == 1


def test_old_youtube_discovery_becomes_ready_after_it_leaves_feed(channel):
    add(channel, "youtube", UC)
    watch.run(channel["slug"], fetch=lambda url: FEED)
    media(registry.directory(channel["slug"]) / "inbox", "video_one.mov")
    empty = '<feed xmlns="http://www.w3.org/2005/Atom"/>'
    assert watch.run(channel["slug"], fetch=lambda url: empty)["started"] == 1


def test_youtube_discovery_does_not_need_view_counts(channel):
    add(channel, "youtube", UC)
    feed = FEED.replace('<media:statistics views="40"/>', "")
    assert watch.run(channel["slug"], fetch=lambda url: feed)["found"] == 1


@pytest.mark.parametrize("kind", ["youtube", "uoink"])
def test_uoink_uses_only_matching_existing_kept_media(channel, tmp_path, kind):
    path = media(tmp_path)
    add(channel, kind, UC if kind == "youtube" else "player stories")
    calls = []

    def search(query):
        calls.append(query)
        return {"ok": True, "results": [{"item_ref": "uoink://item/" + ident, "title": ident}
                                         for ident in ("not-kept", "missing", "wrong", "matching")]}

    def resolve(ref):
        ident = ref.rsplit("/", 1)[-1]
        return {"ok": True, "data": {"state": "not_kept" if ident == "not-kept" else "available",
                "source_url": "https://youtu.be/" + ("video_one" if ident == "matching" else "wrong"),
                "media": {"path": str(path if ident != "missing" else tmp_path / "missing.mp4")}}}
    got = watch.run(channel["slug"], fetch=lambda url: FEED, search=search, resolve=resolve)
    assert got["started"] == (1 if kind == "youtube" else 2)
    assert all(r["media"] == str(path) for r in rows(channel))
    assert "https://www.youtube.com/watch?v=video_one" in calls if kind == "youtube" else calls == ["player stories"]
    assert watch.run(channel["slug"], fetch=lambda url: FEED, search=search, resolve=resolve)["started"] == 0


@pytest.mark.parametrize("rights", ["permission", "unknown"])
def test_podcast_enclosures_rights_audio_and_dedupe(channel, rights):
    add(channel, "podcast", "https://example.org/feed", rights)
    downloaded = []

    def download(url, path, **options):
        downloaded.append(url)
        assert options["cap"] == 4 * 1024 ** 3
        assert path.parent == registry.directory(channel["slug"]) / "inbox"
        path.write_bytes(b"enclosure")
        return path
    result = watch.run(channel["slug"], fetch=lambda url: RSS, downloader=download)
    assert result["found"] == 2 and result["started"] == (rights != "unknown") and not result["errors"]
    audio = next(row for row in rows(channel) if row["id"] == "audio")
    assert audio["note"] == "audio only, needs a video" and "project" not in audio
    assert audio["state"] == ("found" if rights != "unknown" else "found, needs rights")
    assert len(downloaded) == (2 if rights != "unknown" else 0)
    assert watch.run(channel["slug"], fetch=lambda url: RSS, downloader=download)["found"] == 0
    assert len(downloaded) == (2 if rights != "unknown" else 0)
    assert len(rows(channel)) == 2


def test_podcast_download_failure_keeps_discovery_and_retries(channel):
    add(channel, "podcast", "https://example.org/feed")

    def fail(*args, **kwargs):
        raise OSError("enclosure unavailable")
    result = watch.run(channel["slug"], fetch=lambda url: RSS, downloader=fail)
    assert len(result["errors"]) == 2 and result["started"] == 0
    assert all(r["error"] == "enclosure unavailable" for r in rows(channel))
    assert watch.run(channel["slug"], fetch=lambda url: RSS, downloader=fail)["found"] == 0


def test_expired_podcast_never_downloads(channel):
    add(channel, "podcast", "https://example.org/feed", expires="2000-01-01")
    result = watch.run(channel["slug"], fetch=lambda url: RSS,
                       downloader=lambda *a, **k: pytest.fail("expired source downloaded"))
    assert result == {"found": 2, "started": 0, "errors": []}
    assert all(row["state"] == "found, needs rights" for row in rows(channel))


def test_watch_recovers_project_created_before_item_was_saved(channel, tmp_path):
    path = media(tmp_path / "incoming")
    add(channel, "folder", path.parent)
    assert watch.run(channel["slug"])["started"] == 1
    row, = rows(channel)
    row.pop("project")
    row.pop("started_at")
    log = registry.directory(channel["slug"]) / "sources" / "source.jsonl"
    watch._write(log, [row])
    assert watch.run(channel["slug"]) == {"found": 0, "started": 0, "errors": []}
    assert Path(rows(channel)[0]["project"]).is_dir()
    assert len(list((registry.directory(channel["slug"]) / "projects").iterdir())) == 1


def test_watch_paused_and_stop_during_discovery_do_not_start(channel, tmp_path):
    path = media(tmp_path / "incoming")
    add(channel, "folder", path.parent)
    pause = registry.home() / "PAUSE"
    pause.touch()
    with pytest.raises(registry.ChannelError, match="paused"):
        watch.run(channel["slug"])
    pause.unlink()
    assert watch.run(channel["slug"], stop=lambda: True) == {"found": 0, "started": 0, "errors": []}
    assert not rows(channel)


def test_download_streams_atomically_and_can_stop(channel, monkeypatch):
    root = registry.directory(channel["slug"])
    path = root / "episode.mp4"

    class Response(io.BytesIO):
        headers = {"Content-Length": "5"}
    monkeypatch.setattr(network.Network, "open", lambda *a, **k: Response(b"video"))
    assert watch.download("https://example.org/file", path, root=root, stop=lambda: True) is None
    assert not path.exists() and not path.with_suffix(".mp4.part").exists()
    assert watch.download("https://example.org/file", path, root=root, cap=5) == path
    assert path.read_bytes() == b"video" and not path.with_suffix(".mp4.part").exists()


def test_podcast_cannot_redirect_to_private_host(channel, monkeypatch):
    root = registry.directory(channel["slug"])
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *a, **k: [
        (2, 1, 6, "", ("127.0.0.1" if host == "private.test" else "8.8.8.8", 443))])

    def opener(handler, *handlers):
        class Opener:
            def open(self, request, **kwargs):
                return handler.redirect_request(request, io.BytesIO(), 302, "Found", {}, "https://private.test/file")
        return Opener()
    monkeypatch.setattr(urllib.request, "build_opener", opener)
    with pytest.raises(ValueError, match="private address"):
        watch.download("https://example.org/file", root / "episode.mp4", root=root)
    assert not (root / "episode.mp4").exists()


@pytest.mark.parametrize("length,body", [("20", b"x"), ("", b"123456"), ("6", b"123")])
def test_download_cap_and_truncation_leave_no_media(channel, monkeypatch, length, body):
    root = registry.directory(channel["slug"])
    path = root / "episode.mp4"

    class Response(io.BytesIO):
        headers = {"Content-Length": length}

    def open(self, url, purpose, **kwargs):
        assert kwargs["validate"] is visuals._public_url
        return Response(body)
    monkeypatch.setattr(network.Network, "open", open)
    with pytest.raises(registry.ChannelError, match="exceeds|incomplete"):
        watch.download("https://example.org/file", path, root=root, cap=5)
    assert not path.exists() and not path.with_suffix(".mp4.part").exists()


def test_download_checks_private_hosts_and_records_requests(channel, monkeypatch):
    root = registry.directory(channel["slug"])
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 80))])
    with pytest.raises(ValueError, match="private address"):
        watch.download("http://example.org/file", root / "episode.mp4", root=root)
    ledger, = watch.read(root / "network.jsonl")
    assert ledger["host"] == "example.org" and ledger["purpose"] == "podcast enclosure"
    with pytest.raises(ValueError, match="non-http"):
        watch.download("file://example.org/file", root / "episode.mp4", root=root)


def test_tick_order_one_episode_and_summary(channel, tmp_path, monkeypatch):
    channel["judge"] = "claude"
    channel["handles"]["youtube"] = "@stories"
    registry.save(channel)
    first = episode(channel, tmp_path, "a")
    episode(channel, tmp_path, "b")
    order = []

    def watcher(slug, **kwargs):
        order.append("watch")
        return {"found": 2, "started": 1, "errors": []}

    def runner(project, judge, **kwargs):
        order.append("run")
        assert project == first and judge.backend == "claude"
        return {"pending": [{"task": "clip01-plan", "prompt_path": "prompt.md"}]}
    monkeypatch.setattr(queue, "build", lambda *a, **k: order.append("queue") or {"added": 3, "blocked": {"b/clip01": ["Needs review."]}})
    monkeypatch.setattr(kit, "kit", lambda *a, **k: order.append("kit") or {"made": 2, "blocked": {}})
    monkeypatch.setattr(outcomes, "track", lambda slug: order.append("track") or {"matched": 0})
    result = tick.run([channel["slug"]], watch_fn=watcher, runner=runner)
    assert order == ["watch", "run", "queue", "kit", "track"]
    row = result["channels"][channel["slug"]]
    assert (row["found"], row["started"], row["advanced"], row["queued"], row["kits"]) == (2, 1, 1, 3, 2)
    assert row["pending"][0]["task"] == "clip01-plan" and row["blocked"] == {"b/clip01": ["Needs review."]}
    assert row["seconds"] >= 0 and result["exit_code"] == 0
    assert watch.read(registry.directory(channel["slug"]) / "ticks.jsonl") == [row]


@pytest.mark.parametrize("when", ["before", "after watch", "after run"])
def test_tick_stops_on_pause(channel, tmp_path, monkeypatch, when):
    episode(channel, tmp_path)
    pause = registry.directory(channel["slug"]) / "PAUSE"
    called = []
    if when == "before":
        pause.touch()

    def watcher(slug, **kwargs):
        called.append("watch")
        if when == "after watch":
            pause.touch()
        return {"found": 0, "started": 0}

    def runner(*args, **kwargs):
        called.append("run")
        pause.touch()
        return {}
    monkeypatch.setattr(queue, "build", lambda *a, **k: pytest.fail("queue ran after pause"))
    result = tick.run([channel["slug"]], watch_fn=watcher, runner=runner)
    assert called == {"before": [], "after watch": ["watch"], "after run": ["watch", "run"]}[when]
    assert result["channels"][channel["slug"]]["stopped"] == "paused"
    assert result["exit_code"] == 0


def test_tick_time_budget_stops_later_steps_and_channels(channel, monkeypatch):
    clock = [0.0]
    registry.create("Second", "Other stories")
    monkeypatch.setattr(tick.time, "monotonic", lambda: clock[0])

    def watcher(slug, **kwargs):
        clock[0] = 61
        return {"found": 1, "started": 0}
    monkeypatch.setattr(queue, "build", lambda *a, **k: pytest.fail("queue ran after budget"))
    result = tick.run([channel["slug"], "second"], max_minutes=1, watch_fn=watcher)
    assert list(result["channels"]) == [channel["slug"]]
    assert result["channels"][channel["slug"]]["stopped"] == "out of time"


def test_lock_rejects_overlap_and_recovers_stale_file(channel):
    now = datetime.now(timezone.utc)
    path = registry.home() / "tick.lock"
    with tick.lock(now) as acquired:
        assert acquired and pipeline._read(path)["pid"] == os.getpid()
        assert tick.run([channel["slug"]])["message"] == "another tick is running"
    assert not path.exists()
    pipeline._write(path, {"pid": 999999, "started": now.isoformat()})
    assert tick.run([channel["slug"]], now=now)["exit_code"] == 0
    assert path.exists()
    pipeline._write(path, {"pid": 999999, "started": (now - timedelta(hours=3)).isoformat()})
    assert channel["slug"] in tick.run([channel["slug"]], now=now)["channels"]
    assert not path.exists()
    with pytest.raises(RuntimeError), tick.lock(now):
        raise RuntimeError("crash")
    assert not path.exists()


def test_one_channel_error_continues_and_all_errors_exit_one(channel):
    registry.create("Second", "Other stories")
    called = []

    def watcher(slug, **kwargs):
        called.append(slug)
        if slug == channel["slug"]:
            raise ValueError("bad feed")
        return {"found": 1, "started": 0}
    result = tick.run([channel["slug"], "second"], watch_fn=watcher)
    assert called == [channel["slug"], "second"] and result["exit_code"] == 0
    assert result["channels"][channel["slug"]]["errors"] == ["bad feed"]
    assert result["channels"]["second"]["found"] == 1
    assert tick.run([channel["slug"]], watch_fn=watcher)["exit_code"] == 1


def test_tick_does_not_advance_projects_after_source_rights_expire(channel, tmp_path):
    path = media(tmp_path / "incoming")
    src = add(channel, "folder", path.parent)
    watch.run(channel["slug"])
    src["rights"]["expires"] = "2000-01-01"
    registry.save(channel)
    result = tick.run([channel["slug"]], runner=lambda *a, **k: pytest.fail("expired project ran"))
    row = result["channels"][channel["slug"]]
    assert row["advanced"] == 0 and list(row["blocked"].values()) == [["Source rights need review."]]


def test_tick_log_failure_does_not_stop_next_channel(channel, monkeypatch):
    registry.create("Second", "Other stories")
    append = tick.append_jsonl

    def write(path, rows):
        if path.parent.name == channel["slug"]:
            raise OSError("read-only log")
        return append(path, rows)
    monkeypatch.setattr(tick, "append_jsonl", write)
    result = tick.run([channel["slug"], "second"])
    assert "Could not write ticks.jsonl" in result["channels"][channel["slug"]]["errors"][0]
    assert not result["channels"]["second"]["errors"] and result["exit_code"] == 0


def test_host_tick_reports_prompts_then_resumes_after_answer(channel, tmp_path):
    path = media(tmp_path / "incoming")
    path.with_suffix(".vtt").write_text("WEBVTT\n\n00:00.000 --> 00:10.000\nA story.\n", encoding="utf-8")
    add(channel, "folder", path.parent)
    row = tick.run([channel["slug"]])["channels"][channel["slug"]]
    assert row["advanced"] == 1 and row["pending"][0]["task"] == "scout"
    assert not row["errors"]
    project = Path(rows(channel)[0]["project"])
    row = tick.run([channel["slug"]])["channels"][channel["slug"]]
    assert row["advanced"] == 0 and row["pending"][0]["task"] == "scout"
    judge.Judge(project).save("scout", {"moments": []})
    called = []
    row = tick.run([channel["slug"]], runner=lambda *a, **k: called.append(a[0]) or {})["channels"][channel["slug"]]
    assert called == [project] and row["advanced"] == 1 and not row["pending"]


def test_pipeline_stops_between_steps(channel, tmp_path, monkeypatch):
    project = episode(channel, tmp_path)
    stopped = [False]

    def transcribe(*args, **kwargs):
        stopped[0] = True
        return [{"w": "Story", "s": 0, "e": 2}]
    monkeypatch.setattr(source, "transcribe_episode", transcribe)
    result = pipeline.run(project, judge.Judge(project), stop=lambda: stopped[0], say=lambda m: None)
    assert result["state"] == "stopped" and not result["pending"]
    assert (project / "transcript.json").is_file()


def test_pipeline_keeps_clip_errors_when_stopped(channel, tmp_path, monkeypatch):
    project = episode(channel, tmp_path)
    pipeline._write(project / "moments.json", {"scouted": True, "moments": [
        {"hook": "Story", "start": 0, "end": 10, "snapped": True},
        {"hook": "Another story", "start": 10, "end": 20, "snapped": True}]})
    stopped = [False]

    def fail(*args, **kwargs):
        stopped[0] = True
        raise pipeline.FactoryError("cut failed")
    monkeypatch.setattr(pipeline, "_clip", fail)
    result = pipeline.run(project, judge.Judge(project), stop=lambda: stopped[0], say=lambda m: None)
    assert result["state"] == "stopped" and result["failed"] == {"clip01": "cut failed"}


@pytest.mark.parametrize("file", ["clip.mp4", "post.json"])
@pytest.mark.parametrize("policy", ["manual", "veto", "auto"])
def test_edited_after_approval_needs_new_post(channel, tmp_path, file, policy):
    channel["approval"].update(policy=policy, manual_first=0, veto_hours=0)
    project = episode(channel, tmp_path)
    now = datetime.now(timezone.utc)
    d = clip(project, now)
    assert gate.check(project, "clip01", channel)["publishable"]
    stamp = (now + timedelta(seconds=1)).timestamp()
    os.utime(d / file, (stamp, stamp))
    got = gate.check(project, "clip01", channel)
    assert not got["publishable"] and "The clip was edited after approval." in got["blockers"]
    pipeline._write(project / "ratings.json", {"clip01": {"v": "post", "at": (now + timedelta(seconds=2)).isoformat()}})
    assert gate.check(project, "clip01", channel)["publishable"]


@pytest.mark.parametrize("setting", ["cleared", "editorial"])
@pytest.mark.parametrize("rights", ["cleared", "attribution", "editorial", "unknown", None])
def test_visual_policy_accepts_only_declared_rights(channel, tmp_path, setting, rights):
    channel["visuals"] = setting
    registry.save(channel)
    project = episode(channel, tmp_path)
    d = clip(project)
    pipeline._write(d / "visuals" / "manifest.json", {"a": [{"rights": rights} if rights else {}]})
    pipeline._write(d / "visuals" / "picks.json", {"picks": {"a": {"pick": 0}}})
    assert gate.check(project, "clip01", channel)["publishable"] is (rights in ("cleared", "attribution") or setting == rights == "editorial")


def test_registry_validates_judge_and_visuals_and_show_includes_them(channel, capsys):
    assert channel["visuals"] == "cleared" and channel["judge"] == "host"
    assert command.run(["show", channel["slug"]]) == 0
    assert json.loads(capsys.readouterr().out)["settings"]["visuals"] == "cleared"
    for key in ("visuals", "judge"):
        for bad in (None, "other", [], {}):
            with pytest.raises(registry.ChannelError, match=key):
                registry.validate({**channel, key: bad})


def test_digest_last_day_and_waiting_work(channel, tmp_path):
    now = datetime.now(timezone.utc) + timedelta(minutes=2)
    old = (now - timedelta(days=2)).isoformat()
    path = media(tmp_path / "incoming")
    add(channel, "folder", path.parent)
    watch.run(channel["slug"])
    project = Path(rows(channel)[0]["project"])
    d = clip(project)
    queue.build(channel["slug"])
    queued = queue.read(channel["slug"])
    queued[0].update(status="kit", kit=str(registry.directory(channel["slug"]) / "kits" / "ready"))
    queue.write(channel["slug"], queued)
    pipeline._write(d / "context.json", {"flags": [{"why": "missing context"}]})
    pending = project / "pending" / "clip01-plan.md"
    pending.parent.mkdir()
    pending.write_text("Plan this clip", encoding="utf-8")
    add(channel, "youtube", UC, "unknown", ident="needs-rights")
    log = registry.directory(channel["slug"]) / "ticks.jsonl"
    watch._write(log, [{"at": old, "errors": ["old failure"]}, {"at": now.isoformat(), "errors": ["feed unavailable"]}])
    previous = episode(channel, tmp_path, "old-project")
    cfg = pipeline._read(previous / "factory.json")
    pipeline._write(previous / "factory.json", {**cfg, "created": old})
    text = digest.build(now=now)
    assert "1 item found. 1 project started. 1 clip made." in text
    assert queued[0]["slot"] in text and "1 kit waiting to be posted" in text
    assert "Context flags need review" in text and "needs-rights" in text
    assert "clip01-plan" in text and "feed unavailable" in text and "old failure" not in text


def test_cli_watch_tick_digest_and_flags(channel, tmp_path, capsys):
    assert command.run(["watch", channel["slug"]]) == 0
    assert command.run(["tick", "--all", "--max-minutes", "1"]) == 0
    path = tmp_path / "digest.md"
    assert command.run(["digest", "--all", "--out", str(path)]) == 0
    assert "# Channel digest" in path.read_text(encoding="utf-8")
    assert command.run(["digest", channel["slug"]]) == 0
    assert "# Channel digest" in capsys.readouterr().out
    for args in (["tick"], ["tick", channel["slug"], "--all"], ["tick", "--all", "--max-minutes", "nan"],
                 ["tick", "--all", "--max-minutes", "0"], ["digest", channel["slug"], "--all"]):
        assert command.run(args) == 2
