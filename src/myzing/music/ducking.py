"""Known-speech ducking envelopes and span expressions. Standard library only.

The director knows where speech is. Ducking therefore follows a deterministic
gain envelope instead of a compressor reacting to a gated key: the bed starts
down before the first word, stays down through clause gaps and comes back
slowly only in real pauses. Rendering needs no NumPy and no per-sample FFmpeg
expression.

A pause is real only when the bed can recover and stay up before the next
pre-duck: it must be at least ``hold`` and at least attack + release +
``plateau`` (0.2 + 0.8 + 0.3 = 1.3 s by default). Shorter gaps stay ducked, so
the bed never swings up and straight back down between sentences (LISTEN1
measured an 8.4 dB, half-second lift in a 0.84 s gap under the old
hold-only rule). The edges follow the same idea: a lead-in shorter than
max(hold, attack + plateau) before the first word, or a tail shorter than
max(hold, release + plateau) after the last, stays ducked instead of playing
a fraction of a second at pause level.

Optional gain points (time, dB <= 0) add a slow per-clip bed level on top of
the duck, for sources whose speech levels differ (docs/MUSIC.md).
"""
from __future__ import annotations

import array
import math
import sys
import wave
from pathlib import Path

# Clause splitting already treats a 600 ms silence as a pause; the hold keeps
# such gaps ducked, and release_gap() also requires attack + release +
# plateau. P15/P17 (docs/taste/TRANSITIONS-AND-MIX.md): duck within ~200 ms,
# recover over >=500-700 ms so the bed does not pump between phrases.
DEFAULT_HOLD_SECONDS = 0.8
DEFAULT_DEPTH_DB = 9.0
DEFAULT_ATTACK_SECONDS = 0.2
DEFAULT_RELEASE_SECONDS = 0.8
# Shortest audible time at the recovered level that justifies a release.
DEFAULT_PLATEAU_SECONDS = 0.3
ENVELOPE_RATE = 1000
# Balanced expression trees keep FFmpeg's parser depth near log2(spans); the
# bound keeps per-frame selection cost and evidence size reasonable.
MAX_SPANS = 2048


class SpanLimitError(ValueError):
    """Too many measurement windows for one bounded FFmpeg selection."""


def check_span_count(count: int, what: str = "speech spans", limit: int = MAX_SPANS) -> None:
    if count > limit:
        raise SpanLimitError(f"{count} {what} exceed the {limit}-span limit for one music mix; "
                             "split the edit into shorter renders or merge adjacent clauses.")


def merge(spans, gap: float = 0.0) -> list[list[float]]:
    """Sorted union of spans; spans separated by less than ``gap`` seconds join."""
    merged: list[list[float]] = []
    for a, b in sorted((float(a), float(b)) for a, b in spans):
        if b <= a:
            continue
        if merged and a - merged[-1][1] < gap + 1e-9:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


def passages(spans, hold: float = DEFAULT_HOLD_SECONDS) -> list[list[float]]:
    """Plain merge: clause gaps shorter than ``hold`` join. See duck_passages."""
    return merge(spans, hold)


def release_gap(hold: float = DEFAULT_HOLD_SECONDS, attack: float = DEFAULT_ATTACK_SECONDS,
                release: float = DEFAULT_RELEASE_SECONDS, plateau: float = DEFAULT_PLATEAU_SECONDS) -> float:
    """Shortest pause the bed recovers in: the hold, and room to settle up."""
    return max(hold, attack + release + plateau)


def duck_passages(spans, duration: float, *, hold: float = DEFAULT_HOLD_SECONDS,
                  attack: float = DEFAULT_ATTACK_SECONDS, release: float = DEFAULT_RELEASE_SECONDS,
                  plateau: float = DEFAULT_PLATEAU_SECONDS) -> list[list[float]]:
    """The passages the renderer ducks under, edges included (module docstring)."""
    held = merge(spans, release_gap(hold, attack, release, plateau))
    if held:
        if held[0][0] < max(hold, attack + plateau):
            held[0][0] = 0.0
        if duration - held[-1][1] < max(hold, release + plateau):
            held[-1][1] = max(held[-1][1], float(duration))
    return held


def gain_at(points, t: float) -> float:
    """dB of (time, dB) gain points at ``t``; raised-cosine between points."""
    if not points:
        return 0.0
    points = sorted((float(a), float(g)) for a, g in points)
    if t <= points[0][0]:
        return points[0][1]
    for (t0, g0), (t1, g1) in zip(points, points[1:]):
        if t <= t1:
            x = (t - t0) / (t1 - t0) if t1 > t0 else 1.0
            return g0 + (g1 - g0) * (1 - math.cos(math.pi * x)) / 2
    return points[-1][1]


