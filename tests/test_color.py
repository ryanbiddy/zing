"""Color distribution recovery and standalone serialization contracts."""

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

np = pytest.importorskip("numpy", reason='install myzing[color] for color tests')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from myzing.color.cube import Cube, apply_cube, make_cube, read_cube, write_cube
from myzing.color.looks import apply_transform, look_bank, transform_for
from myzing.color.match import rank_looks
from myzing.color.measure import quality_warnings, sample_plan
from myzing.color.media import check_color_space
from myzing.color.models import MatchResult, Transform
from myzing.color.science import delta_e_2000, rgb_to_lab
from myzing.color.stats import distance, statistics
from myzing.schemas import Shot
from tools.eval.color_fixture import chart


@pytest.mark.parametrize("look", list(look_bank()))
def test_procedural_looks_deterministic_cube_roundtrip(tmp_path, look):
    transform = transform_for(look, 0.63, exposure_ev=0.125, temperature=0.02, tint=-0.01)
    assert Transform.from_dict(transform.to_dict()) == transform
    a = write_cube(make_cube(transform), tmp_path / "a.cube")
    b = write_cube(make_cube(transform), tmp_path / "b.cube")
    assert a.read_bytes() == b.read_bytes()
    loaded = read_cube(a)
    assert Cube.from_dict(loaded.to_dict()) == loaded
    assert loaded.size == 33
    np.testing.assert_allclose(loaded.values, make_cube(transform).values, atol=5.1e-11, rtol=0)
    # 33^3 interpolation softens sharp clipping knees by up to 3.1 RGB8 codes.
    np.testing.assert_allclose(apply_cube(chart(), loaded), apply_transform(chart(), transform), atol=3.1 / 255)


def test_identity_cube_exact_pixels():
    rgb = np.random.default_rng(12).random((40, 60, 3))
    np.testing.assert_allclose(apply_cube(rgb, make_cube(transform_for("neutral"))), rgb, atol=1e-12)


@pytest.mark.parametrize("text", [
    "TITLE unquoted\nLUT_3D_SIZE 2\n",
    "LUT_3D_SIZE 1\n", "LUT_3D_SIZE 66\n", "LUT_1D_SIZE 2\n", "0 0 0\n",
    "LUT_3D_SIZE 2\nLUT_3D_SIZE 2\n", "LUT_3D_SIZE 2\n0 0 0\n",
    "LUT_3D_SIZE 2\nDOMAIN_MIN 1 0 0\n" + "0 0 0\n" * 8,
    "LUT_3D_SIZE 2\nDOMAIN_MAX 1 1 nan\n" + "0 0 0\n" * 8,
    "LUT_3D_SIZE 2\n" + "0 0 nan\n" * 8,
    "LUT_3D_SIZE 2\n" + "0 0 2\n" * 8,
    "LUT_3D_SIZE 2\n" + "0 0 0\n" * 9,
    "LUT_3D_SIZE 2\n0 0 0\nTITLE \"late\"\n" + "0 0 0\n" * 7,
])
def test_cube_rejects_malformed_headers_domains_and_rows(tmp_path, text):
    path = tmp_path / "bad.cube"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        read_cube(path)


def test_cube_accepts_comments_and_default_unit_domain(tmp_path):
    path = tmp_path / "comments.cube"
    path.write_text('TITLE "Test #1" # trailing comment\nLUT_3D_SIZE 2 # size\n' + "0 0 0 # row\n" * 8)
    assert read_cube(path).domain_max == [1, 1, 1]
    assert read_cube(path).title == "Test #1"


@pytest.mark.parametrize("look,strength", [
    ("warm", 0.37), ("cool", 0.67), ("teal-orange", 0.67),
    ("faded-film", 0.37), ("punchy", 0.67), ("desaturated", 0.37),
    ("golden-hour", 0.67),
])
def test_known_grade_recovers_top_one_and_strength(look, strength):
    rgb = chart(64, 48)
    target = apply_transform(rgb, transform_for(look, strength))
    match = rank_looks(target, rgb)
    chosen = match.chosen.transform
    assert chosen.look == look, match.to_dict()
    assert abs(chosen.strength - strength) <= 0.08
    rendered = apply_cube(rgb, make_cube(chosen))
    error = np.median(delta_e_2000(rgb_to_lab(rendered), rgb_to_lab(target)))
    assert error <= 3, f"median Delta E 2000 = {error}"
    assert match.chosen.score <= match.baseline_score
    assert MatchResult.from_dict(json.loads(json.dumps(match.to_dict()))) == match


def test_corrections_are_bounded_and_improve_exposure_pair():
    rgb = chart(64, 48)
    target = apply_transform(rgb, transform_for("teal-orange", 0.6, exposure_ev=0.2, temperature=0.025, tint=-0.02))
    result = rank_looks(target, rgb)
    t = result.chosen.transform
    assert abs(t.exposure_ev) <= 0.5
    assert max(abs(t.temperature), abs(t.tint)) <= 0.06
    assert result.chosen.score < result.baseline_score / 10
    assert np.median(delta_e_2000(rgb_to_lab(apply_transform(rgb, t)), rgb_to_lab(target))) <= 3


