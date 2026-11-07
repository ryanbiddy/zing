import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from myzing import doctor, mcp_server, reference_range, setup_flow, storage, suite_peer, thumbs
from myzing.factory import pipeline
from myzing.schemas import Breakdown, StyleProfile, VideoMeta, Word
from myzing.study import speech_models


@pytest.mark.parametrize("handler,kwargs", [
    (mcp_server.h_factory_clip, {"start": 5, "end": 20}),
    (mcp_server.h_factory_answer, {"task": "clip01-context", "answer": {"flags": []}}),
])
def test_factory_mutations_require_project(tmp_path, handler, kwargs):
    result = handler(str(tmp_path), **kwargs)
    assert result["ok"] is False
    assert "not a factory project" in result["error"]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("handler,kwargs", [
    (mcp_server.h_factory_clip, {"start": 10, "end": 25}),
    (mcp_server.h_factory_clip, {"clip": "clip01", "start": 10, "end": 25}),
    (mcp_server.h_factory_clip, {"bench": 0}),
    (mcp_server.h_factory_answer, {"task": "clip01-context", "answer": {"flags": []}}),
])
def test_factory_mutations_reject_running_project(tmp_path, monkeypatch, handler, kwargs):
    (tmp_path / "factory.json").write_text("{}", encoding="utf-8")
    pipeline.add_clip(tmp_path, 5, 20)
    clip = tmp_path / "clip01"
    clip.mkdir()
    (clip / "context.json").write_text("{}", encoding="utf-8")
    before = _files(tmp_path)
    monkeypatch.setattr(mcp_server, "_FACTORY_JOBS", {str(tmp_path.resolve()): object()})
    monkeypatch.chdir(tmp_path)
    result = handler(".", **kwargs)
    assert result["ok"] is False
    assert "in progress" in result["error"]
    assert _files(tmp_path) == before


