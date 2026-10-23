"""LISTEN1 measurement battery on generated signals (NumPy only, no FFmpeg)."""
import pytest

np = pytest.importorskip("numpy")

from tools.eval import listen1_packet as packet

RATE = packet.RATE


def stereo(mono):
    return np.stack([mono, mono], axis=1)


def test_onsets_find_generated_clicks_within_ten_ms():
    signal = np.zeros(4 * RATE)
    times = [.5, 1.25, 2.0, 3.1]
    rng = np.random.default_rng(1)
    for t in times:
        i = int(t * RATE)
        signal[i:i + 480] += rng.standard_normal(480) * np.exp(-np.arange(480) / 80)
    found = [t for t, _ in packet.onsets(stereo(signal))]
    for t in times:
        assert min(abs(f - t) for f in found) < .01


def test_low_band_rise_marks_a_bass_entry_not_a_hat():
    t = np.arange(4 * RATE) / RATE
    bass = np.where(t >= 2.0, .5 * np.sin(2 * np.pi * 55 * t), 0)
    hats = np.where((t % .25) < .005, .3, 0) * np.sin(2 * np.pi * 9000 * t)
    rise = packet.low_band_rise(stereo(bass + hats), 2.1, span=1.0)
    assert abs(rise["time"] - 2.0) <= packet.WINDOW and rise["after_db"] - rise["before_db"] > 30


def test_rms_curve_and_correlation_read_level_and_phase():
    tone = .1 * np.sin(2 * np.pi * 440 * np.arange(RATE) / RATE)
    curve = packet.rms_curve(stereo(tone))
    assert len(curve) == 20 and np.allclose(curve, 20 * np.log10(.1 / np.sqrt(2)), atol=.1)
    assert packet.correlation(np.stack([tone, tone], axis=1))[0] == pytest.approx(1)
    assert packet.correlation(np.stack([tone, -tone], axis=1))[0] == pytest.approx(-1)


def test_timing_sheet_names_events_without_local_paths():
    record = {"case": "talking", "duration": 12.95, "width": 1920, "height": 1080,
              "track": {"id": "calm", "attribution": "The Cynic Project", "license": "CC0-1.0",
                        "source_offset": 71.225, "source_end": 84.175, "gain_db": -9.75},
              "cuts": [{"cut": 3.2}, {"cut": 8.5}], "planned_alignments": [], "moments": [],
              "speech_spans": [[.33, 1.85], [8.92, 12.62]], "duck": {"hold": .8, "depth_db": 9, "attack": .2, "release": .8, "plateau": .3, "gain_points": []}, "release_gap": 1.3,
              "duck_passages": [[0.0, 3.0], [8.92, 12.95]], "fades": {"in": [0, .15], "out": [11.95, 12.95]},
              "sidecar": {"integrated": {"integrated_lufs": -13.9, "true_peak_dbtp": -2.8, "loudness_range_lu": 8.9},
                          "music_integrated": {"integrated_lufs": -34.4}, "music_speech_lufs": -35.3,
                          "source_speech_lufs": -13.5, "speech_to_music_lu": 21.8, "music_gap_lufs": -30.2}}
    sheet = packet.timing_sheet(record)
    assert "- 3.200" in sheet and "ducked passage 8.920-12.950 (down from 8.720, held to the edit end)" in sheet
    assert "ducked passage 0.000-3.000 (ducked from the start, recovering 3.000-3.800)" in sheet
    assert "21.8 LU apart" in sheet and ":\\" not in sheet and "/Users" not in sheet
