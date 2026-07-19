"""Offline tests for caption OCR: rapidocr/cv2 are mocked at the three
seams (_engine/_iter_frames/_ocr plus the _changed gate); clustering and
scheduling logic is tested directly. No numpy, no decoding, no models."""

from __future__ import annotations

from pathlib import Path

import pytest

from myzing.study import captions
from myzing.study.captions import Line, Observation


def obs(t, text, step=0.125, y=0.6, score=0.9):
    lines = [Line(text=text, score=score, y_center=y)] if text else []
    return Observation(t=t, step=step, lines=lines)


# -- sampling schedule ------------------------------------------------------

def test_sample_schedule_dense_hook_then_sparse():
    sched = captions.sample_schedule(5.0)
    hook = [t for t, _ in sched if t < 3.0]
    body = [t for t, _ in sched if t >= 3.0]
    assert len(hook) == 24            # 8 fps over 3s
    assert len(body) == 8             # 4 fps over remaining 2s
    assert sched[0] == (0.0, 0.125)
    assert all(step == 0.25 for t, step in sched if t >= 3.0)


# -- clustering -------------------------------------------------------------

def test_growing_pop_caption_is_one_event_keeping_longest():
    events = captions.cluster([
        obs(0.0, "STOP"),
        obs(0.125, "STOP SCROLLING"),
        obs(0.25, "STOP SCROLLING NOW"),
    ])
    assert len(events) == 1
    e = events[0]
    assert e.text == "STOP SCROLLING NOW"
    assert e.start == 0.0
    assert e.end == 0.375             # last t + its step
    assert e.words_visible == 2       # median of 1,2,3 words on screen
    assert e.all_caps is True


def test_word_replace_style_yields_one_event_per_word():
    events = captions.cluster([
        obs(0.0, "STOP"),
        obs(0.125, "SCROLLING"),
        obs(0.25, "NOW"),
    ])
    assert [e.text for e in events] == ["STOP", "SCROLLING", "NOW"]
    assert all(e.words_visible == 1 for e in events)


def test_ocr_flicker_gap_does_not_split_event():
    events = captions.cluster([
        obs(0.0, "hello world"),
        obs(0.125, "hello world"),
        obs(0.25, ""),                # OCR missed one frame
        obs(0.375, "hello world"),
    ])
    assert len(events) == 1
    assert events[0].end == 0.5


def test_long_gap_splits_event():
    events = captions.cluster([
        obs(0.0, "hello world"),
        obs(0.25, ""),
        obs(0.5, ""),
        obs(0.75, ""),
        obs(1.0, "hello world"),
    ])
    assert len(events) == 2


def test_different_text_closes_event():
    events = captions.cluster([
        obs(0.0, "first caption here"),
        obs(0.125, "completely different words"),
    ])
    assert len(events) == 2


def test_event_style_observations():
    events = captions.cluster([
        Observation(t=0.0, step=0.125, lines=[
            Line("lower text", 0.8, y_center=0.6),
        ]),
        Observation(t=0.125, step=0.125, lines=[
            Line("lower text", 0.9, y_center=0.62),
        ]),
    ])
    (e,) = events
    assert e.position == "lower"
    assert e.confidence == pytest.approx(0.85, abs=1e-3)
    assert e.all_caps is False


@pytest.mark.parametrize("y,bucket", [
    (0.1, "top"), (0.4, "center"), (0.6, "lower"), (0.9, "bottom"),
])
def test_position_buckets(y, bucket):
    assert captions._position_bucket(y) == bucket


# -- region tracking (A-Q8) -------------------------------------------------

def frame(t, *line_specs, step=0.25):
    """line_specs: (text, y) or (text, y, x)."""
    lines = [
        Line(text=s[0], score=0.9, y_center=s[1], x_center=s[2] if len(s) > 2 else 0.5)
        for s in line_specs
    ]
    return Observation(t=t, step=step, lines=lines)


def test_concurrent_regions_become_separate_events():
    # A watermark at the top and a caption lower on screen, same frames:
    # one event per region, never a concatenated "WATERMARK CAPTION" event.
    frames = [
        frame(0.0, ("MetalWood", 0.1), ("HELLO WORLD", 0.6)),
        frame(0.25, ("MetalWood", 0.1), ("HELLO WORLD", 0.6)),
        frame(0.5, ("MetalWood", 0.1), ("NEXT CAPTION", 0.6)),
    ]
    events, notes = captions.cluster_regions(frames, duration=10.0)
    texts = [e.text for e in events]
    assert "HELLO WORLD" in texts and "NEXT CAPTION" in texts
    assert "MetalWood" in texts          # short video: not yet overlay-length
    assert not any("MetalWood HELLO" in t for t in texts)
    assert notes == []


def test_two_line_caption_is_one_region():
    frames = [
        frame(0.0, ("stop scrolling", 0.60), ("right now", 0.65)),
        frame(0.25, ("stop scrolling", 0.60), ("right now", 0.65)),
    ]
    events, _ = captions.cluster_regions(frames, duration=10.0)
    assert len(events) == 1
    assert events[0].text == "stop scrolling right now"


