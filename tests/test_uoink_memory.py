"""P19 acceptance: fake HTTP only; no real peer, credentials or corpus."""

from __future__ import annotations

import json
import logging
import urllib.error
from pathlib import Path

import pytest

from conftest import FakeHTTPResponse, _guard_live_uoink
from myzing import cli, engagement, uoink_bridge
from myzing.project import api
from myzing.project.choices import choose_draft
from myzing.project.models import ProjectError
from myzing.project.references import resolve_reference, study_reference
from myzing.schemas import Breakdown, VideoMeta
from test_uoink_search_contract import search_body
from test_suite_peer import make_manifest

TOKEN = "p19-test-credential-only"


def response(body):
    return FakeHTTPResponse(json.dumps(body).encode("utf-8"))


def accepted(duplicates=0):
    return {"ok": True, "contract": "uoink.engagement.ingest", "version": 1,
            "data": {"submitted": 1, "accepted": 1 - duplicates,
                     "duplicates": duplicates, "rejected": []}}


@pytest.fixture
def project(tmp_path, monkeypatch, zing_workspace):
    clips = tmp_path / "clips"
    clips.mkdir()
    root = tmp_path / "project"
    api.init_project("uoink:ref-123", clips, root)
    (root / "drafts").mkdir()
    (root / "drafts" / "A.json").write_text('{"draft":"A","version":1}', encoding="utf-8")
    monkeypatch.setenv("UOINK_TOKEN", TOKEN)
    # Even a missed HTTP mock cannot discover the real peer.
    monkeypatch.setenv("UOINK_URL", "http://127.0.0.1:61983")
    monkeypatch.setattr(uoink_bridge.urllib.request, "urlopen",
                        lambda *a, **k: pytest.fail("Unexpected HTTP request; install a fake peer"))
    return root


@pytest.fixture
def handoff(tmp_path):
    media = tmp_path / "fake-peer-kept.mp4"
    media.write_bytes(b"synthetic kept media; study is mocked")
    return {"ok": True, "contract": "uoink.media.handoff", "version": 1,
            "operation": "resolve", "data": {
                "item_ref": "uoink://item/ref-123", "state": "available",
                "source_url": "https://example.test/saved-video",
                "media": {"path": str(media), "sha256": api.hash_file(media),
                          "byte_length": media.stat().st_size, "media_type": "video/mp4"},
                "provenance": {"kind": "uoink_sidecar", "sidecar_schema_version": 1, "field": "media_file"}}}


def serve(monkeypatch, body, calls):
    def request(req, **kwargs):
        assert ":5179" not in req.full_url
        assert TOKEN not in req.full_url
        calls.append(req)
        logging.getLogger("fake-peer").info("%s %s", req.method, req.full_url)
        return response(body)
    monkeypatch.setattr(uoink_bridge.urllib.request, "urlopen", request)


