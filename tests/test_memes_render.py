"""Structural goldens use pixel regions, not platform-dependent font hashes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

Image = pytest.importorskip("PIL.Image", reason="install myzing[memes] for render tests")
from PIL import ImageChops, ImageFont

from myzing import cli, mcp_server, storage
from myzing.memes import MemeError
from myzing.memes.render import (FONTS_DIR, Rect, TextLayer, draw_composition,
                                 render_meme, resolve_font, wrap_text)


@pytest.fixture
def photo(tmp_path, monkeypatch):
    monkeypatch.setattr("myzing.memes.templates.build_opener", lambda *a: pytest.fail("local photo used network"))
    path = tmp_path / "photo.png"
    Image.new("RGB", (640, 480), (63, 97, 122)).save(path)
    return path


@pytest.mark.parametrize("aspect,size", [("16:9", (1200, 675)), ("1:1", (1080, 1080)),
                                        ("4:5", (1080, 1350)), ("9:16", (1080, 1920))])
@pytest.mark.parametrize("layout", ["classic", "caption", "labels"])
def test_render_structural_goldens(photo, tmp_path, aspect, size, layout):
    result = render_meme(["one quick fix", "six hours later"], image=str(photo), layout=layout,
                         aspect=aspect, out=str(tmp_path / f"{layout}.png"))
    with Image.open(result["path"]) as image:
        assert image.size == size
        assert image.mode == "RGB"
        assert len(result["boxes"]) == 2
        for report in result["boxes"]:
            x0, y0, x1, y1 = report["box"]
            ink = report["text_bbox"]
            assert x0 <= ink[0] < ink[2] <= x1
            assert y0 <= ink[1] < ink[3] <= y1
            crop = image.crop(tuple(ink))
            colors = crop.getcolors(crop.width * crop.height)
            if layout == "caption":
                assert sum(n for n, p in colors if max(p) < 100) > 100
                assert ink[3] < size[1] * .26
            else:
                assert sum(n for n, p in colors if min(p) > 200) > 100
        # Text stays in its assigned bands; the central photo remains intact.
        if layout in ("classic", "caption"):
            assert image.getpixel((size[0] // 2, size[1] // 2)) == (63, 97, 122)


def test_plates_shadow_rotation_and_multiline(photo, tmp_path):
    result = render_meme(["first line\nsecond line", "payoff"], image=str(photo), layout="labels",
                         regions=[[.05, .05, .4, .4], [.55, .55, .4, .4]],
                         plate=True, shadow=True, rotation=14, out=str(tmp_path / "effects.webp"))
    assert len(result["boxes"][0]["wrapped_lines"]) >= 2
    with Image.open(result["path"]) as image:
        assert image.format == "WEBP"
        assert len(image.crop(tuple(result["boxes"][0]["box"])).getcolors(10_000_000)) > 20


def test_text_wrap_never_discards_long_words():
    font = ImageFont.truetype(str(FONTS_DIR / "Anton-Regular.ttf"), 40)
    text = "a" * 70
    lines = wrap_text(text, font, 100)
    assert "".join(lines) == text
    assert all(font.getlength(line) <= 100 for line in lines)
    assert wrap_text("one\n\ntwo", font, 500) == ["one", "", "two"]


def test_max_budget_text_fits(photo, tmp_path):
    result = render_meme(["W" * 70, "Z" * 40], image=str(photo), out=str(tmp_path / "budget.png"))
    assert "".join(result["boxes"][0]["wrapped_lines"]) == "W" * 70
    for box in result["boxes"]:
        assert box["font_size"] >= 10


def test_normal_words_shrink_before_splitting(photo, tmp_path):
    result = render_meme(["emergency power"], image=str(photo), layout="labels",
                         regions=[[.025, .55, .23, .14]], out=str(tmp_path / "words.png"))
    assert result["boxes"][0]["wrapped_lines"] == ["emergency", "power"]


def test_low_level_layer_alignment_and_effects_change_pixels():
    source = Image.new("RGB", (640, 480), "#537183")
    box = Rect(40, 40, 400, 200)
    plain, _ = draw_composition(source, size=(640, 480), layers=[TextLayer("caption", box)])
    fancy, reports = draw_composition(source, size=(640, 480), layers=[
        TextLayer("caption", box, align="left", background="#202020", shadow=True, rotation=-12)])
    assert ImageChops.difference(plain, fancy).getbbox()
    assert reports[0]["text_bbox"]


def test_contain_preserves_source_and_maps_regions(photo, tmp_path):
    result = render_meme(["label"], image=str(photo), layout="labels", fit="contain",
                         regions=[[0, 0, 1, .3]], out=str(tmp_path / "contain.png"))
    # 640x480 in 1080 square: photo y=135..945.
    assert result["boxes"][0]["box"] == [0, 135, 1080, 378]
    with Image.open(result["path"]) as image:
        assert image.getpixel((540, 20)) == (24, 24, 24)
        assert image.getpixel((540, 540)) == (63, 97, 122)


def test_template_uses_cached_blank_and_catalog_regions(tmp_path, zing_workspace, monkeypatch):
    monkeypatch.setattr("myzing.memes.templates.build_opener", lambda *a: pytest.fail("cached template used network"))
    blank = storage.workspace_root() / "memes/templates/drake.jpg"
    blank.parent.mkdir(parents=True)
    Image.new("RGB", (600, 600), "#847261").save(blank)
    result = render_meme(["reject", "prefer"], template="drake", offline=True, out=str(tmp_path / "drake.png"))
    assert result["layout"] == "labels" and result["fit"] == "contain"
    assert all(r["box"][0] > 540 for r in result["boxes"])


def test_empty_slots_do_not_shift_text(photo, tmp_path):
    result = render_meme(["", "bottom"], image=str(photo), out=str(tmp_path / "bottom.png"))
    assert len(result["boxes"]) == 1 and result["boxes"][0]["index"] == 1
    assert result["boxes"][0]["text_bbox"][1] > 540


def test_exif_orientation_and_jpeg_export(tmp_path):
    source = tmp_path / "oriented.jpg"
    image = Image.new("RGB", (800, 400), "#537183")
    exif = Image.Exif()
    exif[274] = 6
    image.save(source, exif=exif)
    result = render_meme(["upright"], image=str(source), aspect="original", out=str(tmp_path / "done.jpg"))
    assert (result["width"], result["height"]) == (1200, 2400)
    with Image.open(result["path"]) as image:
        assert image.format == "JPEG"


@pytest.mark.parametrize("options", [dict(aspect="bad"), dict(fit="bad"), dict(layout="bad"),
                                    dict(rotation=float("nan")), dict(font="missing-font"),
                                    dict(regions=[[0, 0, 1, 1]]), dict(out="bad.gif")])
def test_invalid_render_options_are_data(photo, options):
    result = mcp_server.h_meme_render(["hello"], image=str(photo), **options)
    assert result["ok"] is False
    assert result["error"]


def test_missing_corrupt_and_inplace_input_errors(photo, tmp_path):
    for image in (tmp_path / "missing.png", tmp_path / "corrupt.png"):
        if image.stem == "corrupt":
            image.write_bytes(b"not a photo")
        result = mcp_server.h_meme_render(["hello"], image=str(image))
        assert not result["ok"] and "Could not render" in result["error"]
    original = photo.read_bytes()
    with pytest.raises(MemeError, match="differ"):
        render_meme(["hello"], image=str(photo), out=str(photo))
    assert photo.read_bytes() == original


def test_cli_and_mcp_return_paths_never_image_bytes(photo, tmp_path, zing_workspace, capsys):
    assert cli.main(["meme", "render", "--image", str(photo), "--text", "hello", "--json"]) == 0
    cli_result = json.loads(capsys.readouterr().out)
    result = mcp_server.h_meme_render(["hello"], image=str(photo))
    assert result["ok"] and Path(result["path"]).is_file()
    assert Path(result["path"]).is_relative_to(storage.workspace_root())
    assert result["path"] != cli_result["path"]
    assert "base64" not in json.dumps(result)
    assert not list(Path(result["path"]).parent.glob("*.tmp"))


def test_system_font_path_and_missing_font(photo, tmp_path):
    path = str(FONTS_DIR / "IBMPlexSans.ttf")
    assert Path(resolve_font(path)).is_file()
    result = render_meme(["hello"], image=str(photo), font=path, out=str(tmp_path / "font.png"))
    assert Path(result["path"]).is_file()


def test_render_refuses_to_overwrite_existing_output(photo, tmp_path):
    out = tmp_path / "keep.png"
    Image.new("RGB", (8, 8), (1, 2, 3)).save(out)
    before = out.read_bytes()
    with pytest.raises(MemeError, match="already exists"):
        render_meme(["top", "bottom"], image=str(photo), out=str(out))
    assert out.read_bytes() == before
    result = render_meme(["top", "bottom"], image=str(photo), out=str(out), overwrite=True)
    with Image.open(result["path"]) as image:
        assert image.size == (1080, 1080)
