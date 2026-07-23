from __future__ import annotations

import hashlib
import json
import os
import subprocess
import wave
from array import array
from pathlib import Path

import pytest

from myzing.render.assemble import VoiceoverScript, render_assembled_edl
from myzing.render.tts import SynthesisResult, default_tts_provider
from myzing.schemas import Clip, EDL
from tools.eval.voiceover import evaluate_real_voiceover


def _write_voice(path: Path, sample_rate: int = 24_000) -> SynthesisResult:
    samples = array("h", [0, 2_000, -2_000, 4_000, -4_000] * 4_800)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(samples.tobytes())
    return SynthesisResult(
        path=path,
        provider="kokoro-onnx",
        voice="af_sarah",
        sample_rate=sample_rate,
        duration=len(samples) / sample_rate,
    )


def _fake_volume_runner(command, **kwargs):
    start = command[command.index("-ss") + 1]
    mean = -91.0 if start == "0.050000" else -23.0
    return subprocess.CompletedProcess(
        command,
        0,
        stdout="",
        stderr=f"mean_volume: {mean:.1f} dB\nmax_volume: -8.0 dB\n",
    )


def test_real_voiceover_probe_pins_assets_wav_and_render_delta(
    tmp_path: Path,
) -> None:
    model = tmp_path / "model.onnx"
    voices = tmp_path / "voices.bin"
    model.write_bytes(b"model")
    voices.write_bytes(b"voices")
    synthesis = _write_voice(tmp_path / "voice.wav")
    rendered = tmp_path / "render.mp4"
    rendered.write_bytes(b"render")

    report = evaluate_real_voiceover(
        model,
        voices,
        synthesis,
        rendered,
        expected_model_sha256=hashlib.sha256(b"model").hexdigest(),
        expected_voices_sha256=hashlib.sha256(b"voices").hexdigest(),
        baseline_window=(0.05, 0.2),
        active_window=(1.0, 0.5),
        run=_fake_volume_runner,
    )

    assert report["passed"] is True
    assert report["assets"]["passed"] is True
    assert report["wav"]["sample_rate"] == 24_000
    assert report["wav"]["channels"] == 1
    assert report["wav"]["rms_dbfs"] > -30.0
    assert report["render"]["voice_gain_over_baseline_db"] == 68.0


def test_real_voiceover_probe_mutations_fail_only_target_dimension(
    tmp_path: Path,
) -> None:
    model = tmp_path / "model.onnx"
    voices = tmp_path / "voices.bin"
    model.write_bytes(b"model")
    voices.write_bytes(b"voices")
    synthesis = _write_voice(tmp_path / "voice.wav")
    rendered = tmp_path / "render.mp4"
    rendered.write_bytes(b"render")
    expected_model = hashlib.sha256(b"model").hexdigest()
    expected_voices = hashlib.sha256(b"voices").hexdigest()

    wrong_asset = evaluate_real_voiceover(
        model,
        voices,
        synthesis,
        rendered,
        expected_model_sha256="0" * 64,
        expected_voices_sha256=expected_voices,
        baseline_window=(0.05, 0.2),
        active_window=(1.0, 0.5),
        run=_fake_volume_runner,
    )

    assert wrong_asset["passed"] is False
    assert wrong_asset["assets"]["model_sha256_passed"] is False
    assert wrong_asset["assets"]["voices_sha256_passed"] is True
    assert wrong_asset["wav"]["passed"] is True
    assert wrong_asset["render"]["passed"] is True

    def flat_volume(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="",
            stderr="mean_volume: -30.0 dB\nmax_volume: -8.0 dB\n",
        )

    inaudible_render = evaluate_real_voiceover(
        model,
        voices,
        synthesis,
        rendered,
        expected_model_sha256=expected_model,
        expected_voices_sha256=expected_voices,
        baseline_window=(0.05, 0.2),
        active_window=(1.0, 0.5),
        run=flat_volume,
    )

    assert inaudible_render["passed"] is False
    assert inaudible_render["assets"]["passed"] is True
    assert inaudible_render["wav"]["passed"] is True
    assert inaudible_render["render"]["passed"] is False


@pytest.mark.skipif(
    os.environ.get("ZING_REQUIRE_KOKORO") != "1",
    reason="set ZING_REQUIRE_KOKORO=1 for the optional real Kokoro check",
)
def test_real_kokoro_voiceover_survives_assembled_render(
    tmp_path: Path,
) -> None:
    source = tmp_path / "silent-source.mp4"
    generated = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=teal:s=320x180:r=24:d=6",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo",
            "-t",
            "6",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(source),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert generated.returncode == 0, generated.stderr

    provider = default_tts_provider()
    result = render_assembled_edl(
        EDL(
            clips=[Clip(str(source), 0.0, 6.0, 0.0)],
            width=320,
            height=180,
            fps=24.0,
        ),
        tmp_path / "real-vo-render.mp4",
        scripts=[
            VoiceoverScript(
                "Open with the result. Zing turns measured evidence into "
                "a creator-ready draft.",
                timeline_start=0.5,
            )
        ],
        provider=provider,
        base_dir=tmp_path,
    )
    report = evaluate_real_voiceover(
        provider.model_path,
        provider.voices_path,
        result.voiceovers[0],
        result.render.output_path,
        baseline_window=(0.05, 0.2),
        active_window=(1.0, 0.5),
    )

    assert report["passed"] is True, json.dumps(report, indent=2)
