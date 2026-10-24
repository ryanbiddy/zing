"""Offline before/after cut scoring against frozen V1 labels and transition truth."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from myzing.study.shots import detect_shots
from myzing.study.source_map import build_source_map, planning_shots
from tools.eval.real.scoring import transition_score
from tools.eval.transition_corpus import corpus_cases, generate_case


def measure(path, duration, fps):
    original = detect_shots(path, duration, fps)
    if not original.shots:
        raise RuntimeError(f"No shot measurement for {path}: {original.warnings}")
    source_map = build_source_map(path, duration, fps, original.shots)
    if source_map.status != "measured":
        raise RuntimeError(source_map.warnings)
    b = SimpleNamespace(shots=original.shots, meta=SimpleNamespace(duration=duration, fps=fps),
                        provenance={"source_map": source_map.to_dict()})
    return original.shots, planning_shots(b), source_map.to_dict()


def evaluate(clips, labels, thresholds, paths):
    before, after, maps = {}, {}, {}
    for id, clip in clips.items():
        a, b, maps[id] = measure(paths[id], clip["duration"], clip["fps"])
        for target, shots in ((before, a), (after, b)):
            target[id] = {"breakdown": {"provenance": {}, "shots": [asdict(s) for s in shots]}}
    return {"before": transition_score(clips, labels, before, "hard_cut", thresholds, shots=True),
            "after": transition_score(clips, labels, after, "hard_cut", thresholds, shots=True),
            "maps": maps}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clips", type=Path, required=True, help="Copied V1 clips directory")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    here = Path(__file__).parent
    manifest = json.loads((here / "real/manifest.json").read_text(encoding="utf-8"))
    labels = json.loads((here / "real/labels.json").read_text(encoding="utf-8"))
    clips = {c["id"]: c for c in manifest["clips"]}
    paths = {id: args.clips / Path(c["file"]).name for id, c in clips.items()}
    for id, path in paths.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == clips[id]["sha256"] == labels["clips"][id]["media_sha256"]
    result = {"version": 1, "v1": evaluate(clips, labels["clips"], labels["thresholds"], paths),
              "label_limit": labels["annotator"], "transition_truth": {}}
    (args.out / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    for split in ("calibration", "held_out"):
        clips, truth, paths = {}, {}, {}
        for case in corpus_cases(split):
            directory = generate_case(case, args.out / "transition-media")
            paths[case.case_id] = directory / "clip.mp4"
            clips[case.case_id] = {"fps": case.fps, "duration": case.duration}
            events = case.truth_events()
            # A whip transition contains an authored hard boundary at its
            # midpoint. Other gradual signatures are not hard-cut truth.
            if case.kind == "whip_pan":
                t = round((case.start + case.length / 2) * case.fps) / case.fps
                events = [{"signature": "hard_cut", "start_seconds": t, "end_seconds": t}]
            truth[case.case_id] = {"transition_windows": [[0, case.duration]], "transition_events": events}
        result["transition_truth"][split] = evaluate(clips, truth, labels["thresholds"], paths)
        (args.out / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    for name, row in [("v1", result["v1"]), *result["transition_truth"].items()]:
        print(name, {when: {k: row[when][k] for k in ("tp", "fp", "fn", "precision", "recall")}
                     for when in ("before", "after")})


if __name__ == "__main__":
    main()
