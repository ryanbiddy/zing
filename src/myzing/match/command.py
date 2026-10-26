"""zing match: one reference, local clips, and three verified drafts."""

import argparse
import json
import sys
from pathlib import Path

from .api import init, validate
from .jobs import execute


def run(argv):
    if argv and argv[0] == "screen":
        from myzing.screen.command import match
        return match(argv[1:])
    parser = argparse.ArgumentParser(prog="zing match", description=__doc__)
    from myzing.delivery_options import add_options, overrides
    add_options(parser)
    from myzing.reference_range import add_options as add_range_options
    add_range_options(parser)
    parser.add_argument("reference")
    parser.add_argument("--clips", required=True)
    parser.add_argument("--out", required=True)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--brief")
    source.add_argument("--answers", help="JSON object using zing brief answer fields")
    parser.add_argument("--drafts", type=int, choices=[3], default=3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--color", choices=("source", "reference"), default="source",
                        help="keep source color (default), or opt into fitting the reference grade")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--no-repair-asr", dest="repair_asr", action="store_false",
                        help="disable bounded ASR repair; exclude clips with invalid word timings")
    parser.add_argument("--allow-download", action="store_true", help="explicit consent to acquire the reference URL via study; never downloads models")
    parser.add_argument("--json", action="store_true", help="final summary on stdout; progress on stderr")
    args = parser.parse_args(argv)
    options = vars(args).copy()
    override_names = ("caption_options", "caption_mode", "picture_crop", "target_mb", "video_bitrate_kbps", "short_side")
    for name in override_names:
        options.pop(name, None)
    json_output = options.pop("json")
    try:
        if args.answers is not None:
            options["answers"] = json.loads(args.answers)
        values = overrides(args)
        if args.brief is None and args.answers is None and not (args.resume and (Path(args.out) / "brief.json").is_file()):
            if not sys.stdin.isatty():
                raise ValueError("Noninteractive match requires --brief <file> or --answers '<json>'.")
            # The existing interview reads inventory. Initialize it first, then
            # pass completed answers into the supervised worker, never stdin.
            validate(**{**options, "answers": {}})
            root = Path(args.out).expanduser().resolve()
            init(args.reference, args.clips, root)
            from myzing.brief.questions import interview
            options["answers"] = interview(root, sys.stdin, sys.stderr).to_dict()
        if values:
            from myzing.brief.api import load_brief
            saved = Path(args.out) / "brief.json"
            existing = (load_brief(args.brief).to_dict() if args.brief else options.get("answers")
                        if options.get("answers") is not None else load_brief(saved).to_dict() if args.resume and saved.is_file() else {})
            if "target_mb" in values:
                existing.pop("video_bitrate_kbps", None)
            if "video_bitrate_kbps" in values:
                existing.pop("target_mb", None)
            options["answers"], options["brief"] = {**existing, **values}, None
        validate(**options)
        result = execute(options, progress=lambda text: print(text, file=sys.stderr, flush=True))
    except KeyboardInterrupt:
        result = {"status": "cancelled", "summary": "Match cancelled before work began; completed checkpoints can be resumed."}
    except (ValueError, OSError, RuntimeError) as exc:
        result = {"status": "failed", "error": str(exc)}
    if json_output:
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    else:
        print(result.get("summary", result.get("error", "Match failed")))
        if result.get("comparison"):
            print(result["comparison"])
        for item in result.get("failures", []):
            print(f"{item['step']}: {item['error']} (log: {item['log']})", file=sys.stderr)
        for item in result.get("shortages", []):
            print(json.dumps(item, ensure_ascii=False), file=sys.stderr)
    return 0 if result["status"] == "ready" else 130 if result["status"] == "cancelled" else 1
