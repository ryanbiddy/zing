from __future__ import annotations

import json

import pytest

from myzing.factory import judge, render
from test_factory_caption_craft import words
from test_factory_review_fixes import javascript


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)


DOM = r"""
function element(id = '') {
  const el = {style: {setProperty(k, v) {this[k] = v;}}, dataset: {}, children: [],
    innerHTML: '', textContent: '', classList: {toggle() {}, add() {}, contains() {return false;}},
    decode: async () => {}, querySelectorAll: () => [], getContext: () => ({drawImage() {}})};
  el.firstChild = id === 'box' ? null : element('box');
  el.querySelector = () => el.firstChild;
  Object.defineProperties(el, {
    offsetWidth: {get() {return id === 'box' ?
      this.innerHTML.replace(/<[^>]*>/g, '').length * (parseFloat(this.style.fontSize) || CAP_SIZE)*.56 + 16 : 900;}},
    offsetHeight: {get() {return id === 'box' ? (parseFloat(this.style.fontSize) || CAP_SIZE)*1.15 :
      id === 'cap' ? this.firstChild.offsetHeight : id === 'hook' ? 240 : 60;}}
  });
  return el;
}
document.getElementById = id => nodes[id] ||= element(id);
"""


def data(shape="9x16", layout="solo", src=(640, 360), cam=None, theme=None, **extra):
    width, height = render.SHAPES[shape]
    return {"words": words("AND MANY PEOPLE"), "fps": 30, "W": width, "H": height,
            "aspect": shape, "theme": theme or {}, "duration": 4, "frames": 120, "framesDir": "frames",
            "srcSize": src, "hookUntil": 0, "hookHtml": "A guest", "sourceTag": "",
            "shots": [{"from": 0, "to": 4, "layout": layout, "visual": "v1"}],
            "cams": [{"from": 0, "to": 4, "mode": "face", "cx": .5, "cy": .56, "fh": .35, **(cam or {})}],
            "visuals": {"v1": {"src": "visual.jpg", "w": 640, "h": 360}}, **extra}


def scene(value, code):
    script = render.data_path("scene.html").read_text(encoding="utf-8")
    rest = script.split("// Geometry per delivery shape.")[1].split("</script>")[0]
    return javascript("scene.html", DOM + "\n// Geometry per delivery shape." + rest + "\n" + code, value)


def frames(value, times=(.1, .5, .9, 1.3)):
    return scene(value, r"""
      const states = [];
      for (const t of TIMES) {
        await window.seek(t);
        const S = geometry(shotAt(t).layout).spk, cam = camAt(t), cap = $('cap'), box = cap.firstChild;
        const [tx, ty, s] = $(S && geometry(shotAt(t).layout).front ? 'spkCut' : 'spkImg')
          .style.transform.match(/-?[\d.]+/g).map(Number);
        const [iw, ih] = D.srcSize, fh = cam.fh*ih*s, pad = S.h*.04;
        const x = S.x + cam.cx*iw*s + tx, y = S.y + cam.cy*ih*s + ty;
        const pop = Number(cap.style.transform.match(/scale\(([^)]+)\)/)[1]);
        const stroke = TH0.cap_stroke_w ?? (CAP_DEFAULT ? 7 : 0);
        const h = cap.offsetHeight*Math.max(1, CAP_SCALE)*pop + stroke*2;
        const w = box.offsetWidth*Math.max(1, CAP_SCALE)*pop + stroke*2;
        const cy = parseFloat(cap.style.top), mid = cy + (ASPECT === '9x16' || CAP.y != null ? 0 : cap.offsetHeight/2);
        states.push({t, s, tx, ty, panel:S, center:y, cy, opacity:cap.style.opacity,
          caption:{x0:(SW-w)/2, x1:(SW+w)/2, y0:mid-h/2, y1:mid+h/2},
          face:{x0:x-fh*.425-pad, x1:x+fh*.425+pad, y0:y-fh/2-pad, y1:y+fh/2+pad}});
      }
      console.log(JSON.stringify(states));
    """.replace("TIMES", json.dumps(times)))


def intersects(a, b):
    return a["x0"] < b["x1"] and a["x1"] > b["x0"] and a["y0"] < b["y1"] and a["y1"] > b["y0"]


@pytest.mark.parametrize("theme", [{}, render.theme("zing"), {"cap_y": .7}, {"cap_y": .65, "cap_scale": 1.5}])
def test_webcam_captions_clear_the_face_and_phone_controls(theme):
    states = frames(data(theme=theme), [i / 30 for i in range(1, 42)])
    assert len({s["cy"] for s in states}) == 1
    for state in states:
        assert not intersects(state["caption"], state["face"])
        assert 390 <= state["caption"]["y0"] < state["caption"]["y1"] <= 1440
        assert state["caption"]["y1"] < state["face"]["y0"]


@pytest.mark.parametrize("src", [(640, 360), (1920, 1080)])
@pytest.mark.parametrize("wide", [False, True])
def test_high_face_keeps_the_original_framing_and_default_caption(src, wide):
    states = frames(data(src=src, cam={"cy": .35, "wide": wide}))
    for state in states:
        p = state["t"] / 4
        move = 1 + .05 * (4*p**3 if p < .5 else 1 - (-2*p+2)**3 / 2)
        scale = 1520 / src[1] * move
        assert state["s"] == pytest.approx(scale)
        assert state["ty"] == pytest.approx(max(1520-src[1]*scale, min(0, 760-.41*src[1]*scale)))
        assert state["cy"] == 1340
        assert not intersects(state["caption"], state["face"])


