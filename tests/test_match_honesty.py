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
    band = timing_band(.8, [.6, .7, .8, .9, 1.0])
    assert band["reference_iqr_seconds"] == pytest.approx(.2)
    assert (band["lower"], band["upper"]) == pytest.approx((.45, 1.15)) and not band["capped"]
    assert timing_band(2, [2])["tolerance"] == .4
    assert timing_band(.8, [.8])["tolerance"] == .25
    assert "0.250 s shorter" in timing_distance(.2, band)
    assert "0.350 s longer" in timing_distance(1.5, band)
    assert "Inside" in timing_distance(.467, band)
    # The NASA audit reference (0.800 s median, 0.267 s IQR) is below the cap.
    nasa = timing_band(.8, [.8, 1.267, 1.3, 1.366, .834, .833, .467, .433, .633, 1.6, .967, .767, 1.0,
                            1.0, .766, .867, 1.2, .767, .8, .7, .633, .8, .2])
    assert not nasa["capped"]
    assert nasa["reference_iqr_seconds"] == pytest.approx(.267, abs=1e-3)
    assert (nasa["lower"], nasa["upper"]) == pytest.approx((.4165, 1.1835), abs=1e-3)


@pytest.mark.parametrize("reference", [[.4, .5, .6, .8, 1.0, 1.5, 2.5, 4.0, 6.0], [5, 50, 5], [.5, 8.0],
                                       [.4, .7, .8, 1.1, 1.6]])
def test_spread_cannot_stretch_a_band_to_half_or_double_the_target(reference):
    """Heavy-tailed references once gave 0-2.2 s around a 1 s median."""
    from statistics import median
    for target in (median(reference), reference[0]):
        band = timing_band(target, reference)
        assert band["lower"] >= min(target / 2, target - .25) - 1e-9 and band["lower"] > 0
        assert band["upper"] < 2 * target
        assert band["tolerance"] <= max(.25, target / 2) + 1e-9


def test_heavy_tailed_reference_still_fails_off_pace_drafts():
    reference = [1.0, .4, 2.5, .5, 6.0, .6, .8, 4.0, 1.5]
    slow, fast = [2 * x for x in reference], [x / 3 for x in reference]
    for lengths in (slow, fast):
        dims = compare(reference, lengths, lengths)["dimensions"]
        assert dims["shot_pace"]["status"] == "miss" and dims["first_cut"]["status"] == "miss"
    assert compare(reference, reference, reference)["dimensions"]["shot_pace"]["status"] == "pass"


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
    notes = dimension_notes({k: result["dimensions"][k] for k in ("shot_pace", "first_cut")})
    assert len(notes) == 2 and all("not applicable for this footage" in n for n in notes)
    assert result["dimensions"]["caption_size"]["status"] == "not_applicable"
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


def test_matte_edges_are_inset_and_an_all_gap_sample_set_is_unmeasured(monkeypatch, tmp_path):
    from myzing.color import measure
    from myzing.composition import CropBounds, Framing
    from myzing.match import picture
    framing = Framing("fit", 320, 180, CropBounds(0, 24, 320, 132), 320, 132, 160, 90)
    plan = Composition(width=240, height=240, assets=[AssetRef("a", "a.mp4", "a" * 64)], clips=[CompositionClip(
        id="c", asset_id="a", src="a.mp4", src_in=0, src_out=1, timeline_start=0, framing=framing)])
    # Foreground 240x134 at y=52; the bars map to rows 52-69 and 169-185.
    # Scaling and 4:2:0 chroma blend each matte edge into the next row pair.
    assert picture.picture_regions(plan)[0]["rect"] == [0, 72, 240, 94]
    # Two layers with no common sharp area for the whole video: every sample
    # is a gap. That leaves color unmeasured; it must not fail the delivery.
    monkeypatch.setattr(picture, "picture_regions", lambda plan: [
        {"start": 0, "end": 1, "rect": [0, 0, 60, 90], "clip_id": "x"},
        {"start": 0, "end": 1, "rect": [100, 0, 60, 90], "clip_id": "y"}])
    monkeypatch.setattr(measure, "local_video", lambda path: path)
    monkeypatch.setattr(measure, "probe", lambda path: (1.0, 160, 90, {}))
    monkeypatch.setattr(measure, "check_color_space", lambda metadata: [])
    monkeypatch.setattr(measure, "frame", lambda *a, **k: pytest.fail("a gap must not be decoded"))
    color = picture.measure_output_color(tmp_path / "out.mp4", plan)
    assert color["status"] == "unmeasured" and color["aggregate"] is None
    assert len(color["picture_area"]["samples"]) == 6
    assert all(s["rect"] is None for s in color["picture_area"]["samples"])
    recipe = build_style_recipe(breakdown([.8] * 4))
    from dataclasses import replace
    recipe.measured.append(replace(recipe.measured[0], name="color.luma_percentiles", value=[.1] * 7))
    dimension = report(recipe, breakdown([.8] * 4), {}, color, {}, plan)["dimensions"]["color"]
    assert dimension["status"] == "approximate" and dimension["max_luma_percentile_delta"] is None
    assert dimension["reason"].startswith("No sample had a usable sharp picture area")
    # A failure before sampling (probe/color space) is still a real error.
    monkeypatch.setattr(measure, "probe", lambda path: (_ for _ in ()).throw(measure.ColorError("probe failed")))
    with pytest.raises(measure.ColorError, match="probe failed"):
        picture.measure_output_color(tmp_path / "out.mp4", plan)
