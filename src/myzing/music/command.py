"""zing music check: measured advice for local candidates."""
import argparse
import json
import sys
from myzing.audio.media import AudioError
from .advice import check_tracks


def run(argv):
    parser = argparse.ArgumentParser(prog="zing music")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="rate local tracks; licensing remains unknown")
    check.add_argument("tracks", nargs="+")
    context = check.add_mutually_exclusive_group()
    context.add_argument("--brief")
    context.add_argument("--plan")
    check.add_argument("--length", type=float)
    check.add_argument("--pace", type=float, help="reference median shot length, seconds")
    check.add_argument("--speech", action="store_true", default=None)
    check.add_argument("--license-record", help="your recorded rights claim; Zing does not verify it")
    check.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = check_tracks(args.tracks, brief=args.brief, plan=args.plan, length=args.length,
                              pace=args.pace, speech=args.speech, license_record=args.license_record)
    except (AudioError, OSError, ValueError, TypeError, KeyError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}))
        else:
            print(f"zing music: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, allow_nan=False))
    else:
        for track in result["tracks"]:
            print(f"{track['rating'].upper()}: {track['track']} ({track['score']}/100)")
            for reason in track["reasons"]:
                print("  " + reason["reason"])
            print("  " + track["licensing"])
    return 0
