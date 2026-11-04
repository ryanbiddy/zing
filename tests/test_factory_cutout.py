"""Speaker cutout and photo upscaling: consent, the quality gate, the caches and how a render picks them up."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from myzing.factory import cutout, render, upscale
from myzing.factory.tools import FactoryError

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
Image = pytest.importorskip("PIL.Image")


def test_downloads_need_consent_and_nothing_runs_without_them(zing_workspace, tmp_path):
    assert not cutout.ready() and not upscale.ready()
    with pytest.raises(FactoryError, match="consent"):
        cutout.fetch()
    with pytest.raises(FactoryError, match="consent"):
        upscale.fetch()
    with pytest.raises(FactoryError, match="fetch-cutout"):
        cutout.segment(np.zeros((40, 40, 3), np.uint8))
    small = tmp_path / "small.jpg"
    Image.new("RGB", (400, 300)).save(small)
    with pytest.raises(FactoryError, match="fetch-upscale"):
        upscale.upscale(small, tmp_path / "out.jpg")


def test_a_speaker_too_small_missing_or_filling_the_frame_is_not_cut_out():
    assert cutout.usable([.3] * 20) is None
    assert "fills 3%" in cutout.usable([.03] * 20)                       # a tiny inset camera, like a conference slide
    assert "missing" in cutout.usable([.3] * 15 + [0] * 5)              # the speaker walks off
    assert "fills 95%" in cutout.usable([.95] * 20)
    assert cutout.usable([]) == "no frames to cut out"
    assert cutout.frames_in([(0, .1), (1.0, 1.05)], 40) == [1, 2, 3, 4, 31, 32]


def clip(tmp_path: Path, frames: int = 12, settings: dict | None = None) -> Path:
    d = tmp_path / "clip01"
    (d / "frames").mkdir(parents=True)
    (d / "visuals").mkdir()
    for f in range(1, frames + 1):
        cv2.imwrite(str(d / "frames" / f"{f:05d}.jpg"), np.full((90, 160, 3), f * 10, np.uint8))
    photo, page = d / "visuals" / "photo.jpg", d / "visuals" / "page.png"
    Image.new("RGB", (640, 480), "navy").save(photo)
    Image.new("RGB", (640, 480), "white").save(page)
    (d / "plan.json").write_text(json.dumps({
        "hook": "A *box*", "shots": [{"from": 0, "layout": "solo"}, {"from": .1, "layout": "split", "visual": "v1"},
                                     {"from": .2, "layout": "split", "visual": "v2"}],
        "visuals": {"v1": {"path": str(photo), "credit": "Jo · CC BY"}, "v2": {"path": str(page), "fit": "contain"}}}),
        encoding="utf-8")
    (d / "words.json").write_text(json.dumps({"words": [{"w": "hi", "os": 0, "oe": .3}]}), encoding="utf-8")
    (d / "cams.json").write_text(json.dumps({"frames": frames, "size": [160, 90], "cams": []}), encoding="utf-8")
    (tmp_path / "factory.json").write_text(json.dumps(settings or {}), encoding="utf-8")
    return d


def person(share: float):
    """A fake segmenter: a person filling `share` of the frame's width, as a full-height column."""
    calls = []

    def seg(rgb):
        calls.append(1)
        a = np.zeros(rgb.shape[:2], np.float32)
        a[:, : int(rgb.shape[1] * share)] = 1
        return a
    return seg, calls


def test_mattes_cover_the_shots_blend_between_keys_and_are_reused(tmp_path, monkeypatch):
    d = clip(tmp_path)
    seg, calls = person(.4)
    monkeypatch.setattr(cutout, "segment", seg)
    got = cutout.mattes(d, [(0, .3)])
    assert got["frames"] == list(range(1, 11)) and len(calls) == 5 + 1          # every 2nd frame, plus the last
    png = cv2.imread(str(d / "mattes" / "00002.png"), cv2.IMREAD_UNCHANGED)
    assert png.shape[2] == 4 and png[45, 10, 3] > 200 and png[45, 150, 3] < 30   # opaque on the person only
    assert cutout.mattes(d, [(0, .2)])["frames"] == got["frames"] and len(calls) == 6   # reused
    tiny, _ = person(.03)
    monkeypatch.setattr(cutout, "segment", tiny)
    e = clip(tmp_path / "inset")
    assert cutout.mattes(e, [(0, .3)]) is None
    assert "a cutout needs" in json.loads((e / "mattes" / "meta.json").read_text(encoding="utf-8"))["why"]
    assert cutout.mattes(e, []) is None


