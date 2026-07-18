"""Tests for the breakdown.md renderer (pure function, no mocks needed)."""

from __future__ import annotations

from myzing.schemas import (
    AudioLayout,
    Breakdown,
    CaptionEvent,
    Shot,
    VideoMeta,
    Word,
)
from myzing.study import report


def sample() -> Breakdown:
    return Breakdown(
        meta=VideoMeta(
            source_url="https://www.tiktok.com/@cleo/video/1",
            platform="tiktok",
            author="cleo",
            title="why ice",
            duration=21.0,
            width=1080,
            height=1920,
            fps=30.0,
            media_path="media.mp4",
        ),
        shots=[
            Shot(0, 0.0, 1.4, keyframe="frames/shot_000.jpg"),
            Shot(1, 1.4, 3.05),
            Shot(2, 3.05, 21.0),
        ],
        words=[
            Word("stop", 0.1, 0.32, 0.99),
            Word("scrolling", 0.32, 0.8, 0.98),
            Word("later", 4.0, 4.4, 0.3),
        ],
        captions=[
            CaptionEvent("STOP SCROLLING", 0.0, 0.9, "lower", True, 2, 0.93),
            CaptionEvent("WATCH", 4.0, 5.0, "lower", True, 1, 0.88),
        ],
        audio=AudioLayout(True, 0.7, True, 0.72, [-14.0, -13.2, -20.5]),
        avg_shot_duration=7.0,
        cuts_per_10s=[2.0, 0.0, 0.0],
        warnings=["caption OCR sampled at 8 fps in 0-3s"],
    )


def test_render_contains_all_sections():
    md = report.render_markdown(sample())
    assert "# Edit breakdown — why ice" in md
    assert "author: cleo" in md
    assert "## Pacing" in md and "3 shots, 2 cuts" in md
    assert "densest window: 0-10s" in md
    assert "## First 3 seconds" in md
    assert '"stop scrolling"' in md          # only words inside window
    assert "later" not in md.split("## Shots")[0]
    assert '| 0 | 0.00 | 1.40 | 1.40s | frames/shot_000.jpg |' in md
    assert "STOP SCROLLING" in md
    assert "ALL CAPS" in md
    assert "speech: 72% of runtime" in md
    assert "music bed: yes (confidence 0.70)" in md
    assert "1 low-confidence" in md
    assert "## Measurement notes" in md
    assert "8 fps" in md


def test_render_empty_breakdown_is_honest():
    b = Breakdown(
        meta=VideoMeta(source_url="file.mp4", platform="file", duration=10.0),
        warnings=["shot detection skipped: scenedetect not installed"],
    )
    md = report.render_markdown(b)
    assert "(no shot data — see warnings)" in md
    assert "(nothing transcribed in this window)" in md
    assert "(no on-screen text observed" in md
    assert "no meaningful speech" in md
    assert "scenedetect not installed" in md


def test_render_roundtrips_through_schema_json():
    b = Breakdown.from_json(sample().to_json())
    assert report.render_markdown(b) == report.render_markdown(sample())
