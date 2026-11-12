from __future__ import annotations

import json
import re

import pytest
from PIL import ImageFont

from myzing.factory import judge, pipeline, render
from test_factory_caption_craft import words
from test_factory_caption_faces import data, scene as run_scene


def scene(value, code):
    return run_scene(value, """
      const make = document.createElement;
      document.createElement = name => name === 'canvas' ? {getContext:() => ({
        font:'', measureText(s) {return {width:s.length*(parseFloat(this.font.match(/[\\d.]+px/)[0]) || 74)*.5};}
      })} : make(name);
    """ + code)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)


@pytest.mark.parametrize("pack", ["desk", "editorial", "newsroom"])
def test_packs_load_and_validate(pack):
    got = render.theme(pack)
    assert got["motion"] == "still" and got["captions"] == "band"
    assert got["look"] == pack and got["cap_upper"] is False
    assert render.check_pack(pack) == []
    assert pack in render.themes()


def test_podcast_default_and_launch_default():
    assert pipeline.SETTINGS["pack"] == "desk"
    assert pipeline.LAUNCH["pack"] == "launch"


def test_still_crop_and_quote_lean():
    value = data(src=(3840, 2160), theme={"motion": "still"})
    got = scene(value, """
      const b = geometry('solo').spk, c = D.cams[0];
      console.log(JSON.stringify({crops:[0,2,3.99].map(t => faceCrop(c,b,t)),
        lean:quoteLean({from:0,to:4},2)}));
    """)
    assert got["crops"][0] == got["crops"][1] == got["crops"][2]
    assert got["lean"] == 1


@pytest.mark.parametrize("duration,punched", [(12, False), (20, True)])
def test_punch_is_a_sentence_cut_in_a_long_shot(duration, punched):
    rows = words("We fly home. Then we rest. Next we train. Now we fly.")
    rows = [{**w, "os": w["os"] * 3, "oe": w["oe"] * 3} for w in rows]
    value = data(src=(3840, 2160), theme={"motion": "still", "solo_fill": True},
                 cam={"to": duration, "cy": .36, "fh": .15}, words=rows, duration=duration)
    got = scene(value, """
      const b = geometry('solo').spk, c = D.cams[0];
      console.log(JSON.stringify(Array.from({length:D.duration*30}, (_, f) => faceCrop(c,b,f/30))));
    """)
    changes = [i for i in range(1, len(got)) if got[i] != got[i-1]]
    assert len(changes) == int(punched)
    if punched:
        at = changes[0] / 30
        starts = [rows[i + 1]["os"] for i, w in enumerate(rows[:-1]) if w["w"].endswith(".")]
        assert at == pytest.approx(min(starts, key=lambda t: abs(t - duration / 2)))
        assert got[-1]["s"] / got[0]["s"] == pytest.approx(1.12)
        assert (.36 * 2160 * got[-1]["s"] + got[-1]["ty"]) / 1920 == pytest.approx(.36)


def test_zing_still_moves_and_pops():
    value = data(theme=render.theme("zing"))
    got = scene(value, """
      const b = geometry('solo').spk, c = D.cams[0], states = [];
      for (const t of [0,.1,.2]) { await window.seek(t); states.push($('cap').style.transform); }
      console.log(JSON.stringify({a:faceCrop(c,b,0),b:faceCrop(c,b,3.99),states,
        lean:quoteLean({from:0,to:4},2),scale:CAP_SCALE}));
    """)
    assert got["a"] != got["b"] and len(set(got["states"])) > 1
    assert got["lean"] > 1 and got["scale"] == 1.06


def measured(value, code):
    size = 103 if value["aspect"] == "16x9" else value["theme"].get("cap_size", 74)
    font = ImageFont.truetype(str(render.data_path("../fonts/ZingCaption-800.ttf")), size)
    texts = [w["w"] for w in value["words"]]
    widths = {" ".join(texts[a:b]): font.getlength(" ".join(texts[a:b]))
              for a in range(len(texts)) for b in range(a + 1, min(len(texts), a + 12) + 1)}
    return scene(value, """
      const widths = WIDTHS, create = document.createElement;
      document.createElement = name => name === 'canvas' ? {getContext:() => ({
        font:'', measureText(s) {return {width:widths[s] ?? s.length*30,
          actualBoundingBoxAscent:54,actualBoundingBoxDescent:15};}
      })} : create(name);
    """.replace("WIDTHS", json.dumps(widths)) + code)


