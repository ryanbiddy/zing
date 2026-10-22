"""Generated audio only. Timing tolerance is one frame at 30 fps (33 ms).

The synthetic speech-like fixture tests supplied-word segmentation, not an ASR
accuracy claim. Speech boundaries allow 100 ms, music coverage allows 250 ms
around activity transitions. No recordings or pretrained models are used.
"""

from __future__ import annotations

import json
import re
import subprocess
import wave

import pytest

from myzing import cli, storage
from myzing.audio import AudioMap, analyze, measure_loudness, recommend_gain
from myzing.audio.media import AudioError, SAMPLE_RATE, decode_mono
from myzing.schemas import Breakdown, VideoMeta, Word

pytestmark = pytest.mark.ffmpeg


@pytest.fixture
def np():
    # Keep tests collected without this extra, so required FFmpeg mode rejects
    # a missing runtime instead of silently reducing the selected gate count.
    return pytest.importorskip("numpy", reason='install myzing[audio] for audio acceptance tests')


def write_wave(path, samples, np, rate=44100):
    samples = np.asarray(samples)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1 if samples.ndim == 1 else samples.shape[1])
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return path


def click_track(np, duration=10, offset=0.25, bpm=120, rate=44100):
    audio = np.zeros(round(duration * rate))
    times = np.arange(offset, duration - 0.05, 60 / bpm)
    t = np.arange(round(0.025 * rate)) / rate
    click = 0.75 * np.exp(-t * 180) * np.cos(2 * np.pi * 1800 * t)
    for time in times:
        start = round(time * rate)
        audio[start:start + len(click)] += click
    return audio, times


@pytest.mark.parametrize("offset", [0.0, 0.173, 0.25])
def test_120_bpm_clicks_align_to_one_frame(np, tmp_path, offset):
    samples, expected = click_track(np, offset=offset)
    result = analyze(write_wave(tmp_path / "120 bpm.wav", samples, np))
    assert result.tempo.status == "steady", result.tempo
    assert abs(result.tempo.bpm - 120) <= 1
    assert result.tempo.confidence >= 0.75
    assert len(result.beats) == len(expected)
    assert np.max(np.abs(np.array(result.beats) - expected)) <= 1 / 30
    assert result.tempo.downbeat_status == "unknown" and not result.tempo.downbeats
    assert {item.time for item in result.onsets}.issuperset(result.beats)
    assert AudioMap.from_dict(json.loads(json.dumps(result.to_dict(), allow_nan=False))) == result


@pytest.mark.parametrize("kind", ["white", "colored", "drone"])
def test_ambient_has_no_invented_grid(np, tmp_path, kind):
    rng = np.random.default_rng(1601)
    samples = rng.normal(0, 0.035, 44100 * 10)
    t = np.arange(len(samples)) / 44100
    if kind == "colored":
        samples = np.convolve(samples, np.ones(64) / 8, mode="same")
        samples *= 0.7 + 0.3 * np.sin(2 * np.pi * 0.13 * t)
    elif kind == "drone":
        samples = 0.07 * np.sin(2 * np.pi * 110 * t) + 0.03 * np.sin(2 * np.pi * 164.81 * t) + samples * 0.1
    result = analyze(write_wave(tmp_path / f"ambient-{kind}.wav", samples, np))
    assert result.tempo.status in {"none", "unknown"}
    assert result.tempo.bpm is None and result.beats == []


