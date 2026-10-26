"""COLOR2 calibration and honesty, including CI's no-FFmpeg environment."""

from copy import deepcopy

import pytest

np = pytest.importorskip("numpy")

from myzing.match.color import BANDS, compare_color, from_recipe
from myzing.match.skin import compare_face, face_pixels, summarize
from tools.eval.color2_fixture import cases, measurement
from tools.eval.skin_fixture import SKIN_TONES, grades, lab_to_rgb, patch


@pytest.mark.parametrize("name", list(cases()[1]))
def test_generated_color_calibration(name):
    reference, variants = cases()
    rgb, expected = variants[name]
    result = compare_color(measurement(reference), measurement(rgb))
    assert result["status"] == expected
    assert len(result["components"]) == 5
    assert "saturation" in result["reason"] and "contrast" in result["reason"]
    if name.startswith("equal-luma"):
        assert result["max_luma_percentile_delta"] < 1e-12
        assert result["components"]["cast"]["status"] == "miss"
        assert ("bluer" if name.endswith("blue") else "greener") in result["reason"]


@pytest.mark.parametrize("limit", ["missing", "legacy", "nan", "shape", "sparse", "gap", "low-confidence", "shots"])
def test_incomplete_evidence_cannot_pass(limit):
    a = measurement(cases()[0])
    b = deepcopy(a)
    if limit == "missing":
        b = None
    elif limit == "legacy":
        b["aggregate"] = {"luma_percentiles": [0]*7}
    elif limit == "nan":
        b["aggregate"]["ab_mean"][0] = float("nan")
    elif limit == "shape":
        b["aggregate"]["tone_ab"] = [[0, 0]]
    elif limit == "sparse":
        b["coverage"]["usable_samples"] = 1
    elif limit == "gap":
        b["coverage"]["sample_fraction"] = .75
    elif limit == "low-confidence":
        b["confidence"] = .2
    else:
        b["coverage"].update(shots_supplied=8, shot_fraction=.5)
    assert compare_color(a, b)["status"] == "approximate"


def test_bands_have_explicit_inclusive_pass_exclusive_miss_boundaries():
    from myzing.match.color import _status
    for name, (inner, outer) in BANDS.items():
        assert _status(inner, name) == "pass"
        assert _status(inner+1e-8, name) == "approximate"
        assert _status(outer, name) == "approximate"
        assert _status(outer+1e-8, name) == "miss"


BOX = (60/160, 36/120, 88/160, 64/120)


def people():
    """Two different people with different skin tones in otherwise identical scenes."""
    rgb, _ = cases()
    first, second = rgb.copy(), rgb.copy()
    first[36:64, 60:88] = lab_to_rgb((64, 23, 14))   # ruddy, pink-toned skin
    second[36:64, 60:88] = lab_to_rgb((38, 9, 20))   # a deeper, more olive skin tone
    return first, second


def identity(px):
    return px


def green(px):
    return np.clip(px + [-.035, .014, -.035686], 0, 1)


def test_different_people_without_a_grade_never_miss_on_skin():
    first, second = people()
    a, b = measurement(first), measurement(second)
    # Even measurement dicts that still carry face data cannot feed the
    # draft-vs-reference color verdict: there is no face component at all.
    a["skin"] = {"ab_mean": [23, 14], "face_ab": [[23, 14]]}
    b["skin"] = {"ab_mean": [9, 20], "face_ab": [[9, 20]]}
    result = compare_color(a, b)
    assert set(result["components"]) == set(BANDS) and "skin" not in result
    assert "face" not in result["reason"]
    assert result["status"] == compare_color(measurement(first), measurement(second))["status"]
    # Skin preservation compares each person only with themself: ungraded, both pass.
    faces = []
    for frame in (first, second):
        pixels, interior = face_pixels(frame, BOX)
        faces.append({"source": "clip.mp4", "timestamp": .5, **compare_face(pixels, identity)})
    assert [f["shift"] for f in faces] == [0, 0]
    assert summarize(faces, [{"source": "clip.mp4", "faces": 2}])["status"] == "pass"


@pytest.mark.parametrize("tone", list(SKIN_TONES))
def test_lut_that_greens_the_same_face_misses(tone):
    face = patch(SKIN_TONES[tone]).reshape(-1, 3)
    result = compare_face(face, green)
    assert result["status"] == "miss" and result["toward_green"] > 5 and result["a_delta"] < 0
    assert compare_face(face, identity)["status"] == "pass"