@pytest.mark.parametrize("shape,width", [("9x16", 490), ("16x9", 1560)])
def test_band_phrases_keep_words_and_fit_pixels(shape, width):
    text = "We train at the base and fly into space. We can fly far and get home with our crew."
    value = data(shape=shape, theme={"captions": "band", "cap_size": 74, "cap_weight": 800,
                                   "cap_width": 490, "cap_upper": False}, words=words(text), duration=12)
    got = measured(value, """
      await window.seek(0);
      console.log(JSON.stringify(groups.map(g => ({ids:g,...bandLayout(g)}))));
    """)
    assert [j for g in got for j in g["ids"]] == list(range(len(value["words"])))
    weak = set("a an the of and to if we they i would could that than was my them at into with our".split())
    for group in got:
        assert group["size"] >= (103 if shape == "16x9" else 74) * .92
        font = ImageFont.truetype(str(render.data_path("../fonts/ZingCaption-800.ttf")), group["size"])
        assert 1 <= len(group["lines"]) <= 2
        for line in group["lines"]:
            assert font.getlength(line) <= width
            assert re.sub(r"\W", "", line.split()[-1]).lower() not in weak
            if shape == "16x9":
                assert len(line) <= 26


def test_band_stays_at_one_baseline_across_groups_and_faces():
    value = data(theme={"motion": "still", "captions": "band", "cap_size": 74},
                 words=words("We fly home. We train at the base. We fly far."), duration=6)
    value["cams"] = [{**value["cams"][0], "from": a, "to": b, "cy": y}
                     for a, b, y in [(0, 2, .2), (2, 6, .56)]]
    got = measured(value, """
      const out = [];
      for (const t of [0,.2,1.5,2.5,4]) { await window.seek(t);
        out.push({y:$('cap').style.top,transform:$('cap').style.transform,html:$('cap').firstChild.innerHTML}); }
      console.log(JSON.stringify(out));
    """)
    assert len({s["y"] for s in got}) == 1
    assert 1150 <= float(got[0]["y"].removesuffix("px")) <= 1500
    assert all('class="on"' not in s["html"] and "scale(" not in s["transform"] for s in got)
    assert got[0]["html"] == got[1]["html"]


def test_desk_banner_cuts_out_by_five_and_a_half_seconds():
    value = data(theme={"look": "desk", "motion": "still"}, hookUntil=9, duration=8)
    got = scene(value, """
      const out = [];
      for (const t of [0,4,5.5,7]) { await window.seek(t); out.push(+$('hook').style.opacity); }
      console.log(JSON.stringify(out));
    """)
    assert got == [1, 1, 0, 0]


def test_takeaway_hides_captions():
    value = data(theme={"look": "desk", "motion": "still", "captions": "band"},
                 words=words("We train at the base and fly far from home."), duration=5,
                 shots=[{"from": 0, "to": 3, "layout": "solo"},
                        {"from": 3, "to": 5, "layout": "graphic", "idx": 1,
                         "graphic": {"kind": "counter", "value": 100, "label": "people"}}])
    got = measured(value, "await window.seek(3.2); console.log(JSON.stringify($('cap').style.opacity));")
    assert float(got) == 0


def test_newsroom_strip_preserves_the_source():
    value = data(src=(1920, 1080), theme={"look": "newsroom", "motion": "still"})
    got = scene(value, """
      await window.seek(1);
      console.log(JSON.stringify({box:geometry('solo').spk,transform:$('spkImg').style.transform}));
    """)
    assert got["box"] == {"x": 0, "y": 600, "w": 1080, "h": 608}
    assert "scale(0.5625)" in got["transform"]


@pytest.fixture
def clip(tmp_path):
    d = tmp_path / "clip01"
    pipeline._write(d / "words.json", {"words": words("We fly home. We train here. We fly far."), "duration": 5})
    pipeline._write(d / "cams.json", {"size": [1920, 1080], "frames": 150, "cams": [
        {"from": 0, "to": 5, "mode": "face", "cx": .5, "cy": .4, "fh": .3}]})
    pipeline._write(d / "plan.json", {"hook": "A *safe* flight home", "shots": [
        {"from": 0, "layout": "solo"},
        {"from": 1, "layout": "graphic", "graphic": {"kind": "counter", "value": 100, "label": "people"}},
        {"from": 4, "layout": "solo"}], "visuals": {}})
    return d


def test_pack_timeline_adds_silent_endcard_and_bounds_takeaways(clip):
    got = render.scene_data(clip, "9x16", {"look": "desk", "motion": "still", "captions": "band"},
                            parallax=False, front=False, sharpen=False)
    last = got["words"][-1]["oe"]
    assert got["duration"] == pytest.approx(last + 1.8)
    assert got["audioUntil"] == last
    cards = [s for s in got["shots"] if (s.get("graphic") or {}).get("kind") == "counter"]
    assert len(cards) <= 2 and all(s["from"] >= 3 and s["to"] - s["from"] >= 1.2 for s in cards)
    assert got["shots"][-1]["graphic"]["kind"] == "endcard"
    assert got["shots"][-1]["from"] == last


