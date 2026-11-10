"""Core readiness must not hide missing optional render prerequisites."""
import pytest

from myzing import doctor
from myzing.factory import tools


@pytest.fixture
def checks(monkeypatch, zing_workspace):
    rows = [doctor.Check("ffmpeg", doctor.REQUIRED, True, "installed")]
    monkeypatch.setattr(doctor, "run_checks", lambda: rows)
    return rows


@pytest.mark.parametrize("name,tier,data,blocked,fix", [
    ("faster-whisper", doctor.RECOMMENDED, {"cached": False},
     "transcription and spoken captions are off", "zing doctor --speech-model small.en --yes"),
    ("layout", doctor.OPTIONAL, {"model_verified": False},
     "factory framing and face-aware captions are off", "zing layout fetch-model"),
    ("hyperframes", doctor.OPTIONAL, {},
     "HyperFrames captions are off", "npm ci --ignore-scripts"),
    ("factory", doctor.OPTIONAL, {}, "factory rendering is off", "npm ci"),
])
def test_summary_names_each_missing_piece(checks, capsys, name, tier, data, blocked, fix):
    checks.append(doctor.Check(name, tier, name == "faster-whisper", "not downloaded", fix=fix,
                               degraded_mode=blocked, data=data))
    assert doctor.run([]) == 0
    out = capsys.readouterr().out
    assert "fully ready" not in out
    assert "core" in out.lower() and "ready" in out.lower()
    assert blocked in out and fix in out


def test_face_check_explains_factory_limit(monkeypatch, zing_workspace):
    from myzing.layout import detector, vision_models
    monkeypatch.setattr(doctor, "_has_module", lambda _: True)

    def version(name):
        if name == "opencv-python-headless":
            return "4.13.0.92"
        raise doctor.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(doctor.metadata, "version", version)
    monkeypatch.setattr(vision_models, "inventory", lambda: [])
    monkeypatch.setattr(detector, "verified_model", lambda _: False)
    check = doctor.check_layout()
    assert not check.ok
    assert "factory framing and face-aware captions are off" in check.degraded_mode
    assert "zing layout fetch-model" in check.fix


def test_factory_sidecar_is_reported(monkeypatch, zing_workspace):
    def missing():
        raise tools.FactoryError("The factory sidecar is not installed. Run npm ci in the sidecar folder.")

    monkeypatch.setattr(tools, "node_sidecar", missing)
    monkeypatch.setattr(doctor, "_which", lambda _: None)
    monkeypatch.setattr(doctor, "_has_module", lambda _: False)
    rows = doctor.run_checks()
    found = next((c for c in rows if c.name == "factory"), None)
    assert found is not None
    assert not found.ok and "npm ci" in found.fix
    assert "factory rendering is off" in found.degraded_mode


def test_core_failure_is_still_fatal(checks, capsys):
    checks[0].ok = False
    assert doctor.run([]) == 1
    assert "NOT ready" in capsys.readouterr().out


def test_missing_speech_model_summary_uses_real_check(checks, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "empty-hub"))
    monkeypatch.setenv("ZING_WHISPER_MODEL", "small.en")
    monkeypatch.setattr(doctor, "_has_module", lambda _: True)
    checks.append(doctor.check_whisper())
    assert checks[-1].ok and not checks[-1].data["cached"]
    assert doctor.run([]) == 0
    out = capsys.readouterr().out
    assert "core ready" in out
    assert "no speech model" in out
    assert "Transcription and spoken captions are off" in out
    assert "zing doctor --speech-model small.en --yes" in out
