"""Trend signals from local fixtures, with every external operation blocked."""
from __future__ import annotations

import io
import json
import socket
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing.channels import resurface_signals as signals, updates
from myzing.factory import judge, network, visuals

NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / "fixtures" / "resurface"
TRENDS = signals.TRENDS_URL.format(geo="US")
URLS = [f"https://desk{i}.example.org/feed.xml" for i in range(6)]
EMPTY = "<rss><channel/></rss>"


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(urllib.request, "build_opener", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)


@pytest.fixture
def metadata():
    data = {TRENDS: (FIXTURES / "trends.xml").read_bytes()}
    calls = []

    def fetch(url):
        calls.append(url)
        value = data[url]
        if isinstance(value, Exception):
            raise value
        return value
    return SimpleNamespace(data=data, calls=calls, fetch=fetch)


def trend(*, traffic="20,000+", published=NOW, entity="Maya Stone", headlines=True):
    tree = ET.parse(FIXTURES / "trends.xml").getroot()
    channel = tree.find("channel")
    for row in channel.findall("item")[1:]:
        channel.remove(row)
    row = channel.find("item")
    row.find("title").text = entity
    row.find("ht:approx_traffic", signals.NS).text = traffic
    row.find("pubDate").text = published.isoformat() if isinstance(published, datetime) else published
    if not headlines:
        for item in row.findall("ht:news_item", signals.NS):
            row.remove(item)
    return ET.tostring(tree)


def publishers(metadata, count, *, now=NOW, urls=URLS):
    metadata.data[TRENDS] = EMPTY
    for index, url in enumerate(urls):
        tree = ET.parse(FIXTURES / "publisher.xml").getroot()
        row = tree.find("channel/item")
        if index < count:
            row.find("title").text = f"Maya Stone opens lab number {index}"
            row.find("link").text = f"https://desk{index}.example.org/{now:%Y%m%d%H}/lab"
            row.find("pubDate").text = (now - timedelta(minutes=30)).isoformat()
        else:
            tree.find("channel").remove(row)
        metadata.data[url] = ET.tostring(tree)


def history(root, metadata, counts, *, evening=False):
    for day, count in zip(range(len(counts), 0, -1), counts):
        at = NOW - timedelta(days=day)
        publishers(metadata, count, now=at)
        assert signals.watch(["Maya Stone"], feeds=URLS, state_dir=root, now=at, fetch=metadata.fetch,
                             min_publishers=100, warmup_publishers=100) == []
        if evening:
            at += timedelta(hours=6)
            publishers(metadata, 6, now=at)
            assert signals.watch(["Maya Stone"], feeds=URLS, state_dir=root, now=at, fetch=metadata.fetch,
                                 min_publishers=100, warmup_publishers=100) == []


def state(root):
    return json.loads((root / "signals.json").read_text(encoding="utf-8"))


