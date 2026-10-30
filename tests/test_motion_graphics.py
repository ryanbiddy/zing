"""Motion-graphics templates: v2 contract, sidecar plan, fit checks and renders."""
from __future__ import annotations

import copy
import hashlib
import os
import re
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from myzing.composition import (
    AssetRef, Composition, CompositionClip, CompositionGraphic, FontAsset, GraphicStyle,
    load_composition, lower_to_v1,
)
from myzing.layout.delivery import adapt_plan
from myzing.layout.types import Box
from myzing.project.models import Rational
from myzing.render import hyperframes_adapter as hf, render_composition
from myzing.render.deliveries import input_paths
from myzing.render.hyperframes_cache import overlay_key
from myzing.render.hyperframes_v2 import captions_to_plan

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.eval.render_hyperframes_fixture import fixture, run

FONT = Path(__file__).resolve().parents[1] / "src/myzing/_data/fonts/Anton-Regular.ttf"
ANTON = FontAsset(str(FONT), hashlib.sha256(FONT.read_bytes()).hexdigest(), "OFL-1.1")
TEMPLATES = ["title-card", "lower-third", "callout", "progress-bar"]


def graphics(end=3.0):
    return [
        CompositionGraphic(id="title", template="title-card", start=0, end=1.5, box=Box(.05, .1, .9, .4),
                           text=["BIG IDEA", "small print"], font=ANTON, style=GraphicStyle(48)),
        CompositionGraphic(id="name", template="lower-third", start=.5, end=2.3, box=Box(.05, .7, .7, .25),
                           text=["Ada Lovelace"], font=ANTON, style=GraphicStyle(28)),
        CompositionGraphic(id="wait", template="callout", start=1, end=2, box=Box(.55, .05, .4, .25),
                           text=["WAIT"], font=ANTON, style=GraphicStyle(28, "#111111", "#FFD400")),
        CompositionGraphic(id="progress", template="progress-bar", start=0, end=end, box=Box(0, .95, 1, .05),
                           style=GraphicStyle()),
    ]


def composition(**changes):
    c = Composition(assets=[AssetRef("a", "clip.mp4", None)],
                    clips=[CompositionClip("clip.mp4", 0, 3, 0, id="c", asset_id="a")],
                    graphics=graphics(), width=640, height=360)
    return replace(c, **changes)


def plan_for(items, duration=3):
    return captions_to_plan([], width=640, height=360, fps=Rational(30, 1), duration=duration, graphics=items)


def test_graphics_round_trip_and_an_empty_list_keeps_the_old_spelling():
    data = composition().to_dict()
    assert load_composition(data).to_dict() == data
    assert [g["template"] for g in data["graphics"]] == TEMPLATES
    assert data["graphics"][3]["text"] == [] and data["graphics"][3]["font"] is None
    assert "graphics" not in composition(graphics=[]).to_dict()


def test_graphics_block_lowering_to_v1():
    with pytest.raises(ValueError, match="blocking features: .*graphics"):
        lower_to_v1(composition())


@pytest.mark.parametrize("name, change", [
    ("callout has one line", lambda d: d["graphics"][2]["text"].append("MORE")),
    ("bar has no font", lambda d: d["graphics"][3].update(font=d["graphics"][0]["font"])),
    ("bar has no size", lambda d: d["graphics"][3]["style"].update(size=10)),
    ("text needs a font", lambda d: d["graphics"][0].update(font=None)),
    ("text needs a size", lambda d: d["graphics"][0]["style"].update(size=None)),
    ("blank line", lambda d: d["graphics"][1].update(text=["  "])),
    ("control character", lambda d: d["graphics"][1].update(text=["a\tb"])),
    ("long line", lambda d: d["graphics"][1].update(text=["x" * 121])),
    ("unmeasurable font", lambda d: d["graphics"][0]["font"].update(path="face.woff2")),
    ("accent color", lambda d: d["graphics"][0]["style"].update(accent="red")),
    ("unknown template", lambda d: d["graphics"][0].update(template="starburst")),
    ("unknown field", lambda d: d["graphics"][0].update(easing="bounce")),
    ("past the cut", lambda d: d["graphics"][3].update(end=3.5)),
    ("empty interval", lambda d: d["graphics"][0].update(end=0)),
    ("duplicate id", lambda d: d["graphics"][1].update(id="title")),
    ("outside the frame", lambda d: d["graphics"][0]["box"].update(x=.5)),
])
def test_invalid_graphics_fail_to_load(name, change):
    data = composition().to_dict()
    change(data)
    with pytest.raises(ValueError):
        load_composition(data)


def test_plan_carries_graphics_with_resolved_fonts_and_no_font_for_a_bar():
    data = plan_for(graphics()).to_dict()
    assert [g["template"] for g in data["graphics"]] == TEMPLATES
    title, bar = data["graphics"][0], data["graphics"][3]
    assert title["style"] == {"font": str(FONT), "font_sha256": ANTON.sha256, "size": 48,
                              "color": "#FFFFFF", "accent": "#FF3D00"}
    assert title["box"] == {"x": .05, "y": .1, "width": .9, "height": .4}
    assert title["text"] == ["BIG IDEA", "small print"]
    assert bar == {"start": 0, "end": 3.0, "template": "progress-bar", "box": {"x": 0, "y": .95, "width": 1, "height": .05},
                   "text": [], "style": {"color": "#FFFFFF", "accent": "#FF3D00"}}
    assert "graphics" not in plan_for([]).to_dict()  # Caption-only plans are unchanged.


