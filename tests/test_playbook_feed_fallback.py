"""Public metadata fallback with fake transports and no downloads."""
from __future__ import annotations

import json
import subprocess
import urllib.error
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from conftest import FakeHTTPResponse
from myzing.channels import brief, outliers, outcomes, queue, registry, updates
from myzing.factory import judge
from myzing.playbook import feeds, watch
from myzing.playbook.common import append_jsonl

CHANNEL = "UC" + "a" * 22
NOW = datetime(2026, 11, 6, tzinfo=timezone.utc)
URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL}"
FIELDS = {"id", "title", "published", "views", "short", "channel_id", "channel_title", "approximate"}


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    monkeypatch.setenv("ZING_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ZING_CHANNELS_HOME", str(tmp_path / "channels"))

    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(feeds.urllib.request, "urlopen", refuse)
    monkeypatch.setattr(feeds.urllib.request, "build_opener", refuse)
    monkeypatch.setattr(feeds.proc, "run", refuse)
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(feeds.doctor, "resolve_ytdlp_argv", lambda: ["python", "-m", "yt_dlp"])
    monkeypatch.setattr(feeds, "_last_request", None)
    monkeypatch.setattr(feeds.time, "sleep", lambda seconds: None)


def metadata(ident, days=3, views=88000, **values):
    return {"id": ident, "title": "Creator revenue update", "channel": "Fixture channel",
            "timestamp": (NOW - timedelta(days=days)).timestamp(), "view_count": views, **values}


def result(rows=(), code=0):
    return SimpleNamespace(stdout="\n".join(json.dumps(row) for row in rows), returncode=code, stderr="")


class Runner:
    def __init__(self):
        self.calls = []
        self.videos = result([metadata("video000001"), metadata("undated0001", timestamp=None),
                              metadata("video000002", days=5, channel=None, uploader="Uploader")])
        self.shorts = result([metadata("short000001", timestamp=None, views=12000),
                              metadata("short000002", timestamp=None, views=10000)])
        self.exact = result([metadata("short000001", days=1, views=12345),
                             metadata("short000002", days=4, views=10789)])

    def __call__(self, argv, timeout):
        self.calls.append((argv, timeout))
        value = (self.videos if argv[-1].endswith("/videos") else self.shorts) if "--flat-playlist" in argv else self.exact
        if isinstance(value, Exception):
            raise value
        return value


def fail(error):
    def fetch(*args, **kwargs):
        raise error
    return fetch


def transport(monkeypatch, error):
    monkeypatch.setattr(feeds.urllib.request, "build_opener", lambda handler: SimpleNamespace(open=fail(error)))


def jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_rss_404_lists_public_metadata_and_logs(tmp_path, monkeypatch):
    runner = Runner()
    monkeypatch.setattr(feeds.proc, "run", runner)
    transport(monkeypatch, urllib.error.HTTPError(URL, 404, "missing", {}, None))
    rows = feeds.feed(CHANNEL, root=tmp_path)
    assert [row["id"] for row in rows] == ["short000001", "video000001", "short000002", "video000002"]
    assert all(set(row) == FIELDS and row["channel_id"] == CHANNEL for row in rows)
    assert rows[0] == {"id": "short000001", "title": "Creator revenue update", "views": 12345,
                       "published": "2026-11-05T00:00:00+00:00", "short": True, "channel_id": CHANNEL,
                       "channel_title": "Fixture channel", "approximate": False}
    assert rows[1]["views"] == 88000 and rows[1]["approximate"] is True and rows[1]["short"] is False
    assert rows[-1]["channel_title"] == "Uploader"
    assert len(runner.calls) == 3
    for tab, (argv, timeout) in zip(("videos", "shorts"), runner.calls):
        assert argv == ["python", "-m", "yt_dlp", "--ignore-config", "--no-update", "--flat-playlist", "--skip-download",
                        "--playlist-end", "15", "--extractor-args", "youtubetab:approximate_date", "-j",
                        f"https://www.youtube.com/channel/{CHANNEL}/{tab}"]
        assert timeout == 240
    assert runner.calls[2] == (["python", "-m", "yt_dlp", "--ignore-config", "--no-update", "--skip-download",
                                "--no-playlist", "-j", "https://www.youtube.com/shorts/short000001",
                                "https://www.youtube.com/shorts/short000002"], 180)
    log, = jsonl(tmp_path / "feed-fallbacks.jsonl")
    assert set(log) == {"at", "channel_id", "reason", "rows"}
    assert log["channel_id"] == CHANNEL and log["rows"] == 4 and "HTTP 404" in log["reason"]
    assert datetime.fromisoformat(log["at"]).tzinfo is not None
    assert jsonl(tmp_path / "feeds" / "requests.jsonl")[0]["status"] == 404


