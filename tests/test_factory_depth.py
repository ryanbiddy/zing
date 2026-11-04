"""Depth parallax for still photos: the move, the cache, the fallbacks and how a render picks it up."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from myzing.factory import depth, render
from myzing.factory.tools import FactoryError

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")


def scene(h=240, w=320):
    """A textured far wall with a near box in the middle, and its depth."""
    rng = np.random.default_rng(7)
    img = (rng.random((h, w, 3)) * 255).astype(np.uint8)
    img[80:160, 120:200] = (40, 200, 240)
    d = np.zeros((h, w), np.float32)
    d[80:160, 120:200] = 1
    return img, d


def box_x(frame) -> float:
    mask = np.all(np.abs(frame.astype(int) - (40, 200, 240)) < 30, axis=2)
    return float(np.nonzero(mask)[1].mean())


def test_near_things_move_against_the_far_wall():
    img, d = scene()
    fr = list(depth.frames(img, d, 30, "push-right"))
    assert len(fr) == 30 and all(f.shape == img.shape for f in fr)
    # the wall is the far layer; the box slides against it and grows
    assert box_x(fr[-1]) - box_x(fr[0]) > 4
    grown = lambda f: np.all(np.abs(f.astype(int) - (40, 200, 240)) < 30, axis=2).sum()
    assert grown(fr[-1]) > grown(fr[0])
    # eased: the middle frame is between the ends, and the first two frames barely differ
    assert box_x(fr[0]) < box_x(fr[15]) < box_x(fr[-1])
    assert abs(box_x(fr[1]) - box_x(fr[0])) < .5


def test_moves_are_stable_per_visual():
    assert depth.move_for("v1") == depth.move_for("v1") and depth.move_for("v1") in depth.MOVES


def test_download_needs_consent_and_nothing_runs_without_weights(zing_workspace):
    assert not depth.ready()
    with pytest.raises(FactoryError, match="consent"):
        depth.fetch()
    with pytest.raises(FactoryError, match="fetch-depth"):
        depth.estimate(np.zeros((40, 40, 3), np.uint8))


class FakeEncoder:
    calls = 0

    def __init__(self, argv, stdin=None):
        FakeEncoder.calls += 1
        self.out, self.stdin, self.returncode = Path(argv[-1]), io.BytesIO(), 0
        self.stdin.close = lambda: None

    def wait(self):
        self.out.write_bytes(self.stdin.getvalue()[:64])


def test_parallax_is_cached_and_flat_pictures_stay_flat(tmp_path, monkeypatch):
    img, d = scene(400, 480)
    photo = tmp_path / "photo.jpg"
    cv2.imencode(".jpg", img)[1].tofile(str(photo))
    monkeypatch.setattr(depth, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(depth.subprocess, "Popen", FakeEncoder)
    monkeypatch.setattr(depth, "estimate", lambda rgb: d)
    FakeEncoder.calls = 0
    out = tmp_path / "vis" / "v1-parallax.mp4"
    assert depth.parallax(photo, out, 1.0, key="v1") == out and out.is_file()
    assert depth.parallax(photo, out, 1.0, key="v1") == out and FakeEncoder.calls == 1      # reused
    depth.parallax(photo, out, 2.0, key="v1")
    assert FakeEncoder.calls == 2                                                            # a longer shot re-encodes
    monkeypatch.setattr(depth, "estimate", lambda rgb: np.full(rgb.shape[:2], .5, np.float32))
    assert depth.parallax(photo, tmp_path / "flat.mp4", 1.0) is None                        # a chart or screenshot
    tiny = tmp_path / "tiny.jpg"
    cv2.imencode(".jpg", img[:100, :100])[1].tofile(str(tiny))
    assert depth.parallax(tiny, tmp_path / "tiny.mp4", 1.0) is None


def clip(tmp_path: Path, settings: dict | None = None) -> Path:
    d = tmp_path / "clip01"
    (d / "visuals").mkdir(parents=True)
    photo, logo = d / "visuals" / "photo.jpg", d / "visuals" / "logo.png"
    cv2.imencode(".jpg", scene()[0])[1].tofile(str(photo))
    cv2.imencode(".png", scene()[0])[1].tofile(str(logo))
    (d / "plan.json").write_text(json.dumps({
        "hook": "A *box*", "shots": [{"from": 0, "layout": "split", "visual": "v1"}, {"from": 3, "layout": "solo"},
                                     {"from": 5, "layout": "split", "visual": "v2"}],
        "visuals": {"v1": {"path": str(photo), "credit": "x"}, "v2": {"path": str(logo), "fit": "contain"}}}), encoding="utf-8")
    (d / "words.json").write_text(json.dumps({"words": [{"w": "hi", "os": 0, "oe": 6.5}]}), encoding="utf-8")
    (d / "cams.json").write_text(json.dumps({"frames": 1, "size": [640, 360], "cams": []}), encoding="utf-8")
    if settings is not None:
        (tmp_path / "factory.json").write_text(json.dumps(settings), encoding="utf-8")
    return d


def test_render_moves_photos_but_never_logos_or_pages(tmp_path, monkeypatch, zing_workspace):
    d = clip(tmp_path)
    asked = []

    def fake_parallax(image, out, seconds, key=""):
        asked.append((Path(image).name, round(seconds, 2), key))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"mp4")
        return out

    def fake_run(*argv, **kwargs):                     # the frame extraction: one frame is enough here
        cv2.imwrite(str(Path(str(argv[-1])).parent / "00001.jpg"), scene()[0])

    monkeypatch.setattr(render.depth, "parallax", fake_parallax)
    monkeypatch.setattr(render, "run", fake_run)
    monkeypatch.setattr(render, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(render.depth, "ready", lambda: True)
    data = render.scene_data(d, "9x16", "zing")
    assert asked == [("photo.jpg", 3.0, "v1")]                 # sized to the shot that shows it
    assert data["visuals"]["v1"]["move"] is True and data["visuals"]["v1"]["frames"] == 1
    assert "src" in data["visuals"]["v2"] and "move" not in data["visuals"]["v2"]
    # off when the project says so, when the render says so, or when the weights are missing
    for i, (settings, flag, ready) in enumerate((({"parallax": False}, None, True), (None, False, True), (None, None, False))):
        asked.clear()
        e = clip(tmp_path / f"case{i}", settings)
        monkeypatch.setattr(render.depth, "ready", lambda r=ready: r)
        data = render.scene_data(e, "9x16", "zing", parallax=flag)
        assert not asked and "src" in data["visuals"]["v1"]
