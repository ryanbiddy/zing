"""Offline path acceptance: real ingest, persisted assembly, and FFmpeg render."""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing import cli, mcp_server, storage
from myzing.render import assemble, pipeline, validation
from myzing.schemas import AudioTrack, Breakdown, Clip, EDL, VideoMeta
from myzing.study import api as study_api


@pytest.mark.ffmpeg
@pytest.mark.parametrize("root_mode", ["relative", "absolute", "env"])
@pytest.mark.parametrize("project_name", ["project", "creator's project"])
@pytest.mark.parametrize("move_project", [False, True], ids=["in-place", "moved"])
def test_study_assemble_render_workspace(
    tmp_path, monkeypatch, capsys, root_mode, project_name, move_project,
):
    monkeypatch.chdir(tmp_path)
    project = tmp_path / project_name
    project.mkdir()
    source = project / "source clip's.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=red:s=180x320:r=30:d=0.8",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
        ],
        check=True, capture_output=True,
    )

    # Only model-backed measurements are stubbed: no model/asset downloads.
    monkeypatch.setattr(
        study_api.transcribe_mod, "transcribe",
        lambda *a, **kw: SimpleNamespace(words=[], warnings=[], provenance={}),
    )
    monkeypatch.setattr(
        study_api.captions_mod, "read_captions",
        lambda *a, **kw: SimpleNamespace(captions=[], warnings=[], provenance={}),
    )
    workspace = project / "workspace"
    root_arg = workspace if root_mode == "absolute" else workspace.relative_to(tmp_path)
    workspace_args = ["--workspace", str(root_arg)]
    if root_mode == "env":
        monkeypatch.setenv(storage.ENV_VAR, str(root_arg))
        workspace_args = []
    assert cli.main(["study", str(source.relative_to(tmp_path)), *workspace_args]) == 0
    direction = project / "direction.json"
    direction.write_text(
        json.dumps({"keepers": [{"start": 0, "end": 0.8}]}), encoding="utf-8",
    )
    slug = storage.slug_for(str(source))
    assert cli.main([
        "assemble", slug, *workspace_args,
        "--direction", str(direction),
    ]) == 0
    edl_path = workspace / "breakdowns" / slug / "draft-edl.json"
    original_edl = edl_path.read_bytes()
    assert json.loads(original_edl)["clips"][0]["src"] == "media.mp4"
    if move_project:
        moved_project = tmp_path / "moved creator's project"
        # Both paths are children of this test's own directory.
        project.rename(moved_project)
        edl_path = moved_project / edl_path.relative_to(project)
        project = moved_project
        assert edl_path.read_bytes() == original_edl  # no relinking/reassembly
    # Render from a different CWD, so a bare media.mp4 cannot work by accident.
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    output = project / "output.mp4"
    result = cli.main([
        "render", str(edl_path), "-o", str(output),
        "--keep-work", str(project / "render work's files"),
    ])
    captured = capsys.readouterr()
    assert result == 0, captured.out + captured.err
    assert output.is_file()
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(output)],
        check=True, capture_output=True, text=True,
    )
    assert float(json.loads(probe.stdout)["format"]["duration"]) == pytest.approx(0.8, abs=0.05)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-xerror", "-i", str(output), "-f", "null", "-"],
        check=True, capture_output=True,
    )


@pytest.mark.ffmpeg
@pytest.mark.parametrize("legacy_absolute", [False, True], ids=["relative", "absolute-v1"])
def test_saved_edl_video_and_audio_paths(tmp_path, monkeypatch, legacy_absolute):
    project = tmp_path / "creator's project"
    assets = project / "assets"
    edits = project / "edits"
    assets.mkdir(parents=True)
    edits.mkdir()
    video = assets / "video clip.mp4"
    audio = assets / "music's tone.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
         "color=c=blue:s=180x320:r=30:d=0.8", "-c:v", "libx264", str(video)],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=0.8", str(audio)],
        check=True, capture_output=True,
    )
    edl = EDL(
        clips=[Clip(str(video) if legacy_absolute else "../assets/video clip.mp4", 0, 0.8, 0)],
        audio=[AudioTrack(str(audio) if legacy_absolute else "../assets/music's tone.wav", "music")],
        width=180, height=320,
    )
    edl_path = edits / "v1.json"
    edl_path.write_text(edl.to_json(), encoding="utf-8")
    if not legacy_absolute:
        moved = tmp_path / "moved project"
        project.rename(moved)  # Both paths are under this test's own directory.
        edl_path = moved / "edits" / edl_path.name
    monkeypatch.chdir(tmp_path)
    assert cli.main(["render", str(edl_path)]) == 0
    decoded = subprocess.run(
        ["ffmpeg", "-v", "error", "-xerror", "-i", str(edl_path.with_suffix(".mp4")),
         "-map", "0:a:0", "-f", "s16le", "-"],
        check=True, capture_output=True,
    )
    assert any(decoded.stdout), "the referenced audio must survive the render"


