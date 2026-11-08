"""Brief, draft, profile and peer regressions with no network calls."""
from __future__ import annotations

import io
import json
import tempfile
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing import engagement, setup_flow, storage, tts_providers, urls
from myzing.assemble.draft import AssembleError, draft_edl, draft_for_slug
from myzing.brief import api as brief_api, command as brief_command
from myzing.brief.models import Brief
from myzing.profile.api import build_profile
from myzing.profile.packs import PackError, build_pack, load_manifest
from myzing.project.api import init_project
from myzing.render.tts import SynthesisRequest, TTSUnavailableError
from myzing.schemas import Word
from myzing.timing import TimingReviewError, transform_word
from tests.test_assemble_draft import make_breakdown
from tests.test_profile_api import make_source
from tests.test_profile_packs import ref, write_manifest


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked network call")
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(urls, "open_no_redirect", refuse)


@pytest.fixture
def project(tmp_path):
    clips = tmp_path / "clips"
    clips.mkdir()
    root = tmp_path / "project"
    init_project("uoink:fixture", clips, root)
    return root


def test_invalid_short_side_keeps_previous_brief(project, capsys):
    brief_api.save_brief(project, Brief(purpose="Keep these answers", short_side=720))
    path = project / "brief.json"
    before = path.read_bytes()

    assert brief_command.run(["new", str(project), "--answers", "{}", "--short-side", "19"]) == 1

    assert "short_side" in capsys.readouterr().err
    assert path.read_bytes() == before


@pytest.mark.parametrize("mode", ["answers", "import", "reuse", "interview", "restart"])
def test_brief_applies_short_side_in_one_save(project, tmp_path, monkeypatch, mode):
    brief = Brief(purpose="Keep this purpose")
    args = ["new", str(project), "--short-side", "720"]
    if mode == "answers":
        args += ["--answers", json.dumps(brief.to_dict())]
    elif mode == "import":
        imported = tmp_path / "import.json"
        imported.write_text(json.dumps(brief.to_dict()), encoding="utf-8")
        args += ["--brief", str(imported)]
    elif mode in ("reuse", "restart"):
        brief_api.save_brief(project, brief)
        if mode == "restart":
            args += ["--restart"]
    monkeypatch.setattr(brief_command, "interview", lambda *args: brief)
    saved = []

    def save(root, value, **kwargs):
        saved.append(value)
        return brief_api.save_brief(root, value, **kwargs)
    monkeypatch.setattr(brief_command, "save_brief", save)

    assert brief_command.run(args) == 0
    assert len(saved) == 1 and saved[0].short_side == 720
    loaded = brief_api.load_brief(project / "brief.json")
    assert loaded.short_side == 720 and loaded.purpose == brief.purpose


def test_short_side_keeps_interview_concurrent_save_guard(project, monkeypatch, capsys):
    def interview(*args):
        brief_api.save_brief(project, Brief(purpose="Other writer"))
        return Brief(purpose="Interview")
    monkeypatch.setattr(brief_command, "interview", interview)

    assert brief_command.run(["new", str(project), "--short-side", "720"]) == 1
    assert "saved while you were answering" in capsys.readouterr().err
    assert brief_api.load_brief(project / "brief.json").purpose == "Other writer"


