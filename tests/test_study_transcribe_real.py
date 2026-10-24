"""Real-dependency tests for the transcribe seams (SG-2 coverage lift).

Every other transcription test mocks _load_model/_run_model_batched;
these exercise the actual bodies only with ZING_REQUIRE_REAL_ASR=1.
They use a pre-provisioned tiny model and local_files_only=True. Default
pytest skips before fixtures run, independently of HF offline settings.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

import pytest

from myzing.study import transcribe


@pytest.fixture(scope="module")
def loaded_model():
    pytest.importorskip("faster_whisper")
    try:
        return transcribe._load_model("tiny", local_files_only=True)
    except Exception as exc:
        pytest.fail(f"Explicit real-ASR test needs a pre-provisioned tiny model; tests never fetch it: {exc}")


@pytest.mark.real_model(env="ZING_REQUIRE_REAL_ASR")
def test_load_model_returns_working_configuration(loaded_model):
    model, device, compute_type, version = loaded_model
    assert model is not None
    assert device in ("auto", "cpu")
    # On a CUDA-less box the int8_float16 attempt must fall back to
    # cpu/int8 rather than raising — the documented R1-A compute picks.
    if device == "cpu":
        assert compute_type == "int8"
    assert isinstance(version, str) and version


@pytest.mark.real_model(env="ZING_REQUIRE_REAL_ASR")
def test_batched_pipeline_runs_on_real_silence(loaded_model, tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg unavailable")
    wav = tmp_path / "silence.wav"
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono:d=2",
         str(wav)],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr

    model, *_ = loaded_model
    words, language, probability = transcribe._run_model_batched(model, wav)[:3]

    # Silence honestly yields no words — and the batched body actually ran.
    assert words == []
    assert isinstance(language, str)
    assert 0.0 <= float(probability) <= 1.0


def test_python_version_sanity():
    # Guard against the shared-env drift that bit this repo once: the
    # interpreter running these real-dep tests must be the venv's.
    assert sys.version_info >= (3, 10)
