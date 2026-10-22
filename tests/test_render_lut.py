"""LUT preflight, frozen v2 commands and source/color ownership boundaries."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from myzing import ffmpeg_capabilities as capabilities
from myzing.color import COLOR_SPACE
from myzing.composition import ColorTransform, Composition
from myzing.render import pipeline, render_composition
from myzing.render.composition import prepare_composition
from myzing.render.graph import build_graph
from myzing.render.validation import EDLValidationError, MediaInfo, ResolvedClip, ValidatedEDL
from myzing.schemas import EDL
from test_render_composition import ROOT, forbid_work, plan


def lut_plan(tmp_path, *, strength=1, contents=None):
    c = plan(tmp_path)
    path = tmp_path / "look's [test],.cube"
    data = contents or ('LUT_3D_SIZE 2\n' + ''.join(
        f'{r} {g} {b}\n' for b in (0, 1) for g in (0, 1) for r in (0, 1)))
    path.write_bytes(data.encode())
    c.clips[0].color = ColorTransform(path.name, hashlib.sha256(path.read_bytes()).hexdigest(), strength, COLOR_SPACE)
    return c, path


def test_e2e1_v2_no_lut_commands_and_graph_are_byte_identical(monkeypatch):
    baseline = json.loads((ROOT / "tests/fixtures/render-v2-no-lut-baseline.json").read_text(encoding="utf-8"))
    c = Composition.from_dict(baseline["composition"])
    assert all(clip.color is None for clip in c.clips)
    edl = EDL.from_dict(baseline["edl"])
    v = ValidatedEDL(edl, (ResolvedClip(edl.clips[0], Path("source.mp4"), MediaInfo(2, True, False)),), (), 2, (), "landscape")
    rate = f"{c.fps.numerator}/{c.fps.denominator}"
    graph = build_graph(v, True, fonts_dir=True, fps_rate=rate)
    assert graph.graph.encode() == baseline["graph"].encode()
    for version in (6, 9):
        monkeypatch.setattr(pipeline, "ffmpeg_major_version", lambda _, v=version: v)
        cmd = pipeline._ffmpeg_command("ffmpeg", graph, Path("graph.txt"), Path("output.mp4"), v, rate)
        assert json.dumps(cmd).encode() == json.dumps(baseline["commands"][str(version)]).encode()


@pytest.mark.parametrize("strength", [0, .5, 1])
def test_hash_mismatch_precedes_cube_parser_and_all_work(tmp_path, monkeypatch, strength):
    c, path = lut_plan(tmp_path, strength=strength)
    path.write_bytes(b"malformed cube and different hash")
    forbid_work(monkeypatch)
    out, work = tmp_path / "output/video.mp4", tmp_path / "work"
    with pytest.raises(EDLValidationError, match="clip clip LUT: SHA-256 mismatch"):
        render_composition(c, out, base_dir=tmp_path, work_dir=work)
    assert not out.parent.exists() and not work.exists()


@pytest.mark.parametrize("space", ["ACEScg", "linear", "Rec.2020", "S-Log3", "SDR Rec.709/sRGB plus HDR"])
def test_unsupported_declared_space_fails_before_work(tmp_path, monkeypatch, space):
    c, _ = lut_plan(tmp_path)
    c.clips[0].color.color_space = space
    forbid_work(monkeypatch)
    with pytest.raises(EDLValidationError, match="unsupported color_space"):
        render_composition(c, tmp_path / "out.mp4", base_dir=tmp_path)


@pytest.mark.parametrize("contents", ["LUT_1D_SIZE 2\n", "LUT_3D_SIZE 2\n0 0 0\n", "LUT_3D_SIZE 2\nDOMAIN_MAX 2 2 2\n" + "0 0 0\n" * 8])
def test_hashed_but_invalid_cube_is_rejected_before_work(tmp_path, monkeypatch, contents):
    pytest.importorskip("numpy")
    c, _ = lut_plan(tmp_path, contents=contents)
    forbid_work(monkeypatch)
    with pytest.raises(EDLValidationError, match="clip clip LUT:"):
        render_composition(c, tmp_path / "out.mp4", base_dir=tmp_path)


def test_missing_cube_and_network_cube_fail_without_work(tmp_path, monkeypatch):
    c, path = lut_plan(tmp_path)
    path.unlink()
    forbid_work(monkeypatch)
    with pytest.raises(EDLValidationError, match="missing asset"):
        prepare_composition(c, tmp_path)
    c.clips[0].color.lut_path = "https://example.invalid/look.cube"
    with pytest.raises(EDLValidationError, match="local file path"):
        prepare_composition(c, tmp_path)


def test_lut3d_preflight_precedes_media_probe_and_work(tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    c, _ = lut_plan(tmp_path)
    monkeypatch.setattr(capabilities, "_filters_for_executable", lambda _: frozenset({"ass"}))
    monkeypatch.setattr(capabilities.shutil, "which", lambda _: "ffmpeg")
    forbid_work(monkeypatch)
    out, work = tmp_path / "output/video.mp4", tmp_path / "work"
    with pytest.raises(pipeline.RenderError, match="requires the lut3d filter"):
        render_composition(c, out, base_dir=tmp_path, work_dir=work)
    assert not out.parent.exists() and not work.exists()


@pytest.mark.parametrize("flags", ["TSC", "TS"])
def test_lut3d_capability_accepts_ffmpeg_6_and_9_listing(tmp_path, monkeypatch, flags):
    capabilities._filters_for_executable.cache_clear()
    monkeypatch.setattr(capabilities.shutil, "which", lambda _: str(tmp_path / "ffmpeg"))
    monkeypatch.setattr(capabilities.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(
        a[0], 0, f" {flags} lut3d V->V Adjust colors using a 3D LUT.\n", ""))
    try:
        capabilities.require_lut3d()
    finally:
        capabilities._filters_for_executable.cache_clear()


@pytest.mark.parametrize("location", ["format", "stream"])
def test_probe_keeps_log_profile_tags_and_rejects_before_work(tmp_path, monkeypatch, location):
    c = plan(tmp_path)
    payload = {"format": {"duration": "3"}, "streams": [{"codec_type": "video"}]}
    target = payload["format"] if location == "format" else payload["streams"][0]
    target["tags"] = {"camera_gamma": "S-Log3"}
    monkeypatch.setattr(pipeline.shutil, "which", lambda _: "ffprobe")
    monkeypatch.setattr(pipeline.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, json.dumps(payload), ""))
    out, work = tmp_path / "output/video.mp4", tmp_path / "work"
    with pytest.raises(EDLValidationError, match="Unsupported LOG/HDR"):
        render_composition(c, out, base_dir=tmp_path, work_dir=work)
    assert not out.parent.exists() and not work.exists()


def test_lut_inputs_cannot_be_overwritten_by_output_or_work(tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    c, path = lut_plan(tmp_path)
    original = path.read_bytes()
    with pytest.raises(pipeline.RenderError, match="overwrite an input"):
        render_composition(c, path, base_dir=tmp_path)
    work = tmp_path / "work"
    (work / "luts").mkdir(parents=True)
    moved = work / "luts/clip-0000.cube"
    moved.write_bytes(original)
    c.clips[0].color.lut_path = str(moved)
    monkeypatch.setattr("myzing.render.composition.require_lut3d", lambda _: None)
    monkeypatch.setattr(pipeline, "probe_media", lambda *a, **kw: MediaInfo(3, True, False))
    with pytest.raises(pipeline.RenderError, match="overwrite an input"):
        render_composition(c, tmp_path / "out.mp4", base_dir=tmp_path, work_dir=work)
    assert moved.read_bytes() == original


def test_prepared_lut_snapshot_does_not_reread_mutated_source(tmp_path):
    pytest.importorskip("numpy")
    from myzing.color.cube import apply_cube, read_cube
    from myzing.render.color import write_luts
    c, path = lut_plan(tmp_path, strength=.5)
    prepared = prepare_composition(c, tmp_path)
    path.write_bytes(b"changed after preparation")
    work = tmp_path / "work"
    write_luts(prepared.composition, prepared.luts, prepared.lut_paths, work)
    assert apply_cube([[.2, .4, .7]], read_cube(work / "luts/clip-0000.cube"))[0].tolist() == pytest.approx([.2, .4, .7])
    # Queued MCP jobs call prepare_composition again, so stale hashes fail there.
    with pytest.raises(EDLValidationError, match="SHA-256 mismatch"):
        prepare_composition(c, tmp_path)
