"""Reject candidate footage with measured face-free gaps or graphic slates."""

from types import SimpleNamespace

from .selection import merge, overlaps


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
    cards = text_cards(SimpleNamespace(src_in=0, src_out=clip.duration), clip.text_geometry)
    card_times = {t for t, *_ in cards}
    def large(boxes):
        return sum((b[2]-b[0])*(b[3]-b[1]) for b in boxes) >= .08
    for frame in clip.text_geometry.get("frames", []):
        boxes = [d.get("appearance", {}).get("ink_box") or d["box"] for d in frame.get("detections", [])
                 if (d.get("confidence") or 0) >= .5]
        if large(boxes):
            card_times.add(frame["t"])
    # Compact and older OCR sidecars may omit raw frames. Keep the same rule
    # for their retained geometry, including a single large logo/title word.
    for sample in clip.text_geometry.get("protected_samples", []):
        if large(sample["boxes"]):
            card_times.add(sample["t"])
    tracked = {}
    for track in clip.text_geometry.get("tracks", []):
        for sample in track.get("samples", []):
            tracked.setdefault(sample["t"], []).extend(sample.get("line_boxes") or [sample["box"]])
    card_times.update(t for t, boxes in tracked.items() if large(boxes))
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


def filter_candidates(pool, excluded):
    return [c for c in pool if not any(overlaps((c.start, c.end), span)
                                     for span in excluded.get(c.asset_id, []))]
