"""Conservative, model-free onset/tempo and audio-role observations.

See docs/AUDIO.md for thresholds, confidence semantics, and limitations.
NumPy is imported only when analysis is requested.
"""

from __future__ import annotations

import math

from .media import SAMPLE_RATE, numpy
from .models import Onset, Segment, Tempo

HOP = 220  # 9.98 ms at 22.05 kHz
WINDOW = 1024


def spectral_features(samples):
    np = numpy()
    padded = np.pad(samples, (WINDOW // 2, WINDOW // 2))
    frames = np.lib.stride_tricks.sliding_window_view(padded, WINDOW)[::HOP]
    count = (len(samples) + HOP - 1) // HOP
    frames = frames[:count]
    rms = np.empty(count)
    flux = np.empty(count)
    flatness = np.empty(count)
    similarity = np.empty(count)
    window = np.hanning(WINDOW)
    previous = np.zeros(WINDOW // 2 + 1)
    # Batch the FFT instead of allocating a whole ten-minute spectrogram.
    for start in range(0, count, 512):
        chunk = frames[start:start + 512]
        magnitude = np.abs(np.fft.rfft(chunk * window, axis=1)) / WINDOW
        prior = np.vstack((previous, magnitude[:-1]))
        positive = np.maximum(0, magnitude - prior)
        end = start + len(chunk)
        flux[start:end] = np.sqrt(np.sum(positive ** 2, axis=1))
        rms[start:end] = np.sqrt(np.mean(chunk ** 2, axis=1))
        power = magnitude ** 2 + 1e-16
        flatness[start:end] = np.exp(np.mean(np.log(power), axis=1)) / np.mean(power, axis=1)
        similarity[start:end] = np.sum(magnitude * prior, axis=1) / np.maximum(
            1e-16, np.linalg.norm(magnitude, axis=1) * np.linalg.norm(prior, axis=1),
        )
        previous = magnitude[-1]
    return {"rms": rms, "flux": flux, "flatness": flatness, "similarity": similarity}


def detect_onsets(features) -> list[Onset]:
    np = numpy()
    flux = features["flux"]
    if len(flux) < 3 or float(flux.max()) < 1e-5:
        return []
    neighborhoods = np.lib.stride_tricks.sliding_window_view(np.pad(flux, 25, mode="reflect"), 51)
    median = np.median(neighborhoods, axis=1)
    mad = np.median(np.abs(neighborhoods - median[:, None]), axis=1)
    threshold = np.maximum(median + 6 * mad, max(1e-5, float(flux.max()) * 0.08))
    peaks = np.flatnonzero(
        (flux > threshold)
        & (flux >= np.r_[0, flux[:-1]])
        & (flux > np.r_[flux[1:], 0])
    )
    # Retain the stronger of peaks less than 80 ms apart, including at t=0.
    chosen: list[int] = []
    for index in peaks:
        if chosen and (index - chosen[-1]) * HOP / SAMPLE_RATE < 0.08:
            if flux[index] > flux[chosen[-1]]:
                chosen[-1] = int(index)
        else:
            chosen.append(int(index))
    maximum = float(flux.max())
    return [Onset(round(i * HOP / SAMPLE_RATE, 6), round(float(flux[i]) / maximum, 6)) for i in chosen]


def track_beats(
    onsets: list[Onset], duration: float, speech: list[tuple[float, float, float]],
) -> tuple[Tempo, list[float]]:
    """Fit a cadence only when consecutive measured attacks support it.

    Return supported onset times only: no extrapolated ticks through rests,
    speech, or unobserved edges. This deliberately rejects syncopated material
    that would require a learned musical prior or a more capable tracker.
    """
    np = numpy()
    if duration < 3 or 0 < len(onsets) < 6:
        return Tempo(evidence="fewer than six attacks or less than three seconds"), []
    if len(onsets) < 6:
        return Tempo(status="none", evidence="no repeated salient attacks"), []
    times = np.array([item.time for item in onsets])
    if speech:
        covered = sum(any(start <= t <= end for start, end, _ in speech) for t in times)
        if covered / len(times) > 0.8:
            return Tempo(evidence="attacks mostly overlap supplied speech; independent music pulse is unconfirmed"), []
    intervals = np.diff(times)
    plausible = intervals[(intervals >= 0.25) & (intervals <= 1.5)]  # 40-240 BPM
    if len(plausible) < 5:
        return Tempo(status="none", evidence="no supported cadence in 40-240 BPM"), []
    # Histogram voting avoids imposing a preferred tempo such as 120 BPM.
    bins = np.rint(plausible / 0.025).astype(int)
    mode = int(np.bincount(bins).argmax()) * 0.025
    neighbors = plausible[np.abs(plausible - mode) <= 0.03]
    period = float(np.median(neighbors))
    regularity = float(np.mean(np.abs(intervals - period) <= 0.03))
    if regularity < 0.75:
        return Tempo(status="none", evidence="inter-onset intervals do not support a steady pulse"), []
    best = None
    for anchor in times[:16]:
        indices = np.rint((times - anchor) / period)
        match = np.abs(times - (anchor + indices * period)) <= 0.03
        if match.sum() < 6:
            continue
        slope, intercept = np.polyfit(indices[match], times[match], 1)
        residual = np.abs(times - (intercept + indices * slope))
        match = residual <= 0.03
        supported = times[match]
        if len(supported) < 6 or supported[-1] - supported[0] < 3:
            continue
        occupancy = len(np.unique(indices[match])) / (indices[match].max() - indices[match].min() + 1)
        coverage = float(np.mean(match))
        if coverage < 0.85 or occupancy < 0.8 or not 0.25 <= slope <= 1.5:
            continue
        jitter = float(np.sqrt(np.mean(residual[match] ** 2)))
        score = min(0.95, regularity * coverage * occupancy * max(0, 1 - jitter / 0.06))
        if best is None or score > best[0]:
            best = (score, slope, supported)
    if best is None:
        return Tempo(status="none", evidence="cadence has insufficient phase consistency or missing attacks"), []
    score, period, supported = best
    return Tempo(
        status="steady", bpm=round(60 / float(period), 3), confidence=round(float(score), 3),
        evidence="regular measured attacks; >=85% phase agreement within 30 ms, >=80% pulse occupancy; metrical half/double-time unresolved",
    ), [round(float(t), 6) for t in supported]


def speech_intervals(words, duration: float) -> tuple[list[tuple[float, float, float]], list[str]]:
    intervals = []
    invalid = 0
    clipped = 0
    for word in words:
        start, end, confidence = word.start, word.end, word.confidence
        if (not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
                    for x in (start, end, confidence))
                or start < 0 or end <= start or not 0 <= confidence <= 1):
            invalid += 1
            continue
        if start >= duration:
            clipped += 1
            continue
        if end > duration:
            clipped += 1
        # Schema v1 uses 1.0 when probability was not reported; cap accordingly.
        intervals.append((float(start), min(float(end), duration), min(float(confidence), 0.9)))
    warnings = []
    if invalid:
        warnings.append(f"Ignored {invalid} invalid supplied word interval(s).")
    if clipped:
        warnings.append(f"Clipped or excluded {clipped} supplied word interval(s) outside the analyzed excerpt.")
    return sorted(intervals), warnings


def segment_roles(features, duration: float, speech: list[tuple[float, float, float]]) -> list[Segment]:
    """100 ms energy/flatness observations, split at supplied word boundaries.

    Segments partition the excerpt. A speech label does not exclude background
    music; this pass does not separate sources. Without word evidence, fluctuating
    tonal activity remains uncertain instead of pretending to identify speech.
    """
    np = numpy()
    boundaries = {0.0, duration}
    boundaries.update(round(float(t), 6) for t in np.arange(0.1, duration, 0.1))
    for start, end, _ in speech:
        boundaries.update((start, end))
    ordered = sorted(boundaries)
    segments: list[Segment] = []
    for start, end in zip(ordered, ordered[1:]):
        if end - start < 1e-9:
            continue
        mid = (start + end) / 2
        a = max(0, int(start * SAMPLE_RATE / HOP))
        b = min(len(features["rms"]), max(a + 1, int(math.ceil(end * SAMPLE_RATE / HOP))))
        rms = float(np.mean(features["rms"][a:b]))
        db = 20 * math.log10(max(rms, 1e-12))
        flat = float(np.median(features["flatness"][a:b]))
        similar = float(np.median(features["similarity"][a:b]))
        probabilities = [c for s, e, c in speech if s <= mid < e]
        if probabilities and max(probabilities) >= 0.5 and db > -55:
            label, confidence, evidence = "speech", max(probabilities), "supplied ASR word timing; background audio is not separated"
        elif probabilities:
            label, confidence, evidence = "uncertain", 0.3, "supplied word has weak confidence or conflicts with near-silence"
        elif db <= -55:
            label, confidence, evidence = "silence", 0.95, "RMS <= -55 dBFS on mono analysis signal"
        else:
            # Tonal continuity alone cannot distinguish a held vowel from a
            # music bed. Local stability supplies modest, explicit evidence.
            lo = max(0, int((mid - 0.4) * SAMPLE_RATE / HOP))
            hi = min(len(features["rms"]), int((mid + 0.4) * SAMPLE_RATE / HOP) + 1)
            levels = 20 * np.log10(np.maximum(features["rms"][lo:hi], 1e-12))
            # Supplied speech changes the mixture's level. Exclude that known
            # activity when judging whether the surrounding bed is stable.
            if speech:
                centers = np.arange(lo, hi) * HOP / SAMPLE_RATE
                keep = np.ones(len(centers), dtype=bool)
                for word_start, word_end, _ in speech:
                    keep &= (centers < word_start - 0.03) | (centers > word_end + 0.03)
                if keep.any():
                    levels = levels[keep]
            spread = float(np.percentile(levels, 90) - np.percentile(levels, 10))
            if flat < 0.12 and similar > 0.92 and spread < 4:
                label, confidence, evidence = "music", 0.6, "stable tonal energy; heuristic music candidate, sustained voice also possible"
            else:
                label, confidence, evidence = "uncertain", 0.3, "audible energy without reliable speech/music evidence"
        if segments and segments[-1].label == label and segments[-1].evidence == evidence:
            previous = segments[-1]
            total = end - previous.start
            previous.confidence = (previous.confidence * (previous.end - previous.start) + confidence * (end - start)) / total
            previous.end = end
        else:
            segments.append(Segment(start, end, label, confidence, evidence))
    for segment in segments:
        segment.confidence = round(segment.confidence, 3)
    return segments
