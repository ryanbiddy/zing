"""Windowed CED observations. Scores are model confidences, not calibrated odds.

Ten-second context with one-second hops: these are overlapping clip tags, not
frame-accurate event boundaries or proof of separated music/speech stems.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from myzing.contracts import Record
from . import tag_models

VOCALS = {"Singing", "Male singing", "Female singing", "Child singing", "Choir", "Rapping", "Humming", "Vocal music", "Chant"}
SPEECH = {"Speech", "Male speech, man speaking", "Female speech, woman speaking", "Child speech, kid speaking", "Conversation", "Narration, monologue"}
INSTRUMENTS = {"Musical instrument", "Piano", "Electric piano", "Keyboard (musical)", "Synthesizer", "Guitar", "Acoustic guitar", "Electric guitar", "String section", "Orchestra"}
EVENTS = {"Laughter", "Giggle", "Chuckle, chortle", "Belly laugh", "Applause", "Clapping"}
LABELS = VOCALS | SPEECH | INSTRUMENTS | EVENTS | {"Music", "Background music"}
WINDOW_SECONDS = 10.0
HOP_SECONDS = 1.0
THRESHOLD = .2
WEAK_THRESHOLD = .02


@dataclass
class AudioTags(Record):
    status: str = "unavailable"
    method: str = "heuristic_fallback"
    labels: list[dict] = field(default_factory=list)
    windows: list[dict] = field(default_factory=list)
    music_under_speech: list[dict] = field(default_factory=list)
    moment_candidates: list[dict] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    version: int = 1


def _score(scores, labels):
    return max((scores.get(label, 0.0) for label in labels), default=0.0)


def tag_samples(samples, sample_rate: int, *, speech=()) -> AudioTags:
    """Only verified local models. An absent/broken optional runtime is a fallback."""
    result = AudioTags()
    try:
        engine = tag_models.engine()
        from .media import numpy
        np = numpy()
        if sample_rate <= 0 or len(samples) == 0 or not np.isfinite(samples).all():
            raise ValueError("tagging requires finite nonempty mono audio and a positive sample rate")
        speech = [(float(a), float(b)) for a, b in speech]
        duration = len(samples) / sample_rate
        # The last context ends at the source end, without one-second slivers.
        starts = list(range(0, max(1, math.floor(duration - WINDOW_SECONDS) + 1), int(HOP_SECONDS)))
        if duration > WINDOW_SECONDS and starts[-1] < duration - WINDOW_SECONDS:
            starts.append(duration - WINDOW_SECONDS)
        peaks = dict.fromkeys(sorted(LABELS), 0.0)
        for start in starts:
            end = min(duration, start + WINDOW_SECONDS)
            stream = engine.create_stream()
            waveform = np.ascontiguousarray(samples[round(start * sample_rate):round(end * sample_rate)], dtype=np.float32)
            if len(waveform) < sample_rate:
                waveform = np.pad(waveform, (0, sample_rate - len(waveform)))
            stream.accept_waveform(sample_rate=sample_rate, waveform=waveform)
            scores = {event.name: float(event.prob) for event in engine.compute(stream)}
            if any(not math.isfinite(v) or not 0 <= v <= 1 for v in scores.values()):
                raise ValueError("CED returned invalid confidence values")
            labels = [{"label": name, "confidence": round(scores.get(name, 0.0), 6)} for name in sorted(LABELS)]
            result.windows.append({"start": start, "end": round(end, 6), "labels": labels})
            for name in peaks:
                peaks[name] = max(peaks[name], scores.get(name, 0.0))
            music = _score(scores, {"Music", "Background music"} | INSTRUMENTS)
            voice = _score(scores, SPEECH)
            overlaps = [(max(start, a), min(end, b)) for a, b in speech if max(start, a) < min(end, b)]
            if music >= WEAK_THRESHOLD and (overlaps or voice >= THRESHOLD):
                result.music_under_speech.append({"start": start, "end": round(end, 6),
                    "confidence": round(min(music, voice) if not overlaps else music, 6),
                    "strength": "weak candidate" if music < THRESHOLD else "candidate",
                    "music_confidence": round(music, 6), "speech_confidence": round(voice, 6),
                    "speech_basis": "supplied word intervals" if overlaps else "CED speech tags",
                    "speech_intervals": [list(pair) for pair in overlaps],
                    "evidence": "Music and speech in the same context window; candidate baked-in score, not source separation."})
            for label in ("Laughter", "Applause"):
                family = {"Laughter", "Giggle", "Chuckle, chortle", "Belly laugh"} if label == "Laughter" else {"Applause", "Clapping"}
                score = _score(scores, family)
                if score >= THRESHOLD:
                    result.moment_candidates.append({"start": start, "end": round(end, 6),
                        "kind": label.lower(), "confidence": round(score, 6),
                        "evidence": "CED context tag; event boundary unmeasured"})
        result.labels = [{"label": name, "confidence": round(value, 6)} for name, value in peaks.items()]
        result.status, result.method = "measured", "sherpa-onnx/ced-mini-int8"
        result.provenance = {"repository": tag_models.REPOSITORY, "revision": tag_models.REVISION,
            "model_sha256": tag_models.ASSETS["model.int8.onnx"][0], "license": "Apache-2.0",
            "window_seconds": WINDOW_SECONDS, "hop_seconds": HOP_SECONDS, "threshold": THRESHOLD, "weak_candidate_threshold": WEAK_THRESHOLD,
            "aggregation": "maximum across overlapping windows", "network_used": False}
        result.warnings.append("CED confidence is uncalibrated; overlapping 10-second tags do not locate exact events or prove simultaneous sources.")
    except Exception as exc:
        # Discard partial model output: a failed run cannot silently look complete.
        result = AudioTags(warnings=[f"Learned audio tagging unavailable ({exc}); heuristic fallback. Install {tag_models.INSTALL_HINT}; provision with {tag_models.FETCH_HINT}."])
    return result


def vocal_evidence(tags: AudioTags, heuristic: dict) -> dict:
    if tags.status != "measured":
        return {**heuristic, "method": "heuristic_fallback"}
    scores = {row["label"]: row["confidence"] for row in tags.labels}
    vocal = _score(scores, VOCALS)
    instrument = _score(scores, INSTRUMENTS)
    # Instrument confidence alone cannot veto a real voice over accompaniment.
    corroborated = vocal >= WEAK_THRESHOLD and heuristic.get("status") == "possible"
    status = "possible" if vocal >= THRESHOLD or corroborated else "not_detected" if vocal < WEAK_THRESHOLD else "unknown"
    return {"status": status, "confidence": vocal, "instrument_confidence": instrument,
            "method": tags.method, "labels": tags.labels, "heuristic": heuristic,
            "strength": "candidate" if vocal >= THRESHOLD else "weak corroborated candidate" if corroborated else "low model evidence",
            "evidence": "maximum singing-family confidence across CED context windows",
            "limits": "CED is an uncalibrated tagger; quiet or masked singing may be missed. No lyric recognition or source separation."}
