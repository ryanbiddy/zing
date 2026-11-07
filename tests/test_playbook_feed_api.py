"""Exact feed fallback with fake API responses and no external calls."""
from __future__ import annotations

import json
import traceback
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone

import pytest

from conftest import FakeHTTPResponse
from myzing import doctor
from myzing.factory import judge
from myzing.playbook import feeds

CHANNEL = "UC" + "a" * 22
KEY = "fixture-youtube-key"
NOW = datetime(2026, 11, 6, tzinfo=timezone.utc)
FIELDS = {"id", "title", "published", "views", "short", "channel_id", "channel_title", "approximate"}


def refuse(*args, **kwargs):
    raise AssertionError("unmocked external operation")


@pytest.fixture(autouse=True)
def offline(tmp_path, monkeypatch):
    monkeypatch.setenv("ZING_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.setattr(feeds.urls, "open_no_redirect", refuse)
    monkeypatch.setattr(feeds.urllib.request, "urlopen", refuse)
    monkeypatch.setattr(feeds.urllib.request, "build_opener", refuse)
    monkeypatch.setattr(feeds, "listing", refuse)
    monkeypatch.setattr(judge.subprocess, "run", refuse)


def video(ident, days=1, views="12345"):
    return {"id": ident, "snippet": {"title": "Creator update", "channelTitle": "Fixture channel",
                                    "publishedAt": (NOW - timedelta(days=days)).isoformat()},
            "statistics": {"viewCount": views}}


def playlist(*ids):
    return {"items": [{"contentDetails": {"videoId": ident}} for ident in ids]}


def error(code, reason, body=None):
    body = body if body is not None else json.dumps({"error": {"message": KEY, "errors": [{"reason": reason}]}}).encode()
    return urllib.error.HTTPError("https://www.googleapis.com/youtube/v3/playlistItems", code, KEY, {},
                                  FakeHTTPResponse(body))


class Opener:
    def __init__(self):
        self.calls = []
        self.responses = {"UUSH": playlist("short000001"), "UULF": playlist("video000001"),
                          "videos": {"items": [video("video000001", days=3, views="88901"), video("short000001")]}}

    def __call__(self, request, *, timeout):
        self.calls.append((request, timeout))
        parsed = urllib.parse.urlsplit(request.full_url)
        params = urllib.parse.parse_qs(parsed.query)
        name = params["playlistId"][0][:4] if parsed.path.endswith("/playlistItems") else "videos"
        value = self.responses[name]
        if isinstance(value, Exception):
            raise value
        return FakeHTTPResponse(value if isinstance(value, bytes) else json.dumps(value).encode())


def outage(*args, **kwargs):
    raise urllib.error.HTTPError("https://www.youtube.com/feeds/videos.xml", 404, "missing", {}, None)


def log(root):
    row, = [json.loads(line) for line in (root / "feed-fallbacks.jsonl").read_text(encoding="utf-8").splitlines()]
    return row


def test_rss_404_uses_exact_api_rows_and_header_only_key(tmp_path, monkeypatch):
    opener = Opener()
    monkeypatch.setenv("YOUTUBE_API_KEY", "  " + KEY + "  ")
    monkeypatch.setattr(feeds, "request", outage)
    monkeypatch.setattr(feeds.urls, "open_no_redirect", opener)
    rows = feeds.feed(CHANNEL, root=tmp_path)
    assert [row["id"] for row in rows] == ["short000001", "video000001"]
    assert all(set(row) == FIELDS and row["approximate"] is False for row in rows)
    assert rows[0] == {"id": "short000001", "title": "Creator update", "published": "2026-11-05T00:00:00+00:00",
                       "views": 12345, "short": True, "channel_id": CHANNEL,
                       "channel_title": "Fixture channel", "approximate": False}
    assert rows[1]["views"] == 88901 and rows[1]["short"] is False
    assert len(opener.calls) == 3
    for request, timeout in opener.calls:
        assert timeout == 30
        assert request.full_url.startswith("https://www.googleapis.com/youtube/v3/")
        assert KEY not in request.full_url and request.data is None
        assert request.headers == {}
        assert request.unredirected_hdrs == {"X-goog-api-key": KEY}
    for prefix, (request, _) in zip(("UUSH", "UULF"), opener.calls):
        assert urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query) == {
            "part": ["contentDetails,snippet"], "maxResults": ["15"], "playlistId": [prefix + CHANNEL[2:]]}
    request = opener.calls[-1][0]
    assert urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query) == {
        "part": ["snippet,statistics"], "id": ["short000001,video000001"]}
    assert log(tmp_path)["source"] == "api" and log(tmp_path)["rows"] == 2
    assert "api_error" not in log(tmp_path)
    assert KEY not in (tmp_path / "feed-fallbacks.jsonl").read_text(encoding="utf-8")


