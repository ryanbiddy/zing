"""Small, explicit metrics. Unknown/unreviewed observations are not negatives."""

import re
from collections import Counter
from statistics import mean, median


def pr(tp, fp, fn):
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
    }


def assign(truths, predictions, quality):
    """Maximum-cardinality one-to-one matching; quality >= 0 is eligible.

    Preference is highest quality, but an augmenting path preserves a second
    match when a greedy nearest-neighbor choice would lose it.
    """
    owner = {}
    edges = [
        sorted(((quality(t, p), j) for j, p in enumerate(predictions)), reverse=True)
        for t in truths
    ]

    def augment(i, seen):
        for value, j in edges[i]:
            if value < 0 or j in seen:
                continue
            seen.add(j)
            if j not in owner or augment(owner[j], seen):
                owner[j] = i
                return True
        return False

    for i in range(len(truths)):
        augment(i, set())
    return sorted((i, j) for j, i in owner.items())


def iou(a, b):
    overlap = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1])
    )
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - overlap
    return overlap / union if union > 0 else 0


def interval_iou(a, b):
    overlap = max(
        0,
        min(a["end_seconds"], b["end_seconds"])
        - max(a["start_seconds"], b["start_seconds"]),
    )
    union = max(a["end_seconds"], b["end_seconds"]) - min(
        a["start_seconds"], b["start_seconds"]
    )
    return overlap / union if union > 0 else 0


def normalize(text):
    return re.sub(r"[^\w\s]", "", text.casefold()).strip()


def distance(a, b):
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        row = [i]
        for j, y in enumerate(b, 1):
            row.append(min(row[-1] + 1, previous[j] + 1, previous[j - 1] + (x != y)))
        previous = row
    return previous[-1]


def inside(event, windows):
    return any(
        a - 1e-6 <= event["start_seconds"] < b - 1e-6
        and event["end_seconds"] <= b + 1e-6
        for a, b in windows
    )


def transition_score(clips, labels, observations, kind, thresholds, shots=False):
    rows = []
    unavailable = []
    for id, clip in clips.items():
        truth = labels.get(id, {})
        windows = truth.get("transition_windows", [])
        if not windows:
            continue
        breakdown = observations.get(id, {}).get("breakdown")
        if not breakdown or (
            not shots and "transition_evidence" not in breakdown.get("provenance", {})
        ):
            unavailable.append(id)
            continue
        events = breakdown["provenance"].get("transition_evidence", [])
        if shots:
            predictions = [
                {"start_seconds": s["start"], "end_seconds": s["start"]}
                for s in breakdown["shots"][1:]
            ]
        else:
            predictions = [
                e
                for e in events
                if e["signature"] == kind
                and e["confidence"] >= thresholds["confidence"]
            ]
        predictions = [e for e in predictions if inside(e, windows)]
        truths = [e for e in truth["transition_events"] if e["signature"] == kind]

        def quality(t, p, fps=clip["fps"]):
            if kind == "hard_cut":
                error = max(abs(t[k] - p[k]) for k in ("start_seconds", "end_seconds"))
                return (
                    -error
                    if error <= thresholds["cut_tolerance_frames"] / fps + 1e-6
                    else -100
                )
            value = interval_iou(t, p)
            return value if value >= thresholds["interval_iou"] else -100

        # Eligible cut quality must be nonnegative.
        def eligible(t, p):
            q = quality(t, p)
            return 1 + q if q > -100 else -1

        matches = assign(truths, predictions, eligible)
        matched_truth = {i for i, j in matches}
        matched_pred = {j for i, j in matches}
        rows.append(
            dict(
                clip=id,
                **pr(
                    len(matches),
                    len(predictions) - len(matches),
                    len(truths) - len(matches),
                ),
                boundary_errors_seconds=[
                    max(
                        abs(truths[i][k] - predictions[j][k])
                        for k in ("start_seconds", "end_seconds")
                    )
                    for i, j in matches
                ],
                missed=[t for i, t in enumerate(truths) if i not in matched_truth],
                false_positives=[
                    p for j, p in enumerate(predictions) if j not in matched_pred
                ],
                abstentions=sum(
                    e["signature"] == "unknown" and inside(e, windows) for e in events
                ),
            )
        )
    errors = [x for r in rows for x in r["boundary_errors_seconds"]]
    return dict(
        **pr(
            sum(r["tp"] for r in rows),
            sum(r["fp"] for r in rows),
            sum(r["fn"] for r in rows),
        ),
        boundary_mae_seconds=mean(errors) if errors else None,
        per_clip=rows,
        unavailable=unavailable,
    )


