"""Keep text cards whole without changing face framing or requiring OCR models."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing.factory import cut, judge
from myzing.factory.tools import data_path
from myzing.layout import detector
from myzing.study import caption_models


class Frame:
    def __init__(self, shape, number):
        self.shape, self.number, self.size = shape, number, 0

    def __getitem__(self, key):
        return self


@pytest.fixture
def clip(tmp_path, monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    (tmp_path / "frames").mkdir()
    for n in range(1, 61):
        (tmp_path / "frames" / f"{n:05d}.jpg").touch()
    state = SimpleNamespace(path=tmp_path, shape=(1080, 1920, 3), faces=None, cuts="", calls=[], loads=[],
                            boxes=[(.05, .4, .95, .48)], text="How long does training take?", score=.95, error=None)

    def read(path):
        return Frame(state.shape, int(Path(path).stem))

    def detect(img):
        return None, state.faces(img) if callable(state.faces) else state.faces

    def ocr(img):
        state.calls.append((img.number, img.shape))
        if state.error:
            raise state.error
        h, w = img.shape[:2]
        boxes = [[[l*w, t*h], [r*w, t*h], [r*w, b*h], [l*w, b*h]] for l, t, r, b in state.boxes]
        return SimpleNamespace(boxes=boxes, txts=[state.text]*len(boxes), scores=[state.score]*len(boxes))

    def engine():
        state.loads.append(True)
        return ocr, "fake"

    cv2 = SimpleNamespace(imread=read, INTER_AREA=3,
                          resize=lambda img, size, **kw: Frame((size[1], size[0], 3), img.number),
                          FaceDetectorYN=SimpleNamespace(create=lambda *a: SimpleNamespace(
                              setInputSize=lambda size: None, detect=detect)))
    monkeypatch.setitem(sys.modules, "cv2", cv2)
    monkeypatch.setattr(detector, "require_model", lambda: tmp_path / "model")
    monkeypatch.setattr(cut, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(cut, "run", lambda *a, **kw: SimpleNamespace(
        stderr=re.sub(r"(pts_time:[0-9.]+)", r"\1\nlavfi.scene_score=1", state.cuts)))
    monkeypatch.setattr(cut, "burned_caption_top", lambda d: None)
    monkeypatch.setattr(caption_models, "engine", engine)
    return state


def test_wide_text_is_marked_and_saved(clip):
    info = cut.cams(clip.path)
    assert info == {"cams": [{"from": 0, "to": 2, "mode": "wide", "faces": 0, "text": True,
                            "text_box": [.05, .4, .95, .48]}],
                    "size": [1920, 1080], "frames": 60, "burn_top": None}
    assert json.loads((clip.path / "cams.json").read_text(encoding="utf-8")) == info
    assert clip.calls == [(31, (540, 960, 3))]
    assert clip.loads == [True]


@pytest.mark.parametrize("boxes", [[(.4, .3, .6, .6)], [(.05, .1, .1, .13)], []])
def test_centered_text_small_marks_and_empty_frames_keep_the_crop(clip, boxes):
    clip.boxes = boxes
    text = {"text_box": [.4, .3, .6, .6]} if boxes == [(.4, .3, .6, .6)] else {}
    assert cut.cams(clip.path)["cams"] == [{"from": 0, "to": 2, "mode": "wide", "faces": 0, **text}]
    assert len(clip.calls) == 1


@pytest.mark.parametrize("text,score", [(" ", .95), ("Wide text", .5), ("Wide text", float("nan"))])
def test_only_readable_text_counts(clip, text, score):
    clip.text, clip.score = text, score
    assert "text" not in cut.cams(clip.path)["cams"][0]


@pytest.mark.parametrize("box,marked", [((.2, .7, .8, .8), True), ((.2, .3, .8, .4), False)])
def test_portrait_source_uses_the_panel_vertical_crop(clip, box, marked):
    clip.shape, clip.boxes = (1920, 1080, 3), [box]
    assert cut.cams(clip.path)["cams"][0].get("text", False) is marked
    assert clip.calls == [(31, (960, 540, 3))]


def test_faces_skip_ocr_and_keep_the_same_framing(clip):
    clip.faces = [(700, 200, 240, 320)]
    assert cut.cams(clip.path)["cams"] == [{"from": 0, "to": 2, "mode": "face",
                                           "cx": 820 / 1920, "cy": 360 / 1080, "fh": 320 / 1080}]
    assert not clip.calls and not clip.loads


def test_small_faces_skip_ocr(clip):
    clip.faces = [(700, 200, 60, 60)]
    assert cut.cams(clip.path)["cams"] == [{"from": 0, "to": 2, "mode": "wide", "faces": 1}]
    assert not clip.calls and not clip.loads


def test_faces_elsewhere_in_the_shot_skip_ocr(clip):
    clip.faces = lambda img: [(100, 200, 240, 320), (1400, 200, 240, 320)] if img.number < 30 else None
    assert cut.cams(clip.path)["cams"] == [{"from": 0, "to": 2, "mode": "wide", "faces": 0}]
    assert not clip.calls and not clip.loads


@pytest.mark.parametrize("error", [ImportError("rapidocr absent"), RuntimeError("models absent"), OSError("runtime absent")])
def test_ocr_unavailable_keeps_the_old_output(clip, monkeypatch, error):
    def unavailable():
        clip.loads.append(True)
        raise error
    monkeypatch.setattr(caption_models, "engine", unavailable)
    clip.cuts = "pts_time:1.0"
    assert cut.cams(clip.path)["cams"] == [{"from": 0, "to": 1, "mode": "wide", "faces": 0},
                                          {"from": 1, "to": 2, "mode": "wide", "faces": 0}]
    assert clip.loads == [True] and not clip.calls


def test_failed_ocr_keeps_the_old_output(clip):
    clip.error = RuntimeError("inference failed")
    assert cut.cams(clip.path)["cams"] == [{"from": 0, "to": 2, "mode": "wide", "faces": 0}]


def test_one_small_middle_frame_per_shot_and_one_reader(clip):
    clip.cuts, clip.shape = "pts_time:1.0", (270, 480, 3)
    assert all(cam["text"] for cam in cut.cams(clip.path)["cams"])
    assert clip.calls == [(16, (270, 480, 3)), (46, (270, 480, 3))]
    assert clip.loads == [True]


def test_scene_contains_text_shots_over_the_existing_blur():
    scene = data_path("scene.html").read_text(encoding="utf-8")
    assert re.search(r"else if \(textCut\(cam, iw, ih, BW, BH, lean\) \|\| \(cam\.mode === 'wide' && cam\.faces > 1\)\)\s*"
                     r"contain\(body, iw, ih, BW, BH\)", scene)
    assert "cover($('spkBlur'), iw, ih, BW, BH, 1.1)" in scene
    assert "else cover(body, iw, ih, BW, BH, lean, .5, .38, D.burnTop)" in scene
