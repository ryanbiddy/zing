from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from myzing.factory import cut
from myzing.layout import detector
from test_factory_grid_tiles import grid

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")


@pytest.fixture
def clip(tmp_path, monkeypatch, zing_workspace):
    (tmp_path / "frames").mkdir()
    for n in range(1, 361):
        (tmp_path / "frames" / f"{n:05d}.jpg").touch()
    state = SimpleNamespace(path=tmp_path, frame=None, faces=[(580, 90, 100, 145)], cuts=[], burn=None)
    monkeypatch.setattr(cut, "_camera_cuts", lambda *a: state.cuts)
    monkeypatch.setattr(cut, "burned_caption_top", lambda d: state.burn)
    monkeypatch.setattr(detector, "require_model", lambda: tmp_path / "model")
    monkeypatch.setattr(cv2, "imread", lambda path: state.frame((int(path[-9:-4])-1)/30).copy())
    monkeypatch.setattr(cv2, "FaceDetectorYN", SimpleNamespace(create=lambda *a: SimpleNamespace(
        setInputSize=lambda size: None, detect=lambda img: (None, np.array([
            [x, y, w, h, x+.3*w, y+.35*h, x+.7*w, y+.35*h, x+.5*w, y+.55*h,
             x+.3*w, y+.75*h, x+.7*w, y+.75*h, .9]
            for x, y, w, h in (state.faces(img) if callable(state.faces) else state.faces)], dtype=np.float32)))))
    return state


def room():
    img = np.full((540, 960, 3), (95, 110, 125), dtype=np.uint8)
    for y in range(20, 540, 65):
        cv2.line(img, (0, y), (959, y), (55, 65, 75), 3)
    cv2.rectangle(img, (60, 65), (160, 360), (40, 55, 60), -1)
    cv2.ellipse(img, (630, 162), (50, 72), 0, 0, 360, (110, 150, 195), -1)
    return img


def panel(img, box, dark=False, text=True):
    img = img.copy()
    l, t, r, b = [round(v*(540 if i % 2 else 960)) for i, v in enumerate(box)]
    cv2.rectangle(img, (l, t), (r-1, b-1), (12, 12, 12) if dark else (245, 245, 245), -1)
    if text:
        for y in range(t+25, b-15, 28):
            cv2.putText(img, "TWO ROUTES DIFFER", (l+15, y), cv2.FONT_HERSHEY_SIMPLEX, .55,
                        (230, 230, 230) if dark else (25, 25, 25), 2)
    else:
        cv2.circle(img, ((l+r)//2, (t+b)//2), 50, (50, 125, 200), -1)
    return img


@pytest.mark.parametrize("start,end,dark,text", [(2.4, 5.6, True, True), (0, 4.4, True, True),
                                               (7.2, 12, False, True), (3.1, 6.7, False, False),
                                               (2, 10, True, True), (0, 9.4, True, True), (2.1, 12, False, True)])
def test_temporary_panel_has_its_own_window_and_box(clip, start, end, dark, text):
    box = [.025, .08, .46, .82]
    plain = room()
    shown = panel(plain, box, dark, text)
    clip.frame = lambda t: shown if start <= t < end else plain
    info = cut.cams(clip.path)
    overlays = info.get("overlays", [])
    assert len(overlays) == 1
    assert overlays[0]["from"] == pytest.approx(start, abs=.15)
    assert overlays[0]["to"] == pytest.approx(end, abs=.15)
    assert overlays[0]["box"] == pytest.approx(box, abs=.025)
    assert [(c["from"], c["to"]) for c in info["cams"]] == [(0, 12)]
    assert json.loads((clip.path / "cams.json").read_text(encoding="utf-8")) == info


def test_repeated_panel_keeps_the_clear_gap(clip):
    plain = room()
    shown = panel(plain, [.025, .08, .46, .82], dark=True)
    clip.frame = lambda t: shown if 2 <= t < 4 or 7 <= t < 10 else plain
    overlays = cut.cams(clip.path).get("overlays", [])
    assert len(overlays) == 2
    for overlay, (start, end) in zip(overlays, [(2, 4), (7, 10)]):
        assert overlay["from"] == pytest.approx(start, abs=.15)
        assert overlay["to"] == pytest.approx(end, abs=.15)


def test_permanent_bright_poster_is_part_of_the_room(clip):
    img = panel(room(), [.025, .08, .46, .82])
    clip.frame = lambda t: img
    assert not cut.cams(clip.path).get("overlays")


def test_another_camera_view_is_not_an_overlay(clip):
    plain = room()
    other = panel(plain, [.025, .08, .46, .82])
    clip.cuts = [4, 8]
    clip.frame = lambda t: other if 4 <= t < 8 else plain
    assert not cut.cams(clip.path).get("overlays")


def test_rounded_camera_edges_do_not_borrow_the_next_shots_face(clip):
    plain = room()
    shown = panel(plain, [.025, .08, .46, .82], dark=True)
    other = plain.copy()
    other[0, 0] = 3
    clip.cuts = [2+1/30, 10+1/30]
    clip.faces = lambda img: [(200 if img[0, 0, 0] == 3 else 580, 90, 100, 145)]
    clip.frame = lambda t: other if t < clip.cuts[0] or t >= clip.cuts[1] else shown if 4 <= t < 7 else plain
    overlays = cut.cams(clip.path).get("overlays", [])
    assert len(overlays) == 1
    assert overlays[0]["from"] == pytest.approx(4, abs=.15)
    assert overlays[0]["to"] == pytest.approx(7, abs=.15)


def test_burned_lower_third_is_not_an_overlay(clip):
    plain = room()
    shown = panel(plain, [0, .78, 1, 1])
    clip.burn = .76
    clip.frame = lambda t: shown if 2 <= t < 5 else plain
    assert not cut.cams(clip.path).get("overlays")


def test_grid_tiles_are_not_overlays(clip):
    img, clip.faces, _ = grid()
    other = img.copy()
    other[25:400, 25:220] = (110, 150, 195)
    clip.frame = lambda t: other if 3 <= t < 6 else img
    assert not cut.cams(clip.path).get("overlays")


def test_moving_speaker_is_not_an_overlay(clip):
    plain = room()
    def moving(t):
        img = plain.copy()
        cv2.ellipse(img, (600+round(20*t), 340), (65, 100), 0, 0, 360, (30, 60, 120), -1)
        return img
    clip.frame = moving
    assert not cut.cams(clip.path).get("overlays")
