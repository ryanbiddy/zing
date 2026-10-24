"""Windowed CED observations. Scores are model confidences, not calibrated odds.

Five-second context with one-second hops: these are overlapping clip tags, not
frame-accurate event boundaries or proof of separated music/speech stems.
Five seconds, not ten: CED pools over its whole input, so a sung phrase or a
laugh of two or three seconds is diluted by ten seconds of accompaniment.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from myzing.contracts import Record
from . import tag_models

ALGORITHM = "ced-windows-2"
SAMPLE_RATE = 16_000  # CED's own rate; sherpa-onnx would otherwise resample (and log) every window
# The complete AudioSet "Singing" subtree (Choir, Yodeling, Chant > Mantra, the
# gendered and synthetic singing classes, Rapping), plus Humming and the
# vocal-music genre. Wordless or chant-like vocals often land on Mantra/Yodeling.
VOCALS = {"Singing", "Choir", "Yodeling", "Chant", "Mantra", "Male singing", "Female singing", "Child singing",
          "Synthetic singing", "Rapping", "Humming", "Vocal music", "A capella"}
SPEECH = {"Speech", "Male speech, man speaking", "Female speech, woman speaking", "Child speech, kid speaking", "Conversation", "Narration, monologue"}
INSTRUMENTS = {"Musical instrument", "Piano", "Electric piano", "Keyboard (musical)", "Synthesizer", "Guitar", "Acoustic guitar", "Electric guitar", "String section", "Orchestra"}
MUSIC = {"Music", "Background music"} | INSTRUMENTS
LAUGHTER = {"Laughter", "Baby laughter", "Giggle", "Snicker", "Belly laugh", "Chuckle, chortle"}
APPLAUSE = {"Applause", "Clapping"}
EVENTS = LAUGHTER | APPLAUSE
LABELS = VOCALS | SPEECH | MUSIC | EVENTS
WINDOW_SECONDS = 5.0
HOP_SECONDS = 1.0
# Strong candidate. Below WEAK_THRESHOLD a family is treated as absent: on the
# licensed acceptance clips, speech-only and instrumental windows reach 0.08
# (singing family) and 0.05 (music under plain speech) at most.
THRESHOLD = .2
WEAK_THRESHOLD = .1


@dataclass
class AudioTags(Record):
    status: str = "unavailable"
    method: str = "heuristic_fallback"
    labels: list[dict] = field(default_factory=list)
    windows: list[dict] = field(default_factory=list)
    music_under_speech: list[dict] = field(default_factory=list)
    moment_candidates: list[dict] = field(default_factory=list)
    vocal_spans: list[dict] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    version: int = 1  # Record contract; provenance.algorithm carries the windowing revision


def _score(scores, labels):
    return max((scores.get(label, 0.0) for label in labels), default=0.0)


def _best(scores, labels):
    label = max(sorted(labels), key=lambda name: scores.get(name, 0.0))
    return label, scores.get(label, 0.0)


def _spans(rows, key, floor):
    """Merge overlapping windows whose score reaches floor; keep each span's peak."""
    spans = []
    for row in rows:
        if row[key] < floor:
            continue
        if spans and row["start"] <= spans[-1]["end"]:
            span = spans[-1]
            span["end"] = max(span["end"], row["end"])
            span["windows"] += 1
            if row[key] > span["peak"]:
                span["peak"], span["peak_window"] = row[key], [row["start"], row["end"]]
        else:
            spans.append({"start": row["start"], "end": row["end"], "peak": row[key],
                          "peak_window": [row["start"], row["end"]], "windows": 1})
    return spans


def _strength(value):
    return "candidate" if value >= THRESHOLD else "weak candidate"


def unavailable(exc) -> AudioTags:
    # Discard partial model output: a failed run cannot silently look complete.
    return AudioTags(warnings=[f"Learned audio tagging unavailable ({exc}); heuristic fallback. Install {tag_models.INSTALL_HINT}; provision with {tag_models.FETCH_HINT}."])


