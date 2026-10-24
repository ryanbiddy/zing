"""The converter and publication boundaries always run without Node/FFmpeg."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

from myzing.composition import CompositionCaption, CaptionStyle, FontAsset
from myzing.layout.types import Box, EventLayout, Keyframe, OverlapCheck
from myzing.project.models import Rational
from myzing.schemas import Word
from myzing.render import hyperframes_adapter as hf
from myzing.render.hyperframes_v2 import captions_to_plan
from myzing.render.hyperframes_publish import atomic_publish, publish_pair, reserve_output


@pytest.fixture
def caption(tmp_path):
    font = tmp_path / "font's folder/test.ttf"
    font.parent.mkdir()
    font.write_bytes(b"unit fixture; no font decoder needed")
    return CompositionCaption(id="c1", text="one two", start=.2, end=1.4,
        all_caps=False, word_timed=True, words=[Word("one", .2, .6), Word("two", .8, 1.4)],
        layout=EventLayout("c1", .2, 1.4, "fixture", OverlapCheck(True), box=Box(.1, .2, .8, .3)),
        font=FontAsset(str(font), hashlib.sha256(font.read_bytes()).hexdigest(), "OFL-1.1"),
        style=CaptionStyle(44, outline_width=1.5), backend="hyperframes", template="phrase-highlight")


def convert(events, **kwargs):
    return captions_to_plan(events, **({"width": 640, "height": 360, "fps": Rational(30, 1), "duration": 3} | kwargs))


def test_converter_exact_values_selection_and_immutability(caption, tmp_path):
    caption.font.path = str(Path(caption.font.path).relative_to(tmp_path))
    original = copy.deepcopy(caption.to_dict())
    ass = CompositionCaption(id="ass", text="other", start=0, end=1, word_timed=False)
    p = convert([ass, caption], base_dir=tmp_path).to_dict()
    assert p["background"] == {"transparent": True}
    assert len(p["captions"]) == 1
    e = p["captions"][0]
    assert e["words"] == [{"text": "one", "start": .2, "end": .6}, {"text": "two", "start": .8, "end": 1.4}]
    assert e["box"] == {"x": .1, "y": .2, "width": .8, "height": .3}
    assert e["style"] == {"font": str((tmp_path / caption.font.path).resolve()), "font_sha256": caption.font.sha256,
        "size": 44, "color": "#FFFFFF", "highlight": "#FFFF00", "outline_color": "#000000", "outline_width": 1.5}
    assert caption.to_dict() == original


def test_converter_accepts_joined_currency_without_retiming(caption):
    caption.text = "$3,000.50"
    caption.words = [Word("$3", .2, .5), Word(",000", .5, .9), Word(".50", .9, 1.4)]
    event = convert([caption]).captions[0]
    assert event["words"] == [{"text": w.text, "start": w.start, "end": w.end} for w in caption.words]


def test_converter_path_caps_colors_and_reducible_rate(caption):
    caption.template, caption.all_caps = "kinetic", True
    caption.style.box_color = "#204080"
    caption.layout = EventLayout("c1", .2, 1.4, "path", OverlapCheck(True), path=[
        Keyframe(.2, Box(.1, .2, .5, .3)), Keyframe(.7, Box(.2, .1, .6, .4)), Keyframe(1.4, Box(.3, .2, .5, .3))])
    e = convert([caption], fps=Rational(60, 2)).captions[0]
    assert e["template"] == "kinetic" and e["words"][0]["text"] == "ONE"
    assert [k["time"] for k in e["path"]] == [.2, .7, 1.4]
    assert e["path"][1]["box"] == {"x": .2, "y": .1, "width": .6, "height": .4}
    assert e["style"]["box_color"] == "#204080"


@pytest.mark.parametrize("change,match", [
    (lambda c: setattr(c.font, "sha256", "0" * 64), "SHA-256 mismatch"),
    (lambda c: setattr(c.font, "path", "absent.ttf"), "missing file"),
    (lambda c: setattr(c.font, "path", "https://example.com/font.ttf"), "local file"),
    (lambda c: setattr(c, "word_timed", False), "per-word timings"),
    (lambda c: setattr(c, "words", []), "requires words"),
    (lambda c: setattr(c, "text", "different phrase"), "phrase text"),
    (lambda c: setattr(c, "template", "shader"), "Invalid CompositionCaption"),
    (lambda c: setattr(c, "layout", None), "needs layout"),
    (lambda c: setattr(c, "layout", EventLayout("c1", .2, 1.4, "shrink", OverlapCheck(True), box=Box(.1, .2, .5, .2), scale=.7)), "layout.scale"),
])
def test_converter_rejects_unsupported(caption, change, match):
    change(caption)
    with pytest.raises(hf.HyperframesError, match=match):
        convert([caption])


@pytest.mark.parametrize("options", [{"fps": Rational(30000, 1001)}, {"width": 641}, {"duration": 3.001}, {"duration": 1}])
def test_converter_rejects_output_constraints(caption, options):
    with pytest.raises(hf.HyperframesError):
        convert([caption], **options)


def test_duplicate_and_empty_selection(caption):
    with pytest.raises(hf.HyperframesError, match="Duplicate"):
        convert([caption, caption])
    assert convert([]).captions == []


def test_font_changed_after_conversion_rejected(caption, tmp_path):
    p = convert([caption])
    Path(caption.font.path).write_bytes(b"changed after validation")
    with pytest.raises(hf.HyperframesError, match="SHA-256 mismatch"):
        hf.write_plan(p, tmp_path / "plan.json")


def test_atomic_publish_refuses_racer_and_allows_explicit_overwrite(tmp_path):
    src, dst = tmp_path / "source", tmp_path / "output"
    src.write_bytes(b"complete new bytes")
    with reserve_output(dst):
        dst.write_bytes(b"racing writer")
        with pytest.raises(FileExistsError):
            atomic_publish(src, dst)
    assert dst.read_bytes() == b"racing writer"
    with reserve_output(dst, overwrite=True):
        atomic_publish(src, dst, overwrite=True)
    assert dst.read_bytes() == src.read_bytes()
    assert not list(tmp_path.glob("*.part"))


def test_receipt_collision_and_lock_refuse_before_render(tmp_path):
    out = tmp_path / "out.mp4"
    receipt = Path(str(out) + ".receipt.json")
    receipt.write_text("keep")
    with pytest.raises(FileExistsError, match="receipt"):
        with reserve_output(out):
            pytest.fail("must not reserve")
    assert receipt.read_text() == "keep" and not out.exists()
    with reserve_output(out, overwrite=True):
        with pytest.raises(FileExistsError):
            with reserve_output(out, overwrite=True):
                pytest.fail("concurrent writer")


def test_pair_rolls_back_new_receipt_on_output_collision(tmp_path):
    src, out = tmp_path / "source", tmp_path / "output"
    src.write_bytes(b"new")
    with reserve_output(out):
        out.write_bytes(b"racer")
        with pytest.raises(FileExistsError):
            publish_pair(src, out, {"version": 1})
    assert out.read_bytes() == b"racer"
    assert not Path(str(out) + ".receipt.json").exists()


def test_failed_job_is_kept_under_workspace(caption, tmp_path, monkeypatch):
    monkeypatch.setattr(hf, "check_install", lambda **kw: {k: k for k in ("browser", "sidecar", "ffmpeg", "ffprobe", "node")})
    def fail(*args, **kwargs):
        raise hf.HyperframesError("synthetic failure")
    monkeypatch.setattr(hf, "_run_process", fail)
    output = tmp_path / "separate/overlay.mov"
    with pytest.raises(hf.HyperframesError, match="job retained at"):
        hf.render_hyperframes(convert([caption]), output, workspace=tmp_path / "workspace")
    assert len(list((tmp_path / "workspace/hyperframes/jobs").glob("hf-job-*/plan.json"))) == 1
    assert list(output.parent.iterdir()) == []


@pytest.mark.skipif(os.environ.get("ZING_REQUIRE_HYPERFRAMES") != "1", reason="set ZING_REQUIRE_HYPERFRAMES=1 for real alpha render/composite")
def test_real_v2_overlay_and_composite(tmp_path):
    path = Path(__file__).resolve().parents[1] / "tools/hyperframes-sidecar/overlay-proof.py"
    spec = importlib.util.spec_from_file_location("overlay_proof", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.run_proof(tmp_path / "proof")
    assert result["checked_frames"] == 90
    assert result["word_boundary_error_frames"] <= 1
    assert result["max_path_error_fraction"] <= .02
