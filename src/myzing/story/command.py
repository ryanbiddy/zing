"""`zing story`: make a narrated paper-cutout video from a local story file."""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

from . import StoryError
from . import contract


def _stills(value: str) -> list[float]:
    try:
        times = [float(part.strip()) for part in value.split(",")]
        if not times or any(not math.isfinite(t) or t < 0 for t in times):
            raise ValueError
        return times
    except ValueError:
        raise argparse.ArgumentTypeError("stills need comma-separated seconds, all finite and at least zero") from None


def _voice_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--voice", default="af_heart", help="Kokoro voice name (default af_heart)")
    parser.add_argument("--speed", type=float, default=1.0, help="Kokoro speech speed (default 1)")
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


def build(directory: Path, *, voice: str = "af_heart", speed: float = 1.0,
          lines_dir: Path | None = None, out: Path | None = None, synthetic: bool = False) -> dict:
    from . import heads, receipt, render
    from .voice import generate

    directory = Path(directory)
    story = contract.load(directory)
    generate(directory, story, voice=voice, speed=speed, lines_dir=lines_dir, synthetic=synthetic)
    heads.generate(directory, story)
    output = render.render(directory, out=out)
    receipt_path = receipt.write(directory, output)
    return {"rendered": str(output), "receipt": str(receipt_path)}


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="zing story", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="print every story.json problem").add_argument("directory", type=Path)
    voice = commands.add_parser("voice", help="write narration.wav and exact line timings")
    voice.add_argument("directory", type=Path)
    _voice_options(voice)
    commands.add_parser("heads", help="cut licensed cast photos into head stickers").add_argument("directory", type=Path)
    render = commands.add_parser("render", help="render a 1080x1920 MP4 or review JPEGs")
    render.add_argument("directory", type=Path)
    render.add_argument("--out", type=Path, metavar="FILE", help="output video (default <dir>/story.mp4)")
    render.add_argument("--stills", type=_stills, metavar="t1,t2,...", help="write JPEGs at these seconds instead of a video")
    build_parser = commands.add_parser("build", help="check, voice, heads, render and write a receipt")
    build_parser.add_argument("directory", type=Path)
    _voice_options(build_parser)
    build_parser.add_argument("--out", type=Path, metavar="FILE")
    args = parser.parse_args(argv)
    try:
        directory = args.directory.expanduser()
        if args.command == "check":
            problems = check(directory)
            if problems:
                for problem in problems:
                    print(f"zing story: {problem}", file=sys.stderr)
                return 1
            result = {"ok": True, "story": str(directory / "story.json")}
        elif args.command == "voice":
            from .voice import generate
            result = generate(directory, contract.load(directory), voice=args.voice, speed=args.speed,
                              lines_dir=args.lines_dir.expanduser() if args.lines_dir else None,
                              synthetic=args.synthetic_voice)
        elif args.command == "heads":
            from .heads import generate
            result = {"heads": generate(directory, contract.load(directory))}
        elif args.command == "render":
            from .render import render
            output = render(directory, out=args.out, stills=args.stills)
            result = {"stills": [str(path) for path in output]} if isinstance(output, list) else {"rendered": str(output)}
        else:
            result = build(directory, voice=args.voice, speed=args.speed,
                           lines_dir=args.lines_dir.expanduser() if args.lines_dir else None, out=args.out,
                           synthetic=args.synthetic_voice)
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
