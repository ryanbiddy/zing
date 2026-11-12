from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing.factory import cut, render
from myzing.layout import detector
from test_factory_caption_craft import words
from test_factory_caption_faces import data
from test_factory_looks import scene


def text_nodes(markup):
    root = ET.fromstring(markup)
    return [el for el in root.iter() if el.tag.endswith('}text')]


@pytest.mark.parametrize("look", ["desk", "editorial", "newsroom"])
@pytest.mark.parametrize("quote", ["we failed twice", "You can append the word yet and it still holds water"])
def test_quote_keeps_large_balanced_lines(look, quote):
    value = data(theme=render.theme(look))
    got = scene(value, "drawTakeaway({kind:'quote',text:" + json.dumps(quote) + "}); console.log(JSON.stringify($('gfxIn').innerHTML));")
    lines = text_nodes(got)
    assert 2 <= len(lines) <= 4
    assert " ".join(el.text for el in lines) == quote
    assert all(80 <= float(el.attrib["font-size"]) <= 110 for el in lines)
    widths = [len(el.text) * float(el.attrib["font-size"]) * .5 for el in lines]
    assert max(widths) <= 936 and min(widths) >= max(widths) * .45
    assert all(300 <= float(el.attrib["y"]) <= (1208 if look == "newsroom" else 760) for el in lines)


@pytest.mark.parametrize("look", ["desk", "editorial", "newsroom"])
def test_long_quote_returns_to_speaker(look):
    quote = "Look, I think we should just shut it down. You know, we failed twice."
    plan = {"shots": [{"from": 0, "layout": "solo"},
                      {"from": 4, "layout": "graphic", "graphic": {"kind": "quote", "text": quote}},
                      {"from": 12, "layout": "solo"}]}
    _, shots, _ = render.timeline(plan, {"duration": 20}, look)
    assert not any((s.get("graphic") or {}).get("kind") == "quote" for s in shots)
    assert next(s for s in shots if s["from"] <= 5 < s["to"])["layout"] == "solo"


GRAPHICS = [
    {"kind": "list", "title": "Food brands", "items": [{"text": t} for t in ["Kraft", "General Foods", "Philip Morris bought these brands"]]},
    {"kind": "funnel", "title": "Plan", "rows": [{"value": 100, "label": "People"}, {"value": 20, "label": "Customers"}]},
    {"kind": "title", "text": "Personalized medicine for each person"},
]


@pytest.mark.parametrize("look", ["desk", "editorial", "newsroom"])
@pytest.mark.parametrize("graphic", GRAPHICS)
def test_list_items_fill_width_at_readable_size(look, graphic):
    value = data(theme=render.theme(look), shots=[{"from": 0, "to": 10, "idx": 0, "layout": "graphic", "graphic": graphic}])
    got = scene(value, "await window.seek(4); console.log(JSON.stringify($('gfxIn').innerHTML));")
    lines = text_nodes(got)
    items = [el for el in lines if el.text != graphic.get("title")]
    assert items
    assert all(60 <= float(el.attrib["font-size"]) <= 70 for el in items)
    for el in items:
        x, size = float(el.attrib["x"]), float(el.attrib["font-size"])
        assert 72 <= x and x + len(el.text) * size * .5 <= 1008


@pytest.mark.parametrize("look", ["desk", "editorial", "newsroom"])
@pytest.mark.parametrize("graphic", GRAPHICS)
def test_list_hold_ends_near_read_time(look, graphic):
    plan = {"shots": [{"from": 0, "layout": "solo"}, {"from": 4, "layout": "graphic", "graphic": graphic},
                      {"from": 18, "layout": "solo"}]}
    _, shots, _ = render.timeline(plan, {"duration": 22}, look)
    text = " ".join([graphic.get("title", ""), graphic.get("text", ""),
                     *(r["text"] for r in graphic.get("items", [])),
                     *(f"{r.get('text', r['value'])} {r['label']}" for r in graphic.get("rows", []))])
    hold = max(1.2, .35 * len(text.split()) + .5)
    card = next(s for s in shots if s.get("graphic") == graphic)
    assert card["to"] - card["from"] <= hold + 1
    assert next(s for s in shots if s["from"] == card["to"])["layout"] == "solo"


@pytest.mark.parametrize("look", ["desk", "editorial"])
@pytest.mark.parametrize("headline", ["A guest", "The guest explains why they failed twice"])
def test_picture_clears_visible_headline(look, headline):
    value = data(theme=render.theme(look), hookHtml=headline, duration=8,
                 visuals={"v1": {"src": "visual.jpg", "w": 1600, "h": 900, "card": True}},
                 shots=[{"from": 0, "to": 8, "layout": "split", "visual": "v1"}])
    got = scene(value, """
      const out = [];
      for (const t of [4,6,4]) { await window.seek(t); out.push({y:parseFloat($('top').style.top),
        hook:$('hook').innerHTML,visible:+$('hook').style.opacity}); }
      console.log(JSON.stringify(out));
    """)
    root = ET.fromstring(got[0]["hook"])
    if look == "desk":
        plate = next(el for el in root.iter() if el.tag.endswith('}rect'))
        bottom = float(plate.attrib["y"]) + float(plate.attrib["height"])
    else:
        bottom = max(float(el.attrib["y"]) + float(el.attrib["font-size"]) * .25 for el in text_nodes(got[0]["hook"]))
    assert got[0]["visible"] == 1 and got[0]["y"] >= bottom + 24
    assert got[1]["visible"] == 0 and got[1]["y"] == 330
    assert got[2] == got[0]