def test_distance_has_no_spatial_correspondence():
    rgb = chart(32, 24).reshape(-1, 3)
    shuffled = rgb[np.random.default_rng(18).permutation(len(rgb))]
    # Median-cut ties and lightness quartile ties can move tiny amounts.
    assert distance(statistics(rgb), statistics(shuffled))[0] < 1e-8


@pytest.mark.parametrize("first,second,expected", [
    ([50, 2.6772, -79.7751], [50, 0, -82.7485], 2.0425),
    ([50, 3.1571, -77.2803], [50, 0, -82.7485], 2.8615),
    ([50, 0, 0], [50, -1, 2], 2.3669),
    ([50, 2.49, -0.001], [50, -2.49, 0.0011], 7.2195),
    ([50, -0.001, 2.49], [50, 0.0011, -2.49], 4.7461),
    ([2.0776, 0.0795, -1.1350], [0.9033, -0.0636, -0.5514], 0.9082),
])
def test_delta_e_2000_published_sharma_pairs(first, second, expected):
    assert float(delta_e_2000(first, second)) == pytest.approx(expected, abs=0.0001)
    assert float(delta_e_2000(second, first)) == pytest.approx(expected, abs=0.0001)


def test_lab_reference_neutrals():
    lab = rgb_to_lab(np.array([[0, 0, 0], [1, 1, 1], [.5, .5, .5]]))
    np.testing.assert_allclose(lab[:, 0], [0, 100, 53.38896], atol=0.0001)
    np.testing.assert_allclose(lab[:, 1:], 0, atol=0.0001)


def test_bounded_even_and_shot_sampling():
    plan = sample_plan(10, 4)
    assert [v[0] for v in plan] == [1.25, 3.75, 6.25, 8.75]
    shots = [Shot(0, 0, 1), Shot(1, 1, 5), Shot(2, 5, 10)]
    plan = sample_plan(10, 6, shots)
    assert len(plan) == 6
    assert {v[1] for v in plan} == {0, 1, 2}
    assert all(shots[i].start < t < shots[i].end for t, i in plan)
    assert len(sample_plan(10, 2, shots)) == 2
    with pytest.raises(ValueError):
        sample_plan(10, 33)
    with pytest.raises(ValueError):
        sample_plan(10, 4, [Shot(0, 0, 7), Shot(1, 6, 10)])


def test_log_like_and_clipped_warnings():
    assert any("LOG-like" in w for w in quality_warnings(statistics(np.full((20, 20, 3), 0.4))))
    assert any("clipped" in w for w in quality_warnings(statistics(np.zeros((20, 20, 3)))))
    assert not quality_warnings(statistics(chart()))


@pytest.mark.parametrize("metadata", [
    {"color_transfer": "smpte2084"}, {"color_transfer": "arib-std-b67"},
    {"color_transfer": "log100"}, {"color_primaries": "bt2020"},
    {"profile_tags": "S-Log3"}, {"color_space": "bt2020nc"},
])
def test_hdr_log_metadata_is_rejected(metadata):
    from myzing.color import ColorError
    with pytest.raises(ColorError, match="declared"):
        check_color_space(metadata)


def test_unknown_metadata_is_disclosed():
    assert "assumed" in check_color_space({})[0]


def test_contracts_reject_unknown_versions_and_unbounded_corrections():
    t = transform_for("warm")
    for version in (None, 2, True):
        with pytest.raises(ValueError):
            Transform.from_dict({**t.to_dict(), "version": version})
    with pytest.raises(ValueError):
        replace(t, exposure_ev=0.6)
    with pytest.raises(ValueError):
        replace(t, temperature=float("nan"))


def test_partial_measurement_discloses_coverage(tmp_path, monkeypatch):
    from myzing.color import ColorError, measure
    path = tmp_path / "local.mp4"
    path.write_bytes(b"local fixture for mocked decode")
    monkeypatch.setattr(measure, "probe", lambda _: (4.0, 64, 48, {}))
    def decode(path, timestamp, *args):
        if timestamp == 1.5:
            raise ColorError("damaged frame")
        return chart(64, 48)
    monkeypatch.setattr(measure, "frame", decode)
    measured, _, _ = measure.measure_video(path, count=4)
    assert len(measured.samples) == 3
    assert measured.coverage["sample_fraction"] == 0.75
    assert any("1.500000s unavailable" in w for w in measured.warnings)
    monkeypatch.setattr(measure, "frame", lambda *a, **kw: (_ for _ in ()).throw(ColorError("bad decode")))
    with pytest.raises(ColorError, match="No usable frames"):
        measure.measure_video(path, count=4)
