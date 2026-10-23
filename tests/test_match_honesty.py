"""Editorial bands, detector uncertainty and clause constraints remain distinct."""

import json

import pytest

from myzing.composition import AssetRef, Composition, CompositionClip
from myzing.director.plans import REPORT_PREFIX
from myzing.match.evidence import report, markdown
from myzing.match.picture import region_at
from myzing.match.timing import dimension_notes
from myzing.schemas import Breakdown, Shot, VideoMeta
from myzing.style_ranges import timing_band, timing_distance
from myzing.style_recipe import build_style_recipe


def breakdown(lengths):
    shots, cursor = [], 0
    for i, length in enumerate(lengths):
        shots.append(Shot(i, cursor, cursor + length))
        cursor += length
    return Breakdown(VideoMeta("fixture", "file", duration=cursor, fps=30), shots=shots)


def compare(reference, pixels, mapped=None, *, clauses=(), clips=(), warnings=()):
    planning = {"pacing_evidence": {"shot_durations_seconds": mapped} if mapped else {},
                "continuity": {"clauses": list(clauses)}}
    plan = Composition(assets=[AssetRef("a", "fixture.mp4", "a" * 64)] if clips else [],
                       clips=list(clips), warnings=[REPORT_PREFIX + json.dumps(planning)])
    rendered = breakdown(pixels)
    rendered.warnings = list(warnings)
    # Empty continuity status avoids claiming a continuity grade in this fixture.
    if clauses:
        planning["continuity"].update(status="pass", basis="Fixture clauses")
    else:
        planning.pop("continuity")
    plan.warnings = [REPORT_PREFIX + json.dumps(planning)]
    return report(build_style_recipe(breakdown(reference)), rendered, {}, None, {}, plan)


def test_reference_spread_and_policy_floor_define_band():
    band = timing_band(.8, [.4, .7, .8, 1.1, 1.6])
    assert band["reference_iqr_seconds"] == pytest.approx(.4)
    assert (band["lower"], band["upper"]) == pytest.approx((.35, 1.25))
    assert timing_band(2, [2])["tolerance"] == .4
    assert timing_band(.8, [.8])["tolerance"] == .25
    assert "0.150 s shorter" in timing_distance(.2, band)
    assert "0.250 s longer" in timing_distance(1.5, band)
    assert "Inside" in timing_distance(.467, band)


def test_detector_disagreement_is_not_a_style_miss_or_pass():
    result = compare([.8] * 8, [.967] * 8, [.8] * 8)
    pace = result["dimensions"]["shot_pace"]
    assert pace["status"] == "detector_disagreement"
    assert pace["planned"] == .8 and pace["observed"] == pytest.approx(.967)
    assert "0.800 s" in pace["reason"] and "0.967 s" in pace["reason"]
    assert result["pacing_flag"] == "unverified"


def test_matching_medians_do_not_certify_mismatched_events():
    result = compare([.8] * 3, [.8, .4, 1.2], [.8] * 3)
    pace = result["dimensions"]["shot_pace"]
    assert pace["status"] == "detector_disagreement"
    assert pace["cut_agreement"]["mapped_not_detected_seconds"] == [1.6]


def test_bad_plan_stays_a_miss_when_detector_looks_like_reference():
    result = compare([.8] * 4, [.8] * 4, [3.2])
    assert result["dimensions"]["shot_pace"]["status"] == "miss"
    assert result["pacing_flag"] == "unmet"


def test_missing_detector_never_establishes_a_miss():
    result = compare([.8] * 4, [3.2], [.8] * 4, warnings=["shot detection skipped"])
    assert result["dimensions"]["shot_pace"]["status"] == "approximate"
    assert result["pacing_flag"] == "unverified"


def speech_fixture():
    clips = [CompositionClip(id=f"c{i}", asset_id="a", src="fixture.mp4", src_in=i * 3,
                             src_out=(i + 1) * 3, timeline_start=i * 3) for i in range(3)]
    clauses = [{"asset_id": "a", "start": i * 3, "end": (i + 1) * 3,
                "complete": True, "selected_whole": True} for i in range(3)]
    return clips, clauses


def test_continuous_speech_abstains_with_reason_and_retained_measurements():
    clips, clauses = speech_fixture()
    result = compare([.8] * 10, [3] * 3, [3] * 3, clips=clips, clauses=clauses)
    for name in ("shot_pace", "first_cut"):
        d = result["dimensions"][name]
        assert d["status"] == "not_applicable"
        assert "protected" in d["reason"] and d["planned"] == 3
        assert d["rendered_pixels"]["observed"] == 3
    assert result["pacing_flag"] == "not_applicable"
    notes = dimension_notes(result["dimensions"])
    assert len(notes) == 2 and all("not applicable for this footage" in n for n in notes)
    summary = {"project": ".", "summary": "1 ready", "drafts": {"A": {
        "status": "ready", "dimensions": result["dimensions"], "video": "a.mp4", "plan": "a.json",
        "timeline": "a.png", "report": "a.match.json"}}}
    text = markdown(summary)
    assert "not applicable for this footage" in text and "would split clauses" in text
    assert "| not applicable for this footage |" in text


def test_speech_with_internal_montage_cuts_is_applicable():
    clips, clauses = speech_fixture()
    result = compare([.8] * 10, [.8] * 10, [.8] * 10, clips=clips, clauses=clauses)
    assert result["dimensions"]["shot_pace"]["status"] == "pass"
    assert result["dimensions"]["first_cut"]["status"] == "pass"


def test_non_speech_opening_cannot_abstain_due_to_later_speech():
    clips, clauses = speech_fixture()
    result = compare([.8] * 10, [3] * 3, [3] * 3, clips=clips, clauses=clauses[1:])
    assert result["dimensions"]["first_cut"]["status"] == "miss"


def test_overlap_uses_intersection_and_gaps_are_explicit():
    regions = [{"start": 0, "end": 2, "rect": [0, 40, 320, 100]},
               {"start": 1, "end": 3, "rect": [100, 0, 120, 180]}]
    assert region_at(regions, 1.5) == (100, 40, 120, 100)
    assert region_at(regions, 4) is None
