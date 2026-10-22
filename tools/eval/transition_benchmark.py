"""Event-level scoring for the generated P14 corpus (no media downloads)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Sequence

from myzing.study import transitions

CLASSES = (*transitions.SIGNATURES, "whip_pan", "flash")
CONFIDENT = 0.8
MIN_PRECISION = 0.95
MIN_RECALL = 0.85


def _matches(prediction: dict, truth: dict, fps: float) -> bool:
    start, end = prediction["start_seconds"], prediction["end_seconds"]
    a, b = truth["start_seconds"], truth["end_seconds"]
    if a == b:
        return abs(start - a) <= 2 / fps and abs(end - b) <= 2 / fps
    intersection = max(0.0, min(end, b) - max(start, a))
    union = max(end, b) - min(start, a)
    return union > 0 and intersection / union >= 0.5


def score_events(cases: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """One-to-one matches; duplicates and wrong-time labels are false positives.

    A missing prediction is a false negative, never an invented unknown.
    v4 has no confidence: count all its emitted labels as claims.
    """
    summary = {kind: {"true_positives": 0, "false_positives": 0,
                      "false_negatives": 0, "unknown": 0, "truth_count": 0,
                      "boundary_errors_seconds": []} for kind in CLASSES}
    negative_effects = 0
    unknown_count = 0
    for case in cases:
        events = list(case["events"])
        unknowns = [event for event in events if event["signature"] == "unknown"]
        unknown_count += len(unknowns)
        events = [event for event in events if event["signature"] != "unknown"
                  and event.get("confidence", 1.0) >= CONFIDENT]
        for pair in case.get("audio_aligned_pairs", []):
            cut = next((event for event in events if event["signature"] == "hard_cut"
                        and event["start_seconds"] == pair["cut_seconds"]), None)
            if cut and not any(event["signature"] == "audio_aligned_cut"
                               and event["start_seconds"] == pair["cut_seconds"] for event in events):
                events.append({**cut, "signature": "audio_aligned_cut"})
        if not case["truth_events"]:
            negative_effects += len(events)
        for kind in CLASSES:
            stats = summary[kind]
            truths = [event for event in case["truth_events"] if event["signature"] == kind]
            predictions = [event for event in events if event["signature"] == kind]
            used = set()
            stats["truth_count"] += len(truths)
            for truth in truths:
                matching = [index for index, event in enumerate(predictions)
                            if index not in used and _matches(event, truth, case["fps"])]
                if matching:
                    index = min(matching, key=lambda i: abs(predictions[i]["start_seconds"] - truth["start_seconds"]))
                    used.add(index)
                    stats["true_positives"] += 1
                    stats["boundary_errors_seconds"].append(round(max(
                        abs(predictions[index][edge] - truth[edge])
                        for edge in ("start_seconds", "end_seconds")), 6))
                else:
                    stats["false_negatives"] += 1
                    # Unknown coverage is separate from recall and does not improve it.
                    stats["unknown"] += int(any(_matches(event, truth, case["fps"]) for event in unknowns))
            stats["false_positives"] += len(predictions) - len(used)
    for stats in summary.values():
        tp, fp, fn = (stats[key] for key in ("true_positives", "false_positives", "false_negatives"))
        stats["precision"] = round(tp / (tp + fp), 6) if tp + fp else None
        stats["recall"] = round(tp / (tp + fn), 6) if tp + fn else None
    return {"signatures": summary, "unknown_count": unknown_count,
            "negative_confident_effects": negative_effects,
            "negative_case_count": sum(not case["truth_events"] for case in cases)}


def evaluate_corpus(directories: Sequence[Path], report_path: Path, *,
                    ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe",
                    detector: Callable | None = None) -> dict[str, Any]:
    if not directories:
        raise ValueError("no generated transition cases found; use --generate")
    detector = detector or transitions.detect_transition_signatures
    cases = []
    for directory in directories:
        truth = json.loads((directory / "truth.json").read_text(encoding="utf-8"))
        spec = truth["case"]
        actual_hash = hashlib.sha256((directory / truth["media"]).read_bytes()).hexdigest()
        if actual_hash != truth["sha256"]:
            raise ValueError(f"generated media hash mismatch: {directory}; regenerate the corpus")
        measurement = detector(directory / truth["media"], ffmpeg=ffmpeg, ffprobe=ffprobe)
        cases.append({"case_id": spec["case_id"], "split": spec["split"],
                      "fps": spec["fps"], "variant": spec["variant"],
                      "media": str(directory / truth["media"]), "sha256": truth["sha256"],
                      "truth_events": truth["truth_events"], **measurement})
    splits = {split: score_events([case for case in cases if case["split"] == split])
              for split in sorted({case["split"] for case in cases})}
    supported = list(getattr(transitions, "SUPPORTED_SIGNATURES", transitions.SIGNATURES))
    gate_failures = []
    for split, result in splits.items():
        if result["negative_confident_effects"]:
            gate_failures.append(f"{split}: confident effects on negatives")
        for kind in supported:
            stats = result["signatures"][kind]
            if (stats["precision"] or 0) < MIN_PRECISION or (stats["recall"] or 0) < MIN_RECALL:
                gate_failures.append(f"{split}: {kind} below precision/recall threshold")
    report = {"version": 1, "detector_version": transitions.DETECTOR_VERSION,
              "detector_provenance": transitions.detector_provenance(),
              "validation": transitions.VALIDATION_STATUS, "case_count": len(cases),
              "supported_signatures": supported,
              "thresholds": {"confidence": CONFIDENT, "precision": MIN_PRECISION,
                             "recall": MIN_RECALL, "negative_confident_effects": 0},
              "scoring": {"unit": "one-to-one event matches", "cut_tolerance_frames": 2,
                          "interval_iou_min": 0.5,
                          "unknown": "explicit abstentions only; unmatched truth remains a false negative",
                          "legacy_v4": "confidence absent; all emitted labels counted as claims"},
              "threshold_reason": "Precision takes priority because false effects corrupt style recipes. Recall >=0.85 allows conservative abstention. Small generated sets do not establish real-video accuracy.",
              "aggregate": score_events(cases), "splits": splits,
              "acceptance": {"passed": not gate_failures, "failures": gate_failures},
              "limitations": ["Generated textures and motion are not human-labeled camera footage.",
                              "Held-out parameters use the same generator family.",
                              "Detector timing is graded separately from the one-frame renderer release gate.",
                              "Confidence is a heuristic evidence score, not a calibrated probability."],
              "cases": cases}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
