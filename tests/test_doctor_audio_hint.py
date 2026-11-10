"""The audio-ml fix names only the missing piece."""
import pytest

from myzing import doctor, storage
from myzing.audio import tag_models


@pytest.mark.parametrize("version,install", [("2.1.0", False), ("1.12.0", True), (None, True)])
def test_audio_ml_fix_skips_the_install_when_the_runtime_is_fine(monkeypatch, tmp_path, version, install):
    monkeypatch.setattr(doctor, "_has_module", lambda name: version is not None)
    monkeypatch.setattr(tag_models, "runtime_version", lambda: version)
    with storage.use_workspace(tmp_path):
        result = doctor.check_audio_ml()
    assert not result.ok
    assert tag_models.FETCH_HINT in result.fix
    assert ("myzing[audio-ml]" in result.fix) is install


def test_audio_ml_fix_names_only_the_runtime_when_weights_are_verified(monkeypatch):
    monkeypatch.setattr(doctor, "_has_module", lambda name: True)
    monkeypatch.setattr(tag_models, "runtime_version", lambda: "1.12.0")
    monkeypatch.setattr(tag_models, "model_paths", lambda: {})
    result = doctor.check_audio_ml()
    assert result.fix == doctor._install_command("myzing[audio-ml]")