def captions_score(clips, labels, observations, thresholds):
    rows = []
    unavailable = []
    errors = []
    height_errors = []
    centers = []
    exact = 0
    chars = 0
    edits = 0
    for id, truth in labels.items():
        geometry = observations.get(id, {}).get("geometry", {})
        for frame in truth.get("caption_frames", []):
            samples = geometry.get("frames", [])
            sample = (
                min(samples, key=lambda s: abs(s["t"] - frame["t"]))
                if samples
                else None
            )
            if (
                sample is None
                or abs(sample["t"] - frame["t"])
                > thresholds["caption_sample_tolerance_seconds"]
            ):
                unavailable.append([id, frame["t"]])
                continue
            # All OCR evidence is retained in JSON. Score the shipped 0.75 gate,
            # not low-confidence diagnostics as if they were accepted claims.
            predictions = [
                p for p in sample["detections"] if (p.get("confidence") or 0) >= 0.75
            ]
            truths = frame["lines"]
            matches = assign(
                truths,
                predictions,
                lambda t, p: (
                    iou(t["box"], p["box"])
                    if iou(t["box"], p["box"]) >= thresholds["caption_iou"]
                    else -1
                ),
            )
            details = []
            for i, j in matches:
                t, p = truths[i], predictions[j]
                ink = p.get("appearance", {}).get("ink_box", p["box"])
                a, b = normalize(t["text"]), normalize(p["text"])
                errors.append(iou(t["box"], ink))
                height_errors.append(
                    abs((ink[3] - ink[1]) / (t["box"][3] - t["box"][1]) - 1)
                )
                centers.append(
                    [
                        abs((ink[k] + ink[k + 2] - t["box"][k] - t["box"][k + 2]) / 2)
                        for k in (0, 1)
                    ]
                )
                exact += a == b
                chars += len(a)
                edits += distance(a, b)
                details.append(
                    {
                        "truth": t["text"],
                        "predicted": p["text"],
                        "ink_iou": errors[-1],
                        "height_relative_error": height_errors[-1],
                    }
                )
            rows.append(
                dict(
                    clip=id,
                    t=frame["t"],
                    **pr(
                        len(matches),
                        len(predictions) - len(matches),
                        len(truths) - len(matches),
                    ),
                    matches=details,
                    missed=[
                        t["text"]
                        for i, t in enumerate(truths)
                        if i not in {a for a, b in matches}
                    ],
                )
            )
    matched = sum(r["tp"] for r in rows)
    return dict(
        **pr(matched, sum(r["fp"] for r in rows), sum(r["fn"] for r in rows)),
        frames_scored=len(rows),
        unavailable=unavailable,
        per_frame=rows,
        median_ink_iou=median(errors) if errors else None,
        median_height_relative_error=median(height_errors) if height_errors else None,
        median_center_error_xy=[median(x[i] for x in centers) for i in (0, 1)]
        if centers
        else None,
        exact_text_matches=exact,
        matched_text_lines=matched,
        matched_line_cer=edits / chars if chars else None,
        note="Text/geometry errors condition on detected lines; missed lines remain false negatives. Text lowercased, punctuation removed; spaces retained.",
    )


