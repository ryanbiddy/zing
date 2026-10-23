"""Generated pixels through the public API; no detector outputs injected."""

import json
from pathlib import Path

import pytest

from myzing.explain.api import explain_video

pytestmark = pytest.mark.ffmpeg


@pytest.mark.parametrize("kind", ["hard_cut", "dissolve"])
def test_explain_generated_transition(tmp_path, monkeypatch, kind):
    from tools.eval.transition_corpus import corpus_cases, generate_case
    case = next(c for c in corpus_cases("held_out") if c.kind == kind)
    source = tmp_path / "clips"
    source.mkdir()
    path = generate_case(case, source) / "clip.mp4"
    # Missing ASR must never trigger a model download.
    monkeypatch.setenv("ZING_WHISPER_MODEL", str(tmp_path / "absent-model"))
    result = explain_video(path, tmp_path / "card")
    assert result["ok"], result
    card = json.loads(Path(result["card_json"]).read_text(encoding="utf-8"))
    events = card["sections"]["transitions"]["facts"]["events"]
    match = next(e for e in events if e["signature"] == kind)
    truth = case.truth_events()[0]
    assert abs(match["start_seconds"] - truth["start_seconds"]) <= .15
    assert abs(match["end_seconds"] - truth["end_seconds"]) <= .15
    assert match["confidence"] >= .8
    if kind == "hard_cut":
        pacing = card["sections"]["pacing"]
        assert pacing["facts"]["cuts_per_minute"] > 0 or pacing["facts"]["v6_additional_cut_times"]
        if pacing["facts"]["v6_additional_cut_times"]:
            assert "Pacing uncertain" in pacing["unknowns"][0]
    from PIL import Image
    with Image.open(result["card_png"]) as image:
        assert image.width == 800 and 1000 < image.height < 8000
    from myzing.style_recipe import StyleRecipe
    StyleRecipe.from_dict(json.loads(Path(card["recipe_path"]).read_text()))


@pytest.mark.real_model(env="ZING_REQUIRE_OCR")
def test_explain_generated_caption_position_and_warm_color(tmp_path, monkeypatch):
    from test_caption_geometry_ffmpeg import draw, render
    from myzing.study.caption_models import model_paths
    try:
        model_paths()
    except RuntimeError:
        pytest.skip("caption geometry OCR models unavailable; no automatic download")
    folder = tmp_path / "clips"
    folder.mkdir()
    path = render(folder / "caption.mp4", [draw(text="CAPTION TEST", x="120", y="220", enable="between(t,0.25,1.15)")], bg="0xB87A40")
    monkeypatch.setenv("ZING_WHISPER_MODEL", str(tmp_path / "absent-model"))
    result = explain_video(path, tmp_path / "card")
    assert result["ok"], result
    card = json.loads(Path(result["card_json"]).read_text(encoding="utf-8"))
    text = card["sections"]["captions"]["facts"]["tracks"]
    assert any("CAPTION" in r["text"].upper() and r["zone"] == "lower" and abs(r["box"][1]-220/360) < .03 for r in text)
    assert card["sections"]["color"]["facts"]["ab_mean"][1] > 15
    assert len(card["sections"]["color"]["facts"]["swatches"]) == 8


def test_explain_missing_optional_extras_stays_offline(tmp_path):
    import subprocess
    import sys
    folder = tmp_path / "clips"
    folder.mkdir()
    source = folder / "plain.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=blue:s=160x120:d=0.5",
                    "-c:v", "libx264", str(source)], check=True, capture_output=True, timeout=30)
    script = '''
import importlib.abc, sys, socket, json
class Missing(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'cv2','numpy','rapidocr','faster_whisper','scenedetect'}:
            raise ImportError('deliberately absent optional extra: '+fullname)
sys.meta_path.insert(0, Missing())
def denied(*args, **kwargs):
    raise AssertionError('unexpected network')
socket.socket.connect = denied
from myzing.explain.api import explain_video
print(json.dumps(explain_video(sys.argv[1], sys.argv[2])))
'''
    result = subprocess.run([sys.executable, "-c", script, str(source), str(tmp_path / "card")], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["ok"], receipt
    card = json.loads(Path(receipt["card_json"]).read_text(encoding="utf-8"))
    assert card["sections"]["pacing"]["facts"] == {}
    assert card["sections"]["color"]["facts"] == {}
    assert card["sections"]["captions"]["facts"]["tracks"] == []
    assert card["sections"]["audio"]["facts"]["speech_share"] is None


def _ffmpeg(*args):
    import subprocess
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, capture_output=True, timeout=60)


