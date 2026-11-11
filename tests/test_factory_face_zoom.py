from __future__ import annotations

import json

import pytest

from myzing.factory import judge
from test_factory_caption_faces import data, scene


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)


def crops(value, panel=None, lean=1):
    return scene(value, """
      const b = PANEL || geometry(D.shots[0].layout).spk, cam = D.cams[0];
      console.log(JSON.stringify([0, 2, 4].map(t => ({...faceCrop(cam, b, t, LEAN), panel:b}))));
    """.replace("PANEL", json.dumps(panel)).replace("LEAN", str(lean)))


@pytest.mark.parametrize("shape", ["9x16", "1x1", "16x9"])
@pytest.mark.parametrize("lean", [1, 1.06])
def test_face_height_stays_below_two_fifths_of_panel_unless_filling_needs_more(shape, lean):
    value = data(shape=shape, src=(1280, 720), cam={"cy": .57, "fh": .44})
    for r in crops(value, lean=lean):
        fill = max(r["panel"]["w"] / 1280, r["panel"]["h"] / 720)
        assert fill - 1e-6 <= r["s"] <= max(fill * 1.05 * lean, .4 * r["panel"]["h"] / (.44 * 720)) + 1e-6


@pytest.mark.parametrize("shape", ["9x16", "1x1", "16x9"])
@pytest.mark.parametrize("src", [(640, 360), (1280, 720), (1920, 1080)])
def test_zoom_past_filling_the_panel_stays_below_1_6(shape, src):
    for r in crops(data(shape=shape, src=src, cam={"cy": .8, "fh": .1}), lean=1.06):
        fill = max(r["panel"]["w"] / src[0], r["panel"]["h"] / src[1])
        assert fill - 1e-6 <= r["s"] <= max(1.6, fill * 1.05 * 1.06) + 1e-6


def test_head_keeps_margin_above_the_detected_face():
    value = data(src=(1280, 720), cam={"cy": .57, "fh": .44})
    for r in crops(value, {"w": 1080, "h": 960}, lean=1.06):
        assert (.57 - .85 * .44) * 720 * r["s"] + r["ty"] >= -1e-6


def test_head_margin_holds_when_scale_and_face_height_already_fit():
    value = data(src=(1920, 3840), cam={"cy": .4, "fh": .1})
    for r in crops(value, {"w": 1080, "h": 960}, lean=1.06):
        assert r["s"] < 1.6 and .1*3840*r["s"] < .4*960
        assert (.4 - .85*.1)*3840*r["s"] + r["ty"] >= -1e-6


def test_low_face_can_stay_below_the_old_target():
    value = data(src=(1920, 1080), cam={"cy": .8, "fh": .25})
    for r in crops(value):
        assert (.8 * 1080 * r["s"] + r["ty"]) / r["panel"]["h"] > .42


@pytest.mark.parametrize("wide,limit", [(False, 2.2), (True, 1.4)])
def test_low_face_keeps_the_existing_zoom_limit_when_caps_allow_it(wide, limit):
    value = data(src=(3840, 2160), cam={"cy": .9, "fh": .05, "wide": wide})
    for r in crops(value, {"w": 1080, "h": 960}, lean=1.06):
        assert r["s"] == pytest.approx(960/2160*limit)


@pytest.mark.parametrize("burn", [.72, .4])
def test_burned_caption_minimum_overrides_the_caps(burn):
    value = data(src=(640, 360), burnTop=burn)
    for r in crops(value):
        assert r["s"] >= r["panel"]["h"] / (burn * 360)
        assert (r["panel"]["h"] - r["ty"]) / r["s"] <= burn * 360 + 1e-6


@pytest.mark.parametrize("shape", ["1x1", "16x9"])
def test_other_shapes_keep_a_crop_that_meets_the_caps(shape):
    value = data(shape=shape, src=(1920, 1080), cam={"cy": .4, "fh": .3})
    got = scene(value, """
      const b = geometry('solo').spk, cam = D.cams[0], [iw, ih] = D.srcSize;
      const base = Math.max(b.w/iw, b.h/ih), z = clamp(b.h/(cam.fh*ih*3.2*base), 1, 2.2);
      console.log(JSON.stringify({old:crop(iw, ih, b.w, b.h, z*1.025, cam.cx, cam.cy+.06),
        now:faceCrop(cam, b, 2)}));
    """)
    for key in ["tx", "ty", "s"]:
        assert got["now"][key] == pytest.approx(got["old"][key])


@pytest.mark.parametrize("shape,layout", [("9x16", "solo"), ("9x16", "split"), ("1x1", "solo"), ("16x9", "solo")])
@pytest.mark.parametrize("src,fh", [((1920, 1080), .22), ((3840, 2160), .05)])
def test_tile_window_never_shows_its_neighbors(shape, layout, src, fh):
    tile = [.5, .05, .75, .68]
    value = data(shape=shape, layout=layout, src=src, burnTop=.71,
                 cam={"cx": .65, "cy": .33, "fh": fh, "tile": tile})
    got = scene(value, r"""
      await window.seek(2);
      const b = geometry(D.shots[0].layout).spk, cam = D.cams[0];
      const img = $('spkImg');
      const r = faceCrop(cam, b, 2);
      console.log(JSON.stringify({r, panel:b, clip:img.style.clipPath || ''}));
    """)
    r, b = got["r"], got["panel"]
    assert got["clip"].startswith("inset(")
    clip = [float(x.removesuffix("px")) for x in got["clip"][6:-1].split()]
    iw, ih = src
    visible = [max(-r["tx"]/r["s"], clip[3]), max(-r["ty"]/r["s"], clip[0]),
               min((b["w"]-r["tx"])/r["s"], iw-clip[1]), min((b["h"]-r["ty"])/r["s"], ih-clip[2])]
    assert visible[0] >= tile[0]*iw - 1e-6 and visible[2] <= tile[2]*iw + 1e-6
    assert visible[1] >= tile[1]*ih - 1e-6 and visible[3] <= tile[3]*ih + 1e-6
    tw, th = (tile[2]-tile[0])*iw, (tile[3]-tile[1])*ih
    whole = min(b["w"]/tw, b["h"]/th)
    assert r["s"] <= max(whole, min(1.6, .4*b["h"]/(fh*ih))) + 1e-6   # the tile fits one way, or zooms only as far as the caps allow
    assert r["s"] >= min(whole, max(b["w"]/tw, b["h"]/th)) - 1e-6


def test_tile_crossing_the_caption_band_keeps_the_burn_minimum():
    value = data(src=(1920, 1080), burnTop=.4,
                 cam={"tile": [.25, .05, .75, .68], "cy": .3, "fh": .2})
    for r in crops(value):
        assert r["s"] >= r["panel"]["h"]/(.35*1080)
        assert (r["panel"]["h"]-r["ty"])/r["s"] <= .4*1080 + 1e-6


def test_leaving_a_tile_clears_its_clip():
    value = data(src=(1920, 1080), cam={"tile": [.5, .05, .75, .68]})
    value["cams"] = [{**value["cams"][0], "to": 2},
                     {"from": 2, "to": 4, "mode": "wide", "faces": 2}]
    got = scene(value, """
      await window.seek(1);
      const before = $('spkImg').style.clipPath;
      await window.seek(3);
      console.log(JSON.stringify({before, after:$('spkImg').style.clipPath}));
    """)
    assert got["before"].startswith("inset(")
    assert got["after"] == ""