@pytest.mark.parametrize("prefix", ["UUSH", "UULF"])
def test_missing_playlist_is_empty(prefix):
    opener = Opener()
    missing = error(404, "playlistNotFound")
    opener.responses[prefix] = missing
    rows = feeds.api_listing(CHANNEL, key=KEY, opener=opener, now=NOW)
    assert len(rows) == 1 and rows[0]["short"] is (prefix == "UULF")
    assert rows[0]["approximate"] is False
    assert len(opener.calls) == 3 and missing.closed


def test_empty_playlists_need_no_video_request():
    opener = Opener()
    opener.responses.update(UUSH=playlist(), UULF=playlist())
    assert feeds.api_listing(CHANNEL, key=KEY, opener=opener, now=NOW) == []
    assert len(opener.calls) == 2


@pytest.mark.parametrize("code,reason", [(403, "quotaExceeded"), (403, "keyInvalid"),
                                         (403, "accessNotConfigured"), (400, "badRequest")])
def test_api_refusal_is_plain_and_falls_back(tmp_path, monkeypatch, code, reason):
    opener = Opener()
    opener.responses["UUSH"] = error(code, reason)
    with pytest.raises(ValueError) as caught:
        feeds.api_listing(CHANNEL, key=KEY, opener=opener, now=NOW)
    message = "YouTube Data API refused the request: " + reason
    assert str(caught.value) == message
    assert KEY not in "".join(traceback.format_exception(caught.value))
    monkeypatch.setenv("YOUTUBE_API_KEY", KEY)
    monkeypatch.setattr(feeds, "request", outage)
    monkeypatch.setattr(feeds.urls, "open_no_redirect", opener)
    calls = []
    expected = [{"id": "video000001", "short": False, "approximate": True}]
    monkeypatch.setattr(feeds, "listing", lambda ident, **kwargs: calls.append((ident, kwargs)) or expected)
    opener.responses["UUSH"] = error(code, reason)
    assert feeds.feed(CHANNEL, root=tmp_path, watch_only=False) == expected
    assert calls == [(CHANNEL, {"watch_only": False})]
    assert log(tmp_path)["source"] == "ytdlp" and log(tmp_path)["api_error"] == message
    assert KEY not in (tmp_path / "feed-fallbacks.jsonl").read_text(encoding="utf-8")


@pytest.mark.parametrize("failure", [ValueError(KEY), OSError(KEY)])
def test_injected_api_errors_redact_key(tmp_path, monkeypatch, failure):
    monkeypatch.setenv("YOUTUBE_API_KEY", KEY)
    monkeypatch.setattr(feeds, "listing", lambda *args, **kwargs: [])

    def api(ident):
        assert ident == CHANNEL
        raise failure

    assert feeds.feed(CHANNEL, outage, root=tmp_path, api=api) == []
    assert log(tmp_path)["source"] == "ytdlp"
    assert log(tmp_path)["api_error"] == "[redacted]"


@pytest.mark.parametrize("key", [None, "", " \t "])
def test_no_key_never_calls_api(tmp_path, monkeypatch, key):
    if key is not None:
        monkeypatch.setenv("YOUTUBE_API_KEY", key)
    monkeypatch.setattr(feeds, "request", outage)
    monkeypatch.setattr(feeds, "listing", lambda *args, **kwargs: [])
    assert feeds.feed(CHANNEL, root=tmp_path, api=refuse) == []
    assert "api_error" not in log(tmp_path)


def test_watch_only_queries_long_playlist(tmp_path, monkeypatch):
    opener = Opener()
    monkeypatch.setenv("YOUTUBE_API_KEY", KEY)
    monkeypatch.setattr(feeds, "request", outage)
    monkeypatch.setattr(feeds.urls, "open_no_redirect", opener)
    rows = feeds.feed(CHANNEL, root=tmp_path, watch_only=True)
    assert len(rows) == 1 and rows[0]["short"] is False
    assert len(opener.calls) == 2
    assert all("UUSH" not in request.full_url for request, _ in opener.calls)
    assert "UULF" + CHANNEL[2:] in opener.calls[0][0].full_url


