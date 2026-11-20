from __future__ import annotations

import json
import math
import re

import pytest

from myzing.factory import render
from test_factory_caption_craft import words
from test_factory_caption_faces import data
from test_factory_look_polish import text_nodes
from test_factory_looks import scene


def face(start, end, cy, fh):
    return {"from": start, "to": end, "mode": "face", "cx": .44, "cy": cy, "fh": fh}


def clip(pack, cams, shape="9x16"):
    return data(shape=shape, src=(1280, 720), theme=render.theme(pack), cams=cams,
                words=words("We fly home. We train here. We fly far."))


def captions(value, times):
    return scene(value, """
      const frames = [];
      for (const t of TIMES) {
        await window.seek(t);
        const spk = $('spk').style, cap = $('cap');
        frames.push({speaker:[spk.left, spk.top, spk.width, spk.height].map(parseFloat),
          top:parseFloat(cap.style.top), transform:cap.style.transform, visible:+cap.style.opacity,
          svg:cap.firstChild.innerHTML});
      }
      console.log(JSON.stringify(frames));
    """.replace("TIMES", json.dumps(times)))


@pytest.mark.parametrize("pack", ["desk", "editorial"])
def test_tight_faces_leave_room_below_the_speaker(pack):
    value = clip(pack, [face(0, 2, .57, .43), face(2, 4, .66, .49)])
    frames = captions(value, [f / 30 for f in range(120)])
    for frame in frames:
        assert frame["speaker"] == [0, 180, 1080, 1150]
        if frame["visible"]:
            assert frame["top"] == 1360
            assert frame["transform"] == "none"
            lines = text_nodes(frame["svg"])
            assert lines
            for i, line in enumerate(lines):
                # The band places each baseline 0.76 em below its line top.
                top = frame["top"] + float(line.get("y")) - .76 * float(line.get("font-size"))
                assert top >= 1360 and top > frame["speaker"][1] + frame["speaker"][3]
                if i == 0:
                    assert top == pytest.approx(1360)
    assert any(f["visible"] for f in frames[:60]) and any(f["visible"] for f in frames[60:])


@pytest.mark.parametrize("pack,shape,cy,fh,speaker,anchor,transform", [
    ("desk", "9x16", .35, .20, [0, 0, 1080, 1920], 1150, "translateY(-100%)"),
    ("newsroom", "9x16", .66, .49, [0, 600, 1080, 608], 1258, "none"),
    ("desk", "16x9", .66, .49, [0, 0, 1920, 1080], 975, "translateY(-100%)"),
])
def test_roomy_faces_newsroom_and_landscape_keep_their_band(pack, shape, cy, fh, speaker, anchor, transform):
    for frame in captions(clip(pack, [face(0, 4, cy, fh)], shape), [.1, 1.5, 3.1]):
        assert frame["visible"] and text_nodes(frame["svg"])
        assert (frame["speaker"], frame["top"], frame["transform"]) == (speaker, anchor, transform)


@pytest.mark.parametrize("tight_frames,speaker", [(14, [0, 0, 1080, 1920]), (15, [0, 180, 1080, 1150])])
def test_one_quarter_of_face_time_triggers_framing(tight_frames, speaker):
    # Two seconds contain faces. The other two seconds must not dilute the threshold.
    cut = tight_frames / 30
    cams = [face(0, cut, .66, .49), face(cut, 2, .35, .20), {"from": 2, "to": 4, "mode": "wide"}]
    for frame in captions(clip("desk", cams), [.1, 1, 3]):
        assert frame["speaker"] == speaker


@pytest.mark.parametrize("items,size", [
    (["Set up", "Record", "Play back"], 96),
    (["Set the input level", "Record a short voice sample", "Listen for background noise",
      "Move closer to the microphone", "Compare both recordings", "Save the clearest version"], 64),
], ids=["short-three", "long-six"])
def test_list_card_fits_every_item_and_its_number(items, size):
    graphic = {"kind": "list", "title": "Sound check", "items": [{"text": item} for item in items]}
    value = data(theme=render.theme("desk"), shots=[{"from": 0, "to": 4, "layout": "graphic", "graphic": graphic}])
    markup = scene(value, "await window.seek(3); console.log(JSON.stringify($('gfxIn').innerHTML));")
    title, *rows = text_nodes(markup)
    assert title.text == graphic["title"] and float(title.get("font-size")) == pytest.approx(max(44, .62 * size))
    lines = []
    for node in [title, *rows]:
        x, y, fs = (float(node.get(key)) for key in ("x", "y", "font-size"))
        # The scene harness measures an advance of half an em per character.
        assert 0 <= x < x + len(node.text) * fs * .5 <= value["W"]
        assert 0 <= y - fs and y + .25 * fs <= value["H"]
        if node is title:
            continue
        assert fs == size
        if node.text == f"{len(lines) + 1}.":
            assert x == 72
            lines.append([])
        else:
            assert x == pytest.approx(72 + 1.6 * size)
            lines[-1].append(node.text)
    assert [" ".join(row) for row in lines] == items
    assert all(1 <= len(row) <= 2 for row in lines)