def face_score(labels, observations, thresholds):
    rows = []
    unknown = []
    unavailable = []
    for id, truth in labels.items():
        samples = (
            observations.get(id, {})
            .get("layout", {})
            .get("provenance", {})
            .get("detections", [])
        )
        for frame in truth.get("face_frames", []):
            if frame["present"] is None:
                unknown.append([id, frame["t"]])
                continue
            sample = (
                min(samples, key=lambda f: abs(f["time"] - frame["t"]))
                if samples
                else None
            )
            if (
                sample is None
                or abs(sample["time"] - frame["t"])
                > thresholds["face_sample_tolerance_seconds"]
            ):
                unavailable.append([id, frame["t"]])
                continue
            rows.append(
                {
                    "clip": id,
                    "t": frame["t"],
                    "truth": frame["present"],
                    "predicted": bool(sample["detections"]),
                }
            )
    tp = sum(r["truth"] and r["predicted"] for r in rows)
    fp = sum(not r["truth"] and r["predicted"] for r in rows)
    fn = sum(r["truth"] and not r["predicted"] for r in rows)
    tn = sum(not r["truth"] and not r["predicted"] for r in rows)
    return dict(
        **pr(tp, fp, fn),
        tn=tn,
        accuracy=(tp + tn) / len(rows) if rows else None,
        frames_scored=len(rows),
        unknown=unknown,
        unavailable=unavailable,
        per_frame=rows,
    )


def score(manifest, labels, observations):
    if labels.get("version") != 1 or not labels.get("clips"):
        raise ValueError(
            "Version 1 reviewed labels required; unreviewed media cannot produce an accuracy report"
        )
    clips = {c["id"]: c for c in manifest["clips"]}
    truth = labels["clips"]
    actual = observations["clips"]
    thresholds = labels["thresholds"]
    for id, c in truth.items():
        if c["media_sha256"] != clips[id]["sha256"]:
            raise ValueError(f"Label/media hash mismatch: {id}")
    for id, c in actual.items():
        if id not in clips or c.get("media_sha256") != clips[id]["sha256"]:
            raise ValueError(f"Observation/media hash mismatch: {id}")
    fonts = Counter()
    audio = []
    font_details = []
    for id, c in actual.items():
        for track in c.get("geometry", {}).get("font_candidates", {}).get("tracks", []):
            status = track.get("status", "unknown")
            fonts[status] += 1
            font_details.append({"clip": id, **track})
        if c.get("audio"):
            a = c["audio"]
            audio.append(
                {
                    "clip": id,
                    "truth": truth.get(id, {}).get("audio"),
                    "tempo": a["tempo"],
                    "beat_count": len(a["beats"]),
                    "segment_seconds": {
                        k: sum(
                            s["end"] - s["start"]
                            for s in a["segments"]
                            if s["label"] == k
                        )
                        for k in ("music", "speech", "silence", "uncertain")
                    },
                }
            )
    return {
        "version": 1,
        "clip_count": len(clips),
        "source_work_count": len(manifest["sources"]),
        "reviewed_transition_seconds": sum(
            b - a for c in truth.values() for a, b in c.get("transition_windows", [])
        ),
        "transitions": {
            kind: transition_score(clips, truth, actual, kind, thresholds)
            for kind in ("hard_cut", "dissolve", "wipe")
        },
        "shot_boundaries": transition_score(
            clips, truth, actual, "hard_cut", thresholds, shots=True
        ),
        "captions": captions_score(clips, truth, actual, thresholds),
        "faces": face_score(truth, actual, thresholds),
        "fonts": {
            "identity_accuracy": None,
            "reason": "No verified source font identities",
            "statuses": dict(fonts),
            "tracks": font_details,
        },
        "audio": {
            "accuracy": None,
            "reason": "No independent listening labels; no beat-timing ground truth",
            "clips": audio,
        },
        "color": {
            "perceptual_accuracy": None,
            "reason": "Unpaired scenes have no target pixels or original LUT labels",
            "pairs": [
                {
                    "reference": c["reference"],
                    "clip": c["clip"],
                    "match": c["result"]["match"] if c["result"] else None,
                    "visual_check": c.get("visual_check"),
                }
                for c in observations.get("colors", [])
            ],
        },
    }
