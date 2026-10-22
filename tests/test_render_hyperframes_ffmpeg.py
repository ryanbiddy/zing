"""P10b CI gate: real ProRes alpha and v2 graph, with no Node dependency."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from myzing.composition import CompositionAudio
from myzing.project.models import Rational
from myzing.render import hyperframes_adapter as hf, pipeline, render_composition

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.eval.render_hyperframes_fixture import fixture, run


def decode(path, width=320, height=180, alpha=False):
    np = pytest.importorskip("numpy")
    raw = run(["-i", path, "-map", "0:v:0", "-vf", "scale=in_color_matrix=bt709:in_range=tv:out_range=pc",
               "-f", "rawvideo", "-pix_fmt", "rgba" if alpha else "rgb24", "pipe:1"])
    return np.frombuffer(raw, dtype=np.uint8).reshape(-1, height, width, 4 if alpha else 3).astype(float)


def generated_overlay(plan, output, **kwargs):
    """Straight RGB is constant even at zero/half alpha; double multiplication fails."""
    np = pytest.importorskip("numpy")
    rate = hf.plan_rate(plan.fps)
    count = round(Fraction(str(plan.duration)) * rate)
    rgba = np.zeros((count, plan.height, plan.width, 4), dtype=np.uint8)
    rgba[:, :, :, :3] = [230, 50, 80]
    # Non-microsecond rational boundaries catch framesync choosing the prior frame.
    # Visible in [7, 65): an opaque center with wide 50% edges, on transparency.
    rgba[7:65, 55:125, 80:240, 3] = 128
    rgba[7:65, 65:115, 96:224, 3] = 255
    run(["-f", "rawvideo", "-pixel_format", "rgba", "-video_size", f"{plan.width}x{plan.height}",
         "-framerate", plan.fps, "-i", "pipe:0", "-an",
         "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuva444p10le",
         "-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p10le",
         "-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", output], input=rgba.tobytes())


@pytest.fixture
def seam(monkeypatch):
    calls = []
    monkeypatch.setattr(hf, "check_install", lambda **kw: {})
    def render(plan, output, **kwargs):
        calls.append(copy.deepcopy(plan))
        generated_overlay(plan, output, **kwargs)
    monkeypatch.setattr(hf, "render_hyperframes", render)
    return calls


@pytest.mark.ffmpeg
@pytest.mark.parametrize("fps", [Rational(30, 1), Rational(30000, 1001)])
def test_alpha_grade_dissolve_layer_order_and_exact_timing(tmp_path, seam, fps):
    np = pytest.importorskip("numpy")
    c = fixture(tmp_path / "assets", fps, width=320, height=180)
    c.accepted_unsafe_layouts = [c.captions[0].id]
    # Force an opaque ASS plate to overlap HyperFrames and establish z-order.
    ass = c.captions[1]
    ass.layout = replace(ass.layout, box=replace(ass.layout.box, x=.35, y=.42, width=.3, height=.16))
    ass.text = "TOP"
    ass.style.box_color = "#204080"
    base = replace(c, captions=[], accepted_unsafe_layouts=[])
    baseline = render_composition(base, tmp_path / "base.mp4", work_dir=tmp_path / "base-work")
    with_ass = render_composition(replace(c, captions=[ass], accepted_unsafe_layouts=[]), tmp_path / "ass.mp4", work_dir=tmp_path / "ass-work")
    result = render_composition(c, tmp_path / "mixed.mp4", work_dir=tmp_path / "work")
    decoded, cut, ass_only = (decode(r.output_path) for r in (result, baseline, with_ass))
    assert decoded.shape[0] == cut.shape[0] == 72
    assert len(seam) == 1 and len(seam[0].captions) == 1
    # Outside the overlay, footage stays graded, including the dissolve window.
    np.testing.assert_allclose(decoded[:, 10:40, 10:70], cut[:, 10:40, 10:70], atol=5)
    for n in (7, 18, 30, 36, 42, 64):
        np.testing.assert_allclose(np.median(decoded[n, 68:72, 100:220], axis=(0, 1)), [230, 50, 80], atol=5)
        expected = np.array([230, 50, 80]) * (128 / 255) + cut[n, 80:100, 84:92] * (127 / 255)
        np.testing.assert_allclose(decoded[n, 80:100, 84:92], expected, atol=6)
        # ASS plate and text win in overlap and are unchanged by either LUT.
        # Compare the interior distribution; H.264 can ring at isolated glyph edges.
        ass_error = np.abs(decoded[n, 80:98, 120:200] - ass_only[n, 80:98, 120:200])
        assert np.median(ass_error) <= 2 and np.percentile(ass_error, 99) <= 5
    # Stay clear of ASS's plate/chroma edge when measuring overlay off frames.
    np.testing.assert_allclose(decoded[:7, 60:72, 100:220], cut[:7, 60:72, 100:220], atol=5)
    np.testing.assert_allclose(decoded[65:, 60:72, 100:220], cut[65:, 60:72, 100:220], atol=5)
    centers = np.median(decoded[:, 68:72, 100:220], axis=(1, 2))
    visible = np.flatnonzero(np.max(np.abs(centers - [230, 50, 80]), axis=1) < 8)
    assert visible.tolist() == list(range(7, 65))
    # The baseline is actually graded; a LUT bypass cannot satisfy this test.
    plain = render_composition(replace(base, clips=[replace(clip, color=None) for clip in c.clips]),
                               tmp_path / "plain.mp4", work_dir=tmp_path / "plain-work")
    assert np.abs(cut - decode(plain.output_path)).mean() > 15
    assert result.filtergraph.index("lut3d=") < result.filtergraph.index("xfade=") < result.filtergraph.index("overlay=") < result.filtergraph.index("filename='captions.ass'")
    p = replace(seam[0], background={"color": "#000000"})
    probe = hf.verify_output(result.output_path, p)
    assert Fraction(probe["streams"][0]["avg_frame_rate"]) == Fraction(fps.numerator, fps.denominator)


@pytest.mark.ffmpeg
def test_one_overlay_for_all_events_cache_reuse_and_audio_input_indices(tmp_path, seam):
    np = pytest.importorskip("numpy")
    c = fixture(tmp_path / "assets", width=320, height=180)
    first = c.captions[0]
    second = replace(first, id="another", layout=replace(first.layout, id="another"))
    c.captions = [first, second]
    c.audio = [CompositionAudio(id="music", asset_id="asset-0", src=c.assets[0].path, kind="music", role="music", gain_db=-12)]
    output, work = tmp_path / "out.mp4", tmp_path / "work"
    result = render_composition(c, output, work_dir=work)
    first_pixels = decode(output)
    overlay = next((work / "hyperframes-overlays").glob("*.mov"))
    original = overlay.stat().st_mtime_ns
    rerun = render_composition(c, output, work_dir=work)
    assert len(seam) == 1 and len(seam[0].captions) == 2
    assert overlay.stat().st_mtime_ns == original
    assert rerun.command == result.command
    np.testing.assert_array_equal(first_pixels, decode(output))
    assert "[3:v:0]settb" in result.filtergraph  # Two footage inputs + music.
    assert not (work / "captions.ass").exists()
    audio = run(["-i", output, "-map", "0:a:0", "-f", "f32le", "-ac", "1", "pipe:1"])
    assert np.sqrt(np.mean(np.frombuffer(audio, dtype=np.float32) ** 2)) > .03
    first.style = replace(first.style, color="#123456")
    render_composition(c, output, work_dir=work)
    assert len(seam) == 2 and len(list((work / "hyperframes-overlays").glob("*.mov"))) == 2


@pytest.mark.ffmpeg
@pytest.mark.parametrize("mismatch", ["size", "duration", "fps", "alpha"])
def test_wrong_overlay_fails_before_final_encode_and_preserves_output(tmp_path, monkeypatch, seam, mismatch):
    c = fixture(tmp_path / "assets", width=320, height=180)
    output = tmp_path / "out.mp4"
    output.write_bytes(b"previous render")
    def wrong(plan, path, **kwargs):
        changed = replace(plan, **{"size": {"width": 322}, "duration": {"duration": 2.5},
                                  "fps": {"fps": 25}, "alpha": {}}[mismatch])
        generated_overlay(changed, path)
        if mismatch == "alpha":
            opaque = path.with_name("opaque.mov")
            run(["-i", path, "-an", "-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le", opaque])
            opaque.replace(path)
    monkeypatch.setattr(hf, "render_hyperframes", wrong)
    with pytest.raises(pipeline.RenderError, match="ffprobe verification failed"):
        render_composition(c, output, work_dir=tmp_path / "work")
    assert output.read_bytes() == b"previous render"
    assert not (tmp_path / "work/filter graph.txt").exists()


@pytest.mark.skipif(os.environ.get("ZING_REQUIRE_HYPERFRAMES") != "1", reason="set ZING_REQUIRE_HYPERFRAMES=1 for real alpha render/composite (v2 pipeline)")
def test_real_hyperframes_rational_pipeline_and_straight_alpha_edges(tmp_path, monkeypatch):
    np = pytest.importorskip("numpy")
    real_render = hf.render_hyperframes
    monkeypatch.setattr(hf, "render_hyperframes", lambda *a, **kw: real_render(*a, **kw, verify_seeks=True))
    c = fixture(tmp_path / "assets", Rational(30000, 1001), width=320, height=180)
    # White antialiased glyph edges must contain unassociated white RGB.
    c.captions[0].style = replace(c.captions[0].style, color="#FFFFFF", highlight="#FFFFFF")
    c.captions[0].template = "phrase-highlight"
    result = render_composition(c, tmp_path / "real.mp4", work_dir=tmp_path / "work")
    overlay = next((tmp_path / "work/hyperframes-overlays").glob("*.mov"))
    rgba = decode(overlay, alpha=True)
    assert len(rgba) == 72
    edge = (rgba[18, :, :, 3] > 32) & (rgba[18, :, :, 3] < 224)
    assert edge.sum() > 50
    assert np.median(rgba[18, :, :, :3][edge]) > 240  # Premultiplied RGB would be dark.
    base = render_composition(replace(c, captions=[c.captions[1]]), tmp_path / "base.mp4", work_dir=tmp_path / "base-work")
    rgb, cut = decode(result.output_path), decode(base.output_path)
    a = rgba[18, :, :, 3:4] / 255
    expected = rgba[18, :, :, :3] * a + cut[18] * (1 - a)
    assert np.mean(np.abs(rgb[18][edge] - expected[edge])) < 10
    assert not rgba[:6, :, :, 3].any() and not rgba[66:, :, :, 3].any()
    metadata = json.loads(next((tmp_path / "work/hyperframes-overlays").glob("*.json")).read_text())
    p = hf.HyperframesPlan.from_dict(metadata["plan"])
    hf.verify_output(result.output_path, replace(p, background={"color": "#000000"}))
