"""Rule boundaries and provenance use authored ASR, never downloaded models."""

import json
from pathlib import Path

import pytest

from myzing.director.asr_repair import repair_words
from myzing.director.continuity import Clause, clauses, dangling, score
from myzing.director.inventory import inventory
from myzing.director.models import ClipStudy
from myzing.director.selection import Candidate, shot_lengths
from myzing.match.evidence import group_disclosures, report
from myzing.schemas import Breakdown, CaptionEvent, Shot, VideoMeta, Word
from myzing.style_recipe import build_style_recipe
from myzing.study.text_roles import TextRole, caption_geometry, classify_text
from myzing.timing import prepare_words, transform_word
from tools.plan_examples import example_project, write_json


def words(text, start=0., step=.2):
    return [Word(t, start + i * step, start + i * step + .15) for i, t in enumerate(text.split())]


@pytest.mark.parametrize("text", ["Know where you", "We already", "there's no reason to", "When there's danger,", "If there is a warning,", "And a dick,"])
def test_dangling_endings_are_not_complete(text):
    assert dangling(text)
    assert not clauses(words(text))[-1].complete


def test_pause_only_boundary_and_dependent_prefix_stays_attached():
    w = words("We finished") + words("Go home", start=2) + words("When danger comes, stay calm.", start=4)
    result = clauses(w)
    assert [c.text for c in result] == ["We finished", "Go home", "When danger comes, stay calm."]
    assert result[0].boundary == "pause" and all(c.complete for c in result)
    assert Clause.from_dict(result[0].to_dict()) == result[0]


def test_object_pronoun_is_complete_but_unfinished_pronoun_is_not():
    assert not dangling("Ask an older person to help you.")
    assert dangling("Know where you")


@pytest.mark.parametrize("bad", [(1., 1.), (1.2, .9), (-1., 1.), (float("nan"), 1.)])
def test_interpolation_preserves_originals_and_mapping_provenance(bad):
    source = [Word("Before", .1, .5), Word("bad", *bad), Word("after.", 1.5, 1.8)]
    before = repr(source)
    fixed, ledger = repair_words(source, 2)
    assert repr(source) == before
    assert ledger["repairs"][0]["repaired"] is True
    assert fixed[0].start == .1 and fixed[-1].end == 1.8
    assert .5 <= fixed[1].start < fixed[1].end <= 1.5
    mapped = transform_word(fixed[1], 3, 4, "timeline_mapping", corrected=False)
    assert mapped.timing["original"] == fixed[1].timing["original"]
    assert mapped.timing["repaired"] is True
    assert mapped.timing["adjustments"][0]["repaired"] is True
    prepare_words(fixed, 2, repair=False)
    with pytest.raises(ValueError):
        repair_words(source, 2, enabled=False)


def test_packed_zero_words_reflow_only_bounded_neighbors():
    source = [Word("left", 0, .4), Word("zero", .4, .4), Word("right", .4, .9), Word("untouched", 2, 3)]
    fixed, ledger = repair_words(source, 3)
    assert len(ledger["repairs"]) == 3
    assert all(r["repaired"] for r in ledger["repairs"])
    assert fixed[3].start == 2 and fixed[3].end == 3
    assert fixed[0].start == 0 and fixed[2].end == .9


def test_large_gap_and_too_many_words_quarantine_only_span():
    source = [Word("good.", 0, 1), Word("bad", 3, 3), Word("good.", 8, 9)]
    fixed, ledger = repair_words(source, 10)
    assert [w.text for w in fixed] == ["good.", "good."]
    assert ledger["quarantined"][0]["start"] == 1
    assert ledger["quarantined"][0]["end"] == 8
    _, ledger = repair_words([Word("left", 0, .2), *[Word("bad", .5, .5) for _ in range(13)], Word("right", 1, 1.2)], 2)
    assert len(ledger["quarantined"][0]["word_indices"]) == 13


def test_inventory_raw_bytes_and_explicit_opt_out(tmp_path, zing_workspace):
    root, _, _ = example_project(tmp_path / "project")
    path = root / "breakdowns/take-0/breakdown.json"
    b = json.loads(path.read_text())
    b["words"][1]["end"] = b["words"][1]["start"]
    write_json(path, b)
    raw = path.read_bytes()
    clips, _ = inventory(root)
    assert clips[0].status == "ready" and clips[0].asr_repair["repairs"]
    assert "ASR repair" in " ".join(clips[0].warnings)
    strict, _ = inventory(root, repair_asr=False)
    assert strict[0].status == "needs_study"
    assert path.read_bytes() == raw
    with pytest.raises(ValueError, match="zero duration"):
        prepare_words(Breakdown.from_dict(b).words, 8, repair=False)
    from myzing.inspect import InspectionError
    from myzing.inspect.timing import validate_words
    with pytest.raises(InspectionError, match="invalid timing"):
        validate_words(Breakdown.from_dict(b).words, 8)