def test_skin_hue_calibration_cases_hold_on_every_generated_tone():
    for name, (function, expected) in grades().items():
        statuses = {tone: compare_face(patch(lab).reshape(-1, 3), function)["components"]["hue_shift"]["status"] for tone, lab in SKIN_TONES.items()}
        if expected == "miss":
            assert set(statuses.values()) == {"miss"}, (name, statuses)
        else:
            allowed = {"pass"} if expected == "pass" else {"pass", "approximate"}
            assert set(statuses.values()) <= allowed, (name, statuses)


def test_gray_faces_still_catch_a_green_push():
    gray = patch((55, 1, 2)).reshape(-1, 3)
    assert compare_face(gray, green)["status"] == "miss"
    assert compare_face(gray, grades()["look desaturated @1"][0])["status"] == "pass"


def test_skin_summary_states_and_limits():
    assert summarize([], [])["measurement_status"] == "unmeasured"
    assert summarize([], [], unmeasured_reason="detector missing")["reason"] == "detector missing"
    face = patch(SKIN_TONES["medium"]).reshape(-1, 3)
    rows = [{"source": "a.mp4", "timestamp": 1.0, **compare_face(face, identity)},
            {"source": "b.mp4", "timestamp": 2.0, **compare_face(face, green)}]
    result = summarize(rows, [{"source": "a.mp4", "faces": 1}, {"source": "b.mp4", "faces": 1}, {"source": "c.mp4", "faces": 0}])
    assert result["status"] == "miss" and result["worst"]["source"] == "b.mp4"
    assert "toward green" in result["reason"] and "b.mp4" in result["reason"] and "c.mp4" in result["reason"]
    assert face_pixels(np.zeros((10, 10, 3)), (0, 0, .2, .2)) == (None, None)  # too few interior pixels
    assert face_pixels(np.zeros((90, 160, 3)), (float("nan"), 0, 1, 1)) == (None, None)
    assert "in 4 sampled source frames" in summarize([], [{"source": "a.mp4", "samples": [1, 2, 3, 4], "faces": 0}])["reason"]
    assert "could be decoded" in summarize([], [{"source": "a.mp4", "samples": [], "faces": 0}])["reason"]
    from myzing.match.skin import sample_times
    # Only the trims a draft uses are sampled; overlapping trims are merged.
    assert sample_times([(10, 12), (11, 14), (20, 21)], 5) == pytest.approx([10.5, 11.5, 12.5, 13.5, 20.5])
    assert sample_times([(3, 3)], 4) == []


def test_plan_without_a_grade_has_no_skin_dimension():
    from myzing.composition import AssetRef, Composition, CompositionClip
    from myzing.match.skin import measure_plan
    plan = Composition(width=160, height=120, assets=[AssetRef("a", "clip.mp4", "0" * 64)],
                       clips=[CompositionClip(id="c", asset_id="a", src="clip.mp4", src_in=0, src_out=2, timeline_start=0)])
    assert measure_plan(plan, boxes_at=lambda t, rgb: []) is None


def montage(rgb, casts):
    """One sample per 'shot', each with its own whole-frame cast: varied scene content."""
    from myzing.color.stats import statistics
    frames = [np.clip(rgb + c, 0, 1) for c in casts]
    return {"aggregate": statistics(np.concatenate([f.reshape(-1, 3) for f in frames])).to_dict(),
            "samples": [{"stats": statistics(f).to_dict()} for f in frames],
            "confidence": .85, "coverage": {"usable_samples": len(frames), "sample_fraction": 1}}


def test_scene_variation_softens_a_miss_but_a_consistent_grade_still_misses():
    rgb, variants = cases()
    blue = variants["equal-luma-blue"][0] - rgb
    varied = montage(rgb, [blue, -blue] * 3)            # shots alternate blue and yellow
    steady = montage(rgb, [0 * blue] * 6)               # one consistent picture
    draft = montage(rgb, [.75 * blue] * 6)              # a consistent blue grade
    soft = compare_color(varied, draft)
    assert soft["components"]["cast"]["delta"] > BANDS["cast"][1]
    assert soft["components"]["cast"]["status"] == "approximate" and soft["components"]["cast"]["content_limited"]
    assert "Scene content differs" in soft["reason"] and soft["status"] != "miss"
    hard = compare_color(steady, draft)
    assert hard["components"]["cast"]["status"] == "miss" and hard["status"] == "miss"
    assert hard["scene_variation"]["allowance"]["cast"] < 1e-9
    # Variation never manufactures a pass: an approximate difference stays approximate.
    near = compare_color(varied, montage(rgb, [.3 * blue] * 6))
    assert near["components"]["cast"]["status"] == "approximate" and not near["components"]["cast"]["content_limited"]


