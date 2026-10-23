"""COLOR2 rendered calibration, own-LUT pass, and same-face skin preservation."""

import pytest

pytest.importorskip("numpy")

from myzing.color.measure import measure_video
from myzing.color.media import run_media
from myzing.match.color import compare_color
from tools.eval.color2_fixture import cases
from tools.eval.color_fixture import make_video

pytestmark = pytest.mark.ffmpeg


def encoded(path, rgb):
    raw = path.with_suffix(".mkv")
    make_video(raw, rgb)
    run_media(["ffmpeg", "-v", "error", "-i", str(raw), "-vf",
               "scale=out_color_matrix=bt709:out_range=tv,format=yuv444p",
               "-c:v", "libx264", "-crf", "16", "-color_primaries", "bt709",
               "-color_trc", "iec61966-2-1", "-colorspace", "bt709", "-color_range", "tv", str(path)])
    return measure_video(path, count=4)[0].to_dict()


@pytest.mark.parametrize("name", list(cases()[1]))
def test_generated_color_calibration_after_bt709_encode(tmp_path, name):
    rgb, variants = cases()
    pixels, expected = variants[name]
    a = encoded(tmp_path / "reference.mp4", rgb)
    b = encoded(tmp_path / "draft.mp4", pixels)
    result = compare_color(a, b)
    assert result["status"] == expected, result
    if name.startswith("equal-luma"):
        assert result["max_luma_percentile_delta"] < .015
        assert result["components"]["cast"]["status"] == "miss"


def test_zing_fitted_lut_reaches_color_pass(tmp_path, monkeypatch):
    from myzing.color.api import match_video
    from myzing.color.media import apply_video
    from myzing.composition import AssetRef, Composition, CompositionClip
    from myzing.match.picture import measure_output_color
    monkeypatch.chdir(tmp_path)
    rgb, variants = cases()
    source, reference = tmp_path / "source.mp4", tmp_path / "reference.mp4"
    a = encoded(reference, variants["teal-orange"][0])
    b = encoded(source, rgb)
    assert compare_color(a, b)["status"] == "miss"
    recipe = match_video(reference, source, tmp_path / "grade", samples=4)
    graded = tmp_path / "graded.mp4"
    apply_video(recipe.cube_path, source, graded)
    plan = Composition(width=160, height=120, assets=[AssetRef("a", str(source), recipe.clip.sha256)],
                       clips=[CompositionClip(id="c", asset_id="a", src=str(source), src_in=0, src_out=2, timeline_start=0)])
    result = compare_color(a, measure_output_color(graded, plan, count=4))
    assert result["status"] == "pass", result


def test_skin_preservation_compares_each_face_with_its_own_ungraded_source(tmp_path):
    """(a) different people, no grade: no skin miss; (b) a greening LUT on the same clip: miss."""
    from test_match_color import BOX, people
    from myzing.color import COLOR_SPACE
    from myzing.color.cube import Cube, make_cube, write_cube
    from myzing.color.looks import transform_for
    from myzing.color.media import sha256
    from myzing.composition import AssetRef, ColorTransform, Composition, CompositionClip
    from myzing.match.skin import measure_plan
    first, second = people()
    sources = [tmp_path / "first.mp4", tmp_path / "second.mp4"]
    for path, rgb in zip(sources, (first, second)):
        encoded(path, rgb)
    neutral = make_cube(transform_for("neutral", 0))
    luts = {"identity": write_cube(neutral, tmp_path / "identity.cube"),
            "green": write_cube(Cube(neutral.size, [[min(1, max(0, v + d)) for v, d in zip(row, (-.035, .014, -.035686))]
                                                    for row in neutral.values]), tmp_path / "green.cube")}

    def plan(lut, strength=1.0):
        color = None if lut is None else ColorTransform(str(lut), sha256(lut), strength, COLOR_SPACE)
        return Composition(width=160, height=120,
                           assets=[AssetRef(f"a{i}", str(path), sha256(path)) for i, path in enumerate(sources)],
                           clips=[CompositionClip(id=f"c{i}", asset_id=f"a{i}", src=str(path), src_in=0, src_out=2,
                                                  timeline_start=2 * i, color=color) for i, path in enumerate(sources)])
    boxes = lambda t, rgb: [BOX]
    assert measure_plan(plan(None), boxes_at=boxes) is None
    assert measure_plan(plan(luts["green"], 0.0), boxes_at=boxes) is None
    same = measure_plan(plan(luts["identity"]), boxes_at=boxes, count=3)
    assert same["status"] == "pass" and len(same["faces"]) == 6
    assert max(f["shift"] for f in same["faces"]) < .5
    greened = measure_plan(plan(luts["green"]), boxes_at=boxes, count=3)
    assert greened["status"] == "miss" and {f["status"] for f in greened["faces"]} == {"miss"}
    assert all(f["a_delta"] < -5 for f in greened["faces"]) and "toward green" in greened["reason"]
    half = measure_plan(plan(luts["green"], .5), boxes_at=boxes, count=3)
    assert half["worst"]["shift"] < greened["worst"]["shift"]
