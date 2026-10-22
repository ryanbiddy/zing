"""R13 generated-media render gates: 9 cases, no downloaded media."""

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

np = pytest.importorskip("numpy", reason="install myzing[color] for LUT render tests")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from myzing.color.cube import Cube, apply_cube, make_cube, read_cube, write_cube
from myzing.color.looks import transform_for
from myzing.color.media import run_media, sha256
from myzing.composition import AssetRef, CaptionStyle
from myzing.layout.types import Box, EventLayout, OverlapCheck
from myzing.render import pipeline, render_composition
from myzing.render.validation import EDLValidationError
from myzing.schemas import Word
from tools.eval.color_fixture import chart, make_video
from tools.eval.render_lut_fixture import color_transform, composition, decode, make_source, metrics
from test_render_composition import caption, forbid_work

pytestmark = pytest.mark.ffmpeg


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    root = tmp_path_factory.mktemp("r13 source's [x], paths")
    return make_source(root / "generated chart.mkv")


def render(tmp_path, c, name):
    return render_composition(c, tmp_path / f"{name}.mp4", work_dir=tmp_path / f"{name}-work")


def look(tmp_path, name="teal-orange", strength=1):
    path = write_cube(make_cube(transform_for(name)), tmp_path / f"{name}'s [x],.cube")
    return color_transform(path, strength)


def test_render_identity_preserves_decoded_pixels_with_codec_tolerance(tmp_path, source):
    result = render(tmp_path, composition(source, look(tmp_path, "neutral")), "identity")
    observed = metrics(decode(result.output_path), decode(source))
    # Whole-frame RGB code errors include H.264 and the YUV/RGB round trip.
    assert observed["mean_code_error"] <= 2, observed
    assert observed["p99_code_error"] <= 8, observed
    assert observed["median_delta_e_2000"] <= 2, observed
    metadata = pipeline.probe_media(result.output_path, include_color=True).color_metadata
    assert metadata["pix_fmt"] == "yuv420p"
    assert metadata["color_space"] == metadata["color_primaries"] == metadata["color_transfer"] == "bt709"


def test_render_procedural_look_matches_apply_cube_delta_e_2000(tmp_path, source):
    color = look(tmp_path)
    result = render(tmp_path, composition(source, color), "graded")
    before = decode(source)
    expected = apply_cube(before, read_cube(color.lut_path))
    observed = metrics(decode(result.output_path), expected)
    assert observed["median_delta_e_2000"] <= 2, observed
    assert metrics(before, expected)["median_delta_e_2000"] > 3  # A no-op cannot pass.
    # Quantization/chroma reconstruction can push near-endpoint values to an
    # endpoint. Clipping must remain within the expected eight-code envelope.
    assert observed["black_fraction"] <= np.mean(np.any(expected <= 8 / 255, axis=-1)) + .005
    assert observed["white_fraction"] <= np.mean(np.any(expected >= 247 / 255, axis=-1)) + .005
    assert result.filtergraph.index("lut3d=") < result.filtergraph.index("scale=320:180") < result.filtergraph.index("concat=")


def test_render_strength_zero_is_exact_and_half_is_midway(tmp_path, source):
    color = look(tmp_path)
    original_hash = sha256(color.lut_path)
    outputs = {}
    for name, transform in (("plain", None), ("zero", replace(color, strength=0)),
                            ("half", replace(color, strength=.5)), ("full", color)):
        outputs[name] = render(tmp_path, composition(source, transform), name)
    plain, zero, half, full = (decode(outputs[n].output_path) for n in ("plain", "zero", "half", "full"))
    np.testing.assert_array_equal(zero, plain)
    assert outputs["zero"].filtergraph == outputs["plain"].filtergraph
    expected = (decode(source) + apply_cube(decode(source), read_cube(color.lut_path))) / 2
    assert metrics(half, expected)["median_delta_e_2000"] <= 2
    assert metrics(half, (plain + full) / 2)["median_delta_e_2000"] <= 2
    manifest = json.loads((outputs["half"].work_dir / "color-transforms.json").read_text())
    entry = manifest["transforms"][0]
    assert manifest["version"] == 1 and entry["strength"] == .5 and entry["stage"] == "before_captions"
    assert entry["source_sha256"] == original_hash == sha256(color.lut_path)
    assert entry["baked_sha256"] == sha256(outputs["half"].work_dir / entry["baked_path"])
    baked = read_cube(outputs["half"].work_dir / entry["baked_path"])
    np.testing.assert_allclose(apply_cube(decode(source), baked), expected, atol=1e-9)


