from __future__ import annotations

import json
from pathlib import Path

import pytest

from myzing.factory import judge, render
from test_factory_brand_kit import browser_tools
from test_factory_caption_faces import data, scene
from test_factory_review_fixes import javascript


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)


@pytest.fixture
def clip(tmp_path):
    d = tmp_path / "clip01"
    d.mkdir()
    for name, value in [
        ("plan", {"hook": "A test", "shots": [{"from": 0, "layout": "solo"}], "visuals": {}}),
        ("words", {"words": [{"w": "Test.", "os": 3.3, "oe": 3.8}]}),
        ("cams", {"size": [640, 360], "frames": 120, "cams": [
            {"from": 0, "to": 4, "mode": "face", "cx": .5, "cy": .35, "fh": .3}]}),
    ]:
        (d / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
    return d


def prepared(d, shape="9x16"):
    return render.scene_data(d, shape, "zing", parallax=False, front=False, sharpen=False)


def counter(graphic, times):
    return javascript("scene.html", """
      const num = {style:{}}, lab = {style:{}};
      const el = {dataset:{id:'g'}, querySelector:s => s === '.g-num' ? num : lab};
      const states = TIMES.map(t => {
        drawGraphic({id:'g', kind:'counter', from:5.2, value:18000, ...GRAPHIC}, t, el);
        return {text:num.textContent, transform:num.style.transform, opacity:lab.style.opacity};
      });
      console.log(JSON.stringify(states));
    """.replace("GRAPHIC", json.dumps(graphic)).replace("TIMES", json.dumps(times)))


@pytest.mark.parametrize("at", [5.2, 5.3, 5.85, 6.6])
def test_counter_finishes_on_the_spoken_word(at):
    states = counter({"at": at}, [at, at + .1, at + 1])
    assert all(s["text"] == "18,000" and s["opacity"] == 1 for s in states)
    assert states[0]["transform"] == "scale(1)"


def test_counter_moves_as_soon_as_the_card_appears():
    times = [5.2 + i/30 for i in range(1, 20)]
    states = counter({"at": 6.6}, times)
    values = [int(s["text"].replace(",", "")) for s in states]
    assert 0 < values[0] < values[-1] <= 18000
    assert values == sorted(values)
    assert states == counter({"at": 6.6}, times[::-1])[::-1]


@pytest.mark.parametrize("graphic,want", [({"value": 1886, "format": "year"}, "1886"),
                                         ({"value": 12}, "12"),
                                         ({"value": 42.5, "prefix": "$", "suffix": "M"}, "$42.5M")])
def test_counter_keeps_whole_years_small_values_and_decimals(graphic, want):
    assert counter({**graphic, "at": 5.4}, [5.4])[0]["text"] == want


@pytest.mark.parametrize("video", [False, True])
@pytest.mark.parametrize("fit", [None, "contain"])
def test_visual_fitting_excludes_baked_black_bars(clip, monkeypatch, video, fit):
    Image = pytest.importorskip("PIL.Image")
    picture = Image.new("RGB", (640, 360))
    picture.paste((180, 210, 240), (0, 40, 640, 320))
    path = clip / ("visual.mp4" if video else "visual.png")
    if video:
        path.write_bytes(b"video")
        def extract(*argv, **kwargs):
            for i in range(1, 4):
                picture.save(Path(argv[-1]).parent / f"{i:05d}.jpg")
        monkeypatch.setattr(render, "run", extract)
        monkeypatch.setattr(render, "ffmpeg", lambda: "ffmpeg")
    else:
        picture.save(path)
    plan = {"hook": "A test", "shots": [{"from": 0, "layout": "split", "visual": "v1"}],
            "visuals": {"v1": {"path": str(path), "fit": fit}}}
    (clip / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    value = prepared(clip)
    assert value["visuals"]["v1"].get("crop") == [0, 40, 640, 280]
    got = scene(value, r"""
      await window.seek(.5);
      console.log(JSON.stringify({crop:$('topImg').style.transform.match(/-?[\d.]+/g).map(Number),
        blur:$('topBlur').style.transform.match(/-?[\d.]+/g).map(Number),
        clip:$('topImg').style.clipPath, box:visualBox(geometry('split'), shotAt(.5))}));
    """)
    x, y, scale = got["crop"]
    bx, by, bs = got["blur"]
    assert bx <= 0 and by + 40*bs <= 0 and bx + 640*bs >= 1080 and by + 320*bs >= 960
    if fit == "contain":
        assert x == pytest.approx(0) and y + 40*scale > 0 and y + 320*scale < 960
        assert got["clip"] == "inset(40px 0px 40px 0px)"
        assert got["box"] == {"y0": pytest.approx(y + 40*scale), "y1": pytest.approx(y + 320*scale)}
    else:
        assert x <= 0 and y + 40*scale <= 0 and x + 640*scale >= 1080 and y + 320*scale >= 960


@pytest.mark.parametrize("box,want", [((0, 0, 640, 360), None), ((0, 40, 640, 360), None),
                                      ((0, 0, 0, 0), None), ((0, 120, 640, 240), None),
                                      ((64, 0, 576, 360), [64, 0, 512, 360])])
def test_picture_crop_leaves_dark_or_unbalanced_edges_alone(tmp_path, box, want):
    Image = pytest.importorskip("PIL.Image")
    path = tmp_path / "visual.png"
    picture = Image.new("RGB", (640, 360))
    picture.paste("white", box)
    picture.save(path)
    assert render.picture_crop([path]) == want


def test_video_crop_keeps_every_sample_visible(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    files = []
    for i, edge in enumerate([40, 40, 30, 40, 40]):
        path = tmp_path / f"{i}.png"
        picture = Image.new("RGB", (640, 360))
        picture.paste("white", (0, edge, 640, 360-edge))
        picture.save(path)
        files.append(path)
    assert render.picture_crop(files) == [0, 30, 640, 300]


@pytest.mark.parametrize("shape", render.SHAPES)
@pytest.mark.parametrize("move", [False, True])
def test_uncropped_visuals_keep_cover_and_focus_when_seeking(shape, move):
    value = data(shape=shape, layout="split", visuals={"v1": {
        "w": 640, "h": 360, "frames": 30, "dir": "video", "move": move}})
    got = scene(value, r"""
      const states = [];
      for (const t of [.5, 3, .5]) {
        await window.seek(t);
        states.push({crop:$('topImg').style.transform.match(/-?[\d.]+/g).map(Number),
          src:$('topImg').dataset.src, clip:$('topImg').style.clipPath, panel:geometry('split').top});
      }
      console.log(JSON.stringify(states));
    """)
    assert got[0] == got[2]
    for state in got:
        x, y, scale = state["crop"]
        assert x <= 0 and y <= 0 and x + 640*scale >= state["panel"]["w"] - 1e-6
        assert y + 360*scale >= state["panel"]["h"] - 1e-6 and state["clip"] == ""


def test_solo_hook_shrinks_after_the_hook_window():
    value = data(theme=render.theme("zing"), hookUntil=1)
    value["shots"] = [{"from": a, "to": b, "layout": layout, "visual": "v1"}
                      for a, b, layout in [(0, 2, "solo"), (2, 3, "split"), (3, 4, "solo")]]
    got = scene(value, """
      const states = [];
      for (const t of [.5, 1.5, 2.5, 3.5, .5]) {
        await window.seek(t);
        states.push({size:parseFloat($('hook').style.fontSize), hook:$('hook').style.opacity,
          pill:$('pill').style.opacity});
      }
      console.log(JSON.stringify(states));
    """)
    assert got[0]["size"] == 74 and got[0]["hook"] == 1
    assert 0 < got[1]["size"] <= 44 and got[1]["hook"] == 1
    assert got[2]["hook"] == got[2]["pill"] == 0
    assert got[3] == got[1] and got[4] == got[0]


@pytest.mark.parametrize("theme,until", [({}, 0), ({"hook_header": False}, 1), ({"solo_fill": True}, 1)])
def test_disabled_hook_or_header_does_not_persist(theme, until):
    got = scene(data(theme=theme, hookUntil=until), """
      await window.seek(2);
      console.log(JSON.stringify([$('hook').style.opacity, $('pill').style.opacity]));
    """)
    assert got == [0, 0]


@pytest.mark.parametrize("fit", [None, "contain"])
@pytest.mark.parametrize("padded", [False, True])
def test_picture_credit_is_readable_on_white(tmp_path, browser_tools, fit, padded):
    Image = pytest.importorskip("PIL.Image")
    path = tmp_path / "white.png"
    picture = Image.new("RGB", (640, 360), "black" if padded else "white")
    picture.paste("white", (0, 40, 640, 320))
    picture.save(path)
    frames = tmp_path / "speaker"
    frames.mkdir()
    Image.new("RGB", (640, 360), "gray").save(frames / "00001.jpg")
    value = data(layout="split", frames=1, framesDir=frames.as_uri(), visuals={
        "v1": {"src": path.as_uri(), "w": 640, "h": 360, "fit": fit, "credit": "Photo credit",
               **({"crop": [0, 40, 640, 280]} if padded else {})}})
    render.capture(value, tmp_path / "data.json", tmp_path / "capture", samples=[15])
    with Image.open(tmp_path / "capture/00016.png") as image:
        assert max(image.getpixel((1054, 30))[:3]) < 180
        if fit == "contain" or padded:
            assert min(image.getpixel((540, 80))[:3]) > 80
            assert min(image.getpixel((540, 880))[:3]) > 80


def test_short_untracked_closing_cut_holds_the_last_tracked_frame(clip):
    file = clip / "cams.json"
    cams = json.loads(file.read_text(encoding="utf-8"))
    cams["cams"][0]["to"] = 3.7
    cams["cams"].append({"from": 3.7, "to": 4, "mode": "wide", "faces": 3})
    file.write_text(json.dumps(cams), encoding="utf-8")
    value = prepared(clip)
    got = scene(value, """
      await window.seek(D.duration - 1/FPS);
      console.log(JSON.stringify({mode:camAt(D.duration - 1/FPS).mode, src:$('spkImg').dataset.src,
        to:camAt(D.duration - 1/FPS).to}));
    """)
    assert got["mode"] == "face" and got["src"].endswith("/00111.jpg")
    assert got["to"] >= value["duration"]
    assert value["duration"] == 4.25 and json.loads(file.read_text(encoding="utf-8")) == cams


@pytest.mark.parametrize("tail", [{"from": 2, "to": 4}, {"text": True}, {"text_box": [.1, .1, .9, .9]},
                                  {"faces": 1}, {"mode": "face", "cx": .6, "cy": .4, "fh": .2}])
def test_longer_closing_shots_and_text_keep_their_camera(clip, tail):
    file = clip / "cams.json"
    cams = json.loads(file.read_text(encoding="utf-8"))
    last = {"from": 3.7, "to": 4, "mode": "wide", "faces": 3, **tail}
    cams["cams"][0]["to"] = last["from"]
    cams["cams"].append(last)
    file.write_text(json.dumps(cams), encoding="utf-8")
    value = prepared(clip)
    assert value["cams"] == cams["cams"] and value["frames"] == 120


@pytest.mark.parametrize("shape", render.SHAPES)
@pytest.mark.parametrize("uhd", [False, True])
def test_encode_has_a_social_quality_target_and_keeps_uhd(clip, monkeypatch, shape, uhd):
    calls = []
    (clip.parent / "factory.json").write_text(json.dumps({"uhd": uhd}), encoding="utf-8")
    monkeypatch.setattr(render, "capture", lambda *a, **kw: None)
    monkeypatch.setattr(render, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(render.tools, "run", lambda *a, **kw: None)
    def encode(*argv, **kwargs):
        calls.append(argv)
        Path(argv[-1]).write_bytes(b"mp4")
    monkeypatch.setattr(render, "run", encode)
    out = render.render(clip, shape, parallax=False, front=False, sharpen=False)
    enc = calls[0]
    assert out.is_file() and enc[enc.index("-c:v") + 1] == "libx264"
    assert enc[enc.index("-crf") + 1] == 20
    assert enc[enc.index("-preset") + 1] == ("medium" if uhd else "slow")
    assert enc[enc.index("-maxrate") + 1] == ("40M" if uhd else "12M")
    assert enc[enc.index("-bufsize") + 1] == ("80M" if uhd else "24M")
    assert enc[enc.index("-pix_fmt") + 1] == "yuv420p"
    assert enc[enc.index("-movflags") + 1] == "+faststart"