def no_frames(monkeypatch):
    monkeypatch.setattr(render, "run", lambda *a, **k: None)
    monkeypatch.setattr(render, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(render.depth, "ready", lambda: False)


def test_render_stands_the_speaker_in_front_only_when_asked_and_the_cutout_is_clean(zing_workspace, tmp_path,
                                                                                     monkeypatch):
    no_frames(monkeypatch)
    seg, _ = person(.4)
    monkeypatch.setattr(cutout, "segment", seg)
    monkeypatch.setattr(render.cutout, "ready", lambda: True)
    data = render.scene_data(clip(tmp_path / "on", settings={"cutout": True}), "9x16", "zing")
    assert [s["layout"] for s in data["shots"]] == ["solo", "front", "front"] and data["mattesDir"].startswith("file:")
    data = render.scene_data(clip(tmp_path / "off"), "9x16", "zing")                     # the default: split
    assert [s["layout"] for s in data["shots"]] == ["solo", "split", "split"] and "mattesDir" not in data
    data = render.scene_data(clip(tmp_path / "flag"), "9x16", "zing", front=True)        # a render can ask for it
    assert data["shots"][1]["layout"] == "front"
    tiny, _ = person(.03)
    monkeypatch.setattr(cutout, "segment", tiny)
    data = render.scene_data(clip(tmp_path / "inset", settings={"cutout": True}), "9x16", "zing")
    assert data["shots"][1]["layout"] == "split"                                         # too small to lift: stays split
    monkeypatch.setattr(render.cutout, "ready", lambda: False)
    data = render.scene_data(clip(tmp_path / "nomodel", settings={"cutout": True}), "9x16", "zing")
    assert data["shots"][1]["layout"] == "split"


def fake_esrgan(monkeypatch, fail=False):
    runs, real = [], upscale.subprocess.run

    def run(argv, **kwargs):
        if "-i" not in argv:                                 # anything else (the platform probe) runs for real
            return real(argv, **kwargs)
        runs.append(argv)
        if not fail:
            src, out = Path(argv[argv.index("-i") + 1]), Path(argv[argv.index("-o") + 1])
            with Image.open(src) as im:
                im.resize((im.width * 4, im.height * 4)).save(out)
        return type("Done", (), {"returncode": 1 if fail else 0})()
    monkeypatch.setattr(upscale.subprocess, "run", run)
    monkeypatch.setattr(upscale, "ready", lambda: True)
    return runs


def test_small_photos_are_upscaled_once_and_big_ones_are_left_alone(tmp_path, monkeypatch):
    runs = fake_esrgan(monkeypatch)
    small = tmp_path / "small.jpg"
    Image.new("RGB", (800, 500), "teal").save(small)
    out = tmp_path / "vis" / "v1-upscaled.jpg"
    assert upscale.upscale(small, out) == out
    with Image.open(out) as im:
        assert im.size == (2400, 1500)                       # 4x, then kept at a 2400 px long side
    assert upscale.upscale(small, out) == out and len(runs) == 1                        # reused
    assert not list(out.parent.glob("*.png"))                                           # the 4x PNG is cleaned up
    big = tmp_path / "big.jpg"
    Image.new("RGB", (1800, 1200)).save(big)
    assert upscale.upscale(big, tmp_path / "big-up.jpg") is None and len(runs) == 1
    fake_esrgan(monkeypatch, fail=True)                                                 # no Vulkan device
    assert upscale.upscale(small, tmp_path / "again.jpg") is None


def test_render_upscales_photos_not_pages_and_credits_it(zing_workspace, tmp_path, monkeypatch):
    no_frames(monkeypatch)
    fake_esrgan(monkeypatch)
    data = render.scene_data(clip(tmp_path / "on"), "9x16", "zing")
    assert data["visuals"]["v1"]["src"].endswith("v1-upscaled.jpg") and data["visuals"]["v1"]["w"] == 2400
    assert data["visuals"]["v1"]["credit"] == "Jo · CC BY · upscaled"
    assert data["visuals"]["v2"]["src"].endswith("page.png") and data["visuals"]["v2"]["credit"] == ""
    for name, settings, flag in (("setting", {"upscale": False}, None), ("flag", None, False)):
        data = render.scene_data(clip(tmp_path / name, settings=settings), "9x16", "zing", sharpen=flag)
        assert data["visuals"]["v1"]["src"].endswith("photo.jpg")


def test_the_upscaler_unpacks_only_its_program_and_model(zing_workspace, monkeypatch):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name in upscale.members() + ["onepiece_demo.mp4", "models/realesrgan-x4plus-anime.bin"]:
            z.writestr(name, name.encode())
    blob = buf.getvalue()
    monkeypatch.setitem(upscale.BUILDS, upscale.build(), (__import__("hashlib").sha256(blob).hexdigest(), len(blob)))

    def fetched(url, target, digest, limit, progress=None):
        assert url.endswith(f"-{upscale.build()}.zip") and limit == len(blob)
        Path(target).write_bytes(blob)
    monkeypatch.setattr(upscale.model_fetch, "fetch_verified", fetched)
    assert upscale.fetch(consent=True) == upscale.program() and upscale.ready()
    names = sorted(str(p.relative_to(upscale.folder())).replace("\\", "/") for p in upscale.folder().rglob("*") if p.is_file())
    assert names == sorted(upscale.members() + ["installed.json"])                      # no demo video, no zip left
    upscale.program().write_bytes(b"tampered")
    upscale._checked = None
    assert not upscale.ready()
