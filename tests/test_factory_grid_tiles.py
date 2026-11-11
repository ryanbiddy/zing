from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from myzing.factory import cut
from myzing.layout import detector

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")


@pytest.fixture
def clip(tmp_path, monkeypatch, zing_workspace):
    (tmp_path / "frames").mkdir()
    for n in range(1, 91):
        (tmp_path / "frames" / f"{n:05d}.jpg").touch()
    state = SimpleNamespace(path=tmp_path, images=[], faces=[])
    monkeypatch.setattr(cut, "_camera_cuts", lambda *a: [])
    monkeypatch.setattr(cut, "burned_caption_top", lambda d: None)
    monkeypatch.setattr(detector, "require_model", lambda: tmp_path / "model")
    monkeypatch.setattr(cv2, "imread", lambda path: state.images[(int(path[-9:-4])-1)//30].copy())
    monkeypatch.setattr(cv2, "FaceDetectorYN", SimpleNamespace(create=lambda *a: SimpleNamespace(
        setInputSize=lambda size: None, detect=lambda img: (None, np.array([[x, y, w, h, x + .3*w, y + .35*h, x + .7*w, y + .35*h, x + .5*w, y + .55*h,
                                              x + .3*w, y + .75*h, x + .7*w, y + .75*h, .9]
                                             for x, y, w, h in state.faces], dtype=np.float32)))))
    return state


def grid(rows=1, gutters=True):
    img = np.full((540, 960, 3), 12, dtype=np.uint8)
    tiles, faces = [], []
    cols = 4 // rows
    for j in range(4):
        x, y = 20 + j % cols * (920 // cols), 20 + j // cols * (440 // rows)
        w, h = 920 // cols - (8 if gutters else 0), 440 // rows - (8 if gutters else 0)
        color = [(90, 110, 130), (170, 100, 70), (75, 160, 110), (150, 130, 180)][j]
        cv2.rectangle(img, (x, y), (x+w-1, y+h-1), color, -1)
        cv2.rectangle(img, (x, y+h-24), (x+w-1, y+h-1), (48, 48, 48), -1)
        face = (x+w//2-25, y+45, 50, 65)
        cv2.ellipse(img, (face[0]+25, face[1]+32), (25, 32), 0, 0, 360, (110, 150, 195), -1)
        faces.append(face)
        tiles.append([x/960, y/540, (x+w)/960, (y+h)/540])
    return img, faces, tiles


@pytest.mark.parametrize("rows,gutters", [(1, True), (2, True), (1, False)])
def test_grid_face_has_a_tile_from_stable_borders(clip, rows, gutters):
    img, clip.faces, tiles = grid(rows, gutters)
    clip.images = [img.copy() for _ in range(3)]
    info = cut.cams(clip.path)
    assert info["cams"] and all(c["mode"] == "face" and c["wide"] for c in info["cams"])
    for cam in info["cams"]:
        tile = next(t for t in tiles if t[0] < cam["cx"] < t[2] and t[1] < cam["cy"] < t[3])
        assert cam.get("tile") == pytest.approx(tile, abs=.006)
    assert json.loads((clip.path / "cams.json").read_text(encoding="utf-8")) == info


@pytest.mark.parametrize("count", [1, 2, 3])
def test_plain_studio_never_gets_a_tile(clip, count):
    img = np.full((540, 960, 3), (110, 100, 90), dtype=np.uint8)
    cv2.rectangle(img, (80, 60), (160, 470), (30, 40, 50), -1)
    cv2.ellipse(img, (480, 240), (70, 100), 0, 0, 360, (100, 150, 200), -1)
    clip.images = [img]*3
    clip.faces = [(410, 140, 140, 200), (200, 160, 110, 170), (700, 160, 110, 170)][:count]
    info = cut.cams(clip.path)
    assert info["cams"][0]["mode"] == "face"
    assert all("tile" not in c for c in info["cams"])


def test_clear_center_tile_can_have_obscured_neighbors(clip):
    img = np.full((540, 960, 3), 12, dtype=np.uint8)
    cv2.rectangle(img, (220, 20), (739, 379), (150, 160, 170), -1)
    cv2.rectangle(img, (20, 35), (199, 339), (80, 90, 100), -1)
    cv2.rectangle(img, (760, 35), (939, 339), (100, 90, 80), -1)
    img[170:210, 190:210] = 12
    img[170:210, 930:950] = 12
    clip.images = [img]*3
    clip.faces = [(440, 110, 80, 100), (60, 80, 50, 65), (800, 80, 50, 65)]
    cam = cut.cams(clip.path)["cams"][0]
    assert cam["mode"] == "face" and not cam.get("wide")
    assert cam.get("tile") == pytest.approx([220/960, 20/540, 740/960, 380/540], abs=.006)


def test_borders_must_agree_across_samples(clip):
    img, clip.faces, _ = grid()
    clip.images = [img, np.roll(img, 30, axis=1), img]
    assert all("tile" not in c for c in cut.cams(clip.path)["cams"])


def test_unbounded_faces_do_not_get_tiles(clip):
    img, clip.faces, _ = grid()
    img[:20] = img[20]
    img[452:] = img[451]
    clip.images = [img]*3
    assert all("tile" not in c for c in cut.cams(clip.path)["cams"])