@pytest.mark.parametrize("error", [urllib.error.HTTPError(URL, code, "failed", {}, None) for code in (500, 503, 599)] +
                         [urllib.error.URLError("private detail"), OSError("private detail")])
def test_outages_use_fallback(tmp_path, monkeypatch, error):
    transport(monkeypatch, error)
    calls = []
    assert feeds.feed(CHANNEL, root=tmp_path, fallback=lambda ident: calls.append(ident) or []) == []
    assert calls == [CHANNEL]
    log, = jsonl(tmp_path / "feed-fallbacks.jsonl")
    assert log["rows"] == 0 and "private detail" not in log["reason"]


@pytest.mark.parametrize("code", [400, 403, 429])
def test_other_http_errors_do_not_fall_back(tmp_path, monkeypatch, code):
    transport(monkeypatch, urllib.error.HTTPError(URL, code, "failed", {}, None))
    with pytest.raises(ValueError, match=f"HTTP {code}"):
        feeds.feed(CHANNEL, root=tmp_path, fallback=lambda ident: pytest.fail("unexpected fallback"))
    assert not (tmp_path / "feed-fallbacks.jsonl").exists()


@pytest.mark.parametrize("body", [b"<feed", b"<html/>"])
def test_bad_feed_body_never_falls_back(tmp_path, monkeypatch, body):
    monkeypatch.setattr(feeds.urllib.request, "build_opener", lambda handler: SimpleNamespace(
        open=lambda req, timeout: FakeHTTPResponse(body)))
    with pytest.raises(ValueError, match="feed"):
        feeds.feed(CHANNEL, root=tmp_path, fallback=lambda ident: pytest.fail("unexpected fallback"))
    assert not (tmp_path / "feed-fallbacks.jsonl").exists()


@pytest.mark.parametrize("error", [urllib.error.HTTPError(URL, 404, "missing", {}, None),
                                  urllib.error.HTTPError(URL, 500, "failed", {}, None), urllib.error.URLError("failed")])
def test_injected_fetch_needs_explicit_fallback(tmp_path, error):
    with pytest.raises(type(error)):
        feeds.feed(CHANNEL, fail(error), root=tmp_path)
    assert not (tmp_path / "feed-fallbacks.jsonl").exists()
    runner = Runner()
    rows = feeds.feed(CHANNEL, fail(error), root=tmp_path,
                      fallback=lambda ident: feeds.listing(ident, runner=runner, now=NOW))
    assert len(rows) == 4


def test_watch_only_requests_videos(tmp_path, monkeypatch):
    runner = Runner()
    monkeypatch.setattr(feeds.proc, "run", runner)
    transport(monkeypatch, urllib.error.HTTPError(URL, 404, "missing", {}, None))
    rows = feeds.feed(CHANNEL, root=tmp_path, watch_only=True)
    assert len(rows) == 2 and all(not row["short"] for row in rows)
    assert len(runner.calls) == 1 and runner.calls[0][0][-1].endswith("/videos")
    rows = feeds.feed(CHANNEL, fail(urllib.error.URLError("failed")), root=tmp_path, watch_only=True,
                      fallback=lambda ident: feeds.listing(ident, runner=Runner(), now=NOW))
    assert len(rows) == 2 and all(not row["short"] for row in rows)


