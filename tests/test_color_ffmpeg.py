"""Real lut3d, output decode, recipe and color acceptance gates (5 tests)."""

import json
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy", reason="install myzing[color] for color FFmpeg tests")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from myzing import storage
from myzing.color import ColorError
from myzing.color.api import resolve_reference
from myzing.color.command import run
from myzing.color.cube import Cube, make_cube, read_cube, write_cube
from myzing.color.looks import apply_transform, transform_for
from myzing.color.measure import measure_video
from myzing.color.media import apply_video, frame, probe, run_media, sha256
from myzing.color.models import Measurement, Recipe
from myzing.color.science import delta_e_2000, rgb_to_lab
from myzing.schemas import Breakdown, Shot, VideoMeta
from tools.eval.color_fixture import chart, make_video

pytestmark = pytest.mark.ffmpeg


def test_identity_lut_preserves_pixels_and_audio(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    hostile = tmp_path / "color space's [test], path"
    hostile.mkdir()
    source, with_audio = hostile / "source.mkv", hostile / "source audio.mkv"
    make_video(source, chart())
    run_media([
        "ffmpeg", "-v", "error", "-nostdin", "-i", str(source),
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2:sample_rate=48000",
        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", str(with_audio),
    ])
    lut = write_cube(make_cube(transform_for("neutral")), hostile / "identity's [x],.cube")
    original_hash = sha256(with_audio)
    result = apply_video(lut, with_audio, hostile / "graded.mp4")
    output_metadata = probe(result["output_path"])[3]
    assert output_metadata["color_transfer"] == output_metadata["color_primaries"] == "bt709"
    assert output_metadata["color_space"] == "bt709"
    before = frame(with_audio, 0.5, 160, 120)
    after = frame(result["output_path"], 0.5, 160, 120)
    error = np.abs(after - before) * 255
    # Explicit codec tolerance: <= 5 codes at p99, <= 1.5 on average.
    assert np.percentile(error, 99) <= 5
    assert error.mean() <= 1.5
    def audio_hash(path):
        return run_media(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-c:a", "copy", "-f", "hash", "pipe:1"])
    assert audio_hash(with_audio) == audio_hash(result["output_path"])
    assert sha256(with_audio) == original_hash
    with pytest.raises(ColorError, match="exists"):
        apply_video(lut, with_audio, with_audio)


def test_ffmpeg_cube_channel_order_and_interpolation(tmp_path):
    source = tmp_path / "chart.mkv"
    make_video(source, chart())
    # Independently constructed affine LUT: R'=B, G'=R, B'=G, red fastest.
    rows = [[b / 2, r / 2, g / 2] for b in range(3) for g in range(3) for r in range(3)]
    write_cube(Cube(3, rows), tmp_path / "look.cube")
    before = frame(source, 0.5, 160, 120)
    after = frame(source, 0.5, 160, 120, lut_dir=tmp_path)
    np.testing.assert_allclose(after, before[..., [2, 0, 1]], atol=1 / 255 + 1e-9)


def test_known_grade_cli_recipe_and_rendered_delta_e_gate(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    source, reference = tmp_path / "clip.mkv", tmp_path / "reference.mkv"
    rgb = chart()
    make_video(source, rgb)
    make_video(reference, apply_transform(rgb, transform_for("teal-orange", 0.67)))
    out = tmp_path / "result's [color], grade"
    assert run(["match", "--reference", str(reference), "--clip", str(source),
                "--out", str(out), "--samples", "4", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    recipe = Recipe.from_dict(payload)
    assert json.loads((out / "recipe.json").read_text()) == payload
    assert recipe.match.chosen.transform.look == "teal-orange"
    assert abs(recipe.match.chosen.transform.strength - 0.67) <= 0.08
    assert recipe.cube_sha256 == sha256(recipe.cube_path)
    assert recipe.reference.sha256 == sha256(reference)
    assert recipe.clip.sha256 == sha256(source)
    assert read_cube(recipe.cube_path).size == 33
    assert len(recipe.reference.samples) == len(recipe.clip.samples) == 4
    assert recipe.color_space and recipe.color_version and recipe.tool_version
    assert "approximation" in recipe.interpretation
    preview = Path(recipe.preview_path)
    assert preview.is_relative_to(tmp_path / "zing-workspace")
    assert preview.read_bytes().startswith(b"\x89PNG")
    run_media(["ffmpeg", "-v", "error", "-i", str(preview), "-f", "null", "-"])
    output = tmp_path / "after.mp4"
    assert run(["apply", "--lut", recipe.cube_path, "--in", str(source), "--out", str(output), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["sha256"] == sha256(output)
    target, after = frame(reference, 0.5, 160, 120), frame(output, 0.5, 160, 120)
    median_de = float(np.median(delta_e_2000(rgb_to_lab(after), rgb_to_lab(target))))
    assert median_de <= 3, f"rendered median Delta E 2000 = {median_de:.6f}"


def test_measurement_breakdown_shots_and_low_confidence(tmp_path, zing_workspace):
    directory = storage.breakdown_dir("color-ref")
    directory.mkdir(parents=True)
    source = directory / "media.mkv"
    make_video(source, np.full((48, 64, 3), 0.4))
    shots = [Shot(0, 0, 0.75), Shot(1, 0.75, 2)]
    storage.save_breakdown(Breakdown(VideoMeta("local", "file", media_path="media.mkv"), shots=shots), "color-ref")
    path, loaded_shots = resolve_reference("color-ref")
    assert path == source.resolve() and loaded_shots == shots
    measured, _, _ = measure_video(path, count=4, shots=shots)
    assert Measurement.from_dict(measured.to_dict()) == measured
    assert {s.shot_index for s in measured.samples} == {0, 1}
    assert measured.coverage["shot_fraction"] == 1
    assert measured.confidence <= 0.2
    assert any("LOG-like" in w for w in measured.warnings)
    clipped = tmp_path / "clipped.mkv"
    make_video(clipped, np.zeros((48, 64, 3)))
    measured, _, _ = measure_video(clipped, count=2)
    assert any("clipped" in w for w in measured.warnings)
    assert measured.aggregate.clipping["black"] == 1


def test_tagged_hdr_fails_before_creating_match_outputs(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    source, hdr = tmp_path / "source.mkv", tmp_path / "hdr.mkv"
    make_video(source, chart())
    run_media(["ffmpeg", "-v", "error", "-i", str(source), "-c:v", "libx264", "-pix_fmt", "yuv444p",
               "-vf", "setparams=color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc",
               "-color_trc", "smpte2084", "-color_primaries", "bt2020", "-colorspace", "bt2020nc", str(hdr)])
    assert probe(hdr)[3]["color_transfer"] == "smpte2084", "HDR fixture lost its transfer tag"
    out = tmp_path / "match"
    status = run(["match", "--reference", str(hdr), "--clip", str(source), "--out", str(out), "--json"])
    error = json.loads(capsys.readouterr().out)
    assert status == 1
    assert "Unsupported LOG/HDR" in error["error"]
    assert not out.exists()