def ramp_windows(points) -> list[list[float]]:
    """Intervals where the bed gain points change level."""
    points = sorted((float(t), float(g)) for t, g in points or [])
    return [[a, b] for (a, ga), (b, gb) in zip(points, points[1:]) if abs(ga - gb) > 1e-9 and b > a]


def mean_gain(points, start: float, end: float, step: float = .05) -> float:
    """Energy-mean dB of the gain points over [start, end] (for planning a clause)."""
    if not points or end <= start:
        return gain_at(points, start)
    count = max(1, int(math.ceil((end - start) / step)))
    times = [start + (i + .5) * (end - start) / count for i in range(count)]
    return 10 * math.log10(sum(10 ** (gain_at(points, t) / 10) for t in times) / count)


def gain_curve(points, count: int, rate: int = ENVELOPE_RATE):
    """dB per control sample from (time, dB) points; raised-cosine between points.

    Before the first point and after the last the nearest value holds; equal
    neighbouring values give a flat segment, so pairs of points place ramps.
    """
    out = [0.0] * count
    if not points:
        return out
    points = sorted((float(t), float(g)) for t, g in points)
    j = 1
    for i in range(count):
        t = i / rate
        if t <= points[0][0]:
            out[i] = points[0][1]
        elif t >= points[-1][0]:
            out[i] = points[-1][1]
        else:
            while points[j][0] < t:  # time only increases, so the segment index does too
                j += 1
            (t0, g0), (t1, g1) = points[j - 1], points[j]
            x = (t - t0) / (t1 - t0) if t1 > t0 else 1.0
            out[i] = g0 + (g1 - g0) * (1 - math.cos(math.pi * x)) / 2
    return out


def weights(passage_list, duration: float, attack: float, release: float, rate: int = ENVELOPE_RATE) -> array.array:
    """Duck weight 0..1 per control sample: raised-cosine ramps, max over passages.

    The attack ramp ends at the first word; the release ramp starts after the
    last word, so no ramp overlaps known speech.
    """
    count = int(math.ceil(duration * rate)) + 1
    w = array.array("d", [0.0]) * count
    for a, b in passage_list:
        first, last = max(0, int(math.ceil(a * rate))), min(count, int(math.floor(b * rate)) + 1)
        if last > first:
            w[first:last] = array.array("d", [1.0]) * (last - first)
        if attack > 0:
            for i in range(max(0, int(math.ceil((a - attack) * rate))), min(count, first)):
                x = (i / rate - (a - attack)) / attack
                w[i] = max(w[i], (1 - math.cos(math.pi * min(1.0, max(0.0, x)))) / 2)
        if release > 0:
            for i in range(max(0, last), min(count, int(math.floor((b + release) * rate)) + 1)):
                x = (i / rate - b) / release
                w[i] = max(w[i], (1 + math.cos(math.pi * min(1.0, max(0.0, x)))) / 2)
    return w


def write_envelope(path: Path, passage_list, duration: float, *, depth_db: float,
                   attack: float, release: float, rate: int = ENVELOPE_RATE, gain_points=None) -> Path:
    """Write the linear gain envelope as a mono 32-bit PCM WAV control track.

    Gain points must be <= 0 dB: the envelope can lower the bed, never raise it.
    """
    w = weights(passage_list, duration, attack, release, rate)
    if any(g > 1e-9 for _, g in gain_points or []):
        raise ValueError("music bed gain points must be <= 0 dB; raise the track gain instead")
    extra = gain_curve(gain_points or [], len(w), rate)
    scale = 2 ** 31 - 1
    samples = array.array("i", (round(scale * 10 ** ((-depth_db * v + g) / 20)) for v, g in zip(w, extra)))
    if sys.byteorder != "little":
        samples.byteswap()
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(4)
        out.setframerate(rate)
        out.writeframes(samples.tobytes())
    return path


def span_expression(spans) -> str:
    """A balanced sum of between(t,a,b) terms: parser depth grows as log2(n).

    FFmpeg 8 rejects a flat sum of about 99 terms (left-deep nesting), while a
    balanced tree of 512 terms parses on 6.1 and 8.1.
    """
    terms = [f"between(t,{a:.6f},{b:.6f})" for a, b in spans]
    if not terms:
        return "0"

    def tree(lo: int, hi: int) -> str:
        if hi - lo == 1:
            return terms[lo]
        mid = (lo + hi) // 2
        return f"({tree(lo, mid)}+{tree(mid, hi)})"

    return tree(0, len(terms))
