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
    pytest.importorskip("numpy")
    pytest.importorskip("cv2")
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
    pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    photo["face"] = [200, 200, 150, 150]
    with pytest.raises(StoryError, match="must fit inside"):
        heads.generate(tmp_path, {"cast": {"mira": {"photos": [photo]}}})


def test_missing_face_detector_match_requests_an_explicit_box(tmp_path, photo, monkeypatch):
    pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    photo.pop("face")
    monkeypatch.setattr(heads, "_find_face", lambda image, cv2, **kwargs: None)
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


@pytest.mark.parametrize("side", ["original", "mirror"])
def test_profile_fallback_checks_both_directions(monkeypatch, side):
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    image = np.zeros((100, 200, 3), dtype=np.uint8)
    image[:, 0] = 255
    calls = []

    class Detector:
        def __init__(self, filename):
            self.profile = filename.endswith("haarcascade_profileface.xml")

        def empty(self):
            return False

        def detectMultiScale(self, gray, *args, **kwargs):
            mirrored = bool(gray[0, -1] == 255)
            calls.append((self.profile, mirrored))
            if self.profile and mirrored == (side == "mirror"):
                return [(20, 10, 30, 40)]
            return []

    monkeypatch.setattr(cv2, "CascadeClassifier", Detector)
    detection = {}
    found = heads._find_face(image, cv2, detection=detection)
    assert calls == [(False, False), (True, False), (True, True)]
    assert found == ((20, 10, 30, 40) if side == "original" else (150, 10, 30, 40))
    assert detection == {"face_count": 1}


def test_largest_detected_face_wins_and_is_reported(tmp_path, photo, monkeypatch, capsys):
    pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    photo.pop("face")
    calls = []

    class Detector:
        def __init__(self, filename):
            calls.append(filename)

        def empty(self):
            return False

        def detectMultiScale(self, *args, **kwargs):
            return [(20, 30, 40, 50), (100, 100, 100, 110), (230, 100, 30, 35)]

    monkeypatch.setattr(cv2, "CascadeClassifier", Detector)
    records = heads.generate(tmp_path, {"cast": {"mira": {"photos": [photo]}}})
    # One face detector, then the eye detector that checks whether the head is tilted.
    assert calls[0].endswith("haarcascade_frontalface_default.xml")
    assert [name.rsplit("_", 1)[-1] for name in calls[1:]] == ["eye.xml"]
    assert "leveled" not in records[0]
    assert records[0]["face"] == [100, 100, 100, 110]
    assert records[0]["face_count"] == 3 and records[0]["selection"] == "largest"
    assert "found 3 faces; using the largest" in capsys.readouterr().err
    assert (tmp_path / "heads/mira-0.png").is_file()


def test_manual_face_box_bypasses_all_detectors(tmp_path, photo, monkeypatch, capsys):
    pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    monkeypatch.setattr(cv2, "CascadeClassifier", lambda *args: pytest.fail("manual face must override detection"))
    records = heads.generate(tmp_path, {"cast": {"mira": {"photos": [photo]}}})
    assert "selection" not in records[0]
    assert capsys.readouterr().err == ""


def test_profile_detections_of_the_same_face_count_once(monkeypatch):
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    calls = 0

    class Detector:
        def __init__(self, filename):
            self.profile = filename.endswith("haarcascade_profileface.xml")

        def empty(self):
            return False

        def detectMultiScale(self, *args, **kwargs):
            nonlocal calls
            if not self.profile:
                return []
            calls += 1
            return [(20, 10, 30, 40)] if calls == 1 else [(150, 10, 30, 40)]

    monkeypatch.setattr(cv2, "CascadeClassifier", Detector)
    detection = {}
    assert heads._find_face(np.zeros((100, 200, 3), dtype=np.uint8), cv2, detection=detection) == (20, 10, 30, 40)
    assert detection["face_count"] == 1


