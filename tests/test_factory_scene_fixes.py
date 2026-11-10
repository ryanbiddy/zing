from __future__ import annotations

import json
import re

import pytest

from myzing.factory import cut, judge, plan, render
from test_factory_caption_craft import words
from test_factory_caption_faces import data, frames, intersects, scene
from test_factory_review_fixes import javascript
from test_factory_text_frames import clip


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)


def body(value):
    return scene(value, r"""
      let fit;
      const fitContain = contain, fitCover = cover;
      contain = (img, ...args) => { if (img === $('spkImg')) fit = 'contain'; return fitContain(img, ...args); };
      cover = (img, ...args) => { if (img === $('spkImg')) fit = 'cover'; return fitCover(img, ...args); };
      await window.seek(.5);
      console.log(JSON.stringify({fit, panel:geometry('solo').spk,
        crop:$('spkImg').style.transform.match(/-?[\d.]+/g).map(Number)}));
    """)


def test_text_box_survives_a_card_that_fits_the_old_panel(clip):
    clip.boxes = [(.25, .4, .75, .5)]
    got = cut.cams(clip.path)
    assert got["cams"][0]["text_box"] == [.25, .4, .75, .5]
    assert "text" not in got["cams"][0]
    assert json.loads((clip.path / "cams.json").read_text(encoding="utf-8")) == got


def test_text_box_is_the_rounded_union_of_ocr_boxes(clip):
    clip.boxes = [(.2004, .3004, .4004, .5004), (.5996, .5496, .7996, .6996)]
    assert cut.cams(clip.path)["cams"][0]["text_box"] == [.2, .3, .8, .7]


@pytest.mark.parametrize("boxes,text,score", [([], "Text", .95), ([(.1, .1, .2, .2)], "Text", .95),
                                             ([(.1, .1, .9, .9)], " ", .95),
                                             ([(.1, .1, .9, .9)], "Text", .5),
                                             ([(.1, .1, .9, .9)], "Text", float("nan"))])
def test_small_or_unreadable_text_has_no_box(clip, boxes, text, score):
    clip.boxes, clip.text, clip.score = boxes, text, score
    cam = cut.cams(clip.path)["cams"][0]
    assert "text_box" not in cam and "text" not in cam


