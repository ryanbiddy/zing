"""Tests for format-aware measurement parameters (A-Q4): hook window and
OCR sampling adapt to short-form vs long-form by duration; X URLs are a
first-class platform."""

from __future__ import annotations

from myzing.schemas import Breakdown, Shot, VideoMeta, Word
from myzing.study import captions, formats, ingest, report


def test_hook_window_by_duration():
    assert formats.hook_window_s(45.0) == 3.0
    assert formats.hook_window_s(180.0) == 3.0      # boundary: still short-form
    assert formats.hook_window_s(600.0) == 30.0     # YouTube Intro window


def test_body_fps_drops_for_long_form():
    assert formats.body_fps(60.0) == 4.0
    assert formats.body_fps(1200.0) == 2.0


def test_long_form_sample_schedule():
    sched = captions.sample_schedule(120.0 * 60)    # 2h video terminates fine
    dense = [t for t, _ in sched if t < 30.0]
    assert len(dense) == 240                        # 8 fps across full 30s hook
    assert all(step == 0.5 for t, step in sched if t >= 30.0)  # 2 fps body


def test_short_form_schedule_unchanged():
    sched = captions.sample_schedule(5.0)
    assert len([t for t, _ in sched if t < 3.0]) == 24
    assert all(step == 0.25 for t, step in sched if t >= 3.0)


def test_sampling_note_reflects_format():
    assert "0-3s" in captions.sampling_note(45.0)
    long_note = captions.sampling_note(900.0)
    assert "0-30s" in long_note and "2 fps after" in long_note


def test_detect_platform_x_urls():
    assert ingest.detect_platform("https://x.com/user/status/123") == "x"
    assert ingest.detect_platform("https://twitter.com/user/status/123") == "x"
    assert ingest.detect_platform("https://xembed.example.com/v") == "url"


def test_report_uses_long_form_hook_window():
    b = Breakdown(
        meta=VideoMeta(source_url="u", platform="youtube", duration=600.0),
        shots=[Shot(0, 0.0, 600.0)],
        words=[Word("intro", 12.0, 12.4, 0.9), Word("later", 90.0, 90.4, 0.9)],
    )
    md = report.render_markdown(b)
    assert "## First 30 seconds" in md
    assert '"intro"' in md
    assert "later" not in md.split("## Shots")[0]   # outside the intro window