@pytest.fixture
def pop_clip():
    value = clip("pop", [face(0, 1, .35, .20), face(1, 4, .52, .16)])
    text = "We can fly we can run. Rockets return safely! Don’t look back?"
    value["words"] = [{"w": w, "os": i / 5, "oe": i / 5 + .16} for i, w in enumerate(text.split())]
    return value


def test_pop_pages_show_short_capitals_and_color_the_newest_line(pop_clip):
    frames = captions(pop_clip, [f / 30 for f in range(72)])
    theme = pop_clip["theme"]
    pages = []
    for frame in frames:
        assert frame["visible"]
        nodes = text_nodes(frame["svg"])
        assert 1 <= len(nodes) <= 2
        assert [n.get("fill") for n in nodes] == [theme["cap_ink"]] * (len(nodes) - 1) + [theme["cap_on"]]
        assert all(n.get("font-family") == "Lilita One" for n in nodes)
        lines = [n.text for n in nodes]
        assert all(len(line.split()) <= 3 and len(line) <= 16 for line in lines)
        if not pages or pages[-1] != lines:
            pages.append(lines)
    assert pages == [["WE CAN FLY"], ["WE CAN FLY", "WE CAN RUN"], ["ROCKETS"],
                     ["ROCKETS", "RETURN SAFELY"], ["DON'T LOOK BACK"]]


@pytest.mark.parametrize("settings", [{}, {"cap_pop_from": 1.4, "cap_pop_ms": 240}], ids=["built-in", "custom"])
def test_pop_starts_at_the_pack_scale_and_settles_after_its_duration(pop_clip, settings):
    theme = pop_clip["theme"]
    theme.update(settings)
    start = pop_clip["words"][3]["os"]  # second line appears while the first stays up
    end_frame = math.ceil(theme["cap_pop_ms"] * pop_clip["fps"] / 1000)
    frames = captions(pop_clip, [start + f / pop_clip["fps"] for f in [0, 1, end_frame - 1, end_frame]])
    scales = []
    for frame in frames:
        old, new = text_nodes(frame["svg"])
        assert old.text == "WE CAN FLY" and new.text == "WE CAN RUN"
        assert "scale(1)" in old.get("transform")
        scales.append(float(re.search(r"scale\(([^)]+)\)", new.get("transform"))[1]))
    assert scales[0] == pytest.approx(theme["cap_pop_from"])
    assert scales[0] > scales[1] > scales[2] > scales[3]
    assert scales[3] == pytest.approx(1)


@pytest.mark.parametrize("shape,framed", [("9x16", False), ("9x16", True), ("16x9", False)])
def test_pop_keeps_one_position_across_faces_and_pages(pop_clip, shape, framed):
    cams = [face(0, 1, .35, .20), face(1, 4, .66, .49)] if framed else pop_clip["cams"]
    value = clip("pop", cams, shape)
    value["words"] = pop_clip["words"]
    frames = captions(value, [f / 30 for f in range(0, 72, 3)])
    assert all(f["visible"] and f["transform"] == "none" for f in frames)
    top, = {f["top"] for f in frames}
    if shape == "16x9":
        assert value["H"] * 2 / 3 <= top < value["H"] - 2 * value["theme"]["cap_size"]
    elif framed:
        assert frames[0]["speaker"] == [0, 180, 1080, 1150]
        assert 1330 < top < 1400
    else:
        # The 720px-high source fills 1920px, so the lowest chin is at (.52 + .6*.16)*1920.
        assert top == pytest.approx((.52 + .6 * .16) * 1920 + 12)


def test_pop_clears_a_chin_just_above_the_framing_threshold():
    value = clip("pop", [face(0, 4, .62, .16)])
    frame, = captions(value, [.2])
    assert frame["visible"]
    _, y, _, h = frame["speaker"]
    assert frame["top"] >= y + (.62 + .6 * .16) * h


def test_pop_captions_need_a_named_look(pop_clip):
    del pop_clip["theme"]["look"]
    assert render.check_pack(pop_clip["theme"]) == ["captions pop needs a look: desk, editorial or newsroom"]


def test_exported_pop_cues_match_the_active_lines(pop_clip):
    cues = scene(pop_clip, "console.log(JSON.stringify(window.captionCues()));")
    frames = captions(pop_clip, [f / 30 for f in range(72)])
    active = []
    for frame in frames:
        assert frame["visible"]
        newest = text_nodes(frame["svg"])[-1].text
        if not active or active[-1] != newest:
            active.append(newest)
    assert all(cue["text"].isupper() for cue in cues)
    assert [cue["text"] for cue in cues] == active


def test_pop_pack_loads_and_validates():
    assert "pop" in render.themes()
    assert render.check_pack("pop") == []
    assert render.theme("pop")["captions"] == "pop"
    assert render.check_pack({"captions": "bogus"}) == ["captions must be band or pop"]


