"""POLISH1 item 6: pushed notes use the best real title, not 'media'."""

from __future__ import annotations

import copy
import json
import logging
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import FakeHTTPResponse
from myzing import storage, uoink_bridge
from myzing.project import api
from myzing.project.references import resolve_reference, study_reference
from myzing.schemas import Breakdown, VideoMeta
from test_suite_peer import make_manifest
from test_uoink_search_contract import provider

TOKEN = "polish1-test-credential-only"
ITEM = "video-contract"  # the vendored corpus.read/1 provider fixture's item


def respond(body, status=200):
    return FakeHTTPResponse(json.dumps(body).encode("utf-8"))


@pytest.fixture
def project(tmp_path, monkeypatch, zing_workspace):
    clips = tmp_path / "clips"
    clips.mkdir()
    root = tmp_path / "edit-korky"
    api.init_project(f"uoink:{ITEM}", clips, root)
    monkeypatch.setenv("UOINK_TOKEN", TOKEN)
    monkeypatch.setenv("UOINK_URL", "http://127.0.0.1:61984")
    return root


@pytest.fixture
def kept(tmp_path):
    """A retained Uoink file is named media.mp4: its stem is not a title."""
    media = tmp_path / "uoink-library" / ITEM / "media.mp4"
    media.parent.mkdir(parents=True)
    if shutil.which("ffmpeg"):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=64x64:d=0.2",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(media)], check=True, timeout=60)
    else:
        media.write_bytes(b"synthetic kept media")
    return media


def handoff(media):
    return {"ok": True, "contract": "uoink.media.handoff", "version": 1, "operation": "resolve", "data": {
        "item_ref": f"uoink://item/{ITEM}", "state": "available", "source_url": "https://example.test/video-contract",
        "media": {"path": str(media), "sha256": api.hash_file(media), "byte_length": media.stat().st_size,
                  "media_type": "video/mp4"},
        "provenance": {"kind": "uoink_sidecar", "sidecar_schema_version": 1, "field": "media_file"}}}


def peer(monkeypatch, media, *, capabilities=("uoink.corpus.read/1", "uoink.media.handoff/1"), get=None):
    calls, notes = [], []

    def answer(req, **kwargs):
        url = req.full_url
        assert ":5179" not in url and TOKEN not in url
        calls.append(req)
        if url.endswith("/.well-known/suite-service.json"):
            return respond(make_manifest(capabilities=list(capabilities)))
        if url.endswith("/kept-media"):
            return respond(handoff(media))
        if url.endswith(f"/api/corpus/v1/items/{ITEM}"):
            assert req.method == "GET" and req.data is None and "?" not in url
            assert req.get_header("X-uoink-token") == TOKEN
            return respond(get if get is not None else provider()["operations"]["get"])
        if url.endswith("/notes"):
            notes.append(json.loads(req.data.decode("utf-8")))
            return respond({"ok": True, "video_id": "n1", "slug": "note"})
        raise AssertionError(f"unexpected peer request {url}")

    monkeypatch.setattr(uoink_bridge.urllib.request, "urlopen", answer)
    from myzing import suite_peer
    monkeypatch.setattr(suite_peer.urllib.request, "urlopen", answer)
    return calls, notes


def study(monkeypatch, root):
    from myzing.study import api as study_api

    monkeypatch.setattr(study_api, "study", lambda source, **kwargs: Breakdown(
        meta=VideoMeta(source_url=source, platform="file", title=Path(source).stem, media_path="")))
    attachment = study_reference(root)
    folder = Path(attachment["breakdown_path"]).parent
    (folder / "breakdown.md").write_text("# Edit breakdown - media\n", encoding="utf-8")
    return folder.name


def test_get_response_parser_uses_the_vendored_provider_fixture(monkeypatch):
    operations = provider()["operations"]
    parsed = uoink_bridge.parse_get_response(copy.deepcopy(operations["get"]), ITEM)
    assert parsed == {"ok": True, "item_ref": f"uoink://item/{ITEM}", "title": "The saved hour",
                      "author": "Fixture Creator", "source_url": "https://example.test/video-contract"}
    other = operations["get_non_video"]["data"]["item"]["id"]
    assert uoink_bridge.parse_get_response(copy.deepcopy(operations["get_non_video"]), other)["ok"]
    missing = uoink_bridge.parse_get_response(copy.deepcopy(operations["missing"]), ITEM)
    assert missing["ok"] is False and missing["code"] == "not_found"
    drifted = copy.deepcopy(operations["get"])
    drifted["data"]["item"]["extra"] = 1
    assert uoink_bridge.parse_get_response(drifted, ITEM)["code"] == "contract_mismatch"
    assert uoink_bridge.parse_get_response(copy.deepcopy(operations["get"]), "another-id")["code"] == "contract_mismatch"
    monkeypatch.setenv("UOINK_TOKEN", TOKEN)
    leaked = copy.deepcopy(operations["get"])
    leaked["data"]["item"]["title"] = f"echo {TOKEN}"
    assert uoink_bridge.parse_get_response(leaked, ITEM)["code"] == "contract_mismatch"


