from __future__ import annotations

import json

import pytest

from myzing.factory import judge, render
from test_factory_review_fixes import javascript

SCENE = render.data_path("scene.html")
WEAK = set("a an the to of in on at for with from by about into and or but so because if that "
           "my your our their his her its is are was were be been will would can could do does did "
           "have has had i we you they he she it".split())


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)


def words(text):
    return [{"w": w, "os": i * .4, "oe": i * .4 + .3} for i, w in enumerate(text.split())]


def groups(rows, **theme):
    return javascript("scene.html", "console.log(JSON.stringify(groups));",
                      {"words": rows, "fps": 30, "theme": theme})


@pytest.mark.parametrize("text", [
    "we hired you up to your first mission and then you graduate",
    "bring us up to your first mission and then you graduate",
    "we train at the base and fly into space",
    "a good team can fly far with our help",
])
def test_phrases_keep_function_words_with_what_follows(text):
    rows = words(text)
    got = groups(rows)
    assert [j for group in got for j in group] == list(range(len(rows)))
    for group in got:
        assert 2 <= len(group) <= 4
        assert len(" ".join(rows[j]["w"] for j in group)) <= 18
        assert rows[group[-1]]["w"].lower() not in WEAK
    assert rows == words(text)


@pytest.mark.parametrize("text,want", [
    ("we train at the base", ["we train", "at the base"]),
    ("you graduate and start work", ["you graduate", "and start work"]),
    ("mission ready", ["mission ready"]),
    ("mission. ready set", ["mission.", "ready set"]),
    ("go! we train, then fly.", ["go!", "we train,", "then fly."]),
    ('we train,\" then fly', ['we train,\"', "then fly"]),
    ("we fly very high now", ["we fly", "very high now"]),
])
def test_boundaries_and_dangling_words(text, want):
    rows = words(text)
    assert [" ".join(rows[j]["w"] for j in g) for g in groups(rows)] == want


@pytest.mark.parametrize("pause,split", [(.4, True), (.3, True), (.299, False)])
def test_pause_uses_previous_word_end(pause, split):
    rows = words("we go fly home")
    shift = rows[1]["oe"] + pause - rows[2]["os"]
    for row in rows[2:]:
        row["os"] += shift
        row["oe"] += shift
    assert groups(rows) == ([[0, 1], [2, 3]] if split else [[0, 1, 2, 3]])


def test_isolated_word_and_long_word_keep_their_timing():
    rows = words("go electromagneticradiation")
    rows[1].update(os=2, oe=3)
    assert groups(rows) == [[0], [1]]
    assert [(rows[g[0]]["os"], rows[g[-1]]["oe"]) for g in groups(rows)] == [(0, .3), (2, 3)]


@pytest.mark.parametrize("theme", [{"cap_words": 1}, {"cap_words": 2, "cap_chars": 10},
                                  {"cap_words": 5, "cap_chars": 30}])
def test_pack_limits_take_precedence(theme):
    rows = words("we can fly far and get home with our crew")
    got = groups(rows, **theme)
    assert [j for g in got for j in g] == list(range(len(rows)))
    assert all(len(g) <= theme["cap_words"] for g in got)
    assert all(len(" ".join(rows[j]["w"] for j in g)) <= theme.get("cap_chars", 18) for g in got)
    if theme["cap_words"] == 1:
        assert got == [[j] for j in range(len(rows))]


def test_zing_caption_fields():
    theme = render.theme("zing")
    assert theme.items() >= {
        "cap_bg": "none", "cap_ink": "#FFFFFF", "cap_on": "#FFD23F", "cap_upper": True,
        "cap_font": "ZingCaption", "cap_weight": 900, "cap_size": 78,
        "cap_stroke": "#050C24", "cap_stroke_w": 7,
        "cap_shadow": "0 6px 18px rgba(0,0,0,.55)", "cap_scale": 1.06,
    }.items()
    assert render.check_pack(theme) == []


def test_scene_defaults_use_the_zing_caption_look():
    got = javascript("scene.html", "console.log(JSON.stringify(document.documentElement.style));")
    assert got["--cap-size"] == "78px" and got["--cap-bg"] == "transparent"
    assert got["--cap-stroke"] == "7px #050C24" and got["--cap-ink"] == "#FFFFFF"
    assert got["--cap-scale"] == 1.06


@pytest.mark.parametrize("pack,size,font,bg,ink", [
    ("headline", 58, "Inter", "transparent", "#FFE9A8"),
    ("newsdesk", 54, "Inter", "#F4F1E8", "#121417"),
    ("swiss", 54, "Inter", "#111111", "#FFFFFF"),
    ("documentary", 66, "Instrument Serif", "transparent", "#F7F2E7"),
    ("launch", 50, "Inter", "transparent", "#FFFFFF"),
])
@pytest.mark.parametrize("shape", ["9x16", "16x9"])
def test_other_packs_keep_caption_styles(pack, size, font, bg, ink, shape):
    theme = render.theme(pack)
    width, height = render.SHAPES[shape]
    got = javascript("scene.html", "console.log(JSON.stringify(document.documentElement.style));",
                     {"words": [], "fps": 30, "W": width, "H": height, "theme": theme})
    assert got["--cap-size"] == f"{round(size * min(width, height) / 1080) if 'cap_size' in theme else size}px"
    assert got["--cap-font"] == f'"{font}", Inter, sans-serif'
    assert got["--cap-bg"] == bg and got["--cap-ink"] == ink
    assert got["--cap-scale"] == 1 and "--cap-stroke" not in got