def test_still_disables_parallax_even_when_requested(clip, monkeypatch):
    monkeypatch.setattr(render.depth, "parallax", lambda *a, **k: pytest.fail("still pack made parallax"))
    from PIL import Image
    photo = clip / "photo.jpg"
    Image.new("RGB", (200, 100)).save(photo)
    plan = json.loads((clip / "plan.json").read_text())
    plan["visuals"] = {"v1": {"path": str(photo), "credit": "example.org"}}
    plan["shots"][1] = {"from": 1, "layout": "split", "visual": "v1"}
    pipeline._write(clip / "plan.json", plan)
    got = render.scene_data(clip, "9x16", {"look": "desk", "motion": "still"},
                            parallax=True, front=False, sharpen=False)
    assert got["visuals"]["v1"]["card"] is True
    assert all(s["from"] >= 3 for s in got["shots"] if s["layout"] == "split")


def test_band_clears_a_tile_face_sitting_low():
    value = data(src=(1920, 1080), theme={"motion": "still", "captions": "band", "cap_size": 74},
                 words=words("We fly home. We train at the base. We fly far."), duration=6)
    value["cams"] = [{"from": 0, "to": 3, "mode": "face", "cx": .5, "cy": .3, "fh": .2},
                     {"from": 3, "to": 6, "mode": "face", "cx": .5, "cy": .5, "fh": .12, "tile": [.4, 0, .6, .67]}]
    got = measured(value, """
      const out = [];
      for (const t of [0,1.5,2.9,3.1,4.5,5.9]) { await window.seek(t);
        const cam = camAt(t), r = faceCrop(cam, geometry('solo').spk, t), y = parseFloat($('cap').style.top);
        const o = geometry("solo").spk.y+r.ty;
        out.push({y, chin:(cam.cy+.6*cam.fh)*D.srcSize[1]*r.s+o, top:(cam.cy-.6*cam.fh)*D.srcSize[1]*r.s+o}); }
      console.log(JSON.stringify(out));
    """)
    assert got[0]["y"] == got[1]["y"] == got[2]["y"] == 1500
    assert got[3]["y"] == got[4]["y"] == got[5]["y"] < 1500
    for g in got:
        assert g["y"] <= g["top"] or g["y"] - 74 * 2.1 >= g["chin"]


STILL_CASES = {
    "face": {"mode": "face"},
    "tile": {"mode": "face", "tile": [.25, 0, .75, .7]},
    "wide": {"mode": "wide", "faces": 1},
    "group": {"mode": "wide", "faces": 3},
}


@pytest.mark.parametrize("name", sorted(STILL_CASES))
@pytest.mark.parametrize("look", ["desk", "editorial", "newsroom"])
def test_still_shots_never_drift(name, look):
    value = data(src=(1920, 1080), theme={**render.theme(look)}, duration=10,
                 words=words("We fly home. We rest."), cam={"to": 10, **STILL_CASES[name], "overlays": []})
    value["overlays"] = [{"from": 0, "to": 10, "box": [.7, .6, .95, .95]}]
    value["shots"] = [{"from": 0, "to": 5, "layout": "solo", "idx": 0},
                      {"from": 5, "to": 10, "layout": "split", "visual": "v1", "idx": 1}]
    value["visuals"]["v1"] = {"src": "visual.jpg", "w": 1600, "h": 900, "card": False}
    got = scene(value, """
      const out = [];
      for (const group of [[3.1, 3.5, 4.9], [5.1, 7.5, 9.9]]) {
        const rows = [];
        for (const t of group) { await window.seek(t);
          rows.push([$('spkImg').style.transform, $('topImg').style.transform, $('top').style.left,
            $('gfx').innerHTML, $('cap').style.transform, $('hook').style.transform]); }
        out.push(rows);
      }
      console.log(JSON.stringify(out));
    """)
    for rows in got:
        assert rows[0] == rows[1] == rows[2]


@pytest.mark.parametrize("graphic", [
    {"kind": "list", "title": "Plan", "items": [{"text": "One", "at": 4}, {"text": "Two", "at": 6}]},
    {"kind": "funnel", "title": "Plan", "rows": [{"text": "One", "value": 5, "at": 4}, {"text": "Two", "value": 3, "at": 6}]},
    {"kind": "title", "text": "A *name*"}, {"kind": "counter", "value": 100, "label": "people"}])
def test_still_graphics_enter_without_motion(graphic):
    value = data(theme=render.theme("desk"), duration=10, words=words("We fly home. We rest."))
    value["shots"] = [{"from": 0, "to": 3, "layout": "solo", "idx": 0},
                      {"from": 3, "to": 10, "layout": "graphic", "idx": 1, "graphic": graphic}]
    got = scene(value, """
      const out = [];
      for (const t of [3.05, 3.4, 5, 9.9]) { await window.seek(t); out.push($('gfxIn').innerHTML + $('gfxIn').style.transform); }
      console.log(JSON.stringify(out));
    """)
    assert len(set(got)) == 1
