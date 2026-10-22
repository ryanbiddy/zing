"""Generated-video oracles: explicit file fonts, offline matching, held-out styles.

Set ZING_TEST_FETCH_FONTS=1 to explicitly provision and exercise all 13 fonts.
Without it, use only the two bundled files. No test fetches implicitly.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from myzing.fonts import library
from myzing.study import caption_geometry as cg, caption_pixels, caption_models
from myzing.study import font_match as fm

pytestmark = pytest.mark.ffmpeg


@pytest.fixture(scope="module")
def font_workspace(tmp_path_factory):
    pytest.importorskip("cv2")
    pytest.importorskip("PIL.Image")
    if os.environ.get("ZING_TEST_FETCH_FONTS") == "1":
        from myzing import storage
        workspace = storage.resolve_workspace()
        library.fetch([f["id"] for f in library.manifest()["fonts"]], workspace)
    else:
        workspace = tmp_path_factory.mktemp("bundled-fonts-only")
    return workspace


def draw(font, text, size, *, stroke=0, plate=False, fill="white"):
    escaped = Path(font).as_posix().replace(":", r"\:")
    value = (f"drawtext=fontfile='{escaped}':text='{text}':fontsize={size}:"
             f"x=30:y=100:fontcolor={fill}:borderw={stroke}:bordercolor=0x151515")
    if plate:
        value += ":box=1:boxcolor=0x151515:boxborderw=12"
    return value


def render(path, filter_value, *, bg="0x34527A"):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"color=c={bg}:s=1280x240:r=24:d=0.25", "-vf", filter_value,
                    "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "14",
                    "-pix_fmt", "yuv420p", str(path)], check=True, capture_output=True, timeout=60)
    return path


def first_frame(path):
    import cv2
    cap = cv2.VideoCapture(str(path))
    ok, frame = cap.read()
    cap.release()
    assert ok
    return frame


def measured_fixture(tmp_path, row, text, size, stroke, plate, fill="white"):
    """Independent FFmpeg fill oracle locates text; no Pillow-produced truth."""
    import numpy as np
    oracle = render(tmp_path / "oracle.mp4", draw(row["path"], text, size), bg="black")
    pixels = first_frame(oracle)
    ys, xs = np.nonzero(pixels.mean(axis=2) > 128)
    assert len(xs) and xs.max() < pixels.shape[1] - 5
    pad = stroke + 3
    x0, x1 = (int(xs.min()) - pad) / 1280, (int(xs.max()) + pad + 1) / 1280
    y0, y1 = (int(ys.min()) - pad) / 240, (int(ys.max()) + pad + 1) / 240
    polygon = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    video = render(tmp_path / "media.mp4", draw(row["path"], text, size, stroke=stroke, plate=plate, fill=fill))
    frame = first_frame(video)
    detection = cg.Detection(text, .99, polygon, [x0, y0, x1, y1], caption_pixels.measure(frame, polygon))
    samples = [cg.FrameSample(i / 24, i / 24, 1 / 24, i, 1280, 240, [detection]) for i in (0, 3, 5)]
    geometry = cg.CaptionGeometry(.25, frames=samples, tracks=cg.track_frames(samples, .25),
                                  provenance={"media": {"sha256": library.sha256(video)}})
    assert len(geometry.tracks) == 1
    return video, geometry


# Texts differ from the separate calibration phrases; a fixed acceptance set.
CASES = [
    ("small-caps", "QUICK BRIGHT WORDS", 24, 0, False, "white"),
    ("outline", "WATCH THIS SPACE", 42, 3, False, "0xF0CA40"),
    ("plate", "MAKE EVERY CUT COUNT", 54, 0, True, "white"),
    ("mixed-case", "Bright ideas Grow", 36, 2, False, "white"),
    ("lowercase-plate", "jump over lazy dogs", 48, 0, True, "0xF0CA40"),
    ("large-digits", "Frame 2026 Go", 68, 4, False, "white"),
]


def assert_top_three(results):
    """Apply the acceptance gate separately to each phrase/style's font set."""
    assert sum(r["rank"] is not None and r["rank"] <= 3 for r in results) / len(results) >= .9, results


