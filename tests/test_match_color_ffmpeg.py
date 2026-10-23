"""COLOR2 rendered calibration, own-LUT pass, and protected face proxy."""

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
    result = compare_color(a, measure_output_color(graded, plan, count=4, face_boxes_at=lambda t, rgb: []))
    assert result["status"] == "pass", result


def test_face_cast_survives_render_and_sharp_area_sampling(tmp_path):
    from test_match_color import skin_case
    from myzing.match.skin import measure_faces
    rgb, green, boxes = skin_case()
    a = encoded(tmp_path / "reference.mp4", rgb)
    b = encoded(tmp_path / "green.mp4", green)
    assert compare_color(a, b)["status"] == "pass"
    for data, path in ((a, tmp_path / "reference.mp4"), (b, tmp_path / "green.mp4")):
        measured, frames, _ = measure_video(path, count=4)
        data["skin"] = measure_faces(frames, [s.timestamp for s in measured.samples], boxes_at=boxes)
    assert compare_color(a, b)["status"] == "miss"
