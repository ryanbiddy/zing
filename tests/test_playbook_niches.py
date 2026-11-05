"""Offline metadata fixtures for feeds, velocity, title heuristics and niche priors."""
from __future__ import annotations

import json
import subprocess
import urllib.error
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from xml.sax.saxutils import escape

import pytest

from conftest import FakeHTTPResponse, zing_workspace
from myzing.playbook import command, feeds, niches, sources, titles, watch
from myzing.playbook.common import append_jsonl, read_json, write_json

CHANNEL = "UC" + "a" * 22
OTHER = "UC" + "b" * 22
NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)
STORY = "Peyton Manning banned wives from the team hotel 👀"
NEWS = "Raiders are stepping up 😤"


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(feeds.urllib.request, "urlopen", refuse)
    monkeypatch.setattr(feeds.urllib.request, "build_opener", refuse)
    monkeypatch.setattr(sources.proc, "run", refuse)
    monkeypatch.setattr(feeds, "_last_request", None)


@pytest.fixture
def metadata(tmp_path):
    values = [10, 20, 30, 40, 50, 100, 100, 150, 200, 250, 300, 600, 9000, 9000, 9000]
    entries = []
    for i, views in enumerate(values):
        url = f"https://www.youtube.com/shorts/video{i}" if i < 12 else f"https://www.youtube.com/watch?v=video{i}"
        entries.append(f'''<entry><yt:videoId>video{i}</yt:videoId><yt:channelId>{CHANNEL}</yt:channelId>
            <title>{escape(STORY if i >= 8 else NEWS)} fixture {i}</title><link rel="alternate" href="{url}"/>
            <published>{(NOW - timedelta(days=16 - i)).isoformat()}</published>
            <author><name>Fixture channel</name></author><media:group>
            <media:thumbnail url="https://example.invalid/never-fetch.jpg"/>
            <media:community><media:statistics views="{views}"/></media:community></media:group></entry>''')
    xml = tmp_path / "feed.xml"
    xml.write_text('''<feed xmlns="http://www.w3.org/2005/Atom"
        xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/">
        <title>Fixture channel</title>''' + "".join(entries) + "</feed>", encoding="utf-8")
    page = tmp_path / "channel.html"
    page.write_text(f'''<html><head><link href="https://www.youtube.com/channel/{CHANNEL}"
        rel="canonical"></head><body>fixture</body></html>''', encoding="utf-8")
    calls = []

    def fetch(url):
        calls.append(url)
        if url == "https://www.youtube.com/@Fixture":
            return page.read_text(encoding="utf-8")
        assert url == f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL}"
        return xml.read_text(encoding="utf-8")
    return SimpleNamespace(fetch=fetch, calls=calls, xml=xml, page=page)


def config(channels=("@Fixture",)):
    return {"niches": [{"niche": "NFL stories", "channels": list(channels), "rights": "mixed",
                        "fit": "high", "money": "mid", "notes": "Check source permissions."}]}


def jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_resolve_canonical_external_id_and_cache(tmp_path, metadata):
    out = tmp_path / "out"
    assert feeds.resolve(CHANNEL, metadata.fetch, root=out) == CHANNEL
    assert not metadata.calls
    assert feeds.resolve("@Fixture", metadata.fetch, root=out) == CHANNEL
    assert feeds.resolve("fixture", metadata.fetch, root=out) == CHANNEL
    assert len(metadata.calls) == 1
    assert read_json(out / "feeds/ids.json") == {"fixture": CHANNEL}
    assert feeds.resolve("Other", lambda url: f'{{"externalId" : "{OTHER}"}}', root=out) == OTHER
    with pytest.raises(ValueError, match="no public channel ID"):
        feeds.resolve("Missing", lambda url: "<html></html>", root=out)
    for invalid in ("UCshort", CHANNEL + "x", "@bad/path", "@evil?query", ""):
        with pytest.raises(ValueError):
            feeds.resolve(invalid, metadata.fetch, root=out)


def test_feed_parsing_uses_only_public_fields(metadata):
    rows = feeds.feed(CHANNEL, metadata.fetch)
    assert len(rows) == 15
    assert rows[0] == {"id": "video0", "title": NEWS + " fixture 0", "published": "2026-10-20T00:00:00+00:00",
                       "views": 10, "short": True, "channel_id": CHANNEL, "channel_title": "Fixture channel"}
    assert sum(row["short"] for row in rows) == 12
    assert rows[-1]["short"] is False and rows[-1]["views"] == 9000
    assert len(metadata.calls) == 1 and "thumbnail" not in json.dumps(rows)
    for text in ("<feed", "<html/>"):
        with pytest.raises(ValueError, match="feed"):
            feeds.feed(CHANNEL, lambda url: text)
    missing = metadata.xml.read_text(encoding="utf-8").replace('views="10"', 'views="unknown"')
    assert len(feeds.feed(CHANNEL, lambda url: missing)) == 14


