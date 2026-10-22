"""Known-speech ducking envelopes and span expressions. Standard library only.

The director knows where speech is. Ducking therefore follows a deterministic
gain envelope instead of a compressor reacting to a gated key: spans closer
than ``hold`` seconds form one speech passage, the bed starts down before the
first word, stays down through short clause gaps and comes back slowly only in
real pauses. Rendering needs no NumPy and no per-sample FFmpeg expression.
"""
from __future__ import annotations

import array
import math
import sys
import wave
from pathlib import Path

# Clause splitting already treats a 600 ms silence as a pause; with a 200 ms
# pre-duck, a gap under 800 ms leaves no audible time at the recovered level.
# P15/P17 (docs/taste/TRANSITIONS-AND-MIX.md): duck within ~200 ms, recover
# over >=500-700 ms so the bed does not pump between phrases.
DEFAULT_HOLD_SECONDS = 0.8
DEFAULT_DEPTH_DB = 9.0
DEFAULT_ATTACK_SECONDS = 0.2
DEFAULT_RELEASE_SECONDS = 0.8
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
    """Speech passages: clause gaps shorter than ``hold`` stay ducked."""
    return merge(spans, hold)


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
                   attack: float, release: float, rate: int = ENVELOPE_RATE) -> Path:
    """Write the linear gain envelope as a mono 32-bit PCM WAV control track."""
    w = weights(passage_list, duration, attack, release, rate)
    scale = 2 ** 31 - 1
    samples = array.array("i", (round(scale * 10 ** (-depth_db * v / 20)) for v in w))
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
