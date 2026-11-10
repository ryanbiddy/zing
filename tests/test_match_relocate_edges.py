"""Legacy moves keep usable sources and trust only project state."""

import os
import shutil
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing.match.state import Checkpoints, resolve_data, write
from myzing.project import api
from myzing.project.models import ProjectError
from myzing.project.paths import map_paths, previous_roots, relocate, resolve_path
from myzing.project.probe import parse_probe
from myzing.studio.models import load_session


@pytest.fixture
def project(tmp_path, monkeypatch, zing_workspace):
    root, target = tmp_path / "proj-a", tmp_path / "proj-b"
    clips = root / "clips"
    clips.mkdir(parents=True)
    source = clips / "a.mp4"
    source.write_bytes(b"source")
    reference = tmp_path / "reference.mp4"
    reference.write_bytes(b"reference")
    probe = parse_probe({"streams": [{"codec_type": "video", "width": 320, "height": 180,
                                     "avg_frame_rate": "30/1", "r_frame_rate": "30/1"}],
                         "format": {"duration": "8"}})
    monkeypatch.setattr(api, "probe_file", lambda p: probe)
    manifest = api.init_project(str(reference), clips, root)
    data = map_paths(manifest.to_dict(), lambda p: str(root / p) if p in {"clips", "clips/a.mp4"} else p)
    write(root / "project.json", data)
    log = root / "logs" / "study.log"
    log.parent.mkdir()
    log.write_text("study", encoding="utf-8")
    write(root / "match-state.json", {"version": 1, "steps": {
        "study": {"status": "done", "log": str(log), "result": {"path": str(source), "outputs": [str(source)]},
                  "artifacts": {str(source): api.hash_file(source)}}}})
    return SimpleNamespace(root=root, target=target, source=source, manifest=data)


@pytest.mark.parametrize("load", ["manifest", "state"])
def test_copy_without_clips_keeps_original_sources(project, load):
    shutil.copytree(project.root, project.target, ignore=shutil.ignore_patterns("clips"))
    if load == "manifest":
        manifest = api.load_project(project.target)
        assert manifest.clips_root == str(project.source.parent)
        assert manifest.assets[0].path == str(project.source)
        assert api.project_status(project.target)["counts"]["ready"] == 1
    else:
        checkpoints = Checkpoints(project.target, True)
        entry = checkpoints.data["steps"]["study"]
        assert entry["result"]["path"] == str(project.source)
        assert entry["result"]["outputs"] == [str(project.source)]
        assert entry["artifacts"] == {str(project.source): api.hash_file(project.source)}


@pytest.mark.parametrize("kind", ["root", "home", "ancestor"])
@pytest.mark.parametrize("record", ["previous_roots", "legacy_root", "log", "session"])
def test_broad_previous_roots_are_ignored(tmp_path, monkeypatch, kind, record):
    root = tmp_path / "project"
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    old = {"root": Path(tmp_path.anchor), "home": home, "ancestor": tmp_path}[kind]
    source = old / "external" / "a.mp4"
    replacement = root / source.relative_to(old)
    replacement.parent.mkdir(parents=True)
    replacement.write_bytes(b"unrelated")
    state = {"version": 1, "relative_paths": True, "steps": {}}
    if record == "previous_roots":
        state["previous_roots"] = [str(old)]
    elif record == "legacy_root":
        state["steps"]["study"] = {"legacy_root": str(old)}
    elif record == "log":
        state["steps"]["study"] = {"log": str(old / "logs" / "study.log")}
    else:
        write(root / "studio-session.json", {"answers": {"project": str(old)}})
    write(root / "match-state.json", state)
    assert old not in previous_roots(root)
    assert resolve_data({"path": str(source)}, root)["path"] == str(source)
    assert resolve_path(str(source), root) == source