def timed(value, spoken):
    value["words"] = [{"w": w, "os": start, "oe": start + .2} for w, start in spoken]
    return value


def test_pop_frames_a_short_close_up_that_desk_lets_its_band_handle():
    cams = [face(0, .5, .66, .49), face(.5, 4, .35, .20)]
    assert captions(clip("pop", cams), [1])[0]["speaker"] == [0, 180, 1080, 1150]
    assert captions(clip("desk", cams), [1])[0]["speaker"] == [0, 0, 1080, 1920]


def test_desk_frames_a_clip_whose_band_would_have_to_jump():
    frames = captions(clip("desk", [face(0, 2, .35, .20), face(2, 4, .66, .10)]), [f / 10 for f in range(2, 38)])
    assert {tuple(f["speaker"]) for f in frames} == {(0, 180, 1080, 1150)}
    assert len({f["top"] for f in frames if f["visible"]}) == 1


def test_a_close_up_behind_a_card_does_not_frame_the_clip():
    value = clip("desk", [face(0, 4, .35, .20), face(4, 6, .66, .49)])
    value["duration"] = 6
    graphic = {"kind": "list", "title": "Plan", "items": [{"text": "Fly"}, {"text": "Land"}]}
    value["shots"] = [{"from": 0, "to": 4, "layout": "solo"}, {"from": 4, "to": 6, "layout": "graphic", "graphic": graphic}]
    assert captions(value, [1])[0]["speaker"] == [0, 0, 1080, 1920]
    value["shots"][1] = {"from": 4, "to": 6, "layout": "solo"}
    assert captions(value, [1])[0]["speaker"] == [0, 180, 1080, 1150]


def test_pop_keeps_signs_decimals_and_names_with_symbols(pop_clip):
    spoken = ["Down", "-12%", "today.", "Only", ".5", "left!", "“Paid", "$5,", "then”", "C++", "and", "C#."]
    timed(pop_clip, [(w, i * .3) for i, w in enumerate(spoken)])
    seen = []
    for frame in captions(pop_clip, [f / 10 for f in range(40)]):
        for node in text_nodes(frame["svg"]):
            if node.text not in seen:
                seen.append(node.text)
    assert " ".join(seen) == "DOWN -12% TODAY ONLY .5 LEFT PAID $5 THEN C++ AND C#"


def test_a_long_pop_line_stays_inside_the_frame_while_it_pops(pop_clip):
    timed(pop_clip, [("www.example.com/docs/guides/start", .5)])
    frames = captions(pop_clip, [.5 + f / 30 for f in range(6)])
    scales = []
    for frame in frames:
        node, = text_nodes(frame["svg"])
        scale = float(re.search(r"scale\(([^)]+)\)", node.get("transform"))[1])
        # The scene harness measures an advance of half an em per character.
        assert len(node.text) * float(node.get("font-size")) * .5 * scale <= pop_clip["W"]
        scales.append(scale)
    assert scales[0] > 1 and scales[-1] == pytest.approx(1)


def test_exported_pop_cues_follow_the_screen_through_pauses_and_cards(pop_clip):
    timed(pop_clip, [("First.", .03), ("Second.", .51), ("Third", 3.01), ("word.", 3.3)])
    graphic = {"kind": "list", "title": "Plan", "items": [{"text": "Fly"}, {"text": "Land"}]}
    pop_clip["shots"] = [{"from": 0, "to": 3.2, "layout": "solo"},
                         {"from": 3.2, "to": 4, "layout": "graphic", "graphic": graphic}]
    cues = scene(pop_clip, "console.log(JSON.stringify(window.captionCues()));")
    fps = pop_clip["fps"]
    frames = captions(pop_clip, [f / fps for f in range(4 * fps)])
    for f, frame in enumerate(frames):
        t = (f + .5) / fps
        said = [cue["text"] for cue in cues if cue["from"] <= t < cue["to"]]
        shown = [text_nodes(frame["svg"])[-1].text] if frame["visible"] else []
        assert said == shown, f
    assert [cue["text"] for cue in cues] == ["FIRST", "SECOND", "THIRD WORD"]
    assert cues[1]["to"] < 1.6 and cues[2]["to"] <= 3.2 + 1 / fps


def test_a_long_list_title_stays_inside_the_frame():
    graphic = {"kind": "list", "title": "What to check before you hit record today",
               "items": [{"text": item} for item in ["Set up", "Record", "Play back"]]}
    value = data(theme=render.theme("desk"), shots=[{"from": 0, "to": 4, "layout": "graphic", "graphic": graphic}])
    markup = scene(value, "await window.seek(3); console.log(JSON.stringify($('gfxIn').innerHTML));")
    title, *rows = text_nodes(markup)
    x, size = float(title.get("x")), float(title.get("font-size"))
    assert title.text == graphic["title"] and size >= 44
    assert x + len(title.text) * size * .5 <= value["W"] - 72 + 1
    assert all(float(row.get("font-size")) == 96 for row in rows)
