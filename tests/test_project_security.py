"""Manifest containment, lock ownership, and local-only probe regressions."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing.project import api, locking, probe
from myzing.project.models import ProjectError, ProjectManifest
from myzing.study.proc import MediaError


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "project"
    clips = root / "clips"
    clips.mkdir(parents=True)
    (clips / "clip.mp4").write_bytes(b"media")
    (root / "reference.mp4").write_bytes(b"reference")
    monkeypatch.setattr(api, "probe_file", lambda path: probe.parse_probe({
        "streams": [{"codec_type": "video", "width": 16, "height": 16,
                     "avg_frame_rate": "30/1", "r_frame_rate": "30/1"}],
        "format": {"duration": "1"},
    }))
    manifest = api.init_project(str(root / "reference.mp4"), clips, root)
    return root, manifest.to_dict()


def set_entry(data, keys, value):
    for key in keys[:-1]:
        data = data[key]
    data[keys[-1]] = value


PATH_ENTRIES = [
    ("clips_root",), ("source", "origin"), ("reference", "value"),
    ("reference", "source", "origin"), ("assets", 0, "path"),
    ("assets", 0, "original_path"), ("assets", 0, "source", "origin"),
    ("assets", 0, "previous_paths", 0),
]


@pytest.mark.parametrize("keys", PATH_ENTRIES)
@pytest.mark.parametrize("value", ["../outside", "clips/../../outside"])
def test_every_stored_path_is_validated_at_load(project, keys, value):
    root, data = project
    data["assets"][0]["previous_paths"] = ["clips/old.mp4"]
    set_entry(data, keys, value)
    name = ".".join(str(key) if isinstance(key, str) else f"[{key}]" for key in keys)
    # Assert field names, including indexes, without prescribing error punctuation.
    for load in (lambda: ProjectManifest.from_dict(data, root), lambda: api.load_project(root)):
        (root / "project.json").write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(ProjectError, match="outside the project") as error:
            load()
        assert all(part in str(error.value) for part in name.split("."))
        assert value in str(error.value)


@pytest.mark.parametrize("operation", [api.scan_project, api.project_status])
@pytest.mark.parametrize("keys", [("clips_root",), ("assets", 0, "path")])
def test_crafted_manifest_fails_before_walk_hash_probe_or_asset_stat(project, monkeypatch, operation, keys):
    root, data = project
    set_entry(data, keys, "../outside")
    manifest = root / "project.json"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    before = manifest.read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid manifest must fail before inventory IO")

    monkeypatch.setattr(api, "_files", forbidden)
    monkeypatch.setattr(api, "_signature", forbidden)
    monkeypatch.setattr(api, "hash_file", forbidden)
    monkeypatch.setattr(api, "probe_file", forbidden)
    with pytest.raises(ProjectError, match="outside the project"):
        operation(root)
    assert manifest.read_bytes() == before
    assert not (root / locking.LOCK_NAME).exists()


@pytest.mark.parametrize("value", ["C:foo", "C:", "c:../outside"])
def test_drive_relative_paths_are_rejected(project, value):
    root, data = project
    data["clips_root"] = value
    with pytest.raises(ProjectError, match="clips_root.*ambiguous"):
        ProjectManifest.from_dict(data, root)
    with pytest.raises(ProjectError, match="ambiguous"):
        api.resolve_path(value, root)


@pytest.mark.parametrize("value", ["/Windows", "\\Windows"])
def test_native_root_relative_paths(project, value):
    root, data = project
    data["clips_root"] = value
    if os.name == "nt":
        with pytest.raises(ProjectError, match="clips_root.*ambiguous"):
            ProjectManifest.from_dict(data, root)
    else:
        # A leading slash is fully absolute on POSIX; a backslash is literal.
        assert api.resolve_path(value, root) == (Path(value) if value.startswith("/") else root / value)


@pytest.mark.parametrize("value", ["~", "~/clips", "~someone/clips"])
def test_manifest_tilde_is_literal(project, monkeypatch, value):
    root, data = project

    def forbidden(*args):
        pytest.fail("Stored paths must never expand '~'")

    monkeypatch.setattr(Path, "expanduser", forbidden)
    data["clips_root"] = value
    assert api.resolve_path(value, root) == root / value
    assert ProjectManifest.from_dict(data, root).clips_root == value


def test_valid_relative_paths_roundtrip_and_require_project_context(project):
    root, data = project
    data["clips_root"] = "clips/../clips"
    assert api.resolve_path(data["clips_root"], root) == root / "clips"
    assert ProjectManifest.from_dict(data, root).to_dict() == data
    with pytest.raises(ProjectError, match="supply the project folder"):
        ProjectManifest.from_dict(data)


def test_absolute_external_paths_are_preserved(project):
    root, data = project
    external = str(root.parent / "outside" / ".." / "other" / "~" / "clip.mp4")
    data["assets"][0]["previous_paths"] = ["clips/old.mp4"]
    for keys in PATH_ENTRIES:
        set_entry(data, keys, external)
    assert api.resolve_path(external, root) == Path(external)
    assert ".." in api.resolve_path(external, root).parts
    assert ProjectManifest.from_dict(data, root).to_dict() == data
    (root / "project.json").write_text(json.dumps(data), encoding="utf-8")
    assert api.load_project(root).to_dict() == data


def directory_link(link, target):
    # Exercise native links on each CI OS. Windows junctions need no symlink
    # privilege (this host does not grant it); POSIX exercises symlinks.
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        link.symlink_to(target, target_is_directory=True)


@pytest.mark.parametrize("keys", [("clips_root",), ("assets", 0, "path")])
def test_relative_directory_links_cannot_escape_project(project, keys):
    root, data = project
    outside = root.parent / "outside"
    outside.mkdir()
    (outside / "clip.mp4").write_bytes(b"external media")
    directory_link(root / "escape", outside)
    set_entry(data, keys, "escape" if keys == ("clips_root",) else "escape/clip.mp4")
    (root / "project.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ProjectError, match="outside the project"):
        api.load_project(root)
    with pytest.raises(ProjectError, match="outside the project"):
        api.resolve_path("escape/clip.mp4", root)
    # Absolute links are explicit external paths and retain their spelling.
    assert api.resolve_path(str(root / "escape"), root) == root / "escape"


def test_relative_directory_links_inside_project_are_resolved(project):
    root, data = project
    directory_link(root / "alias", root / "clips")
    data["clips_root"] = "alias"
    assert api.resolve_path("alias", root) == root / "clips"
    assert ProjectManifest.from_dict(data, root).clips_root == "alias"


def test_scan_does_not_follow_child_directory_links(project):
    root, data = project
    outside = root.parent / "outside"
    outside.mkdir()
    (outside / "secret.mp4").write_bytes(b"external media")
    directory_link(root / "clips" / "escape", outside)
    assert api.scan_project(root).to_dict() == data


@pytest.mark.parametrize("value", ["", None, 17, "clips\0outside"])
def test_invalid_path_values_name_the_entry(project, value):
    root, data = project
    data["assets"][0]["path"] = value
    with pytest.raises(ProjectError, match=r"assets\[0\].*\.path"):
        ProjectManifest.from_dict(data, root)


def test_lock_release_preserves_replacement_between_read_and_delete(tmp_path, monkeypatch):
    path = tmp_path / locking.LOCK_NAME
    original_read = Path.read_text
    replacement = '{"token": "new owner"}'
    raced = []

    def replace_after_read(self, *args, **kwargs):
        result = original_read(self, *args, **kwargs)
        if not raced:
            raced.append(True)
            path.unlink(missing_ok=True)
            path.write_text(replacement, encoding="utf-8")
        return result

    with locking.project_lock(tmp_path):
        monkeypatch.setattr(Path, "read_text", replace_after_read)
    assert raced and path.read_text(encoding="utf-8") == replacement
    assert not list(tmp_path.glob(".project-*.tmp"))


@pytest.mark.parametrize("replacement", ['{"token": "other owner"}', "{", "[]"])
def test_lock_replaced_before_release_is_restored(tmp_path, replacement):
    path = tmp_path / locking.LOCK_NAME
    with locking.project_lock(tmp_path):
        path.unlink()
        path.write_text(replacement, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == replacement
    assert not list(tmp_path.glob(".project-*.tmp"))


def test_lock_changed_in_place_is_not_removed(tmp_path):
    path = tmp_path / locking.LOCK_NAME
    with locking.project_lock(tmp_path):
        path.write_text('{"token": "other owner"}', encoding="utf-8")
    assert json.loads(path.read_text(encoding="utf-8"))["token"] == "other owner"


def test_lock_restoration_never_overwrites_new_owner(tmp_path, monkeypatch):
    path = tmp_path / locking.LOCK_NAME
    original_link = os.link

    def race_restore(src, dst, *args, **kwargs):
        path.write_text('{"token": "third owner"}', encoding="utf-8")
        return original_link(src, dst, *args, **kwargs)

    with pytest.raises(ProjectError, match="displaced lock is preserved") as error:
        with locking.project_lock(tmp_path):
            path.write_text('{"token": "second owner"}', encoding="utf-8")
            monkeypatch.setattr(locking.os, "link", race_restore)
    assert json.loads(path.read_text(encoding="utf-8"))["token"] == "third owner"
    displaced, = tmp_path.glob(".project-*.tmp")
    assert str(displaced) in str(error.value)
    assert json.loads(displaced.read_text(encoding="utf-8"))["token"] == "second owner"


@pytest.mark.parametrize("stage", ["write", "fsync"])
def test_failed_lock_write_removes_partial_file_and_can_retry(tmp_path, monkeypatch, stage):
    path = tmp_path / locking.LOCK_NAME

    def fail_write(data, handle):
        handle.write('{"pid":')
        raise OSError("failed token write")

    def fail_sync(fd):
        raise OSError("failed token sync")

    with monkeypatch.context() as patch:
        if stage == "write":
            patch.setattr(locking.json, "dump", fail_write)
        else:
            patch.setattr(locking.os, "fsync", fail_sync)
        with pytest.raises(OSError, match="failed token"):
            with locking.project_lock(tmp_path):
                pytest.fail("Incomplete lock must not enter scan")
    assert not path.exists()
    assert not list(tmp_path.glob(".project-*.tmp"))
    with locking.project_lock(tmp_path):
        assert json.loads(path.read_text(encoding="utf-8"))["token"]
    assert not path.exists()


def test_failed_lock_write_preserves_replacement(tmp_path, monkeypatch):
    path = tmp_path / locking.LOCK_NAME
    original_rename = Path.rename

    def fail_write(data, handle):
        handle.write("{")
        raise OSError("failed token write")

    def replace_before_release(self, target):
        if self == path:
            original_rename(self, tmp_path / "old-partial-lock")
            path.write_text('{"token": "other owner"}', encoding="utf-8")
        return original_rename(self, target)

    monkeypatch.setattr(locking.json, "dump", fail_write)
    monkeypatch.setattr(Path, "rename", replace_before_release)
    with pytest.raises(OSError, match="failed token write"):
        with locking.project_lock(tmp_path):
            pytest.fail("Incomplete lock must not enter scan")
    assert json.loads(path.read_text(encoding="utf-8"))["token"] == "other owner"


@pytest.mark.parametrize("suffix", [".m3u8", ".m3u", ".ffconcat", ".concat", ".sdp", ".mpd", ".txt", ""])
def test_nonmedia_files_are_hashed_but_never_probed(tmp_path, monkeypatch, suffix):
    clips = tmp_path / "clips"
    clips.mkdir()
    path = clips / f"playlist{suffix}"
    path.write_text("ffconcat version 1.0\nfile '../outside.mp4'\n", encoding="utf-8")
    before = path.read_bytes()

    def forbidden(*args, **kwargs):
        pytest.fail("Unlisted extension must never reach ffprobe")

    monkeypatch.setattr(api, "probe_file", forbidden)
    monkeypatch.setattr(probe.proc, "run", forbidden)
    root = tmp_path / "project"
    manifest = api.init_project("uoink:fixture", clips, root)
    asset, = manifest.assets
    assert asset.state == "unsupported" and asset.probe is None
    assert asset.sha256 == api.hash_file(path)
    assert "file was not probed" in asset.error
    assert api.scan_project(root) == manifest
    assert api.project_status(root)["counts"]["unsupported"] == 1
    with pytest.raises(MediaError, match="Unsupported media extension"):
        probe.probe_file(path)
    assert path.read_bytes() == before


def test_extension_changes_invalidate_cached_probe(project, monkeypatch):
    root, data = project
    asset_id = data["assets"][0]["id"]
    (root / "clips/clip.mp4").rename(root / "clips/clip.m3u8")

    def forbidden(*args):
        pytest.fail("Renaming cached media to a playlist must discard its probe")

    with monkeypatch.context() as patch:
        patch.setattr(api, "probe_file", forbidden)
        asset, = api.scan_project(root).assets
        assert asset.id == asset_id and asset.state == "unsupported" and asset.probe is None
    (root / "clips/clip.m3u8").rename(root / "clips/clip.MP4")
    asset, = api.scan_project(root).assets
    assert asset.id == asset_id and asset.state == "ready" and asset.probe
    assert asset.error is None and asset.revision == 1
    (root / "clips/clip.MP4").rename(root / "clips/clip.mov")

    def no_reprobe(*args):
        pytest.fail("A move between allowed extensions must still reuse the cached probe")

    monkeypatch.setattr(api, "probe_file", no_reprobe)
    moved, = api.scan_project(root).assets
    assert moved.id == asset_id and moved.probe == asset.probe and moved.revision == 1


def test_probe_disables_external_references_and_playlist_demuxers(tmp_path, monkeypatch):
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout='{"streams": [], "format": {}}')

    monkeypatch.setattr(probe.proc, "run", run)
    probe.probe_file(tmp_path / "clip.MP4")
    command, = commands
    options = dict(zip(command[1:-1:2], command[2:-1:2]))
    assert options["-protocol_whitelist"] == "file"
    assert options["-enable_drefs"] == options["-use_absolute_path"] == "0"
    allowed = set(options["-format_whitelist"].split(","))
    assert not allowed.intersection({"concat", "hls", "dash", "sdp", "image2", "image2pipe"})
    assert {"mov", "matroska", "mpegts", "wav"} <= allowed
