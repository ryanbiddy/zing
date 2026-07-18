"""Evaluate the production transition detector against synthetic goldens."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from myzing.study.transitions import (
    SIGNATURES,
    TransitionProbeError,
    detect_transition_signatures,
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


def evaluate_transition_goldens(
    directories: Sequence[Path],
    report_path: Path,
    *,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
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
    report = {
        "prototype_schema_version": 1,
        "signatures": signatures,
        "macro_precision": round(
            sum(value["precision"] for value in signatures.values())
            / len(signatures),
            6,
        ),
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
                "Thresholds are calibrated only on exact synthetic 96px goldens.",
                "Precision on these goldens is not evidence of real-video recall.",
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
        )
    except (OSError, ValueError, TransitionProbeError, json.JSONDecodeError) as exc:
        parser.exit(2, f"error: {exc}\n")
    for signature, result in report["signatures"].items():
        print(f"{signature}: precision={result['precision']:.3f}")
    print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