@pytest.mark.parametrize("case,text,size,stroke,plate,fill", CASES, ids=[c[0] for c in CASES])
def test_known_fonts_top_three(tmp_path, font_workspace, monkeypatch, case, text, size, stroke, plate, fill):
    rows = [r for r in library.inventory(font_workspace) if r["available"]]
    assert len(rows) == (13 if os.environ.get("ZING_TEST_FETCH_FONTS") == "1" else 2)
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: pytest.fail("matching attempted network"))
    monkeypatch.setattr(library, "urlopen", lambda *a, **k: pytest.fail("matching attempted font download"))
    results = []
    for row in rows:
        folder = tmp_path / row["id"]
        folder.mkdir()
        video, geometry = measured_fixture(folder, row, text, size, stroke, plate, fill)
        result = fm.match_geometry(video, geometry, font_workspace)
        track = result.tracks[0]
        ids = [r["font_id"] for r in track["candidates"]]
        rank = ids.index(row["id"]) + 1 if row["id"] in ids else None
        results.append({"font": row["family"], "case": case, "rank": rank,
                        "top_score": track["candidates"][0]["score"] if ids else None,
                        "true_score": next((c["score"] for c in track["candidates"] if c["font_id"] == row["id"]), None),
                        "status": track["status"]})
        # Full result equality includes every metric, evidence frame and ordering.
        assert result.to_dict() == fm.match_geometry(video, geometry, font_workspace).to_dict()
        assert len(result.available_fonts) == len(rows)
        assert result.provenance["network_used"] is False
        geometry.font_candidates = result.to_dict()
        geometry.write(folder)
    print(json.dumps(results))
    if os.environ.get("ZING_FONT_TEST_REPORT"):
        output = Path(os.environ["ZING_FONT_TEST_REPORT"])
        output.mkdir(parents=True, exist_ok=True)
        (output / f"{case}.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    assert_top_three(results)


@pytest.mark.parametrize("omitted", ["anton", "ibmplexsans"])
def test_absent_font_is_substitution(tmp_path, font_workspace, omitted):
    row = next(r for r in library.inventory(font_workspace) if r["id"] == omitted)
    video, geometry = measured_fixture(tmp_path, row, "Sphinx Bright 248", 45, 3, True)
    # Exclude the generating file while retaining every other available font.
    allowed = [r["id"] for r in library.inventory(font_workspace) if r["available"] and r["id"] != omitted]
    result = fm.match_geometry(video, geometry, font_workspace, font_ids=allowed)
    assert result.tracks[0]["status"] == "best substitute", result.to_dict()
    assert result.tracks[0]["original_font"] == "unknown"
    assert result.tracks[0]["candidates"][0]["score"] < fm.MATCH_THRESHOLD
    assert omitted not in [r["id"] for r in result.available_fonts]


CALIBRATION_CASES = [
    ("cal-caps", "GLYPH SHAPES", 32, 0, False),
    ("cal-mixed", "Mix type 739", 44, 3, False),
    ("cal-plate", "watch our story", 60, 0, True),
]


@pytest.mark.parametrize("case,text,size,stroke,plate", CALIBRATION_CASES, ids=[c[0] for c in CALIBRATION_CASES])
def test_calibrated_threshold_rejects_held_out_font(tmp_path, font_workspace, case, text, size, stroke, plate):
    rows = [r for r in library.inventory(font_workspace) if r["available"]]
    for row in rows:
        folder = tmp_path / row["id"]
        folder.mkdir()
        video, geometry = measured_fixture(folder, row, text, size, stroke, plate)
        result = fm.match_geometry(video, geometry, font_workspace, font_ids=[r["id"] for r in rows if r != row])
        track = result.tracks[0]
        assert track["status"] == "best substitute", (case, row["id"], track)
        assert track["candidates"][0]["score"] < fm.MATCH_THRESHOLD


@pytest.mark.parametrize("font_id", ["anton", "ibmplexsans"])
def test_real_ocr_geometry_to_font_candidates(tmp_path, font_workspace, font_id):
    pytest.importorskip("rapidocr")
    pytest.importorskip("onnxruntime")
    try:
        caption_models.model_paths()
    except RuntimeError:
        pytest.skip("caption geometry OCR models unavailable; run python -m myzing.study.caption_models --fetch")
    row = next(r for r in library.inventory(font_workspace) if r["id"] == font_id)
    video = render(tmp_path / "media.mp4", draw(row["path"], "CAPTION STYLE", 48, stroke=2))
    geometry = cg.read_geometry(video, .25)
    assert geometry.tracks, geometry.to_dict()
    result = fm.match_geometry(video, geometry, font_workspace)
    assert any(font_id in [c["font_id"] for c in t["candidates"][:3]] for t in result.tracks), result.to_dict()


def test_sparse_seek_returns_exact_frames_across_keyframes(tmp_path, monkeypatch):
    """Seeked B-frame/GOP pixels must agree with an independent sequential decode."""
    import hashlib
    cv2 = pytest.importorskip("cv2")
    pytest.importorskip("PIL.Image")
    video = tmp_path / "seek.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=s=320x240:r=24:d=6", "-an", "-c:v", "libx264", "-g", "48", "-bf", "3",
                    "-pix_fmt", "yuv420p", str(video)], check=True, capture_output=True, timeout=60)
    indices = [0, 35, 48, 73, 120, 143]
    expected = []
    cap = cv2.VideoCapture(str(video))
    try:
        for index in range(indices[-1] + 1):
            ok, pixels = cap.read()
            assert ok
            if index in indices:
                expected.append(hashlib.sha256(pixels.tobytes()).hexdigest())
    finally:
        cap.release()
    detection = cg.Detection("SEEK", .99, [[0, 0], [1, 0], [1, 1], [0, 1]], [0, 0, 1, 1])
    frames = [cg.FrameSample(i / 24, i / 24, 1 / 24, i, 320, 240, [detection]) for i in indices]
    track = cg.CaptionTrack("seek", "SEEK", "caption",
                            [{"sample_index": i, "detection_indices": [0]} for i in range(len(frames))],
                            .1, 1, "center", 1., "static", [], {})
    geometry = cg.CaptionGeometry(6, frames=frames, tracks=[track])
    actual = []
    def observe(pixels, detection):
        actual.append(hashlib.sha256(pixels.tobytes()).hexdigest())
        return None, "decoder pixel probe"
    monkeypatch.setattr(fm, "crop_ink", observe)
    capture = cv2.VideoCapture(str(video))
    reads = []
    seeks = []
    class CountedCapture:
        def isOpened(self):
            return capture.isOpened()

        def set(self, prop, index):
            seeks.append(index)
            return capture.set(prop, index)

        def get(self, prop):
            return capture.get(prop)

        def read(self):
            reads.append(capture.get(cv2.CAP_PROP_POS_FRAMES))
            return capture.read()

        def release(self):
            capture.release()

    monkeypatch.setattr(cv2, "VideoCapture", lambda *args: CountedCapture())
    result = fm.match_geometry(video, geometry, tmp_path)
    assert actual == expected
    assert seeks == reads == indices
    assert [g["frame_index"] for g in result.tracks[0]["gaps"]] == indices
    assert not capture.isOpened()
