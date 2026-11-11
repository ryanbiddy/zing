from __future__ import annotations

import json

import pytest

from myzing.factory import judge, pick, render
from test_factory_caption_craft import words
from test_factory_caption_faces import data, frames, scene


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)


def page(shape="9x16", **extra):
    value = data(shape=shape, layout="split", src=(1280, 720),
                 cam={"cy": .63, "fh": .45, "wide": True}, **extra)
    value["visuals"]["v1"].update(w=1280, h=800, fit="contain", page=True)
    return value


def plates(value, times=(.5,)):
    return scene(value, """
      const states = [];
      for (const t of TIMES) {
        await window.seek(t);
        const box = $('cap').firstChild;
        states.push({background:box.style.background || '', padding:box.style.padding || '',
          radius:box.style.borderRadius || '', top:$('top').style.display, quote:$('quote').style.display});
      }
      console.log(JSON.stringify(states));
    """.replace("TIMES", json.dumps(times)))


@pytest.mark.parametrize("theme", [{}, render.theme("zing"), {"cap_y": .5, "cap_scale": 1.5}])
def test_face_avoidance_cannot_move_captions_back_into_the_page(theme):
    value = page(theme=theme)
    for state in frames(value, [i/30 for i in range(1, 33)]):
        assert state["caption"]["y0"] >= 817.5
        assert state["caption"]["y1"] <= 1440


def test_page_limit_holds_across_a_shot_change_in_either_seek_order():
    value = page()
    value["shots"] = [{**value["shots"][0], "layout": layout, "from": a, "to": b}
                      for layout, a, b in [("solo", 0, .6), ("split", .6, 4)]]
    times = [.1, .5, .9, 1.1]
    forward, reverse = frames(value, times), frames(value, times[::-1])
    assert forward == reverse[::-1]
    assert len({s["cy"] for s in forward}) == 1
    assert all(s["caption"]["y0"] >= 817.5 for s in forward)


@pytest.mark.parametrize("theme", [{}, render.theme("zing"), render.theme("documentary")])
def test_landscape_page_has_a_dark_caption_plate(theme):
    state = plates(page("16x9", theme=theme))[0]
    assert state["background"] == "rgba(5,12,36,.75)"
    assert state["padding"] == ".18em .45em"
    assert state["radius"] == ".18em"


@pytest.mark.parametrize("kind", ["photo", "logo", "footage"])
def test_non_pages_keep_the_caption_look(kind):
    value = page("16x9")
    value["visuals"]["v1"].pop("page")
    if kind != "logo":
        value["visuals"]["v1"].pop("fit")
    if kind == "footage":
        value["shots"][0]["layout"] = "solo"
    state = plates(value)[0]
    assert state["background"] == state["padding"] == state["radius"] == ""


def test_caption_plate_clears_when_seeking_from_a_page_to_a_photo():
    value = page("16x9")
    value["visuals"]["v2"] = {"src": "photo.jpg", "w": 1280, "h": 800}
    value["shots"] = [{**value["shots"][0], "visual": vid, "from": a, "to": b}
                      for vid, a, b in [("v1", 0, .6), ("v2", .6, 4)]]
    states = plates(value, [.5, .9, .5])
    assert states[0] == states[2]
    assert states[0]["background"] == "rgba(5,12,36,.75)"
    assert states[1]["background"] == states[1]["padding"] == states[1]["radius"] == ""


@pytest.mark.parametrize("pack", ["newsdesk", "swiss"])
def test_page_keeps_the_packs_caption_background(pack):
    theme = render.theme(pack)
    state = plates(page("16x9", theme=theme))[0]
    assert state["background"] in ("", theme["cap_bg"])
    assert state["padding"] == state["radius"] == ""


def test_portrait_kinetic_captions_clear_the_page():
    value = page(theme={**render.theme("documentary"), "cutaway": "split"})
    for state in frames(value):
        assert state["caption"]["y0"] >= 817.5


@pytest.mark.parametrize("shape", ["9x16", "16x9"])
def test_quote_moments_hide_the_page(shape):
    value = page(shape, quotes=[{"from": 0, "to": 2, "a": 0, "b": 2, "marks": []}])
    state = plates(value)[0]
    assert state["top"] == "none" and state["quote"] == "block"


@pytest.mark.parametrize("source,kind,want", [("screenshot", "screenshot", True), ("scroll", "screenshot", True),
                                            ("ogimage", "screenshot", True), ("commons", "photo", False),
                                            ("commons", "logo", False), ("ogimage", "logo", False)])
def test_picked_pages_are_distinct_from_logos(tmp_path, source, kind, want):
    found = pick.chosen(tmp_path, [{"id": "v1", "kind": kind}],
                        {"v1": [{"path": "visual.jpg", "source": source}]}, {})
    assert found["v1"].get("page", False) is want


@pytest.mark.parametrize("video", [False, True])
@pytest.mark.parametrize("saved", [False, True])
def test_page_flag_reaches_the_scene(tmp_path, monkeypatch, video, saved):
    from PIL import Image

    image = tmp_path / "visual.jpg"
    Image.new("RGB", (1280, 800), "white").save(image)
    visual = {"path": str(image.with_suffix(".mp4") if video else image), "fit": "contain", "page": True}
    if saved:
        visual.pop("page")
        (tmp_path / "visuals").mkdir()
        (tmp_path / "visuals" / "requests.json").write_text(
            json.dumps([{"id": "v1", "kind": "screenshot"}]), encoding="utf-8")
    value = page()
    for name, content in [("plan", {"hook": "A page", "shots": value["shots"], "visuals": {"v1": visual}}),
                          ("words", {"words": words("AND MANY PEOPLE"), "duration": 4}),
                          ("cams", {"frames": 120, "size": [1280, 720], "cams": value["cams"]})]:
        (tmp_path / f"{name}.json").write_text(json.dumps(content), encoding="utf-8")
    monkeypatch.setattr(render, "run", lambda *args, **kwargs: Image.open(image).save(str(args[-1]).replace("%05d", "00001")))
    got = render.scene_data(tmp_path, "16x9", {}, parallax=False, front=False, sharpen=False)
    assert got["visuals"]["v1"].get("page") is True