@pytest.mark.parametrize("url", ["https://youtube.com/feed", "https://www.youtube.com.evil.test/feed",
    "https://evil.test/www.youtube.com", "https://user@www.youtube.com/feed", "http://www.youtube.com/feed",
    "file:///feed", "https://www.youtube.com:444/feed"])
def test_feed_transport_refuses_other_hosts_and_schemes(tmp_path, url):
    with pytest.raises(ValueError, match="https://www.youtube.com"):
        feeds.request(url, root=tmp_path)
    assert not (tmp_path / "feeds/requests.jsonl").exists()


def test_default_transport_logs_errors_throttles_and_sends_no_credentials(tmp_path, monkeypatch):
    clock, calls, waits = [0.0], [], []

    def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds

    def open_request(req, timeout):
        calls.append((clock[0], req.full_url))
        assert timeout == 20
        assert dict(req.header_items()) == {"User-agent": "Mozilla/5.0 (compatible; Zing)"}
        if len(calls) == 3:
            raise urllib.error.HTTPError(req.full_url, 403, "forbidden", {}, None)
        return FakeHTTPResponse(b"fixture text")

    monkeypatch.setattr(feeds.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(feeds.time, "sleep", sleep)
    monkeypatch.setattr(feeds.urllib.request, "build_opener", lambda handler: SimpleNamespace(open=open_request))
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL}"
    assert feeds.request(url, root=tmp_path) == "fixture text"
    feeds.request(url, root=tmp_path)
    with pytest.raises(ValueError, match="HTTP 403"):
        feeds.request(url, root=tmp_path)
    assert [at for at, _ in calls] == [0, 1.5, 3]
    assert waits == [1.5, 1.5]
    log = jsonl(tmp_path / "feeds/requests.jsonl")
    assert [row["status"] for row in log] == [200, 200, 403]
    assert all(set(row) == {"at", "url", "status"} and row["url"] == url for row in log)


def test_connection_failures_are_logged(tmp_path, monkeypatch):
    def fail(req, timeout):
        raise urllib.error.URLError("private upstream detail")
    monkeypatch.setattr(feeds.urllib.request, "build_opener", lambda handler: SimpleNamespace(open=fail))
    with pytest.raises(ValueError, match="^YouTube feed request failed$"):
        feeds.request("https://www.youtube.com/@Fixture", root=tmp_path)
    assert jsonl(tmp_path / "feeds/requests.jsonl")[0]["status"] == "error"