def test_injected_fetch_requires_explicit_api_or_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", KEY)
    with pytest.raises(urllib.error.HTTPError):
        feeds.feed(CHANNEL, outage, root=tmp_path)
    assert not (tmp_path / "feed-fallbacks.jsonl").exists()
    calls = []
    rows = [{"id": "short000001", "short": True}, {"id": "video000001", "short": False}]
    assert feeds.feed(CHANNEL, outage, root=tmp_path, watch_only=True,
                      api=lambda ident: calls.append(ident) or rows) == rows[1:]
    assert calls == [CHANNEL] and log(tmp_path)["source"] == "api" and log(tmp_path)["rows"] == 1


def test_api_runs_before_an_injected_fallback(tmp_path, monkeypatch):
    # platform news always passes fallback=feeds.listing; the key must still come first
    monkeypatch.setenv("YOUTUBE_API_KEY", KEY)
    rows = [{"id": "a", "short": True}]
    assert feeds.feed(CHANNEL, outage, root=tmp_path, api=lambda ident: rows, fallback=refuse) == rows
    assert log(tmp_path)["source"] == "api"


def test_failed_api_hands_over_to_the_injected_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", KEY)
    calls = []

    def broken(ident):
        raise ValueError("YouTube Data API refused the request: quotaExceeded")

    assert feeds.feed(CHANNEL, outage, root=tmp_path, api=broken,
                      fallback=lambda ident: calls.append(ident) or []) == []
    assert calls == [CHANNEL]
    assert log(tmp_path)["source"] == "ytdlp" and "quotaExceeded" in log(tmp_path)["api_error"]


def test_truncated_chunked_api_body_falls_back(tmp_path, monkeypatch):
    import http.client

    class Cut:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, n):
            raise http.client.IncompleteRead(b'{"items": [', 100)

    monkeypatch.setenv("YOUTUBE_API_KEY", KEY)
    monkeypatch.setattr(feeds, "request", outage)
    monkeypatch.setattr(feeds.urls, "open_no_redirect", lambda request, timeout: Cut())
    monkeypatch.setattr(feeds, "listing", lambda *args, **kwargs: [])
    assert feeds.feed(CHANNEL, root=tmp_path) == []
    row = log(tmp_path)
    assert row["source"] == "ytdlp" and row["api_error"] == "YouTube Data API request failed"


@pytest.mark.parametrize("code", [400, 403, 429])
def test_other_rss_errors_do_not_call_api(tmp_path, monkeypatch, code):
    monkeypatch.setenv("YOUTUBE_API_KEY", KEY)

    def fetch(url):
        raise urllib.error.HTTPError(url, code, "failed", {}, None)

    with pytest.raises(urllib.error.HTTPError):
        feeds.feed(CHANNEL, fetch, root=tmp_path, api=refuse)
    assert not (tmp_path / "feed-fallbacks.jsonl").exists()


@pytest.mark.parametrize("body", [b"not JSON", b"\xff", b"[]", b"{}", b'{"items":null}', b'{"items":[null]}',
                                 b'{"items":[{}]}', b'{"items":[{"contentDetails":null}]}'])
def test_malformed_responses_raise_value_error(body):
    opener = Opener()
    opener.responses["UUSH"] = body
    with pytest.raises(ValueError, match="YouTube Data API"):
        feeds.api_listing(CHANNEL, key=KEY, opener=opener, now=NOW)


@pytest.mark.parametrize("field", ["snippet", "statistics", "title", "channelTitle"])
def test_missing_video_fields_raise_value_error(field):
    opener = Opener()
    row = opener.responses["videos"]["items"][0]
    del (row if field in ("snippet", "statistics") else row["snippet"])[field]
    with pytest.raises(ValueError, match="missing fields"):
        feeds.api_listing(CHANNEL, key=KEY, opener=opener, now=NOW)