def test_partial_draft_write_keeps_previous_edl(monkeypatch):
    storage.save_breakdown(make_breakdown(), slug="draft")
    storage.media_target("draft", "mp4").write_bytes(b"fake")
    draft_for_slug("draft", {"keepers": [{"start": 0, "end": 2}]})
    path = storage.breakdown_dir("draft") / "draft-edl.json"
    before = path.read_bytes()
    temporary_file, write_text = tempfile.NamedTemporaryFile, Path.write_text
    writes = []

    @contextmanager
    def partial_file(*args, **kwargs):
        with temporary_file(*args, **kwargs) as stream:
            def write(data):
                writes.append(stream.name)
                stream.write(data[:len(data) // 2])
                stream.flush()
                raise OSError("disk full")
            yield SimpleNamespace(name=stream.name, write=write)

    def partial_text(target, data, **kwargs):
        if target != path:
            return write_text(target, data, **kwargs)
        writes.append(str(target))
        write_text(target, data[:len(data) // 2], **kwargs)
        raise OSError("disk full")

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", partial_file)
    monkeypatch.setattr(Path, "write_text", partial_text)
    with pytest.raises(OSError, match="disk full"):
        draft_for_slug("draft", {"keepers": [{"start": 2, "end": 4}]})

    assert len(writes) == 1
    assert path.read_bytes() == before
    assert not list(path.parent.glob("*.part"))


def test_pack_rebuild_keeps_previous_profile_backup(tmp_path):
    url = "https://youtube.com/shorts/pack-source"
    slug = storage.slug_for(url)
    make_source(slug, 20, [4], 10)
    manifest = write_manifest(tmp_path / "pack.json", references=[ref(1, url)])
    first = build_pack(manifest, study_missing=False).profile
    folder = storage.profile_dir(first.name)
    before = (folder / "profile.json").read_bytes()
    assert not (folder / "profile.json.bak").exists()
    make_source(slug, 30, [6], 15)

    rebuilt = build_pack(manifest, study_missing=False).profile

    assert (folder / "profile.json.bak").read_bytes() == before
    assert rebuilt.duration.median == 30
    assert storage.load_profile(first.name).to_dict() == rebuilt.to_dict()
    assert rebuilt.provenance["preset_pack"]["references"][0]["outcome"] == "reused"


@pytest.mark.parametrize("slugs,expected", [(["a", "a", "b"], ["a", "b"]),
                                           (["b", "a", "b", "b"], ["b", "a"])])
def test_repeated_profile_sources_count_once(slugs, expected):
    make_source("a", 20, [4], 10)
    make_source("b", 40, [8], 20)

    profile = build_profile("taste", slugs)

    assert profile.source_slugs == expected
    assert profile.provenance["source_count"] == profile.duration.n == 2
    assert profile.duration.median == 30
    assert profile.shot_duration.n == 2
    assert f"duplicate source '{slugs[0]}' ignored" in profile.warnings
    assert storage.load_profile("taste").warnings == profile.warnings


def test_profile_can_be_built_without_saving():
    make_source("a", 20, [4], 10)
    profile = build_profile("taste", ["a"], save=False)
    assert profile.source_slugs == ["a"]
    assert not storage.profile_dir("taste").exists()


@pytest.mark.parametrize("reference", [None, [], "reference"])
def test_non_object_pack_reference_is_a_pack_error(tmp_path, reference):
    manifest = write_manifest(tmp_path / "pack.json", references=[reference])
    with pytest.raises(PackError, match="reference 0"):
        load_manifest(manifest)


@pytest.mark.parametrize("root", [[], None, "pack", 1])
def test_non_object_pack_root_is_reported_in_listing(tmp_path, monkeypatch, root):
    folder = tmp_path / "presets"
    folder.mkdir()
    path = folder / "broken.json"
    path.write_text(json.dumps(root), encoding="utf-8")
    monkeypatch.setenv(setup_flow.PRESETS_DIR_ENV, str(folder))

    with pytest.raises(PackError, match="JSON object"):
        load_manifest(path)
    with pytest.raises(ValueError, match="malformed"):
        setup_flow.load_pack("broken")
    listing = setup_flow.list_packs()
    assert len(listing) == 1 and listing[0]["name"] == "broken"
    assert "malformed" in listing[0]["error"]


@pytest.mark.parametrize("start,end", [(False, True), (True, 2), (0, True),
                                      ("0", 2), (0, "2"), (None, 2), (0, [])])
def test_keeper_times_require_numbers(tmp_path, start, end):
    media = tmp_path / "media.mp4"
    media.write_bytes(b"fake")
    with pytest.raises(AssembleError, match="keeper 0 lacks numeric start/end"):
        draft_edl(make_breakdown(), {"keepers": [{"start": start, "end": end}]}, media)


@pytest.mark.parametrize("failure,code", [(TimeoutError, "timeout"), (OSError, "unavailable")])
def test_engagement_error_body_read_failure_is_retryable(monkeypatch, failure, code):
    monkeypatch.setenv("UOINK_TOKEN", "test-token")
    reads = []

    class Body(io.BytesIO):
        def read(self, limit=-1):
            reads.append(limit)
            raise failure("body read failed")

    def post(request, **kwargs):
        raise urllib.error.HTTPError(request.full_url, 503, "unavailable", {}, Body())
    monkeypatch.setattr(urls, "open_no_redirect", post)

    with pytest.raises(engagement._DeliveryError) as caught:
        engagement._post({"event_id": "test-event"})
    assert caught.value.code == code and caught.value.retryable is True
    receipt = engagement.record_opened("uoink:fixture", "ab" * 32)
    assert receipt["state"] == "spooled"
    pending = engagement._read_state()["pending"][receipt["event_id"]]
    assert pending["last_error_code"] == code
    assert reads == [engagement._MAX_RESPONSE_BYTES + 1] * 2


@pytest.mark.parametrize("token", ["private\ncredential", "private\rcredential", "private\tcredential",
                                  "private\x1fcredential", "private\x7fcredential", "private\x85credential"])
def test_engagement_rejects_control_characters_without_echoing_token(monkeypatch, token):
    monkeypatch.setenv("UOINK_TOKEN", token)

    def request(*args, **kwargs):
        raise AssertionError("invalid credential reached request construction")
    monkeypatch.setattr(urllib.request, "Request", request)
    with pytest.raises(engagement._DeliveryError) as caught:
        engagement._post({"event_id": "test-event"})
    assert caught.value.code == "invalid_configuration" and not caught.value.retryable
    assert str(caught.value) == "UOINK_TOKEN must not contain control characters"
    receipt = engagement.record_opened("uoink:fixture", "ab" * 32)
    assert receipt["state"] == "rejected"
    assert "private" not in engagement._state_path().read_text(encoding="utf-8")


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("key", ["private\ncredential", "private\tcredential", "private\x7fcredential",
                                "private\x85credential"])
def test_tts_rejects_control_characters_without_echoing_key(tmp_path, monkeypatch, explicit, key):
    monkeypatch.setenv(tts_providers.ELEVENLABS_KEY_ENV, key)
    provider = tts_providers.ElevenLabsProvider(api_key=key if explicit else None)

    def request(*args, **kwargs):
        raise AssertionError("invalid credential reached request construction")
    monkeypatch.setattr(urllib.request, "Request", request)
    with pytest.raises(TTSUnavailableError) as caught:
        provider.synthesize(SynthesisRequest(text="Hello", voice="v1"), tmp_path / "voice.wav")
    assert str(caught.value) == "ELEVENLABS_API_KEY must not contain control characters"
    assert not (tmp_path / "voice.wav").exists()


@pytest.mark.parametrize("adjustments", [None, {}, "adjustment", 0, False])
def test_non_list_timing_adjustments_need_review(adjustments):
    timing = {"version": 1, "status": "measured", "method": "source_transcript",
              "original": {"start": 0, "end": 1}, "adjustments": adjustments}
    word = Word("hello", 0, 1, timing=timing)

    with pytest.raises(TimingReviewError, match="invalid timing provenance"):
        transform_word(word, .1, .9, "trim_clamp")
    assert word.timing == timing and word.start == 0 and word.end == 1


@pytest.mark.parametrize("edge", ["trailing", "leading"])
def test_engagement_strips_surrounding_newline_from_token(monkeypatch, edge):
    # A token copied from a file often ends in a newline. Surrounding
    # whitespace is stripped as before; only characters inside are refused.
    newline = chr(10)
    token = "private-credential" + newline if edge == "trailing" else newline + "private-credential"
    monkeypatch.setenv("UOINK_TOKEN", token)
    seen = []

    def request(url, *args, **kwargs):
        seen.append(url)
        raise RuntimeError("stop before network")
    monkeypatch.setattr(urllib.request, "Request", request)
    with pytest.raises(Exception):
        engagement._post({"event_id": "test-event"})
    assert seen, "a token with a surrounding newline should reach request construction"
