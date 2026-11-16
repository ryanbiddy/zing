"""Licensed image props use generated drawings and local image tools only."""
from __future__ import annotations

import json
import shutil
import struct
from pathlib import Path

import pytest

from myzing.story import StoryError, heads, images, receipt
from myzing.story.contract import check
from myzing.story.outro import credit_lines, prepare
from test_factory_brand_kit import browser_tools
from test_story_contract import story, timings
from test_story_heads import draw_photo, read_png_rgba
from test_story_render import node_page_script, story_folder


@pytest.fixture
def picture(tmp_path):
    draw_photo(tmp_path / "drawing.ppm")
    return {"path": "drawing.ppm", "credit": "Test drawing", "license": "CC0 1.0",
            "source_url": "https://example.org/test-drawing"}


@pytest.mark.parametrize("license", ["CC BY-NC 4.0", "CC BY-ND 4.0", "CC BY-NC-SA 4.0",
                                     "Attribution No Derivatives", "All rights reserved", "unknown"])
def test_image_rights_refusals_happen_before_image_tools(tmp_path, picture, license, monkeypatch):
    picture["license"] = license
    monkeypatch.setattr(images, "_photo", lambda *args: pytest.fail("conversion ran before rights check"))
    monkeypatch.setattr(heads, "_image_tools", lambda: pytest.fail("OpenCV loaded before rights check"))
    with pytest.raises(StoryError, match="NC, ND and unknown licenses are refused"):
        images.generate(tmp_path, {"images": {"drawing": picture}})
    assert not (tmp_path / "images").exists()


@pytest.mark.parametrize("missing", ["path", "credit", "license", "source_url"])
def test_image_metadata_is_required(tmp_path, picture, missing):
    picture.pop(missing)
    with pytest.raises(StoryError, match=f"image requires {missing}"):
        images.generate(tmp_path, {"images": {"drawing": picture}})


@pytest.mark.parametrize("path", ["../outside.png", "images/../../outside.png", "https://example.org/drawing.png"])
def test_image_paths_stay_inside_story(tmp_path, picture, path):
    picture["path"] = path
    with pytest.raises(StoryError, match="image path"):
        images.generate(tmp_path, {"images": {"drawing": picture}})


def test_bad_image_id_cannot_write_outside_image_folder(tmp_path, picture):
    with pytest.raises(StoryError, match="image id"):
        images.generate(tmp_path, {"images": {"../outside": picture}})


@pytest.mark.parametrize("shared", [False, True])
def test_prepared_picture_cannot_replace_an_original(tmp_path, picture, shared, monkeypatch):
    (tmp_path / "images").mkdir()
    source = tmp_path / "images/drawing-photo.png"
    source.write_bytes(b"original picture")
    original = {**picture, "path": "images/drawing-photo.png"}
    definitions = {"drawing": picture, "other": original} if shared else {"drawing": original}
    monkeypatch.setattr(images, "_photo", lambda *args: pytest.fail("original picture was overwritten"))
    with pytest.raises(StoryError, match="would replace an original picture"):
        images.generate(tmp_path, {"images": definitions})
    assert source.read_bytes() == b"original picture"


@pytest.mark.parametrize("cast_photo", [False, True])
def test_image_sheet_cannot_replace_an_original(tmp_path, picture, cast_photo, monkeypatch):
    (tmp_path / "images").mkdir()
    source = tmp_path / "images/sheet.png"
    source.write_bytes(b"original picture")
    original = {**picture, "path": "images/sheet.png"}
    value = {"images": {"drawing": picture if cast_photo else original}}
    if cast_photo:
        value["cast"] = {"ada": {"photos": [original]}}
    monkeypatch.setattr(images, "_photo", lambda *args: pytest.fail("conversion ran before the sheet path check"))
    monkeypatch.setattr(heads, "_write_sheet", lambda *args, **kwargs: pytest.fail("original picture was overwritten"))
    with pytest.raises(StoryError, match="images/sheet.png is an original picture"):
        images.generate(tmp_path, value, sheet=True)
    assert source.read_bytes() == b"original picture"