def transport(monkeypatch, responses):
    calls, checked, handlers, reads = [], [], [], []

    class Response(io.BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    def open_request(request, timeout):
        calls.append(request)
        assert timeout == 20
        value = responses[len(calls) - 1]
        if isinstance(value, Exception):
            raise value
        body, headers = value
        response = Response(body)
        response.headers, response.status = headers, 200
        return response

    def opener(*args):
        handlers.extend(args)
        return SimpleNamespace(open=open_request)
    monkeypatch.setattr(urllib.request, "build_opener", opener)
    monkeypatch.setattr(visuals, "_public_url", lambda url: checked.append(url) or url)
    return SimpleNamespace(calls=calls, checked=checked, handlers=handlers, reads=reads)


@pytest.mark.parametrize("text,count", [
    ("20,000+", 20000), ("2M+", 2000000), ("500K+", 500000), ("1.25M+", 1250000),
    (" 2.5k+ ", 2500), ("1B+", 1000000000), ("19.9", 19), ("10000", 10000),
    ("", 0), ("unknown", 0), ("-100", 0), ("NaN", 0), ("1e4", 0),
])
def test_traffic_lower_bound(text, count):
    assert signals._traffic(text) == count


def test_real_namespace_missing_fields_and_extra_tags(metadata):
    rows = signals._trends(metadata.data[TRENDS], "US")
    assert rows[0] == {
        "entity": "Maya Stone", "signal": "google_trends", "traffic": 20000,
        "published": "2026-11-09T11:30:00+00:00", "geo": "US",
        "headlines": [
            {"title": "Maya Stone announces a lunar lab", "url": "https://space.example.org/lab", "source": "Space Desk"},
            {"title": "Maya Stone & the lunar lab", "url": "https://science.example.org/lab", "source": ""}],
    }
    assert len(rows) == 4
    assert rows[-1] == {"entity": "Quiet topic", "signal": "google_trends", "traffic": 0,
                        "published": "", "headlines": [], "geo": "US"}
    assert [row["traffic"] for row in rows[1:3]] == [2000000, 500000]


@pytest.mark.parametrize("watch_list", [
    {"Maya Stone": ["M. Stone"], "Spaceflight": ["Orion mission"], "Ann": []},
    [{"name": "Maya Stone", "aliases": ["M. Stone"]}, {"entity": "Spaceflight", "aliases": "Orion mission"}, "Ann"],
])
def test_watch_alias_case_boundaries_and_newest_first(tmp_path, metadata, watch_list):
    metadata.data[TRENDS] = metadata.data[TRENDS].replace(b"<title>Maya Stone</title>", b"<title>M. STONE</title>")
    rows = signals.watch(watch_list, state_dir=tmp_path, fetch=metadata.fetch, now=NOW)
    assert [row["entity"] for row in rows] == ["Orion mission", "M. STONE"]
    assert all(row["first_seen"] == NOW.isoformat() and row["signal"] == "google_trends" for row in rows)
    assert metadata.calls == [TRENDS]


@pytest.mark.parametrize("traffic,headlines,triggered", [("9,999+", True, False), ("10,000+", True, True), ("2M+", False, False)])
def test_primary_trigger_needs_traffic_and_headlines(tmp_path, metadata, traffic, headlines, triggered):
    metadata.data[TRENDS] = trend(traffic=traffic, headlines=headlines)
    rows = signals.watch(["Maya Stone"], state_dir=tmp_path, fetch=metadata.fetch, now=NOW, min_traffic=10000)
    assert bool(rows) == triggered


def test_default_traffic_bar_is_any_listing_on_the_watch_list(tmp_path, metadata):
    metadata.data[TRENDS] = trend(traffic="200+")
    assert len(signals.watch(["Maya Stone"], state_dir=tmp_path, fetch=metadata.fetch, now=NOW)) == 1


@pytest.mark.parametrize("elapsed,triggered", [(timedelta(hours=2), True), (timedelta(hours=2, microseconds=1), False)])
def test_primary_two_hour_first_seen_window(tmp_path, metadata, elapsed, triggered):
    metadata.data[TRENDS] = trend(traffic="5K+")
    assert signals.watch(["Maya Stone"], state_dir=tmp_path, fetch=metadata.fetch, now=NOW, min_traffic=10000) == []
    metadata.data[TRENDS] = trend(traffic="10K+")
    rows = signals.watch(["Maya Stone"], state_dir=tmp_path, fetch=metadata.fetch, now=NOW + elapsed, min_traffic=10000)
    assert bool(rows) == triggered
    saved = next(iter(state(tmp_path)["events"].values()))
    assert saved["first_seen"] == NOW.isoformat()
    assert saved["traffic_previous"] == 5000 and saved["traffic_growth"] == 5000


def test_persisted_cooldown_growth_and_fresh_episode_after_24_hours(tmp_path, metadata):
    metadata.data[TRENDS] = trend()
    assert len(signals.watch(["Maya Stone"], state_dir=tmp_path, fetch=metadata.fetch, now=NOW)) == 1
    for hours in (1, 23):
        metadata.data[TRENDS] = trend(traffic="30K+", published=NOW + timedelta(hours=hours), entity="MAYA STONE")
        assert signals.watch(["maya stone"], state_dir=tmp_path, fetch=metadata.fetch, now=NOW + timedelta(hours=hours)) == []
        saved = next(iter(state(tmp_path)["events"].values()))
        assert saved["first_seen"] == NOW.isoformat() and saved["traffic"] == 30000
        assert saved["traffic_growth"] == (10000 if hours == 1 else 0)
    at = NOW + timedelta(hours=24)
    assert signals.watch(["Maya Stone"], state_dir=tmp_path, fetch=metadata.fetch, now=at) == []
    metadata.data[TRENDS] = trend(traffic="40K+", published=at)
    row = signals.watch(["Maya Stone"], state_dir=tmp_path, fetch=metadata.fetch, now=at)[0]
    assert row["first_seen"] == at.isoformat() and row["traffic_growth"] == 10000


def test_expiry_removes_events_and_does_not_revive_stale_feed(tmp_path, metadata):
    metadata.data[TRENDS] = trend()
    signals.watch(["Maya Stone"], state_dir=tmp_path, fetch=metadata.fetch, now=NOW)
    assert signals.watch(["Maya Stone"], state_dir=tmp_path, fetch=metadata.fetch, now=NOW + timedelta(hours=47)) == []
    assert state(tmp_path)["events"]
    assert signals.watch(["Maya Stone"], state_dir=tmp_path, fetch=metadata.fetch, now=NOW + timedelta(hours=48)) == []
    assert state(tmp_path)["events"] == {} and state(tmp_path)["notified"] == {}


def test_primary_thresholds_can_be_changed(tmp_path, metadata):
    metadata.data[TRENDS] = trend(traffic="100+")
    args = dict(state_dir=tmp_path, fetch=metadata.fetch, min_traffic=100, window_hours=4,
                cooldown_hours=6, expiry_hours=12)
    assert signals.watch(["Maya Stone"], now=NOW, min_headlines=3, **args) == []
    assert len(signals.watch(["Maya Stone"], now=NOW + timedelta(hours=3), min_headlines=2, **args)) == 1
    at = NOW + timedelta(hours=9)
    metadata.data[TRENDS] = trend(traffic="100+", published=at)
    assert len(signals.watch(["Maya Stone"], now=at, **args)) == 1
    metadata.data[TRENDS] = EMPTY
    assert signals.watch(["Maya Stone"], now=at + timedelta(hours=12), **args) == []
    assert state(tmp_path)["events"] == {}


@pytest.mark.parametrize("stamp", [NOW - timedelta(hours=49), NOW + timedelta(minutes=1)])
def test_stale_and_future_publications_are_not_new(tmp_path, metadata, stamp):
    metadata.data[TRENDS] = trend(published=stamp)
    assert signals.watch(["Maya Stone"], state_dir=tmp_path, fetch=metadata.fetch, now=NOW) == []


def test_missing_date_uses_observation_time_without_inventing_publication(tmp_path, metadata):
    metadata.data[TRENDS] = trend(published="not a date")
    row = signals.watch("Maya Stone", state_dir=tmp_path, fetch=metadata.fetch, now=NOW.replace(tzinfo=None))[0]
    assert row["published"] == "" and row["first_seen"] == NOW.isoformat()


def test_empty_watch_does_not_fetch_and_geo_is_configurable(tmp_path, metadata):
    assert signals.watch([], state_dir=tmp_path, fetch=metadata.fetch, now=NOW) == []
    assert metadata.calls == []
    url = signals.TRENDS_URL.format(geo="GB")
    metadata.data[url] = trend()
    row = signals.watch(["Maya Stone"], geo="gb", state_dir=tmp_path, fetch=metadata.fetch, now=NOW)[0]
    assert row["geo"] == "GB" and metadata.calls == [url]


def test_news_feeds_run_with_a_nonempty_primary_and_repeats_stay_quiet(tmp_path, metadata):
    args = dict(state_dir=tmp_path, fetch=metadata.fetch, now=NOW)
    assert signals.watch(["Someone Else"], **args) == []
    assert len(signals.watch(["Maya Stone"], **args)) == 1
    assert signals.watch(["Maya Stone"], **args) == []
    assert metadata.calls == [TRENDS] * 3
    metadata.calls.clear()
    signals.watch(["Someone Else"], feeds=URLS, **args)
    assert metadata.calls[0] == TRENDS and set(URLS) <= set(metadata.calls)


def test_weaker_alias_query_does_not_hide_qualifying_trend(tmp_path, metadata):
    tree = ET.fromstring(trend(published=NOW - timedelta(minutes=30)))
    newer = ET.fromstring(trend(traffic="100+", entity="M. Stone"))
    tree.find("channel").append(newer.find("channel/item"))
    metadata.data[TRENDS] = ET.tostring(tree)
    rows = signals.watch({"Maya Stone": ["M. Stone"]}, state_dir=tmp_path, fetch=metadata.fetch, now=NOW)
    assert len(rows) == 1 and rows[0]["entity"] == "Maya Stone" and rows[0]["traffic"] == 20000
    saved = next(iter(state(tmp_path)["events"].values()))
    assert saved["entity"] == "Maya Stone" and saved["traffic"] == 20000


@pytest.mark.parametrize("count,triggered", [(3, False), (4, False), (5, True), (6, True)])
def test_backup_warmup_needs_five_publishers(tmp_path, metadata, count, triggered):
    publishers(metadata, count)
    rows = signals.watch(["Maya Stone"], feeds=URLS, state_dir=tmp_path, fetch=metadata.fetch, now=NOW)
    assert bool(rows) == triggered
    if triggered:
        assert rows[0]["signal"] == "publisher_rss" and rows[0]["traffic"] == count
        assert rows[0]["published"] == (NOW - timedelta(minutes=30)).isoformat()
        assert rows[0]["first_seen"] == NOW.isoformat() and len(rows[0]["headlines"]) == count


def test_syndicated_titles_and_canonical_links_do_not_inflate_publishers(tmp_path, metadata):
    publishers(metadata, 6)
    metadata.data[URLS[0]] = (FIXTURES / "publisher.xml").read_bytes()
    metadata.data[URLS[1]] = (FIXTURES / "syndicated.xml").read_bytes()
    metadata.data[URLS[2]] = (FIXTURES / "syndicated.xml").read_bytes()
    assert signals.watch(["Maya Stone"], feeds=URLS, state_dir=tmp_path, fetch=metadata.fetch, now=NOW) == []
    metadata.data[URLS[2]] = (FIXTURES / "publisher.atom").read_bytes()
    rows = signals.watch({"Maya Stone": ["M. Stone"]}, feeds=URLS, state_dir=tmp_path, fetch=metadata.fetch, now=NOW)
    assert len(rows) == 1 and rows[0]["traffic"] == 5
    assert any(row["url"] == "https://science.example.org/lab-design" for row in rows[0]["headlines"])


def test_multiple_feeds_of_one_publisher_count_once(tmp_path, metadata):
    urls = [f"https://one.example.org/{index}.xml" for index in range(6)]
    publishers(metadata, 6, urls=urls)
    assert signals.watch(["Maya Stone"], feeds=urls, state_dir=tmp_path, fetch=metadata.fetch, now=NOW) == []


def test_syndication_assignment_does_not_depend_on_feed_order():
    rows = [
        {"title": "Same story", "url": "https://a.example.org/same", "publisher": "a"},
        {"title": "SAME STORY!", "url": "https://b.example.org/same", "publisher": "b"},
        {"title": "Other story", "url": "https://a.example.org/other", "publisher": "a"},
    ]
    for items in (rows, list(reversed(rows))):
        kept = signals._independent(items)
        assert len(kept) == 2 and {row["publisher"] for row in kept} == {"a", "b"}
    rows.append({"title": "Other story", "url": "https://b.example.org/same#top", "publisher": "c"})
    assert len(signals._independent(rows)) == 1


@pytest.mark.parametrize("count,triggered", [(3, False), (5, False), (6, True)])
def test_backup_uses_seven_day_median_and_threefold_growth(tmp_path, metadata, count, triggered):
    history(tmp_path, metadata, [1, 2, 2, 2, 2, 6, 6])
    publishers(metadata, count)
    rows = signals.watch(["Maya Stone"], feeds=URLS, state_dir=tmp_path, fetch=metadata.fetch, now=NOW)
    assert bool(rows) == triggered
    if triggered:
        assert rows[0]["median_publishers"] == 2 and rows[0]["traffic"] == 6


def test_zero_windows_count_in_baseline_after_three_days(tmp_path, metadata):
    history(tmp_path, metadata, [0, 0, 0])
    publishers(metadata, 3)
    row = signals.watch(["Maya Stone"], feeds=URLS, state_dir=tmp_path, fetch=metadata.fetch, now=NOW)[0]
    assert row["traffic"] == 3 and row["median_publishers"] == 0


def test_before_three_days_and_polling_gaps_keep_warmup(tmp_path, metadata):
    history(tmp_path, metadata, [0, 0])
    publishers(metadata, 3)
    assert signals.watch(["Maya Stone"], feeds=URLS, state_dir=tmp_path, fetch=metadata.fetch, now=NOW) == []
    later = NOW + timedelta(days=6)
    publishers(metadata, 3, now=later)
    assert signals.watch(["Maya Stone"], feeds=URLS, state_dir=tmp_path, fetch=metadata.fetch, now=later) == []


def test_baseline_uses_matching_utc_window_and_discards_old_history(tmp_path, metadata):
    history(tmp_path, metadata, [1] * 9, evening=True)
    publishers(metadata, 3)
    row = signals.watch(["Maya Stone"], feeds=URLS, state_dir=tmp_path, fetch=metadata.fetch, now=NOW)[0]
    assert row["median_publishers"] == 1 and row["traffic"] == 3
    saved = state(tmp_path)["history"]["maya stone"]
    assert all(updates._published(item["published"]) > NOW - timedelta(days=7, hours=2) for item in saved["rows"])


def test_changed_feeds_restart_warmup(tmp_path, metadata):
    history(tmp_path, metadata, [0, 0, 0])
    publishers(metadata, 3)
    assert signals.watch(["Maya Stone"], feeds=URLS[:-1], state_dir=tmp_path, fetch=metadata.fetch, now=NOW) == []


@pytest.mark.parametrize("stamp", [NOW - timedelta(hours=2), NOW + timedelta(seconds=1), "bad date", ""])
def test_backup_ignores_out_of_window_or_missing_dates(tmp_path, metadata, stamp):
    publishers(metadata, 5)
    tree = ET.fromstring(metadata.data[URLS[0]])
    tree.find("channel/item/pubDate").text = stamp.isoformat() if isinstance(stamp, datetime) else stamp
    metadata.data[URLS[0]] = ET.tostring(tree)
    assert signals.watch(["Maya Stone"], feeds=URLS, state_dir=tmp_path, fetch=metadata.fetch, now=NOW) == []


def test_backup_alias_boundaries_and_repeated_polls_do_not_inflate_counts(tmp_path, metadata):
    publishers(metadata, 4)
    metadata.data[URLS[0]] = (FIXTURES / "publisher.atom").read_bytes()
    args = dict(feeds=URLS, state_dir=tmp_path, fetch=metadata.fetch, now=NOW)
    for _ in range(4):
        assert signals.watch({"Maya Stone": ["M. Stone"], "May": []}, **args) == []
    assert len(state(tmp_path)["history"]["maya stone"]["rows"]) == 4
    assert state(tmp_path)["history"]["may"]["rows"] == []


def test_primary_then_backup_does_not_repeat_same_entity(tmp_path, metadata):
    assert len(signals.watch(["Maya Stone"], state_dir=tmp_path, fetch=metadata.fetch, now=NOW)) == 1
    publishers(metadata, 5, now=NOW + timedelta(hours=1))
    assert signals.watch(["Maya Stone"], feeds=URLS, state_dir=tmp_path, fetch=metadata.fetch,
                         now=NOW + timedelta(hours=1)) == []


@pytest.mark.parametrize("bad", ["<rss", "<html/>", urllib.error.URLError("fixture outage"), RuntimeError("fixture outage")])
def test_primary_outage_returns_error_and_backup(tmp_path, metadata, bad):
    publishers(metadata, 5)
    metadata.data[TRENDS] = bad
    rows = signals.watch(["Maya Stone"], feeds=URLS, state_dir=tmp_path, fetch=metadata.fetch, now=NOW)
    assert len(rows) == 2 and rows[0]["signal"] == "publisher_rss"
    assert rows[1]["signal"] == "google_trends" and rows[1]["error"]


def test_publisher_outage_keeps_other_feeds_and_does_not_count_as_history(tmp_path, metadata):
    for day in range(3, -1, -1):
        at = NOW - timedelta(days=day)
        publishers(metadata, 3, now=at)
        metadata.data[URLS[5]] = urllib.error.URLError("fixture outage")
        rows = signals.watch(["Maya Stone"], feeds=URLS, state_dir=tmp_path, fetch=metadata.fetch, now=at)
        assert len(rows) == 1 and rows[0]["signal"] == "publisher_rss" and rows[0]["url"] == URLS[5]
    assert state(tmp_path)["history"]["maya stone"]["windows"] == []
    publishers(metadata, 5)
    metadata.data[URLS[5]] = urllib.error.URLError("fixture outage")
    rows = signals.watch(["Maya Stone"], feeds=URLS, state_dir=tmp_path, fetch=metadata.fetch, now=NOW)
    assert len(rows) == 2 and rows[0]["traffic"] == 5 and rows[1]["error"]


def test_conditional_requests_preserve_events_and_use_shared_transport(tmp_path, monkeypatch):
    modified = "Mon, 09 Nov 2026 11:00:00 GMT"
    wire = transport(monkeypatch, [(trend(), {"ETag": '"v1"', "Last-Modified": modified}),
                                   urllib.error.HTTPError(TRENDS, 304, "unchanged", {}, None)])
    assert len(signals.watch(["Maya Stone"], state_dir=tmp_path, now=NOW)) == 1
    assert signals.watch(["Maya Stone"], state_dir=tmp_path, now=NOW + timedelta(hours=1)) == []
    assert not wire.calls[0].has_header("If-none-match")
    assert wire.calls[1].get_header("If-none-match") == '"v1"'
    assert wire.calls[1].get_header("If-modified-since") == modified
    assert wire.checked == [TRENDS, TRENDS]
    assert any(isinstance(handler, network._HTTPHandler) for handler in wire.handlers)
    assert any(isinstance(handler, network._HTTPSHandler) for handler in wire.handlers)
    assert any(isinstance(handler, network._Redirect) for handler in wire.handlers)
    assert wire.reads == [updates.FEED_CAP + 1]
    ledger = [json.loads(line) for line in (tmp_path / "network.jsonl").read_text().splitlines()]
    assert [row["bytes"] for row in ledger] == [len(trend()), 0]
    assert all(row["host"] == "trends.google.com" and row["purpose"] == "trend feed" for row in ledger)
    assert next(iter(state(tmp_path)["events"].values()))["traffic_growth"] == 0


@pytest.mark.parametrize("code,retry_after", [(429, "1800"), (503, "Mon, 09 Nov 2026 12:30:00 GMT"), (502, "1800")])
def test_persistent_retry_after_backoff(tmp_path, monkeypatch, code, retry_after):
    error = urllib.error.HTTPError(TRENDS, code, "fixture outage", {"Retry-After": retry_after}, None)
    wire = transport(monkeypatch, [error, (trend(), {})])
    rows = signals.watch(["Maya Stone"], state_dir=tmp_path, now=NOW)
    assert rows == [{"signal": "google_trends", "error": f"feed request failed with HTTP {code}"}]
    rows = signals.watch(["Maya Stone"], state_dir=tmp_path, now=NOW + timedelta(minutes=29))
    assert "retry waits" in rows[0]["error"] and len(wire.calls) == 1
    assert len(signals.watch(["Maya Stone"], state_dir=tmp_path, now=NOW + timedelta(minutes=30))) == 1
    assert len(wire.calls) == 2 and "retry_at" not in state(tmp_path)["http"][TRENDS]


def test_server_errors_increase_backoff_without_sleeping(tmp_path, monkeypatch):
    wire = transport(monkeypatch, [urllib.error.HTTPError(TRENDS, 500, "outage", {}, None) for _ in range(3)])
    for seconds in (0, 60, 179, 180):
        assert signals.watch(["Maya Stone"], state_dir=tmp_path, now=NOW + timedelta(seconds=seconds))[0]["error"]
    assert len(wire.calls) == 3
    assert state(tmp_path)["http"][TRENDS]["retry_at"] == (NOW + timedelta(seconds=420)).isoformat()


def test_missing_304_body_is_an_error(tmp_path, monkeypatch):
    transport(monkeypatch, [urllib.error.HTTPError(TRENDS, 304, "unchanged", {}, None)])
    assert signals.watch(["Maya Stone"], state_dir=tmp_path, now=NOW) == [
        {"signal": "google_trends", "error": "feed request failed with HTTP 304"}]


def test_304_updates_validators_and_200_clears_them(tmp_path, monkeypatch):
    wire = transport(monkeypatch, [(trend(), {"ETag": '"v1"'}),
                                   urllib.error.HTTPError(TRENDS, 304, "unchanged", {"ETag": '"v2"'}, None),
                                   (trend(), {}), urllib.error.HTTPError(TRENDS, 304, "unchanged", {}, None)])
    for minute in range(3):
        signals.watch(["Maya Stone"], state_dir=tmp_path, now=NOW + timedelta(minutes=minute))
    assert wire.calls[2].get_header("If-none-match") == '"v2"'
    rows = signals.watch(["Maya Stone"], state_dir=tmp_path, now=NOW + timedelta(minutes=3))
    assert not wire.calls[3].has_header("If-none-match")
    assert rows == [{"signal": "google_trends", "error": "feed request failed with HTTP 304"}]


def test_private_host_is_rejected_before_connecting(tmp_path, metadata, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))])
    rows = signals.watch(["Maya Stone"], state_dir=tmp_path, now=NOW)
    assert rows == [{"signal": "google_trends", "error": "refusing private address trends.google.com"}]
    ledger = json.loads((tmp_path / "network.jsonl").read_text())
    assert ledger["bytes"] == 0


