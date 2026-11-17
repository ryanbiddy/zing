"""Color settings, non-destructive caches, and small real FFmpeg color checks."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from myzing.factory import color
from myzing.factory.tools import FactoryError


def test_default_and_source_work_without_site_packages_or_media_tools(tmp_path):
    code = """
import json, sys
from pathlib import Path
from myzing.factory.color import normalize, prepare
directory = Path(sys.argv[1])
result = prepare(directory, {'color_look': 'source', 'color_exposure': 1})
assert result['frames_dir'] == str(directory.resolve() / 'frames')
assert result['color']['settings']['color_exposure'] == 1
assert result['color']['active'] is False
assert 'numpy' not in sys.modules
assert not directory.exists()
assert normalize({})['color_look'] == 'source'
print(json.dumps(result))
"""
    env = {**os.environ, "PYTHONPATH": str(Path(color.__file__).resolve().parents[2]),
           "PATH": "", "UOINK_URL": "http://127.0.0.1:1"}
    completed = subprocess.run([sys.executable, "-S", "-c", code, str(tmp_path / "not-created")],
                               env=env, capture_output=True, text=True, timeout=20,
                               **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("settings", [
    None, [], {"color_look": "missing"}, {"color_look": None}, {"color_strength": True},
    {"color_strength": -0.1}, {"color_strength": 1.01}, {"color_exposure": 1.01},
    {"color_exposure": -1.01}, {"color_temperature": 0.251}, {"color_tint": -0.251},
    {"color_tint": float("nan")}, {"color_tint": float("inf")}, {"color_tint": "0.1"},
    {"color_exposure": None}, {"color_strength": 10 ** 500},
])
def test_bad_settings_fail_before_creating_outputs(tmp_path, settings):
    with pytest.raises(FactoryError):
        color.prepare(tmp_path / "clip", settings)
    assert not (tmp_path / "clip").exists()


def test_zero_intensity_keeps_manual_corrections_and_cube_remains_finite():
    np = pytest.importorskip("numpy")
    from myzing.color.cube import apply_cube
    from myzing.color.science import linearize
    swatches = np.array([[0.2, 0.2, 0.2], [0.72, 0.47, 0.32], [0.35, 0.21, 0.15], [0.9, 0.75, 0.62]])
    identity = color.normalize({"color_look": "cinematic-cool", "color_strength": 0})
    np.testing.assert_allclose(apply_cube(swatches, color._cube(identity)), swatches, atol=1e-12)
    exposure = {**identity, "color_exposure": 1}
    brighter = apply_cube(swatches[:1], color._cube(exposure))
    np.testing.assert_allclose(linearize(brighter), linearize(swatches[:1]) * 2, rtol=0.01)
    warm = apply_cube(swatches[:1], color._cube({**identity, "color_temperature": 0.25}))
    magenta = apply_cube(swatches[:1], color._cube({**identity, "color_tint": 0.25}))
    assert warm[0, 0] > warm[0, 2]
    assert magenta[0, 0] > magenta[0, 1] and magenta[0, 2] > magenta[0, 1]
    look = color._cube(color.normalize({"color_look": "cinematic-cool"}))
    after = apply_cube(swatches, look)
    # Known warm swatches keep their color within six RGB8 codes at default
    # strength. This is a color-transform bound, not a general skin guarantee.
    assert np.max(np.abs(after[1:] - swatches[1:])) < 6 / 255
    assert np.isfinite(look.values).all()
    assert after[0, 2] > after[0, 0]  # neutral shadows gain a cool tint
    np.testing.assert_allclose(apply_cube([[0, 0, 0], [1, 1, 1]], look), [[0, 0, 0], [1, 1, 1]], atol=1e-12)


@pytest.fixture
def fake_clip(tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    directory = tmp_path / "clip with ' [punctuation],"
    frames = directory / "frames"
    frames.mkdir(parents=True)
    for number in (1, 2, 3):
        (frames / f"{number:05d}.jpg").write_bytes(f"original-{number}".encode())
    (directory / "cut.mp4").write_bytes(b"original-cut")
    monkeypatch.setattr(color, "_metadata", lambda d: ({"cut": {"color_space": "bt709"}}, ["test warning"]))
    monkeypatch.setattr(color, "ffmpeg", lambda: "ffmpeg")
    calls = []
    def render(*args, cwd=None):
        calls.append(args)
        for path in frames.glob("*.jpg"):
            (Path(cwd) / "frames" / path.name).write_bytes(b"graded-" + path.read_bytes())
    monkeypatch.setattr(color, "_run", render)
    return directory, calls


def test_cache_reuses_exact_content_and_invalidates_changed_frames_or_settings(fake_clip):
    directory, calls = fake_clip
    original = {p.name: p.read_bytes() for p in (directory / "frames").iterdir()}
    settings = {"color_look": "cinematic-cool"}
    first = color.prepare(directory, settings)
    cached = color.prepare(directory, settings)
    assert first == cached and len(calls) == 1
    assert first["color"]["active"] is True
    assert first["color"]["settings"] == color.normalize(settings)
    assert first["color"]["warnings"] == ["test warning"]
    assert {p.name: p.read_bytes() for p in (directory / "frames").iterdir()} == original
    assert (directory / "cut.mp4").read_bytes() == b"original-cut"
    # A changed source with the same filename and byte length must not reuse
    # the old output. The key is content-based, not an mtime/size shortcut.
    (directory / "frames" / "00002.jpg").write_bytes(b"changed--2")
    changed = color.prepare(directory, settings)
    assert changed["frames_dir"] != first["frames_dir"] and len(calls) == 2
    adjusted = color.prepare(directory, {**settings, "color_exposure": 0.2})
    assert adjusted["frames_dir"] != changed["frames_dir"] and len(calls) == 3


def test_incomplete_or_corrupted_cache_is_rebuilt(fake_clip):
    directory, calls = fake_clip
    settings = {"color_look": "cinematic-cool"}
    result = color.prepare(directory, settings)
    output = Path(result["frames_dir"])
    (output / "00002.jpg").unlink()
    assert color.prepare(directory, settings) == result
    assert (output / "00002.jpg").is_file() and len(calls) == 2
    (output / "00002.jpg").write_bytes(b"broken")
    color.prepare(directory, settings)
    assert (output / "00002.jpg").read_bytes() == b"graded-original-2" and len(calls) == 3
    assert len(list((directory / "color-cache").glob(".invalid-*"))) == 2


def test_incomplete_render_or_changing_source_never_publishes(fake_clip, monkeypatch):
    directory, _ = fake_clip
    settings = {"color_look": "cinematic-cool"}
    def incomplete(*args, cwd=None):
        (Path(cwd) / "frames" / "00001.jpg").write_bytes(b"one frame only")
    monkeypatch.setattr(color, "_run", incomplete)
    with pytest.raises(FactoryError, match="every source frame"):
        color.prepare(directory, settings)
    assert not list((directory / "color-cache").iterdir())
    def changes_source(*args, cwd=None):
        for path in (directory / "frames").glob("*.jpg"):
            (Path(cwd) / "frames" / path.name).write_bytes(b"graded-" + path.read_bytes())
        (directory / "frames" / "00002.jpg").write_bytes(b"new source frame")
    monkeypatch.setattr(color, "_run", changes_source)
    with pytest.raises(FactoryError, match="Source frames changed"):
        color.prepare(directory, settings)
    assert not list((directory / "color-cache").iterdir())


def test_original_hdr_metadata_is_not_hidden_by_a_reencoded_cut(tmp_path, monkeypatch):
    original = tmp_path / "original.mp4"
    original.touch()
    directory = tmp_path / "clip"
    directory.mkdir()
    (directory / "words.json").write_text(json.dumps({"source": str(original)}), encoding="utf-8")
    metadata = {"color_space": "bt709", "color_transfer": "bt709", "color_primaries": "bt709"}
    monkeypatch.setattr(color, "_probe_metadata", lambda path: (
        {**metadata, "color_transfer": "smpte2084", "color_primaries": "bt2020"} if path == original else metadata))
    with pytest.raises(FactoryError, match="Unsupported LOG/HDR"):
        color.prepare(directory, {"color_look": "cinematic-cool"})
    assert not (directory / "color-cache").exists()


def _real_clip(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    directory = tmp_path / "clip ' [space],"
    frames = directory / "frames"
    frames.mkdir(parents=True)
    for number in (1, 2, 3):
        image = Image.new("RGB", (96, 48), (45, 45, 45))
        image.paste((184, 120, 82), (32, 0, 64, 48))
        image.paste((30, 125 + number, 48), (64, 0, 96, 48))
        image.save(frames / f"{number:05d}.jpg", quality=98, subsampling=0)
    original = tmp_path / "source ' [space],.mp4"
    color._run(color.ffmpeg(), "-v", "error", "-nostdin", "-threads", "2", "-filter_threads", "1",
               "-framerate", "30", "-i", frames / "%05d.jpg", "-frames:v", "3",
               "-vf", "scale=in_color_matrix=bt601:out_color_matrix=bt709:out_range=tv,format=yuv420p",
               "-c:v", "libx264", "-threads", "2", "-color_primaries", "bt709", "-color_trc", "bt709",
               "-colorspace", "bt709", original)
    shutil.copyfile(original, directory / "cut.mp4")
    (directory / "words.json").write_text(json.dumps({"source": str(original)}), encoding="utf-8")
    return directory, original


@pytest.mark.ffmpeg
def test_real_frame_grade_preserves_sequence_source_and_warm_colors(tmp_path):
    np = pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")
    directory, original = _real_clip(tmp_path)
    before_hashes = {p.name: color._digest(p) for p in (directory / "frames").glob("*.jpg")}
    source_hash, cut_hash = color._digest(original), color._digest(directory / "cut.mp4")
    result = color.prepare(directory, {"color_look": "cinematic-cool"})
    output = Path(result["frames_dir"])
    assert sorted(p.name for p in output.iterdir()) == sorted(before_hashes)
    assert {p.name: color._digest(p) for p in (directory / "frames").glob("*.jpg")} == before_hashes
    assert color._digest(original) == source_hash and color._digest(directory / "cut.mp4") == cut_hash
    assert color.prepare(directory, {"color_look": "cinematic-cool"}) == result
    before = np.asarray(Image.open(directory / "frames" / "00001.jpg").convert("RGB"), dtype=float)
    after = np.asarray(Image.open(output / "00001.jpg").convert("RGB"), dtype=float)
    assert np.mean(np.abs(after[:, 40:56] - before[:, 40:56])) < 4
    assert np.mean(after[:, 8:24, 2] - after[:, 8:24, 0]) > 2
    # The FFmpeg RGB->JPEG roundtrip must follow the same cube to within the
    # small JPEG quantization error on uniform areas, including green content.
    from myzing.color.cube import apply_cube, read_cube
    expected = apply_cube(before / 255, read_cube(output.parent / "look.cube")) * 255
    assert np.mean(np.abs(after[:, [12, 48, 80]] - expected[:, [12, 48, 80]])) < 3
    assert result["color"]["frame_count"] == 3
    assert "original" in result["color"]["color_metadata"]


@pytest.mark.ffmpeg
def test_real_original_hdr_is_rejected_before_cache_creation(tmp_path):
    pytest.importorskip("numpy")
    directory, original = _real_clip(tmp_path)
    hdr = tmp_path / "original-hdr.mp4"
    color._run(color.ffmpeg(), "-v", "error", "-nostdin", "-i", original, "-c:v", "copy",
               "-color_trc", "smpte2084", "-color_primaries", "bt2020", "-colorspace", "bt2020nc", hdr)
    (directory / "words.json").write_text(json.dumps({"source": str(hdr)}), encoding="utf-8")
    assert color._probe_metadata(hdr)["color_transfer"] == "smpte2084"
    with pytest.raises(FactoryError, match="Unsupported LOG/HDR"):
        color.prepare(directory, {"color_look": "cinematic-cool"})
    assert not (directory / "color-cache").exists()
