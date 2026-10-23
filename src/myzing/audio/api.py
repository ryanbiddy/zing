"""Public, opt-in audio-map analysis. Does not invoke the study/render paths."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from myzing import __version__
from .features import detect_onsets, segment_roles, spectral_features, speech_intervals, track_beats
from .loudness import measure_loudness
from .media import MAX_SECONDS, SAMPLE_RATE, decode_mono, ffmpeg_version, local_file, numpy
from .models import AudioMap, Segment

if TYPE_CHECKING:
    from myzing.schemas import Breakdown


def analyze(
    path: str | Path, *, breakdown: Breakdown | None = None,
    max_seconds: float = MAX_SECONDS,
) -> AudioMap:
    """Measure the first audio stream, at most ten minutes, starting at t=0.

    A supplied breakdown must describe this same file/time origin. No ASR is
    run here. ASR intervals are evidence, not verified spoken-word boundaries.
    """
    path = local_file(path)
    samples, truncated = decode_mono(path, max_seconds=max_seconds)
    duration = len(samples) / SAMPLE_RATE
    features = spectral_features(samples)
    words, warnings = speech_intervals(breakdown.words if breakdown else [], duration)
    breakdown_source = breakdown.meta.source_url if breakdown else None
    if breakdown is None:
        warnings.append("No breakdown supplied; speech cannot be confirmed by this energy/flatness heuristic.")
    else:
        warnings.append("Supplied word timings are assumed to use this file's time origin; ASR can be wrong.")
        if abs(breakdown.meta.duration - duration) > 0.25 and not truncated:
            warnings.append("Breakdown duration differs from decoded audio by more than 250 ms; verify source and timing alignment.")
    if truncated:
        warnings.append(f"Analysis truncated at {duration:.6f} seconds; all observations, including loudness, describe only this excerpt.")
    onsets = detect_onsets(features)
    tempo, beats = track_beats(onsets, duration, words)
    if tempo.status != "steady" and not words:
        from .pulse import layered_pulse
        fallback = layered_pulse(features, onsets, duration)
        if fallback:
            tempo, beats = fallback
    segments = segment_roles(features, duration, words)
    loudness = measure_loudness(path, max_seconds=duration)
    from .structure import analyze_structure, channel_quality
    structure = analyze_structure(features, tempo, beats, onsets, duration)
    if tempo.status != "steady" and not words and duration >= 16:
        from .pulse import layered_pulse
        from .features import HOP
        from .models import Onset
        for frame in range(0, len(features["rms"]), round(16 * SAMPLE_RATE / HOP)):
            start = frame * HOP / SAMPLE_RATE
            length = min(16, duration - start)
            if length < 8:
                continue
            local = {key: values[frame:frame + round(length * SAMPLE_RATE / HOP)] for key, values in features.items()}
            attacks = [Onset(o.time - start, o.strength) for o in onsets if start <= o.time < start + length]
            pulse, supported = track_beats(attacks, length, [])
            if pulse.status != "steady":
                found = layered_pulse(local, attacks, length)
                if found:
                    pulse, supported = found
            if pulse.status != "steady":
                continue
            sub = analyze_structure(local, pulse, supported, attacks, length)
            structure.rhythm_regions.append({"start": start, "end": start + length, "bpm": pulse.bpm,
                "confidence": pulse.confidence, "evidence": pulse.evidence,
                "beats": [start + t for t in supported], "downbeat_status": pulse.downbeat_status,
                "bars": [start + t for t in sub.bars]})
            structure.phrases.extend({**p, "time": start + p["time"], "region_start": start} for p in sub.phrases)
    structure.quality = channel_quality(path, duration, loudness.true_peak_dbtp)
    if float(features["rms"].max()) < 10 ** (-55 / 20) and loudness.integrated_lufs is not None and loudness.integrated_lufs > -50:
        segments = [Segment(0, duration, "uncertain", 0.0, "source is audible but mono downmix is near-silent; possible phase cancellation")]
        warnings.append("Source-channel loudness conflicts with near-silent mono audio; roles and beats are unavailable after possible channel cancellation.")
    if loudness.integrated_lufs is None:
        warnings.append("Integrated loudness is unavailable: audio is too short or below the EBU R128 absolute gate.")
    if duration < 3:
        warnings.append("Loudness range is not meaningful for excerpts shorter than three seconds.")
    warnings.append("Role and tempo confidence are heuristic evidence scores, not calibrated probabilities; onsets are attacks, not identified SFX.")
    warnings.append("Meter requires repeated four-beat accents; otherwise downbeats/bars/phrases are unknown. Metric phrases are candidates, not recovered song form.")
    from .tagging import tag_file, vocal_evidence
    tags = tag_file(path, max_seconds=max_seconds, speech=[(a, b) for a, b, _ in words])
    structure.vocals = vocal_evidence(tags, structure.vocals)
    warnings.extend(tags.warnings)
    warnings.append(structure.vocals["limits"])
    return AudioMap(
        source=str(path), duration_seconds=duration, sample_rate=SAMPLE_RATE,
        max_seconds=max_seconds, truncated=truncated, tempo=tempo, beats=beats,
        onsets=onsets, segments=segments, loudness=loudness, warnings=warnings,
        tool_versions={"zing": __version__, "audio_algorithm": "2.4", "numpy": numpy().__version__, "ffmpeg": ffmpeg_version()},
        breakdown_source=breakdown_source,
        structure=structure, tags=tags,
    )
