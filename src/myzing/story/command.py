"""`zing story`: make a narrated paper-cutout video from a local story file."""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

from . import StoryError, data_path
from . import contract
from .starter import new


def _stills(value: str) -> list[float]:
    try:
        times = [float(part.strip()) for part in value.split(",")]
        if not times or any(not math.isfinite(t) or t < 0 for t in times):
            raise ValueError
        return times
    except ValueError:
        raise argparse.ArgumentTypeError("stills need comma-separated seconds, all finite and at least zero") from None


def _voice_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider", choices=("kokoro", "elevenlabs", "lines"), help="voice provider (default: Zing's configured provider, or lines with --lines-dir)")
    parser.add_argument("--voice", help="provider voice name or ID (default: provider setting)")
    parser.add_argument("--speed", type=float, default=1.0, help="speech speed (default 1)")
    parser.add_argument("--lines-dir", type=Path, metavar="DIR", help="use supplied <beat-id>-<line-index>.wav files")
    parser.add_argument("--synthetic-voice", action="store_true",
                        help="the supplied recordings are a synthetic voice; keeps the AI voice credit")


def check(directory: Path) -> list[str]:
    """Report every contract error without requiring optional media packages."""
    path = Path(directory) / "story.json"
    try:
        story = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"cannot read story.json: {exc}"]
    return contract.check(story, directory=Path(directory))


def check_json(directory: Path) -> list[dict[str, str]]:
    result = []
    for error in check(directory):
        path, separator, message = error.partition(": ")
        if path == "cannot read story.json" or not separator:
            path, message = "story.json", error
        result.append({"path": path, "message": message})
    return result


def build(directory: Path, *, provider: str | None = None, voice: str | None = None, speed: float = 1.0,
          lines_dir: Path | None = None, out: Path | None = None, synthetic: bool = False,
          no_sfx: bool = False) -> dict:
    from . import heads, images, receipt, render
    from .voice import generate

    directory = Path(directory)
    story = contract.load(directory)
    generate(directory, story, provider=provider, voice=voice, speed=speed, lines_dir=lines_dir, synthetic=synthetic)
    heads.generate(directory, story)
    images.generate(directory, story)
    output = render.render(directory, out=out, **({"no_sfx": True} if no_sfx else {}))
    receipt_path = receipt.write(directory, output)
    return {"rendered": str(output), "receipt": str(receipt_path)}


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="zing story", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    new_parser = commands.add_parser("new", help="create a draft for an agent to write")
    new_parser.add_argument("directory", type=Path)
    new_parser.add_argument("--topic", required=True)
    commands.add_parser("prompt", help="print the bundled story writing prompt")
    check_parser = commands.add_parser("check", help="print every story.json problem")
    check_parser.add_argument("directory", type=Path)
    check_parser.add_argument("--json", action="store_true", help="print a JSON list of path/message problems")
    voice = commands.add_parser("voice", help="write narration.wav and exact line timings")
    voice.add_argument("directory", type=Path)
    _voice_options(voice)
    heads = commands.add_parser("heads", help="cut licensed cast photos into head stickers")
    heads.add_argument("directory", type=Path)
    heads.add_argument("--sheet", action="store_true", help="also write heads/sheet.png for review")
    images = commands.add_parser("images", help="prepare licensed pictures as photos or stickers")
    images.add_argument("directory", type=Path)
    images.add_argument("--sheet", action="store_true", help="also write images/sheet.png for review")
    find = commands.add_parser("find", help="search Wikimedia Commons for licensed pictures (uses the network)")
    find.add_argument("query")
    find.add_argument("--limit", type=int, default=10)
    find.add_argument("--json", action="store_true", help="print candidate metadata as JSON")
    fetch = commands.add_parser("fetch", help="download one Commons picture and save its rights (uses the network)")
    fetch.add_argument("directory", type=Path)
    fetch.add_argument("title_or_url", metavar="FILE")
    fetch.add_argument("--as", dest="target", required=True, metavar="photo:CAST_ID|image:IMAGE_ID")
    render = commands.add_parser("render", help="render a 1080x1920 MP4 or review JPEGs")
    render.add_argument("directory", type=Path)
    render.add_argument("--out", type=Path, metavar="FILE", help="output video (default <dir>/story.mp4)")
    render.add_argument("--stills", type=_stills, metavar="t1,t2,...", help="write JPEGs at these seconds instead of a video")
    render.add_argument("--no-sfx", action="store_true", help="turn off synthesized sound effects")
    build_parser = commands.add_parser("build", help="check, voice, heads, images, render and write a receipt")
    build_parser.add_argument("directory", type=Path)
    _voice_options(build_parser)
    build_parser.add_argument("--out", type=Path, metavar="FILE")
    build_parser.add_argument("--no-sfx", action="store_true", help="turn off synthesized sound effects")
    args = parser.parse_args(argv)
    try:
        if args.command == "prompt":
            print(data_path("prompts", "story.md").read_text(encoding="utf-8"), end="")
            return 0
        if args.command == "find":
            from .commons import find
            candidates = find(args.query, limit=args.limit)
            if args.json:
                print(json.dumps(candidates, indent=2, ensure_ascii=False))
            else:
                for item in candidates:
                    status = "accepted" if item["accepted"] else "refused: " + item["reason"]
                    print(f"{item['title']}\n  {item['license']} | {item['credit']}\n"
                          f"  {item['width']}x{item['height']} px | {item['bytes']} bytes | {status}\n"
                          f"  {item['source_url']}")
                if not candidates:
                    print("No Commons pictures found.")
            return 0
        directory = args.directory.expanduser()
        if args.command == "new":
            result = new(directory, topic=args.topic)
        elif args.command == "check":
            if args.json:
                problems = check_json(directory)
                print(json.dumps(problems, indent=2, ensure_ascii=False))
                return 1 if problems else 0
            problems = check(directory)
            if problems:
                for problem in problems:
                    print(f"zing story: {problem}", file=sys.stderr)
                return 1
            result = {"ok": True, "story": str(directory / "story.json")}
        elif args.command == "voice":
            from .voice import generate
            result = generate(directory, contract.load(directory), provider=args.provider, voice=args.voice, speed=args.speed,
                              lines_dir=args.lines_dir.expanduser() if args.lines_dir else None,
                              synthetic=args.synthetic_voice)
        elif args.command == "heads":
            from .heads import generate
            result = {"heads": generate(directory, contract.load(directory), **({"sheet": True} if args.sheet else {}))}
            if args.sheet:
                result["sheet"] = str(directory / "heads" / "sheet.png")
        elif args.command == "images":
            from .images import generate
            result = {"images": generate(directory, contract.load(directory), **({"sheet": True} if args.sheet else {}))}
            if args.sheet:
                result["sheet"] = str(directory / "images" / "sheet.png")
        elif args.command == "fetch":
            from .commons import fetch
            result = fetch(directory, args.title_or_url, args.target)
        elif args.command == "render":
            from .render import render
            output = render(directory, out=args.out, stills=args.stills, **({"no_sfx": True} if args.no_sfx else {}))
            result = {"stills": [str(path) for path in output]} if isinstance(output, list) else {"rendered": str(output)}
        else:
            result = build(directory, provider=args.provider, voice=args.voice, speed=args.speed,
                           lines_dir=args.lines_dir.expanduser() if args.lines_dir else None, out=args.out,
                           synthetic=args.synthetic_voice, no_sfx=args.no_sfx)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except subprocess.SubprocessError as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace")
        print(f"zing story: {detail[-500:]}", file=sys.stderr)
        return 2
    except (StoryError, OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"zing story: {exc}", file=sys.stderr)
        return 2
