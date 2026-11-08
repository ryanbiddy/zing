"""Brief builds, recorded takes and news feeds stay consistent."""
from __future__ import annotations

import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Event

import pytest

from myzing.channels import brief, registry, updates, watch
from myzing.factory import judge, pipeline, source
from myzing.playbook import feeds

from test_channels_brief import (NOW, SCRIPT, Scripts, candidate, channel, folder, local, make,  # noqa: F401
                                 response)
from test_channels_takes import EMPTY, save, take
from test_channels_updates import (UC, URL, YOUTUBE, item as news_item, metadata, offline,  # noqa: F401
                                   rss, series as news_series)

VIDEO = "abCDef12_-3"


@pytest.mark.parametrize("empty", [False, True])
def test_recorded_uses_transcript_segments_without_words(channel, tmp_path, empty):
    data = make(channel, judge=Scripts())
    project = tmp_path / "project"
    tokens = SCRIPT.split()
    pipeline._write(project / "transcript.json", [
        {"text": " ".join(tokens[:20]), "s": 2, "e": 10},
        {"text": " ".join(tokens[20:]), "s": 10, "e": 37}])
    if empty:
        pipeline._write(project / "words.json", [])
    brief.recorded(channel["slug"], project, {"brief": data["date"], "item": 1})
    item = pipeline._read(folder(channel) / "brief.json")["items"][0]
    assert item["status"] == "recorded" and item["project"] == str(project)
    assert item["take"] == {"words": len(tokens), "script_words": len(tokens), "kept": 1, "added": 0,
                            "hook_kept": True, "seconds": 35, "opening": " ".join(tokens[:20])[:200]}
    assert "Kept 100% of the script in 35 seconds." in (folder(channel) / "brief.html").read_text(encoding="utf-8")


def test_quick_model_recording_reaches_the_brief(channel, tmp_path, monkeypatch):
    make(channel, judge=Scripts())
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    media = incoming / "take.mp4"
    media.write_bytes(b"local take")
    stamp = (NOW - timedelta(minutes=3)).timestamp()
    os.utime(media, (stamp, stamp))
    channel["sources"] = [{"id": "takes", "kind": "recordings", "name": "My takes", "url": str(incoming),
                           "rights": {"status": "own", "grant": "Recorded by me"}}]
    registry.save(channel)
    tokens = SCRIPT.split()

    def transcribe(media, model, **kwargs):
        assert model == "tiny"
        return [{"w": word, "s": 2 + i * 35 / len(tokens), "e": 2 + (i + 1) * 35 / len(tokens)}
                for i, word in enumerate(tokens)]
    monkeypatch.setattr(source, "scout_model", lambda: "tiny")
    monkeypatch.setattr(source, "transcribe_episode", transcribe)
    monkeypatch.setattr(watch, "_duration", lambda path: 37)
    assert watch.run(channel["slug"], now=NOW) == {"found": 1, "started": 1, "errors": []}
    item = pipeline._read(folder(channel) / "brief.json")["items"][0]
    project = Path(item["project"])
    assert (project / "transcript.json").is_file() and not (project / "words.json").exists()
    assert item["take"]["words"] == len(tokens) and item["take"]["kept"] == 1 and item["take"]["seconds"] == 35


def test_recorded_prefers_word_timing(channel, tmp_path):
    data = make(channel, judge=Scripts())
    pipeline._write(tmp_path / "words.json", [{"w": SCRIPT, "s": 3, "e": 38}])
    pipeline._write(tmp_path / "transcript.json", [{"text": "Unrelated text", "s": 0, "e": 90}])
    brief.recorded(channel["slug"], tmp_path, {"brief": data["date"], "item": 1})
    stats = pipeline._read(folder(channel) / "brief.json")["items"][0]["take"]
    assert stats["kept"] == 1 and stats["seconds"] == 35


@pytest.mark.parametrize("payload", [None, b"[]", b"null", b"{}", b"{broken", b"\xff"])
def test_recorded_keeps_empty_stats_without_a_readable_transcript(channel, tmp_path, payload):
    data = make(channel, judge=Scripts())
    if payload is not None:
        (tmp_path / "transcript.json").write_bytes(payload)
    brief.recorded(channel["slug"], tmp_path, {"brief": data["date"], "item": 1})
    assert pipeline._read(folder(channel) / "brief.json")["items"][0]["take"] == {
        **EMPTY, "script_words": len(SCRIPT.split())}


