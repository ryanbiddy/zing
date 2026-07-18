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
