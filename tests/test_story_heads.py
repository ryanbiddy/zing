"""Head stickers use drawn shapes and explicit rights, never real photos."""
from __future__ import annotations

import struct
import zlib

import pytest

from myzing.story import StoryError, heads


def draw_photo(path):
    width, height = 300, 320
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            inside = ((x - 150) / 67) ** 2 + ((y - 140) / 86) ** 2 <= 1
            pixels.extend((225, 166, 110) if inside else (33, 90, 102))
    path.write_bytes(f"P6\n{width} {height}\n255\n".encode() + pixels)


def read_png_rgba(path):
    """Read the cutter's PNG with stdlib so assertions do not use its image API."""
    content = path.read_bytes()
    assert content[:8] == b"\x89PNG\r\n\x1a\n"
    position, packed = 8, bytearray()
    while position < len(content):
        length = struct.unpack_from(">I", content, position)[0]
        kind, data = content[position + 4:position + 8], content[position + 8:position + 8 + length]
        if kind == b"IHDR":
            width, height, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", data)
            assert (depth, color, interlace) == (8, 6, 0)
        elif kind == b"IDAT":
            packed.extend(data)
        position += length + 12
    raw, stride, rows = zlib.decompress(packed), width * 4, []
    for y in range(height):
        offset = y * (stride + 1)
        method, row = raw[offset], bytearray(raw[offset + 1:offset + stride + 1])
        previous = rows[-1] if rows else bytearray(stride)
        for x in range(stride):
            left, above, upper_left = row[x - 4] if x >= 4 else 0, previous[x], previous[x - 4] if x >= 4 else 0
            if method == 1:
                predictor = left
            elif method == 2:
                predictor = above
            elif method == 3:
                predictor = (left + above) // 2
            elif method == 4:
                p = left + above - upper_left
                distances = abs(p - left), abs(p - above), abs(p - upper_left)
                predictor = (left, above, upper_left)[distances.index(min(distances))]
            else:
                assert method == 0
                predictor = 0
            row[x] = (row[x] + predictor) & 255
        rows.append(row)
    return width, height, rows


@pytest.fixture
def photo(tmp_path):
    draw_photo(tmp_path / "shape.ppm")
    return {"path": "shape.ppm", "credit": "Test drawing", "license": "CC0 1.0",
            "source_url": "https://example.org/test-drawing", "face": [100, 100, 100, 110]}


def test_explicit_box_produces_transparent_corners_and_opaque_center(tmp_path, photo):
    story = {"cast": {"mira": {"name": "Mira Vale", "photos": [photo]}, "sol": {"name": "Sol Reed"}}}
    records = heads.generate(tmp_path, story)
    output = tmp_path / "heads/mira-0.png"
    width, height, rows = read_png_rgba(output)
    assert rows[0][3] == rows[0][-1] == rows[-1][3] == rows[-1][-1] == 0
    assert rows[height // 2][(width // 2) * 4 + 3] == 255
    assert max(width, height) > heads.HEAD_SIZE
    opaque = [tuple(row[x:x + 4]) for row in rows for x in range(0, len(row), 4) if row[x + 3] == 255]
    assert (250, 250, 250, 255) in opaque
    assert records == [{"cast_id": "mira", "index": 0, "path": "shape.ppm", "head": "heads/mira-0.png",
                        "credit": "Test drawing", "license": "CC0 1.0",
                        "source_url": "https://example.org/test-drawing", "rights": "cleared"}]
    assert "heads" not in story["cast"]["mira"]


@pytest.mark.parametrize("missing", ["credit", "license", "source_url", "path"])
def test_missing_photo_metadata_is_refused_before_image_tools(tmp_path, photo, missing, monkeypatch):
    photo.pop(missing)
    monkeypatch.setattr(heads, "_image_tools", lambda: pytest.fail("image tools loaded before rights check"))
    with pytest.raises(StoryError, match=f"requires {missing}"):
        heads.generate(tmp_path, {"cast": {"mira": {"photos": [photo]}}})
    assert not (tmp_path / "heads").exists()


@pytest.mark.parametrize("license", ["CC BY-NC 4.0", "CC BY-ND 4.0", "CC BY-NC-SA 4.0",
                                     "Attribution No Derivatives", "All rights reserved"])
def test_uncleared_photos_are_refused_even_when_local(tmp_path, photo, license, monkeypatch):
    photo["license"] = license
    monkeypatch.setattr(heads, "_image_tools", lambda: pytest.fail("image tools loaded before rights check"))
    with pytest.raises(StoryError, match="NC, ND and unknown licenses are refused"):
        heads.generate(tmp_path, {"cast": {"mira": {"photos": [photo]}}})


@pytest.mark.parametrize("license,rights", [("CC0", "cleared"), ("Public domain", "cleared"),
                                            ("CC BY 4.0", "attribution"), ("CC BY-SA 4.0", "attribution")])
def test_factory_license_policy_is_reused(photo, license, rights):
    photo["license"] = license
    assert heads.photo_errors(photo) == []
    assert heads.photo_rights(photo) == rights


def test_no_photo_needs_no_image_libraries(tmp_path, monkeypatch):
    monkeypatch.setattr(heads.importlib, "import_module", lambda name: pytest.fail(f"optional import: {name}"))
    assert heads.generate(tmp_path, {"cast": {"mira": {"name": "Mira Vale", "photos": []}}}) == []
    assert not (tmp_path / "heads").exists()


@pytest.mark.parametrize("face", [[1, 2, 3], [1, 2, 0, 3], [-1, 2, 3, 4], [1, 2, True, 4], [1, 2, float("nan"), 4]])
def test_bad_face_box_has_a_plain_error(tmp_path, photo, face):
    photo["face"] = face
    with pytest.raises(StoryError, match="photo face"):
        heads.generate(tmp_path, {"cast": {"mira": {"photos": [photo]}}})


def test_out_of_bounds_face_is_refused(tmp_path, photo):
    photo["face"] = [200, 200, 150, 150]
    with pytest.raises(StoryError, match="must fit inside"):
        heads.generate(tmp_path, {"cast": {"mira": {"photos": [photo]}}})


def test_missing_face_detector_match_requests_an_explicit_box(tmp_path, photo, monkeypatch):
    photo.pop("face")
    monkeypatch.setattr(heads, "_find_face", lambda image, cv2: None)
    with pytest.raises(StoryError, match="Add a face box"):
        heads.generate(tmp_path, {"cast": {"mira": {"photos": [photo]}}})


def test_bad_cast_id_cannot_write_outside_heads_directory(tmp_path, photo):
    with pytest.raises(StoryError, match="cast id"):
        heads.generate(tmp_path, {"cast": {"../outside": {"photos": [photo]}}})


def test_all_rights_are_checked_before_any_cut(tmp_path, photo, monkeypatch):
    monkeypatch.setattr(heads, "cut_head", lambda *args, **kwargs: pytest.fail("cut ran before every photo was checked"))
    with pytest.raises(StoryError, match="requires license"):
        heads.generate(tmp_path, {"cast": {"mira": {"photos": [photo, {**photo, "license": ""}]}}})


@pytest.mark.parametrize("path", [None, [], {}, 123, True])
def test_rights_helper_handles_a_malformed_path_for_validator(photo, path):
    photo["path"] = path
    assert heads.photo_rights(photo) == "cleared"
    assert heads.photo_errors(photo) == ["photo requires path"]
