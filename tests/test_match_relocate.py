"""Project moves reuse measured work and keep reads in the current folder."""

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing import storage
from myzing.audio.models import AudioMap, Loudness, Tempo
from myzing.director.inventory import inventory
from myzing.match import api
from myzing.match.state import Checkpoints, fingerprint, interrupted, read, write
from myzing.project.probe import parse_probe
from myzing.schemas import Breakdown, Shot, VideoMeta, Word


@pytest.fixture
def project(tmp_path, monkeypatch, zing_workspace):
    root, clips = tmp_path / "proj-a", tmp_path / "clips"
    clips.mkdir()
    for i in range(3):
        (clips / f"take-{i}.mp4").write_bytes(f"source {i}".encode())
    reference = tmp_path / "reference.mp4"
    reference.write_bytes(b"reference")
    probe = parse_probe({"streams": [{"codec_type": "video", "width": 320, "height": 180,
                                     "avg_frame_rate": "30/1", "r_frame_rate": "30/1"}, {"codec_type": "audio"}],
                         "format": {"duration": "8"}})
    calls = []

    def study(source, workspace, **options):
        calls.append(source)
        folder = Path(workspace) / "breakdowns" / storage.slug_for(source)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "media.mp4").write_bytes(Path(source).read_bytes())
        return Breakdown(VideoMeta(source, "file", duration=8, fps=30, width=320, height=180,
                                   media_path="media.mp4"),
                         shots=[Shot(i, i * 2, i * 2 + 2) for i in range(4)],
                         words=[Word(text, i * 2 + .2 + j * .4, i * 2 + .4 + j * .4)
                                for i in range(4) for j, text in enumerate(("Here", "is", "our", "example."))])

    def audio(source, **options):
        return AudioMap(source, 8, 48000, 600, False, Tempo(), [], [], [], Loudness(None, None, None))

    def render(plan, video, **options):
        assert all(Path(a.path).is_absolute() and Path(a.path).is_file() for a in plan.assets)
        video.write_bytes(video.name.encode())
        return SimpleNamespace(warnings=[], audio_measurements=None)

    monkeypatch.setattr(api.projects, "probe_file", lambda p: probe)
    monkeypatch.setattr("myzing.project.probe.probe_file", lambda p: probe)
    monkeypatch.setattr(api, "study", study)
    monkeypatch.setattr(api, "capabilities", lambda: dict(fonts=False, audio=True, color=False, layout=False))
    monkeypatch.setattr(api, "_inspect", lambda *a: {"outputs": [], "warnings": []})
    monkeypatch.setattr(api.evidence, "decode", lambda *a: {"duration": 8, "full_decode": True})
    monkeypatch.setattr("myzing.audio.api.analyze", audio)
    monkeypatch.setattr("myzing.study.ingest.probe", lambda p: {"streams": [{"codec_type": "audio"}]})
    monkeypatch.setattr("myzing.match.preflight.check", lambda *a, **k: {"problems": [], "warnings": []})
    monkeypatch.setattr("myzing.layout.framing.analyze_subjects", lambda *a, **k: ([], []))
    monkeypatch.setattr("myzing.render.composition.render_composition", render)
    monkeypatch.setattr("subprocess.run", lambda *a, **k: pytest.fail("No decoder or model is needed"))
    return SimpleNamespace(root=root, clips=clips, reference=reference, calls=calls,
                           answers=dict(target_length_seconds=6, caption_mode="none", picture_crop="off",
                                        aspect="16:9", short_side=180))


def run(project, root=None, **options):
    return api.match(str(project.reference), str(project.clips), root or project.root,
                     answers=project.answers, **options)


def finished(project):
    result = run(project)
    assert result["status"] == "ready", result
    return read(project.root / "match-state.json")