def test_sheet_includes_every_cut_head_on_checks_with_cast_ids(tmp_path, photo, monkeypatch):
    pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    from PIL import ImageDraw

    labels = []
    draw_text = ImageDraw.ImageDraw.text

    def record_text(self, xy, text, *args, **kwargs):
        labels.append(text)
        return draw_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", record_text)
    story = {"cast": {"mira": {"photos": [photo]}, "sol": {"photos": [photo, photo]}}}
    records = heads.generate(tmp_path, story, sheet=True)
    assert len(records) == 3
    assert labels == ["mira / 0", "sol / 0", "sol / 1"]
    width, height, rows = read_png_rgba(tmp_path / "heads/sheet.png")
    assert (width, height) == (560, 680)
    assert tuple(rows[0][0:4]) == (235, 235, 235, 255)
    assert tuple(rows[0][80:84]) == (210, 210, 210, 255)
    assert tuple(rows[170][140 * 4:140 * 4 + 4]) not in ((235, 235, 235, 255), (210, 210, 210, 255))
    assert not list((tmp_path / "heads").glob("*.tmp"))


def test_background_leak_is_retried_then_reported(tmp_path, photo, monkeypatch, capsys):
    """A cut that fills the whole allowed area is a leak: retry tighter, then warn."""
    pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    rooms = []
    real = heads.cut_head

    def watch(*args, **kwargs):
        rooms.append(kwargs.get("room", 1.0))
        return real(*args, **kwargs)

    # A separator that keeps everything it was offered behaves like a photo
    # whose wall matches the hair.
    def keep_everything(image, mask, *args, **kwargs):
        mask[:] = cv2.GC_PR_FGD

    monkeypatch.setattr(cv2, "grabCut", keep_everything)
    monkeypatch.setattr(heads, "cut_head", watch)
    records = heads.generate(tmp_path, {"cast": {"mira": {"name": "Mira Vale", "photos": [photo]}}})
    assert rooms[0] == 1.0 and len(rooms) > 1 and rooms == sorted(rooms, reverse=True)
    assert min(rooms) >= heads.LEAK_MIN_ROOM
    assert records[0]["warning"] == "background may have leaked into the cut"
    assert "may have leaked" in capsys.readouterr().err
    assert (tmp_path / "heads/mira-0.png").exists()


def test_clean_cut_keeps_full_room(tmp_path, photo):
    pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    records = heads.generate(tmp_path, {"cast": {"mira": {"name": "Mira Vale", "photos": [photo]}}})
    assert "room" not in records[0] and "warning" not in records[0]


class _Eyes:
    """Stands in for OpenCV's eye detector with boxes chosen by the test."""
    boxes: list = []

    def __init__(self, filename):
        self.filename = filename

    def empty(self):
        return False

    def detectMultiScale(self, *args, **kwargs):
        return list(self.boxes) if self.filename.endswith("haarcascade_eye.xml") else [(100, 100, 100, 110)]


@pytest.mark.parametrize("boxes,expected", [
    ([(15, 30, 20, 20), (62, 20, 20, 20)], -12.0),     # right eye higher: turn the photo back
    ([(15, 30, 20, 20), (62, 31, 20, 20)], 0.0),       # nearly level: leave it alone
    ([(10, 30, 20, 20), (28, 10, 20, 20)], 0.0),       # both on one side: not a pair of eyes
    ([(15, 30, 20, 20), (62, 20, 8, 8)], 0.0),         # sizes too different
    ([(15, 30, 20, 20)], 0.0),
    ([(15, 40, 20, 20), (55, 0, 30, 30), (62, 30, 20, 20)], -12.0),  # a false third box does not hide the pair
])
def test_eye_tilt_only_trusts_a_believable_pair(monkeypatch, boxes, expected):
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    monkeypatch.setattr(_Eyes, "boxes", boxes)
    monkeypatch.setattr(cv2, "CascadeClassifier", _Eyes)
    tilt = heads._eye_tilt(np.zeros((320, 300, 3), np.uint8), (100, 100, 100, 110), cv2)
    assert tilt == pytest.approx(expected, abs=.5)


def test_tilted_head_is_leveled_before_the_cut(tmp_path, photo, monkeypatch):
    pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    photo.pop("face")
    monkeypatch.setattr(_Eyes, "boxes", [(15, 30, 20, 20), (62, 20, 20, 20)])
    monkeypatch.setattr(cv2, "CascadeClassifier", _Eyes)
    records = heads.generate(tmp_path, {"cast": {"mira": {"name": "Mira Vale", "photos": [photo]}}})
    assert records[0]["leveled"] == pytest.approx(-12.0, abs=.5)
    assert (tmp_path / "heads/mira-0.png").is_file()
