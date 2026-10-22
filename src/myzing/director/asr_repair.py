"""Derived ASR timings with bounded interpolation and local quarantine only."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from myzing.timing import finite, interval_problem, prepare_words, transform_word

MAX_WINDOW_SECONDS = 2.0
MAX_WORDS = 12
MIN_SECONDS = .02


def repair_words(words, duration, *, enabled=True):
    if not enabled:
        validated, _ = prepare_words(words, duration, repair=False)
        return validated, {"version": 1, "enabled": False, "repairs": [], "quarantined": []}
    if interval_problem(0, duration, duration):
        raise ValueError("ASR repair needs a positive finite media duration")
    out = deepcopy(words)
    bad, previous = set(), 0.
    for i, word in enumerate(out):
        if (interval_problem(word.start, word.end, duration) or word.start < previous - 1e-9
                or not isinstance(word.text, str) or not word.text.strip()):
            bad.add(i)
        else:
            previous = word.end
    report = {"version": 1, "enabled": True, "max_window_seconds": MAX_WINDOW_SECONDS,
              "max_words": MAX_WORDS, "repairs": [], "quarantined": []}
    omitted = set()
    while bad:
        first = min(bad)
        stop = first + 1
        while stop in bad:
            stop += 1
        left, right = first - 1, stop
        low = out[left].end if left >= 0 and left not in omitted else 0.
        high = out[right].start if right < len(out) else duration
        begin, end = first, stop
        # Packed zero-duration words need room. Reflow at most one valid word
        # on each side and disclose those changed neighbors as repairs too.
        if high - low < MIN_SECONDS * (end - begin):
            begin = left if left >= 0 and left not in omitted else first
            end = right + 1 if right < len(out) else stop
            low, high = out[begin].start, out[end - 1].end
        count = end - begin
        anchored = left >= 0 or right < len(out)
        plausible = (finite(low) and finite(high) and 0 <= low < high <= duration
                     and MIN_SECONDS * count <= high - low <= MAX_WINDOW_SECONDS
                     and count <= MAX_WORDS and anchored
                     and all(isinstance(w.text, str) and w.text.strip() for w in out[begin:end]))
        if plausible:
            for i in range(begin, end):
                old = out[i]
                # JSON provenance cannot contain NaN/Infinity; retain their
                # literal representation if such input reaches this boundary.
                original = {k: v if finite(v) else repr(v) for k, v in (("start", old.start), ("end", old.end))}
                base = replace(old, timing=None)
                fixed = transform_word(base, low + (i - begin) * (high - low) / count,
                                       low + (i - begin + 1) * (high - low) / count,
                                       "bounded_neighbor_interpolation", repaired=True,
                                       window={"start": low, "end": high}, prior_timing=deepcopy(old.timing))
                fixed.timing["original"] = original
                fixed.timing["repaired"] = True
                fixed.timing["adjustments"][0]["from"] = original
                out[i] = fixed
                report["repairs"].append({"index": i, "text": old.text, "repaired": True,
                                          "method": fixed.timing["method"], "original": original,
                                          "start": fixed.start, "end": fixed.end})
        else:
            # Bound the unsafe source region by trusted neighboring words.
            # Do not exclude unrelated valid speech elsewhere in the clip.
            qlow = out[left].end if left >= 0 and left not in omitted else 0.
            qhigh = out[right].start if right < len(out) else duration
            omitted.update(range(first, stop))
            report["quarantined"].append({"start": qlow, "end": max(qlow, qhigh),
                "word_indices": list(range(first, stop)), "words": [w.text for w in out[first:stop]],
                "reason": "No bounded interpolation between trustworthy neighbors; span requires review."})
        bad.difference_update(range(first, stop))
    validated, _ = prepare_words([w for i, w in enumerate(out) if i not in omitted], duration, repair=False)
    return validated, report