def test_speech_over_music_cli_with_supplied_breakdown(np, tmp_path, zing_workspace, capsys):
    rate = 44100
    t = np.arange(rate * 9) / rate
    music = 0.06 * np.sin(2 * np.pi * 220 * t) + 0.04 * np.sin(2 * np.pi * 330 * t)
    music[t < 1] = 0
    speech_spans = [(2.0, 3.2), (4.0, 5.4), (6.2, 7.6)]
    samples = music.copy()
    for start, end in speech_spans:
        active = (t >= start) & (t < end)
        local = t[active] - start
        # Harmonic formant-like carrier and irregular syllable envelope.
        # No human speech/model/recording is included.
        envelope = 0.35 + 0.65 * np.sin(2 * np.pi * (3.2 * local + 0.4 * local**2)) ** 2
        carrier = sum(np.sin(2 * np.pi * f * local) / (i + 1) for i, f in enumerate([130, 650, 1300, 2600]))
        samples[active] += 0.13 * envelope * carrier
    source = write_wave(tmp_path / "speech and music.wav", samples, np)
    breakdown = Breakdown(
        meta=VideoMeta(str(source), "file", duration=9, media_path=str(source)),
        words=[Word("generated", start, end, 0.88) for start, end in speech_spans],
    )
    storage.save_breakdown(breakdown, slug="audio-fixture")
    assert cli.main(["audio", "analyze", str(source), "--breakdown", "audio-fixture", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    result = AudioMap.from_dict(payload)
    speech = [s for s in result.segments if s.label == "speech"]
    assert len(speech) == len(speech_spans)
    for observed, expected in zip(speech, speech_spans):
        assert abs(observed.start - expected[0]) <= 0.1
        assert abs(observed.end - expected[1]) <= 0.1
        assert observed.confidence == 0.88
    silence_duration = sum(s.end - s.start for s in result.segments if s.label == "silence")
    assert abs(silence_duration - 1) <= 0.1
    music_duration = sum(s.end - s.start for s in result.segments if s.label == "music")
    expected_music_only = 8 - sum(end - start for start, end in speech_spans)
    assert abs(music_duration - expected_music_only) <= 0.5  # <=250 ms per transition region
    assert result.segments[0].start == 0 and result.segments[-1].end == 9
    assert all(a.end == b.start for a, b in zip(result.segments, result.segments[1:]))
    assert any("background" in s.evidence for s in speech)
    assert result.breakdown_source == str(source)


def test_irregular_speech_like_activity_is_not_a_beat_grid(np, tmp_path):
    rate = 44100
    samples = np.zeros(rate * 10)
    rng = np.random.default_rng(1616)
    time = 0.3
    while time < 9.5:
        duration = float(rng.uniform(0.09, 0.25))
        local = np.arange(round(duration * rate)) / rate
        syllable = np.sin(np.pi * local / duration) ** 2 * (
            0.12 * np.sin(2 * np.pi * 140 * local) + 0.06 * np.sin(2 * np.pi * 700 * local)
        )
        start = round(time * rate)
        samples[start:start + len(syllable)] += syllable
        time += float(rng.uniform(0.26, 0.67))
    result = analyze(write_wave(tmp_path / "speech-like.wav", samples, np))
    assert result.tempo.status in {"none", "unknown"} and not result.beats
    assert any(s.label == "uncertain" for s in result.segments)
    assert any("speech cannot be confirmed" in warning for warning in result.warnings)


def test_loudness_matches_independent_ffmpeg_source_channel_report(np, tmp_path):
    rate = 48000
    t = np.arange(rate * 12) / rate
    envelope = np.where(t < 4, 0.03, np.where(t < 8, 0.12, 0.07))
    left = envelope * np.sin(2 * np.pi * 997 * t)
    right = -left  # cancellation after downmix must NOT corrupt source loudness
    source = write_wave(tmp_path / "stereo.wav", np.column_stack((left, right)), np, rate)
    measured = measure_loudness(source)
    reference = subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-i", str(source),
        "-af", "ebur128=peak=true", "-f", "null", "-",
    ], capture_output=True, text=True, check=True, timeout=30).stderr.rsplit("Summary:", 1)[1]
    # Separate oracle: direct report extraction rather than the production parser.
    assert measured.integrated_lufs == float(re.search(r"I:\s*([-\d.]+) LUFS", reference)[1])
    assert measured.loudness_range_lu == float(re.search(r"LRA:\s*([\d.]+) LU", reference)[1])
    assert measured.true_peak_dbtp == float(re.search(r"Peak:\s*([-\d.]+) dBFS", reference)[1])
    assert measured.loudness_range_lu > 0
    mapped = analyze(source)
    assert mapped.loudness == measured
    assert all(segment.label == "uncertain" for segment in mapped.segments)
    assert any("cancellation" in warning for warning in mapped.warnings)


@pytest.mark.parametrize("transient", [False, True])
def test_recommended_gain_hits_target_on_remeasurement(np, tmp_path, transient):
    rate = 48000
    t = np.arange(rate * 10) / rate
    samples = 0.06 * np.sin(2 * np.pi * 997 * t)
    if transient:
        samples[rate * 4:rate * 4 + 8] = 0.9
    source = write_wave(tmp_path / "quiet.wav", samples, np, rate)
    recommendation = recommend_gain(measure_loudness(source), target_lufs=-14, target_dbtp=-1)
    assert recommendation.limiter_required is transient
    output = tmp_path / "adjusted.wav"
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-i", str(source), "-af", recommendation.ffmpeg_filter,
        "-c:a", "pcm_f32le", "-ar", "48000", str(output),
    ], check=True, capture_output=True, timeout=30)
    measured = measure_loudness(output)
    assert abs(measured.integrated_lufs - (-14)) <= 0.5
    assert measured.true_peak_dbtp <= -1


@pytest.mark.parametrize("duration", [0.08, 4])
def test_silence_is_null_loudness_without_grid(np, tmp_path, duration):
    result = analyze(write_wave(tmp_path / "silence.wav", np.zeros(round(44100 * duration)), np))
    assert result.beats == [] and result.onsets == []
    assert result.loudness.integrated_lufs is None and result.loudness.true_peak_dbtp is None
    assert all(s.label == "silence" for s in result.segments)
    json.dumps(result.to_dict(), allow_nan=False)


def test_analysis_and_loudness_share_bounded_excerpt(np, tmp_path):
    t = np.arange(44100 * 4) / 44100
    samples = np.where(t < 2, 0.04, 0.6) * np.sin(2 * np.pi * 1000 * t)
    source = write_wave(tmp_path / "two levels.wav", samples, np)
    pcm, truncated = decode_mono(source, max_seconds=2)
    assert len(pcm) == SAMPLE_RATE * 2 and truncated
    result = analyze(source, max_seconds=2)
    assert result.truncated and result.duration_seconds == 2
    reference = write_wave(tmp_path / "first half.wav", samples[:44100 * 2], np)
    assert result.loudness == measure_loudness(reference)
    assert not analyze(reference, max_seconds=2).truncated
    assert all(o.time < 2 for o in result.onsets)
    assert all(s.end <= 2 for s in result.segments)
    assert any("truncated" in warning for warning in result.warnings)


def test_video_without_audio_fails_with_remedy(np, tmp_path):
    source = tmp_path / "silent-video.mp4"
    subprocess.run([
        "ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=s=32x32:d=0.2",
        "-an", "-c:v", "mpeg4", str(source),
    ], check=True, capture_output=True, timeout=30)
    with pytest.raises(AudioError, match="decodable audio stream"):
        analyze(source)