def assert_reused(project, root, before):
    calls = len(project.calls)
    result = run(project, root, resume=True)
    assert result["status"] == "ready", result
    assert set(result["reused_steps"]) == set(before["steps"]) - {"project-scan"}
    assert len(project.calls) == calls
    after = read(root / "match-state.json")
    for name in result["reused_steps"]:
        assert after["steps"][name]["result"]["checkpoint"] == before["steps"][name]["result"]["checkpoint"]
    rows, notes = inventory(root)
    assert not notes
    assert len(rows) == 3 and all(row.status == "ready" for row in rows)
    assert all(Path(row.study_path).is_relative_to(root) for row in rows)
    assert all(Path(row["plan"]).is_relative_to(root) for row in result["drafts"].values())
    return after


@pytest.mark.parametrize("move", [False, True])
def test_finished_project_reuses_steps_after_relocation(project, move, monkeypatch):
    before = finished(project)
    target = project.root.with_name("proj-b")
    if move:
        project.root.rename(target)
    else:
        shutil.copytree(project.root, target)
        monkeypatch.setenv("ZING_HOME", str(project.root))
    after = assert_reused(project, target, before)
    assert {k: v["key"] for k, v in after["steps"].items() if k != "project-scan"} == {
        k: v["key"] for k, v in before["steps"].items() if k != "project-scan"}


def test_project_with_internal_sources_reuses_after_move(project):
    project.root.mkdir()
    project.reference = project.reference.rename(project.root / "reference.mp4")
    project.clips = project.clips.rename(project.root / "clips")
    before = finished(project)
    target = project.root.with_name("proj-b")
    project.root.rename(target)
    project.reference, project.clips = target / "reference.mp4", target / "clips"
    assert_reused(project, target, before)
    (target / "drafts" / "draft-A.mp4").unlink()
    result = run(project, target, resume=True)
    assert result["status"] == "ready", result
    assert "render-A" not in result["reused_steps"]


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_copy_checks_its_own_artifacts(project, damage):
    before = finished(project)
    target = project.root.with_name("proj-b")
    shutil.copytree(project.root, target)
    video = target / "drafts" / "draft-A.mp4"
    if damage == "missing":
        video.unlink()
    else:
        video.write_bytes(b"corrupt")
    result = run(project, target, resume=True)
    assert result["status"] == "ready", result
    assert "render-A" not in result["reused_steps"]
    assert {"render-B", "render-C"} <= set(result["reused_steps"])
    assert video.read_bytes() == (project.root / "drafts" / "draft-A.mp4").read_bytes()
    assert read(project.root / "match-state.json") == before


@pytest.mark.parametrize("move", [False, True, None])
def test_old_absolute_checkpoints_reuse_after_relocation(project, monkeypatch, move):
    def save(checkpoints):
        write(checkpoints.path, {k: v for k, v in checkpoints.data.items()
                                 if k not in {"relative_paths", "previous_roots"}})

    original_audio = api._audio
    def audio(*args):
        result = original_audio(*args)
        path = Path(result["path"])
        data = read(path)
        data["source"] = str(path.parent / data["source"])
        write(path, data)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Checkpoints, "save", save)
        patch.setattr(Checkpoints, "key", lambda self, value: fingerprint(value))
        patch.setattr(api, "_audio", audio)
        patch.setattr(api, "_save_plan", lambda path, plan, root: write(path, plan.to_dict()))
        before = finished(project)
    data = read(project.root / "project.json")
    data["reference"]["study"]["breakdown_path"] = str(project.root / data["reference"]["study"]["breakdown_path"])
    write(project.root / "project.json", data)
    target = project.root.with_name("proj-b")
    if move is None:
        before = assert_reused(project, project.root, before)
    if move:
        project.root.rename(target)
    else:
        shutil.copytree(project.root, target)
        monkeypatch.setenv("ZING_HOME", str(project.root))
        for path in project.root.glob("breakdowns/*/breakdown.json"):
            path.write_text("stale original", encoding="utf-8")
    assert_reused(project, target, before)
    loaded = api.projects.load_project(target)
    assert loaded.reference.study["breakdown_path"].startswith("reference/breakdowns/")
    assert api.projects.resolve_path(loaded.reference.study["breakdown_path"], target).is_relative_to(target)
    assert_reused(project, target, read(target / "match-state.json"))


