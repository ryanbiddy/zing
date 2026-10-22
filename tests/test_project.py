"""Inventory transactions and incremental invalidation without external tools."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from myzing import cli
from myzing.project import api, locking
from myzing.project.models import ProjectError, ProjectManifest
from myzing.project.probe import parse_probe
from myzing.study.proc import MediaError, ToolMissing


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def video_metadata():
    return {"streams": [{"codec_type": "video", "width": 320, "height": 180,
                         "avg_frame_rate": "30000/1001", "r_frame_rate": "30000/1001"}],
            "format": {"duration": "2.002", "filename": "/unportable/input.mp4"}}


@pytest.fixture
def inventory(tmp_path, monkeypatch):
    clips = tmp_path / "creator's clips"
    clips.mkdir()
    (clips / "a.mp4").write_bytes(b"first source")
    (clips / "b.mp4").write_bytes(b"second source")
    probes, hashes = [], []
    real_hash = api.hash_file

    def probe(path):
        probes.append(path.name)
        return parse_probe(video_metadata())

    def hash_file(path):
        hashes.append(path.name)
        return real_hash(path)

    monkeypatch.setattr(api, "probe_file", probe)
    monkeypatch.setattr(api, "hash_file", hash_file)
    return clips, tmp_path / "project", hashes, probes


def test_incremental_hashing_and_source_integrity(inventory):
    clips, root, hashes, probes = inventory
    before = {p.name: digest(p) for p in clips.iterdir()}
    manifest = api.init_project("uoink:42", clips, root, supplied_by="Ryan", license="CC0-1.0")
    assert hashes == probes == ["a.mp4", "b.mp4"]
    saved = (root / "project.json").read_bytes()
    hashes.clear()
    probes.clear()
    assert api.scan_project(root) == manifest
    assert hashes == probes == []
    assert (root / "project.json").read_bytes() == saved
    assert manifest.reference.study is None
    assert manifest.reference.value == "uoink:42"
    assert all(a.source.supplied_by == "Ryan" and a.source.license == "CC0-1.0" for a in manifest.assets)
    untouched = next(a for a in manifest.assets if Path(a.path).name == "b.mp4").to_dict()
    changed = clips / "a.mp4"
    changed.write_bytes(b"new source content")
    before["a.mp4"] = digest(changed)
    assert api.project_status(root)["counts"]["changed"] == 1
    assert (root / "project.json").read_bytes() == saved
    updated = api.scan_project(root)
    assert hashes == probes == ["a.mp4"]
    assert next(a for a in updated.assets if Path(a.path).name == "b.mp4").to_dict() == untouched
    original = next(a for a in manifest.assets if Path(a.path).name == "a.mp4")
    asset = next(a for a in updated.assets if a.id == original.id)
    assert asset.revision == 2 and asset.sha256 != original.sha256
    assert api.project_status(root)["counts"]["changed"] == 1
    assert {p.name: digest(p) for p in clips.iterdir()} == before


def test_mtime_or_size_change_rehashes_but_same_content_reuses_probe(inventory):
    clips, root, hashes, probes = inventory
    initial = api.init_project("https://example.test/reference", clips, root)
    hashes.clear()
    probes.clear()
    path = clips / "a.mp4"
    info = path.stat()
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
    touched = api.scan_project(root)
    assert hashes == ["a.mp4"] and probes == []
    assert [a.revision for a in touched.assets] == [1, 1]
    assert [a.sha256 for a in initial.assets] == [a.sha256 for a in touched.assets]
    hashes.clear()
    info = path.stat()
    path.write_bytes(path.read_bytes() + b"extra")
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
    api.scan_project(root)
    assert hashes == probes == ["a.mp4"]


def test_move_missing_restore_add_and_duplicate_content(inventory):
    clips, root, hashes, probes = inventory
    manifest = api.init_project("uoink:42", clips, root)
    original = next(a for a in manifest.assets if Path(a.path).name == "a.mp4")
    before = digest(clips / "a.mp4")
    (clips / "a.mp4").rename(clips / "renamed.mp4")
    hashes.clear()
    probes.clear()
    moved = api.scan_project(root)
    asset = next(a for a in moved.assets if a.id == original.id)
    assert asset.original_path == original.path and asset.path.endswith("renamed.mp4")
    assert asset.previous_paths == [original.path] and asset.revision == 1
    assert hashes == ["renamed.mp4"] and probes == []
    assert digest(clips / "renamed.mp4") == before
    (clips / "b.mp4").unlink()
    missing = api.scan_project(root)
    assert len(missing.assets) == 2
    assert sum(a.state == "missing" for a in missing.assets) == 1
    assert api.project_status(root)["counts"]["missing"] == 1
    (clips / "b.mp4").write_bytes(b"second source")
    restored = api.scan_project(root)
    assert all(a.state == "ready" for a in restored.assets)
    (clips / "copy.mp4").write_bytes((clips / "renamed.mp4").read_bytes())
    added = api.scan_project(root)
    assert len(added.assets) == len({a.id for a in added.assets}) == 3
    assert next(a for a in added.assets if a.path.endswith("renamed.mp4")).id == original.id


@pytest.mark.parametrize("operation", ["swap", "reuse_name", "replace_other"])
def test_moves_preserve_identity_when_paths_are_reused(inventory, operation):
    clips, root, hashes, probes = inventory
    manifest = api.init_project("uoink:42", clips, root)
    original = {Path(a.path).name: a for a in manifest.assets}
    if operation == "swap":
        (clips / "a.mp4").rename(clips / "temporary.mp4")
        (clips / "b.mp4").rename(clips / "a.mp4")
        (clips / "temporary.mp4").rename(clips / "b.mp4")
    elif operation == "reuse_name":
        (clips / "a.mp4").rename(clips / "renamed.mp4")
        (clips / "a.mp4").write_bytes(b"a new replacement source")
    else:
        (clips / "a.mp4").unlink()
        (clips / "b.mp4").rename(clips / "a.mp4")
    before = {p.name: digest(p) for p in clips.iterdir()}
    updated = api.scan_project(root)
    by_id = {a.id: a for a in updated.assets}
    if operation == "swap":
        assert by_id[original["a.mp4"].id].path.endswith("b.mp4")
        assert by_id[original["b.mp4"].id].path.endswith("a.mp4")
    elif operation == "reuse_name":
        assert by_id[original["a.mp4"].id].path.endswith("renamed.mp4")
        assert len(updated.assets) == 3
    else:
        assert by_id[original["a.mp4"].id].state == "missing"
        assert by_id[original["b.mp4"].id].path.endswith("a.mp4")
        assert api.project_status(root)["counts"] == {"ready": 1, "missing": 1, "changed": 0, "unsupported": 0}
    hashes.clear()
    probes.clear()
    assert api.scan_project(root) == updated
    assert hashes == probes == []
    assert {p.name: digest(p) for p in clips.iterdir()} == before


@pytest.mark.parametrize("initial", [False, True])
def test_interrupted_scan_resumes_same_manifest(inventory, monkeypatch, initial):
    clips, root, hashes, probes = inventory
    expected = api.init_project("uoink:42", clips, root.parent / "comparison")
    if not initial:
        api.init_project("uoink:42", clips, root)
        (clips / "a.mp4").write_bytes(b"updated a")
        (clips / "b.mp4").write_bytes(b"updated b")
        expected = api.scan_project(root.parent / "comparison")
    real_probe = api.probe_file
    calls = 0

    def interrupt(path):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt("simulated interruption")
        return real_probe(path)

    monkeypatch.setattr(api, "probe_file", interrupt)
    old_bytes = (root / "project.json").read_bytes() if not initial else None
    before = {p.name: digest(p) for p in clips.iterdir()}
    with pytest.raises(KeyboardInterrupt):
        if initial:
            api.init_project("uoink:42", clips, root)
        else:
            api.scan_project(root)
    if initial:
        assert api.load_project(root).assets == []
    else:
        assert (root / "project.json").read_bytes() == old_bytes
    assert not (root / locking.LOCK_NAME).exists()
    monkeypatch.setattr(api, "probe_file", real_probe)
    assert api.scan_project(root).to_dict() == expected.to_dict()
    assert {p.name: digest(p) for p in clips.iterdir()} == before


def test_atomic_replace_failure_keeps_manifest(inventory, monkeypatch):
    clips, root, _, _ = inventory
    api.init_project("uoink:42", clips, root)
    saved = (root / "project.json").read_bytes()
    (clips / "a.mp4").write_bytes(b"changed source")

    def fail_replace(src, dst):
        assert json.loads(Path(src).read_text(encoding="utf-8"))["assets"]
        assert Path(src).parent == Path(dst).parent
        raise OSError("simulated replace interruption")

    with monkeypatch.context() as patch:
        patch.setattr(api.os, "replace", fail_replace)
        with pytest.raises(OSError, match="interruption"):
            api.scan_project(root)
    assert (root / "project.json").read_bytes() == saved
    assert not list(root.glob(".project-*.tmp"))
    assert api.scan_project(root).assets


def test_concurrent_scans_are_refused(inventory, monkeypatch):
    clips, root, _, _ = inventory
    api.init_project("uoink:42", clips, root)
    (clips / "a.mp4").write_bytes(b"changed source")
    entered, release = threading.Event(), threading.Event()
    real_hash = api.hash_file

    def block(path):
        entered.set()
        assert release.wait(10)
        return real_hash(path)

    monkeypatch.setattr(api, "hash_file", block)
    with ThreadPoolExecutor(max_workers=1) as pool:
        worker = pool.submit(api.scan_project, root)
        try:
            assert entered.wait(10)
            assert api.project_status(root)["lock"]
            with pytest.raises(ProjectError, match="locked"):
                api.scan_project(root)
        finally:
            release.set()
        assert worker.result(timeout=10).assets
    assert not (root / locking.LOCK_NAME).exists()


@pytest.mark.parametrize("state", ["stale", "live", "foreign", "incomplete"])
def test_lock_state_reported_without_stealing(inventory, monkeypatch, state):
    clips, root, _, _ = inventory
    api.init_project("uoink:42", clips, root)
    path = root / locking.LOCK_NAME
    path.write_text(json.dumps({"pid": os.getpid(), "host": socket.gethostname() if state != "foreign" else "other-host"}), encoding="utf-8")
    if state == "incomplete":
        path.write_text("{", encoding="utf-8")
    monkeypatch.setattr(locking, "_pid_alive", lambda pid: state != "stale")
    message = "Stale project lock" if state == "stale" else "unreadable" if state == "incomplete" else "locked"
    with pytest.raises(ProjectError, match=message):
        api.scan_project(root)
    assert path.exists()
    assert message in api.project_status(root)["lock"]


def test_pid_liveness_uses_real_process():
    assert locking._pid_alive(os.getpid())
    assert not locking._pid_alive(-1)


def test_source_mutating_mid_scan_does_not_commit(inventory, monkeypatch):
    clips, root, _, _ = inventory
    api.init_project("uoink:42", clips, root)
    (clips / "a.mp4").write_bytes(b"new data")
    saved = (root / "project.json").read_bytes()
    real_hash = api.hash_file

    def racing_writer(path):
        result = real_hash(path)
        path.write_bytes(b"a concurrent source writer")
        return result

    monkeypatch.setattr(api, "hash_file", racing_writer)
    with pytest.raises(ProjectError, match="Source changed during scan"):
        api.scan_project(root)
    assert (root / "project.json").read_bytes() == saved


def test_internal_paths_survive_project_move_and_cwd_change(tmp_path, monkeypatch):
    root = tmp_path / "Ryan's project"
    clips = root / "clips"
    clips.mkdir(parents=True)
    (clips / "a.mp4").write_bytes(b"source")
    (root / "reference.mp4").write_bytes(b"reference is never probed")
    monkeypatch.setattr(api, "probe_file", lambda path: parse_probe(video_metadata()))
    monkeypatch.chdir(tmp_path)
    manifest = api.init_project("Ryan's project/reference.mp4", "Ryan's project/clips", "Ryan's project")
    assert manifest.clips_root == "clips"
    assert manifest.reference.value == "reference.mp4"
    assert manifest.assets[0].path == manifest.assets[0].source.origin == "clips/a.mp4"
    assert "filename" not in manifest.assets[0].probe.format
    saved = (root / "project.json").read_bytes()
    moved = tmp_path / "moved project"
    root.rename(moved)
    monkeypatch.chdir(clips.parent.parent)
    assert api.scan_project(moved) == manifest
    assert (moved / "project.json").read_bytes() == saved


@pytest.mark.parametrize("layout", ["same", "nested"])
def test_project_metadata_is_not_inventoried(tmp_path, monkeypatch, layout):
    clips = tmp_path / "clips"
    clips.mkdir()
    (clips / "source.mp4").write_bytes(b"source")
    root = clips if layout == "same" else clips / "project"
    monkeypatch.setattr(api, "probe_file", lambda path: parse_probe(video_metadata()))
    manifest = api.init_project("uoink:42", clips, root)
    (root / ".project-interrupted.tmp").write_bytes(b"uncommitted manifest")
    assert api.scan_project(root) == manifest
    assert len(manifest.assets) == 1


def test_whole_source_folder_missing_preserves_records(inventory):
    clips, root, _, _ = inventory
    manifest = api.init_project("uoink:42", clips, root)
    clips.rename(clips.with_name("temporarily offline"))
    updated = api.scan_project(root)
    assert [a.id for a in updated.assets] == [a.id for a in manifest.assets]
    assert all(a.state == "missing" for a in updated.assets)


def test_unreadable_folder_does_not_mark_assets_missing(inventory, monkeypatch):
    clips, root, _, _ = inventory
    api.init_project("uoink:42", clips, root)
    saved = (root / "project.json").read_bytes()

    def denied(*args, onerror, **kwargs):
        onerror(PermissionError("source inaccessible"))

    monkeypatch.setattr(api.os, "walk", denied)
    with pytest.raises(PermissionError, match="inaccessible"):
        api.scan_project(root)
    assert (root / "project.json").read_bytes() == saved


@pytest.mark.parametrize("reference,kind", [("uoink:item-42", "uoink"), ("https://example.test/video", "url"), ("missing-local.mp4", "file")])
def test_reference_is_only_recorded(inventory, monkeypatch, reference, kind):
    clips, root, _, probes = inventory
    monkeypatch.chdir(root.parent)
    manifest = api.init_project(reference, clips, root)
    assert manifest.reference.kind == kind
    assert manifest.reference.state == "recorded" and manifest.reference.study is None
    assert probes == ["a.mp4", "b.mp4"]
    assert manifest.reference.source.license == "user-supplied"
    assert all(Path(a.path).is_absolute() for a in manifest.assets)


@pytest.mark.parametrize("reference", ["", "uoink:", "ftp://example.test/video"])
def test_invalid_reference_fails_before_creation(inventory, reference):
    clips, root, _, _ = inventory
    with pytest.raises(ProjectError):
        api.init_project(reference, clips, root)
    assert not root.exists()


def test_init_will_not_overwrite_existing_manifest(inventory):
    clips, root, _, _ = inventory
    api.init_project("uoink:42", clips, root)
    saved = (root / "project.json").read_bytes()
    with pytest.raises(ProjectError, match="already exists"):
        api.init_project("uoink:different", clips, root)
    assert (root / "project.json").read_bytes() == saved


def test_missing_ffprobe_leaves_resumable_manifest(inventory, monkeypatch):
    clips, root, _, _ = inventory

    def missing(path):
        raise ToolMissing("ffprobe")

    with monkeypatch.context() as patch:
        patch.setattr(api, "probe_file", missing)
        with pytest.raises(ToolMissing, match="zing doctor"):
            api.init_project("uoink:42", clips, root)
    assert api.load_project(root).assets == []
    assert len(api.scan_project(root).assets) == 2


def test_unprobeable_files_are_hashed_and_unsupported(inventory, monkeypatch):
    clips, root, _, _ = inventory

    def unsupported(path):
        raise MediaError("Unknown media format")

    monkeypatch.setattr(api, "probe_file", unsupported)
    before = {p.name: digest(p) for p in clips.iterdir()}
    manifest = api.init_project("uoink:42", clips, root)
    assert all(a.state == "unsupported" and a.sha256 and a.error for a in manifest.assets)
    assert api.project_status(root)["counts"]["unsupported"] == 2
    assert {p.name: digest(p) for p in clips.iterdir()} == before


def test_json_roundtrip_and_versions(inventory):
    clips, root, _, _ = inventory
    manifest = api.init_project("uoink:42", clips, root)
    assert ProjectManifest.from_dict(json.loads(json.dumps(manifest.to_dict()))) == manifest
    for keys in [[], ["reference"], ["assets", 0], ["assets", 0, "probe"], ["assets", 0, "source"], ["assets", 0, "probe", "fps"]]:
        data = copy.deepcopy(manifest.to_dict())
        target = data
        for key in keys:
            target = target[key]
        target["version"] = 99
        with pytest.raises(ProjectError, match="version"):
            ProjectManifest.from_dict(data)


@pytest.mark.parametrize("bad", ["{", "[]", '{"version": 1}', '{"version": 99}'])
def test_corrupt_manifest_is_actionable(tmp_path, capsys, bad):
    (tmp_path / "project.json").write_text(bad, encoding="utf-8")
    assert cli.main(["project", "status", str(tmp_path)]) == 1
    assert "Cannot load" in capsys.readouterr().err


def test_cli_json_and_text(inventory, capsys):
    clips, root, _, _ = inventory
    assert cli.main(["project", "init", "--reference", "uoink:42", "--clips", str(clips), "--out", str(root), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["counts"] == {"ready": 2, "missing": 0, "changed": 0, "unsupported": 0}
    assert cli.main(["project", "scan", str(root)]) == 0
    assert "2 ready" in capsys.readouterr().out
    (clips / "a.mp4").unlink()
    assert cli.main(["project", "status", str(root), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["counts"]["missing"] == 1


@pytest.mark.parametrize("transfer,flag", [("smpte2084", "hdr"), ("arib-std-b67", "hdr"), ("log", "log"), ("log_sqrt", "log")])
def test_probe_explicit_color_flags(transfer, flag):
    data = video_metadata()
    data["streams"][0]["color_transfer"] = transfer
    assert flag in parse_probe(data).flags


def test_probe_preserves_unknowns_and_rotation():
    data = video_metadata()
    video = data["streams"][0]
    video["side_data_list"] = [{"rotation": -90}]
    video["avg_frame_rate"] = "24/1"
    video["color_transfer"] = "unknown"
    probe = parse_probe(data)
    assert probe.orientation == "portrait" and probe.rotation == -90
    assert probe.fps.numerator == 24 and probe.fps.denominator == 1
    assert probe.flags == ["vfr_suspected"]
    assert "untagged" in probe.notes[-1]
    assert probe.streams == data["streams"]
    unknown = parse_probe({})
    assert unknown.duration is None and unknown.fps is None and unknown.orientation is None
    assert unknown.flags == ["no_video", "unknown_duration", "unknown_fps"]


def test_explicit_log_tag_and_secondary_hdr_stream():
    data = video_metadata()
    data["streams"][0]["tags"] = {"gamma": "S-Log3"}
    data["streams"].append({"codec_type": "video", "color_transfer": "smpte2084"})
    assert parse_probe(data).flags == ["hdr", "log"]
