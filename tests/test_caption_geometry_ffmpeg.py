"""Known-answer video acceptance: real FFmpeg drawtext, RapidOCR and pixels.

No system fonts, stock video, downloads, or oracle boxes passed to the detector.
Ground truth is an independently rendered white fill-only glyph mask. Color
tolerance is Delta E 76 <= 10 in Lab D65 (lossy SDR/YUV decoding included).
"""

from __future__ import annotations

import math
import subprocess
from pathlib import Path
from statistics import median

import pytest

from myzing.study import caption_geometry as cg, caption_models

pytestmark = pytest.mark.ffmpeg
FONT_ROOT = Path(__file__).resolve().parents[1] / "src/myzing/_data/fonts"


@pytest.fixture(scope="module")
def runtime():
    pytest.importorskip("cv2")
    pytest.importorskip("rapidocr")
    pytest.importorskip("onnxruntime")
    try:
        caption_models.model_paths()
    except RuntimeError:
        pytest.skip("caption geometry OCR models unavailable; run python -m myzing.study.caption_models --fetch")
    return caption_models.engine()


@pytest.fixture
def reader(runtime, monkeypatch):
    monkeypatch.setattr(caption_models, "engine", lambda: runtime)
    # Any attempt to download during inference is a bug.
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("study attempted network"))
    return cg.read_geometry


def draw(text="CAPTION TEST", *, font="Anton-Regular.ttf", size=40, x="120", y="220",
         fill="0xF0CA40", outline="0x181818", stroke=3, enable=None, plate=False):
    path = (FONT_ROOT / font).as_posix().replace(":", r"\:")
    value = (f"drawtext=fontfile='{path}':text='{text}':fontsize={size}:"
             f"fontcolor={fill}:borderw={stroke}:bordercolor={outline}:x='{x}':y='{y}'")
    if enable:
        value += f":enable='{enable}'"
    if plate:
        value += ":box=1:boxcolor=0x212121:boxborderw=12"
    return value


def render(path, filters, *, width=640, height=360, duration=1.5, bg="0x284268", fps=24):
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
               f"color=c={bg}:s={width}x{height}:r={fps}:d={duration}", "-vf", ",".join(filters),
               "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "10", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(command, check=True, capture_output=True, timeout=60)
    return path


def truth_box(tmp_path, *, text="CAPTION TEST", font="Anton-Regular.ttf", size=40,
              x="120", y="220", width=640, height=360):
    import cv2
    import numpy as np
    path = render(tmp_path / "mask.mp4", [draw(text, font=font, size=size, x=x, y=y,
                   fill="white", stroke=0)], width=width, height=height, duration=.1, bg="black")
    cap = cv2.VideoCapture(str(path))
    ok, frame = cap.read()
    cap.release()
    assert ok
    ys, xs = np.nonzero(frame.mean(axis=2) > 128)
    return [xs.min() / width, ys.min() / height, (xs.max() + 1) / width, (ys.max() + 1) / height]


def primary(result):
    tracks = [t for t in result.tracks if t.kind == "caption"]
    assert tracks, result.to_dict()
    return max(tracks, key=lambda t: len(t.samples) * len(t.text))


@pytest.mark.parametrize("width,height,size,font,x,y", [
    (640, 360, 40, "Anton-Regular.ttf", "120", "220"),
    (360, 640, 32, "Anton-Regular.ttf", "30", "420"),
    (640, 360, 46, "IBMPlexSans.ttf", "80", "100"),
])
def test_static_center_height_and_iou(tmp_path, reader, record_property, width, height, size, font, x, y):
    expected = truth_box(tmp_path, width=width, height=height, size=size, font=font, x=x, y=y)
    path = render(tmp_path / "static.mp4", [draw(size=size, font=font, x=x, y=y,
                  enable="between(t,0.25,1.15)")], width=width, height=height)
    result = reader(path, 1.5)
    track = primary(result)
    for axis in (0, 1):
        errors = [abs(cg._center(s["box"])[axis] - cg._center(expected)[axis]) for s in track.samples]
        record_property(f"median_center_error_{axis}", median(errors))
        assert median(errors) <= .02
    assert track.median_text_height is not None
    record_property("height_relative_error", abs(track.median_text_height / (expected[3] - expected[1]) - 1))
    record_property("median_ink_iou", median(cg._iou(s["box"], expected) for s in track.samples))
    assert abs(track.median_text_height / (expected[3] - expected[1]) - 1) <= .10
    assert median(cg._iou(s["box"], expected) for s in track.samples) >= .8
    assert track.motion == "static"
    assert len(track.samples) >= 5
    assert all(len(d.polygon) == 4 and all(0 <= v <= 1 for p in d.polygon for v in p)
               for f in result.frames for d in f.detections)


