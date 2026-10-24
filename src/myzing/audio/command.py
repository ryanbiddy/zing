"""zing audio analyze <file> [--breakdown <slug>] [--json]."""

from __future__ import annotations

import argparse
import json
import sys

from myzing import storage
from .api import analyze
from .media import AudioError, MAX_SECONDS


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="zing audio", description="Local audio observations; no downloads or rendering.")
    sub = parser.add_subparsers(dest="command", required=True)
    analysis = sub.add_parser("analyze", help="measure beats, onsets, roles, and source-channel EBU R128 loudness")
    analysis.add_argument("file")
    analysis.add_argument("--breakdown", help="stored breakdown slug with word timings for this same audio")
    analysis.add_argument("--workspace", help="workspace containing the breakdown (defaults to ZING_HOME)")
    analysis.add_argument("--max-seconds", type=float, default=MAX_SECONDS, help="analyze at most this many seconds (maximum 600)")
    analysis.add_argument("--json", action="store_true", help="print the complete versioned audio map")
    fetch = sub.add_parser("fetch-model", help="explicitly download pinned Apache-2.0 CED weights")
    fetch.add_argument("--consent", action="store_true", required=True)
    fetch.add_argument("--workspace")
    fetch.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        with storage.use_workspace(args.workspace or storage.workspace_root()):
            if args.command == "fetch-model":
                # --consent is required by the parser: the same explicit yes as
                # zing doctor --audio-model ced-mini --yes.
                from .tag_models import setup
                print(json.dumps(setup(yes=args.consent, json_mode=args.json), indent=2))
                return 0
            breakdown = storage.load_breakdown(args.breakdown) if args.breakdown else None
            result = analyze(args.file, breakdown=breakdown, max_seconds=args.max_seconds)
    except (AudioError, OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"zing audio: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False, allow_nan=False))
    else:
        tempo = f"{result.tempo.bpm:.2f} BPM ({result.tempo.confidence:.2f} confidence)" if result.tempo.bpm else result.tempo.status
        print(f"Analyzed {result.duration_seconds:.3f}s: tempo {tempo}, {len(result.beats)} beats, {len(result.onsets)} onsets")
        loudness = result.loudness
        print(f"Loudness: {loudness.integrated_lufs} LUFS; range {loudness.loudness_range_lu} LU; true peak {loudness.true_peak_dbtp} dBTP")
        for segment in result.segments:
            print(f"  {segment.start:.3f}-{segment.end:.3f}s {segment.label} ({segment.confidence:.2f})")
        for warning in result.warnings:
            print(f"  warning: {warning}")
    return 0