@pytest.mark.parametrize("missing_kind", ["clip", "audio"])
@pytest.mark.parametrize("voiceover", [False, True])
def test_missing_asset_fails_before_any_render_work(
    tmp_path, monkeypatch, capsys, missing_kind, voiceover,
):
    source = tmp_path / "existing.mp4"
    source.write_bytes(b"probe must never read this")
    missing = tmp_path / "moved asset's file.mp4"
    edl = EDL(clips=[Clip(source.name, 0, 1, 0)])
    if missing_kind == "clip":
        edl.clips.append(Clip(missing.name, 0, 1, 1))
    else:
        edl.audio.append(AudioTrack(missing.name, "music"))
    edl_path = tmp_path / "draft.json"
    edl_path.write_text(edl.to_json(), encoding="utf-8")
    output = tmp_path / "existing output.mp4"
    output.write_bytes(b"keep prior render")
    work = tmp_path / "work"

    def forbidden(*args, **kwargs):
        pytest.fail("missing assets must fail before probe/synthesis/FFmpeg")

    monkeypatch.setattr(pipeline, "probe_media", forbidden)
    monkeypatch.setattr(pipeline.subprocess, "run", forbidden)
    monkeypatch.setattr(pipeline, "generate_ass", forbidden)
    monkeypatch.setattr(assemble, "default_tts_provider", forbidden)
    args = ["render", str(edl_path), "-o", str(output), "--keep-work", str(work)]
    if voiceover:
        from myzing.render import command

        monkeypatch.setattr(
            command, "default_tts_provider",
            lambda *a: SimpleNamespace(synthesize=forbidden),
        )
        script = tmp_path / "voiceover.txt"
        script.write_text("A synthetic script.", encoding="utf-8")
        args += ["--voiceover-script", str(script)]
    assert cli.main(args) == 1
    error = capsys.readouterr().err
    assert str(missing) in error
    assert "Restore the file" in error and "update the EDL src" in error
    assert output.read_bytes() == b"keep prior render"
    assert not work.exists()
    assert not (tmp_path / "existing output-assets").exists()


@pytest.mark.parametrize("missing_kind", ["clip", "audio"])
def test_mcp_missing_asset_fails_before_job_dispatch(
    tmp_path, zing_workspace, monkeypatch, missing_kind,
):
    (tmp_path / "existing.mp4").write_bytes(b"fixture")
    edl = EDL(clips=[Clip("existing.mp4", 0, 1, 0)])
    if missing_kind == "clip":
        edl.clips.append(Clip("missing.mp4", 0, 1, 1))
    else:
        edl.audio.append(AudioTrack("missing.mp4", "music"))
    edl_path = tmp_path / "draft.json"
    edl_path.write_text(edl.to_json(), encoding="utf-8")
    monkeypatch.setattr(mcp_server.shutil, "which", lambda tool: tool)

    def forbidden(*args, **kwargs):
        pytest.fail("missing assets must fail before creating a render worker")

    monkeypatch.setattr(mcp_server.threading, "Thread", forbidden)
    result = mcp_server.h_render_edl(str(edl_path))
    assert result["ok"] is False
    assert str(tmp_path / "missing.mp4") in result["error"]
    assert "Restore the file" in result["error"]
    assert not (zing_workspace / "renders").exists()


