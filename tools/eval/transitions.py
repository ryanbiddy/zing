"""Evaluate transition signatures against synthetic and real calibration data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from myzing.study.transitions import (
    DISSOLVE_MEAN_FRAME_DIFFERENCE,
    DISSOLVE_TEMPORAL_MONOTONICITY,
    SIGNATURES,
    TransitionProbeError,
    detect_transition_signatures,
)

HERE = Path(__file__).resolve().parent
DEFAULT_REAL_CALIBRATION = (
    HERE / "fixtures" / "transitions" / "real-gate-candidates.json"
)


def summarize_signature_precision(
    cases: Sequence[dict[str, Any]],
) -> dict[str, dict[str, int | float]]:
    summary = {}
    for signature in SIGNATURES:
        true_positives = sum(
            signature in case["truth"] and signature in case["predicted"]
            for case in cases
        )
        false_positives = sum(
            signature not in case["truth"] and signature in case["predicted"]
            for case in cases
        )
        predicted_count = true_positives + false_positives
        precision = true_positives / predicted_count if predicted_count else 0.0
        summary[signature] = {
            "true_positives": true_positives,
            "false_positives": false_positives,
            "predicted_count": predicted_count,
            "precision": round(precision, 6),
        }
    return summary


def summarize_real_dissolve_calibration(
    calibration_path: Path = DEFAULT_REAL_CALIBRATION,
) -> dict[str, Any]:
    """Apply the current dissolve gate to frozen detector-v2 measurements."""
    calibration = json.loads(
        calibration_path.read_text(encoding="utf-8")
    )
    sources = calibration.get("sources", [])
    if not sources:
        raise ValueError("real dissolve calibration has no sources")

    source_results = []
    prior_count = 0
    retained_count = 0
    for source in sources:
        candidates = source.get("prior_dissolve_candidates", [])
        retained = sum(
            candidate["temporal_monotonicity"]
            >= DISSOLVE_TEMPORAL_MONOTONICITY
            and candidate["mean_frame_difference"]
            >= DISSOLVE_MEAN_FRAME_DIFFERENCE
            for candidate in candidates
        )
        prior_count += len(candidates)
        retained_count += retained
        source_results.append(
            {
                "fixture_id": source["fixture_id"],
                "prior_dissolve_candidates": len(candidates),
                "retained_by_current_gate": retained,
                "suppressed_by_current_gate": len(candidates) - retained,
            }
        )
    suppressed_count = prior_count - retained_count
    annotation = calibration["annotation"]
    return {
        "corpus": calibration["corpus"],
        "source_document": calibration["source_document"],
        "source_count": len(sources),
        "prior_detector_version": calibration["prior_detector_version"],
        "prior_dissolve_candidates": prior_count,
        "retained_by_current_gate": retained_count,
        "suppressed_by_current_gate": suppressed_count,
        "candidate_rejection_rate": round(
            suppressed_count / prior_count if prior_count else 0.0,
            6,
        ),
        "current_gate": {
            "temporal_monotonicity": DISSOLVE_TEMPORAL_MONOTONICITY,
            "mean_frame_difference": DISSOLVE_MEAN_FRAME_DIFFERENCE,
        },
        "precision": {
            "available": annotation["precision_available"],
            "value": None,
            "annotation_status": annotation["status"],
            "reason": annotation["reason"],
        },
        "spot_check_count": len(calibration.get("spot_checks", [])),
        "sources": source_results,
    }


def evaluate_transition_goldens(
    directories: Sequence[Path],
    report_path: Path,
    *,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
    real_calibration_path: Path = DEFAULT_REAL_CALIBRATION,
) -> dict[str, Any]:
    if not directories:
        raise ValueError("no transition goldens found")
    cases = []
    for directory in directories:
        truth = json.loads(
            (directory / "transition-truth.json").read_text(encoding="utf-8")
        )
        measurement = detect_transition_signatures(
            directory / truth["media"],
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
        )
        cases.append(
            {
                "fixture_id": truth["fixture_id"],
                "truth": truth["transition"]["signatures"],
                "predicted": measurement["predicted"],
                "events": measurement["events"],
                "audio_onsets_seconds": measurement["audio_onsets_seconds"],
                "audio_aligned_pairs": measurement["audio_aligned_pairs"],
                "feature_summary": measurement["feature_summary"],
            }
        )
    signatures = summarize_signature_precision(cases)
    real_calibration = summarize_real_dissolve_calibration(
        real_calibration_path
    )
    report = {
        "prototype_schema_version": 2,
        "signatures": signatures,
        "macro_precision": round(
            sum(value["precision"] for value in signatures.values())
            / len(signatures),
            6,
        ),
        "real_video_calibration": real_calibration,
        "cases": cases,
        "limitations": {
            "prototype_only": True,
            "not_detected": [
                "j_cut",
                "l_cut",
                "jump_cut",
                "match_cut",
                "whip_pan",
                "speed_ramp",
                "glitch",
                "invisible_cut",
            ],
            "notes": [
                "Reported signature precision is case-level synthetic precision.",
                "The real-video corpus has no exhaustive transition labels, so its precision is unavailable.",
                "Rejecting prior real-video candidates is not evidence of real-video recall.",
                "Audio alignment detects energy onset, not speaker or scene identity.",
                "Zoom flow uses small pure-Python block matching, not learned flow.",
            ],
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("goldens", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument(
        "--real-calibration",
        type=Path,
        default=DEFAULT_REAL_CALIBRATION,
    )
    args = parser.parse_args(argv)
    directories = sorted(
        path
        for path in args.goldens.iterdir()
        if (path / "transition-truth.json").is_file()
    )
    try:
        report = evaluate_transition_goldens(
            directories,
            args.report,
            ffmpeg=args.ffmpeg,
            ffprobe=args.ffprobe,
            real_calibration_path=args.real_calibration,
        )
    except (OSError, ValueError, TransitionProbeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    for signature, result in report["signatures"].items():
        print(f"{signature}: precision={result['precision']:.3f}")
    real_precision = report["real_video_calibration"]["precision"]
    if real_precision["available"]:
        print(f"real-video dissolve precision: {real_precision['value']:.3f}")
    else:
        print("real-video dissolve precision: unavailable (unjudged corpus)")
    print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