def test_uoink_reference_note_uses_the_corpus_item_title(project, kept, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    calls, notes = peer(monkeypatch, kept)
    resolution = resolve_reference(project)
    assert resolution.state == "resolved" and resolution.title == "The saved hour"
    assert api.load_project(project).reference.resolution.title == "The saved hour"
    slug = study(monkeypatch, project)
    assert slug.startswith("media-")  # the retained file name, as in SUITE2
    stored = storage.load_breakdown(slug).provenance["project_reference"]
    assert stored["title"] == "The saved hour" and stored["project_name"] == "edit-korky"
    pushed = uoink_bridge.push_breakdown(slug)
    assert pushed["ok"] and pushed["title_source"] == "uoink_item"
    assert notes[-1]["title"] == "Zing breakdown: The saved hour"
    assert TOKEN not in caplog.text


def test_older_breakdowns_look_the_title_up_at_push_time(project, kept, monkeypatch):
    calls, notes = peer(monkeypatch, kept)
    resolve_reference(project)
    slug = study(monkeypatch, project)
    breakdown = storage.load_breakdown(slug)
    del breakdown.provenance["project_reference"]["title"]  # a breakdown studied before POLISH1
    storage.save_breakdown(breakdown, slug=slug, markdown="# Edit breakdown - media\n")
    before = len(calls)
    assert uoink_bridge.push_breakdown(slug)["title_source"] == "uoink_item"
    assert any(c.full_url.endswith(f"/api/corpus/v1/items/{ITEM}") for c in calls[before:])
    assert notes[-1]["title"] == "Zing breakdown: The saved hour"


def test_without_the_capability_the_container_title_then_project_name_is_used(project, kept, monkeypatch):
    calls, notes = peer(monkeypatch, kept, capabilities=("uoink.media.handoff/1",))
    resolution = resolve_reference(project)
    assert resolution.state == "resolved" and resolution.title is None
    assert not any(c.full_url.endswith(f"/api/corpus/v1/items/{ITEM}") for c in calls)  # no get without the capability
    slug = study(monkeypatch, project)
    breakdown = storage.load_breakdown(slug)
    media = storage.breakdown_dir(slug) / "media.mp4"
    if shutil.which("ffmpeg"):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(kept), "-c", "copy", "-metadata",
                        "title=Korky Paul introduction", str(media)], check=True, timeout=60)
        breakdown.meta.media_path = "media.mp4"
        storage.save_breakdown(breakdown, slug=slug, markdown="# Edit breakdown - media\n")
        pushed = uoink_bridge.push_breakdown(slug)
        assert pushed["title_source"] == "container"
        assert notes[-1]["title"] == "Zing breakdown: Korky Paul introduction"
        media.unlink()
    pushed = uoink_bridge.push_breakdown(slug)
    assert pushed["title_source"] == "project" and notes[-1]["title"] == "Zing breakdown: edit-korky"


def test_missing_item_and_offline_lookups_fall_back_quietly(project, kept, monkeypatch):
    calls, notes = peer(monkeypatch, kept, get=provider()["operations"]["missing"])
    resolution = resolve_reference(project)
    assert resolution.state == "resolved" and resolution.title is None
    slug = study(monkeypatch, project)
    assert uoink_bridge.push_breakdown(slug)["title_source"] == "project"
    assert uoink_bridge.item_metadata("not-a-ref")["code"] == "invalid_ref"
    monkeypatch.delenv("UOINK_TOKEN")
    assert uoink_bridge.item_metadata(f"uoink://item/{ITEM}")["code"] == "unconfigured"


def test_url_studies_keep_their_platform_title_without_extra_requests(zing_workspace, monkeypatch):
    storage.save_breakdown(Breakdown(meta=VideoMeta(source_url="https://www.tiktok.com/@a/video/42",
                                                    platform="tiktok", title="How to price")),
                           slug="tiktok-42", markdown="# Breakdown\n")
    seen = []

    def notes_only(req, **kwargs):
        seen.append(req.full_url)
        assert req.full_url.endswith("/notes")
        return respond({"ok": True, "video_id": "v1", "slug": "s"})

    monkeypatch.setenv("UOINK_TOKEN", TOKEN)
    monkeypatch.setattr(uoink_bridge.urllib.request, "urlopen", notes_only)
    pushed = uoink_bridge.push_breakdown("tiktok-42")
    assert pushed["title_source"] == "platform"
    assert len(seen) == 1
