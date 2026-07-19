"""Tests for raw-footage measurement (A-Q12): dead air, fillers,
repeated takes — pure functions over synthetic words/segments."""

from __future__ import annotations

from myzing.schemas import Word
from myzing.study import raw


def words_from(spec: list[tuple[str, float, float]]) -> list[Word]:
    return [Word(text, start, end, 0.9) for text, start, end in spec]


# -- dead air ---------------------------------------------------------------

def test_dead_air_includes_leading_middle_and_trailing():
    segments = [(2.0, 5.0), (5.2, 8.0)]     # 0-2 leading, 8-12 trailing
    spans = raw.dead_air_spans(segments, duration=12.0)
    assert [(s.start, s.end) for s in spans] == [(0.0, 2.0), (8.0, 12.0)]


def test_dead_air_ignores_short_gaps():
    segments = [(0.0, 3.0), (4.0, 8.0)]     # 1.0s gap < 1.5s threshold
    assert raw.dead_air_spans(segments, duration=8.0) == []


def test_dead_air_mid_gap_detected():
    segments = [(0.0, 3.0), (6.5, 10.0)]
    spans = raw.dead_air_spans(segments, duration=10.0)
    assert [(s.start, s.end) for s in spans] == [(3.0, 6.5)]
    assert spans[0].duration == 3.5


# -- fillers ----------------------------------------------------------------

def test_fillers_counted_with_locations():
    words = words_from([
        ("Um,", 0.0, 0.2), ("so", 0.2, 0.4), ("I", 0.4, 0.5),
        ("like", 0.5, 0.7), ("went", 0.7, 0.9), ("you", 1.0, 1.1),
        ("know,", 1.1, 1.3), ("there", 1.3, 1.5), ("uh", 1.5, 1.6),
    ])
    counts, locations = raw.find_fillers(words)
    assert counts == {"um": 1, "like": 1, "you know": 1, "uh": 1}
    assert ("you know", 1.0) in locations
    assert ("so", 0.2) not in locations     # "so" is not in the lexicon


def test_filler_bigram_consumes_both_words():
    words = words_from([("you", 0.0, 0.1), ("know", 0.1, 0.2)])
    counts, _ = raw.find_fillers(words)
    assert counts == {"you know": 1}        # not also counted singly


# -- repeated takes ---------------------------------------------------------

def test_repeated_take_detected_across_pause():
    take = [("today", 0.0), ("we", 0.4), ("look", 0.7), ("at", 0.9),
            ("the", 1.1), ("watch", 1.4)]
    retake = [("today", 4.0), ("we", 4.4), ("look", 4.7), ("at", 4.9),
              ("the", 5.1), ("watches", 5.4)]
    words = words_from(
        [(t, s, s + 0.2) for t, s in take]
        + [(t, s, s + 0.2) for t, s in retake]
    )
    takes = raw.find_repeated_takes(words)
    assert len(takes) == 1
    t = takes[0]
    assert t.similarity >= 0.75
    assert (t.first_start, t.second_start) == (0.0, 4.0)
    assert "watch" in t.text


def test_different_sentences_are_not_takes():
    a = [("the", 0.0), ("quick", 0.3), ("brown", 0.6), ("fox", 0.9)]
    b = [("completely", 3.0), ("unrelated", 3.4), ("words", 3.8), ("here", 4.2)]
    words = words_from(
        [(t, s, s + 0.2) for t, s in a] + [(t, s, s + 0.2) for t, s in b]
    )
    assert raw.find_repeated_takes(words) == []


def test_short_chunks_ignored():
    words = words_from([
        ("hello", 0.0, 0.2), ("there", 0.2, 0.4),
        ("hello", 3.0, 3.2), ("there", 3.2, 3.4),
    ])
    assert raw.find_repeated_takes(words) == []  # < 4-word chunks


# -- measure_raw composition ------------------------------------------------

def test_measure_raw_warnings_summaries():
    words = words_from([
        ("um", 0.0, 0.2), ("today", 0.2, 0.5), ("we", 0.5, 0.7),
        ("look", 0.7, 0.9), ("at", 0.9, 1.1),
    ])
    result = raw.measure_raw(words, [(0.0, 1.1), (5.0, 8.0)], duration=8.0)
    assert any("dead-air" in w and "1.1-5.0s" in w for w in result.warnings)
    assert any("filler" in w and "um×1" in w for w in result.warnings)


def test_measure_raw_honest_when_vad_missing():
    result = raw.measure_raw([], None, duration=10.0)
    assert any("dead-air measurement skipped" in w for w in result.warnings)
    assert any("no transcript" in w for w in result.warnings)
    assert result.dead_air == [] and result.repeated_takes == []


def test_study_wires_raw_mode(zing_workspace, monkeypatch):
    from tests.test_study_api import SOURCE, wire_stages
    from myzing.study import api

    wire_stages(monkeypatch)
    b = api.study(SOURCE, raw_mode=True)
    assert "raw_mode" in b.provenance
    assert b.provenance["raw_mode"]["dead_air_min_s"] == raw.DEAD_AIR_MIN_S

    b2 = api.study(SOURCE)
    assert "raw_mode" not in b2.provenance   # strictly opt-in
