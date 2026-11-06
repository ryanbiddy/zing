"""Platform news from local feed fixtures, with no external work."""
from __future__ import annotations

import hashlib
import io
import json
import socket
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from html import escape
from types import SimpleNamespace

import pytest

from myzing.channels import updates
from myzing.factory import judge, visuals
from myzing.playbook import feeds

NOW = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)
URL = "https://example.org/news.xml"
UC = "UC" + "a" * 22
PAGE = f'<html><head><link rel="canonical" href="https://www.youtube.com/channel/{UC}"/></head></html>'
RSS = '''<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<title>Platform news</title>
<item><title>Creator revenue update</title><link>https://example.org/money</link>
<pubDate>Thu, 05 Nov 2026 08:00:00 -0800</pubDate>
<description><![CDATA[<p>Shorts &amp; Reels</p><p>  New &#x74;ools. </p>]]></description></item>
<item><title>Creator policy changes</title><link>https://example.org/policy</link>
<pubDate>Fri, 06 Nov 2026 11:00:00 GMT</pubDate>
<content:encoded><![CDATA[<p>Longer <b>Shorts</b>.</p>]]></content:encoded></item>
</channel></rss>'''
ATOM = '''<feed xmlns="http://www.w3.org/2005/Atom"><title>Platform Atom</title>
<entry><title>Studio reach update</title><link rel="self" href="https://example.org/api"/>
<link rel="alternate" href="https://example.org/reach"/>
<published>2026-11-06T10:00:00Z</published><updated>2026-11-08T10:00:00Z</updated>
<summary type="html">New &lt;b&gt;tools&lt;/b&gt; &amp;amp; notes.</summary></entry>
<entry><title>Creator upload policy</title><link href="https://example.org/upload"/>
<link href="https://example.org/other"/><updated>2026-11-06T12:00:00+02:00</updated>
<content type="xhtml"><div xmlns="http://www.w3.org/1999/xhtml"><p>One</p><p>Two &amp; three.</p></div></content></entry>
</feed>'''
YOUTUBE = '''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"
xmlns:media="http://search.yahoo.com/mrss/"><title>Feed channel</title>''' + "".join(
    f'''<entry><yt:videoId>{ident}</yt:videoId><title>Creator revenue {title}</title>
    <published>2026-11-06T09:00:00Z</published><link href="https://www.youtube.com/{path}"/>
    {author}<media:group><media:thumbnail url="https://example.org/never-fetch.jpg"/>
    <media:community><media:statistics views="40"/></media:community></media:group></entry>'''
    for ident, title, path, author in (
        ("video_one", "update", "watch?v=video_one", "<author><name>Upload channel</name></author>"),
        ("short_one", "Shorts", "shorts/short_one", ""))) + "</feed>"


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(urllib.request, "build_opener", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(feeds, "_last_request", None)


@pytest.fixture
def metadata():
    data = {URL: RSS, "https://www.youtube.com/@Fixture": PAGE,
            f"https://www.youtube.com/feeds/videos.xml?channel_id={UC}": YOUTUBE}
    calls = []

    def fetch(url):
        calls.append(url)
        value = data[url]
        if isinstance(value, Exception):
            raise value
        return value
    return SimpleNamespace(data=data, calls=calls, fetch=fetch)


def series(**values):
    return {"id": "platform", "name": "Money and algorithm", "kind": "news", "feeds": [URL], "per_day": 1, **values}


def item(ident, *, title="Creator revenue", published=NOW.isoformat(), summary="", url=None):
    date = f"<pubDate>{escape(published)}</pubDate>" if published is not None else ""
    return (f"<item><title>{escape(title)}</title><link>{escape(url or 'https://example.org/' + ident)}</link>"
            f"{date}<description>{escape(summary)}</description></item>")


def rss(items, title="Fixture news"):
    return f"<rss><channel><title>{title}</title>{''.join(items)}</channel></rss>"


def errors(root):
    return [json.loads(line) for line in (root / "brief" / "news-errors.jsonl").read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize("binary", [False, True])
def test_rss_fields_html_and_content(tmp_path, metadata, binary):
    if binary:
        metadata.data[URL] = RSS.encode()
    rows = updates.collect(series(), tmp_path, fetch=metadata.fetch, now=NOW)
    url = "https://example.org/money"
    assert rows[0] == {"id": "news-" + hashlib.sha256(url.encode()).hexdigest()[:16], "series": "platform",
                       "kind": "news", "title": "Creator revenue update", "url": url,
                       "published": "2026-11-05T16:00:00+00:00", "source": "Platform news",
                       "summary": "Shorts & Reels New tools.", "score": 6, "why": ["money", "format"]}
    assert len(rows) == 2
    assert rows[1]["summary"] == "Longer Shorts."
    assert rows[1]["why"] == ["format", "policy"]
    assert rows[1]["score"] == 5
    assert metadata.calls == [URL]


def test_atom_alternate_links_updated_and_xhtml(tmp_path, metadata):
    metadata.data[URL] = ATOM
    rows = updates.collect(series(), tmp_path, fetch=metadata.fetch, now=NOW)
    assert [row["url"] for row in rows] == ["https://example.org/upload", "https://example.org/reach"]
    assert [row["summary"] for row in rows] == ["One Two & three.", "New tools & notes."]
    assert [row["score"] for row in rows] == [5, 4]
    assert all(row["published"] == "2026-11-06T10:00:00+00:00" and row["source"] == "Platform Atom" for row in rows)


def test_summary_limit_and_scoring_uses_summary(tmp_path, metadata):
    metadata.data[URL] = rss([item("long", title="Creator", summary="<p>Revenue &amp; " + "é " * 400 + "</p>")])
    row = updates.collect(series(), tmp_path, fetch=metadata.fetch, now=NOW)[0]
    assert row["summary"] == ("Revenue & " + "é " * 400)[:600]
    assert row["score"] == 4 and row["why"] == ["money"]


@pytest.mark.parametrize("values", [{}, {"feeds": [], "watch": []}, {"feeds": []}, {"watch": []}])
def test_defaults_only_when_both_sources_empty(tmp_path, metadata, values):
    metadata.data.update({url: RSS for url in updates.DEFAULT_FEEDS})
    metadata.data.update({f"https://www.youtube.com/feeds/videos.xml?channel_id={ident}": YOUTUBE
                          for ident in updates.DEFAULT_WATCH})
    rows = updates.collect({"id": "news", "kind": "news", **values}, tmp_path, fetch=metadata.fetch, now=NOW)
    assert len(rows) == 4
    assert metadata.calls == list(updates.DEFAULT_FEEDS) + [
        f"https://www.youtube.com/feeds/videos.xml?channel_id={ident}" for ident in updates.DEFAULT_WATCH]
    assert all(row["series"] == "news" for row in rows)


def test_youtube_uploads_and_shorts_without_default_feeds(tmp_path, metadata):
    rows = updates.collect(series(feeds=[], watch=["@Fixture"]), tmp_path, fetch=metadata.fetch, now=NOW)
    assert [row["url"] for row in rows] == ["https://www.youtube.com/shorts/short_one",
                                          "https://www.youtube.com/watch?v=video_one"]
    assert [row["source"] for row in rows] == ["Feed channel", "Upload channel"]
    assert all(row["summary"] == "" and row["published"] == "2026-11-06T09:00:00+00:00" for row in rows)
    assert metadata.calls == ["https://www.youtube.com/@Fixture",
                              f"https://www.youtube.com/feeds/videos.xml?channel_id={UC}"]
    assert json.loads((tmp_path / "brief" / "feeds" / "ids.json").read_text()) == {"fixture": UC}
    assert {path.relative_to(tmp_path).parts[0] for path in tmp_path.rglob("*")} == {"brief"}


def test_date_window_future_limit_and_missing_dates(tmp_path, metadata):
    dates = {"old": NOW - timedelta(days=10, microseconds=1), "edge": NOW - timedelta(days=10),
             "recent": NOW - timedelta(days=2), "now": NOW, "future": NOW + timedelta(minutes=30),
             "last": NOW + timedelta(hours=1), "later": NOW + timedelta(hours=1, microseconds=1)}
    metadata.data[URL] = rss([item(ident, published=date.isoformat()) for ident, date in dates.items()] + [
        item("missing", published=None), item("empty", published=""), item("invalid", published="yesterday"),
        item("broken", published="Fri, 99 Nov 2026 00:00:00 GMT")])
    rows = updates.collect(series(), tmp_path, fetch=metadata.fetch, now=NOW)
    assert [row["url"].rsplit("/", 1)[-1] for row in rows] == ["last", "future", "now", "recent", "edge"]
    assert not (tmp_path / "brief").exists()


@pytest.mark.parametrize("published", ["", "not a date", "2026-10-20T09:00:00Z", "2026-11-06T14:00:00Z"])
def test_youtube_bad_or_outdated_entry_keeps_other_uploads(tmp_path, metadata, published):
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={UC}"
    metadata.data[url] = YOUTUBE.replace("2026-11-06T09:00:00Z", published, 1).encode()
    rows = updates.collect(series(feeds=[], watch=["@Fixture"]), tmp_path, fetch=metadata.fetch, now=NOW)
    assert [row["url"] for row in rows] == ["https://www.youtube.com/shorts/short_one"]
    assert not (tmp_path / "brief" / "news-errors.jsonl").exists()


def test_duplicate_upload_url_keeps_rss_entry(tmp_path, metadata):
    url = "https://www.youtube.com/watch?v=video_one"
    metadata.data[URL] = rss([item("upload", url=url)])
    rows = updates.collect(series(watch=["@Fixture"]), tmp_path, fetch=metadata.fetch, now=NOW)
    matching = [row for row in rows if row["url"] == url]
    assert len(rows) == 2 and len(matching) == 1
    assert matching[0]["source"] == "Fixture news"


def test_default_now_and_naive_dates_use_utc(tmp_path, metadata, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz):
            assert tz == timezone.utc
            return NOW
    monkeypatch.setattr(updates, "datetime", Clock)
    metadata.data[URL] = rss([item("naive", published="2026-11-06T12:00:00")])
    assert updates.collect(series(), tmp_path, fetch=metadata.fetch)[0]["published"] == NOW.isoformat()


def test_https_only_and_duplicate_urls_keep_first(tmp_path, metadata):
    second = "https://example.org/second.xml"
    metadata.data[URL] = rss([item("first"), item("plain", url="http://example.org/plain"),
                              item("file", url="file:///story"), item("relative", url="/story"),
                              item("hostless", url="https:///story")], title="First source")
    metadata.data[second] = rss([item("first", title="Creator revenue algorithm shorts policy"), item("second")],
                                title="Second source")
    rows = updates.collect(series(feeds=[URL, second]), tmp_path, fetch=metadata.fetch, now=NOW)
    assert [row["url"] for row in rows] == ["https://example.org/first", "https://example.org/second"]
    assert rows[0]["source"] == "First source" and rows[0]["score"] == 4


@pytest.mark.parametrize("text,score,why", [
    ("MONETIZATION partner program revenue sponsor subscription", 3, ["money"]),
    ("algorithm recommendation reach discovery explore distribution", 3, ["reach"]),
    ("shorts reels thumbnail test & compare collab", 2, ["format"]),
    ("policy eligibility guidelines copyright ai label disclosure", 2, ["policy"]),
    ("creator channel analytics studio audience", 1, []),
    ("Creator revenue algorithm shorts policy", 11, ["money", "reach", "format", "policy"]),
    ("demonetization", 5, ["money", "policy"]),
])
def test_scoring_groups_count_once(text, score, why):
    assert updates._score(text) == (score, why)


@pytest.mark.parametrize("word,score,why", [
    ("ypp", 3, ["money"]), ("rpm", 3, ["money"]), ("a/b", 2, ["format"]), ("tips", 3, ["money"]),
    ("paid", 3, ["money"]), ("earn", 3, ["money"]), ("live", 2, ["format"]),
    ("views", 3, ["reach"]), ("title", 2, ["format"]),
])
def test_short_tokens_need_word_boundaries(word, score, why):
    assert updates._score("(" + word.upper() + ")") == (score, why)
    assert updates._score("x" + word) == (0, [])
    assert updates._score(word + "x") == (0, [])


@pytest.mark.parametrize("phrase", ["earnings call", "investor", "quarterly results", "emmy", "award",
                                   "festival", "football", "soccer", "INVESTOR football award"])
def test_off_topic_penalty_applies_once(phrase):
    assert updates._score("Creator revenue algorithm " + phrase) == (4, ["money", "reach"])


def test_threshold_and_sort_by_score_then_date(tmp_path, metadata):
    metadata.data[URL] = rss([
        item("low", title="Revenue"), item("new", title="Creator revenue"),
        item("old", title="Creator revenue", published=(NOW - timedelta(days=1)).isoformat()),
        item("best", title="Creator revenue algorithm", published=(NOW - timedelta(days=9)).isoformat()),
        item("policy", title="Shorts policy", published=(NOW - timedelta(days=2)).isoformat()),
        item("off-topic", title="Creator revenue investor"), item("format", title="Creator Shorts")])
    rows = updates.collect(series(), tmp_path, fetch=metadata.fetch, now=NOW)
    assert [row["url"].rsplit("/", 1)[-1] for row in rows] == ["best", "new", "old", "policy"]
    assert [row["score"] for row in rows] == [7, 4, 4, 4]


@pytest.mark.parametrize("bad", ["<rss", "<html/>", urllib.error.HTTPError(URL, 503, "unavailable", {}, None)])
def test_failed_source_is_logged_and_later_sources_return(tmp_path, metadata, bad):
    broken = "https://example.org/broken.xml"
    metadata.data[broken] = bad
    for _ in range(2):
        rows = updates.collect(series(feeds=[broken, URL]), tmp_path, fetch=metadata.fetch, now=NOW)
        assert len(rows) == 2
    logged = errors(tmp_path)
    assert len(logged) == 2
    assert all(set(row) == {"at", "source", "error"} and row["at"] == NOW.isoformat()
               and row["source"] == broken and row["error"] for row in logged)
    assert {path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*") if path.is_file()} == {
        "brief/news-errors.jsonl"}


def test_failed_youtube_source_does_not_block_next(tmp_path, metadata):
    metadata.data["https://www.youtube.com/@Broken"] = "<html/>"
    rows = updates.collect(series(feeds=[], watch=["@Broken", "@Fixture"]), tmp_path, fetch=metadata.fetch, now=NOW)
    assert len(rows) == 2
    assert errors(tmp_path)[0]["source"] == "@Broken"


@pytest.mark.parametrize("count", [0, 1, 2])
def test_stop_between_sources_returns_collected_rows(tmp_path, metadata, count):
    checks = []

    def stop():
        checks.append(True)
        return len(checks) > count
    rows = updates.collect(series(watch=["@Fixture"]), tmp_path, fetch=metadata.fetch, now=NOW, stop=stop)
    assert len(rows) == count * 2
    assert len(metadata.calls) == (0, 1, 3)[count]
    assert len(checks) == min(count + 1, 2)


@pytest.mark.parametrize("binary", [False, True])
def test_fetch_seam_rejects_oversize_bytes_and_text(tmp_path, metadata, binary):
    metadata.data[URL] = b"x" * (updates.FEED_CAP + 1) if binary else "é" * (updates.FEED_CAP // 2 + 1)
    assert updates.collect(series(), tmp_path, fetch=metadata.fetch, now=NOW) == []
    assert errors(tmp_path)[0]["error"] == "news feed exceeds 4 MB"


def test_real_cap_read_and_request_settings(tmp_path, monkeypatch):
    reads, calls, validated = [], [], []

    class Response(io.BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)
    response = Response(b"x" * (updates.FEED_CAP + 2))

    def open_request(request, timeout):
        calls.append((request.full_url, timeout))
        return response
    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: SimpleNamespace(open=open_request))
    monkeypatch.setattr(visuals, "_public_url", lambda url: validated.append(url))
    assert updates.collect(series(), tmp_path, now=NOW) == []
    assert reads == [updates.FEED_CAP + 1] and response.closed
    assert calls == [(URL, 20)] and validated == [URL]
    assert errors(tmp_path)[0]["error"] == "news feed exceeds 4 MB"
    ledger = json.loads((tmp_path / "brief" / "network.jsonl").read_text())
    assert ledger["purpose"] == "news feed" and ledger["bytes"] == updates.FEED_CAP + 1
    assert updates._bounded(b"x" * updates.FEED_CAP) == b"x" * updates.FEED_CAP


def test_default_transports_write_only_under_brief(tmp_path, metadata, monkeypatch):
    root = tmp_path / "channel"
    marker = tmp_path / "factory.json"
    marker.write_text('{"offline": false}')
    calls = []

    def open_request(request, timeout):
        calls.append(request.full_url)
        assert not request.has_header("Cookie") and not request.has_header("Authorization")
        response = io.BytesIO(metadata.fetch(request.full_url).encode())
        response.status = 200
        return response
    monkeypatch.setattr(urllib.request, "build_opener", lambda *args: SimpleNamespace(open=open_request))
    monkeypatch.setattr(visuals, "_public_url", lambda url: None)
    monkeypatch.setattr(feeds.time, "sleep", lambda seconds: None)
    rows = updates.collect(series(watch=["@Fixture", "@Broken"]), root, now=NOW)
    assert len(rows) == 4 and calls == metadata.calls
    paths = {path for path in tmp_path.rglob("*") if path.is_file() and path != marker}
    assert paths == {root / "brief" / name for name in (
        "network.jsonl", "feeds/ids.json", "feeds/requests.jsonl", "news-errors.jsonl")}
    assert marker.read_text() == '{"offline": false}'


def test_offline_factory_policy_is_preserved(tmp_path):
    (tmp_path / "factory.json").write_text('{"offline": true}')
    root = tmp_path / "channel"
    assert updates.collect(series(), root, now=NOW) == []
    assert "offline" in errors(root)[0]["error"]
    assert not (root / "brief" / "network.jsonl").exists()


@pytest.mark.parametrize("value", [None, [], "news", {}, {"kind": "evergreen"}])
def test_bad_series_raises_before_any_work(tmp_path, metadata, value):
    with pytest.raises(ValueError, match="news series"):
        updates.collect(value, tmp_path, fetch=metadata.fetch, now=NOW)
    assert not metadata.calls and not list(tmp_path.iterdir())
