"""Trim measured face-free gaps and graphic slates from interview candidates."""

from dataclasses import replace
from types import SimpleNamespace

from .selection import EPS, merge, overlaps, subtract


def excluded_spans(clip, presence):
    """Only observed negative face/head samples establish an exclusion.

    Detector failures and unexamined ranges stay unknown. Body and saliency
    detections do not establish a visible face or head.
    """
    from myzing.layout.text_safety import text_cards
    samples = sorted(presence.get("samples", []), key=lambda s: s["time"])
    if not samples:
        return []
    has_faces = any(s["present"] for s in samples)
    if not has_faces:
        return []  # Screen recordings and other faceless sources remain usable.
    cards = text_cards(SimpleNamespace(src_in=0, src_out=clip.duration), clip.text_geometry)
    card_times = {t for t, *_ in cards}
    rows, run = [], []

    def close(until=None):
        end = min(clip.duration if until is None else until, run[-1]["time"] + .5) if run else 0.
        if run and has_faces and end - run[0]["time"] >= 1. - 1e-6:
            rows.append((run[0]["time"], end))

    for sample in samples:
        if run and sample["time"] - run[-1]["time"] > .75:
            close()
            run = []
        if sample["present"]:
            close(sample["time"])
            run = []
        else:
            run.append(sample)
            if any(abs(t - sample["time"]) <= .25 for t in card_times):
                rows.append((max(0., sample["time"] - .25), min(clip.duration, sample["time"] + .5)))
    close()
    return merge(rows)


def filter_candidates(pool, excluded, studies, required=()):
    """Retain usable pieces, rebuilding transcript metadata and must-keep bits.

    A trim through speech moves inward past the entire affected clause. It
    cannot inherit the original candidate's text, count, or required coverage.
    """
    from .continuity import clauses
    lookup = {s.asset_id: s for s in studies}
    speech = {s.asset_id: clauses(s.words) for s in studies}
    result = {}
    for candidate in pool:
        if not any(overlaps((candidate.start, candidate.end), span) for span in excluded.get(candidate.asset_id, [])):
            result.setdefault((candidate.asset_id, candidate.start, candidate.end, candidate.covers), candidate)
            continue
        study = lookup[candidate.asset_id]
        bits = [(1 << i, (a, b)) for i, (key, a, b) in enumerate(required) if key == candidate.asset_id]
        for start, end in subtract([(candidate.start, candidate.end)], excluded.get(candidate.asset_id, [])):
            for clause in speech[candidate.asset_id]:
                if clause.start + EPS < start < clause.end - EPS:
                    start = clause.end
                if clause.start + EPS < end < clause.end - EPS:
                    end = clause.start
            if end - start < .2:
                continue
            if any(overlaps((start, end), span) and not (start <= span[0] + EPS and end >= span[1] - EPS)
                   for _, span in bits):
                continue
            words = [w for w in study.words if w.start >= start - EPS and w.end <= end + EPS]
            shot = next(s for s in study.shots if s.start <= start < s.end)
            trimmed = replace(candidate, start=start, end=end, shot=shot.index,
                word_count=len(words), first_word=words[0].start - start if words else None,
                text=" ".join(w.text for w in words), keyframe=bool(shot.keyframe),
                keeper=any(start >= k["start"] - .35 and end <= k["end"] + .35 for k in study.keepers),
                covers=sum(bit for bit, (a, b) in bits if start <= a + EPS and end >= b - EPS),
                dangling_clauses=sum(not c.complete for c in speech[candidate.asset_id]
                                     if overlaps((start, end), (c.start, c.end))))
            result.setdefault((trimmed.asset_id, trimmed.start, trimmed.end, trimmed.covers), trimmed)
    return sorted(result.values(), key=lambda c: (c.asset_id, c.start, c.end))