def test_recipe_carries_lab_coverage_to_report():
    from dataclasses import replace
    from myzing.schemas import Breakdown, VideoMeta
    from myzing.style_recipe import build_style_recipe, Coverage
    recipe = build_style_recipe(Breakdown(VideoMeta("fixture", "file", duration=2)))
    target = measurement(cases()[0])
    fact = recipe.measured[0]
    recipe.measured.extend(replace(fact, name="color."+key, value=value, confidence=.85,
                                  confidence_kind="heuristic", coverage=Coverage(4, 1, "generated", target["coverage"]))
                           for key, value in target["aggregate"].items())
    assert from_recipe(recipe, target)["status"] == "pass"
    # A legacy recipe's reference face fact must not come back as a skin verdict.
    recipe.measured.append(replace(fact, name="color.skin", value={"ab_mean": [30, 2], "face_ab": [[30, 2]]}))
    result = from_recipe(recipe, target)
    assert result["status"] == "pass" and set(result["components"]) == set(BANDS)


def test_skin_preservation_is_its_own_dimension_and_never_changes_color(tmp_path):
    from myzing.composition import AssetRef, Composition, CompositionClip
    from myzing.match.evidence import report
    from myzing.schemas import Breakdown, VideoMeta
    from myzing.studio.presentation import creator_summary
    from myzing.style_recipe import build_style_recipe
    recipe = build_style_recipe(Breakdown(VideoMeta("ref", "file", duration=2)))
    plan = Composition(width=160, height=120, assets=[AssetRef("a", "unused.mp4", "a" * 64)],
                       clips=[CompositionClip(id="c", asset_id="a", src="unused.mp4", src_in=0, src_out=2, timeline_start=0)])
    face = patch(SKIN_TONES["tan"]).reshape(-1, 3)
    rendered = Breakdown(VideoMeta("out", "file", duration=2))
    plain = report(recipe, rendered, {}, None, {}, plan)["dimensions"]
    assert "skin_preservation" not in plain
    for function, status in ((identity, "pass"), (green, "miss")):
        skin = summarize([{"source": "clip.mp4", "timestamp": 1.0, **compare_face(face, function)}], [{"source": "clip.mp4", "faces": 1}])
        dimensions = report(recipe, rendered, {}, None, {}, plan, skin=skin)["dimensions"]
        assert dimensions["skin_preservation"]["status"] == status
        assert dimensions["color"] == plain["color"]
    rows = {"A.16x9": {"status": "ready", "video": "A.mp4", "dimensions": dimensions}}
    text = str(creator_summary({"project": str(tmp_path), "result": {"drafts": rows}}, {"aspects": ["16:9"]}, {}))
    assert "skin preservation miss" in text
    dimensions["skin_preservation"].update(status="approximate")
    text = str(creator_summary({"project": str(tmp_path), "result": {"drafts": rows}}, {"aspects": ["16:9"]}, {}))
    assert "skin preservation approximate" in text
    dimensions["skin_preservation"].update(measurement_status="unmeasured")
    assert "skin preservation" not in str(creator_summary({"project": str(tmp_path), "result": {"drafts": rows}}, {"aspects": ["16:9"]}, {}))


def test_studio_pick_and_finish_keep_color_states_distinct(tmp_path):
    from myzing.studio.presentation import creator_summary
    rows = {f"{draft}.16x9": {"status": "ready", "video": f"{draft}.mp4", "dimensions": {"color": {
        "status": status, "measurement_status": "measured"}}}
        for draft, status in zip("ABC", ("approximate", "miss", "pass"))}
    summary = creator_summary({"project": str(tmp_path), "result": {"drafts": rows}}, {"aspects": ["16:9"]}, {})
    text = str(summary)
    assert "Start with draft C" in text and "passes color" in text
    assert "color approximate" in text and "color miss" in text
    rows["C.16x9"]["dimensions"]["color"].update(status="approximate", measurement_status="unmeasured")
    text = str(creator_summary({"project": str(tmp_path), "result": {"drafts": rows}}, {"aspects": ["16:9"]}, {}))
    assert "passes color" not in text and "color unmeasured" in text