def test_persistent_overlay_excluded_with_warning():
    # Static label across 20s of a 30s video -> overlay note, not a caption.
    frames = [
        frame(t * 0.25, ("Raw Video Preview:", 0.05), ("real caption" if t % 8 < 4 else "other words", 0.6))
        for t in range(80)
    ]
    events, notes = captions.cluster_regions(frames, duration=30.0)
    assert all("Raw Video Preview" not in e.text for e in events)
    assert any("Raw Video Preview" in n and "excluded from captions" in n for n in notes)
    assert any("real caption" in e.text for e in events)


def test_overlay_threshold_scales_with_long_form():
    assert captions._overlay_threshold_s(40.0) == 15.0
    assert captions._overlay_threshold_s(600.0) == 150.0


def test_box_order_flicker_is_one_event():
    # Multi-box scene text whose OCR box order alternates between samples
    # must not shatter into per-sample events.
    frames = [
        frame(0.0, ("WHITE DESERT ANTARCTICA", 0.4)),
        frame(0.25, ("ANTARCTICA WHITE DESERT", 0.4)),
        frame(0.5, ("WHITE DESERT ANTARCTICA", 0.4)),
    ]
    events, _ = captions.cluster_regions(frames, duration=10.0)
    assert len(events) == 1


def test_region_jitter_stays_one_track():
    # Slight vertical wobble must not split a region into multiple tracks.
    frames = [frame(t * 0.25, ("bouncy caption", 0.60 + 0.02 * (t % 2)), step=0.25) for t in range(8)]
    tracks = captions.track_regions(frames)
    assert len(tracks) == 1


def test_reading_order_is_row_major_not_y_jitter():
    # Word boxes on ONE caption line jitter a few pixels vertically; the
    # join must keep left-to-right order within the row band, and rows
    # stay top-to-bottom.
    o = Observation(t=0.0, step=0.125, lines=[
        Line("CUTS", 0.9, y_center=0.601, x_center=0.7),
        Line("QUICK", 0.9, y_center=0.612, x_center=0.3),
        Line("headline", 0.9, y_center=0.2, x_center=0.5),
    ])
    assert o.text == "headline QUICK CUTS"


# -- read_captions with mocked seams ----------------------------------------

def wire(monkeypatch, frames, ocr_map, changed=None):
    monkeypatch.setattr(captions, "_engine", lambda: ("ENGINE", "3.9.1"))
    monkeypatch.setattr(
        captions, "_iter_frames", lambda p, d: iter(frames)
    )
    monkeypatch.setattr(
        captions, "_changed", changed or (lambda a, b: a != b)
    )
    calls = []

    def fake_ocr(engine, frame):
        calls.append(frame)
        return ocr_map[frame]
    monkeypatch.setattr(captions, "_ocr", fake_ocr)
    return calls


def test_read_captions_end_to_end(monkeypatch):
    frames = [(0.0, 0.125, "f0"), (0.125, 0.125, "f0"), (0.25, 0.125, "f1")]
    line = [Line("STOP", 0.9, 0.6)]
    calls = wire(monkeypatch, frames, {"f0": line, "f1": []})

    result = captions.read_captions(Path("media.mp4"), duration=0.5)

    # Unchanged second frame reused the first OCR result: only 2 real calls.
    assert calls == ["f0", "f1"]
    assert len(result.captions) == 1
    assert result.captions[0].text == "STOP"
    assert result.provenance["ocr_backend"] == "rapidocr-3.9.1"
    assert any("sampled at 8 fps" in w for w in result.warnings)


def test_read_captions_missing_backend_is_honest_skip(monkeypatch):
    def raises():
        raise ImportError("No module named 'rapidocr'")
    monkeypatch.setattr(captions, "_engine", raises)

    result = captions.read_captions(Path("m.mp4"), duration=10.0)

    assert result.captions == []
    assert any("myzing[study]" in w for w in result.warnings)


def test_read_captions_frame_ocr_error_warns(monkeypatch):
    frames = [(0.0, 0.125, "f0")]
    monkeypatch.setattr(captions, "_engine", lambda: ("ENGINE", "3.9.1"))
    monkeypatch.setattr(captions, "_iter_frames", lambda p, d: iter(frames))

    def boom(engine, frame):
        raise RuntimeError("onnx session died")
    monkeypatch.setattr(captions, "_ocr", boom)

    result = captions.read_captions(Path("m.mp4"), duration=1.0)

    assert result.captions == []
    assert any("failed to OCR" in w for w in result.warnings)


def test_read_captions_zero_duration_skips(monkeypatch):
    result = captions.read_captions(Path("m.mp4"), duration=0.0)
    assert result.captions == []
    assert any("unknown duration" in w for w in result.warnings)


# -- F-08: rapidocr returning no confidence scores must be loud --------------

NO_SCORES_WARNING = "OCR backend returned no confidence scores; captions skipped"

BOX = [(100, 1500), (500, 1500), (500, 1600), (100, 1600)]