def test_parent_offline_policy_is_preserved_and_ledger_stays_in_state_dir(tmp_path, monkeypatch):
    marker = tmp_path / "factory.json"
    marker.write_text('{"offline": true}')
    root = tmp_path / "signals"
    assert "offline" in signals.watch(["Maya Stone"], state_dir=root, now=NOW)[0]["error"]
    assert not (root / "network.jsonl").exists()
    marker.write_text('{"offline": false}')
    transport(monkeypatch, [(trend(), {})])
    assert len(signals.watch(["Maya Stone"], state_dir=root, now=NOW)) == 1
    assert (root / "network.jsonl").is_file() and not (tmp_path / "network.jsonl").exists()


def test_request_cap_and_old_cache_cleanup(tmp_path, monkeypatch):
    wire = transport(monkeypatch, [(b"x" * (updates.FEED_CAP + 2), {})])
    assert signals.watch(["Maya Stone"], state_dir=tmp_path, now=NOW)[0]["error"] == "news feed exceeds 4 MB"
    assert wire.reads == [updates.FEED_CAP + 1]
    transport(monkeypatch, [(trend(), {"ETag": '"v1"'})])
    assert len(signals.watch(["Maya Stone"], state_dir=tmp_path, now=NOW)) == 1
    assert len(list((tmp_path / "signals-cache").iterdir())) == 1
    signals.watch([], state_dir=tmp_path, now=NOW + timedelta(days=9))
    assert state(tmp_path)["http"] == {} and list((tmp_path / "signals-cache").iterdir()) == []


