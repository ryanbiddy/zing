"""Owner publishing with local kits and response fixtures."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

from myzing.channels import command, kit, outcomes, publish, queue, registry, tick, youtube
from myzing.factory import judge, pipeline

NOW = datetime(2026, 11, 5, 18, tzinfo=timezone.utc)
VIDEO = "abcdefghijk"
CHANNEL = "UC" + "a" * 22
SESSION = "https://www.googleapis.com/upload/youtube/v3/videos?upload_id=fixture-session"
RESPONSES = {
    "token": {"access_token": "fixture-access", "refresh_token": "fixture-refresh", "expires_in": 3600, "token_type": "Bearer"},
    "refresh": {"access_token": "fixture-new-access", "expires_in": 3600, "token_type": "Bearer"},
    "channels": {"items": [{"id": CHANNEL, "snippet": {"title": "Stories"}}]},
    "video": {"kind": "youtube#video", "id": VIDEO},
    "analytics": {"columnHeaders": [{"name": name} for name in
                   ("video", "views", "engagedViews", "averageViewPercentage", "averageViewDuration", "subscribersGained")],
                  "rows": [[VIDEO, 120, 90, 82.5, 24.2, 3]]},
}


class Response(io.BytesIO):
    def __init__(self, status=200, data=None, headers=None):
        super().__init__(json.dumps(data or {}).encode())
        self.status, self.headers = status, headers or {}


class Transport:
    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []

    def __call__(self, request, *, timeout):
        self.requests.append(request)
        assert timeout == 60
        assert self.responses, "unexpected request"
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response(request) if callable(response) else response


def reply(name, status=200):
    return Response(status, RESPONSES[name])


def session():
    return Response(headers={"Location": SESSION})


def headers(request):
    return {k.lower(): v for k, v in request.header_items()}


def token(**values):
    return {"client_id": "123-test.apps.googleusercontent.com", "client_secret": "fixture-client-secret",
            "project_id": "fixture-project", "access_token": "fixture-access", "refresh_token": "fixture-refresh",
            "expires_at": (NOW + timedelta(hours=2)).timestamp(), **values}


@pytest.fixture(autouse=True)
def local(tmp_path, monkeypatch):
    monkeypatch.setenv("ZING_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ZING_CHANNELS_HOME", str(tmp_path / "channels"))

    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")

    monkeypatch.setattr(youtube, "_open", refuse)
    monkeypatch.setattr(youtube, "HTTPServer", refuse)
    monkeypatch.setattr(youtube.webbrowser, "open", refuse)
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(kit, "_video", lambda src, dest: shutil.copyfile(src, dest) and None)


@pytest.fixture
def channel():
    channel = registry.create("Stories", "Player stories", publish={"youtube": "private"},
                              cadence={"timezone": "UTC-08:00"}, youtube={"channel_id": CHANNEL, "title": "Stories",
                              "connected_at": NOW.isoformat()})
    youtube.save_token(channel["slug"], token())
    return channel


def ready(channel, name="episode", *, slot=None, data=b"video", post=None, plan=None):
    slug = channel["slug"]
    project = registry.directory(slug) / "projects" / name
    pipeline._write(project / "factory.json", {**pipeline.SETTINGS, "channel": slug, "rights": "own"})
    pipeline._write(project / "ratings.json", {"clip01": {"v": "post"}})
    d = project / "clip01"
    pipeline._write(d / "post.json", {"youtube_title": "A story", "youtube": "The full story.", **(post or {})})
    pipeline._write(d / "plan.json", plan or {})
    (d / "clip.mp4").write_bytes(data)
    row = {"id": f"{name}/clip01", "project": str(project), "clip": "clip01", "status": "queued",
           "slot": (slot or NOW + timedelta(hours=1)).isoformat(), "title": "A story", "manual": True}
    queue.write(slug, [*queue.read(slug), row])
    assert kit.kit(slug)["made"] == 1
    return next(r for r in queue.read(slug) if r["id"] == row["id"])


def upload(channel, transport, **kwargs):
    return publish.upload(channel["slug"], opener=transport, now=NOW, **kwargs)


def browser_flow(opened, *, wrong_state=False):
    class Server:
        def __init__(self, address, handler):
            assert address == ("127.0.0.1", 0)
            self.server_address, self.handler = ("127.0.0.1", 43125), handler

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def handle_request(self):
            params = parse_qs(urlsplit(opened[-1]).query)
            handler = object.__new__(self.handler)
            handler.path = "/?" + urlencode({"state": "wrong-state" if wrong_state else params["state"][0], "code": "fixture-code"})
            handler.wfile = io.BytesIO()
            handler.send_response = lambda code: None
            handler.send_header = lambda *args: None
            handler.end_headers = lambda: None
            handler.log_message("%s", handler.path)
            handler.do_GET()
            assert b"fixture-code" not in handler.wfile.getvalue()

    return Server


def secret_file(tmp_path):
    path = tmp_path / "client.json"
    path.write_text(json.dumps({"installed": {k: token()[k] for k in ("client_id", "client_secret", "project_id")}}))
    return path


def test_connect_pkce_loopback_scopes_and_no_secrets(channel, tmp_path, capsys):
    opened = []
    transport = Transport(reply("token"), reply("channels"))
    result = youtube.connect(channel["slug"], secret_file(tmp_path), opener=transport, now=NOW,
                             open_browser=opened.append, server_factory=browser_flow(opened))
    params = parse_qs(urlsplit(opened[0]).query)
    exchange = parse_qs(transport.requests[0].data.decode())
    verifier = exchange["code_verifier"][0]
    assert 43 <= len(verifier) <= 128
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert params["code_challenge"] == [challenge] and params["code_challenge_method"] == ["S256"]
    assert params["access_type"] == ["offline"] and params["prompt"] == ["consent"]
    assert set(params["scope"][0].split()) == set(youtube.SCOPES)
    assert params["redirect_uri"] == exchange["redirect_uri"] == ["http://127.0.0.1:43125/"]
    assert exchange["code"] == ["fixture-code"] and exchange["grant_type"] == ["authorization_code"]
    assert transport.requests[0].full_url == youtube.TOKEN
    assert parse_qs(urlsplit(transport.requests[1].full_url).query) == {"part": ["snippet"], "mine": ["true"]}
    assert result == {"channel_id": CHANNEL, "title": "Stories", "connected_at": NOW.isoformat(timespec="seconds")}
    saved = (registry.directory(channel["slug"]) / "channel.json").read_text()
    output = capsys.readouterr()
    assert opened[0] in output.out
    for secret in ("fixture-access", "fixture-refresh", "fixture-client-secret", "fixture-code", verifier):
        assert secret not in saved + output.out + output.err
    assert youtube.load_token(channel["slug"])["client_secret"] == "fixture-client-secret"


def test_connect_wrong_state_refuses_exchange(channel, tmp_path, capsys):
    opened, transport = [], Transport()
    with pytest.raises(registry.ChannelError, match="state did not match"):
        youtube.connect(channel["slug"], secret_file(tmp_path), opener=transport, now=NOW,
                        open_browser=opened.append, server_factory=browser_flow(opened, wrong_state=True))
    assert not transport.requests
    assert "fixture-code" not in capsys.readouterr().out


@pytest.mark.parametrize("query", ["state=ok&state=ok&code=a", "state=ok&code=a&code=b", "state=ok&error=access_denied", "code=a"])
def test_callback_rejects_missing_or_ambiguous_values(query):
    with pytest.raises(registry.ChannelError):
        youtube._callback("/?" + query, "ok")


def test_token_storage_round_trip_and_disconnect(channel, monkeypatch):
    calls = []
    if os.name == "nt":
        protect = youtube._dpapi

        def dpapi(data, *, decrypt=False):
            calls.append(decrypt)
            return protect(data, decrypt=decrypt)

        monkeypatch.setattr(youtube, "_dpapi", dpapi)
    youtube.save_token(channel["slug"], token())
    assert youtube.load_token(channel["slug"]) == token()
    path = registry.directory(channel["slug"]) / "youtube.token"
    if os.name == "nt":
        assert calls == [False, True]
        assert b"fixture-client-secret" not in path.read_bytes() and b"fixture-refresh" not in path.read_bytes()
    else:
        assert path.stat().st_mode & 0o777 == 0o600
    assert youtube.disconnect(channel["slug"])["connected"] is False
    assert not path.exists() and "youtube" not in registry.load(channel["slug"])


@pytest.mark.parametrize("field,value", [("publish", {"youtube": "public"}), ("publish", []), ("publish", {"other": "off"}),
                                        ("youtube_daily_cap", -1), ("youtube_daily_cap", True), ("youtube_category", 22),
                                        ("youtube_category", "x"), ("youtube", {"client_secret": "hidden"})])
def test_publish_settings_are_validated(channel, field, value):
    with pytest.raises(registry.ChannelError):
        registry.validate({**channel, field: value})


def test_default_off_and_show_notice(capsys):
    channel = registry.create("Off", "Stories")
    assert channel["publish"] == {"youtube": "off"}
    assert channel["youtube_daily_cap"] == 6 and channel["youtube_category"] == "22"
    transport = Transport()
    assert upload(channel, transport)["uploaded"] == 0
    assert not transport.requests
    assert command.run(["show", channel["slug"]]) == 0
    assert "Google's API audit" in json.loads(capsys.readouterr().out)["youtube_notice"]


def test_dry_run_needs_no_token_and_sends_nothing(channel):
    row = ready(channel)
    (registry.directory(channel["slug"]) / "youtube.token").unlink()
    transport = Transport()
    result = upload(channel, transport, dry_run=True)
    assert result["uploads"] == [{"title": "A story", "privacy": "private", "publishAt": None,
                                  "file": str(Path(row["kit"]) / "video.mp4"), "size": 5}]
    assert not transport.requests and queue.read(channel["slug"])[0]["status"] == "kit"
    assert not (registry.home() / "youtube-quota.json").exists()
    assert not (registry.directory(channel["slug"]) / "outbox.jsonl").exists()


@pytest.mark.parametrize("policy,minutes,scheduled", [("private", 60, False), ("scheduled", 14, False),
                                                    ("scheduled", 15, True), ("scheduled", 90, True)])
def test_metadata_uses_kit_copy_and_policy(channel, policy, minutes, scheduled):
    channel.update(publish={"youtube": policy}, youtube_category="24")
    registry.save(channel)
    row = ready(channel, slot=NOW + timedelta(minutes=minutes))
    transport = Transport(session(), reply("video", 201))
    assert upload(channel, transport)["uploaded"] == 1
    request = transport.requests[0]
    metadata = json.loads(request.data)
    assert request.full_url == publish.UPLOAD
    assert metadata["snippet"] == {"title": "A story", "description": "The full story.\n", "categoryId": "24"}
    assert metadata["status"]["privacyStatus"] == "private"
    assert metadata["status"]["selfDeclaredMadeForKids"] is False
    assert metadata["status"]["containsSyntheticMedia"] is False
    assert ("publishAt" in metadata["status"]) == scheduled
    if scheduled:
        assert metadata["status"]["publishAt"] == (NOW + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")
    assert headers(request)["x-upload-content-length"] == "5" and headers(request)["x-upload-content-type"] == "video/mp4"
    posted = queue.read(channel["slug"])[0]
    assert posted["status"] == "posted" and posted["video_id"] == VIDEO
    assert posted["url"] == f"https://www.youtube.com/shorts/{VIDEO}" and posted["posted_at"] == NOW.isoformat()
    assert publish._outbox(channel["slug"])[0]["state"] == "done"
    assert upload(channel, Transport())["uploaded"] == 0


@pytest.mark.parametrize("post,plan,generated", [({"generated_media": True}, {}, True),
    ({}, {"visuals": {"photo": {"rights": "cleared", "generated": True}}}, True),
    ({"containsSyntheticMedia": True}, {}, True), ({"generated_media": False}, {"generated": "2026-11-05"}, False)])
def test_generated_media_disclosure(channel, post, plan, generated):
    ready(channel, post=post, plan=plan)
    transport = Transport(session(), reply("video"))
    upload(channel, transport)
    assert json.loads(transport.requests[0].data)["status"]["containsSyntheticMedia"] is generated


def test_slot_window_and_limit(channel):
    for name, hours in (("past", -1), ("soon", 1), ("later", 2), ("edge", 36), ("future", 37)):
        ready(channel, name, slot=NOW + timedelta(hours=hours))
    result = upload(channel, Transport(), dry_run=True, limit=2)
    assert len(result["uploads"]) == 2
    assert "soon" in result["uploads"][0]["file"] and "later" in result["uploads"][1]["file"]
    result = upload(channel, Transport(), dry_run=True, limit=10)
    assert len(result["uploads"]) == 3 and "edge" in result["uploads"][-1]["file"]


def test_refresh_on_401_once(channel):
    ready(channel)
    transport = Transport(Response(401), reply("refresh"), session(), reply("video"))
    assert upload(channel, transport)["uploaded"] == 1
    assert [r.full_url for r in transport.requests].count(youtube.TOKEN) == 1
    assert headers(transport.requests[2])["authorization"] == "Bearer fixture-new-access"
    assert youtube.load_token(channel["slug"])["refresh_token"] == "fixture-refresh"


def test_repeated_401_stops_without_refresh_loop(channel):
    ready(channel)
    transport = Transport(Response(401), reply("refresh"), Response(401))
    with pytest.raises(registry.ChannelError, match="reconnect with zing channels connect"):
        upload(channel, transport)
    assert len(transport.requests) == 3


def test_expired_token_refreshes_before_insert(channel):
    ready(channel)
    youtube.save_token(channel["slug"], token(expires_at=0))
    transport = Transport(reply("refresh"), session(), reply("video"))
    upload(channel, transport)
    assert transport.requests[0].full_url == youtube.TOKEN
    assert parse_qs(transport.requests[0].data.decode())["grant_type"] == ["refresh_token"]


@pytest.mark.parametrize("failure", [Response(400, {"error": "fixture-client-secret fixture-code"}),
                                      URLError("fixture-client-secret fixture-code")])
def test_refresh_failure_hides_secrets(channel, failure, capsys, monkeypatch):
    ready(channel)
    youtube.save_token(channel["slug"], token(expires_at=0))
    transport = Transport(failure)
    real = publish.upload
    monkeypatch.setattr(publish, "upload", lambda slug, **kw: real(slug, now=NOW, opener=transport, **kw))
    assert command.run(["upload", channel["slug"]]) == 2
    output = capsys.readouterr()
    assert "reconnect with zing channels connect" in output.err
    assert "fixture-client-secret" not in output.err + output.out and "fixture-code" not in output.err + output.out


def test_chunks_and_308_continue_from_acknowledged_offset(channel):
    data = b"a" * publish.CHUNK + b"b" * 2048
    row = ready(channel, data=data)

    def first_chunk(request):
        entry = publish._outbox(channel["slug"])[0]
        assert entry["state"] == "uploading" and entry["session_uri"] == SESSION and entry["kit"] == row["kit"]
        assert request.data == data[:publish.CHUNK]
        return Response(308, headers={"Range": f"bytes=0-{publish.CHUNK - 257}"})

    transport = Transport(session(), first_chunk, reply("video"))
    upload(channel, transport)
    assert len(transport.requests[1].data) == publish.CHUNK
    offset = publish.CHUNK - 256
    assert transport.requests[2].data == data[offset:]
    assert headers(transport.requests[2])["content-range"] == f"bytes {offset}-{len(data) - 1}/{len(data)}"


def test_crash_resumes_existing_session_without_second_insert(channel):
    data = b"a" * publish.CHUNK + b"b" * 1024
    ready(channel, data=data)
    first = Transport(session(), Response(308, headers={"Range": f"bytes=0-{publish.CHUNK - 1}"}), KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        upload(channel, first)
    assert publish._outbox(channel["slug"])[0]["state"] == "uploading"
    second = Transport(Response(308, headers={"Range": f"bytes=0-{publish.CHUNK - 1}"}), reply("video"))
    assert upload(channel, second)["uploaded"] == 1
    assert all(r.get_method() == "PUT" for r in second.requests)
    assert second.requests[0].data == b"" and headers(second.requests[0])["content-range"] == f"bytes */{len(data)}"
    assert second.requests[1].data == data[publish.CHUNK:]
    assert pipeline._read(registry.directory(channel["slug"]) / "youtube-quota.json")["uploads"] == 1


def test_off_preserves_an_unfinished_session_and_old_slots_can_resume(channel):
    ready(channel)
    with pytest.raises(KeyboardInterrupt):
        upload(channel, Transport(session(), KeyboardInterrupt()))
    rows = queue.read(channel["slug"])
    rows[0]["slot"] = (NOW - timedelta(hours=2)).isoformat()
    queue.write(channel["slug"], rows)
    channel["publish"]["youtube"] = "off"
    registry.save(channel)
    assert upload(channel, Transport())["uploaded"] == 0
    assert publish._outbox(channel["slug"])[0]["state"] == "uploading"
    channel["publish"]["youtube"] = "private"
    registry.save(channel)
    transport = Transport(Response(308), reply("video"))
    assert upload(channel, transport)["uploaded"] == 1
    assert all(r.get_method() == "PUT" for r in transport.requests)
    assert transport.requests[1].data == b"video"


def test_changed_resume_file_stops_without_requests(channel):
    row = ready(channel)
    with pytest.raises(KeyboardInterrupt):
        upload(channel, Transport(session(), KeyboardInterrupt()))
    (Path(row["kit"]) / "video.mp4").write_bytes(b"a changed video")
    with pytest.raises(registry.ChannelError, match="file changed"):
        upload(channel, Transport())


def test_queue_video_id_is_never_uploaded_again(channel):
    ready(channel)
    rows = queue.read(channel["slug"])
    rows[0]["video_id"] = VIDEO
    queue.write(channel["slug"], rows)
    assert upload(channel, Transport())["uploaded"] == 0


def test_connection_mismatch_stops_before_requests(channel):
    ready(channel)
    youtube.save_token(channel["slug"], token(channel_id="UC" + "b" * 22))
    with pytest.raises(registry.ChannelError, match="reconnect with zing channels connect"):
        upload(channel, Transport())


def test_completed_id_recovers_queue_without_any_request(channel, monkeypatch):
    ready(channel)
    write = queue.write

    def crash(*args):
        raise OSError("queue write interrupted")

    monkeypatch.setattr(queue, "write", crash)
    with pytest.raises(OSError, match="interrupted"):
        upload(channel, Transport(session(), reply("video")))
    entry = publish._outbox(channel["slug"])[0]
    assert entry["video_id"] == VIDEO and entry["state"] == "uploading"
    monkeypatch.setattr(queue, "write", write)
    (registry.directory(channel["slug"]) / "youtube.token").unlink()
    assert upload(channel, Transport())["uploaded"] == 1
    assert queue.read(channel["slug"])[0]["status"] == "posted"
    assert publish._outbox(channel["slug"])[0]["state"] == "done"


def test_5xx_backoff_leaves_session_for_next_run(channel):
    ready(channel)
    slept = []
    transport = Transport(session(), *[Response(503) for _ in range(4)])
    result = upload(channel, transport, sleep=slept.append)
    assert slept == [1, 4, 16] and "503" in result["stopped"]
    assert publish._outbox(channel["slug"])[0]["state"] == "uploading"
    recovery = Transport(reply("video"))
    assert upload(channel, recovery)["uploaded"] == 1
    assert headers(recovery.requests[0])["content-range"] == "bytes */5"


@pytest.mark.parametrize("reason", ["quotaExceeded", "uploadLimitExceeded"])
def test_quota_error_stops_run_and_is_recorded(channel, reason):
    ready(channel)
    ready(channel, "another")
    body = json.dumps({"error": {"errors": [{"reason": reason}]}}).encode()
    failure = HTTPError(publish.UPLOAD, 403, "Forbidden", {}, io.BytesIO(body))
    transport = Transport(failure)
    assert reason in upload(channel, transport)["stopped"]
    assert len(transport.requests) == 1
    assert pipeline._read(registry.directory(channel["slug"]) / "youtube-quota.json")["blocked"] == reason
    assert upload(channel, Transport())["stopped"] == reason


def test_channel_cap_and_project_cap_across_channels(channel):
    channel["youtube_daily_cap"] = 1
    registry.save(channel)
    ready(channel)
    ready(channel, "another")
    transport = Transport(session(), reply("video"))
    result = upload(channel, transport)
    assert result["uploaded"] == 1 and "channel cap" in result["stopped"]
    other = registry.create("Other", "Stories", publish={"youtube": "private"}, youtube=channel["youtube"])
    youtube.save_token(other["slug"], token())
    ready(other)
    ledger = registry.home() / "youtube-quota.json"
    pipeline._write(ledger, {"day": publish._day(NOW), "projects": {"fixture-project": {"uploads": 80}}})
    assert "project cap" in upload(other, Transport())["stopped"]
    saved = pipeline._read(ledger)
    assert saved["projects"]["fixture-project"]["uploads"] == 80
    youtube.save_token(other["slug"], token(project_id="another-project"))
    assert upload(other, Transport(session(), reply("video")))["uploaded"] == 1


@pytest.mark.parametrize("at,day", [("2026-11-05T07:59:59+00:00", "2026-11-04"), ("2026-11-05T08:00:00+00:00", "2026-11-05"),
                                    ("2026-07-05T06:59:59+00:00", "2026-07-04"), ("2026-07-05T07:00:00+00:00", "2026-07-05")])
def test_quota_uses_pacific_day_without_tzdata(at, day):
    assert publish._day(datetime.fromisoformat(at)) == day


def test_daily_caps_reset_on_the_next_pacific_day(channel):
    ready(channel)
    day = publish._day(NOW - timedelta(days=1))
    pipeline._write(registry.home() / "youtube-quota.json", {"day": day, "projects": {"fixture-project": {"uploads": 80}}})
    pipeline._write(registry.directory(channel["slug"]) / "youtube-quota.json", {"day": day, "uploads": 6, "blocked": "quotaExceeded"})
    assert upload(channel, Transport(session(), reply("video")))["uploaded"] == 1


@pytest.mark.parametrize("global_pause", [False, True])
def test_pause_stops_before_any_request(channel, global_pause):
    ready(channel)
    root = registry.home() if global_pause else registry.directory(channel["slug"])
    (root / "PAUSE").touch()
    transport = Transport()
    with pytest.raises(registry.ChannelError, match="paused"):
        upload(channel, transport)
    assert not transport.requests


def test_pause_after_session_stops_before_video_bytes(channel):
    ready(channel)

    def pause(request):
        (registry.home() / "PAUSE").touch()
        return session()

    transport = Transport(pause)
    with pytest.raises(registry.ChannelError, match="paused"):
        upload(channel, transport)
    assert len(transport.requests) == 1 and publish._outbox(channel["slug"])[0]["state"] == "uploading"


def test_gate_is_checked_again_after_kit(channel):
    row = ready(channel)
    pipeline._write(Path(row["project"]) / "ratings.json", {"clip01": {"v": "no"}})
    transport = Transport()
    result = upload(channel, transport)
    assert result["uploaded"] == 0 and result["blocked"][row["id"]] == ["The clip is rated No."]
    assert not transport.requests


def posted_rows(channel, n=1):
    project = registry.directory(channel["slug"]) / "projects" / "episode"
    rows = [{"id": f"episode/clip{i + 1:02d}", "clip": f"clip{i + 1:02d}", "project": str(project), "status": "posted",
             "slot": (NOW - timedelta(days=7)).isoformat(), "posted_at": (NOW - timedelta(days=7)).isoformat(),
             "video_id": VIDEO if i == 0 else f"{i:011d}", "url": f"https://www.youtube.com/shorts/{VIDEO if i == 0 else f'{i:011d}'}"}
            for i in range(n)]
    queue.write(channel["slug"], rows)
    return rows


def test_analytics_merges_metrics_and_preserves_age_windows(channel):
    rows = posted_rows(channel)
    outcomes.write(channel["slug"], [{"id": rows[0]["id"], "views_24h": 50, "masked": True, "studio_views": 70}])
    transport = Transport(reply("analytics"))
    assert publish.analytics(channel["slug"], opener=transport, now=NOW) == {"videos": 1, "matched": 1}
    params = parse_qs(urlsplit(transport.requests[0].full_url).query)
    assert params == {"ids": ["channel==MINE"], "dimensions": ["video"], "filters": ["video==" + VIDEO],
                      "metrics": ["views,engagedViews,averageViewPercentage,averageViewDuration,subscribersGained"],
                      "startDate": ["2026-10-29"], "endDate": ["2026-11-05"]}
    result = outcomes.read(channel["slug"])[0]
    assert {k: result[k] for k in publish.METRICS.values()} == {"views": 120, "engaged_views": 90, "avg_view_pct": 82.5,
                                                            "avg_view_duration": 24.2, "subs": 3}
    assert result["views_24h"] == 50 and result["masked"] is True and result["studio_views"] == 70
    assert not publish.analytics_due(channel["slug"], NOW)


def test_analytics_missing_metrics_and_missing_videos_stay_null(channel):
    posted_rows(channel, 2)
    transport = Transport(Response(data={"columnHeaders": [{"name": "video"}, {"name": "views"}, {"name": "engagedViews"}],
                                         "rows": [[VIDEO, 0, None]]}))
    publish.analytics(channel["slug"], opener=transport, now=NOW)
    rows = outcomes.read(channel["slug"])
    assert rows[0]["views"] == 0
    assert all(rows[0][k] is None for k in ("engaged_views", "avg_view_pct", "avg_view_duration", "subs"))
    assert all(rows[1][k] is None for k in publish.METRICS.values())


def test_analytics_batches_at_most_200_ids(channel):
    posted_rows(channel, 201)
    transport = Transport(Response(), Response())
    publish.analytics(channel["slug"], opener=transport, now=NOW)
    batches = [parse_qs(urlsplit(r.full_url).query)["filters"][0].removeprefix("video==").split(",") for r in transport.requests]
    assert [len(b) for b in batches] == [200, 1]
    assert len(outcomes.read(channel["slug"])) == 201


def test_analytics_failure_records_attempt_and_keeps_outcomes(channel):
    rows = posted_rows(channel)
    old = [{"id": rows[0]["id"], "video_id": VIDEO, "views": 40, "avg_view_pct": 80}]
    outcomes.write(channel["slug"], old)
    with pytest.raises(youtube.Error):
        publish.analytics(channel["slug"], opener=Transport(Response(400)), now=NOW)
    assert outcomes.read(channel["slug"]) == old
    assert not publish.analytics_due(channel["slug"], NOW + timedelta(hours=1))
    assert publish.analytics_due(channel["slug"], NOW + timedelta(days=1))
    assert pipeline._read(registry.directory(channel["slug"]) / "youtube-analytics.json")["complete"] is False


def test_tick_uploads_after_kit_and_analytics_once_a_day(channel, monkeypatch):
    calls = []
    monkeypatch.setattr(tick, "_advance", lambda *a: None)
    monkeypatch.setattr(queue, "build", lambda *a, **kw: {"added": 0, "blocked": {}})
    monkeypatch.setattr(kit, "kit", lambda *a, **kw: calls.append("kit") or {"made": 0, "blocked": {}})
    monkeypatch.setattr(publish, "upload", lambda *a, **kw: calls.append("upload") or {"uploaded": 0, "blocked": {}, "stopped": None})
    real = publish.analytics

    def analytics(slug, **kw):
        calls.append("analytics")
        return real(slug, opener=Transport(), **kw)

    monkeypatch.setattr(publish, "analytics", analytics)
    watch = lambda *a, **kw: {"found": 0, "started": 0}
    assert tick.run([channel["slug"]], watch_fn=watch, now=NOW)["exit_code"] == 0
    assert calls == ["kit", "upload", "analytics"]
    tick.run([channel["slug"]], watch_fn=watch, now=NOW + timedelta(hours=1))
    assert calls == ["kit", "upload", "analytics", "kit", "upload"]
    channel["publish"]["youtube"] = "off"
    registry.save(channel)
    tick.run([channel["slug"]], watch_fn=watch, now=NOW + timedelta(days=1))
    assert calls[-2:] == ["kit", "analytics"]


def test_cli_routes_new_flags(channel, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(publish, "upload", lambda slug, **kw: calls.append((slug, kw)) or {})
    assert command.run(["upload", channel["slug"], "--dry-run", "--limit", "4"]) == 0
    assert calls == [(channel["slug"], {"dry_run": True, "limit": 4})]
    monkeypatch.setattr(publish, "analytics", lambda slug: calls.append(slug) or {})
    assert command.run(["analytics", channel["slug"]]) == 0
    assert calls[-1] == channel["slug"]
    monkeypatch.setattr(youtube, "connect", lambda slug, path, **kw: calls.append((slug, path)) or {})
    assert command.run(["connect", channel["slug"], "--client-secret", "client.json"]) == 0
    assert calls[-1] == (channel["slug"], Path("client.json"))
    assert command.run(["disconnect", channel["slug"]]) == 0
