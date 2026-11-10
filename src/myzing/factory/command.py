"""`zing factory`: turn one long episode into a pack of social clips with on-screen visuals, graphics and copy."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _shapes(value: str) -> list[str]:
    return [s.strip() for s in value.split(",") if s.strip()]


def _clips(value: str) -> set[int]:
    return {int(x) for x in value.split(",") if x.strip()}


def _port(value: str) -> int:
    port = int(value)
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("Port must be between 0 and 65535. Use 0 for any free port.")
    return port


def _time(value: str) -> float:
    """Seconds, or m:ss / h:mm:ss."""
    parts = value.strip().split(":")
    try:
        return float(sum(float(p) * 60 ** i for i, p in enumerate(reversed(parts))))
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a time: {value!r} (use seconds or m:ss)") from None


def _new_settings(new: argparse.ArgumentParser) -> None:
    new.add_argument("--transcript", type=Path, help="SRT, VTT or word JSON; without one the episode is transcribed")
    new.add_argument("--vocab", action="append", default=[], metavar="TERM,TERM",
                     help="names and terms to spell exactly; repeat or separate with commas")
    new.add_argument("--offset", type=float, help="seconds to add to the transcript's times; skips the sync check")
    new.add_argument("--no-sync-check", action="store_true", help="skip the transcript sync check before scouting")
    new.add_argument("--name", help="source credit, e.g. the show and episode")
    new.add_argument("--url", default="", help="the source link used in first comments")
    new.add_argument("--date", default="", help="the source's date; copy never calls older news 'new'")
    new.add_argument("--rights", choices=("own", "licensed", "permission", "unknown"), default="unknown",
                     help="label the source rights; this never blocks a clip")
    new.add_argument("--brief", type=Path, metavar="FILE", help="JSON campaign rules to copy into the project")
    new.add_argument("--tag", default="", help="short on-screen source tag")
    new.add_argument("--moments", type=int, default=None,
                     help="clips to scout (default 8, or 2 launch films; 0 lets you pick all clips)")
    new.add_argument("--focus", help="what to clip, e.g. 'the pricing argument' or 'funny moments'; the scout favors it")
    new.add_argument("--show", help="the show's name; Post/No calls on its episodes teach the scout for the next one")
    new.add_argument("--mode", choices=("context", "fun", "documentary", "launch"), default="context",
                     help="documentary uses archival photos and documents with the speaker as narrator. Pair with --pack documentary. "
                          "Launch assembles films from several spans of a demo or interview")
    new.add_argument("--shapes", type=_shapes, default=None, help="any of 9x16,4x5,1x1,16x9 (default 9x16,1x1; launch 16x9,1x1,9x16)")
    new.add_argument("--pack", default=None, help="style pack (see 'zing factory packs'; default zing, launch for launch films)")
    new.add_argument("--4k", dest="uhd", action="store_true", help="render every shape at twice its usual width and height")
    new.add_argument("--brand-name", help="the product's name for the title and end card in launch mode")
    new.add_argument("--brand-url", help="the product's url for the end card in launch mode")
    new.add_argument("--cta", help="a short call to action for the end card in launch mode")
    new.add_argument("--news-peg", help="today's news the clips are the backstory to, e.g. 'Elon Musk is a trillionaire again'")
    new.add_argument("--news", action="append", default=[], metavar="URL",
                     help="an article about the news peg (repeatable); clips open on its headline")
    new.add_argument("--public", action="store_true", help="only visuals cleared for reuse or with attribution")
    new.add_argument("--offline", action="store_true", help="fetch nothing; use the host judge and local media")
    new.add_argument("--visuals", type=Path, metavar="DIR", help="use images and videos from this folder")
    new.add_argument("--no-parallax", dest="parallax", action="store_false",
                     help="keep photos flat instead of moving through their depth")
    new.add_argument("--cutout", action="store_true",
                     help="stand the speaker, cut out, in front of the pictures instead of splitting the frame "
                          "(needs 'zing factory fetch-cutout --yes')")
    new.add_argument("--no-upscale", dest="upscale", action="store_false",
                     help="render small photos at their own size instead of upscaling them")


def _settings(args: argparse.Namespace) -> dict:
    return dict(transcript=args.transcript, offset=args.offset, no_sync_check=args.no_sync_check,
                name=args.name, url=args.url, date=args.date, tag=args.tag,
                rights=args.rights or "unknown", brief=args.brief,
                vocab=[term for group in (args.vocab or []) for term in group.split(",")],
                mode=args.mode or "context", public=args.public, parallax=args.parallax, cutout=args.cutout,
                upscale=args.upscale, uhd=args.uhd, offline=args.offline, visuals=args.visuals,
                **{k: v for k, v in {"shapes": args.shapes, "pack": args.pack, "moments": args.moments,
                                     "focus": args.focus, "show": args.show}.items() if v is not None},
                **({"brand": {k: v for k, v in {"name": args.brand_name, "url": args.brand_url,
                                               "cta": args.cta}.items() if v}} if args.brand_name else {}),
                **({"news": {"peg": args.news_peg, "links": args.news}} if args.news_peg or args.news else {}))


def _channel_settings(args: argparse.Namespace) -> tuple[Path, dict]:
    from myzing.channels import registry
    settings = _settings(args)
    if not args.channel:
        if args.source:
            raise registry.ChannelError("--source needs --channel")
        if args.project is None:
            raise registry.ChannelError("a project path or --channel is required")
        return args.project, settings
    for key in ("pack", "mode", "shapes", "moments", "focus", "vocab", "brief", "rights", "name"):
        if getattr(args, key) is None:
            settings.pop(key, None)
    settings["brand"] = {key: value for key, value in (("name", args.brand_name), ("url", args.brand_url), ("cta", args.cta))
                         if value is not None}
    settings = registry.project_settings(args.channel, args.source, **settings)
    project = args.project if args.project is not None else registry.directory(args.channel) / "projects" / args.media.stem
    return project, settings


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="zing factory", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="start a project from a local episode file")
    new.add_argument("project", type=Path, nargs="?")
    new.add_argument("--media", type=Path, required=True, help="the local episode video")
    _new_settings(new)
    new.add_argument("--channel", metavar="SLUG", help="use a channel's defaults and shared Post and No history")
    new.add_argument("--source", metavar="ID", help="use a source registered with the channel")
    new.set_defaults(mode=None, rights=None, vocab=None)
    batch = commands.add_parser("batch", help="clip new episodes in a folder and resume unfinished projects")
    batch.add_argument("inbox", type=Path)
    batch.add_argument("--out", type=Path, required=True, help="folder for episode projects and batch.jsonl")
    batch.add_argument("--judge", choices=("host", "claude"), default="host", help="who answers the judgment prompts")
    batch.add_argument("--watch", action="store_true", help="keep checking the inbox until Ctrl+C")
    batch.add_argument("--every", type=float, default=60, metavar="SECONDS", help="seconds between passes with --watch (default 60)")
    batch.add_argument("--limit", type=int, metavar="N", help="start at most N new episodes per pass")
    _new_settings(batch)
    batch.set_defaults(url=None, date=None, tag=None)
    go = commands.add_parser("run", help="advance the project; stops when it needs answers (host judge)")
    go.add_argument("project", type=Path)
    go.add_argument("--judge", choices=("host", "claude"), default="host",
                    help="host: write prompts for you or your agent to answer; claude: ask Claude Code's CLI")
    go.add_argument("--model", default=None, help="model for --judge claude")
    go.add_argument("--clips", type=_clips, help="only these clip numbers, e.g. 1,3")
    go.add_argument("--no-sync-check", action="store_true", help="skip the transcript sync check before scouting")
    go.add_argument("--offset", type=float, help="set the transcript shift in seconds before scouting and skip the sync check")
    commands.add_parser("status", help="progress, pending prompts, model cost and network requests").add_argument("project", type=Path)
    ans = commands.add_parser("answer", help="answer a pending prompt with JSON from a file or '-' for stdin")
    ans.add_argument("project", type=Path)
    ans.add_argument("task")
    ans.add_argument("answer", help="path to the answer, or - to read stdin")
    clip = commands.add_parser("clip", help="make a clip yourself: a stretch of the episode, or one of the scout's runners-up")
    clip.add_argument("project", type=Path)
    clip.add_argument("--start", type=_time, help="seconds or m:ss")
    clip.add_argument("--end", type=_time, help="seconds or m:ss")
    clip.add_argument("--hook", default="", help="the on-screen hook (default: the plan writes one)")
    clip.add_argument("--bench", type=int, help="make runner-up number N instead, as 'status' lists them (from 1)")
    trim = commands.add_parser("trim", help="move a clip's in and out points; the next run re-cuts it")
    trim.add_argument("project", type=Path)
    trim.add_argument("clip", help="clipNN")
    trim.add_argument("--start", type=_time, required=True)
    trim.add_argument("--end", type=_time, required=True)
    edit = commands.add_parser("edit", help="rate a clip, change its words or visuals, or re-render it")
    edit.add_argument("project", type=Path)
    edit.add_argument("clip", help="clipNN")
    action = edit.add_mutually_exclusive_group(required=True)
    action.add_argument("--rate", choices=("post", "edits", "no"), help="save a review verdict")
    action.add_argument("--hook", help="change the hook and recheck it")
    action.add_argument("--copy", nargs=2, metavar=("FIELD", "TEXT"), help="change one post copy field")
    action.add_argument("--visual", nargs=2, metavar=("REQUEST", "INDEX"), help="use a candidate from status; index starts at 0")
    action.add_argument("--word", nargs=2, metavar=("INDEX", "NEW"), help="fix a caption word; index starts at 0")
    action.add_argument("--render", metavar="SHAPE", help="re-render 9x16, 4x5, 1x1 or 16x9")
    edit.add_argument("--why", help="reason for --rate")
    edit.add_argument("--pack", help="style pack for --render (default zing)")
    redo = commands.add_parser("redo", help="forget one judgment so the next run asks again")
    redo.add_argument("project", type=Path)
    redo.add_argument("task", help="scout, or clipNN-plan / clipNN-pick / clipNN-copy / clipNN-context")
    ren = commands.add_parser("render", help="re-render one clip in a shape and style pack")
    ren.add_argument("clip", type=Path)
    ren.add_argument("--shape", default="9x16")
    ren.add_argument("--pack", default="zing")
    ren.add_argument("--4k", dest="uhd", action="store_true", help="save 4K output as the project's render setting")
    ren.add_argument("--no-parallax", dest="parallax", action="store_const", const=False, default=None,
                     help="keep photos flat for this render")
    ren.add_argument("--cutout", dest="front", action=argparse.BooleanOptionalAction, default=None,
                     help="stand the speaker in front of the pictures for this render (default: the project's setting)")
    ren.add_argument("--no-upscale", dest="sharpen", action="store_const", const=False, default=None,
                     help="render small photos at their own size for this render")
    exp = commands.add_parser("export", help="export layers and a timeline for Premiere Pro or DaVinci Resolve")
    exp.add_argument("clipdir", type=Path, help="the finished clip folder")
    exp.add_argument("--shape", default="9x16", choices=("9x16", "4x5", "1x1", "16x9"), help="frame shape (default 9x16)")
    exp.add_argument("--pack", default="zing", help="style pack (default zing)")
    exp.add_argument("--out", type=Path, help="output folder (default <clipdir>/export-<shape>)")
    commands.add_parser("review", help="rebuild the local review page").add_argument("project", type=Path)
    approval = commands.add_parser("approval", help="write a local guest approval page")
    approval.add_argument("project", type=Path)
    approval.add_argument("--out", type=Path, metavar="FILE", help="HTML file to write (default <project>/approval.html)")
    learn = commands.add_parser("learn-style", help="learn a style pack from a clip you like, then check the copy against it")
    learn.add_argument("reference", type=Path, help="a local clip whose captions and pacing you want")
    learn.add_argument("--name", required=True, help="the new pack's name, e.g. bold-yellow")
    learn.add_argument("--sample", type=Path, required=True, help="a factory clip folder to render the trial with")
    learn.add_argument("--rounds", type=int, default=3)
    learn.add_argument("--base", default="zing", help="pack to start from for anything not learned")
    serve = commands.add_parser("serve", help="open the local review dashboard for a project (127.0.0.1 only)")
    serve.add_argument("project", type=Path)
    serve.add_argument("--port", type=_port, default=8765, help="local port from 0 to 65535 (default 8765; 0 picks any free port)")
    serve.add_argument("--judge", choices=("host", "claude"), default="host", help="who answers when Run needs judgments")
    packs = commands.add_parser("packs", help="list or check style packs")
    packs.add_argument("--check", metavar="NAME", help="check pack files and font families; exit 1 on errors")
    depth = commands.add_parser("fetch-depth", help="download the depth model that moves photos (Apache-2.0, about 99 MB)")
    depth.add_argument("--yes", action="store_true", help="agree to the download")
    cut = commands.add_parser("fetch-cutout", help="download the model that lifts the speaker off their background "
                                                   "(rembg's IS-Net, Apache-2.0, about 179 MB)")
    cut.add_argument("--yes", action="store_true", help="agree to the download")
    up = commands.add_parser("fetch-upscale", help="download Real-ESRGAN, which sharpens small photos on the GPU "
                                                   "(BSD-3-Clause, about 50 MB)")
    up.add_argument("--yes", action="store_true", help="agree to the download")
    for fetch in (depth, cut, up):
        fetch.add_argument("--project", type=Path, help="apply this project's network policy and ledger")
    commands.add_parser("doctor", help="check FFmpeg, Node, the sidecar, a browser and the models")
    commands.add_parser("setup", help="install the factory sidecar with npm; needs Node.js 20 or newer")
    args = parser.parse_args(argv)
    try:
        if args.command == "setup":
            from .tools import setup
            setup(say=lambda m: print(m, flush=True))
            return 0
        if args.command == "doctor":
            from .tools import check
            print(json.dumps(check(), indent=2, ensure_ascii=False))
            return 0
        from . import pipeline
        from .judge import Judge
        if args.command == "new":
            project, settings = _channel_settings(args)
            result = pipeline.init(project, args.media, **settings)
        elif args.command == "batch":
            from .batch import run as run_batch
            result = run_batch(args.inbox, args.out, judge=args.judge, watch=args.watch, every=args.every, limit=args.limit,
                               say=lambda m: print(m, file=sys.stderr, flush=True), **_settings(args))
            if args.watch:
                return 0
        elif args.command == "run":
            pipeline.configure_sync(args.project, no_sync_check=args.no_sync_check, offset=args.offset)
            judge = Judge(args.project, args.judge, **({"model": args.model} if args.model else {}))
            result = pipeline.run(args.project, judge, only=args.clips, say=lambda m: print(m, file=sys.stderr, flush=True))
        elif args.command == "status":
            result = pipeline.status(args.project)
        elif args.command == "answer":
            text = sys.stdin.read() if args.answer == "-" else Path(args.answer).read_text(encoding="utf-8")
            result = pipeline.answer(args.project, args.task, text)
        elif args.command == "clip":
            if args.bench is not None:
                made = pipeline.make_bench(args.project, args.bench - 1)
            elif args.start is None or args.end is None:
                raise ValueError("give --start and --end, or --bench N")
            else:
                made = pipeline.add_clip(args.project, args.start, args.end, args.hook)
            result = {"clip": made, "hint": f"zing factory run {args.project} --clips {int(made[4:])}"}
        elif args.command == "trim":
            result = {"clip": pipeline.trim(args.project, args.clip, args.start, args.end),
                      "hint": f"zing factory run {args.project} --clips {int(args.clip[4:])}"}
        elif args.command == "edit":
            from . import edit
            if args.why is not None and args.rate is None:
                raise ValueError("--why needs --rate")
            if args.pack is not None and args.render is None:
                raise ValueError("--pack needs --render")
            if args.rate is not None:
                result = edit.apply(args.project, args.clip, "rate", verdict=args.rate, why=args.why or "")
            elif args.hook is not None:
                result = edit.text(args.project, args.clip, "hook", args.hook)
            elif args.copy is not None:
                result = edit.apply(args.project, args.clip, "copy", field=args.copy[0], text=args.copy[1])
            elif args.visual is not None:
                result = edit.visual(args.project, args.clip, args.visual[0], int(args.visual[1]))
            elif args.word is not None:
                result = edit.word(args.project, args.clip, int(args.word[0]), args.word[1])
            else:
                result = edit.rerender(args.project, args.clip, args.render, args.pack or "zing")
        elif args.command == "redo":
            pipeline.redo(args.project, args.task)
            result = {"task": args.task, "forgotten": True}
        elif args.command == "render":
            from . import render
            if args.uhd:
                path = args.clip.parent / "factory.json"
                cfg = pipeline._read(path)
                if cfg is None:
                    raise ValueError(f"{args.clip.parent} is not a factory project")
                pipeline._write(path, {**cfg, "uhd": True})
            render.warn_uhd(args.clip.parent, say=lambda m: print(m, file=sys.stderr, flush=True))
            result = {"rendered": str(render.render(args.clip, args.shape, args.pack, parallax=args.parallax, front=args.front,
                                                            sharpen=args.sharpen))}
        elif args.command == "review":
            from .review import build
            result = {"review": str(build(args.project))}
        elif args.command == "approval":
            from .approval import build
            result = {"approval": str(build(args.project, args.out))}
        elif args.command == "export":
            from .export import export
            result = export(args.clipdir, args.shape, args.pack, out=args.out)
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
            path = depth.fetch(consent=args.yes, project=args.project, progress=lambda m: print(m, file=sys.stderr, flush=True))
            result = {"model": str(path), "verified": True, "license": "Apache-2.0", "revision": depth.REVISION}
        elif args.command == "fetch-cutout":
            from . import cutout
            path = cutout.fetch(consent=args.yes, project=args.project, progress=lambda m: print(m, file=sys.stderr, flush=True))
            result = {"model": str(path), "verified": True, "license": "Apache-2.0", "source": cutout.URL}
        elif args.command == "fetch-upscale":
            from . import upscale
            path = upscale.fetch(consent=args.yes, project=args.project, progress=lambda m: print(m, file=sys.stderr, flush=True))
            result = {"program": str(path), "verified": True, "license": "BSD-3-Clause",
                      "source": upscale.RELEASE.format(upscale.build())}
        elif args.command == "packs":
            from .render import check_pack, theme, themes
            if args.check is not None:
                errors = check_pack(args.check)
                print(json.dumps({args.check: {"ok": not errors, "errors": errors}}, indent=2, ensure_ascii=False))
                return 1 if errors else 0
            result = {name: theme(name)["name"] for name in themes()}
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if args.command == "run" and (error := pipeline.run_error(result)):
            print(error, file=sys.stderr)
            return 1
        return 0
    except subprocess.SubprocessError as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace")
        print(f"zing factory: {detail[-500:]}", file=sys.stderr)
        return 2
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"zing factory: {exc}", file=sys.stderr)
        return 2
