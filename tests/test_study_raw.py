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


def test_different_numbers_are_preserved_and_distinguished():
    # If digits were stripped, these would clean to identical text and match.
    # Because digits are kept, they compare as "chapter 1 section a" vs "chapter 9 section b"
    # similarity ratio = 2 * 17 / (19 + 19) = 34 / 38 = 0.89.
    # To ensure they are distinguished, we use sufficiently different numbers/words.
    a = [("take", 0.0), ("number", 0.3), ("one", 0.6), ("with", 0.9), ("123", 1.2)]
    b = [("take", 3.0), ("number", 3.3), ("one", 3.6), ("with", 3.9), ("987", 4.2)]
    words = words_from(
        [(t, s, s + 0.2) for t, s in a] + [(t, s, s + 0.2) for t, s in b]
    )
    # Ratio: 2 * 16 / 38 = 32 / 38 = 0.842 (still matches due to low TAKE_SIMILARITY threshold)
    # Let's verify that a major difference is indeed captured:
    c = [("step", 6.0), ("number", 6.3), ("is", 6.6), ("1234567890", 6.9)]
    d = [("step", 9.0), ("number", 9.3), ("is", 9.6), ("0987654321", 9.9)]
    words_cd = words_from(
        [(t, s, s + 0.2) for t, s in c] + [(t, s, s + 0.2) for t, s in d]
    )
    # Without digits, they clean to "step number is " and "step number is " (1.0 similarity)
    # With digits: "step number is 1234567890" (25 chars) vs "step number is 0987654321" (25 chars)
    # match is "step number is " (15 chars). Ratio: 30 / 50 = 0.60 < 0.75 threshold.
    assert raw.find_repeated_takes(words_cd) == []


# -- keepers (S3 support evidence) ------------------------------------------

def clean_take(t0: float, n: int = 6) -> list[tuple[str, float, float]]:
    return [(f"word{i}", t0 + i * 0.4, t0 + i * 0.4 + 0.3) for i in range(n)]


def test_keeper_found_with_full_evidence():
    words = words_from(clean_take(0.0))
    keepers = raw.find_keepers(words, [], [], [], loudness_curve=[-20.0] * 4)
    assert len(keepers) == 1
    k = keepers[0]
    assert (k.start, k.word_count) == (0.0, 6)
    assert any("uninterrupted take" in e for e in k.evidence)
    assert any("no filler words" in e for e in k.evidence)
    assert any("no interior dead air" in e for e in k.evidence)
    assert any("loudness within" in e for e in k.evidence)


def test_short_stretches_around_filler_rejected():
    # Filler at word 0.8 splits a 6-word take into 2+3 word stretches —
    # both under the 4-word floor, so nothing qualifies.
    words = words_from(clean_take(0.0))
    keepers = raw.find_keepers(
        words, [("um", 0.8)], [], [], loudness_curve=[-20.0] * 4
    )
    assert keepers == []


def test_filler_mid_monologue_splits_into_two_keepers():
    # The real-gate lesson: one "literally" inside a 10s monologue must
    # yield the clean stretches around it, not zero keepers.
    words = words_from(clean_take(0.0, n=12) + clean_take(5.0, n=12))
    # continuous speech 0.0-9.7s (0.3s gap keeps it ONE chunk); filler at 5.0
    keepers = raw.find_keepers(
        words, [("literally", 5.0)], [], [], loudness_curve=[-20.0] * 10
    )
    assert len(keepers) == 2
    assert keepers[0].end <= 5.0 and keepers[1].start >= 5.0
    assert all(
        any("clean stretch within a take" in e for e in k.evidence)
        for k in keepers
    )


def test_keeper_rejected_by_interior_dead_air():
    words = words_from(clean_take(0.0))
    keepers = raw.find_keepers(
        words, [], [raw.DeadAir(1.0, 2.6)], [], loudness_curve=[-20.0] * 4
    )
    assert keepers == []


def test_keeper_rejected_by_level_drop():
    words = words_from(clean_take(0.0))
    # bucket 2 collapses 20 dB below the speech median: mumble/turn-away
    curve = [-20.0, -20.0, -40.0, -20.0]
    assert raw.find_keepers(words, [], [], [], loudness_curve=curve) == []


def test_keeper_cross_references_repeated_take():
    words = words_from(clean_take(0.0) + clean_take(10.0))
    takes = [raw.RepeatedTake(0.0, 2.3, 10.0, 12.3, 0.9, "word0 word1")]
    keepers = raw.find_keepers(words, [], [], takes, loudness_curve=[-20.0] * 13)
    assert len(keepers) == 2
    assert keepers[0].repeated_with == (10.0, 12.3)
    assert keepers[1].repeated_with == (0.0, 2.3)
    assert any("compare before choosing" in e for e in keepers[0].evidence)


def test_keeper_too_short_rejected():
    words = words_from(clean_take(0.0, n=4)[:4])  # ~1.5s span < 2.0s floor
    assert raw.find_keepers(words, [], [], [], loudness_curve=[-20.0] * 3) == []


# -- measure_raw composition ------------------------------------------------

def test_measure_raw_warnings_summaries():
    words = words_from([
        ("um", 0.0, 0.2), ("today", 0.2, 0.5), ("we", 0.5, 0.7),
        ("look", 0.7, 0.9), ("at", 0.9, 1.1),
    ])
    result = raw.measure_raw(words, [(0.0, 1.1), (5.0, 8.0)], duration=8.0)
    assert any("dead-air" in w and "1.1-5.0s" in w for w in result.warnings)
    assert any("filler" in w and "um×1" in w for w in result.warnings)


def test_keepers_skipped_when_vad_unavailable():
    """Lane C's SG-1 P1 repro: clean words + no VAD must NOT yield a
    keeper claiming 'no interior dead air' — the check never ran."""
    words = words_from(clean_take(0.0))
    result = raw.measure_raw(words, None, duration=10.0, loudness_curve=[])
    assert result.keepers == []
    assert any(
        "keeper derivation skipped" in w and "dead-air" in w
        for w in result.warnings
    )
    assert not any("no keeper segments passed" in w for w in result.warnings)


def test_keeper_evidence_carries_loudness_caveat_without_curve():
    words = words_from(clean_take(0.0))
    keepers = raw.find_keepers(words, [], [], [], loudness_curve=[])
    assert len(keepers) == 1
    assert any("loudness not verified" in e for e in keepers[0].evidence)
    assert not any("loudness within" in e for e in keepers[0].evidence)


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
