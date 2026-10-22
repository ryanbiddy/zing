"""Offline, clip-split transition evaluation; held-out runs require a frozen detector."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from myzing.study import transitions
from tools.eval.real import scoring
from tools.eval.real.run_real_eval import (
    HERE,
    inside,
    read_json,
    sha256,
    verified,
    write_json,
)

CLASSES = (
    "hard_cut",
    "dissolve",
    "wipe",
    "zoom_punch",
    "audio_aligned_cut",
    "whip_pan",
    "flash",
)


def fingerprint():
    """Freeze decisions independently of the subsequently published validation numbers."""
    files = [Path(transitions.__file__), Path(transitions.models.__file__)]
    trees = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        tree.body = [
            node
            for node in tree.body
            if not (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(t, ast.Name)
                    and t.id in {"VALIDATION_STATUS", "EXPERIMENTAL_RECALL_WARNING"}
                    for t in node.targets
                )
            )
        ]
        trees.append(ast.dump(tree))
    return {
        "decision_sha256": hashlib.sha256("\n".join(trees).encode()).hexdigest(),
        "source_sha256": {p.name: sha256(p) for p in files},
        "detector_version": transitions.DETECTOR_VERSION,
    }


def load_split(path=HERE / "transition-split.json"):
    split = read_json(path)
    manifest, labels = (
        read_json(HERE / "manifest.json"),
        read_json(HERE / "labels.json"),
    )
    a, b = split["calibration"], split["held_out"]
    if (
        split.get("version") != 1
        or not a
        or not b
        or len(set(a + b)) != len(a + b)
        or set(a + b) != {c["id"] for c in manifest["clips"]}
    ):
        raise ValueError("Split must partition every manifest clip exactly once")
    for clip in manifest["clips"]:
        if labels["clips"][clip["id"]]["media_sha256"] != clip["sha256"]:
            raise ValueError(f"Label/media hash mismatch: {clip['id']}")
    return split, manifest, labels


def overlap(event, start, end):
    return event["start_seconds"] <= end and event["end_seconds"] >= start


def score_split(manifest, labels, observations, ids):
    clips = {c["id"]: c for c in manifest["clips"] if c["id"] in ids}
    actual = observations["clips"]
    for id, clip in clips.items():
        if actual.get(id, {}).get("media_sha256") != clip["sha256"]:
            raise ValueError(f"Missing or mismatched observation: {id}")
    result = {}
    for kind in CLASSES:
        stats = scoring.transition_score(
            clips, labels["clips"], actual, kind, labels["thresholds"]
        )
        if stats["unavailable"]:
            raise ValueError(f"Missing transition evidence: {stats['unavailable']}")
        for row in stats["per_clip"]:
            unknowns = [
                e
                for e in actual[row["clip"]]["breakdown"]["provenance"][
                    "transition_evidence"
                ]
                if e["signature"] == "unknown"
            ]
            # Count missed truths covered by an abstention, including long motion runs.
            row["unknown"] = sum(
                any(overlap(u, t["start_seconds"], t["end_seconds"]) for u in unknowns)
                for t in row["missed"]
            )
        stats["unknown"] = sum(r["unknown"] for r in stats["per_clip"])
        stats["truth_count"] = stats["tp"] + stats["fn"]
        result[kind] = stats
    unknown_count = sum(
        e["signature"] == "unknown"
        and any(overlap(e, a, b) for a, b in labels["clips"][id]["transition_windows"])
        for id in ids
        for e in actual[id]["breakdown"]["provenance"]["transition_evidence"]
    )
    return {
        "signatures": result,
        "unknown_count": unknown_count,
        "reviewed_seconds": sum(
            b - a for id in ids for a, b in labels["clips"][id]["transition_windows"]
        ),
        "unknown_definition": "Per class: missed truths intersected by an explicit unknown. Overall: unknown events intersecting reviewed windows. Missing predictions remain FN; no unknown label is inferred.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, required=True, help="read-only pinned real media root"
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--split", choices=("calibration", "held_out"), default="calibration"
    )
    parser.add_argument(
        "--observations",
        type=Path,
        help="rescore frozen V1 observations without inference",
    )
    parser.add_argument(
        "--freeze", type=Path, help="write detector lock before held-out inference"
    )
    parser.add_argument("--lock", type=Path, help="required for held-out inference")
    args = parser.parse_args(argv)
    try:
        split, manifest, labels = load_split()
        inputs = {
            name: sha256(HERE / name)
            for name in (
                "manifest.json",
                "labels.json",
                "transition-split.json",
                "scoring.py",
                "run_transition_eval.py",
            )
        }
        current = {**fingerprint(), "inputs": inputs}
        if args.freeze:
            if args.freeze.exists():
                raise ValueError(
                    "Freeze already exists; do not overwrite a held-out decision lock"
                )
            write_json(
                args.freeze,
                {**current, "frozen_utc": datetime.now(timezone.utc).isoformat()},
            )
        if args.split == "held_out" and not args.observations:
            if not args.lock:
                raise ValueError(
                    "Held-out inference requires --lock frozen before evaluation"
                )
            lock = read_json(args.lock)
            if (
                lock["decision_sha256"] != current["decision_sha256"]
                or lock["inputs"] != inputs
            ):
                raise ValueError(
                    "Detector or inputs changed after freeze; held-out tuning is forbidden"
                )
        if args.out.exists() and any(args.out.iterdir()):
            raise ValueError("--out must be empty; preserve previous runs")
        args.out.mkdir(parents=True, exist_ok=True)
        ids = split[args.split]
        clips = {c["id"]: c for c in manifest["clips"]}
        for id in ids:
            if not verified(inside(args.root, clips[id]["file"]), clips[id]["sha256"]):
                raise ValueError(
                    f"Missing pinned clip {id}; use run_real_eval.py --download explicitly"
                )
        observations = (
            read_json(args.observations)
            if args.observations
            else {"version": 1, "clips": {}}
        )
        if not args.observations:
            for id in ids:
                started = time.monotonic()
                result = transitions.detect_transitions(
                    inside(args.root, clips[id]["file"])
                )
                observations["clips"][id] = {
                    "media_sha256": clips[id]["sha256"],
                    "breakdown": {"provenance": result.provenance},
                    "warnings": result.warnings,
                    "inference_seconds": round(time.monotonic() - started, 3),
                }
                print(f"Measured {args.split}: {id}", flush=True)
        observations = {
            "version": 1,
            "clips": {id: observations["clips"][id] for id in ids},
        }
        write_json(args.out / "observations.json", observations)
        result = score_split(manifest, labels, observations, ids)
        versions = {
            c["breakdown"]["provenance"]["transition_detector_version"]
            for c in observations["clips"].values()
        }
        if len(versions) != 1:
            raise ValueError("Mixed detector versions in observations")
        version = versions.pop()
        result.update(
            version=1,
            split=args.split,
            clips=ids,
            detector_version=version,
            matches_current_detector=version == transitions.DETECTOR_VERSION,
            provenance=current
            if not args.observations
            else {"observations_sha256": sha256(args.observations), "inputs": inputs},
            ffmpeg=subprocess.check_output(
                ["ffmpeg", "-version"], text=True
            ).splitlines()[0],
        )
        # Every miss gets a local, exact-frame PNG; source media remains read-only.
        for kind, stats in result["signatures"].items():
            for row in stats["per_clip"]:
                for i, miss in enumerate(row["missed"]):
                    png = (
                        args.out
                        / f"{row['clip']}-{kind}-{i}-{miss['start_seconds']:.3f}.png"
                    )
                    subprocess.run(
                        [
                            "ffmpeg",
                            "-v",
                            "error",
                            "-i",
                            str(inside(args.root, clips[row["clip"]]["file"])),
                            "-ss",
                            str((miss["start_seconds"] + miss["end_seconds"]) / 2),
                            "-frames:v",
                            "1",
                            str(png),
                        ],
                        check=True,
                        capture_output=True,
                    )
                    miss["png"] = png.resolve().as_posix()
        write_json(args.out / "metrics.json", result)
        print(
            json.dumps(
                {
                    k: {
                        key: s[key]
                        for key in ("tp", "fp", "fn", "precision", "recall", "unknown")
                    }
                    for k, s in result["signatures"].items()
                },
                indent=2,
            )
        )
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"transition evaluation: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