@pytest.mark.parametrize("baseline,last,spike", [(200, 599, False), (200, 600, False), (200, 699, False),
                                               (200, 700, True), (1000, 1500, False), (300, 900, True),
                                               (0, 499, False), (0, 500, True)])
def test_pageview_spike_requires_ratio_and_extra_views(tmp_path, baseline, last, spike):
    data = json.loads((FIXTURES / "pageviews.json").read_text())
    for row in data["items"][:-1]:
        row["views"] = baseline
    data["items"][-1]["views"] = last
    assert signals.pageview_spike("Maya Stone", state_dir=tmp_path, now=NOW, fetch=lambda url: json.dumps(data)) is spike


@pytest.mark.parametrize("change", ["missing_yesterday", "missing_baseline", "only_today", "partial_today", "bad_views"])
def test_pageview_history_must_cover_complete_days(tmp_path, change):
    data = json.loads((FIXTURES / "pageviews.json").read_text())
    if change == "missing_yesterday":
        data["items"].pop()
    elif change == "missing_baseline":
        data["items"].pop(0)
    elif change == "bad_views":
        data["items"][0]["views"] = True
    else:
        data["items"][-1]["timestamp"] = "2026110900"
        if change == "partial_today":
            data["items"].append({"timestamp": "2026110800", "views": 200})
    assert signals.pageview_spike("Maya Stone", state_dir=tmp_path, now=NOW, fetch=lambda url: json.dumps(data)) is False