def test_oversize_response_is_bounded():
    reads = []

    class Response(FakeHTTPResponse):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    response = Response(b" " * (2 * 1024 * 1024 + 20))
    with pytest.raises(ValueError, match="exceeds 2 MB"):
        feeds.api_listing(CHANNEL, key=KEY, opener=lambda request, **kwargs: response)
    assert reads == [2 * 1024 * 1024 + 1]


@pytest.mark.parametrize("failure", [OSError(KEY), ValueError(KEY), error(302, "redirect", body=b"bad JSON"),
                                    error(403, KEY)])
def test_transport_errors_never_expose_key(failure):
    opener = Opener()
    opener.responses["UUSH"] = failure
    with pytest.raises(ValueError) as caught:
        feeds.api_listing(CHANNEL, key=KEY, opener=opener, now=NOW)
    assert KEY not in "".join(traceback.format_exception(caught.value))
    assert len(opener.calls) == 1


@pytest.mark.parametrize("encoded", [False, True])
def test_credential_echo_cannot_enter_a_video_url(encoded):
    opener = Opener()
    body = json.dumps(playlist(KEY))
    if encoded:
        body = body.replace(KEY, "".join(f"\\u{ord(char):04x}" for char in KEY))
    opener.responses["UUSH"] = body.encode()
    with pytest.raises(ValueError) as caught:
        feeds.api_listing(CHANNEL, key=KEY, opener=opener, now=NOW)
    assert KEY not in str(caught.value)
    assert len(opener.calls) == 1 and KEY not in opener.calls[0][0].full_url


def test_invalid_rows_are_dropped_and_results_sort_newest_first():
    opener = Opener()
    rows = [video(f"video{i:06d}", days=i) for i in range(12)]
    for row, views in zip(rows[1:6], (None, 100, "-1", "1.5", "１２")):
        row["statistics"]["viewCount"] = views
    for row, stamp in zip(rows[6:9], (None, "bad date", (NOW + timedelta(days=1)).isoformat())):
        row["snippet"]["publishedAt"] = stamp
    rows[9].pop("id")
    opener.responses.update(UUSH=playlist(None, "", "bad/id"), UULF=playlist(*(f"video{i:06d}" for i in range(12))),
                            videos={"items": list(reversed(rows))})
    found = feeds.api_listing(CHANNEL, key=KEY, opener=opener, now=NOW)
    assert [row["id"] for row in found] == ["video000000", "video000010", "video000011"]
    assert all(row["views"] == 12345 and row["approximate"] is False for row in found)


def test_each_playlist_and_single_batch_are_bounded():
    opener = Opener()
    shorts = [video(f"short{i:06d}", days=i) for i in range(20)]
    videos = [video(f"video{i:06d}", days=i) for i in range(20)]
    opener.responses.update(UUSH=playlist(*(row["id"] for row in shorts)), UULF=playlist(*(row["id"] for row in videos)),
                            videos={"items": list(reversed(videos + shorts))})
    rows = feeds.api_listing(CHANNEL, key=KEY, opener=opener, now=NOW)
    assert len(rows) == 30 and sum(row["short"] for row in rows) == 15
    assert [row["published"] for row in rows] == sorted((row["published"] for row in rows), reverse=True)
    assert len(opener.calls) == 3
    ids = urllib.parse.parse_qs(urllib.parse.urlsplit(opener.calls[-1][0].full_url).query)["id"][0].split(",")
    assert len(ids) == len(set(ids)) == 30


@pytest.mark.parametrize("key", [None, "", " \t", KEY])
def test_doctor_reports_presence_without_probing_or_printing_key(monkeypatch, capsys, key):
    from myzing.study import speech_models

    if key is not None:
        monkeypatch.setenv("YOUTUBE_API_KEY", key)
    for name in vars(doctor):
        if name.startswith("check_"):
            monkeypatch.setattr(doctor, name, lambda *args: doctor.Check("fixture", doctor.OPTIONAL, True, "ready"))
    monkeypatch.setattr(doctor, "_next_step", lambda: "")
    monkeypatch.setattr(speech_models, "print_inventory", lambda: None)
    present = bool(key and key.strip())
    assert doctor.run([]) == 0
    output = capsys.readouterr().out
    expected = "set" if present else "not set (optional; used when YouTube RSS is down)"
    assert "YouTube Data API key: " + expected in output and KEY not in output
    assert doctor.run(["--json"]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["ok"] is True and KEY not in output