@pytest.fixture
def moving_clip(tmp_path, monkeypatch, zing_workspace):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    (tmp_path / "frames").mkdir()
    for n in range(1, 601):
        (tmp_path / "frames" / f"{n:05d}.jpg").touch()
    state = SimpleNamespace(path=tmp_path, center=lambda t: .5, invalid=lambda t: False, seen=[])
    monkeypatch.setattr(cut, "_camera_cuts", lambda *a: [])
    monkeypatch.setattr(cut, "burned_caption_top", lambda d: None)
    monkeypatch.setattr(cut, "_overlays", lambda *a: [])
    monkeypatch.setattr(detector, "require_model", lambda: tmp_path / "model")

    def frame(path):
        img = np.zeros((540, 960, 3), dtype=np.uint8)
        n = int(Path(path).stem) - 1
        img[0, 0] = (n // 256, n % 256, 0)
        return img

    def detect(img):
        t = (int(img[0, 0, 0]) * 256 + int(img[0, 0, 1])) / 30
        state.seen.append(t)
        x, y, w, h = state.center(t) * 960 - 45, 140, 90, 110
        row = [x, y, w, h, x+.3*w, y+.35*h, x+.7*w, y+.35*h, x+.5*w, y+.55*h,
               x+.3*w, y+.75*h, x+.7*w, y+.75*h, .9]
        if state.invalid(t):
            row[5] = y + h
        return None, np.array([row], dtype=np.float32)

    monkeypatch.setattr(cv2, "imread", frame)
    monkeypatch.setattr(cv2, "FaceDetectorYN", SimpleNamespace(create=lambda *a: SimpleNamespace(
        setInputSize=lambda size: None, detect=detect)))
    return state


def test_sustained_motion_splits_into_still_cameras(moving_clip):
    moving_clip.center = lambda t: .4 if t < 5 else .62
    info = cut.cams(moving_clip.path)
    cams = info["cams"]
    assert len(cams) == 2
    assert 5 <= cams[0]["to"] <= 5.5
    assert cams[0]["from"] == 0 and cams[-1]["to"] == 20
    assert cams[1]["from"] == cams[0]["to"]
    assert [c["cx"] for c in cams] == pytest.approx([.4, .62], abs=.002)
    assert all(c.get("moving") for c in cams)
    assert len(set(moving_clip.seen)) >= 40
    assert json.loads((moving_clip.path / "cams.json").read_text()) == info


def test_reframes_are_at_least_two_seconds_apart(moving_clip):
    moving_clip.center = lambda t: .4 if int(t) % 2 == 0 else .62
    cams = cut.cams(moving_clip.path)["cams"]
    assert len(cams) > 1
    assert all(b["from"] - a["from"] >= 2 for a, b in zip(cams, cams[1:]))


def test_stationary_face_at_source_edge_does_not_reframe(moving_clip):
    moving_clip.center = lambda t: .98
    cams = cut.cams(moving_clip.path)["cams"]
    assert len(cams) == 1
    assert not cams[0].get("moving")


def test_motion_inside_dead_zone_still_disables_punch(moving_clip):
    moving_clip.center = lambda t: .5 if t < 5 else .545 if t < 10 else .455
    cams = cut.cams(moving_clip.path)["cams"]
    assert len(cams) == 1 and cams[0].get("moving")


@pytest.mark.parametrize("invalid", [False, True])
def test_brief_or_invalid_face_motion_does_not_reframe(moving_clip, invalid):
    moving_clip.center = lambda t: .7 if (4 <= t < (8 if invalid else 4.5)) else .5
    moving_clip.invalid = lambda t: invalid and 4 <= t < 8
    assert len(cut.cams(moving_clip.path)["cams"]) == 1


def test_moving_shot_never_punches():
    rows = [{**w, "os": w["os"] * 3, "oe": w["oe"] * 3}
            for w in words("We fly home. Then we rest. Next we train. Now we fly.")]
    value = data(src=(3840, 2160), theme=render.theme("desk"), duration=20, words=rows,
                 cam={"to": 20, "cy": .36, "fh": .15, "moving": True})
    got = scene(value, "console.log(JSON.stringify([0,6,12,19].map(t => faceCrop(D.cams[0],geometry('solo').spk,t))));")
    assert all(c == got[0] for c in got)
