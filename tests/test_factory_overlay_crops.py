from __future__ import annotations

import json

import pytest

from myzing.factory import render
from test_factory_caption_faces import data, frames, intersects, scene


def crops(value, times):
    return scene(value, r"""
      const out = [];
      for (const t of TIMES) {
        await window.seek(t);
        const b = geometry(captionState(t).layout).spk;
        const [tx, ty, s] = $('spkImg').style.transform.match(/-?[\d.]+/g).map(Number);
        out.push({tx, ty, s, box:[-tx/(1280*s), -ty/(720*s), (b.w-tx)/(1280*s), (b.h-ty)/(720*s)]});
      }
      console.log(JSON.stringify(out));
    """.replace("TIMES", json.dumps(times)))


def clear(a, b):
    return a[2] <= b[0]+1e-6 or a[0] >= b[2]-1e-6 or a[3] <= b[1]+1e-6 or a[1] >= b[3]-1e-6


@pytest.mark.parametrize("shape", ["9x16", "1x1"])
@pytest.mark.parametrize("mode", ["face", "wide"])
def test_speaker_window_clears_the_overlay_at_its_own_boundaries(shape, mode):
    box = [0, .04, .47, .9]
    value = data(shape=shape, layout="split" if shape == "9x16" else "solo", src=(1280, 720),
                 cam={"mode": mode, "cx": .65, "cy": .3, "fh": .26},
                 overlays=[{"from": .6, "to": 2.4, "box": box}])
    times = [.59, .6, 1, 2.39, 2.4, 3]
    got = crops(value, times)
    plain = crops({**value, "overlays": []}, times)
    for i in [1, 2, 3]:
        assert clear(got[i]["box"], box)
        assert 0 <= got[i]["box"][0] < got[i]["box"][2] <= 1+1e-6
        assert 0 <= got[i]["box"][1] < got[i]["box"][3] <= 1+1e-6
    assert got[0] == plain[0] and got[4:] == plain[4:]
    assert crops(value, times[::-1]) == got[::-1]


def test_shifting_clears_a_panel_without_extra_zoom():
    box = [0, .05, .47, .8]
    value = data(src=(1280, 720), cam={"cx": .65, "cy": .3, "fh": .26},
                 overlays=[{"from": 1, "to": 3, "box": box}])
    got = crops(value, [1])[0]
    plain = crops({**value, "overlays": []}, [1])[0]
    assert got["s"] == pytest.approx(plain["s"])
    assert clear(got["box"], box)


@pytest.mark.parametrize("mode", ["face", "wide"])
def test_overlay_can_zoom_past_sharpness_cap_up_to_2_2(mode):
    box = [0, 0, .59, 1]
    value = data(layout="split", src=(1280, 720), cam={"mode": mode, "cx": .73, "cy": .3, "fh": .15},
                 overlays=[{"from": 1, "to": 3, "box": box}])
    got = crops(value, [1, 1.1, 2.9])
    for r in got:
        assert 1.6 < r["s"] <= 2.2
        assert clear(r["box"], box)
    assert got[0] == got[1] == got[2]


def test_impossible_clearance_leaves_the_crop_alone():
    value = data(layout="split", src=(1280, 720), cam={"cx": .8},
                 overlays=[{"from": 1, "to": 3, "box": [0, 0, .7, 1]}])
    assert crops(value, [1, 2]) == crops({**value, "overlays": []}, [1, 2])


@pytest.mark.parametrize("mode", ["face", "wide"])
@pytest.mark.parametrize("end", [.8, 3])
def test_quote_lean_does_not_drift_through_an_overlay(mode, end):
    value = data(src=(1280, 720), cam={"mode": mode, "cx": .65, "cy": .3, "fh": .26},
                 theme={"solo_fill": True}, quotes=[{"from": 0, "to": end, "a": 0, "b": 2, "marks": []}],
                 overlays=[{"from": .2, "to": 2.8, "box": [0, 0, .55, 1]}])
    got = crops(value, [.2, .5, 1, 2, 2.7])
    assert all(clear(r["box"], value["overlays"][0]["box"]) for r in got)
    assert all(r == got[0] for r in got)


def test_landscape_keeps_its_original_crop():
    value = data(shape="16x9", src=(1280, 720), overlays=[{"from": 0, "to": 4, "box": [0, .05, .47, .8]}])
    assert crops(value, [0, 2]) == crops({**value, "overlays": []}, [0, 2])


def test_captions_avoid_faces_during_an_overlay_inside_the_group():
    value = data(layout="split", src=(1280, 720), cam={"cx": .73, "cy": .2, "fh": .25},
                 theme={"cap_y": .62}, overlays=[{"from": .4, "to": .8, "box": [0, 0, .59, 1]}])
    states = frames(value, [.1, .5, .9, 1.3])
    assert len({s["cy"] for s in states}) == 1
    assert all(not intersects(s["caption"], s["face"]) for s in states)


def test_scene_data_passes_overlay_windows_to_the_page(tmp_path, zing_workspace):
    overlays = [{"from": .6, "to": 2.4, "box": [0, .05, .47, .8]}]
    (tmp_path / "plan.json").write_text(json.dumps({"hook": "A guest", "shots": [{"from": 0, "layout": "solo"}],
                                                  "visuals": {}}), encoding="utf-8")
    (tmp_path / "words.json").write_text(json.dumps({"duration": 4, "words": data()["words"]}), encoding="utf-8")
    (tmp_path / "cams.json").write_text(json.dumps({"cams": data()["cams"], "size": [1280, 720], "frames": 120,
                                                  "overlays": overlays}), encoding="utf-8")
    got = render.scene_data(tmp_path, "9x16", "zing", parallax=False, front=False, sharpen=False)
    assert got.get("overlays") == overlays