class FakeOcrOut:
    """Shape of a rapidocr result object, minus whatever a future API drops."""

    def __init__(self, boxes=None, txts=None, scores=None):
        self.boxes = boxes
        self.txts = txts
        self.scores = scores


class FakeFrame:
    shape = (1920, 1080, 3)


def wire_engine(monkeypatch, out):
    """Wire read_captions through the REAL _ocr adapter with a fake engine."""
    monkeypatch.setattr(captions, "_engine", lambda: (lambda frame: out, "9.9.9"))
    monkeypatch.setattr(
        captions, "_iter_frames", lambda p, d: iter([(0.0, 0.125, FakeFrame())])
    )


def test_no_scores_api_drift_warns_instead_of_silent_zero(monkeypatch):
    """rapidocr returns text but scores=None: every line must NOT be scored
    0.0 and dropped in silence — one honest warning, captions skipped."""
    wire_engine(monkeypatch, FakeOcrOut(boxes=[BOX], txts=["STOP"], scores=None))

    result = captions.read_captions(Path("m.mp4"), duration=1.0)

    assert result.captions == []
    assert any(NO_SCORES_WARNING in w for w in result.warnings)
    # This is API drift, not a per-frame OCR crash — don't misreport it.
    assert not any("failed to OCR" in w for w in result.warnings)


def test_scores_length_mismatch_is_treated_as_no_scores(monkeypatch):
    """A scores list that doesn't cover every line is the same API drift;
    zip() must not silently truncate lines."""
    wire_engine(
        monkeypatch,
        FakeOcrOut(boxes=[BOX, BOX], txts=["STOP", "SCROLLING"], scores=[0.9]),
    )

    result = captions.read_captions(Path("m.mp4"), duration=1.0)

    assert result.captions == []
    assert any(NO_SCORES_WARNING in w for w in result.warnings)


def test_ocr_raises_dedicated_no_scores_error():
    out = FakeOcrOut(boxes=[BOX], txts=["STOP"], scores=None)
    with pytest.raises(captions.OcrNoScores):
        captions._ocr(lambda frame: out, FakeFrame())


def test_empty_frame_without_scores_is_not_drift():
    """No text at all (txts empty, scores None) is a normal empty frame."""
    out = FakeOcrOut(boxes=[], txts=[], scores=None)
    assert captions._ocr(lambda frame: out, FakeFrame()) == []


def test_valid_scores_still_flow_through_real_ocr_adapter(monkeypatch):
    wire_engine(
        monkeypatch, FakeOcrOut(boxes=[BOX], txts=["hello world"], scores=[0.9])
    )

    result = captions.read_captions(Path("m.mp4"), duration=1.0)

    assert [c.text for c in result.captions] == ["hello world"]
    assert result.captions[0].position == "bottom"
    assert not any(NO_SCORES_WARNING in w for w in result.warnings)


def test_engine_start_failure_is_honest_skip(monkeypatch):
    def boom():
        raise RuntimeError("onnxruntime DLL load failed")
    monkeypatch.setattr(captions, "_engine", boom)

    result = captions.read_captions(Path("m.mp4"), duration=1.0)

    assert result.captions == []
    assert any("backend failed to start" in w for w in result.warnings)


def test_frame_read_crash_midway_is_honest_skip(monkeypatch):
    monkeypatch.setattr(captions, "_engine", lambda: ("E", "3.9.1"))

    def frames(path, duration):
        yield 0.0, 0.125, "f0"
        raise RuntimeError("decoder desync at frame 1")
    monkeypatch.setattr(captions, "_iter_frames", frames)
    monkeypatch.setattr(captions, "_ocr", lambda e, f: [])
    monkeypatch.setattr(captions, "_changed", lambda a, b: True)

    result = captions.read_captions(Path("m.mp4"), duration=1.0)

    assert result.captions == []
    assert any("failed while reading frames" in w for w in result.warnings)


def test_same_event_rejects_empty_normalizations():
    assert captions._same_event("   ", "STOP") is False  # nothing left of a
    assert captions._same_event("STOP", "") is False


def test_flicker_gap_between_same_text_closes_event():
    gap = captions.MAX_FLICKER_GAP_S
    events = captions.cluster([
        obs(0.0, "STOP"),
        obs(0.25, "STOP"),
        obs(0.25 + gap + 0.6, "STOP"),   # same text, but too late
    ])
    assert len(events) == 2


def test_ocr_missing_boxes_or_txts_is_empty():
    assert captions._ocr(
        lambda frame: FakeOcrOut(boxes=None, txts=None, scores=None),
        FakeFrame(),
    ) == []


def test_ocr_drops_blank_and_low_confidence_lines():
    out = FakeOcrOut(
        boxes=[BOX, BOX, BOX],
        txts=["  ", "faint", "KEEP"],
        scores=[0.99, captions.CONF_THRESHOLD - 0.01, 0.9],
    )
    lines = captions._ocr(lambda frame: out, FakeFrame())
    assert [ln.text for ln in lines] == ["KEEP"]