@pytest.mark.parametrize("kind", ["rotated", "anamorphic"])
def test_explain_reports_the_displayed_frame(tmp_path, monkeypatch, kind):
    # A phone clip stored landscape with a rotation flag, or non-square pixels,
    # must be described (and drawn) the way a viewer sees it.
    folder = tmp_path / "clips"
    folder.mkdir()
    base = tmp_path / "base.mp4"
    source = folder / f"{kind}.mp4"
    tone = ["-f", "lavfi", "-i", "sine=d=2", "-c:a", "aac", "-shortest"]
    if kind == "rotated":
        _ffmpeg("-f", "lavfi", "-i", "testsrc2=s=320x180:d=2:r=30", *tone, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(base))
        _ffmpeg("-display_rotation", "90", "-i", str(base), "-c", "copy", str(source))
        expected, stored = (180, 320), (320, 180)
    else:
        _ffmpeg("-f", "lavfi", "-i", "testsrc2=s=360x360:d=2:r=30", *tone, "-vf", "setsar=16/9",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source))
        expected, stored = (640, 360), (360, 360)
    monkeypatch.setenv("ZING_WHISPER_MODEL", str(tmp_path / "absent-model"))
    result = explain_video(source, tmp_path / "card")
    assert result["ok"], result
    card = json.loads(Path(result["card_json"]).read_text(encoding="utf-8"))
    framing = card["sections"]["framing"]
    assert (framing["facts"]["width"], framing["facts"]["height"]) == expected
    assert (framing["facts"]["stored_width"], framing["facts"]["stored_height"]) == stored
    assert f"stored {stored[0]} x {stored[1]}" in framing["lines"][0]
    width, height = card["evidence"]["preview"]["keyframe_size"]
    assert abs(width / height - expected[0] / expected[1]) < .05
    assert framing["facts"]["matte"]["kind"] == "none"


def test_explain_refuses_unreadable_inputs_before_any_work(tmp_path):
    import time
    folder = tmp_path / "clips"
    folder.mkdir()
    audio_only, video = folder / "voice.m4a", folder / "video.mp4"
    _ffmpeg("-f", "lavfi", "-i", "sine=d=2", "-c:a", "aac", str(audio_only))
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=s=160x90:d=2:r=30", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video))
    (folder / "empty.mp4").write_bytes(b"")
    from myzing.explain.api import _explain
    for source, against, words in [(audio_only, None, "no video stream"), (folder / "empty.mp4", None, "empty"),
                                   (video, audio_only, "no video stream")]:
        start = time.monotonic()
        result = _explain(str(source), str(tmp_path / "card"), against=str(against) if against else None)
        assert not result["ok"] and words in result["error"], result
        assert "media.mp4" not in result["error"]  # names the user's file, not an internal copy
        assert not (tmp_path / "card").exists()
        assert time.monotonic() - start < 20  # the reference is not studied first


def test_matte_detector_finds_baked_bars_and_active_picture(tmp_path):
    from myzing.explain.matte import detect_matte
    pillar, letter, full = tmp_path / "pillar.mp4", tmp_path / "letter.mp4", tmp_path / "full.mp4"
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=s=360x640:d=2:r=30", "-vf", "scale=202:640,pad=360:640:79:0:black",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(pillar))
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=s=640x360:d=2:r=30", "-vf", "scale=640:268,pad=640:360:0:46:black",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(letter))
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=s=360x640:d=2:r=30", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(full))
    p = detect_matte(pillar, 2, 360, 640)
    assert p["kind"] == "pillarbox" and abs(p["active_size"][0] - 202) <= 6 and p["active_size"][1] == 640
    assert abs(p["bars"]["left"] - 79/360) < .02 and p["bar_level"] < 20
    l = detect_matte(letter, 2, 640, 360)
    assert l["kind"] == "letterbox" and abs(l["active_size"][1] - 268) <= 6
    f = detect_matte(full, 2, 360, 640)
    assert f["kind"] == "none" and f["active_size"] == [360, 640] and f["samples_informative"] == 7