@pytest.mark.parametrize("handler,kwargs,seam", [
    (mcp_server.h_factory_clip, {"start": 5, "end": 20}, "add_clip"),
    (mcp_server.h_factory_answer, {"task": "clip01-context", "answer": {"flags": []}}, "answer"),
])
def test_factory_mutations_report_io_errors(tmp_path, monkeypatch, handler, kwargs, seam):
    (tmp_path / "factory.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(pipeline, seam, Mock(side_effect=OSError("write failed")))
    assert handler(str(tmp_path), **kwargs) == {"ok": False, "error": "write failed"}


@pytest.mark.parametrize("source", [
    "https://www.youtube.com/watch?v=abc", "https://youtu.be/abc",
    "https://www.youtube.com/shorts/abc", "https://www.tiktok.com/@a/video/123",
    "https://www.instagram.com/reel/abc", "https://x.com/a/status/123",
    "https://twitter.com/a/status/123", "https://example.com/video.mp4",
])
def test_reference_slugs_separate_options_and_preserve_untrimmed(source):
    base = storage.slug_for(source)
    assert reference_range.slug(source) == base
    assert reference_range.slug(source, reference_range="all") == base
    selected = reference_range.slug(source, reference_range="0:10-0:30")
    assert selected == reference_range.slug(source, ref_start=10, ref_end=30)
    assert len({base, selected,
                reference_range.slug(source, reference_range="0:30-0:50"),
                reference_range.slug(source, analysis_seconds=20),
                reference_range.slug(source, analysis_max_side=640),
                reference_range.slug(source, reference_range="0:10-0:30", analysis_seconds=10)}) == 6


@pytest.mark.parametrize("stem", ["clip", "c" * 80])
def test_reference_file_slug_retains_content_identity(tmp_path, stem):
    first, second = tmp_path / "a" / f"{stem}.mp4", tmp_path / "b" / f"{stem}.mp4"
    for path, content in ((first, b"first"), (second, b"second")):
        path.parent.mkdir()
        path.write_bytes(content)
    assert reference_range.slug(str(first)) == storage.slug_for(str(first))
    original = reference_range.slug(str(first), reference_range="10-30")
    assert original != reference_range.slug(str(second), reference_range="10-30")
    first.write_bytes(b"changed")
    assert original != reference_range.slug(str(first), reference_range="10-30")


def test_long_reference_slug_leaves_room_for_acquisition(zing_workspace):
    source = "https://youtu.be/" + "a" * 80
    selected = reference_range.slug(source, reference_range="10-30")
    assert storage.breakdown_dir(selected + "-reference-source").name == selected + "-reference-source"
    assert selected != reference_range.slug(source[:-1] + "b", reference_range="10-30")


@pytest.mark.parametrize("pid", [987654, None, "dead"])
def test_get_render_reconciles_dead_runner(zing_workspace, monkeypatch, pid):
    folder = storage.render_dir("orphan")
    storage.write_status_at(folder, state="running", pid=pid)
    monkeypatch.setattr(mcp_server, "_pid_alive", lambda value: False)
    result = mcp_server.h_get_render("orphan")
    assert result["state"] == "failed"
    assert "render_edl again" in result["error"]
    assert storage.read_status_at(folder)["state"] == "failed"


def test_get_render_preserves_live_foreign_runner(zing_workspace, monkeypatch):
    folder = storage.render_dir("live")
    storage.write_status_at(folder, state="running", pid=os.getpid() + 1)
    monkeypatch.setattr(mcp_server, "_pid_alive", lambda value: True)
    assert mcp_server.h_get_render("live")["state"] == "running"
    assert storage.read_status_at(folder)["state"] == "running"


def test_setup_plan_reconciles_dead_study(zing_workspace, monkeypatch):
    source = "https://youtu.be/orphan"
    slug = storage.slug_for(source)
    storage.write_status(slug, state="running", pid=987654)
    monkeypatch.setattr(mcp_server, "_pid_alive", lambda value: False)
    plan = setup_flow.plan_setup("taste", [source])
    assert plan["in_progress"] == []
    assert plan["failed"] == [slug]
    assert storage.read_status(slug)["state"] == "failed"


@pytest.mark.parametrize("raw", ["{", "{}", "null", "[]"])
def test_whisper_reports_invalid_speech_settings(zing_workspace, monkeypatch, raw):
    monkeypatch.delenv("ZING_WHISPER_MODEL", raising=False)
    zing_workspace.mkdir(parents=True)
    (zing_workspace / "speech.json").write_text(raw, encoding="utf-8")
    check = doctor.check_whisper()
    assert check.ok is False
    assert "speech.json" in check.detail
    assert "zing doctor --speech-model" in check.fix


def test_whisper_reports_inventory_io_error(zing_workspace, monkeypatch):
    monkeypatch.setattr(doctor, "_whisper_model_name", lambda: "small.en")
    monkeypatch.setattr(speech_models, "inventory", Mock(side_effect=OSError("unreadable speech.json")))
    check = doctor.check_whisper()
    assert check.ok is False
    assert "speech.json" in check.detail
    assert check.fix


@pytest.mark.parametrize("args", [[], ["--json"]])
def test_doctor_cli_reports_invalid_speech_settings(zing_workspace, monkeypatch, capsys, args):
    monkeypatch.delenv("ZING_WHISPER_MODEL", raising=False)
    zing_workspace.mkdir(parents=True)
    (zing_workspace / "speech.json").write_text("{", encoding="utf-8")
    monkeypatch.setattr(doctor, "run_checks", lambda: [doctor.check_whisper()])
    assert doctor.run(args) == 0
    output = capsys.readouterr().out
    assert "speech.json" in output
    assert "zing doctor --speech-model" in output


@pytest.mark.parametrize("raw", [None, [], {"meta": None}, {"shots": None}, {"words": None}, {"judgment": None}])
def test_breakdown_index_reports_invalid_shapes(zing_workspace, raw):
    folder = storage.breakdown_dir("bad")
    folder.mkdir(parents=True)
    (folder / "breakdown.json").write_text(json.dumps(raw), encoding="utf-8")
    storage.save_breakdown(Breakdown(VideoMeta("source", "file")), slug="good")
    rows = storage.list_breakdowns()
    assert rows[0]["slug"] == "bad" and "unreadable breakdown.json" in rows[0]["error"]
    assert rows[1]["slug"] == "good" and "error" not in rows[1]


@pytest.mark.parametrize("raw", [None, [], {"source_slugs": None}, {"unjudged_source_slugs": None},
                                  {"judged": None}, {"warnings": None}])
def test_profile_index_reports_invalid_shapes(zing_workspace, raw):
    folder = storage.profile_dir("bad")
    folder.mkdir(parents=True)
    (folder / "profile.json").write_text(json.dumps(raw), encoding="utf-8")
    storage.save_profile(StyleProfile(name="good", source_slugs=[]))
    rows = storage.list_profiles()
    assert rows[0]["name"] == "bad" and "unreadable profile.json" in rows[0]["error"]
    assert rows[1]["name"] == "good" and "error" not in rows[1]


@pytest.mark.parametrize("raw", [None, [], {}, {"meta": None}, {"meta": {}},
                                  {"meta": {"source_url": "x", "platform": "file"}, "shots": None},
                                  {"meta": {"source_url": "x", "platform": "file"}, "words": [None]},
                                  {"meta": {"source_url": "x", "platform": "file"}, "audio": None}])
def test_breakdown_shape_errors_are_value_errors(zing_workspace, raw):
    with pytest.raises(ValueError):
        Breakdown.from_dict(raw)
    folder = storage.breakdown_dir("bad")
    folder.mkdir(parents=True)
    (folder / "breakdown.json").write_text(json.dumps(raw), encoding="utf-8")
    assert mcp_server.h_get_breakdown("bad")["ok"] is False


@pytest.mark.parametrize("pid", [True, False, None, "1", 0, -1, 2**32, 10**12])
def test_pid_alive_rejects_invalid_values(monkeypatch, pid):
    kill = Mock()
    monkeypatch.setattr(mcp_server, "os", SimpleNamespace(name="posix", kill=kill))
    assert mcp_server._pid_alive(pid) is False
    kill.assert_not_called()


@pytest.mark.parametrize("error,alive", [(OverflowError(), False), (OSError(), False), (PermissionError(), True)])
def test_pid_alive_handles_posix_errors(monkeypatch, error, alive):
    monkeypatch.setattr(mcp_server, "os", SimpleNamespace(name="posix", kill=Mock(side_effect=error)))
    assert mcp_server._pid_alive(2**31) is alive


@pytest.mark.parametrize("query_ok", [True, False])
def test_pid_alive_windows_uses_full_handles(monkeypatch, query_ok):
    handle = 0x1234567887654321

    def exit_code(value, code):
        assert value == handle
        code._obj.value = 259
        return query_ok

    kernel = SimpleNamespace(OpenProcess=Mock(return_value=handle),
                             GetExitCodeProcess=Mock(side_effect=exit_code), CloseHandle=Mock())
    monkeypatch.setattr(ctypes, "WinDLL", Mock(return_value=kernel), raising=False)
    monkeypatch.setattr(mcp_server, "os", SimpleNamespace(name="nt"))
    assert mcp_server._pid_alive(2**31) is query_ok
    assert kernel.OpenProcess.argtypes == [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    assert kernel.OpenProcess.restype is wintypes.HANDLE
    assert kernel.GetExitCodeProcess.argtypes == [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    assert kernel.GetExitCodeProcess.restype is wintypes.BOOL
    assert kernel.CloseHandle.argtypes == [wintypes.HANDLE]
    assert kernel.CloseHandle.restype is wintypes.BOOL
    kernel.CloseHandle.assert_called_once_with(handle)


@pytest.mark.parametrize("pid", [True, False, 0, -1, 2**32, 10**12])
def test_lease_rejects_invalid_pids(pid):
    lease = {"contract": "ryan.suite.runtime-lease", "version": 1, "service_id": "uoink",
             "service_version": "3.6.0", "api_version": 1, "base_url": "http://127.0.0.1:5999",
             "health_url": "http://127.0.0.1:5999/health", "manifest_url": "http://127.0.0.1:5999/manifest",
             "capabilities": [], "ui": {"home": "/", "routes": {}}, "pid": pid, "started_at": "now"}
    assert "pid" in suite_peer.lease_defect(lease, "uoink")


@pytest.mark.parametrize("failure", ["serialize", "publish"])
def test_failed_profile_save_preserves_published_profile(zing_workspace, monkeypatch, failure):
    old = StyleProfile(name="taste", source_slugs=["old"])
    folder = storage.save_profile(old)
    before = (folder / "profile.json").read_bytes()
    new = StyleProfile(name="taste", source_slugs=["new"])
    if failure == "serialize":
        monkeypatch.setattr(new, "to_json", Mock(side_effect=ValueError("serialization failed")))
    else:
        monkeypatch.setattr(storage, "_replace", Mock(side_effect=OSError("publish failed")))
    with pytest.raises((ValueError, OSError), match="failed"):
        storage.save_profile(new)
    assert (folder / "profile.json").read_bytes() == before
    assert (folder / "profile.json.bak").read_bytes() == before
    assert sorted(p.name for p in folder.iterdir()) == ["profile.json", "profile.json.bak"]


def test_profile_stays_readable_until_atomic_publish(zing_workspace, monkeypatch):
    folder = storage.save_profile(StyleProfile(name="taste", source_slugs=["old"]))
    replace = storage._replace
    calls = []

    def publish(source, target):
        assert storage.load_profile("taste").source_slugs == ["old"]
        assert Path(source).parent == folder
        calls.append(target)
        replace(source, target)

    monkeypatch.setattr(storage, "_replace", publish)
    storage.save_profile(StyleProfile(name="taste", source_slugs=["new"]))
    assert calls == [folder / "profile.json"]
    assert storage.load_profile("taste").source_slugs == ["new"]


def _files(folder):
    return {p.relative_to(folder): p.read_bytes() for p in folder.rglob("*") if p.is_file()}


@pytest.fixture
def thumbnail_set(zing_workspace, monkeypatch):
    breakdown = Breakdown(VideoMeta("source", "file", duration=12, width=640, height=360),
                          words=[Word("Opening", 0, 1)])
    folder = storage.save_breakdown(breakdown, slug="thumbs") / thumbs.THUMBNAILS_DIR
    storage.media_target("thumbs", "mp4").write_bytes(b"media")
    monkeypatch.setattr(thumbs.shutil, "which", lambda value: value)
    monkeypatch.setattr(storage, "load_breakdown", lambda slug: breakdown)
    monkeypatch.setattr(thumbs, "select_thumbnail_candidates", lambda *args: [
        {"selector": selector, "timestamp": i + 1, "perceptual_hash": i,
         "description": "source frame", "scores": {"quality": i}}
        for i, selector in enumerate(("emotional_peak", "object_reveal", "contrast_sharpness"))
    ])
    monkeypatch.setattr(thumbs, "_extract_source_frame",
                        lambda media, timestamp, target, ffmpeg: target.write_bytes(f"old {timestamp}".encode()))
    thumbs.generate_thumbnails("thumbs")
    return breakdown, folder


@pytest.mark.parametrize("failure", ["hook", "extract"])
def test_thumbnail_failure_preserves_published_set(thumbnail_set, monkeypatch, failure):
    breakdown, folder = thumbnail_set
    before = _files(folder)
    calls = []

    def extract(media, timestamp, target, ffmpeg):
        calls.append(timestamp)
        target.write_bytes(b"new frame")
        if failure == "extract" and len(calls) == 2:
            raise thumbs.ThumbnailError("extraction failed")

    monkeypatch.setattr(thumbs, "_extract_source_frame", extract)
    if failure == "hook":
        breakdown.words = []
    with pytest.raises(thumbs.ThumbnailError, match="no transcript|extraction failed"):
        thumbs.generate_thumbnails("thumbs")
    assert _files(folder) == before
    assert all(p.is_file() for p in folder.iterdir())
    if failure == "hook":
        assert calls == []


def test_thumbnail_manifest_publishes_atomically_before_stale_cleanup(thumbnail_set, monkeypatch):
    _, folder = thumbnail_set
    manifest = folder / "thumbs.json"
    before = manifest.read_bytes()
    stale = folder / "candidate-stale.jpg"
    stale.write_bytes(b"stale")
    replace = storage._replace
    calls = []

    def publish(source, target):
        assert manifest.read_bytes() == before
        assert stale.is_file()
        calls.append(target)
        replace(source, target)

    monkeypatch.setattr(storage, "_replace", publish)
    result = thumbs.generate_thumbnails("thumbs")
    assert calls[-1] == manifest
    assert len(calls) == result["candidate_count"] + 1
    assert not stale.exists()
    assert {p.name for p in folder.iterdir()} == {"thumbs.json", *(
        Path(candidate["frame_path"]).name for candidate in result["candidates"])}