def test_exact_failure_keeps_only_successful_shorts():
    runner = Runner()
    runner.exact = result([metadata("short000001", days=1, views=12345)], code=1)
    rows = feeds.listing(CHANNEL, runner=runner, now=NOW)
    assert [row["id"] for row in rows if row["short"]] == ["short000001"]
    assert rows[0]["views"] == 12345 and rows[0]["approximate"] is False


@pytest.mark.parametrize("exact", [result(code=1), subprocess.TimeoutExpired("yt-dlp", 180), OSError("failed"),
                                   result([metadata("short000001", timestamp=None),
                                           metadata("short000002", view_count=None)])])
def test_failed_exact_metadata_leaves_videos(exact):
    runner = Runner()
    runner.exact = exact
    rows = feeds.listing(CHANNEL, runner=runner, now=NOW)
    assert len(rows) == 2 and all(not row["short"] and row["approximate"] for row in rows)


def test_listing_sorts_and_limits_each_tab():
    runner = Runner()
    runner.videos = result([metadata(f"video{i:06d}", days=20 - i) for i in range(20)])
    runner.shorts = result([metadata(f"short{i:06d}", timestamp=None) for i in range(20)])
    runner.exact = result([metadata(f"short{i:06d}", days=20 - i) for i in range(20)])
    rows = feeds.listing(CHANNEL, runner=runner, now=NOW)
    assert len(rows) == 30 and sum(row["short"] for row in rows) == 15
    assert [row["published"] for row in rows] == sorted((row["published"] for row in rows), reverse=True)
    assert len([arg for arg in runner.calls[-1][0] if arg.startswith("https://")]) == 15
    assert {row["id"] for row in rows if not row["short"]} == {f"video{i:06d}" for i in range(5, 20)}


def test_empty_shorts_need_no_exact_call_and_failed_tab_keeps_other_tab():
    runner = Runner()
    runner.shorts = result()
    assert len(feeds.listing(CHANNEL, runner=runner, now=NOW)) == 2 and len(runner.calls) == 2
    runner.shorts = result(code=1)
    assert len(feeds.listing(CHANNEL, runner=runner, now=NOW)) == 2
    runner.videos = result(code=1)
    with pytest.raises(ValueError, match="channel listing failed"):
        feeds.listing(CHANNEL, runner=runner, now=NOW)


def test_missing_ytdlp_reports_error_and_logs_attempt(tmp_path, monkeypatch):
    monkeypatch.setattr(feeds.doctor, "resolve_ytdlp_argv", lambda: None)
    with pytest.raises(ValueError, match="^yt-dlp is unavailable; run zing doctor$"):
        feeds.listing(CHANNEL, runner=Runner())
    transport(monkeypatch, urllib.error.HTTPError(URL, 404, "missing", {}, None))
    with pytest.raises(ValueError, match="yt-dlp is unavailable"):
        feeds.feed(CHANNEL, root=tmp_path)
    assert jsonl(tmp_path / "feed-fallbacks.jsonl")[0]["rows"] == 0


@pytest.mark.parametrize("approximate", [False, True])
def test_outliers_and_receipts_keep_count_precision(tmp_path, monkeypatch, approximate):
    rows = [{"id": f"video{i:06d}", "title": "A story", "published": (NOW - timedelta(days=3 + i)).isoformat(),
             "views": 88000 if i == 0 else 10000, "short": False, "channel_id": CHANNEL,
             "channel_title": "Fixture", "approximate": approximate if i == 0 else True} for i in range(6)]
    monkeypatch.setattr(feeds, "feed", lambda *args, **kwargs: rows)
    found = outliers.collect({"id": "stories", "watch": [CHANNEL], "min_multiple": 2}, tmp_path, now=NOW)
    assert len(found) == 1 and found[0]["approximate"] is approximate
    assert found[0]["median"] == 10000
    expected = "about 88,000 views" if approximate else "88,000 views"
    assert brief._receipt(found[0]) == f"Fixture: {expected}, 8.8x their typical video"


