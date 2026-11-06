"""Review fixes for the daily brief, platform news and recorded takes."""
from __future__ import annotations

from datetime import timedelta

import pytest

from myzing.channels import brief, registry, updates
from myzing.factory import judge, scout

from test_channels_brief import (NOW, SCRIPT, Scripts, candidate, channel, folder, local, make,  # noqa: F401
                                 response)
from test_channels_updates import YOUTUBE, metadata, offline  # noqa: F401


def test_a_bad_cached_answer_is_forgotten_and_its_error_clears_after_a_good_one(channel):
    day = folder(channel)
    judge.Judge(day).save("script-1", '{"hook": "Too short", "script": "Too short", "move": "x", "title": "x", "check": []}')
    data = make(channel, judge=judge.Judge(day))
    assert data["items"][0]["script"] is None and data["errors"][0].startswith("script-1 ")
    assert not (day / "answers" / "script-1.json").exists() and (day / "pending" / "script-1.md").is_file()
    data = make(channel, judge=Scripts())
    assert data["items"][0]["script"] == SCRIPT and data["errors"] == []


def test_one_bad_link_drops_that_candidate_not_the_series(channel):
    bad = candidate("bad", url="https://example.org/a b", multiple=9)
    data = make(channel, bad, candidate("good"), judge=Scripts())
    assert [item["id"] for item in data["items"]] == ["good"] and data["errors"] == []


def test_a_brief_stopped_before_its_scripts_is_due_again(channel, monkeypatch):
    calls = []

    def stop():
        calls.append(True)
        return len(calls) > 2                       # stop once the picks are written
    data = make(channel, judge=Scripts(), stop=stop)
    assert data["items"][0]["script"] is None and not (folder(channel) / "brief.html").exists()
    assert brief.due(channel["slug"], NOW)
    make(channel, judge=Scripts())
    assert not brief.due(channel["slug"], NOW)


def test_refilling_an_older_brief_keeps_the_newest_latest_page(channel):
    make(channel, judge=Scripts())
    root = registry.directory(channel["slug"]) / "brief"
    latest = (root / "latest.html").read_text(encoding="utf-8")
    brief.make(channel["slug"], now=NOW - timedelta(days=1), judge=Scripts(),
               collectors={"breakdown": lambda *a, **k: [candidate("older")]})
    assert (root / "latest.html").read_text(encoding="utf-8") == latest


def test_a_whole_take_keeps_its_last_words_without_a_full_stop():
    words = [{"w": "So", "s": 0.0, "e": 0.3}, {"w": "this", "s": 0.4, "e": 0.6}, {"w": "worked.", "s": 0.7, "e": 1.0}] + [
        {"w": "done." if i == 23 else f"word{i}", "s": 1.0 + i, "e": 1.5 + i} for i in range(30)]
    moment = {"hook": "h", "start": 0.0, "end": 30.5}
    assert scout.snap(moment, words)["end"] == 24.55                # a clip snaps back to its last full stop
    whole = scout.snap({**moment, "whole": True}, words)
    assert whole["start"] == 0.35 and whole["end"] == 30.55


def test_uploads_use_the_outlier_id_and_feed_text_is_plain(tmp_path, metadata):
    metadata.data["https://example.org/news.xml"] = (
        '<rss version="2.0"><channel><title>Feed &lt;b&gt;name&lt;/b&gt;</title><item>'
        '<title>Creator revenue &amp;lt;script&amp;gt;</title><link>https://example.org/money</link>'
        '<pubDate>Fri, 06 Nov 2026 11:00:00 GMT</pubDate><description><![CDATA[<style>p{}</style>'
        '<script>views views</script><p>Partner program</p>]]></description></item></channel></rss>')
    rows = updates.collect({"id": "news", "kind": "news", "feeds": ["https://example.org/news.xml"],
                            "watch": ["@Fixture"]}, tmp_path, fetch=metadata.fetch, now=NOW)
    news = next(row for row in rows if row["url"] == "https://example.org/money")
    assert news["source"] == "Feed name" and "<" not in news["title"] and news["summary"] == "Partner program"
    assert {row["id"] for row in rows if row["url"].startswith("https://www.youtube.com/")} == {"yt-short_one", "yt-video_one"}