def test_render_caption_fill_highlight_outline_and_plate_are_not_graded(tmp_path):
    rgb = chart(640, 360)
    rgb[72:288] = 0
    source = make_source(tmp_path / "caption source.mkv", rgb)
    # Strong channel permutation preserves black and changes every caption color.
    cube = Cube(2, [[g, b, r] for b in (0, 1) for g in (0, 1) for r in (0, 1)])
    color = color_transform(write_cube(cube, tmp_path / "swap.cube"))
    event = caption(
        text="ONE TWO", end=2, word_timed=True, words=[Word("ONE", 0, 1), Word("TWO", 1, 2)],
        style=CaptionStyle(64, color="#E03B70", highlight="#31D4BD", outline_color="#E0B040",
                           outline_width=5, box_color="#304080"),
        layout=EventLayout("caption", 0, 2, "preferred-anchor", OverlapCheck(True), box=Box(.1, .3, .8, .4)),
    )
    c = composition(source, width=640, height=360)
    c.captions = [event]
    plain = render(tmp_path, c, "plain")
    c.clips[0].color = color
    graded = render(tmp_path, c, "graded")
    assert graded.filtergraph.index("lut3d=") < graded.filtergraph.index("concat=") < graded.filtergraph.index("filename='captions.ass'")
    for time in (.5, 1.5):
        a = decode(plain.output_path, time, 640, 360)
        b = decode(graded.output_path, time, 640, 360)
        # Opaque caption interiors, clear of chroma/antialias boundaries, must
        # retain all four colors; the chart outside the caption must change.
        for hex_color in ("E03B70", "31D4BD", "E0B040", "304080"):
            target = np.array([int(hex_color[i:i + 2], 16) for i in (0, 2, 4)]) / 255
            # libass's existing TV.601 script matrix affects the baseline's
            # decoded RGB. Select its flat interiors near each declared color;
            # the LUT/plain comparison below still allows only two code values.
            mask = np.max(np.abs(a - target), axis=-1) < .12
            mask[:110] = mask[250:] = False
            mask[:, :66] = mask[:, 574:] = False
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                mask &= np.max(np.abs(a - np.roll(a, (dy, dx), axis=(0, 1))), axis=-1) < 3 / 255
            assert mask.sum() > 30, hex_color
            assert np.median(np.abs(a[mask] - b[mask])) * 255 <= 2, hex_color
        assert np.abs(a[-60:] - b[-60:]).mean() * 255 > 10


def test_render_lut_hash_mismatch_fails_before_any_media_work(tmp_path, source, monkeypatch):
    color = look(tmp_path)
    c = composition(source, color)
    Path(color.lut_path).write_bytes(b"changed")
    forbid_work(monkeypatch)
    out, work = tmp_path / "output/video.mp4", tmp_path / "work"
    with pytest.raises(EDLValidationError, match="clip clip LUT: SHA-256 mismatch"):
        render_composition(c, out, work_dir=work)
    assert not out.parent.exists() and not work.exists()


@pytest.mark.parametrize("transfer", ["smpte2084", "arib-std-b67", "log100"])
def test_render_tagged_hdr_or_log_fails_up_front_even_with_creative_lut(tmp_path, source, transfer):
    tagged = tmp_path / "tagged.mkv"
    run_media(["ffmpeg", "-v", "error", "-i", str(source),
               "-vf", f"setparams=color_primaries=bt2020:color_trc={transfer}:colorspace=bt2020nc",
               "-c:v", "libx264", "-color_trc", transfer,
               "-color_primaries", "bt2020", "-colorspace", "bt2020nc", str(tagged)])
    assert pipeline.probe_media(tagged, include_color=True).color_metadata["color_transfer"] == transfer
    for color in (None, look(tmp_path)):
        out, work = tmp_path / "output/video.mp4", tmp_path / "work"
        with pytest.raises(EDLValidationError, match="Unsupported LOG/HDR"):
            render_composition(composition(tagged, color), out, work_dir=work)
        assert not out.parent.exists() and not work.exists()


def test_render_per_clip_luts_follow_timeline_order_and_leave_ungraded_clip_alone(tmp_path, source):
    warm, cool = look(tmp_path, "warm"), look(tmp_path, "cool")
    c = composition(source)
    # RGB source for the ungraded middle clip exercises mixed-input matrix
    # normalization; the two graded instances still share the YUV asset.
    rgb_source = tmp_path / "rgb chart.mkv"
    make_video(rgb_source, chart(320, 180))
    c.assets.append(AssetRef("rgb", str(rgb_source), sha256(rgb_source)))
    original = c.clips[0]
    # Same asset, nonzero trims, deliberately reverse stored order.
    c.clips = [replace(original, id="cool", src_in=.5, src_out=1.5, timeline_start=2, color=cool),
               replace(original, id="warm", src_in=1, src_out=2, timeline_start=1, color=warm),
               replace(original, id="plain", src=str(rgb_source), asset_id="rgb", src_in=0, src_out=1, timeline_start=0)]
    result = render(tmp_path, c, "cut")
    before = decode(source)
    for timestamp, color in ((.5, None), (1.5, warm), (2.5, cool)):
        expected = decode(rgb_source) if color is None else apply_cube(before, read_cube(color.lut_path))
        assert metrics(decode(result.output_path, timestamp), expected)["median_delta_e_2000"] <= 2
    manifest = json.loads((result.work_dir / "color-transforms.json").read_text())
    assert [e["clip_id"] for e in manifest["transforms"]] == ["warm", "cool"]
    assert result.filtergraph.count("lut3d=") == 2