def test_voice_ignores_unmeasured_takes(channel):
    measured = [take(i, kept=.4, hook_kept=False) for i in range(3)]
    save(channel, *measured)
    expected = brief.voice(channel["slug"], NOW)
    assert "The owner rewrote 3 of the last 3 hooks when recording." in expected
    assert any("kept about 40%" in line for line in expected)
    save(channel, *measured, *(take(i, words=0, seconds=0, kept=0, hook_kept=False) for i in range(3, 8)))
    assert brief.voice(channel["slug"], NOW) == expected
    save(channel, *(take(i, words=0, seconds=0, kept=0, hook_kept=False) for i in range(3)))
    assert brief.voice(channel["slug"], NOW) == []


@pytest.fixture
def waiting(monkeypatch):
    event = Event()
    acquire = brief._try_lock

    def attempt(stream):
        locked = acquire(stream)
        if not locked:
            event.set()
        return locked
    monkeypatch.setattr(brief, "_try_lock", attempt)
    return event


def test_concurrent_builds_keep_one_set_of_picks_and_answers(channel, waiting):
    entered = Event()
    collected, asked = [], []

    def collect(*args, **kwargs):
        collected.append(True)
        entered.set()
        assert waiting.wait(5)
        return [candidate("first"), candidate("second")]

    class Slow(judge.Judge):
        def ask(self, task, prompt):
            time.sleep(.05)
            asked.append(task)
            title = "first" if '"id": "first"' in prompt else "second"
            return self.cached(task) or self.save(task, response(title=title))

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(brief.make, channel["slug"], now=NOW, judge=Slow(folder(channel)),
                            collectors={"breakdown": collect})
        assert entered.wait(5)
        second = pool.submit(make, channel, candidate("different"), judge=Scripts())
        one, two = first.result(timeout=5), second.result(timeout=5)
    assert one == two == pipeline._read(folder(channel) / "brief.json")
    assert [(item["id"], item["title"]) for item in one["items"]] == [("first", "first"), ("second", "second")]
    assert collected == [True] and asked == ["script-1", "script-2"]
    assert pipeline._read(folder(channel).parent / "seen.json") == {"first": one["date"], "second": one["date"]}
    for item in one["items"]:
        assert judge.Judge(folder(channel)).cached(f"script-{item['n']}") == brief.check(item)
    assert (folder(channel) / "brief.html").read_bytes() == (folder(channel).parent / "latest.html").read_bytes()


def test_answer_waits_for_the_build_before_saving(channel, waiting):
    entered = Event()

    def collect(*args, **kwargs):
        entered.set()
        assert waiting.wait(5)
        return [candidate("picked")]

    with ThreadPoolExecutor(max_workers=2) as pool:
        build = pool.submit(brief.make, channel["slug"], now=NOW, collectors={"breakdown": collect})
        assert entered.wait(5)
        answered = pool.submit(brief.answer, channel["slug"], "script-1", response(), date="2026-11-06")
        assert build.result(timeout=5)["items"][0]["pending"]
        data = answered.result(timeout=5)
    assert data == pipeline._read(folder(channel) / "brief.json")
    assert data["items"][0]["id"] == "picked" and data["items"][0]["script"] == SCRIPT
    assert judge.Judge(folder(channel)).cached("script-1") == response()
    assert not judge.Judge(folder(channel)).pending()


@pytest.mark.parametrize("answer", [False, True])
def test_held_brief_lock_times_out_without_writing(channel, monkeypatch, answer):
    make(channel)
    before = (folder(channel) / "brief.json").read_bytes()
    monkeypatch.setattr(brief, "LOCK_TIMEOUT", .02)
    with brief._lock(channel["slug"]):
        with pytest.raises(registry.ChannelError, match=f"Timed out waiting for another brief command for {channel['slug']}"):
            if answer:
                brief.answer(channel["slug"], "script-1", response(), date="2026-11-06")
            else:
                make(channel, judge=Scripts())
    assert (folder(channel) / "brief.json").read_bytes() == before
    assert judge.Judge(folder(channel)).cached("script-1") is None
    assert make(channel, judge=Scripts())["items"][0]["script"] == SCRIPT


def test_a_brief_lock_does_not_block_another_channel(channel):
    other = registry.create("Second", "More stories", series=channel["series"])
    with brief._lock(channel["slug"]):
        assert make(other, judge=Scripts())["items"][0]["script"] == SCRIPT


def test_bad_item_url_keeps_the_rest_of_its_feed(tmp_path, metadata):
    metadata.data[URL] = rss([news_item("bad", url="https://[broken"), news_item("good")])
    rows = updates.collect(news_series(), tmp_path, fetch=metadata.fetch, now=NOW)
    assert [row["url"] for row in rows] == ["https://example.org/good"]
    assert not (tmp_path / "brief" / "news-errors.jsonl").exists()


