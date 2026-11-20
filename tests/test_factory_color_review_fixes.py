"""Regression tests for source corrections, frame paths and cache publication."""
import errno
import shutil
from pathlib import Path

import pytest

from myzing.factory import color, pipeline
from myzing.factory.tools import FactoryError
from test_factory_color import _real_clip, fake_clip


@pytest.mark.parametrize("control", ["color_exposure", "color_temperature", "color_tint"])
def test_source_corrections_grade_and_invalidate_old_render(fake_clip, control):
    np = pytest.importorskip("numpy")
    from myzing.color.cube import apply_cube, read_cube

    folder, calls = fake_clip
    settings = {control: .2}
    output = color.prepare(folder, settings)
    recipe = output["color"]
    assert recipe["active"] and len(calls) == 1
    assert not pipeline._color_current({}, settings)
    assert not pipeline._color_current({"color": {**recipe, "active": False}}, settings)
    assert pipeline._color_current({"color": recipe}, settings)
    cube = read_cube(Path(output["frames_dir"]).parent / "look.cube")
    swatches = [[.2, .2, .2], [.72, .47, .32]]
    manual_only = color._cube(color.normalize({**settings, "color_look": "cinematic-cool", "color_strength": 0}))
    np.testing.assert_allclose(apply_cube(swatches, cube), apply_cube(swatches, manual_only), atol=1e-6)
    assert not np.allclose(apply_cube(swatches, cube), swatches)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="needs FFmpeg and ffprobe")
def test_grade_in_percent_folder(tmp_path):
    pytest.importorskip("numpy")
    folder, _ = _real_clip(tmp_path)
    renamed = tmp_path / "100% done"
    folder.rename(renamed)
    result = color.prepare(renamed, {"color_look": "cinematic-cool"})
    assert result["color"]["frame_count"] == 3


def test_cache_race_reuses_verified_winner(fake_clip, monkeypatch):
    folder, _ = fake_clip
    original = Path.rename

    def competing_publish(staging, target):
        if staging.name.startswith(".staging-"):
            shutil.copytree(staging, target)
            raise OSError(errno.ENOTEMPTY, "directory not empty")
        return original(staging, target)

    monkeypatch.setattr(Path, "rename", competing_publish)
    result = color.prepare(folder, {"color_look": "cinematic-cool"})
    assert (Path(result["frames_dir"]) / "00003.jpg").read_bytes() == b"graded-original-3"


def test_locked_staging_cleanup_preserves_encoder_error(fake_clip, monkeypatch):
    folder, _ = fake_clip
    remove = shutil.rmtree

    def locked(path, *args, ignore_errors=False, **kwargs):
        if not ignore_errors:
            raise PermissionError("file still open")
        remove(path, *args, **kwargs)

    def fail(*args, **kwargs):
        raise FactoryError("encoder stopped")

    monkeypatch.setattr(shutil, "rmtree", locked)
    monkeypatch.setattr(color, "_run", fail)
    with pytest.raises(FactoryError, match="encoder stopped"):
        color.prepare(folder, {"color_look": "cinematic-cool"})
