"""Offline tests for audio measurement: ffmpeg mocked at proc.run, VAD
mocked at the _run_vad seam; heuristic + parsing logic tested pure."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from myzing.study import audio


ASTATS_STDOUT = """\
frame:0    pts:0       pts_time:0
lavfi.astats.Overall.RMS_level=-21.400000
frame:1    pts:48000   pts_time:1
lavfi.astats.Overall.RMS_level=-19.87
frame:2    pts:96000   pts_time:2
lavfi.astats.Overall.RMS_level=-inf
"""


def test_parse_astats_floors_infinities():
    assert audio.parse_astats(ASTATS_STDOUT) == [-21.4, -19.9, -99.0]


def test_parse_astats_empty():
    assert audio.parse_astats("random ffmpeg banner\n") == []


# -- music heuristic --------------------------------------------------------

def seg(*pairs):
    return list(pairs)


def test_music_bed_detected_when_gaps_stay_loud():
    curve = [-15.0, -16.0, -18.0, -17.0, -16.5, -17.5]
    # speech only covers buckets 0-1; gaps at similar loudness = bed.
    segments = seg((0.0, 2.0))
    has, conf = audio._music_heuristic(curve, segments, 0.33, [])
    assert has is True
    assert 0.4 <= conf <= 0.85


def test_no_music_when_gaps_are_silent():
    curve = [-15.0, -16.0, -70.0, -75.0, -80.0, -72.0]
    segments = seg((0.0, 2.0))
    has, conf = audio._music_heuristic(curve, segments, 0.33, [])
    assert has is False
    assert conf >= 0.3


def test_wall_to_wall_speech_is_honest_unknown():
    warnings: list[str] = []
    curve = [-15.0, -16.0, -15.5]
    segments = seg((0.0, 3.0))
    has, conf = audio._music_heuristic(curve, segments, 1.0, warnings)
    assert (has, conf) == (False, 0.0)
    assert any("inconclusive" in w for w in warnings)


def test_no_speech_loud_audio_suggests_music():
    has, conf = audio._music_heuristic([-20.0, -21.0, -19.0], seg(), 0.0, [])
    assert (has, conf) == (True, 0.6)


def test_no_speech_silence_suggests_no_music():
    has, conf = audio._music_heuristic([-80.0, -99.0, -90.0], seg(), 0.0, [])
    assert (has, conf) == (False, 0.4)


def test_no_vad_means_no_music_call():
    warnings: list[str] = []
    has, conf = audio._music_heuristic([-20.0], None, 0.0, warnings)
    assert (has, conf) == (False, 0.0)
    assert any("needs VAD" in w for w in warnings)


def test_partition_buckets_by_overlap():
    speech, gaps = audio._partition_buckets(
        [-10.0, -20.0, -30.0], seg((0.0, 1.6))
    )
    assert speech == [-10.0, -20.0]   # bucket 1 has 0.6s overlap > 0.5
    assert gaps == [-30.0]


# -- measure_audio composition ----------------------------------------------

def ffmpeg_ok(stdout=ASTATS_STDOUT):
    def run(cmd, timeout=None):
        assert cmd[0] == "ffmpeg" and "asetnsamples=48000" in " ".join(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")
    return run


def test_measure_audio_end_to_end(monkeypatch):
    monkeypatch.setattr("myzing.study.audio.proc.run", ffmpeg_ok())
    monkeypatch.setattr(audio, "_run_vad", lambda p: [(0.0, 1.5)])

    result = audio.measure_audio(Path("media.mp4"), duration=3.0)

    a = result.audio
    assert a.loudness_curve == [-21.4, -19.9, -99.0]
    assert a.speech_ratio == 0.5
    assert a.has_voiceover is True
    assert result.provenance["vad_params"]["min_silence_duration_ms"] == 100
    assert result.warnings == []


def test_measure_audio_vad_missing_is_honest(monkeypatch):
    monkeypatch.setattr("myzing.study.audio.proc.run", ffmpeg_ok())

    def raises(p):
        raise ImportError("no faster_whisper")
    monkeypatch.setattr(audio, "_run_vad", raises)

    result = audio.measure_audio(Path("m.mp4"), duration=3.0)

    assert result.audio.speech_ratio == 0.0
    assert result.audio.has_voiceover is False
    assert result.audio.music_confidence == 0.0
    assert any("speech ratio skipped" in w for w in result.warnings)


def test_measure_audio_ffmpeg_failure_is_honest(monkeypatch):
    def failing(cmd, timeout=None):
        return subprocess.CompletedProcess(cmd, 1, "", "no audio stream found")
    monkeypatch.setattr("myzing.study.audio.proc.run", failing)
    monkeypatch.setattr(audio, "_run_vad", lambda p: [])

    result = audio.measure_audio(Path("m.mp4"), duration=3.0)

    assert result.audio.loudness_curve == []
    assert any("loudness curve skipped" in w for w in result.warnings)


def test_measure_audio_no_audio_frames_warns(monkeypatch):
    monkeypatch.setattr(
        "myzing.study.audio.proc.run", ffmpeg_ok(stdout="banner only\n")
    )
    monkeypatch.setattr(audio, "_run_vad", lambda p: [])

    result = audio.measure_audio(Path("m.mp4"), duration=3.0)

    assert any("loudness curve empty" in w for w in result.warnings)


def test_speech_ratio_clamped_and_rounded(monkeypatch):
    monkeypatch.setattr("myzing.study.audio.proc.run", ffmpeg_ok())
    monkeypatch.setattr(audio, "_run_vad", lambda p: [(0.0, 5.0)])

    result = audio.measure_audio(Path("m.mp4"), duration=3.0)

    assert result.audio.speech_ratio == 1.0