def test_news_wrapper_allows_default_fallback(tmp_path, monkeypatch):
    runner = Runner()
    monkeypatch.setattr(feeds.proc, "run", runner)
    transport(monkeypatch, urllib.error.HTTPError(URL, 404, "missing", {}, None))
    series = {"id": "news", "kind": "news", "watch": [CHANNEL], "feeds": []}
    rows = updates.collect(series, tmp_path, now=NOW)
    assert len(rows) == 4 and not (tmp_path / "brief" / "news-errors.jsonl").exists()
    assert jsonl(tmp_path / "brief" / "feed-fallbacks.jsonl")[0]["rows"] == 4
    assert updates.collect(series, tmp_path, now=NOW, fetch=fail(urllib.error.URLError("failed"))) == []
    assert len(runner.calls) == 3


@pytest.mark.parametrize("basis,hours", [("24h", 24), ("7d", 168)])
def test_outcomes_keep_matches_without_rewarding_approximate_counts(tmp_path, monkeypatch, basis, hours):
    channel = registry.create("Stories", "Player stories", handles={"youtube": CHANNEL})
    slug, root = channel["slug"], registry.directory(channel["slug"])
    rows = [{"id": "episode/clip01", "project": str(tmp_path / "episode"), "clip": "clip01", "status": "queued",
             "slot": NOW.isoformat(), "title": "A story"}]
    queue.write(slug, rows)
    video = {"id": "video000001", "title": "A story", "published": (NOW - timedelta(hours=hours)).isoformat(),
             "views": 88000, "short": False, "channel_id": CHANNEL, "channel_title": "Fixture", "approximate": True}
    monkeypatch.setattr(feeds, "feed", lambda *args, **kwargs: [video])
    assert outcomes.track(slug, now=NOW)["matched"] == 1
    saved, = queue.read(slug)
    assert saved["status"] == "posted" and saved["video_id"] == video["id"]
    measured, = outcomes.read(slug)
    assert all(measured[f"views_{age}"] is None for age in ("1h", "24h", "7d"))
    assert measured["reward"] is None and measured["reward_basis"] is None
    assert jsonl(root / "snapshots.jsonl") == []
    video.update(views=88123, approximate=False)
    outcomes.track(slug, now=NOW + timedelta(minutes=1))
    assert outcomes.read(slug)[0][f"views_{basis}"] == 88123
    video.update(views=89000, approximate=True)
    outcomes.track(slug, now=NOW + timedelta(minutes=2))
    assert outcomes.read(slug)[0][f"views_{basis}"] == 88123


def test_playbook_snapshots_keep_precision_and_velocity_uses_exact_samples(tmp_path, monkeypatch):
    video = {"id": "video000001", "title": "A story", "published": (NOW - timedelta(days=1)).isoformat(),
             "views": 88000, "short": False, "channel_id": CHANNEL, "channel_title": "Fixture", "approximate": True}
    monkeypatch.setattr(feeds, "feed", lambda *args, **kwargs: [video])
    watch.watch(tmp_path, [CHANNEL], now=NOW)
    assert jsonl(tmp_path / "snapshots.jsonl")[0]["approximate"] is True
    assert watch.velocity(tmp_path)["videos"] == []
    append_jsonl(tmp_path / "snapshots.jsonl", [{**video, "at": (NOW + timedelta(minutes=1)).isoformat(),
                 "channel": CHANNEL, "approximate": False, "views": 88123}])
    measured, = watch.velocity(tmp_path)["videos"]
    assert measured["views"]["24h"] == 88123