def test_external_reference_study_is_preserved(project, tmp_path):
    from myzing.project.references import resolve_reference
    api.projects.init_project(str(project.reference), project.clips, project.root)
    resolve_reference(project.root)
    manifest = api.projects.load_project(project.root)
    path = tmp_path / "other-workspace" / "breakdowns" / "reference" / "breakdown.json"
    write(path, {"measured": True})
    manifest.reference.study = {"breakdown_path": str(path)}
    api.projects._save(project.root, manifest)
    assert api.projects.load_project(project.root).reference.study == manifest.reference.study


def test_resolving_internal_reference_keeps_its_study(project):
    from myzing.project.references import resolve_reference
    project.root.mkdir()
    project.reference = project.reference.rename(project.root / "reference.mp4")
    finished(project)
    before = api.projects.load_project(project.root).reference.study
    resolve_reference(project.root)
    assert api.projects.load_project(project.root).reference.study == before


def test_written_paths_are_relative_and_external_inputs_stay_absolute(project):
    state = finished(project)
    manifest = read(project.root / "project.json")
    assert manifest["reference"]["value"] == str(project.reference)
    assert manifest["clips_root"] == str(project.clips)
    assert all(Path(a["path"]).is_absolute() for a in manifest["assets"])
    assert not Path(manifest["reference"]["study"]["breakdown_path"]).is_absolute()
    assert "\\" not in manifest["reference"]["study"]["breakdown_path"]
    for entry in state["steps"].values():
        assert entry["log"].startswith("logs/")
        for path in entry.get("artifacts", {}):
            assert not Path(path).is_absolute() or Path(path) == project.reference
        for value in entry["result"].get("outputs", []):
            assert not Path(value).is_absolute() or Path(value) == project.reference
    (project.root / project.reference.name).write_bytes(b"unrelated file")
    assert api.projects.resolve_path(str(project.reference), project.root) == project.reference
    assert api.projects.load_project(project.root).reference.resolution.path == str(project.reference)


@pytest.mark.parametrize("legacy", [False, True])
def test_studio_session_follows_its_project(tmp_path, legacy):
    from myzing.studio.models import Session, load_session, save_session
    root = tmp_path / "proj-a"
    root.mkdir()
    outside = tmp_path / "reference.mp4"
    outside.write_bytes(b"reference")
    (root / "clips").mkdir()
    (root / "draft.mp4").write_bytes(b"rendered")
    session = Session(answers={"path": "a", "project": str(root), "clips": str(root / "clips"),
                               "reference": str(outside), "music": "original"},
                      result={"path": "a", "project": str(root), "outputs": [str(root / "draft.mp4")],
                              "result": {"selected": {"path": str(root / "draft.mp4")}},
                              "output_sha256": {str(root / "draft.mp4"): "digest"}})
    save_session(root, session)
    data = read(root / "studio-session.json")
    assert data["answers"]["project"] == "." and data["answers"]["clips"] == "clips"
    if legacy:
        write(root / "studio-session.json", session.to_dict())
    target = tmp_path / "proj-b"
    shutil.copytree(root, target)
    loaded = load_session(target)
    assert loaded.answers == {**session.answers, "project": str(target), "clips": str(target / "clips")}
    assert loaded.result["outputs"] == [str(target / "draft.mp4")]
    assert loaded.result["output_sha256"] == {str(target / "draft.mp4"): "digest"}
    assert loaded.result["path"] == "a"
    assert loaded.result["result"]["selected"]["path"] == str(target / "draft.mp4")


def test_interrupted_log_follows_legacy_project(tmp_path):
    old, root = tmp_path / "proj-a", tmp_path / "proj-b"
    (old / "logs").mkdir(parents=True)
    log = old / "logs" / "render-A.log"
    log.write_text("old log", encoding="utf-8")
    write(root / "match-state.json", {"version": 1, "steps": {
        "render-A": {"status": "running", "log": str(log)}}})
    interrupted(root)
    assert log.read_text(encoding="utf-8") == "old log"
    assert "--resume" in (root / "logs" / log.name).read_text(encoding="utf-8")
    assert read(root / "match-state.json")["steps"]["render-A"]["log"] == "logs/render-A.log"
