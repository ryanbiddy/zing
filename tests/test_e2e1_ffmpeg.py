"""Regressions exposed by E2E1. Every input is generated locally with lavfi."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from myzing import storage
from myzing.composition import AssetRef, Composition, CompositionClip
from myzing.match import api
from myzing.match.state import read
from myzing.schemas import Breakdown, VideoMeta, Word

pytestmark = pytest.mark.ffmpeg


def ffmpeg(*args):
    result = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", *map(str, args)],
                            capture_output=True, timeout=90)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return result.stdout


def test_invalid_rendered_asr_keeps_visual_audio_inspection(tmp_path, zing_workspace):
    pytest.importorskip("PIL.Image")
    video = tmp_path / "rendered.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=red:s=160x90:r=30:d=1",
           "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", video)
    b = Breakdown(VideoMeta(str(video), "file", duration=1, fps=30, media_path=str(video)),
                  words=[Word("valid", .1, .5), Word("invalid", .98, .98)])
    storage.save_breakdown(b, slug="rendered")
    path = storage.breakdown_dir("rendered") / "breakdown.json"
    before = path.read_bytes()
    result = api._inspect(video, tmp_path / "timeline.png", {"path": str(path), "slug": "rendered"}, zing_workspace, 1)
    assert Path(result["outputs"][0]).read_bytes().startswith(b"\x89PNG")
    assert result["inspection"]["transcript_origin"] == "none"
    assert not result["inspection"]["rows"][0]["words"]
    assert result["inspection"]["rows"][0]["waveform"]["peak_rms"] > .01
    assert "ASR transcript omitted" in result["warnings"][0]
    assert "0.98-0.98" in result["warnings"][0]
    assert path.read_bytes() == before


@pytest.mark.parametrize("matrix", ["bt470bg", "smpte170m"])
def test_sdr_601_matrix_measure_apply_and_render_keep_colors(tmp_path, monkeypatch, matrix):
    np = pytest.importorskip("numpy")
    from myzing.color.cube import make_cube, write_cube
    from myzing.color.looks import transform_for
    from myzing.color.measure import measure_video
    from myzing.color.media import apply_video, frame, probe, sha256
    from myzing.composition.models import ColorTransform
    from myzing.render.composition import render_composition

    monkeypatch.chdir(tmp_path)
    source = tmp_path / "601.mkv"
    ffmpeg("-f", "lavfi", "-i", "smptebars=s=320x180:r=30:d=1",
           "-vf", "scale=in_color_matrix=bt601:out_color_matrix=bt601:out_range=tv,format=yuv444p",
           "-colorspace", matrix, "-color_primaries", "bt709", "-color_trc", "bt709", "-c:v", "ffv1", source)
    digest = sha256(source)
    # Independent decoder explicitly applies the declared matrix.
    oracle = np.frombuffer(ffmpeg("-i", source, "-vf", "scale=in_color_matrix=bt601,format=rgb24",
                                 "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"),
                           dtype=np.uint8).reshape(180, 320, 3).astype(float) / 255
    measured, _, _ = measure_video(source, count=1)
    assert any("BT.601" in w for w in measured.warnings)
    np.testing.assert_allclose(frame(source, .5, 320, 180), oracle, atol=1 / 255)
    lut = write_cube(make_cube(transform_for("neutral")), tmp_path / "identity.cube")
    applied = Path(apply_video(lut, source, tmp_path / "applied.mp4")["output_path"])
    outputs = [applied]
    for graded in (False, True):
        color = ColorTransform(str(lut), sha256(lut), 1.0, "SDR Rec.709/sRGB") if graded else None
        plan = Composition(assets=[AssetRef("source", str(source), digest)],
            clips=[CompositionClip(str(source), 0, 1, 0, id="clip", asset_id="source", color=color)], width=320, height=180)
        output = tmp_path / f"render-{graded}.mp4"
        render_composition(plan, output)
        outputs.append(output)
    for output in outputs:
        metadata = probe(output)[3]
        assert metadata["color_space"] == metadata["color_primaries"] == metadata["color_transfer"] == "bt709"
        error = np.abs(frame(output, .5, 320, 180) - oracle) * 255
        # The renderer delivers 4:2:0 H.264; allow matrix rounding and chroma
        # subsampling at bar edges (standalone apply uses 4:4:4).
        assert error.mean() < 3, (output, error.mean())
        assert np.percentile(error, 95) <= 8 + 1e-9, (output, np.percentile(error, 95))
    assert sha256(source) == digest


@pytest.mark.parametrize("rate", ["30/1", "30000/1001"])
def test_fractional_cut_chain_stays_on_absolute_video_clock(tmp_path, rate):
    np = pytest.importorskip("numpy")
    from myzing.project.models import Rational
    from myzing.render.composition import render_composition
    from myzing.composition import frame_index

    sources = []
    for color in ("red", "blue"):
        path = tmp_path / f"{color}.mp4"
        ffmpeg("-f", "lavfi", "-i", f"color={color}:s=160x90:r=30:d=1",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", path)
        sources.append(path)
    fps = Rational(*map(int, rate.split('/')))
    length = .253
    plan = Composition(assets=[AssetRef(str(i), str(p), None) for i, p in enumerate(sources)],
        clips=[CompositionClip(str(sources[i % 2]), .019, .019 + length, i * length,
                               id=f"clip-{i}", asset_id=str(i % 2)) for i in range(12)],
        width=160, height=90, fps=fps)
    output = tmp_path / "fractional.mp4"
    render_composition(plan, output)
    decoded = np.frombuffer(ffmpeg("-i", output, "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"),
                            dtype=np.uint8).reshape(-1, 90, 160, 3)
    colors = decoded[:, 45, 80].argmax(axis=1)
    cuts = list(np.flatnonzero(colors[1:] != colors[:-1]) + 1)
    expected = [frame_index(i * length, fps, rounding="nearest") for i in range(1, 12)]
    assert cuts == expected
    assert len(decoded) == frame_index(12 * length, fps, rounding="nearest")


def test_cut_audio_declick_preserves_placement_and_interior(tmp_path):
    np = pytest.importorskip("numpy")
    from myzing.render.composition import render_composition
    paths = []
    for i, level in enumerate((.3, -.3)):
        path = tmp_path / f"dc-{i}.mkv"
        ffmpeg("-f", "lavfi", "-i", "color=gray:s=160x90:r=30:d=1",
               "-f", "lavfi", "-i", f"aevalsrc={level}:s=48000:d=1",
               "-c:v", "ffv1", "-c:a", "pcm_f32le", path)
        paths.append(path)
    plan = Composition(assets=[AssetRef(str(i), str(p), None) for i, p in enumerate(paths)],
        clips=[CompositionClip(str(p), .1, .6, i * .5, id=f"clip-{i}", asset_id=str(i)) for i, p in enumerate(paths)],
        width=160, height=90)
    output = tmp_path / "declick.mp4"
    render_composition(plan, output)
    audio = np.frombuffer(ffmpeg("-i", output, "-vn", "-ac", "1", "-ar", "48000", "-f", "f32le", "pipe:1"), dtype='<f4')
    assert np.max(np.abs(np.diff(audio[23900:24100]))) < .025
    # No fade moves the cut or attenuates the body of either source span.
    assert audio[4800:19200].mean() == pytest.approx(.3, abs=.025)
    assert audio[28800:43200].mean() == pytest.approx(-.3, abs=.025)
    hot = tmp_path / "hot.mkv"
    ffmpeg("-f", "lavfi", "-i", "color=gray:s=160x90:r=30:d=1",
           "-f", "lavfi", "-i", "aevalsrc=1.2*sin(2*PI*997*t)*between(t\\,.2\\,.8):s=48000:d=1",
           "-c:v", "ffv1", "-c:a", "pcm_f32le", hot)
    hot_plan = Composition(assets=[AssetRef("hot", str(hot), None)],
        clips=[CompositionClip(str(hot), 0, 1, 0, id="hot", asset_id="hot")], width=160, height=90)
    limited = tmp_path / "limited.mp4"
    render_composition(hot_plan, limited)
    pcm = np.frombuffer(ffmpeg("-i", limited, "-vn", "-ac", "2", "-ar", "192000", "-f", "f32le", "pipe:1"), dtype='<f4').reshape(-1, 2)
    assert np.max(np.abs(pcm)) < 10 ** (-1 / 20)  # encoded true peak below -1 dB
    active = np.flatnonzero(np.max(np.abs(pcm), axis=1) > .1)
    assert abs(active[0] / 192000 - .2) < .002
    assert abs(active[-1] / 192000 - .8) < .002


def test_excluded_invalid_words_reach_planning_summary(tmp_path, zing_workspace):
    from tools.plan_examples import example_project, write_json
    from myzing.director import plan_drafts
    from myzing.match.evidence import markdown

    project, _, _ = example_project(tmp_path / "project", media=True)
    path = project / "breakdowns/take-2/breakdown.json"
    b = read(path)
    b["words"][0]["end"] = b["words"][0]["start"]
    write_json(path, b)
    result = plan_drafts(project, project / "recipe.json", project / "plans", seed=17, repair_asr=False)
    warnings = result["summary"]["warnings"]
    assert any("Excluded take-2.mp4" in w and "zero duration" in w for w in warnings)
    summary = {"project": str(project), "summary": "Planning review", "drafts": {}, "warnings": warnings}
    assert "zero duration" in markdown(summary)
    # Keep the malformed measurement for correction; do not guess a duration.
    assert read(path) == b