def test_moving_fitted_path_tracks_drawn_centers(tmp_path, reader, record_property):
    expected = truth_box(tmp_path, text="MOVE WITH ME", x="50", y="180")
    path = render(tmp_path / "moving.mp4", [draw("MOVE WITH ME", x="50+100*t", y="180+15*t",
                  enable="between(t,0.125,1.3)")])
    result = reader(path, 1.5)
    track = primary(result)
    assert track.motion == "moving"
    assert len(track.samples) >= 7
    measured_times = {s["t"] for s in track.samples}
    path_errors = []
    for run in track.path:
        assert run["keyframes"]
        for key in run["keyframes"]:
            assert key["t"] in measured_times
            expected_center = [cg._center(expected)[0] + 100 * key["t"] / 640,
                               cg._center(expected)[1] + 15 * key["t"] / 360]
            assert max(abs(a - b) for a, b in zip(key["center"], expected_center)) <= .02
            path_errors.append(max(abs(a - b) for a, b in zip(key["center"], expected_center)))
    record_property("max_path_error", max(path_errors))
    assert result.coverage["sampled_fps"] == 8


def test_fill_outline_colors_and_width(tmp_path, reader, record_property):
    import cv2
    import numpy as np
    path = render(tmp_path / "colors.mp4", [draw(enable="between(t,0.25,1.15)")])
    result = reader(path, 1.5)
    track = primary(result)
    estimates = [result.frames[s["sample_index"]].detections[s["detection_indices"][0]].appearance
                 for s in track.samples]
    for role, rgb in [("fill", [240, 202, 64]), ("outline", [24, 24, 24])]:
        lab = cv2.cvtColor(np.array([[rgb]], dtype=np.float32) / 255, cv2.COLOR_RGB2LAB)[0, 0]
        errors = [float(np.linalg.norm(np.array(e[role]["lab"]) - lab)) for e in estimates if e[role]]
        assert len(errors) >= len(estimates) * .8
        record_property(f"median_{role}_delta_e76", median(errors))
        assert median(errors) <= 10
        assert all(e[role]["confidence"] > .4 for e in estimates if e[role])
    assert median(e["stroke_width_px"] for e in estimates if e["stroke_width_px"] is not None) == pytest.approx(3, abs=1.5)
    record_property("median_stroke_width_px", median(e["stroke_width_px"] for e in estimates if e["stroke_width_px"] is not None))


def test_corner_watermark_is_overlay(tmp_path, reader):
    path = render(tmp_path / "watermark.mp4", [draw("ZING CHANNEL", size=24, x="12", y="12", fill="white", stroke=1),
                   draw("FIRST CAPTION", enable="between(t,0.25,0.7)"),
                   draw("SECOND CAPTION", enable="between(t,0.8,1.3)")])
    result = reader(path, 1.5)
    overlays = [t for t in result.tracks if t.kind == "overlay"]
    assert len(overlays) == 1, result.to_dict()
    assert "CHANNEL" in overlays[0].text.upper()
    assert all("CHANNEL" not in t.text.upper() for t in result.tracks if t.kind == "caption")
    assert all("CHANNEL" not in e.text.upper() for e in cg.caption_events(result))
    assert len([t for t in result.tracks if t.kind == "caption"]) >= 2


def test_low_confidence_samples_are_gaps_not_geometry(tmp_path, runtime, monkeypatch):
    """Force confidence loss after real inference; geometry/pixels/decoding stay real."""
    engine, backend = runtime
    count = 0

    def uncertain(frame):
        nonlocal count
        out = engine(frame)
        count += 1
        if count in (4, 5) and out.scores is not None:
            out.scores = [0.2 for _ in out.scores]
        return out

    monkeypatch.setattr(caption_models, "engine", lambda: (uncertain, backend))
    path = render(tmp_path / "gap.mp4", [draw(x="80+60*t")])
    result = cg.read_geometry(path, 1.5)
    low = result.coverage["low_confidence_frames"]
    assert len(low) == 2
    assert all(any(g["t"] == t and g["reason"] == "low_confidence" for g in result.coverage["gaps"]) for t in low)
    assert all(s["t"] not in low for t in result.tracks for s in t.samples)
    assert all(not d.appearance for f in result.frames if f.t in low for d in f.detections)
    for track in result.tracks:
        for segment in track.path:
            keys = segment["keyframes"]
            assert not any(keys[0]["t"] < t < keys[-1]["t"] for t in low)


def test_word_by_word_growth_and_plate(tmp_path, reader):
    path = render(tmp_path / "pop.mp4", [
        draw("STOP", x="80", y="180", stroke=0, plate=True, enable="between(t,0.125,0.45)"),
        draw("STOP RIGHT", x="80", y="180", stroke=0, plate=True, enable="between(t,0.5,0.85)"),
        draw("STOP RIGHT NOW", x="80", y="180", stroke=0, plate=True, enable="between(t,0.9,1.3)"),
    ])
    result = reader(path, 1.5)
    track = primary(result)
    assert track.motion == "popping", result.to_dict()
    assert track.text.upper() == "STOP RIGHT NOW"
    estimates = [result.frames[s["sample_index"]].detections[s["detection_indices"][0]].appearance for s in track.samples]
    assert sum(e["plate_present"] is True for e in estimates) >= len(estimates) * .7


def test_sparse_source_timestamps_are_actual_frames(tmp_path, reader):
    path = render(tmp_path / "sparse.mp4", [draw()], fps=5)
    result = reader(path, 1.5)
    assert all(math.isclose(f.t, f.frame_index / 5) for f in result.frames)
    assert len({f.frame_index for f in result.frames}) == len(result.frames)
    assert any(g["reason"] == "frame_unavailable" for g in result.coverage["gaps"])
    assert any(f.t != f.scheduled_t for f in result.frames)
