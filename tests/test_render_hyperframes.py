"""P10b routing, preflight and cache identity without Node or media tools."""
import copy
import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from myzing.project.models import Rational
from myzing.render import hyperframes_adapter as hf, pipeline, render_composition
from myzing.render.composition import prepare_composition, unsupported_features
from myzing.render.hyperframes_cache import cached_overlay, overlay_key
from myzing.render.hyperframes_v2 import captions_to_plan
from myzing.schemas import Word
from test_render_composition import caption, plan


def hf_caption(**kwargs):
    return caption(backend="hyperframes", template="kinetic", word_timed=True,
                   words=[Word("ONE", 0, 1), Word("TWO", 1, 2)], **kwargs)


def overlay_plan(c):
    return captions_to_plan(c.captions, width=c.width, height=c.height, fps=c.fps,
                            duration=max(clip.timeline_end for clip in c.clips))


@pytest.mark.parametrize("remedy", ["install Node.js 24", "run npm ci --ignore-scripts", "set HYPERFRAMES_BROWSER_PATH"])
def test_hyperframes_preflight_fails_before_media_or_work(tmp_path, monkeypatch, remedy):
    c = plan(tmp_path, captions=[hf_caption()])
    def missing(**kwargs):
        raise hf.HyperframesError(remedy)
    monkeypatch.setattr(hf, "check_install", missing)
    monkeypatch.setattr(pipeline, "probe_media", lambda *a, **kw: pytest.fail("media work before preflight"))
    monkeypatch.setattr(pipeline, "preflight_captions", lambda *a: pytest.fail("ASS fallback"))
    with pytest.raises(pipeline.RenderError, match=remedy):
        render_composition(c, tmp_path / "out/video.mp4", work_dir=tmp_path / "work", base_dir=tmp_path)
    assert not (tmp_path / "out").exists() and not (tmp_path / "work").exists()


def test_backends_are_partitioned_and_hyperframes_does_not_use_ass_metrics(tmp_path, monkeypatch):
    import myzing.render.composition as renderer
    c = plan(tmp_path, captions=[hf_caption()])
    c.fps = Rational(120, 1)
    monkeypatch.setattr(renderer, "private_font", lambda *a: pytest.fail("HyperFrames needs original font bytes"))
    assert not unsupported_features(c)
    prepared = prepare_composition(c, tmp_path)
    assert not prepared.edl.captions and not prepared.fonts
    c.captions.append(caption(id="ass", layout=None))
    assert "ASS captions above 100 fps" in unsupported_features(c)[0]


def test_exact_rational_plan_and_unaligned_end_remedy(tmp_path):
    c = plan(tmp_path, captions=[hf_caption()])
    c.fps = Rational(30000, 1001)
    c.clips[0].src_out = 3.003
    assert overlay_plan(c).fps == "30000/1001"
    c.clips[0].src_out = 3
    with pytest.raises(hf.HyperframesError, match="align the composition end"):
        overlay_plan(c)


@pytest.mark.parametrize("rate", [True, 29.97, "30", "30/0", "-30/1", "30000/1000x", "30000000000/1000000001", 121])
def test_adapter_rejects_ambiguous_or_invalid_rates(rate):
    with pytest.raises(hf.HyperframesError, match="fps"):
        hf.plan_rate(rate)


def test_cache_identity_covers_plan_fonts_geometry_and_rate(tmp_path):
    c = plan(tmp_path, captions=[hf_caption()])
    original = overlay_plan(c)
    key = overlay_key(original)
    for changed in (
        replace(original, width=320), replace(original, height=180),
        replace(original, fps="30000/1001", duration=3.003), replace(original, duration=4),
    ):
        assert overlay_key(changed) != key
    changed = copy.deepcopy(original)
    changed.captions[0]["words"][0]["text"] = "DIFFERENT"
    assert overlay_key(changed) != key
    changed = copy.deepcopy(original)
    changed.captions[0]["style"]["color"] = "#123456"
    assert overlay_key(changed) != key
    font = tmp_path / "changed.ttf"
    font.write_bytes(b"other font bytes")
    changed = copy.deepcopy(original)
    changed.captions[0]["style"].update(font=str(font), font_sha256=hashlib.sha256(font.read_bytes()).hexdigest())
    assert overlay_key(changed) != key
    font.write_bytes(b"mutated after declaration")
    with pytest.raises(hf.HyperframesError, match="SHA-256 mismatch"):
        overlay_key(changed)
    # Moving an identical font does not invalidate content identity.
    source = c.captions[0].font
    font.write_bytes(Path(source.path).read_bytes())
    changed.captions[0]["style"]["font_sha256"] = source.sha256
    assert overlay_key(changed) == key


def test_cache_reuses_only_verified_output_and_rejects_corruption(tmp_path, monkeypatch):
    p = overlay_plan(plan(tmp_path, captions=[hf_caption()]))
    calls, probes = [], []
    def render(plan, path, **kwargs):
        calls.append(kwargs)
        path.write_bytes(b"verified overlay fixture")
    monkeypatch.setattr(hf, "render_hyperframes", render)
    monkeypatch.setattr(hf, "verify_output", lambda *a: probes.append(a) or {})
    out = cached_overlay(p, tmp_path / "work", ffmpeg="selected-ffmpeg", ffprobe="selected-ffprobe")
    assert cached_overlay(p, tmp_path / "work", ffmpeg="selected-ffmpeg", ffprobe="selected-ffprobe") == out
    assert len(calls) == 1 and len(probes) == 2
    assert calls[0]["ffmpeg"] == "selected-ffmpeg" and calls[0]["ffprobe"] == "selected-ffprobe"
    out.write_bytes(b"changed media")
    with pytest.raises(hf.HyperframesError, match="cache integrity mismatch"):
        cached_overlay(p, tmp_path / "work", ffmpeg="ffmpeg", ffprobe="ffprobe")
    assert len(calls) == 1


@pytest.mark.parametrize("patch", [
    {"duration": "3.010000"}, {"duration_ts": 90001}, {"avg_frame_rate": "29999999/1000000"},
    {"r_frame_rate": "60/1"}, {"nb_read_frames": "89"}, {"width": 638},
])
def test_overlay_metadata_must_match_exactly(tmp_path, monkeypatch, patch):
    p = overlay_plan(plan(tmp_path, captions=[hf_caption()]))
    stream = {"width": 640, "height": 360, "avg_frame_rate": "30/1", "r_frame_rate": "30/1",
              "duration": "3.000000", "duration_ts": 90000, "time_base": "1/30000",
              "nb_read_frames": "90", "codec_name": "prores", "pix_fmt": "yuva444p12le", **patch}
    monkeypatch.setattr(hf.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, json.dumps({
        "streams": [stream], "format": {"duration": "3.000000"}})))
    with pytest.raises(hf.HyperframesError, match="differs from plan"):
        hf.verify_output(tmp_path / "overlay.mov", p)
