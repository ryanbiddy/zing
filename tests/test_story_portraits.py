"""Portrait crops use drawn images and stay local, including without OpenCV."""
from __future__ import annotations

import importlib

import pytest
from PIL import Image, ImageDraw

from myzing.story import StoryError, heads, portraits


@pytest.fixture
def photo(tmp_path):
    image = Image.new("RGB", (300, 240), (30, 90, 110))
    ImageDraw.Draw(image).ellipse((180, 50, 298, 190), fill=(230, 170, 120))
    image.save(tmp_path / "drawing.png")
    return {"path": "drawing.png", "credit": "Test drawing", "license": "CC0",
            "source_url": "https://example.org/drawing", "face": [240, 60, 60, 100]}


def test_portrait_is_square_rgb_jpeg_without_edge_padding(tmp_path, photo):
    records = portraits.generate(tmp_path, {"cast": {"mira": {"photos": [photo]}}})
    assert records[0]["portrait"] == "heads/mira-0-portrait.jpg"
    assert "head" not in records[0]
    with Image.open(tmp_path / records[0]["portrait"]) as image:
        assert (image.format, image.mode, image.size) == ("JPEG", "RGB", (600, 600))
        assert image.convert("L").getextrema()[0] > 25
    assert not list((tmp_path / "heads").glob("*.png"))


@pytest.mark.parametrize("size,face", [
    ((300, 240), (240, 60, 60, 100)),
    ((300, 240), (0, 0, 100, 100)),
    ((70, 240), (0, 50, 70, 90)),
    ((300, 80), (70, 0, 160, 80)),
])
def test_crop_shifts_inside_then_shrinks_when_needed(size, face):
    left, top, right, bottom = portraits.crop_box(size, face)
    assert 0 <= left < right <= size[0]
    assert 0 <= top < bottom <= size[1]
    assert right - left == bottom - top == min(*size, round(face[2] * 1.9))


def test_crop_center_lifts_to_leave_room_for_hair():
    assert portraits.crop_box((600, 600), (200, 200, 100, 100)) == (155, 147, 345, 337)


def test_explicit_box_and_sheet_work_when_opencv_and_numpy_cannot_import(tmp_path, photo, monkeypatch):
    original = importlib.import_module
    attempted = []

    def no_opencv(name, *args, **kwargs):
        if name in ("cv2", "numpy"):
            attempted.append(name)
            raise ImportError(name)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", no_opencv)
    monkeypatch.setattr(heads, "cut_head", lambda *a, **kw: pytest.fail("headline tried to cut a head"))
    records = heads.generate(tmp_path, {"look": "headline", "cast": {"mira": {"photos": [photo]}}}, sheet=True)
    assert attempted == []
    assert (tmp_path / records[0]["portrait"]).is_file()
    with Image.open(tmp_path / "heads/sheet.png") as sheet:
        assert sheet.size == (280, 340)


def test_missing_opencv_without_a_face_box_uses_heads_plain_error(tmp_path, photo, monkeypatch):
    photo.pop("face")
    original = importlib.import_module

    def no_opencv(name, *args, **kwargs):
        if name == "cv2":
            raise ImportError(name)
        return original(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", no_opencv)
    with pytest.raises(StoryError, match="Head cutouts need OpenCV and NumPy"):
        portraits.generate(tmp_path, {"cast": {"mira": {"photos": [photo]}}})
    assert not (tmp_path / "heads").exists()


def test_missing_detected_face_uses_heads_plain_error(tmp_path, photo, monkeypatch):
    pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    photo.pop("face")
    monkeypatch.setattr(heads, "_find_face", lambda *args, **kwargs: None)
    with pytest.raises(StoryError, match=r"No face found in drawing.png. Add a face box"):
        portraits.generate(tmp_path, {"cast": {"mira": {"photos": [photo]}}})


@pytest.mark.parametrize("license", ["CC BY-NC 4.0", "CC BY-ND 4.0", "unknown"])
def test_all_portrait_rights_are_checked_before_pixel_work(tmp_path, photo, monkeypatch, license):
    monkeypatch.setattr(Image, "open", lambda *args, **kwargs: pytest.fail("pixels opened before rights"))
    bad = {**photo, "license": license}
    with pytest.raises(StoryError, match="NC, ND and unknown licenses are refused"):
        portraits.generate(tmp_path, {"cast": {"mira": {"photos": [photo, bad]}}})
    assert not (tmp_path / "heads").exists()


def test_cutout_writes_both_assets_and_sheet_shows_portrait(tmp_path, photo, monkeypatch):
    # The cutout algorithm is tested separately. Use a solid head to locate the crop inset.
    def cut(source, output, **kwargs):
        output.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGBA", (200, 200), (230, 10, 20, 255)).save(output)

    monkeypatch.setattr(heads, "cut_head", cut)
    records = heads.generate(tmp_path, {"cast": {"mira": {"photos": [photo]}}}, sheet=True)
    assert records[0]["head"] == "heads/mira-0.png"
    assert (tmp_path / "heads/mira-0-portrait.jpg").is_file()
    with Image.open(tmp_path / "heads/sheet.png") as sheet:
        assert sheet.getpixel((210, 230))[:3] != (230, 10, 20)


@pytest.mark.parametrize("face", [[290, 60, 60, 100], [0, 0, 1, 20]])
def test_face_box_must_fit_the_source(tmp_path, photo, face):
    photo["face"] = face
    with pytest.raises(StoryError, match="must fit inside its 300x240 image"):
        portraits.generate(tmp_path, {"cast": {"mira": {"photos": [photo]}}})
