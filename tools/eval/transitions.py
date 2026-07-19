"""Evaluate transition signatures against synthetic and real calibration data."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from myzing.study.transitions import (
    DETECTOR_VERSION,
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
DEFAULT_REAL_RECALL_AUDIT = (
    HERE / "fixtures" / "transitions" / "real-recall-audit.json"
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


def summarize_signature_recall(
    cases: Sequence[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Count case-level false negatives without inventing empty-set recall."""
    summary = {}
    for signature in SIGNATURES:
        true_positives = sum(
            signature in case["truth"] and signature in case["predicted"]
            for case in cases
        )
        false_negatives = sum(
            signature in case["truth"] and signature not in case["predicted"]
            for case in cases
        )
        truth_count = true_positives + false_negatives
        available = truth_count > 0
        summary[signature] = {
            "available": available,
            "true_positives": true_positives,
            "false_negatives": false_negatives,
            "truth_count": truth_count,
            "recall": (
                round(true_positives / truth_count, 6)
                if available
                else None
            ),
        }
    return summary


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(HERE.parents[1]).as_posix()
    except ValueError:
        return path.name


def summarize_real_transition_recall(
    audit_path: Path = DEFAULT_REAL_RECALL_AUDIT,
) -> dict[str, Any]:
    """Audit whether the requested real corpora can support recall."""
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    corpora = audit.get("corpora")
    if not isinstance(corpora, list) or not corpora:
        raise ValueError("real transition recall audit has no corpora")

    corpus_counts = {}
    sources = []
    exhaustive_count = 0
    measured_sources = 0
    measured_detector_versions = set()
    measured_accuracy_statuses = set()
    predicted_event_counts = {signature: 0 for signature in SIGNATURES}
    for corpus in corpora:
        corpus_id = corpus.get("id")
        corpus_sources = corpus.get("sources")
        if not isinstance(corpus_id, str) or not isinstance(
            corpus_sources,
            list,
        ):
            raise ValueError("real transition recall audit has malformed corpus")
        corpus_counts[corpus_id] = len(corpus_sources)
        for source in corpus_sources:
            annotation = source.get("annotation")
            if not isinstance(annotation, dict):
                raise ValueError(
                    f"recall audit source has no annotation: {source}"
                )
            exhaustive = annotation.get("exhaustive_transition_events")
            if not isinstance(exhaustive, bool):
                raise ValueError(
                    "recall audit annotation must state whether it is exhaustive"
                )
            if exhaustive:
                exhaustive_count += 1
                if not isinstance(source.get("truth_events"), list):
                    raise ValueError(
                        "exhaustively labeled source has no truth_events: "
                        f"{source.get('fixture_id')}"
                    )
            measurement = source.get("detector_measurement")
            if measurement is not None:
                if not isinstance(measurement, dict):
                    raise ValueError(
                        "recall audit detector measurement must be an object"
                    )
                counts = measurement.get("predicted_event_counts")
                if not isinstance(counts, dict) or set(counts) != set(SIGNATURES):
                    raise ValueError(
                        "recall audit detector measurement must count every "
                        "signature"
                    )
                if any(
                    not isinstance(count, int) or isinstance(count, bool)
                    or count < 0
                    for count in counts.values()
                ):
                    raise ValueError(
                        "recall audit detector event counts must be "
                        "non-negative integers"
                    )
                measured_sources += 1
                measured_detector_versions.add(
                    measurement["detector_version"]
                )
                measured_accuracy_statuses.add(
                    measurement["accuracy_status"]
                )
                for signature, count in counts.items():
                    predicted_event_counts[signature] += count
            sources.append(
                {
                    "fixture_id": source["fixture_id"],
                    "corpus": corpus_id,
                    "annotation_status": annotation["status"],
                    "exhaustive_transition_events": exhaustive,
                    "reason": annotation["reason"],
                }
            )

    if exhaustive_count:
        raise ValueError(
            "real recall calculation is not implemented for labeled sources"
        )
    if measured_sources and measured_detector_versions != {DETECTOR_VERSION}:
        raise ValueError(
            "real recall audit detector measurements are stale: "
            f"expected version {DETECTOR_VERSION}, found "
            f"{sorted(measured_detector_versions)}"
        )
    reason = (
        "None of the audited real sources has exhaustive exact transition "
        "events and types, so false negatives and real-video recall cannot "
        "be calculated."
    )
    by_signature = {
        signature: {
            "available": False,
            "value": None,
            "truth_event_count": 0,
            "reason": reason,
        }
        for signature in SIGNATURES
    }
    detector_execution = {
        "available": measured_sources > 0,
        "accuracy_status": (
            next(iter(measured_accuracy_statuses))
            if len(measured_accuracy_statuses) == 1
            else "mixed"
        ),
        "detector_version": (
            next(iter(measured_detector_versions))
            if len(measured_detector_versions) == 1
            else None
        ),
        "source_count": measured_sources,
        "predicted_event_counts": predicted_event_counts,
    }
    return {
        "audit_schema_version": audit["schema_version"],
        "audit_path": _display_path(audit_path),
        "audit_sha256": _sha256(audit_path),
        "source_count": len(sources),
        "corpora": corpus_counts,
        "exhaustively_labeled_source_count": exhaustive_count,
        "recall": {
            "available": False,
            "value": None,
            "reason": reason,
            "by_signature": by_signature,
        },
        "detector_execution": detector_execution,
        "production_disposition": audit["disposition"]["status"],
        "production_disposition_reason": audit["disposition"]["reason"],
        "sources": sources,
    }


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
    recall = summarize_signature_recall(cases)
    signatures = {
        signature: {
            **signatures[signature],
            **recall[signature],
        }
        for signature in SIGNATURES
    }
    real_calibration = summarize_real_dissolve_calibration(
        real_calibration_path
    )
    real_recall = summarize_real_transition_recall()
    recall_values = [
        value["recall"]
        for value in signatures.values()
        if value["recall"] is not None
    ]
    report = {
        "prototype_schema_version": 3,
        "signatures": signatures,
        "macro_precision": round(
            sum(value["precision"] for value in signatures.values())
            / len(signatures),
            6,
        ),
        "macro_recall": round(
            sum(recall_values) / len(recall_values),
            6,
        ),
        "real_video_calibration": real_calibration,
        "real_video_recall": real_recall,
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
                "Reported signature recall is case-level synthetic recall.",
                "All eight requested real sources were audited; none has exhaustive exact transition labels, so real-video recall is unavailable.",
                "Rejecting prior real-video candidates is not evidence of real-video recall.",
                "Production transition types remain experimental until a labeled real corpus makes false negatives measurable.",
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
        print(
            f"{signature}: precision={result['precision']:.3f} "
            f"recall={result['recall']:.3f}"
        )
    real_precision = report["real_video_calibration"]["precision"]
    if real_precision["available"]:
        print(f"real-video dissolve precision: {real_precision['value']:.3f}")
    else:
        print("real-video dissolve precision: unavailable (unjudged corpus)")
    print("real-video transition recall: unavailable (no exhaustive labels)")
    print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