def test_continuity_score_detects_partial_and_out_of_order():
    w = words("We arrived.") + words("Stay here.", start=2)
    clip = ClipStudy("a", "a.mp4", "a" * 64, 4, "ready", words=w, shots=[Shot(0, 0, 4)])
    def c(a, b):
        return Candidate("a", clip.sha256, a, b, 0, 2, 0, "", False, False)
    good = score([c(0, .35), c(2, 2.35)], [clip])
    assert good["score"] == 1 and good["complete_clauses"] == 2
    bad = score([c(2, 2.35), c(0, .15)], [clip])
    assert bad["source_order_violations"] == bad["partial_clauses"] == bad["dangling_endings"] == 1
    assert bad["score"] < 1 and bad["status"] == "flagged"
    assert score([c(2, 2.35), c(0, .35)], [clip], allow_reordering=True)["status"] == "pass"


def test_decoded_audio_tail_does_not_exclude_repaired_clip(tmp_path, zing_workspace):
    from myzing.audio.models import AudioMap, Loudness, Segment, Tempo
    root, _, _ = example_project(tmp_path / "project")
    path = root / "breakdowns/take-0/audio-map.json"
    audio = AudioMap(str(root / "clips/take-0.mp4"), 8.024, 48000, 60, False, Tempo(), [], [],
                     [Segment(7.9, 8.024, "silence", 1, "decoded audio tail")], Loudness(None, None, None))
    write_json(path, audio.to_dict())
    original = path.read_bytes()
    clips, _ = inventory(root)
    assert clips[0].status == "ready"
    assert clips[0].dead_air[-1]["end"] == 8
    assert clips[0].dead_air[-1]["original"]["end"] == 8.024
    assert path.read_bytes() == original


def test_internal_source_cuts_cannot_be_hidden_by_pixel_detector():
    from myzing.composition import Composition
    from myzing.director.plans import REPORT_PREFIX
    clip = ClipStudy("a", "a.mp4", "a" * 64, 4, "ready", shots=[Shot(i, i, i + 1) for i in range(4)])
    selection = [Candidate("a", clip.sha256, 0, 4, 0, 0, None, "", False, False)]
    assert shot_lengths(selection, [clip]) == [1, 1, 1, 1]
    reference = Breakdown(VideoMeta("reference", "file", duration=4, fps=30), shots=[Shot(0, 0, 4)])
    rendered = Breakdown(VideoMeta("output", "file", duration=4, fps=30), shots=[Shot(0, 0, 4)])
    plan = Composition(warnings=[REPORT_PREFIX + json.dumps({"pacing_evidence": {"shot_durations_seconds": [1, 1, 1, 1]}})])
    result = report(build_style_recipe(reference), rendered, {}, None, {}, plan)
    assert result["pacing_flag"] == "unmet"
    assert result["dimensions"]["shot_pace"]["rendered_pixels"]["status"] == "pass"
    assert result["dimensions"]["shot_pace"]["status"] == "miss"


@pytest.mark.parametrize("text,position,start,end,speech,expected", [
    ("Stay safe", "lower", 0, 2, "Stay safe", "caption"),
    ("Directed by Example", "lower", 0, 2, "We should leave", "credit"),
    ("Supported by the Example Film Fund", "lower", 0, 2, "We should leave", "credit"),
    ("A NEW DAY", "center", 0, 3, "", "title"),
    ("LAB 42", "lower", 0, 2, "We should leave", "scene_text"),
    ("NASA", "top", 0, 10, "We should leave", "scene_text"),
])
def test_labeled_caption_and_synthetic_negatives(text, position, start, end, speech, expected):
    b = Breakdown(VideoMeta("fixture", "file", duration=12), words=words(speech),
                  captions=[CaptionEvent(text, start, end, position)])
    roles = classify_text(b)
    assert roles["events"][0]["role"] == expected
    assert TextRole.from_dict(roles["events"][0]).role == expected
    recipe = build_style_recipe(b)
    assert any(f.name.startswith("captions[") for f in recipe.measured) == (expected == "caption")


def test_noncaption_tracks_cannot_supply_geometry_or_fonts():
    b = Breakdown(VideoMeta("fixture", "file", duration=12), captions=[CaptionEvent("Directed by A", 0, 3)])
    geo = {"tracks": [{"id": "credit", "kind": "caption", "text": "Directed by A", "motion": "static", "samples": [{"t": 1}]}],
           "font_candidates": {"tracks": [{"track_id": "credit", "kind": "caption", "candidates": [1]}]}}
    filtered = caption_geometry(geo, classify_text(b, geo))
    assert not filtered["tracks"] and not filtered["font_candidates"]["tracks"]
    assert geo["tracks"]


def test_font_warnings_group_by_cause():
    result = group_disclosures([f"font candidates track text-{i}: font{i} weight 400: ValueError: font lacks OCR character U+2192" for i in range(3)])
    assert len(result) == 1 and "3x" in result[0] and "U+2192" in result[0]