def _summarize(result: AudioTags, speech) -> None:
    """Spans from the per-window rows; speech intervals decide score-under-speech."""
    rows, music_rows = result.windows, []
    for row in rows:
        start, end = row["start"], row["end"]
        overlaps = [(max(start, a), min(end, b)) for a, b in speech if max(start, a) < min(end, b)]
        if row["music"] >= WEAK_THRESHOLD and (overlaps or row["speech"] >= THRESHOLD):
            music_rows.append({**row, "overlap": round(min(row["music"], row["speech"]) if not overlaps else row["music"], 6)})
    result.music_under_speech, result.moment_candidates, result.vocal_spans = [], [], []
    for span in _spans(music_rows, "overlap", WEAK_THRESHOLD):
        inside = [r for r in music_rows if span["start"] <= r["start"] and r["end"] <= span["end"]]
        intervals = [[round(max(span["start"], a), 6), round(min(span["end"], b), 6)]
                     for a, b in speech if max(span["start"], a) < min(span["end"], b)]
        result.music_under_speech.append({
            "start": span["start"], "end": span["end"], "confidence": span["peak"], "strength": _strength(span["peak"]),
            "music_confidence": max(r["music"] for r in inside), "speech_confidence": max(r["speech"] for r in inside),
            "speech_basis": "supplied word intervals" if intervals else "CED speech tags",
            "speech_intervals": intervals, "windows": span["windows"], "peak_window": span["peak_window"],
            "evidence": "Music and speech in the same context windows; candidate baked-in score, not source separation."})
    for kind in ("laughter", "applause"):
        for span in _spans(rows, kind, THRESHOLD):
            result.moment_candidates.append({"start": span["start"], "end": span["end"], "kind": kind,
                "confidence": span["peak"], "windows": span["windows"], "peak_window": span["peak_window"],
                "evidence": "CED context tag; event boundary unmeasured"})
    for span in _spans(rows, "vocals", WEAK_THRESHOLD):
        inside = [r for r in rows if span["start"] <= r["start"] and r["end"] <= span["end"]]
        result.vocal_spans.append({"start": span["start"], "end": span["end"], "confidence": span["peak"],
            "label": max(inside, key=lambda r: r["vocals"])["vocal_label"], "strength": _strength(span["peak"]),
            "windows": span["windows"], "peak_window": span["peak_window"],
            "evidence": "singing-family CED tag in overlapping context windows; listen to confirm"})


def reuse(tags, *, speech=(), duration: float) -> AudioTags | None:
    """Re-derive spans from a study's own windows instead of tagging the same file again.

    Only an identical, complete measurement qualifies: same algorithm, model
    revision and weights, and the same analyzed duration. Anything else returns
    None and the caller tags afresh.
    """
    try:
        tags = tags if isinstance(tags, AudioTags) else AudioTags.from_dict(tags)
        p = tags.provenance
        if (tags.status != "measured" or not tags.windows or p.get("algorithm") != ALGORITHM
                or p.get("revision") != tag_models.REVISION
                or p.get("model_sha256") != tag_models.ASSETS["model.int8.onnx"][0]
                or abs(float(p.get("analyzed_seconds", -1)) - duration) > 1e-3):
            return None
        reused = AudioTags.from_dict(tags.to_dict())
        _summarize(reused, [(float(a), float(b)) for a, b in speech])
        reused.provenance["reused_from"] = "study provenance audio_tags (same file, same windows)"
        return reused
    except (TypeError, ValueError, KeyError, AttributeError):
        return None


def tag_file(path, *, max_seconds=None, speech=()) -> AudioTags:
    """Tag a local file's first audio stream at CED's 16 kHz (at most 600 s).

    The runtime and verified weights are checked before FFmpeg decodes anything.
    """
    try:
        engine = tag_models.engine()
        from .media import MAX_SECONDS, decode_mono
        samples, truncated = decode_mono(path, max_seconds=max_seconds or MAX_SECONDS, sample_rate=SAMPLE_RATE)
    except Exception as exc:
        return unavailable(exc)
    tags = tag_samples(samples, SAMPLE_RATE, speech=speech, engine=engine)
    if tags.status == "measured":
        tags.provenance.update(analyzed_seconds=round(len(samples) / SAMPLE_RATE, 6), truncated=truncated)
    return tags