def test_preflight_paths_survive_cwd_change_and_are_resolved_once(tmp_path, monkeypatch):
    (tmp_path / "clip.mp4").write_bytes(b"fixture")
    edl = EDL(clips=[Clip("clip.mp4", 0, 1, 0), Clip("clip.mp4", 1, 2, 1)])
    paths = validation.resolve_assets(edl, tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("preflight paths must be passed inward without re-resolution")

    monkeypatch.setattr(validation, "_resolve_media", forbidden)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    result = validation.validate_edl(
        edl, Path("wrong base"), lambda path: validation.MediaInfo(2, True, False),
        resolved_assets=paths,
    )
    assert [clip.path for clip in result.clips] == [tmp_path / "clip.mp4"] * 2
    (tmp_path / "clip.mp4").unlink()
    with pytest.raises(validation.EDLValidationError, match="Restore the file"):
        validation.validate_edl(edl, tmp_path, forbidden, resolved_assets=paths)


def test_nested_workspace_boundary_reuses_resolved_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = storage.resolve_workspace(Path("creator's workspace"))

    def forbidden(*args, **kwargs):
        pytest.fail("nested boundaries must reuse the pinned workspace")

    with storage.use_workspace(root):
        monkeypatch.setattr(Path, "resolve", forbidden)
        assert storage.resolve_workspace() == root


def test_mcp_study_pins_relative_workspace_and_inputs_before_dispatch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(storage.ENV_VAR, "creator's workspace")
    root = tmp_path / "creator's workspace"
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fixture")
    monkeypatch.setattr(mcp_server.shutil, "which", lambda tool: tool)
    monkeypatch.setattr(mcp_server, "_JOBS", {})

    def study(source_arg, kept_media=None):
        assert source_arg == str(source)
        assert kept_media == str(source)
        assert storage.workspace_root() == root
        return Breakdown(meta=VideoMeta(source_url=source_arg, platform="file"))

    monkeypatch.setattr(mcp_server, "_study_api", lambda: SimpleNamespace(study=study))

    class DeferredThread(threading.Thread):
        def start(self):
            pass  # Execute after changing CWD and ZING_HOME, below.

    with monkeypatch.context() as dispatch:
        dispatch.setattr(mcp_server.threading, "Thread", DeferredThread)
        result = mcp_server.h_study_video("source.mp4", kept_media="source.mp4")
    assert result["ok"] is True
    worker = mcp_server._JOBS[result["slug"]]
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv(storage.ENV_VAR, "different-workspace")
    worker.run()
    status = storage.read_status_at(root / "breakdowns" / result["slug"])
    assert status["state"] == "done", status
    assert not (elsewhere / "different-workspace").exists()


def test_mcp_render_pins_relative_workspace_and_assets_before_dispatch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(storage.ENV_VAR, "creator's workspace")
    root = tmp_path / "creator's workspace"
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fixture")
    edl_path = tmp_path / "draft.json"
    edl_path.write_text(EDL(clips=[Clip(source.name, 0, 1, 0)]).to_json(), encoding="utf-8")
    monkeypatch.setattr(mcp_server.shutil, "which", lambda tool: tool)
    monkeypatch.setattr(mcp_server, "_RENDER_JOBS", {})

    def render(edl, output, *, base_dir, resolved_assets):
        assert storage.workspace_root() == root
        assert base_dir == tmp_path
        assert output.is_absolute() and output.is_relative_to(root)
        assert resolved_assets == {source.name: source}
        return SimpleNamespace(output_path=output)

    monkeypatch.setattr(pipeline, "render_edl", render)

    class DeferredThread(threading.Thread):
        def start(self):
            pass

    with monkeypatch.context() as dispatch:
        dispatch.setattr(mcp_server.threading, "Thread", DeferredThread)
        result = mcp_server.h_render_edl("draft.json")
    assert result["ok"] is True
    worker = mcp_server._RENDER_JOBS[result["render_id"]]
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv(storage.ENV_VAR, "different-workspace")
    worker.run()
    status = storage.read_status_at(root / "renders" / result["render_id"])
    assert status["state"] == "done", status
    assert not (elsewhere / "different-workspace").exists()