@pytest.mark.parametrize("url", [
    f"https://youtube.com/watch?v={VIDEO}", f"https://www.youtube.com/watch?v={VIDEO}&t=20",
    f"https://m.youtube.com/watch?v={VIDEO}", f"https://www.youtube.com/shorts/{VIDEO}",
    f"https://youtu.be/{VIDEO}?t=20", f"https://www.youtu.be/{VIDEO}",
])
def test_rss_and_watched_upload_share_the_video_id(channel, tmp_path, metadata, url):
    metadata.data[URL] = rss([news_item("video", url=url)])
    metadata.data[f"https://www.youtube.com/feeds/videos.xml?channel_id={UC}"] = YOUTUBE.replace("video_one", VIDEO)
    row, = updates.collect(news_series(), tmp_path, fetch=metadata.fetch, now=NOW)
    uploaded = updates.collect(news_series(feeds=[], watch=[UC]), tmp_path, fetch=metadata.fetch, now=NOW)
    same = next(item for item in uploaded if item["url"].endswith("v=" + VIDEO))
    assert row["id"] == same["id"] == "yt-" + VIDEO
    channel["series"] = [news_series()]
    registry.save(channel)
    first = brief.make(channel["slug"], now=NOW, collectors={"news": lambda *a, **k: [row]}, judge=Scripts())
    next_day = brief.make(channel["slug"], now=NOW + timedelta(days=1),
                          collectors={"news": lambda *a, **k: [same]}, judge=Scripts())
    assert first["items"][0]["id"] == "yt-" + VIDEO and next_day["items"] == []


@pytest.mark.parametrize("url", [
    "https://youtube.com/watch?v=short", "https://youtu.be/abcdefghijkl", "https://youtu.be/abcdefghi%2Fj",
    f"https://youtube.com/shorts/{VIDEO}/extra", f"https://example.org/watch?v={VIDEO}",
    f"https://youtube.com.example.org/watch?v={VIDEO}",
])
def test_only_valid_youtube_links_get_video_ids(tmp_path, metadata, url):
    metadata.data[URL] = rss([news_item("video", url=url)])
    row, = updates.collect(news_series(), tmp_path, fetch=metadata.fetch, now=NOW)
    assert row["id"] == "news-" + hashlib.sha256(url.encode()).hexdigest()[:16]


def test_news_uploads_and_shorts_need_no_view_counts(tmp_path, metadata):
    body = YOUTUBE.replace('<media:statistics views="40"/>', "")
    metadata.data[f"https://www.youtube.com/feeds/videos.xml?channel_id={UC}"] = body
    rows = updates.collect(news_series(feeds=[], watch=[UC]), tmp_path, fetch=metadata.fetch, now=NOW)
    assert {row["id"] for row in rows} == {"yt-video_one", "yt-short_one"}
    assert all(row["score"] >= 4 for row in rows)
    assert feeds.feed(UC, lambda url: body, root=tmp_path) == []


@pytest.mark.parametrize("age", [None, -1, 0, 1])
def test_due_checks_the_latest_page(channel, age):
    make(channel, judge=Scripts())
    page = folder(channel) / "brief.html"
    latest = folder(channel).parent / "latest.html"
    if age is None:
        latest.unlink()
    else:
        stamp = page.stat().st_mtime_ns + age * 1_000_000_000
        os.utime(latest, ns=(stamp, stamp))
    assert brief.due(channel["slug"], NOW) is (age is None or age < 0)
    if age is None or age < 0:
        make(channel, judge=Scripts())
        assert not brief.due(channel["slug"], NOW)
        assert latest.read_bytes() == page.read_bytes()


def test_due_does_not_refresh_latest_from_an_older_brief(channel):
    make(channel, judge=Scripts())
    brief.make(channel["slug"], now=NOW - timedelta(days=1), judge=Scripts(),
               collectors={"breakdown": lambda *a, **k: [candidate("older")]})
    latest = folder(channel).parent / "latest.html"
    latest.unlink()
    assert not brief.due(channel["slug"], NOW - timedelta(days=1))
    assert brief.due(channel["slug"], NOW)


def test_failed_latest_publish_is_due_and_releases_the_lock(channel, monkeypatch):
    publish = brief._publish

    def fail(path, text):
        if path.name == "latest.html":
            raise OSError("replace failed")
        publish(path, text)
    monkeypatch.setattr(brief, "_publish", fail)
    with pytest.raises(OSError, match="replace failed"):
        make(channel, judge=Scripts())
    assert (folder(channel) / "brief.html").is_file() and brief.due(channel["slug"], NOW)
    monkeypatch.setattr(brief, "_publish", publish)
    scripts = Scripts()
    make(channel, judge=scripts)
    assert not scripts.calls and not brief.due(channel["slug"], NOW)
