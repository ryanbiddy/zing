"""Footage grading stays below captions, pictures and brand assets."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from myzing.factory import color, export, judge, render
from test_factory_brand_kit import kit
from test_factory_caption_faces import data, scene


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)


@pytest.fixture
def clip(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    directory = tmp_path / "episode" / "clip01"
    directory.mkdir(parents=True)
    picture = directory / "source card.png"
    Image.new("RGB", (640, 360), (240, 190, 30)).save(picture)
    (directory / "frames").mkdir()
    Image.new("RGB", (640, 360), (100, 120, 140)).save(directory / "frames" / "00001.jpg")
    values = {
        "plan": {"hook": "A *real* point", "hook_until": 0,
                 "shots": [{"from": 0, "layout": "solo"},
                           {"from": 3, "layout": "split", "visual": "v1"}],
                 "visuals": {"v1": {"path": str(picture), "fit": "contain", "credit": "Local test"}}},
        "words": {"words": [{"w": word, "os": i * .8, "oe": i * .8 + .6}
                            for i, word in enumerate("We keep the original words.".split())]},
        "cams": {"frames": 1, "size": [640, 360],
                 "cams": [{"from": 0, "to": 5, "mode": "wide"}]},
    }
    for name, value in values.items():
        (directory / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
    (directory / "cut.mp4").write_bytes(b"media is not decoded in scene assembly")
    return directory


@pytest.fixture
def prepared(monkeypatch, clip):
    calls = []

    def prepare(directory, settings):
        normalized = color.normalize(settings)
        active = normalized["color_look"] != "source"
        calls.append(normalized)
        folder = directory / ("color-preview" if active else "frames")
        return {"frames_dir": str(folder.resolve()),
                "color": {"settings": normalized, "active": active,
                          "warnings": ["SDR is assumed for this untagged test source."] if active else []}}

    monkeypatch.setattr(color, "prepare", prepare)
    return calls


def assemble(clip, shape="9x16", pack="desk", **settings):
    return render.scene_data(clip, shape, pack, parallax=False, front=False, sharpen=False, **settings)


@pytest.mark.parametrize("shape", render.SHAPES)
@pytest.mark.parametrize("pack", ["desk", "editorial", "newsroom", "pop"])
def test_color_changes_only_the_footage_input_in_every_delivery(clip, prepared, shape, pack):
    files = [p for p in clip.rglob("*") if p.is_file()]
    before_files = {p: p.read_bytes() for p in files}
    original = assemble(clip, shape, pack)
    graded = assemble(clip, shape, pack, color_look="cinematic-cool", color_strength=.65)

    assert original["framesDir"] == (clip / "frames").as_uri()
    assert graded["framesDir"] == (clip / "color-preview").as_uri()
    assert graded["color"]["settings"]["color_strength"] == .65
    assert graded["color"]["warnings"]
    assert {k: v for k, v in graded.items() if k not in ("color", "framesDir")} == {
        k: v for k, v in original.items() if k not in ("color", "framesDir")}
    assert all(p.read_bytes() == contents for p, contents in before_files.items())


def test_explicit_controls_override_only_the_selected_project_settings(clip, prepared):
    saved = {"color_look": "cinematic-cool", "color_strength": .7, "color_exposure": .2,
             "color_temperature": -.04, "color_tint": .03, "pack": "desk"}
    config = clip.parent / "factory.json"
    config.write_text(json.dumps(saved), encoding="utf-8")
    before = config.read_bytes()

    inherited = assemble(clip)
    overridden = assemble(clip, color_strength=0, color_exposure=0)
    source = assemble(clip, color_look="source")

    assert inherited["color"]["settings"] == color.normalize(saved)
    assert overridden["color"]["settings"] == {
        **color.normalize(saved), "color_strength": 0, "color_exposure": 0}
    assert source["color"]["settings"]["color_look"] == "source"
    assert source["framesDir"] == (clip / "frames").as_uri()
    assert config.read_bytes() == before


def test_color_does_not_rewrite_a_branded_pack_or_its_assets(clip, prepared):
    folder = kit(cap_color="#FA1450", cap_upper=False)
    before_files = {p: p.read_bytes() for p in folder.iterdir() if p.is_file()}
    original = assemble(clip, pack="acme")
    graded = assemble(clip, pack="acme", color_look="cinematic-cool")

    for key in ("theme", "logo", "fonts", "words", "visuals", "hookHtml"):
        assert graded[key] == original[key]
    assert all(p.read_bytes() == contents for p, contents in before_files.items())


@pytest.mark.parametrize("strength", [0, .5, 1])
def test_explicit_look_replaces_speaker_css_grade_but_keeps_picture_grade_and_blur(strength):
    value = data(layout="split", theme={"grade": "sepia(.8)", "transition": "blur"},
                 shots=[{"from": 0, "to": 1, "idx": 0, "layout": "solo"},
                        {"from": 1, "to": 4, "idx": 1, "layout": "split", "visual": "v1"}])
    code = """
      await window.seek(1.1);
      console.log(JSON.stringify({speaker:$('spk').style.filter,picture:$('top').style.filter,
        caption:$('cap').innerHTML,graphic:$('gfx').style.filter}));
    """
    original = scene(value, code)
    value["color"] = {"active": strength > 0,
                      "settings": {"color_look": "cinematic-cool", "color_strength": strength}}
    graded = scene(value, code)

    assert "sepia(.8)" in original["speaker"]
    assert "sepia" not in graded["speaker"]
    assert "blur(" in graded["speaker"]
    assert graded["picture"] == original["picture"]
    assert "sepia(.8)" in graded["picture"]
    assert graded["caption"] == original["caption"]
    assert graded["graphic"] == original["graphic"]


def test_source_color_keeps_the_legacy_pack_filter():
    value = data(theme={"grade": "sepia(.8)"},
                 color={"active": False, "settings": {"color_look": "source", "color_strength": .5}})
    got = scene(value, "await window.seek(.5); console.log(JSON.stringify($('spk').style.filter));")
    assert got == "sepia(.8)"


def test_layered_export_uses_the_same_saved_grade_for_all_capture_passes(clip, prepared, monkeypatch, tmp_path):
    (clip.parent / "factory.json").write_text(
        json.dumps({"color_look": "cinematic-cool", "color_strength": .65,
                    "parallax": False, "cutout": False, "upscale": False}), encoding="utf-8")
    passes = []

    def capture(value, file, images, **kwargs):
        passes.append((kwargs.get("layer", "reference"), value))
        images.mkdir()
        if "samples" in kwargs:
            (images / "captions.json").write_text("[]", encoding="utf-8")

    def encode(*argv, **kwargs):
        Path(argv[-1]).write_bytes(b"test output")

    monkeypatch.setattr(render, "capture", capture)
    monkeypatch.setattr(export, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(export, "run", encode)
    monkeypatch.setattr(export, "compare", lambda *args: [])
    result = export.export(clip, out=tmp_path / "layers")

    assert [layer for layer, _ in passes] == ["speaker", "overlay", "reference"]
    assert all(value["framesDir"] == (clip / "color-preview").as_uri() for _, value in passes)
    assert all(value["color"]["settings"]["color_strength"] == .65 for _, value in passes)
    assert all(value["words"] == passes[0][1]["words"] for _, value in passes)
    assert result["bytes"]["speaker.mp4"] > 0
