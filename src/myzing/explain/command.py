"""Explain a video's measured editing style and how to approximate it."""

import argparse
import json

from .api import _explain


def run(argv):
    parser = argparse.ArgumentParser(prog="zing explain", description=__doc__)
    parser.add_argument("video")
    parser.add_argument("--out", help="new output folder, outside the source folder")
    parser.add_argument("--against", help="compare a second video with this reference")
    parser.add_argument("--no-transitions", dest="transitions", action="store_false")
    parser.add_argument("--allow-download", action="store_true", help="explicit URL download consent; never downloads models")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = _explain(args.video, args.out, transitions=args.transitions,
                      against=args.against, allow_download=args.allow_download)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["ok"]:
        print("\n".join(result["summary"]))
        print(result["card_md"])
        print(result["card_png"])
    else:
        print(result["error"])
    return 0 if result["ok"] else 1