@pytest.mark.parametrize("link", ["symlink"] + (["junction"] if os.name == "nt" else []))
def test_linked_clips_do_not_block_resume(project, tmp_path, link):
    outside = tmp_path / "media"
    project.source.parent.rename(outside)
    if link == "junction":
        import _winapi
        _winapi.CreateJunction(str(outside), str(project.source.parent))
    else:
        try:
            project.source.parent.symlink_to(outside, target_is_directory=True)
        except OSError:
            pytest.skip("symlinks are unavailable on this system")
    project.root.rename(project.target)
    assert relocate(str(project.source), project.target, [project.root]) == str(project.source)
    with pytest.raises(ProjectError, match="outside the project"):
        resolve_path("clips/a.mp4", project.target)
    checkpoints = Checkpoints(project.target, True)
    assert checkpoints.data["status"] == "running"
    assert checkpoints.data["steps"]["study"]["result"]["path"] == str(project.source)
    assert api.load_project(project.target).assets[0].path == str(project.source)


def test_workspace_breakdown_does_not_prove_a_previous_root(project, zing_workspace):
    path = zing_workspace / "breakdowns" / "shared" / "breakdown.json"
    write(path, {"source": "external"})
    write(project.root / "breakdowns" / "shared" / "breakdown.json", {"source": "local"})
    project.manifest["reference"]["study"] = {"breakdown_path": str(path)}
    write(project.root / "project.json", project.manifest)
    assert api.load_project(project.root).reference.study == {"breakdown_path": str(path)}
    assert zing_workspace not in previous_roots(project.root)
    assert resolve_path(str(path), project.root) == path


@pytest.mark.parametrize("original, copied", [(False, False), (False, True), (True, False), (True, True)])
def test_relocation_checks_both_paths(tmp_path, original, copied):
    old, root = tmp_path / "old", tmp_path / "new"
    source, target = old / "a.mp4", root / "a.mp4"
    old.mkdir()
    root.mkdir()
    if original:
        source.write_bytes(b"original")
    if copied:
        target.write_bytes(b"copy")
    write(root / "match-state.json", {"previous_roots": [str(old)]})
    expected = target if copied or not original else source
    assert relocate(str(source), root, previous_roots(root)) == str(expected)
    assert resolve_path(str(source), root) == expected


@pytest.mark.parametrize("load", ["manifest", "state", "checkpoints", "session", "paths"])
def test_fifty_paths_read_metadata_at_most_once(project, tmp_path, monkeypatch, load):
    root = project.root
    paths = [str(tmp_path / "external" / f"{i}.mp4") for i in range(50)]
    asset = project.manifest["assets"][0]
    project.manifest["assets"] = [{**asset, "id": f"asset_{i}", "path": p, "original_path": p,
                                    "source": {**asset["source"], "origin": p}} for i, p in enumerate(paths)]
    write(root / "project.json", project.manifest)
    write(root / "match-state.json", {"version": 1, "steps": {}, "outputs": paths})
    write(root / "studio-session.json", {"version": 1, "answers": {"project": str(root)},
                                         "result": {"outputs": paths}})
    counts = Counter()
    original = Path.read_text

    def read_text(path, *args, **kwargs):
        if path.parent == root and path.name in {"project.json", "match-state.json", "studio-session.json"}:
            counts[path.name] += 1
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    if load == "manifest":
        assert [a.path for a in api.load_project(root).assets] == paths
    elif load == "state":
        assert resolve_data({"outputs": paths}, root) == {"outputs": paths}
    elif load == "checkpoints":
        assert Checkpoints(root, True).data["outputs"] == paths
    elif load == "session":
        assert load_session(root).result["outputs"] == paths
    else:
        assert [str(resolve_path(p, root)) for p in paths] == paths
    assert counts and all(n <= 1 for n in counts.values()), counts


@pytest.mark.parametrize("name", ["match-state.json", "studio-session.json"])
def test_previous_roots_follow_metadata_changes(tmp_path, name):
    root, old = tmp_path / "new", tmp_path / "old"
    root.mkdir()
    assert previous_roots(root) == []
    data = {"previous_roots": [str(old)]} if name == "match-state.json" else {"answers": {"project": str(old)}}
    write(root / name, data)
    assert previous_roots(root) == [old]
    stamp = (root / name).stat().st_mtime_ns
    write(root / name, {})
    os.utime(root / name, ns=(stamp + 1_000_000_000, stamp + 1_000_000_000))
    assert previous_roots(root) == []


def test_relative_escape_is_still_refused(project):
    with pytest.raises(ProjectError, match="outside the project"):
        resolve_data({"path": "../outside/a.mp4"}, project.root)