def test_default_watch_keeps_cache_and_log_under_output(tmp_path, metadata, monkeypatch):
    monkeypatch.setattr(feeds.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(feeds.urllib.request, "build_opener", lambda handler: SimpleNamespace(
        open=lambda req, timeout: FakeHTTPResponse(metadata.fetch(req.full_url).encode())))
    out = tmp_path / "out"
    watch.watch(out, ["@Fixture"], now=NOW)
    assert read_json(out / "feeds/ids.json") == {"fixture": CHANNEL}
    assert [row["status"] for row in jsonl(out / "feeds/requests.jsonl")] == [200, 200]
    assert len(jsonl(out / "snapshots.jsonl")) == 15
    assert {path.relative_to(out).as_posix() for path in out.rglob("*") if path.is_file()} == {
        "feeds/ids.json", "feeds/requests.jsonl", "snapshots.jsonl"}


@pytest.mark.parametrize("target", ["https://other.test/feed", "/@Next"])
def test_redirects_are_checked_and_each_request_is_logged(tmp_path, monkeypatch, target):
    calls = []

    def open_request(req, timeout):
        calls.append(req.full_url)
        if len(calls) == 1:
            raise urllib.error.HTTPError(req.full_url, 302, "redirect", {"Location": target}, None)
        return FakeHTTPResponse(b"ok")

    monkeypatch.setattr(feeds.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(feeds.urllib.request, "build_opener", lambda handler: SimpleNamespace(open=open_request))
    if target.startswith("https://other"):
        with pytest.raises(ValueError, match="https://www.youtube.com"):
            feeds.request("https://www.youtube.com/@Old", root=tmp_path)
        assert len(calls) == 1
    else:
        assert feeds.request("https://www.youtube.com/@Old", root=tmp_path) == "ok"
        assert calls[-1] == "https://www.youtube.com/@Next"
    assert [row["status"] for row in jsonl(tmp_path / "feeds/requests.jsonl")] == ([302] if len(calls) == 1 else [302, 200])


def test_watch_appends_snapshots_once_per_channel(tmp_path, metadata):
    out = tmp_path / "out"
    for hour in (0, 1):
        result = watch.watch(out, ["@Fixture", CHANNEL, "@Fixture"], fetch=metadata.fetch, now=NOW + timedelta(hours=hour))
        assert result == {"entries": 15, "channels": {"@Fixture": {"channel_id": CHANNEL, "entries": 15}}}
    rows = jsonl(out / "snapshots.jsonl")
    assert len(rows) == 30 and rows[0]["at"] != rows[15]["at"]
    assert rows[0]["title"] == NEWS + " fixture 0"
    assert set(rows[0]) == {"at", "channel", "channel_id", "id", "title", "published", "views", "short"}
    assert len(metadata.calls) == 3


def snapshot(ident, hour, views, channel=CHANNEL):
    return {"at": (NOW + timedelta(hours=hour)).isoformat(), "channel": "@Fixture", "channel_id": channel,
            "id": ident, "title": "local snapshot title", "published": NOW.isoformat(), "views": views, "short": True}


def test_velocity_targets_nulls_and_channel_median(tmp_path):
    rows = [snapshot("early", hour, int(hour * 100)) for hour in (.8, 1.1, 6, 24, 72, 168)]
    rows += [snapshot("late", hour, int(hour * 100)) for hour in (3, 12, 29)]
    rows += [snapshot("unknown", 40, 50, OTHER), rows[0]]
    append_jsonl(tmp_path / "snapshots.jsonl", reversed(rows))
    result = watch.velocity(tmp_path)
    videos = {row["id"]: row for row in result["videos"]}
    assert videos["early"]["views"] == {"1h": 110, "6h": 600, "24h": 2400, "72h": 7200, "7d": 16800}
    assert videos["early"]["views_per_hour"] == pytest.approx(100)
    assert videos["late"]["views"] == {"1h": None, "6h": None, "24h": 2900, "72h": None, "7d": None}
    assert videos["unknown"]["views_per_hour"] is None
    assert result["channels"][CHANNEL] == {"channel": "@Fixture", "n_24h": 2, "median_24h_views": 2650}
    assert result["channels"][OTHER]["median_24h_views"] is None
    assert read_json(tmp_path / "velocity.json") == result


@pytest.mark.parametrize("offset,expected", [(0, True), (.0001, False)])
def test_velocity_tolerance_boundaries(tmp_path, offset, expected):
    append_jsonl(tmp_path / "snapshots.jsonl", [snapshot("edge", target * 1.25 + offset, i)
                 for i, target in enumerate(watch.TARGETS.values())])
    views = watch.velocity(tmp_path)["videos"][0]["views"]
    assert list(views.values()) == (list(range(5)) if expected else [None] * 5)


def test_velocity_ties_choose_earlier_time_and_invalid_dates_fail(tmp_path):
    append_jsonl(tmp_path / "snapshots.jsonl", [snapshot("tie", 1.25, 20), snapshot("tie", .75, 10)])
    assert watch.velocity(tmp_path)["videos"][0]["views"]["1h"] == 10
    append_jsonl(tmp_path / "snapshots.jsonl", [{**snapshot("bad", 1, 10), "at": None}])
    with pytest.raises(ValueError, match="ISO date"):
        watch.velocity(tmp_path)


def test_title_features_story_and_news():
    story = titles.features(STORY)
    assert story == {"words": 8, "chars": len(STORY), "starts_lowercase": False, "ends_with_emoji": True,
                     "emoji_count": 1, "has_number": False, "has_question": False, "has_quote": False,
                     "has_name": True, "past_tense": True, "present_news": False, "superlative": False,
                     "taboo_or_conflict": True, "how_or_why": False, "first_person_quote": False}
    news = titles.features(NEWS)
    assert news["words"] == 4 and news["present_news"] and news["ends_with_emoji"]
    assert not news["past_tense"] and not news["has_name"] and not news["taboo_or_conflict"]
    assert titles.features("") == {key: 0 if key in ("words", "chars", "emoji_count") else False for key in story}


def test_title_features_numbers_quotes_names_and_word_boundaries():
    title = 'why “I’m the best at 3 things”?'
    row = titles.features(title)
    assert row["words"] == 7 and row["chars"] == len(title)
    assert all(row[key] for key in ("starts_lowercase", "has_number", "has_question", "has_quote", "superlative", "how_or_why", "first_person_quote"))
    assert not row["has_name"] and not row["past_tense"] and not row["present_news"]
    assert not titles.features("I'm ready")["has_quote"]
    assert titles.features("my team")["first_person_quote"]
    assert titles.features("mahomes speaks", known_names=["Mahomes"])["has_name"]
    assert not titles.features("Mahomes speaks")["has_name"]
    assert titles.features("A visit to New York")["has_name"]
    assert titles.features("they walked away")["past_tense"]
    assert titles.features("they used   to play")["past_tense"]
    assert titles.features("fed up with the team")["taboo_or_conflict"]
    assert not titles.features("red speed indeed")["past_tense"]
    assert not titles.features("justice for the island")["present_news"]
    assert not titles.features("this is mine")["first_person_quote"]


def test_emoji_sequences_are_counted_once():
    row = titles.features("team 👨‍👩‍👧‍👦 👍🏽 🇺🇸 1️⃣  ")
    assert row["emoji_count"] == 4 and row["ends_with_emoji"]
    assert not titles.features("team 👀!")["ends_with_emoji"]


def test_feed_scorecard_numbers_skips_and_title_boundary(tmp_path, metadata):
    out = tmp_path / "out"
    skipped = niches.build(out, config(), fetch=metadata.fetch, now=NOW)
    niche = skipped["niches"][0]
    assert niche["channels_listed"] == 0 and niche["channels_skipped"] == 1 and niche["demand_score"] is None
    assert niche["channels"][0]["reason"] == "fewer than 15 Shorts with view counts"
    result = niches.build(out, config(("@Fixture", CHANNEL)), min_shorts=12, fetch=metadata.fetch, now=NOW)
    niche = result["niches"][0]
    channel = niche["channels"][0]
    assert niche["channels_listed"] == 1 and niche["channels_skipped"] == 0
    assert channel["n"] == 12 and channel["median_views"] == 100
    assert channel["mean_views"] == pytest.approx(1850 / 12) and channel["p90_views"] == pytest.approx(295)
    assert channel["outlier_rate"] == pytest.approx(2 / 12) and channel["posting_rate"] == pytest.approx(12 / 11)
    assert channel["newest_published"] == "2026-10-31T00:00:00+00:00"
    assert channel["top"] == [{"id": "video11", "views": 600, "outlier": 6},
                              {"id": "video10", "views": 300, "outlier": 3}, {"id": "video9", "views": 250, "outlier": 2.5}]
    assert niche["demand_score"] == 4 and niche["active_channels"] == 1
    assert niche["n_hits"] == 4 and niche["n_misses"] == 5 and all(row["weak"] for row in niche["lifts"])
    assert {key: niche[key] for key in ("rights", "fit", "money", "notes")} == {
        key: config()["niches"][0][key] for key in ("rights", "fit", "money", "notes")}
    assert len(jsonl(out / "titles.jsonl")) == 12
    assert jsonl(out / "titles.jsonl") == result["local"]["titles"]
    assert read_json(out / "niches.json") == result
    report = (out / "NICHES.md").read_text(encoding="utf-8")
    assert all(row["title"] not in report for row in result["local"]["titles"])
    assert STORY not in report and NEWS not in report and "https://www.youtube.com/shorts/video11" in report
    assert "title" not in json.dumps(niche) and "Weak evidence" in report
    assert niches.prior(out, "NFL stories", out / "prior.json")["guidance"] == []


def listing(channel, scale=1, old=False):
    rows = []
    for i in range(30):
        title = "they waited" if (i < 4 or 20 <= i < 28) else "a quiet day"
        title += "?" if (i < 4 or i == 20) else ""
        rows.append({"id": f"{channel}{i}", "title": title, "view_count": (10 if i < 10 else 100 if i < 20 else 300) * scale,
                     "duration": 180, "upload_date": (NOW - timedelta(days=i + (60 if old else 0))).strftime("%Y%m%d")})
    return rows


def test_ytdlp_scorecard_pools_within_channel_groups_and_counts(tmp_path, monkeypatch):
    calls = []

    def list_channel(handle):
        calls.append(handle)
        return listing(handle, 10 if handle == "Large" else 1, handle == "Large")

    monkeypatch.setattr(sources, "list_channel", list_channel)
    spec = config(("Small", "Large"))
    spec["niches"].append({"niche": "Other niche", "channels": ["Small"]})
    result = niches.build(tmp_path, spec, source="ytdlp", now=NOW, fresh_days=0, skip_newest=0)
    niche = result["niches"][0]
    assert calls == ["Small", "Large"]
    assert niche["median_views"] == 550 and niche["active_channels"] == 1
    assert niche["median_outlier_rate"] == pytest.approx(1 / 3)
    assert niche["median_posting_rate"] == pytest.approx(30 / 29) and niche["demand_score"] == 5.48
    assert niche["n_hits"] == niche["n_misses"] == 20
    lift = next(row for row in niche["lifts"] if row["feature"] == "past_tense")
    assert lift == {"feature": "past_tense", "n_hits": 20, "n_misses": 20, "hit_count": 16, "miss_count": 8,
                    "hit_share": .8, "miss_share": .4, "lift": 2, "weak": False}
    assert all(row["views"] == 3000 and row["outlier"] == 3 for row in niche["top"])
    report = (tmp_path / "NICHES.md").read_text(encoding="utf-8")
    assert "past-tense story verb were 2x as common among 2x hits" in report
    assert all(row["title"] not in report for row in result["local"]["titles"])
    prior = niches.prior(tmp_path, "NFL stories", tmp_path / "prior.json")
    assert any("past-tense" in text for text in prior["guidance"])
    assert any("0.25x" in text for text in prior["guidance"])
    assert "title\"" not in json.dumps(prior)


def test_short_filter_unknown_dates_and_zero_baseline(tmp_path, monkeypatch):
    rows = [{"id": "url", "url": "https://www.youtube.com/shorts/url", "view_count": 0},
            {"id": "length", "duration": 180, "view_count": 0},
            {"id": "long", "duration": 181, "view_count": 100},
            {"id": "unknown", "view_count": 100}, {"id": "missing", "duration": 10},
            {"id": "bad", "duration": 10, "view_count": -1}, {"id": "bool", "duration": 10, "view_count": True}]
    rows += [rows[0]]
    monkeypatch.setattr(sources, "list_channel", lambda handle: rows)
    result = niches.build(tmp_path, config(), source="ytdlp", min_shorts=2, now=NOW, fresh_days=0, skip_newest=0)
    niche = result["niches"][0]
    summary = niche["channels"][0]
    assert summary["n"] == 2 and summary["median_views"] == niche["demand_score"] == 0
    assert summary["posting_rate"] is summary["newest_published"] is summary["outlier_rate"] is None
    assert niche["active_channels"] == niche["n_hits"] == niche["n_misses"] == 0
    assert all(row["lift"] is None for row in niche["lifts"])
    assert all(row["outlier"] is None for row in result["local"]["titles"])
    assert niches.published({"timestamp": NOW.timestamp()}) == NOW.isoformat()
    assert niches.published({"upload_date": "bad"}) is None


def test_listing_failure_is_recorded_without_upstream_text(tmp_path, monkeypatch):
    def fail(handle):
        raise ValueError(STORY)
    monkeypatch.setattr(sources, "list_channel", fail)
    result = niches.build(tmp_path, config(), source="ytdlp")
    assert result["niches"][0]["channels"][0]["reason"] == "listing failed (ValueError)"
    assert STORY not in (tmp_path / "NICHES.md").read_text(encoding="utf-8")


def test_channel_ids_are_case_sensitive(tmp_path, monkeypatch):
    calls = []
    def list_channel(handle):
        calls.append(handle)
        return listing(handle)
    monkeypatch.setattr(sources, "list_channel", list_channel)
    data = niches.build(tmp_path, config((CHANNEL, CHANNEL.upper())), source="ytdlp", now=NOW)
    assert calls == [CHANNEL, CHANNEL.upper()]
    assert data["niches"][0]["channels_listed"] == 2
    assert [row["channel_id"] for row in data["niches"][0]["channels"]] == calls


@pytest.mark.parametrize("field,value", [("rights", "licensed"), ("fit", "mid"), ("money", "medium"), ("notes", 3)])
def test_human_inputs_are_validated_before_fetch(tmp_path, metadata, field, value):
    data = config()
    data["niches"][0][field] = value
    with pytest.raises(ValueError, match=field):
        niches.build(tmp_path, data, fetch=metadata.fetch)
    assert not metadata.calls


def test_prior_guidance_thresholds_and_publication_allowlist(tmp_path):
    rows = [{"feature": feature, "hit_share": .5, "miss_share": .5, "lift": lift, "weak": weak,
             "title": STORY, "guidance": STORY} for feature, lift, weak in (
        ("has_number", 1.5, False), ("has_question", .67, False), ("has_quote", 1.499999, False),
        ("has_name", .670001, False), ("past_tense", 2, True), ("present_news", None, False),
        ("starts_lowercase", 0, False))]
    write_json(tmp_path / "niches.json", {"schema_version": 1, "local": {"titles": [STORY]}, "niches": [
        {"niche": "NFL stories", "n_hits": 10, "n_misses": 10, "lifts": rows, "notes": STORY}]})
    result = niches.prior(tmp_path, "NFL stories", tmp_path / "prior.json")
    assert set(result) == {"schema_version", "niche", "made_at", "n_hits", "n_misses", "lifts", "guidance"}
    assert len(result["guidance"]) == 3
    assert all(any(text in sentence for sentence in result["guidance"]) for text in ("1.5x", "0.67x", "0x"))
    assert all(set(row) == {"feature", "hit_share", "miss_share", "lift", "weak"} for row in result["lifts"])
    assert STORY not in json.dumps(result)
    with pytest.raises(ValueError, match="niche not found"):
        niches.prior(tmp_path, "Missing", tmp_path / "missing.json")
    saved = read_json(tmp_path / "niches.json")
    saved["niches"][0]["lifts"][0]["hit_share"] = STORY
    write_json(tmp_path / "niches.json", saved)
    with pytest.raises(ValueError, match="invalid title lift"):
        niches.prior(tmp_path, "NFL stories", tmp_path / "invalid.json")


def test_ytdlp_channel_ids_still_use_flat_metadata_listing(monkeypatch):
    monkeypatch.setattr(sources.doctor, "resolve_ytdlp_argv", lambda: ["yt-dlp"])
    def run(argv, **kwargs):
        assert argv[-1] == f"https://www.youtube.com/channel/{CHANNEL}/shorts"
        assert "--skip-download" in argv and "--flat-playlist" in argv and "--ignore-config" in argv
        assert not any("thumbnail" in arg or "audio" in arg for arg in argv)
        return subprocess.CompletedProcess(argv, 0, '{"id":"fixture","view_count":1}', "")
    monkeypatch.setattr(sources.proc, "run", run)
    assert sources.list_channel(CHANNEL) == [{"id": "fixture", "view_count": 1}]


def test_cli_watch_velocity_niches_prior_and_errors(tmp_path, metadata, monkeypatch, capsys):
    monkeypatch.setattr(feeds, "request", lambda url, **kwargs: metadata.fetch(url))
    channels = tmp_path / "channels.txt"
    channels.write_text("\ufeff@Fixture # comment\n", encoding="utf-8")
    out = tmp_path / "out"
    assert command.run(["watch", "--channels", str(channels), "--out", str(out)]) == 0
    assert json.loads(capsys.readouterr().out)["entries"] == 15
    assert command.run(["velocity", str(out)]) == 0
    assert len(json.loads(capsys.readouterr().out)["videos"]) == 15
    path = tmp_path / "niches-input.json"
    write_json(path, config())
    assert command.run(["niches", str(path), "--out", str(out), "--source", "feeds", "--min-shorts", "12"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["niches"][0]["channels_listed"] == 1 and "local" not in output
    assert command.run(["prior", str(out), "--niche", "NFL stories", "--out", str(out / "prior.json")]) == 0
    assert json.loads(capsys.readouterr().out)["schema_version"] == 1
    assert command.run(["niches", str(path), "--out", str(out), "--min-shorts", "0"]) == 2
    assert capsys.readouterr().out.startswith("zing playbook: ")
    assert command.run(["velocity", str(tmp_path / "missing")]) == 2
    assert capsys.readouterr().out.startswith("zing playbook: ")


def test_fresh_shorts_and_newest_undated_are_left_out():
    dated = [{"id": f"d{i}", "short": True, "views": 10, "published": (NOW - timedelta(days=i)).isoformat()} for i in range(6)]
    assert [row["id"] for row in niches.shorts(dated, "feeds", NOW)] == ["d3", "d4", "d5"]
    assert len(niches.shorts(dated, "feeds", NOW, fresh_days=0)) == 6
    undated = [{"id": f"u{i}", "duration": 30, "view_count": 10} for i in range(14)]
    assert [row["id"] for row in niches.shorts(undated, "ytdlp", NOW)] == ["u10", "u11", "u12", "u13"]
