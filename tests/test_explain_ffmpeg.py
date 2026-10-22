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
