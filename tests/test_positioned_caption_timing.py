"""Exact output-frame scheduling, independent of FFmpeg and font metrics."""

from fractions import Fraction

import pytest

from myzing.composition import frame_time
from myzing.project.models import Rational
from myzing.render.composition import prepare_composition
from myzing.render.positioned_captions import caption_frame_timing, frame_centisecond
from myzing.render.validation import EDLValidationError
from myzing.schemas import Word
from test_render_composition import caption, plan


RATES = [Rational(24, 1), Rational(25, 1), Rational(30, 1),
         Rational(30000, 1001), Rational(60, 1), Rational(100, 1)]
SHORT_WORDS = [Word(text, start, end) for text, start, end in [
    ("A", .201, .232), ("B", .501, .511), ("C", .511, .521), ("D", .521, .531),
    ("E", 1.01, 1.03), ("F", 1.80, 1.84), ("G", 1.84, 1.85), ("H", 2.901, 2.911),
]]
# Explicit frame expectations include both reported regressions, three words
# sharing a frame, adjacent words, 10/20/31/40ms durations and phrase extension.
WORD_FRAMES = [
    [(5, 6), (13, 14), (14, 15), (15, 16), (25, 26), (44, 45), (45, 46), (70, 71)],
    [(6, 7), (13, 14), (14, 15), (15, 16), (26, 27), (45, 46), (46, 47), (73, 74)],
    [(7, 8), (16, 17), (17, 18), (18, 19), (31, 32), (54, 56), (56, 57), (88, 89)],
    [(7, 8), (16, 17), (17, 18), (18, 19), (31, 32), (54, 56), (56, 57), (87, 88)],
    [(13, 14), (31, 32), (32, 33), (33, 34), (61, 62), (108, 111), (111, 112), (175, 176)],
    [(21, 24), (51, 52), (52, 53), (53, 54), (101, 103), (180, 184), (184, 185), (291, 292)],
]


@pytest.mark.parametrize("fps", RATES)
def test_ass_boundaries_select_exactly_the_requested_frame(fps):
    previous_cs = -1
    for index in [*range(3001), 100_001, 1_000_001, 10_000_001]:
        cs = frame_centisecond(index, fps)
        assert cs > previous_cs
        assert Fraction(cs, 100) <= frame_time(index, fps)
        if index:
            assert frame_time(index - 1, fps) < Fraction(cs, 100)
            # This is the earliest representable boundary after frame index-1.
            assert Fraction(cs - 1, 100) <= frame_time(index - 1, fps)
        previous_cs = cs


@pytest.mark.parametrize(("fps", "expected"), list(zip(RATES, WORD_FRAMES)))
def test_short_words_get_ordered_minimal_exclusive_frames(fps, expected):
    event = caption(text="A B C D E F G H", end=2.911, word_timed=True, words=SHORT_WORDS, layout=None)
    before = event.to_dict()
    first, last, words, warnings = caption_frame_timing(event, fps, 300)
    assert words == expected
    assert first == 0 and last == expected[-1][1]
    assert all(a < b for a, b in words)
    assert all(a[1] <= b[0] for a, b in zip(words, words[1:]))
    assert any("word 1 'A' render timing 0.201-0.232s" in w for w in warnings)
    assert event.to_dict() == before


@pytest.mark.parametrize("fps", RATES)
def test_whole_short_phrase_extends_to_keep_all_words(fps):
    event = caption(text="A B C", start=.001, end=.031, word_timed=True, layout=None,
                    words=[Word("A", .001, .011), Word("B", .011, .021), Word("C", .021, .031)])
    first, last, words, warnings = caption_frame_timing(event, fps, 300)
    # At <=60fps these starts collide; at 100fps they already occupy 1,2,3.
    assert (first, last, words) == (1, 4, [(1, 2), (2, 3), (3, 4)])
    assert any("render window 0.001-0.031s -> frames [1, 4)" in w for w in warnings)


def test_aligned_timing_is_not_adjusted_or_warned():
    event = caption(word_timed=True, words=[Word("ONE", 0, 1), Word("TWO", 1, 2)])
    assert caption_frame_timing(event, Rational(30, 1), 90) == (0, 60, [(0, 30), (30, 60)], [])


def test_partial_video_tail_keeps_available_frames_and_reports_clipping():
    event = caption(text="A", start=.9, end=1.01, word_timed=True,
                    words=[Word("A", .9, 1.01)], layout=None)
    first, last, words, warnings = caption_frame_timing(event, Rational(30, 1), 30)
    assert (first, last, words) == (27, 30, [(27, 30)])
    assert any("word 1 'A'" in w and "frames [27, 30)" in w for w in warnings)
    assert any("clip to video end" in w for w in warnings)


def test_collisions_do_not_shift_a_later_word_after_a_sufficient_gap():
    event = caption(text="A B C", word_timed=True,
                    words=[Word("A", .201, .211), Word("B", .211, .221), Word("C", 1, 1.5)])
    assert caption_frame_timing(event, Rational(30, 1), 90)[2] == [(7, 8), (8, 9), (30, 45)]


def test_unrepresentable_tail_fails_before_io_instead_of_dropping_words(tmp_path, monkeypatch):
    event = caption(text="A B C", start=2.95, end=3, word_timed=True, layout=None,
                    words=[Word("A", 2.95, 2.96), Word("B", 2.96, 2.97), Word("C", 2.97, 3)])
    c = plan(tmp_path, captions=[event])
    monkeypatch.setattr("myzing.render.composition._path", lambda *a: pytest.fail("asset IO began"))
    with pytest.raises(EDLValidationError, match="extend the video or move the caption earlier"):
        prepare_composition(c, tmp_path)


def test_render_adjustments_reach_prepared_warnings_without_rewriting_provenance(tmp_path):
    event = caption(text="A B", word_timed=True, words=[
        Word("A", .201, .211, timing={"version": 1, "status": "measured", "method": "fixture",
             "original": {"start": .201, "end": .211}, "adjustments": []}),
        Word("B", .211, .221),
    ])
    c = plan(tmp_path, captions=[event])
    before = c.to_json()
    prepared = prepare_composition(c, tmp_path)
    assert any("word 2 'B'" in w and "frames [8, 9)" in w for w in prepared.warnings)
    assert c.to_json() == prepared.composition.to_json() == before