def geometry(layout, shape="9x16", theme=None):
    script = SCENE.read_text(encoding="utf-8")
    code = script[script.index("// Geometry per delivery shape."):script.index("function place(")]
    return javascript("scene.html", code + f"\nconsole.log(JSON.stringify(geometry({json.dumps(layout)})));",
                      {"words": [], "fps": 30, "W": render.SHAPES[shape][0], "H": render.SHAPES[shape][1],
                       "aspect": shape, "theme": theme or render.theme("zing")})


def test_solo_fills_the_frame_and_captions_stay_above_phone_controls():
    got = geometry("solo")
    assert got["spk"] == {"x": 0, "y": 400, "w": 1080, "h": 1520}
    assert 1240 <= got["cap"] <= 1440
    assert geometry("split")["cap"] == 960
    full = geometry("split", theme={"cutaway": "full"})
    assert full["top"] == {"x": 0, "y": 0, "w": 1080, "h": 1920}
    assert 1240 <= full["cap"] <= 1440


@pytest.mark.parametrize("layout", ["solo", "split", "graphic"])
def test_explicit_caption_position_and_split_order(layout):
    got = geometry(layout, theme={"cap_y": .63, "seam": .6, "split": "speaker-top"})
    assert got["cap"] == round((.63 if layout == "solo" else .6) * 1920)
    if layout != "solo":
        assert got["spk"]["y"] == 0 and got["spk"]["h"] == round(.6 * 1920)


def test_explicit_full_cut_position_and_launch_seam_stay_put():
    assert geometry("graphic", theme={"cutaway": "full", "cap_y": .63})["cap"] == round(.63 * 1920)
    assert geometry("solo", theme=render.theme("launch"))["cap"] == round(.86 * 1920)
    assert geometry("split", theme=render.theme("launch"))["cap"] == 960


@pytest.mark.parametrize("shape", ["1x1", "4x5", "16x9"])
def test_other_shapes_keep_placement_and_scale_type_by_short_side(shape):
    width, height = render.SHAPES[shape]
    assert geometry("solo", shape)["cap"] == height - 180
    got = javascript("scene.html", "console.log(JSON.stringify(document.documentElement.style));",
                     {"words": [], "fps": 30, "W": width, "H": height, "theme": render.theme("zing")})
    assert got["--cap-size"] == f"{round(78 * min(width, height) / 1080)}px"  # 16x9 is not 1.8x bigger


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6])
def test_list_block_centers_using_its_final_count(n):
    got = javascript("scene.html", f"console.log(JSON.stringify(listLayout({n}))); ")
    assert (got["title"] + got["items"][-1] + 88) / 2 == pytest.approx(480)
    assert got["title"] >= 150
    assert got["items"][0] - got["title"] == 96
    assert all(b - a >= 88 for a, b in zip(got["items"], got["items"][1:]))


def test_list_items_reveal_without_moving():
    got = javascript("scene.html", """
      const items = [0,1,2].map(() => ({style:{}}));
      const el = {dataset:{}, querySelectorAll:() => items};
      const g = {id:'list', kind:'list', from:0, title:'Training',
                 items:['Learn','Train','Fly'].map((text,i) => ({text, at:i}))};
      const states = [.2, 3, .2].map(t => { drawGraphic(g,t,el);
        return {html:el.innerHTML, items:items.map(it => ({...it.style}))}; });
      console.log(JSON.stringify(states));
    """)
    assert got[0] == got[2]
    assert got[0]["html"] == got[1]["html"]
    assert got[0]["html"].count("font-size:64px") == 3
    assert 0 < got[0]["items"][0]["opacity"] < 1
    assert [it["opacity"] for it in got[0]["items"][1:]] == [0, 0]
    assert got[1]["items"] == [{"opacity": 1}] * 3


def test_long_caption_fits_without_shrinking_the_next_group():
    script = SCENE.read_text(encoding="utf-8")
    fit = script[script.index("function fitCaption("):script.index("function geometry(")]
    got = javascript("scene.html", "const SW = 1080;\n" + fit + """
      let letters = 31;
      const box = {style:{}, get offsetWidth() {return letters * parseFloat(this.style.fontSize);}};
      const sizes = [];
      fitCaption(box, 0); sizes.push(parseFloat(box.style.fontSize));
      letters = 6; fitCaption(box, 1); sizes.push(parseFloat(box.style.fontSize));
      letters = 31; fitCaption(box, 0); sizes.push(parseFloat(box.style.fontSize));
      console.log(JSON.stringify(sizes));
    """)
    assert 0 < got[0] < 78
    assert got[0] * 31 * 1.06 * 1.03 + 14 <= 900
    assert got[1] == 78 and got[2] == got[0]


@pytest.mark.parametrize("zoom,focus", [(1, .38), (2.2, .9)])
def test_taller_speaker_crop_excludes_burned_in_captions(zoom, focus):
    got = javascript("scene.html", rf"""
      const img = {{style: {{}}}};
      cover(img, 1920, 1080, 1080, 1520, {zoom}, .5, {focus}, .72);
      console.log(JSON.stringify(img.style.transform.match(/-?[\d.]+/g).map(Number)));
    """)
    x, y, scale = got
    assert (1520 - y) / scale <= .72 * 1080 + .001
    assert y <= 0 and x <= 0
