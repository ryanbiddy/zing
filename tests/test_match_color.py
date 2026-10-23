"""COLOR2 calibration and honesty, including CI's no-FFmpeg environment."""

from copy import deepcopy

import pytest

np = pytest.importorskip("numpy")

from myzing.match.color import BANDS, compare_color, from_recipe
from myzing.match.skin import measure_faces
from tools.eval.color2_fixture import cases, measurement


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


def skin_case():
    rgb, _ = cases()
    rgb = rgb.copy()
    rgb[36:64, 60:88] = [.63, .43, .33]
    green = rgb.copy()
    green[36:64, 60:88] += [-.035, .014, -.035686]
    boxes = lambda t, frame: [(60/160, 36/120, 88/160, 64/120)]
    return rgb, green, boxes


def test_small_green_face_is_worse_than_the_same_patch_on_a_wall():
    rgb, green, boxes = skin_case()
    a, b = measurement(rgb), measurement(green)
    assert compare_color(a, b)["status"] == "pass"  # small patch diluted by the wall
    for data, pixels in ((a, rgb), (b, green)):
        data["skin"] = measure_faces([pixels], [.5], boxes_at=boxes)
    result = compare_color(a, b)
    assert result["status"] == result["skin"]["status"] == "miss"
    assert result["skin"]["a_delta"] < 0
    assert compare_color(a, a)["status"] == "pass"


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


def test_matching_varied_face_colors_are_not_compared_to_one_average():
    a = measurement(cases()[0])
    a["skin"] = {"ab_mean": [15, 10], "face_ab": [[10, 0], [20, 20]]}
    assert compare_color(a, deepcopy(a))["status"] == "pass"


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