def test_resolve_keeps_path_hash_provenance_and_studies_offline(project, handoff, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    calls = []
    serve(monkeypatch, handoff, calls)
    before = sorted(p.relative_to(project).as_posix() for p in project.rglob("*"))
    result = resolve_reference(project)
    assert result.state == "resolved"
    assert result.path == handoff["data"]["media"]["path"]
    assert result.sha256 == handoff["data"]["media"]["sha256"]
    assert result.provenance == handoff["data"]["provenance"]
    assert sorted(p.relative_to(project).as_posix() for p in project.rglob("*")) == before
    assert api.load_project(project).reference.resolution == result
    assert calls[0].get_header("X-uoink-token") == TOKEN
    assert TOKEN not in caplog.text
    monkeypatch.setattr(uoink_bridge.urllib.request, "urlopen", lambda *a, **k: pytest.fail("study contacted peer"))
    from myzing.study import api as study_api, ingest
    monkeypatch.setattr(ingest, "_fetch", lambda *a, **k: pytest.fail("web refetch"))
    studied = []

    def study(source, **kwargs):
        studied.append(source)
        return Breakdown(meta=VideoMeta(source_url=source, platform="local"))

    monkeypatch.setattr(study_api, "study", study)
    attachment = study_reference(project)
    assert studied == [result.path]
    data = json.loads(Path(attachment["breakdown_path"]).read_text(encoding="utf-8"))
    assert data["provenance"]["project_reference"]["refetch"] is False
    assert attachment["reference_sha256"] == result.sha256
    assert api.load_project(project).reference.study == attachment


def test_offline_project_usable_and_file_override(project, monkeypatch, tmp_path):
    def down(*a, **k):
        raise urllib.error.URLError("offline " + TOKEN)
    monkeypatch.setattr(uoink_bridge.urllib.request, "urlopen", down)
    result = resolve_reference(project)
    assert result.state == "unresolved" and "no uoink helper" in result.reason
    assert TOKEN not in (project / "project.json").read_text()
    assert api.project_status(project)["reference"]["state"] == "unresolved"
    api.scan_project(project)
    from myzing.brief.api import save_brief
    from myzing.brief.models import Brief
    save_brief(project, Brief())
    fallback = tmp_path / "user.mp4"
    fallback.write_bytes(b"supplied file")
    resolved = resolve_reference(project, file=fallback)
    assert resolved.state == "resolved" and resolved.path == str(fallback)
    assert resolved.provenance["kind"] == "user_supplied_file"


@pytest.mark.parametrize("defect", ["hash", "length", "missing", "not_kept", "wrong_item"])
def test_refuses_bad_handoff(project, handoff, monkeypatch, defect):
    if defect == "hash":
        handoff["data"]["media"]["sha256"] = "0" * 64
    elif defect == "length":
        handoff["data"]["media"]["byte_length"] += 1
    elif defect in {"missing", "not_kept"}:
        handoff["data"].update(state=defect, media=None)
    else:
        handoff["data"]["item_ref"] = "uoink://item/wrong"
    serve(monkeypatch, handoff, [])
    result = resolve_reference(project)
    assert result.state == "unresolved" and result.path is None
    with pytest.raises(ProjectError, match="unresolved"):
        study_reference(project)


def test_changed_kept_media_never_reaches_study(project, handoff, monkeypatch):
    serve(monkeypatch, handoff, [])
    resolve_reference(project)
    Path(handoff["data"]["media"]["path"]).write_bytes(b"changed")
    with pytest.raises(ProjectError, match="hash/size mismatch"):
        study_reference(project)
    assert api.load_project(project).reference.state == "unresolved"


def test_real_ingest_replaces_same_length_stale_cache_without_fetch(project, handoff, monkeypatch, zing_workspace):
    from myzing import storage
    from myzing.study import ingest
    from test_study_api import wire_measurement_stages_only

    serve(monkeypatch, handoff, [])
    resolved = resolve_reference(project)
    wire_measurement_stages_only(monkeypatch)
    monkeypatch.setattr(ingest, "_fetch", lambda *a, **k: pytest.fail("web refetch"))
    monkeypatch.setattr(ingest, "probe", lambda p: {
        "streams": [{"codec_type": "video", "codec_name": "h264", "width": 360, "height": 640,
                     "avg_frame_rate": "30/1", "pix_fmt": "yuv420p"}], "format": {"duration": "12"}})
    monkeypatch.setattr(ingest, "_needs_normalize", lambda v: (False, ""))
    monkeypatch.setattr(ingest, "_check_frame_timing", lambda *a: (False, ""))
    with storage.use_workspace(zing_workspace):
        slug = storage.slug_for(resolved.path)
        storage.breakdown_dir(slug).mkdir(parents=True)
        cached = storage.media_target(slug, ".mp4")
    cached.write_bytes(b"x" * resolved.byte_length)
    attachment = study_reference(project)
    assert api.hash_file(cached) == resolved.sha256
    data = json.loads(Path(attachment["breakdown_path"]).read_text())
    assert data["meta"]["duration"] == 12
    assert data["provenance"]["project_reference"]["refetch"] is False


def test_reference_mutating_during_study_invalidates_attachment(project, handoff, monkeypatch):
    from myzing.study import api as study_api

    serve(monkeypatch, handoff, [])
    resolve_reference(project)

    def changed(source, **kwargs):
        Path(source).write_bytes(b"changed during study")
        return Breakdown(meta=VideoMeta(source_url=source, platform="local"))

    monkeypatch.setattr(study_api, "study", changed)
    with pytest.raises(ProjectError, match="hash/size mismatch"):
        study_reference(project)
    ref = api.load_project(project).reference
    assert ref.state == "unresolved" and ref.study is None


def test_search_lists_never_selects(project, monkeypatch, capsys, caplog):
    caplog.set_level(logging.INFO)
    before = (project / "project.json").read_bytes()
    calls = []
    manifest = make_manifest(capabilities=[uoink_bridge.SEARCH_CAPABILITY])
    candidates = [{"item_ref": "uoink://item/one", "title": "First", "source_url": None},
                  {"item_ref": "uoink://item/two", "title": "Second", "source_url": "https://example.test/two"}]

    def answer(req, **kwargs):
        assert TOKEN not in req.full_url and ":5179" not in req.full_url
        calls.append(req)
        logging.info("request %s", req.full_url)
        if req.full_url.endswith("suite-service.json"):
            return response(manifest)
        assert req.method == "GET" and req.data is None
        assert req.full_url == "http://127.0.0.1:61983/api/corpus/v1/search?q=soft+cuts&limit=20"
        assert req.get_header("X-uoink-token") == TOKEN
        body = search_body()
        for item, candidate in zip(body["data"]["items"], candidates):
            item.update(id=candidate["item_ref"].rsplit("/", 1)[-1],
                        title=candidate["title"], source_url=candidate["source_url"])
        return response(body)

    monkeypatch.setattr(uoink_bridge.urllib.request, "urlopen", answer)
    assert cli.main(["project", "find-reference", "soft cuts"]) == 0
    output = capsys.readouterr().out
    assert "First" in output and "Second" in output and "No reference selected" in output
    assert (project / "project.json").read_bytes() == before
    assert not (project / "choices.json").exists()
    assert len(calls) == 2 and TOKEN not in caplog.text + output


def test_search_missing_capability_does_not_guess_endpoint(project, monkeypatch, capsys):
    calls = []
    serve(monkeypatch, make_manifest(capabilities=["uoink.media.handoff/1"]), calls)
    assert cli.main(["project", "find-reference", "query"]) == 1
    assert "does not advertise" in capsys.readouterr().out
    assert len(calls) == 1 and calls[0].full_url.endswith("suite-service.json")


@pytest.mark.parametrize("failure", ["404", "shape", "version", "item", "token"])
def test_search_refuses_unsupported_or_invalid_responses(project, monkeypatch, failure):
    body = search_body()
    if failure == "shape":
        body["data"]["selected"] = "a"
    elif failure == "version":
        body["version"] = 2
    elif failure == "item":
        body["data"]["items"][0]["id"] = "../private"
    elif failure == "token":
        body["data"]["items"][0]["title"] = TOKEN

    def answer(req, **kwargs):
        if req.full_url.endswith("suite-service.json"):
            return response(make_manifest(capabilities=[uoink_bridge.SEARCH_CAPABILITY]))
        if failure == "404":
            raise urllib.error.HTTPError(req.full_url, 404, "missing", {}, None)
        return response(body)

    monkeypatch.setattr(uoink_bridge.urllib.request, "urlopen", answer)
    result = uoink_bridge.search_references("cuts")
    assert result["ok"] is False
    assert TOKEN not in json.dumps(result)


def test_search_unconfigured_never_contacts_peer(project, monkeypatch):
    monkeypatch.delenv("UOINK_TOKEN")
    assert uoink_bridge.search_references("cuts")["code"] == "unconfigured"


def test_search_never_puts_a_pasted_credential_in_the_url(project, monkeypatch):
    calls = []
    monkeypatch.setattr(uoink_bridge.urllib.request, "urlopen",
                        lambda req, **kwargs: calls.append(req))
    result = uoink_bridge.search_references("soft cuts " + TOKEN)
    assert result["code"] == "invalid_query"
    assert TOKEN not in json.dumps(result)
    assert calls == []


def test_choice_local_then_opt_in_and_retry_same_event(project, monkeypatch, caplog, capsys, zing_workspace):
    caplog.set_level(logging.INFO)
    assert cli.main(["plan", "choose", str(project), "--draft", "A", "--note", "Better opening", "--json"]) == 0
    local = json.loads(capsys.readouterr().out)["receipt"]
    assert local["delivery"] == {"state": "local_only"}
    assert local["notes"] == ["Better opening"]
    assert local["draft_sha256"] == api.hash_file(project / "drafts" / "A.json")
    assert not (zing_workspace / "engagement.json").exists()
    events = []

    def retry(req, **kwargs):
        assert TOKEN not in req.full_url and ":5179" not in req.full_url
        assert req.get_header("X-uoink-token") == TOKEN
        event = json.loads(req.data)["events"][0]
        events.append(event)
        # The local receipt must exist even if delivery dies after acceptance.
        assert json.loads((project / "choices.json").read_text())["selected"] == event["event_id"]
        logging.info("POST %s", req.full_url)
        if len(events) == 1:
            raise urllib.error.URLError("response lost " + TOKEN)
        return response(accepted(duplicates=1))

    monkeypatch.setattr(engagement.urllib.request, "urlopen", retry)
    pending = choose_draft(project, "A", share_choice=True)["receipt"]
    assert pending["delivery"]["state"] == "spooled"
    assert choose_draft(project, "A")["receipt"]["event_id"] == local["event_id"]
    assert len(events) == 1  # no-share never retries delivery
    done = choose_draft(project, "A", share_choice=True)["receipt"]
    assert done["delivery"]["duplicates"] == 1
    assert events[0] == events[1]
    assert events[0]["event_id"] == local["event_id"]
    assert events[0]["event_type"] == "cite"
    assert set(events[0]) == engagement._EVENT_KEYS
    choose_draft(project, "A", share_choice=True)
    assert len(events) == 2
    assert TOKEN not in caplog.text + (project / "choices.json").read_text() + (zing_workspace / "engagement.json").read_text()


def test_changed_draft_new_event_and_missing_draft_refused(project):
    first = choose_draft(project, "A")["receipt"]
    (project / "drafts" / "A.json").write_text('{"draft":"A","revision":2}')
    second = choose_draft(project, "A")["receipt"]
    assert first["event_id"] != second["event_id"]
    with pytest.raises(ProjectError, match="missing"):
        choose_draft(project, "B")
    assert len(json.loads((project / "choices.json").read_text())["receipts"]) == 2


def test_receipt_survives_spool_failure(project, monkeypatch):
    def failed(*a, **k):
        raise engagement.EngagementStorageError("disk unavailable")
    monkeypatch.setattr(engagement, "record_choice", failed)
    result = choose_draft(project, "A", share_choice=True)
    assert result["receipt"]["delivery"]["state"] == "pending"
    assert json.loads((project / "choices.json").read_text())["selected"] == result["receipt"]["event_id"]


def test_corrupt_choice_memory_is_not_overwritten(project):
    choose_draft(project, "A")
    path = project / "choices.json"
    state = json.loads(path.read_text())
    state["receipts"][state["selected"]]["notes"] = None
    path.write_text(json.dumps(state))
    before = path.read_bytes()
    with pytest.raises(ProjectError, match="Choice memory is invalid"):
        choose_draft(project, "A", note="new note")
    assert path.read_bytes() == before


def test_peer_rejection_redacts_escaped_credentials(project, monkeypatch, zing_workspace, caplog):
    secret = 'synthetic-secret-with-"quote'
    monkeypatch.setenv("UOINK_TOKEN", secret)

    def reject(req, **kwargs):
        assert secret not in req.full_url
        event_id = json.loads(req.data)["events"][0]["event_id"]
        return response({"ok": True, "contract": "uoink.engagement.ingest", "version": 1,
                         "data": {"submitted": 1, "accepted": 0, "duplicates": 0, "rejected": [
                             {"event_id": event_id, "code": "invalid_event", "message": secret, "retryable": False}]}})

    monkeypatch.setattr(engagement.urllib.request, "urlopen", reject)
    result = choose_draft(project, "A", share_choice=True)
    assert result["receipt"]["delivery"]["state"] == "rejected"
    assert secret not in caplog.text + str(json.loads((zing_workspace / "engagement.json").read_text()))


def test_echoed_token_and_credential_url_not_logged(project, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    body = {"ok": False, "contract": "uoink.media.handoff", "version": 1, "operation": "resolve",
            "error": {"code": "not_found", "message": "bad " + TOKEN}}
    calls = []
    serve(monkeypatch, body, calls)
    result = resolve_reference(project)
    assert TOKEN not in result.reason + caplog.text + (project / "project.json").read_text()
    monkeypatch.setenv("UOINK_URL", "http://127.0.0.1:61983/" + TOKEN)
    resolve_reference(project)
    assert len(calls) == 1
    assert TOKEN not in caplog.text + (project / "project.json").read_text()


def test_auth_header_is_not_forwarded_on_redirect(project, handoff, monkeypatch):
    calls = []
    serve(monkeypatch, handoff, calls)
    resolve_reference(project)
    redirected = uoink_bridge.urllib.request.HTTPRedirectHandler().redirect_request(
        calls[0], None, 302, "redirect", {}, "http://127.0.0.1:61984/elsewhere")
    assert redirected.get_header("X-uoink-token") is None


@pytest.mark.parametrize("event,args", [
    ("socket.connect", (None, ("127.0.0.1", 5179))),
    ("open", ("E:/Uoink/secret", "r", 0)),
    ("os.scandir", ("C:/Users/ExampleUser/AppData/Local/Uoink",)),
])
def test_live_uoink_guard_is_fail_closed(event, args):
    # Invoke the guard directly: no attempted real network/file operation.
    with pytest.raises(AssertionError):
        _guard_live_uoink(event, args)
