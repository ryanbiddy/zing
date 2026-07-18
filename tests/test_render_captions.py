from __future__ import annotations

from pathlib import Path

import pysubs2

from myzing.render.captions import (
    SAFE_BOX_1080X1920,
    caption_anchor,
    generate_ass,
)
from myzing.schemas import CaptionSpec, Word


def test_word_timed_ass_uses_pysubs2_karaoke_and_pop_tags(
    tmp_path: Path,
) -> None:
    output = tmp_path / "creator's captions.ass"
    captions = [
        CaptionSpec(
            text="hello zing",
            start=0.2,
            end=1.4,
            position="lower",
            words=[
                Word("hello", 0.2, 0.7),
                Word("zing", 0.8, 1.3),
            ],
        )
    ]

    generate_ass(captions, 1080, 1920, output)
    subs = pysubs2.load(output, encoding="utf-8")

    assert subs.info["PlayResX"] == "1080"
    assert subs.info["PlayResY"] == "1920"
    assert len(subs.events) == 2
    assert [(event.start, event.end) for event in subs.events] == [
        (200, 700),
        (800, 1300),
    ]
    assert all(event.style == "Karaoke" for event in subs.events)
    assert all(r"\kf50" in event.text for event in subs.events)
    assert all(r"\t(" in event.text for event in subs.events)
    assert [event.plaintext for event in subs.events] == ["HELLO", "ZING"]


def test_static_ass_preserves_line_break_and_case_choice(tmp_path: Path) -> None:
    output = tmp_path / "captions.ass"
    caption = CaptionSpec(
        text="First line\nSecond line",
        start=0.0,
        end=1.0,
        position="top",
        all_caps=False,
        word_timed=False,
    )

    generate_ass([caption], 540, 960, output)
    subs = pysubs2.load(output, encoding="utf-8")

    assert len(subs.events) == 1
    assert subs.events[0].start == 0
    assert subs.events[0].end == 1000
    assert r"\N" in subs.events[0].text
    assert subs.events[0].plaintext == "First line\nSecond line"


def test_all_caption_anchors_stay_in_scaled_universal_safe_box() -> None:
    left, top, right, bottom = SAFE_BOX_1080X1920

    for position in ("top", "center", "lower", "bottom"):
        x, y = caption_anchor(position, 1080, 1920)
        assert left <= x <= right
        assert top <= y <= bottom
