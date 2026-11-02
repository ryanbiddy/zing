"""`zing factory`: turn one long episode into a pack of social clips with on-screen visuals, graphics and copy."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _shapes(value: str) -> list[str]:
    return [s.strip() for s in value.split(",") if s.strip()]


def _clips(value: str) -> set[int]:
    return {int(x) for x in value.split(",") if x.strip()}


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="zing factory", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="start a project from a local episode file")
    new.add_argument("project", type=Path)
    new.add_argument("--media", type=Path, required=True, help="the local episode video")
    new.add_argument("--transcript", type=Path, help="SRT, VTT or word JSON; without one the episode is transcribed")
    new.add_argument("--offset", type=float, default=0.0, help="seconds to add to the transcript's times")
    new.add_argument("--name", help="source credit, e.g. the show and episode")
    new.add_argument("--url", default="", help="the source link used in first comments")
    new.add_argument("--date", default="", help="the source's date; copy never calls older news 'new'")
    new.add_argument("--tag", default="", help="short on-screen source tag")
    new.add_argument("--moments", type=int, default=None, help="clips to scout (default 8; launch: films, default 2)")
    new.add_argument("--mode", choices=("context", "fun", "documentary", "launch"), default="context",
                     help="documentary: archival photos and documents, the speaker as narrator (pair with --pack documentary); "
                          "launch: one launch film from a long demo or interview, assembled from several parts")
    new.add_argument("--shapes", type=_shapes, default=None, help="any of 9x16,4x5,1x1,16x9 (default 9x16,1x1; launch 16x9,1x1,9x16)")
    new.add_argument("--pack", default=None, help="style pack (see 'zing factory packs'; default zing, launch for launch films)")
    new.add_argument("--brand-name", help="launch: the product's name for the title and end card")
    new.add_argument("--brand-url", help="launch: the product's url for the end card")
    new.add_argument("--cta", help="launch: a short call to action for the end card")
    new.add_argument("--public", action="store_true", help="only visuals cleared for reuse or with attribution")
    new.add_argument("--no-parallax", dest="parallax", action="store_false",
                     help="keep photos flat instead of moving through their depth")
    go = commands.add_parser("run", help="advance the project; stops when it needs answers (host judge)")
    go.add_argument("project", type=Path)
    go.add_argument("--judge", choices=("host", "claude"), default="host",
                    help="host: write prompts for you or your agent to answer; claude: ask Claude Code's CLI")
    go.add_argument("--model", default=None, help="model for --judge claude")
    go.add_argument("--clips", type=_clips, help="only these clip numbers, e.g. 1,3")
    commands.add_parser("status", help="progress, pending prompts and model cost").add_argument("project", type=Path)
    ans = commands.add_parser("answer", help="answer a pending prompt with JSON from a file or '-' for stdin")
    ans.add_argument("project", type=Path)
    ans.add_argument("task")
    ans.add_argument("answer", help="path to the answer, or - to read stdin")
    redo = commands.add_parser("redo", help="forget one judgment so the next run asks again")
    redo.add_argument("project", type=Path)
    redo.add_argument("task", help="scout, or clipNN-plan / clipNN-pick / clipNN-copy")
    ren = commands.add_parser("render", help="re-render one clip in a shape and style pack")
    ren.add_argument("clip", type=Path)
    ren.add_argument("--shape", default="9x16")
    ren.add_argument("--pack", default="zing")
    ren.add_argument("--no-parallax", dest="parallax", action="store_const", const=False, default=None,
                     help="keep photos flat for this render")
    commands.add_parser("review", help="rebuild the local review page").add_argument("project", type=Path)
    learn = commands.add_parser("learn-style", help="learn a style pack from a clip you like, then check the copy against it")
    learn.add_argument("reference", type=Path, help="a local clip whose captions and pacing you want")
    learn.add_argument("--name", required=True, help="the new pack's name, e.g. bold-yellow")
    learn.add_argument("--sample", type=Path, required=True, help="a factory clip folder to render the trial with")
    learn.add_argument("--rounds", type=int, default=3)
    learn.add_argument("--base", default="zing", help="pack to start from for anything not learned")
    serve = commands.add_parser("serve", help="open the local review dashboard for a project (127.0.0.1 only)")
    serve.add_argument("project", type=Path)
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--judge", choices=("host", "claude"), default="host", help="who answers when Run needs judgments")
    commands.add_parser("packs", help="list style packs")
    depth = commands.add_parser("fetch-depth", help="download the depth model that moves photos (Apache-2.0, about 99 MB)")
    depth.add_argument("--yes", action="store_true", help="agree to the download")
    commands.add_parser("doctor", help="check FFmpeg, Node, the sidecar, a browser and the models")
    args = parser.parse_args(argv)
    try:
        from . import pipeline
        from .judge import Judge
        if args.command == "new":
            result = pipeline.init(args.project, args.media, transcript=args.transcript, offset=args.offset,
                                   name=args.name, url=args.url, date=args.date, tag=args.tag,
                                   mode=args.mode, public=args.public, parallax=args.parallax,
                                   **{k: v for k, v in {"shapes": args.shapes, "pack": args.pack,
                                                        "moments": args.moments}.items() if v is not None},
                                   **({"brand": {k: v for k, v in {"name": args.brand_name, "url": args.brand_url,
                                                                    "cta": args.cta}.items() if v}} if args.brand_name else {}))
        elif args.command == "run":
            judge = Judge(args.project, args.judge, **({"model": args.model} if args.model else {}))
            result = pipeline.run(args.project, judge, only=args.clips, say=lambda m: print(m, file=sys.stderr, flush=True))
        elif args.command == "status":
            result = pipeline.status(args.project)
        elif args.command == "answer":
            text = sys.stdin.read() if args.answer == "-" else Path(args.answer).read_text(encoding="utf-8")
            result = pipeline.answer(args.project, args.task, text)
        elif args.command == "redo":
            pipeline.redo(args.project, args.task)
            result = {"task": args.task, "forgotten": True}
        elif args.command == "render":
            from .render import render
            result = {"rendered": str(render(args.clip, args.shape, args.pack, parallax=args.parallax))}
        elif args.command == "review":
            from .review import build
            result = {"review": str(build(args.project))}
        elif args.command == "learn-style":
            from .learn import learn
            result = learn(args.reference, args.name, args.sample, rounds=args.rounds, base=args.base,
                           say=lambda m: print(m, file=sys.stderr, flush=True))
        elif args.command == "serve":
            from .serve import serve
            serve(args.project, args.port, args.judge, say=lambda m: print(m, file=sys.stderr, flush=True))
            return 0
        elif args.command == "fetch-depth":
            from . import depth
            path = depth.fetch(consent=args.yes, progress=lambda m: print(m, file=sys.stderr, flush=True))
            result = {"model": str(path), "verified": True, "license": "Apache-2.0", "revision": depth.REVISION}
        elif args.command == "packs":
            from .render import theme, themes
            result = {name: theme(name)["name"] for name in themes()}
        else:
            from .tools import check
            result = check()
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"zing factory: {exc}", file=sys.stderr)
        return 2