def test_low_webcam_fills_the_panel_without_zooming_past_it():
    for state in frames(data(), [0, .5, 1.3]):
        p = state["t"] / 4
        move = 1 + .05 * (4*p**3 if p < .5 else 1 - (-2*p+2)**3 / 2)
        assert state["s"] == pytest.approx(1520 / 360 * move)   # filling already blows 360 rows up past the 1.6x cap
        assert 1520 / state["s"] >= 300


def test_small_low_webcam_face_still_keeps_300_source_pixels():
    for state in frames(data(cam={"cy": .9, "fh": .1})):
        assert 1520 / state["s"] >= 300


@pytest.mark.parametrize("wide", [False, True])
def test_low_hd_face_stops_short_of_42_percent(wide):
    state = frames(data(src=(1920, 1080), cam={"wide": wide}), [0])[0]
    assert (state["center"] - 400) / 1520 == pytest.approx(1 - .44*1080*1.6/1520)
    assert state["s"] == pytest.approx(1.6)
    assert 1520 / state["s"] >= 300


@pytest.mark.parametrize("wide", [False, True])
def test_low_face_zoom_stops_at_the_scale_cap(wide):
    for state in frames(data(src=(1920, 1080), cam={"cy": .97, "wide": wide})):
        assert state["s"] == pytest.approx(1.6)
        assert 1520 / state["s"] >= 300


def test_split_keeps_the_seam_unless_a_face_is_there():
    assert all(s["cy"] == 960 for s in frames(data(layout="split")))
    for state in frames(data(layout="split", cam={"cy": .05})):
        assert state["cy"] > 960
        assert state["caption"]["y0"] > state["face"]["y1"]
        assert state["caption"]["y1"] <= 1440


@pytest.mark.parametrize("shape", ["1x1", "4x5", "16x9"])
@pytest.mark.parametrize("theme", [{}, {"cap_y": .56}])
def test_other_shapes_avoid_faces_inside_the_frame(shape, theme):
    for state in frames(data(shape=shape, src=(1920, 1080), theme=theme)):
        assert not intersects(state["caption"], state["face"])
        assert 0 <= state["caption"]["y0"] < state["caption"]["y1"] <= render.SHAPES[shape][1]


def test_clear_pack_position_stays_put():
    assert all(s["cy"] == 1920 * .3 for s in frames(data(theme={"cap_y": .3})))


@pytest.mark.parametrize("src,burn", [((640, 360), .72), ((1920, 1080), .72), ((1920, 1080), .4)])
def test_burned_in_caption_guard_still_wins(src, burn):
    for state in frames(data(src=src, burnTop=burn)):
        assert (1520 - state["ty"]) / state["s"] <= src[1] * burn + .001
        assert not intersects(state["caption"], state["face"])


def test_camera_change_and_seeking_keep_one_position_for_the_group():
    value = data()
    value["cams"] = [{**value["cams"][0], "cy": cy, "from": a, "to": b}
                     for cy, a, b in [(.35, 0, .6), (.56, .6, 4)]]
    times = [.1, .5, .9, 1.3]
    forward, reverse = frames(value, times), frames(value, times[::-1])
    assert forward == reverse[::-1]
    assert len({s["cy"] for s in forward}) == 1
    assert all(not intersects(s["caption"], s["face"]) for s in forward)


def test_layout_change_keeps_the_group_position_in_either_seek_order():
    value = data(src=(1920, 1080), cam={"cy": .1, "fh": .05, "wide": True})
    value["shots"] = [{**value["shots"][0], "layout": layout, "from": a, "to": b}
                      for layout, a, b in [("solo", 0, .6), ("split", .6, 4)]]
    times = [.1, .5, .9, 1.3]
    forward, reverse = frames(value, times), frames(value, times[::-1])
    assert forward == reverse[::-1]
    assert all(s["cy"] == 1340 and not intersects(s["caption"], s["face"]) for s in forward)


def test_pack_caption_near_the_top_moves_into_the_safe_area():
    for state in frames(data(src=(1920, 1080), cam={"cy": 0, "fh": .02, "wide": True},
                             theme={"solo_fill": True, "cap_y": 0})):
        assert not intersects(state["caption"], state["face"])
        assert 150 <= state["caption"]["y0"] < state["caption"]["y1"] <= 1440


def test_impossible_fit_uses_the_lower_safe_position():
    states = frames(data(cam={"fh": 1}, burnTop=.72))
    assert len({s["cy"] for s in states}) == 1
    assert all(1300 < s["cy"] < 1440 and 150 <= s["caption"]["y0"] < s["caption"]["y1"] <= 1440
               for s in states)


def test_kinetic_captions_keep_their_placement():
    assert all(s["cy"] == 1340 for s in frames(data(theme={"cap_style": "kinetic"})))


def test_quote_moments_keep_their_placement():
    positions = []
    for cy in [.35, .56]:
        value = data(cam={"cy": cy}, quotes=[{"from": 0, "to": 2, "a": 0, "b": 2, "marks": []}])
        positions.append(scene(value, """
          await window.seek(.5);
          console.log(JSON.stringify({top:$('quote').style.top, opacity:$('cap').style.opacity}));
        """))
    assert positions[0] == positions[1]
    assert positions[0]["opacity"] == 0


def test_caption_never_climbs_onto_a_graphic_card():
    value = data(src=(1920, 1080), cam={"cy": .2, "fh": .2})
    value["shots"] = [{**value["shots"][0], "layout": layout, "from": a, "to": b}
                      for layout, a, b in [("solo", 0, .6), ("graphic", .6, 4)]]
    for state in frames(value, [.1, .9]):
        assert state["caption"]["y0"] >= 960 - 36 - (state["caption"]["y1"] - state["caption"]["y0"]) / 2 - 1
