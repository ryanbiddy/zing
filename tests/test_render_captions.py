from __future__ import annotations

from pathlib import Path

import pysubs2
import pytest

from myzing.render.captions import caption_anchor, generate_ass
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
        (200, 800),
        (800, 1400),
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


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (1080, 1920, (472, 1168)),
        (1920, 1080, (960, 918)),
        (1080, 1080, (540, 918)),
    ],
)
def test_caption_anchors_follow_the_output_preset(
    width: int,
    height: int,
    expected: tuple[int, int],
) -> None:
    assert caption_anchor("bottom", width, height) == expected


@pytest.mark.parametrize(
    ("width", "height"),
    [(1080, 1920), (1920, 1080), (1080, 1080)],
)
def test_caption_style_scales_from_the_short_edge(
    tmp_path: Path,
    width: int,
    height: int,
) -> None:
    output = tmp_path / f"{width}x{height}.ass"
    caption = CaptionSpec(
        text="preset",
        start=0.0,
        end=1.0,
        word_timed=False,
    )

    generate_ass([caption], width, height, output)
    subs = pysubs2.load(output, encoding="utf-8")

    assert subs.styles["Caption"].fontsize == 90