def test_photo_cut_converts_with_ffmpeg_without_opencv(tmp_path, picture, monkeypatch):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg not installed")
    monkeypatch.setattr(heads, "_image_tools", lambda: pytest.fail("photo needs no OpenCV"))
    records = images.generate(tmp_path, {"images": {"drawing": picture}})
    output = tmp_path / "images/drawing-photo.png"
    data = output.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack_from(">II", data, 16) == (300, 320)
    assert records == [{"image_id": "drawing", **picture, "image": "images/drawing-photo.png",
                        "cut": "photo", "rights": "cleared"}]
    assert not list((tmp_path / "images").glob("*.tmp"))


def test_sticker_without_opencv_uses_head_install_message(tmp_path, picture, monkeypatch):
    picture["cut"] = "sticker"

    def missing(name):
        raise ImportError(name)

    monkeypatch.setattr(heads.importlib, "import_module", missing)
    with pytest.raises(StoryError, match="Head cutouts need OpenCV and NumPy. Install 'myzing\\[factory\\]'"):
        images.generate(tmp_path, {"images": {"drawing": picture}})


@pytest.mark.parametrize("box", [None, [70, 45, 160, 200]])
def test_sticker_has_transparent_corners_and_the_head_paper_edge(tmp_path, picture, box):
    pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    picture["cut"] = "sticker"
    if box is not None:
        picture["box"] = box
    records = images.generate(tmp_path, {"images": {"drawing": picture}})
    width, height, rows = read_png_rgba(tmp_path / "images/drawing-sticker.png")
    assert rows[0][3] == rows[0][-1] == rows[-1][3] == rows[-1][-1] == 0
    assert rows[height // 2][(width // 2) * 4 + 3] == 255
    assert any(tuple(row[x:x + 4]) == (250, 250, 250, 255)
               for row in rows for x in range(0, len(row), 4))
    assert records[0]["cut"] == "sticker"
    assert max(width, height) > heads.HEAD_SIZE


@pytest.mark.parametrize("box", [[1, 2, 3], [-1, 2, 3, 4], [1, 2, 0, 4], [1, 2, True, 4], [1, 2, float("nan"), 4]])
def test_invalid_sticker_box_is_rejected_before_opencv(tmp_path, picture, box, monkeypatch):
    picture.update(cut="sticker", box=box)
    monkeypatch.setattr(heads, "_image_tools", lambda: pytest.fail("invalid box reached OpenCV"))
    with pytest.raises(StoryError, match="image box"):
        images.generate(tmp_path, {"images": {"drawing": picture}})


def test_sticker_box_must_fit_picture(tmp_path, picture):
    pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    picture.update(cut="sticker", box=[200, 200, 200, 200])
    with pytest.raises(StoryError, match="must fit inside"):
        images.generate(tmp_path, {"images": {"drawing": picture}})


def test_image_sheet_labels_each_picture(tmp_path, picture, monkeypatch):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg not installed")
    from PIL import Image, ImageDraw

    labels = []
    draw_text = ImageDraw.ImageDraw.text

    def record_text(self, xy, text, *args, **kwargs):
        labels.append(text)
        return draw_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", record_text)
    images.generate(tmp_path, {"images": {"first": picture, "second": picture}}, sheet=True)
    with Image.open(tmp_path / "images/sheet.png") as sheet:
        assert sheet.size == (560, 340)
    assert labels == ["first", "second"]


def test_image_credits_deduplicate_with_photos_and_receipt_lists_images(tmp_path, picture):
    value = story()
    value["images"] = {"drawing": picture}
    assert "image: Test drawing · CC0 1.0" in credit_lines(value, timings())
    value["cast"]["ada"]["photos"] = [dict(picture)]
    lines = credit_lines(value, timings())
    assert sum("Test drawing · CC0 1.0" in line for line in lines) == 1
    (tmp_path / "story.json").write_text(json.dumps(value), encoding="utf-8")
    (tmp_path / "timings.json").write_text(json.dumps(timings()), encoding="utf-8")
    output = tmp_path / "story.mp4"
    output.write_bytes(b"test video output")
    saved = json.loads(receipt.write(tmp_path, output).read_text(encoding="utf-8"))
    assert saved["images"] == [{"image_id": "drawing", **picture,
                                "image": "images/drawing-photo.png", "cut": "photo"}]
    prepared = prepare(value, timings())
    assert prepared["images"]["drawing"]["prepared"] == "images/drawing-photo.png"
    assert "prepared" not in value["images"]["drawing"]


def test_image_prop_requires_a_known_image(tmp_path, picture):
    value = story()
    value["images"] = {"drawing": picture}
    prop = {"prop": "image", "image": "drawing", "x": 800, "y": 1450, "w": 300,
            "at": "hook", "until": "turn", "anim": "drop", "scale": .8, "rot": -5, "front": True}
    value["panels"][0]["props"].append(prop)
    assert check(value, tmp_path) == []
    prop["image"] = "missing"
    assert any("panels[0].props[1].image" in error and "missing" in error for error in check(value, tmp_path))


def test_page_image_prop_keeps_photo_border_and_tape_or_sticker_edge(tmp_path):
    result = node_page_script("""
const image={drawing:{url:'file:///drawing.png',w:300,h:320,cut:'photo'}};
const photo=PROPS.image({image:'drawing',w:300},image);
image.drawing.cut='sticker';
const sticker=PROPS.image({image:'drawing',w:300},image);
global.document={createElementNS(){return {attrs:{},children:[],setAttribute(k,v){this.attrs[k]=v;},appendChild(c){this.children.push(c);}}}};
const layer={children:[],appendChild(c){this.children.push(c);}};
const prop=Prop({prop:'image',image:'drawing',w:300,x:800,y:1400,t:2,until:4,scale:.8,rot:-5,still:true},layer,1,image);
prop.update(1);const before=layer.children[0].attrs.visibility;
prop.update(3);const showing={...layer.children[0].attrs};
prop.update(4);const after=layer.children[0].attrs.visibility;
console.log(JSON.stringify({photo,sticker,before,showing,after}));
""", tmp_path)
    assert 'fill="#fff"' in result["photo"] and 'opacity=".8"' in result["photo"]
    assert result["sticker"].count("<image ") == 1 and "<rect " not in result["sticker"]
    assert result["before"] == result["after"] == "hidden"
    assert result["showing"] == {"visibility": "visible", "transform": "translate(800,1400) rotate(-5) scale(0.8)"}


def test_empty_images_need_no_image_tools(tmp_path, monkeypatch):
    monkeypatch.setattr(images, "_photo", lambda *args: pytest.fail("empty images used FFmpeg"))
    monkeypatch.setattr(heads, "_image_tools", lambda: pytest.fail("empty images used OpenCV"))
    assert images.generate(tmp_path, {}) == []


def test_render_missing_prepared_picture_requests_images_step(tmp_path, picture, monkeypatch):
    from myzing.story import render

    directory = story_folder(tmp_path)
    value = json.loads((directory / "story.json").read_text(encoding="utf-8"))
    value["images"] = {"drawing": picture}
    (directory / "story.json").write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(render, "capture", lambda *args: pytest.fail("capture ran without a prepared picture"))
    with pytest.raises(StoryError, match="Prepared image drawing is missing. Run 'zing story images' first"):
        render.render(directory, stills=[.3])


def test_render_prepared_picture_cannot_resolve_outside_story(tmp_path, picture, monkeypatch):
    from myzing.story import render

    directory = story_folder(tmp_path)
    value = json.loads((directory / "story.json").read_text(encoding="utf-8"))
    value["images"] = {"drawing": picture}
    (directory / "story.json").write_text(json.dumps(value), encoding="utf-8")
    prepared = directory / "images/drawing-photo.png"
    outside = directory.parent / "outside.png"
    real_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        return outside if path == prepared else real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    monkeypatch.setattr(render, "capture", lambda *args: pytest.fail("capture read a picture outside the story"))
    with pytest.raises(StoryError, match="image drawing: image path must stay inside the story folder"):
        render.render(directory, stills=[.3])


def test_real_photo_prop_loads_in_the_offline_page(tmp_path, picture, browser_tools):
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg not installed")
    from myzing.story.render import render

    directory = story_folder(tmp_path)
    value = json.loads((directory / "story.json").read_text(encoding="utf-8"))
    value["images"] = {"drawing": picture}
    value["panels"][0]["props"].append({"prop": "image", "image": "drawing", "w": 300,
                                        "x": 800, "y": 1450, "front": True, "rot": -4, "at": 0})
    (directory / "story.json").write_text(json.dumps(value), encoding="utf-8")
    timed = json.loads((directory / "timings.json").read_text(encoding="utf-8"))
    timed.update(outro_start=1.4, duration=2.4)
    (directory / "timings.json").write_text(json.dumps(timed), encoding="utf-8")
    images.generate(directory, value)
    output = render(directory, stills=[.7])
    assert output[0].read_bytes().startswith(b"\xff\xd8")