def tag_samples(samples, sample_rate: int, *, speech=(), engine=None) -> AudioTags:
    """Only verified local models. An absent/broken optional runtime is a fallback."""
    result = AudioTags()
    try:
        engine = engine or tag_models.engine()
        from .media import numpy
        np = numpy()
        if sample_rate != SAMPLE_RATE:
            raise ValueError(f"tagging expects {SAMPLE_RATE} Hz mono samples (decode with sample_rate={SAMPLE_RATE})")
        if len(samples) == 0 or not np.isfinite(samples).all():
            raise ValueError("tagging requires finite nonempty mono audio")
        speech = [(float(a), float(b)) for a, b in speech]
        duration = len(samples) / sample_rate
        # The last context ends at the source end, without one-second slivers.
        starts = list(range(0, max(1, math.floor(duration - WINDOW_SECONDS) + 1), int(HOP_SECONDS)))
        if duration > WINDOW_SECONDS and starts[-1] < duration - WINDOW_SECONDS:
            starts.append(round(duration - WINDOW_SECONDS, 6))
        peaks = dict.fromkeys(sorted(LABELS), 0.0)
        rows = []
        for start in starts:
            end = round(min(duration, start + WINDOW_SECONDS), 6)
            stream = engine.create_stream()
            waveform = np.ascontiguousarray(samples[round(start * sample_rate):round(end * sample_rate)], dtype=np.float32)
            if len(waveform) < sample_rate:
                waveform = np.pad(waveform, (0, sample_rate - len(waveform)))
            stream.accept_waveform(sample_rate=sample_rate, waveform=waveform)
            scores = {event.name: float(event.prob) for event in engine.compute(stream)}
            if any(not math.isfinite(v) or not 0 <= v <= 1 for v in scores.values()):
                raise ValueError("CED returned invalid confidence values")
            for name in peaks:
                peaks[name] = max(peaks[name], scores.get(name, 0.0))
            vocal_label, vocal = _best(scores, VOCALS)
            rows.append({"start": start, "end": end, "vocals": round(vocal, 6), "vocal_label": vocal_label,
                         "music": round(_score(scores, MUSIC), 6), "speech": round(_score(scores, SPEECH), 6),
                         "instrument": round(_score(scores, INSTRUMENTS), 6),
                         "laughter": round(_score(scores, LAUGHTER), 6), "applause": round(_score(scores, APPLAUSE), 6)})
        result.windows = rows
        _summarize(result, speech)
        result.labels = [{"label": name, "confidence": round(value, 6)} for name, value in peaks.items()]
        result.status, result.method = "measured", "sherpa-onnx/ced-mini-int8"
        result.provenance = {"repository": tag_models.REPOSITORY, "revision": tag_models.REVISION,
            "model_sha256": tag_models.ASSETS["model.int8.onnx"][0], "license": "Apache-2.0", "algorithm": ALGORITHM,
            "sample_rate": SAMPLE_RATE, "window_seconds": WINDOW_SECONDS, "hop_seconds": HOP_SECONDS,
            "threshold": THRESHOLD, "weak_candidate_threshold": WEAK_THRESHOLD,
            "families": {"vocals": sorted(VOCALS), "music": sorted(MUSIC), "speech": sorted(SPEECH),
                         "laughter": sorted(LAUGHTER), "applause": sorted(APPLAUSE)},
            "aggregation": "per-window family maximum; spans merge overlapping windows at or above a threshold; "
                           "track value is the strongest window", "network_used": False}
        result.warnings.append("CED confidence is uncalibrated; overlapping 5-second tags do not locate exact events or prove simultaneous sources.")
    except Exception as exc:
        result = unavailable(exc)
    return result


def vocal_evidence(tags: AudioTags, heuristic: dict) -> dict:
    if tags.status != "measured":
        return {**heuristic, "method": "heuristic_fallback"}
    scores = {row["label"]: row["confidence"] for row in tags.labels}
    label, vocal = _best(scores, VOCALS)
    instrument = _score(scores, INSTRUMENTS)
    # Instrument confidence alone cannot veto a real voice over accompaniment.
    corroborated = WEAK_THRESHOLD <= vocal < THRESHOLD and heuristic.get("status") == "possible"
    status = "possible" if vocal >= THRESHOLD or corroborated else "not_detected" if vocal < WEAK_THRESHOLD else "unknown"
    return {"status": status, "confidence": vocal, "label": label, "instrument_confidence": instrument,
            "method": tags.method, "labels": tags.labels, "spans": tags.vocal_spans, "heuristic": heuristic,
            "strength": "candidate" if vocal >= THRESHOLD else "weak corroborated candidate" if corroborated else "low model evidence",
            "evidence": "strongest singing-family confidence across 5-second CED context windows",
            "limits": "CED is an uncalibrated tagger; quiet or masked singing may be missed, and chant-like pads can read as voice. No lyric recognition or source separation."}