@pytest.mark.parametrize("shape,theme,box,fit", [
    ("9x16", {}, [.25, .4, .75, .5], "contain"),
    ("16x9", {}, [.25, .4, .75, .5], "cover"),
    ("9x16", {}, [.35, .4, .65, .6], "cover"),
    ("9x16", {"solo_fill": True}, [.34, .4, .66, .6], "contain"),
    ("9x16", {"solo_fill": True}, [.35, .4, .65, .6], "cover"),
    ("1x1", {}, [.2, .4, .8, .5], "contain"),
    ("4x5", {}, [.25, .4, .75, .5], "contain"),
])
def test_planned_text_card_uses_the_real_solo_box(clip, shape, theme, box, fit):
    clip.boxes = [box]
    cut.cams(clip.path)
    planned = plan.check({"hook": "Training", "shots": [{"from": 0, "layout": "solo"}]})
    for name, value in [("plan", planned), ("words", {"words": words("Learn to fly")})]:
        (clip.path / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
    value = render.scene_data(clip.path, shape, theme, parallax=False, front=False, sharpen=False)
    got = body(value)
    assert got["fit"] == fit
    x, y, scale = got["crop"]
    assert x + box[0]*1920*scale >= -1e-6 and x + box[2]*1920*scale <= got["panel"]["w"] + 1e-6
    assert y + box[1]*1080*scale >= -1e-6 and y + box[3]*1080*scale <= got["panel"]["h"] + 1e-6


@pytest.mark.parametrize("box,fit", [([.2, .24, .8, .4], "cover"), ([.2, .55, .8, .65], "contain")])
def test_text_box_uses_the_cover_focus_and_overrides_the_old_flag(box, fit):
    value = data(shape="16x9", src=(1080, 1920), cam={"mode": "wide", "text": True, "text_box": box})
    assert body(value)["fit"] == fit


def test_text_box_respects_the_burned_caption_crop():
    value = data(src=(1920, 1080), cam={"mode": "wide", "text_box": [.4, .75, .6, .95]}, burnTop=.72)
    assert body(value)["fit"] == "contain"


@pytest.mark.parametrize("shape", ["9x16", "16x9"])
def test_old_text_flag_still_contains_the_card(shape):
    assert body(data(shape=shape, src=(1920, 1080), cam={"mode": "wide", "text": True}))["fit"] == "contain"


@pytest.mark.parametrize("pack,portrait,landscape", [("launch", 50, 89), ("headline", 58, 103),
                                                     ("documentary", 66, 117), ("zing", 78, 78),
                                                     ("newsdesk", 54, 54), ("swiss", 54, 54), (None, 78, 78)])
@pytest.mark.parametrize("shape", ["9x16", "16x9"])
def test_pack_caption_sizes(pack, portrait, landscape, shape):
    width, height = render.SHAPES[shape]
    got = javascript("scene.html", "console.log(JSON.stringify(CAP_SIZE));",
                     {"words": [], "fps": 30, "W": width, "H": height, "theme": render.theme(pack) if pack else {}})
    assert got == (portrait if shape == "9x16" else landscape)


@pytest.mark.parametrize("shape,want", [("9x16", 50), ("16x9", 28)])
def test_learned_caption_size_still_scales_by_height(shape, want):
    width, height = render.SHAPES[shape]
    got = javascript("scene.html", "console.log(JSON.stringify(CAP_SIZE));",
                     {"words": [], "fps": 30, "W": width, "H": height,
                      "theme": {**render.theme("launch"), "learned": True}})
    assert got == want


@pytest.mark.parametrize("theme", [{"split": "speaker-top", "cap_y": .5}, {"split": "speaker-top"}])
def test_speaker_top_captions_clear_the_card_and_phone_controls(theme):
    value = data(layout="graphic", src=(1920, 1080), cam={"cy": .95}, theme=theme)
    states = frames(value, [i/30 for i in range(1, 42)])
    assert len({s["cy"] for s in states}) == 1
    for state in states:
        assert 150 <= state["caption"]["y0"] < state["caption"]["y1"] <= 1440
        assert state["caption"]["y1"] <= state["panel"]["y"] + state["panel"]["h"]
        assert not intersects(state["caption"], state["face"])


@pytest.mark.parametrize("mode", ["wide", "face"])
def test_speaker_top_high_seam_stays_in_the_safe_band_without_a_collision(mode):
    value = data(layout="graphic", src=(1920, 1080), cam={"mode": mode, "cy": .1, "fh": .1},
                 theme={"split": "speaker-top", "seam": .8})
    for state in frames(value):
        assert 150 <= state["caption"]["y0"] < state["caption"]["y1"] <= 1440


@pytest.mark.parametrize("n", [7, 8, 12, 30])
def test_accepted_list_rows_do_not_overlap(n):
    graphic = {"kind": "list", "title": "Training", "items": [{"text": "Learn to fly"} for _ in range(n)]}
    checked = plan.check({"hook": "Training", "shots": [{"from": 0, "layout": "graphic", "graphic": graphic}]})
    _, shots, _ = render.timeline(checked, {"duration": 4})
    assert len(shots[0]["graphic"]["items"]) == n
    got = javascript("scene.html", """
      const el = {dataset:{}, querySelectorAll:() => []};
      drawGraphic({...GRAPHIC, id:'list', from:0}, 4, el);
      console.log(JSON.stringify(el.innerHTML));
    """.replace("GRAPHIC", json.dumps(shots[0]["graphic"])))
    rows = re.findall(r'<div class="g-item" style="([^"]+)"><i([^>]*)>', got)
    assert len(rows) == n
    def px(style, name, default):
        match = re.search(rf'(?:^|[;\"])\s*{name}:([\d.]+)px', style)
        return float(match[1]) if match else default
    for (style, badge), (next_style, _) in zip(rows, rows[1:]):
        step = px(next_style, "top", 0) - px(style, "top", 0)
        assert px(badge, "height", 88) <= step + 1e-6
        assert px(badge, "width", 88) <= step + 1e-6
        assert px(style, "font-size", 66)*1.12 <= step + 1e-6
        assert px(badge, "font-size", 40) <= px(badge, "height", 88)