@pytest.mark.parametrize("index", [0, 1, 2])
def test_text_that_overflows_its_box_fails_and_names_a_size_that_fits(index):
    item = graphics()[index]
    huge = replace(item, style=replace(item.style, size=300))
    with pytest.raises(hf.HyperframesError, match=rf"Graphic {item.id}: .* set style.size to \d+ or less") as caught:
        plan_for([huge])
    largest = int(re.search(r"style.size to (\d+)", str(caught.value)).group(1))
    assert 0 < largest < 300
    plan_for([replace(item, style=replace(item.style, size=largest))])


def test_a_box_too_small_for_any_size_says_so():
    with pytest.raises(hf.HyperframesError, match="enlarge the box; no text size fits it"):
        plan_for([replace(graphics()[2], box=Box(.5, .5, .001, .001))])


def test_missing_glyphs_fail_before_rendering():
    with pytest.raises(hf.HyperframesError, match="no glyph"):
        plan_for([replace(graphics()[2], text=["日本"])])


@pytest.mark.parametrize("name, change", [
    ("unknown template", lambda g: g.update(template="starburst")),
    ("unknown field", lambda g: g.update(easing="bounce")),
    ("too many lines", lambda g: g["text"].append("MORE")),
    ("text is not a list", lambda g: g.update(text="WAIT")),
    ("no font", lambda g: g["style"].pop("font")),
    ("WOFF font", lambda g: g["style"].update(font="face.woff2")),
    ("size", lambda g: g["style"].update(size=0)),
    ("accent injection", lambda g: g["style"].update(accent="red;background:url(https://example.com)")),
    ("box", lambda g: g["box"].update(x=.9)),
    ("interval", lambda g: g.update(end=g["start"])),
    ("past duration", lambda g: g.update(end=4)),
])
def test_adapter_refuses_what_the_sidecar_refuses(name, change):
    data = plan_for(graphics()).to_dict()
    change(data["graphics"][2])
    with pytest.raises(hf.HyperframesError):
        hf.validate_plan(data)


def test_adapter_refuses_font_fields_on_a_textless_bar():
    data = plan_for(graphics()).to_dict()
    data["graphics"][3]["style"]["size"] = 10
    with pytest.raises(hf.HyperframesError, match="has no text"):
        hf.validate_plan(data)


def test_overlay_key_covers_graphics_and_needs_no_font_for_a_bar():
    keys = {overlay_key(plan_for(items)) for items in ([], graphics()[3:], graphics())}
    assert len(keys) == 3
    moved = graphics()
    moved[0] = replace(moved[0], box=Box(.05, .2, .9, .4))
    assert overlay_key(plan_for(moved)) != overlay_key(plan_for(graphics()))


def test_delivery_inputs_include_graphic_fonts(tmp_path):
    (tmp_path / "clip.mp4").write_bytes(b"clip")
    assert FONT in input_paths(composition(), tmp_path)


def test_delivery_shapes_scale_graphic_text_with_the_short_side():
    adapted = adapt_plan(composition(), 540, 960, {"a": (640, 360)}, {"a": []})
    assert [g.style.size for g in adapted.graphics] == [72, 42, 42, None]
    assert [g.box for g in adapted.graphics] == [g.box for g in graphics()]


@pytest.fixture
def seam(monkeypatch):
    calls = []
    monkeypatch.setattr(hf, "check_install", lambda **kw: {})

    def render(plan, output, **kwargs):
        calls.append(copy.deepcopy(plan))
        p = plan.to_dict()
        frames = round(p["duration"] * hf.plan_rate(p["fps"]))
        run(["-f", "lavfi", "-i", f"color=c=black@0.0:s={p['width']}x{p['height']}:r={p['fps']},format=rgba",
             "-frames:v", frames, "-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p10le", output])
    monkeypatch.setattr(hf, "render_hyperframes", render)
    return calls


def small_fixture(directory):
    """The 320x180, 2.4 s render fixture with only its ASS caption and half-size graphics."""
    c = fixture(directory, width=320, height=180)
    c.captions = [event for event in c.captions if event.backend == "ass"]
    c.graphics = [replace(g, style=replace(g.style, size=g.style.size and g.style.size / 2))
                  for g in graphics(end=72 / 30)]
    return c


@pytest.mark.ffmpeg
def test_graphics_alone_route_through_one_overlay(tmp_path, seam):
    c = small_fixture(tmp_path / "assets")
    render_composition(c, tmp_path / "out.mp4", work_dir=tmp_path / "work")
    assert len(seam) == 1
    plan = seam[0].to_dict()
    assert plan["captions"] == [] and [g["template"] for g in plan["graphics"]] == TEMPLATES


@pytest.mark.skipif(os.environ.get("ZING_REQUIRE_HYPERFRAMES") != "1",
                    reason="set ZING_REQUIRE_HYPERFRAMES=1 for a real graphics render")
def test_real_graphics_render_seeks_each_frame(tmp_path):
    np = pytest.importorskip("numpy")
    c = small_fixture(tmp_path / "assets")
    render_composition(c, tmp_path / "out.mp4", work_dir=tmp_path / "work")
    overlay = next((tmp_path / "work/hyperframes-overlays").glob("*.mov"))
    raw = run(["-i", overlay, "-f", "rawvideo", "-pix_fmt", "rgba", "pipe:1"])
    rgba = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 180, 320, 4).astype(float)
    assert len(rgba) == 72
    bar = rgba[36, 172:180]  # Halfway: the fill covers the left half of the track.
    assert np.median(bar[:, 40:120, 3]) > 240 and np.median(bar[:, 40:120, 0]) > 200
    assert 50 < np.median(bar[:, 200:280, 3]) < 110  # The 30% white track.
    title = rgba[:, 18:90, 16:160, 3]  # Left of the callout box.
    assert title[20].max() > 200  # Held between its entrance and exit.
    assert not title[46:].any()  # Gone after 1.5 s.