def test_wikimedia_url_user_agent_and_ledger(tmp_path, monkeypatch):
    wire = transport(monkeypatch, [((FIXTURES / "pageviews.json").read_bytes(), {})])
    assert signals.pageview_spike("Maya Stone/Flight", state_dir=tmp_path, now=NOW)
    request = wire.calls[0]
    assert request.full_url == signals.PAGEVIEWS_URL + "/en.wikipedia.org/all-access/user/Maya_Stone%2FFlight/daily/2026101100/2026110800"
    agent = request.get_header("User-agent")
    assert "Zing" in agent and "https://github.com/ryanbiddy/zing" in agent and "@" not in agent
    assert not request.has_header("Cookie") and not request.has_header("Authorization")
    assert json.loads((tmp_path / "network.jsonl").read_text())["purpose"] == "Wikimedia pageviews"


def test_pageviews_use_median_and_ignore_partial_current_day(tmp_path):
    data = json.loads((FIXTURES / "pageviews.json").read_text())
    data["items"][0]["views"] = 1000000
    data["items"].append({"timestamp": "2026110900", "views": 2000000})
    data["items"].reverse()
    assert signals.pageview_spike("Maya Stone", state_dir=tmp_path, now=NOW, fetch=lambda url: json.dumps(data))


def test_corroboration_only_attaches_to_new_triggered_events(tmp_path, metadata):
    calls = []

    def fetch(url):
        calls.append(url)
        return (FIXTURES / "pageviews.json").read_bytes() if url.startswith(signals.PAGEVIEWS_URL) else metadata.fetch(url)
    args = dict(state_dir=tmp_path, now=NOW, fetch=fetch, articles={"Maya Stone": "Maya Stone"})
    metadata.data[TRENDS] = trend(traffic="100+")
    assert signals.watch(["Maya Stone"], **args) == []
    assert calls == [TRENDS]
    metadata.data[TRENDS] = trend()
    row = signals.watch(["Maya Stone"], **args)[0]
    assert row["signal"] == "google_trends" and row["corroborated"] is True
    assert signals.watch(["Maya Stone"], **args) == []
    assert len([url for url in calls if url.startswith(signals.PAGEVIEWS_URL)]) == 1


def test_corroboration_outage_keeps_trigger(tmp_path, metadata):
    def fetch(url):
        if url.startswith(signals.PAGEVIEWS_URL):
            raise urllib.error.URLError("fixture outage")
        return metadata.fetch(url)
    rows = signals.watch(["Maya Stone"], state_dir=tmp_path, now=NOW, fetch=fetch, articles={"Maya Stone": "Maya Stone"})
    assert len(rows) == 2 and rows[0]["signal"] == "google_trends"
    assert rows[1]["signal"] == "wikimedia" and rows[1]["error"]
