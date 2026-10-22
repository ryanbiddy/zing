"""Audio contracts and failures, independent of optional NumPy/FFmpeg."""

from __future__ import annotations

import builtins
import json
import subprocess

import pytest

from myzing import cli, doctor
from myzing.audio import AudioMap, Loudness, Onset, Segment, Tempo, recommend_gain
from myzing.audio import media
from myzing.audio.loudness import parse_ebur128


def test_versioned_map_round_trip():
    original = AudioMap(
        "input.wav", 4.0, 22050, 600, False,
        Tempo("steady", 120.0, 0.9, "measured"), [0.2, 0.7], [Onset(0.2, 0.9)],
        [Segment(0, 4, "music", 0.6, "tonal")], Loudness(-20.2, 2.0, -8.0),
        ["meter unknown"], {"audio_algorithm": "1"},
    )
    payload = json.loads(json.dumps(original.to_dict(), allow_nan=False))
    assert AudioMap.from_dict(payload) == original
    assert payload["segments"][0]["version"] == 1
    assert payload["loudness"]["version"] == 1
    payload["tempo"]["version"] = 2
    with pytest.raises(ValueError, match="version"):
        AudioMap.from_dict(payload)


def test_unknown_version_and_invalid_confidence_rejected():
    with pytest.raises(ValueError, match="version"):
        Loudness.from_dict({"version": 2})
    with pytest.raises(ValueError, match="confidence"):
        Tempo(confidence=1.1)
    with pytest.raises(ValueError, match="steady"):
        Tempo(bpm=120)
    with pytest.raises(ValueError, match="finite"):
        Loudness(float("nan"), 1.0, -1.0)


def test_import_and_help_work_without_numpy(monkeypatch, capsys):
    real_import = builtins.__import__

    def without_numpy(name, *args, **kwargs):
        if name == "numpy":
            raise ImportError("test: numpy absent")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_numpy)
    assert cli.main(["--help"]) == 0
    assert "audio" in capsys.readouterr().out
    with pytest.raises(media.AudioError, match=r'myzing\[audio\]'):
        media.numpy()
    monkeypatch.setattr(doctor, "_has_module", lambda name: False)
    check = doctor.check_audio()
    assert not check.ok and check.tier == doctor.OPTIONAL
    assert 'myzing[audio]' in check.fix


def test_ffmpeg_missing_and_timeout_have_remedies(monkeypatch):
    monkeypatch.setattr(media.shutil, "which", lambda name: None)
    with pytest.raises(media.AudioError, match="zing doctor"):
        media.ffmpeg()
    monkeypatch.setattr(media.shutil, "which", lambda name: "ffmpeg")

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("ffmpeg", 1)

    monkeypatch.setattr(media.subprocess, "run", timeout)
    with pytest.raises(media.AudioError, match="shorter local excerpt"):
        media.run_ffmpeg([])


@pytest.mark.parametrize("seconds", [0, -1, 601, float("inf"), float("nan"), True])
def test_invalid_duration_limits(seconds):
    with pytest.raises(ValueError):
        media.duration_limit(seconds)


def test_cli_json_missing_file_and_breakdown(capsys, zing_workspace):
    assert cli.main(["audio", "analyze", "absent.wav", "--json"]) == 1
    assert "local file" in json.loads(capsys.readouterr().out)["error"]
    assert cli.main(["audio", "analyze", "absent.wav", "--breakdown", "missing", "--json"]) == 1
    assert "no breakdown" in json.loads(capsys.readouterr().out)["error"]


def test_ebur128_parser_rejects_incomplete_report():
    with pytest.raises(media.AudioError, match="summary"):
        parse_ebur128("I: -12.0 LUFS")
    with pytest.raises(media.AudioError, match="Incomplete"):
        parse_ebur128("Summary: I: -12.0 LUFS LRA: 1.0 LU")


def test_recommendation_round_trip_and_limiting_honesty():
    recommendation = recommend_gain(Loudness(-22, 3, -2))
    assert recommendation.gain_db == 8
    assert recommendation.limiter_required
    assert recommendation.predicted_lufs is None
    assert "level=0" in recommendation.ffmpeg_filter
    assert "latency=1" in recommendation.ffmpeg_filter
    assert type(recommendation).from_dict(recommendation.to_dict()) == recommendation
    with pytest.raises(ValueError, match="longer audible"):
        recommend_gain(Loudness(None, 0, None))
    with pytest.raises(ValueError, match="target_lufs"):
        recommend_gain(Loudness(-22, 3, -2), target_lufs=float("nan"))
    with pytest.raises(ValueError, match="target_dbtp"):
        recommend_gain(Loudness(-22, 3, -2), target_dbtp=2)


def test_invalid_and_outside_word_timings_are_visible():
    from myzing.audio.features import speech_intervals
    from myzing.schemas import Word

    intervals, warnings = speech_intervals([
        Word("valid", 1, 2, 0.85), Word("zero", 2, 2),
        Word("nan", float("nan"), 3), Word("negative", -1, 1),
        Word("bad-confidence", 1, 2, 1.5), Word("clip", 3.5, 5), Word("outside", 8, 9),
    ], 4)
    assert intervals == [(1.0, 2.0, 0.85), (3.5, 4, 0.9)]
    assert "4 invalid" in warnings[0]
    assert "2 supplied" in warnings[1]
