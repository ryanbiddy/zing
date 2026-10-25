"""CLI entry points for screen plans and folder deliveries."""

import argparse
import json
import sys
import subprocess
from pathlib import Path

from myzing import storage
from .api import plan_screen, save_plan, run_folder


def options(parser):
    parser.add_argument("--cursor", type=Path, help="optional record-cursor JSONL; otherwise use lower-confidence UI activity")
    parser.add_argument("--cursor-offset", type=float, default=0., help="video time in seconds of telemetry GO (may be negative)")
    parser.add_argument("--sync-creation-time", action="store_true", help="align UTC log start with video creation_time; verify recorder metadata")
    parser.add_argument("--idle-speed", type=float, default=4.)
    parser.add_argument("--max-zoom", type=float, default=1.8, help="preferred context zoom; phone targets may enlarge further, up to 2.5 output pixels per source pixel")
    parser.add_argument("--ui-text-px", type=float, default=24., help="source UI text em-size estimate; used with the DOGFOOD1 phone floor")
    parser.add_argument("--caption-preset", choices=["clean","punch","box","none"],default="clean")
    parser.add_argument("--click-highlights",action="store_true")
    parser.add_argument("--words",type=Path,help="optional JSON list of source-timed {text,start,end} words, explicitly supplied, never from keys")


def values(a):
    value = {k:getattr(a,k) for k in ("cursor","cursor_offset","sync_creation_time","idle_speed","max_zoom",
                                     "ui_text_px","caption_preset","click_highlights")}
    value["words"] = json.loads(a.words.read_text(encoding="utf-8")) if a.words else None
    return value


def run(argv):
    p=argparse.ArgumentParser(prog="zing plan screen",description="Plan continuous screen demos with smooth zoom/pan and idle speed-up.")
    p.add_argument("video",type=Path)
    p.add_argument("--out",type=Path)
    options(p)
    a=p.parse_args(argv)
    try:
        plan=plan_screen(a.video,**values(a))
        target=a.out or storage.resolve_workspace()/"screen"/(a.video.stem+"-screen.json")
        print(save_plan(plan,target))
        for note in plan.warnings:
            print(note,file=sys.stderr)
    except (ValueError,OSError,RuntimeError,TypeError,KeyError,subprocess.SubprocessError) as exc:
        print(f"zing plan screen: {exc}",file=sys.stderr)
        return 1
    return 0


def match(argv):
    p=argparse.ArgumentParser(prog="zing match screen",description="Make continuous screen demos from local recordings.")
    p.add_argument("--clips",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--aspect",default="16:9",help="all or comma-separated 16:9,1:1,9:16")
    options(p)
    a=p.parse_args(argv)
    try:
        aspects=["16:9","1:1","9:16"] if a.aspect=="all" else a.aspect.split(",")
        from .planner import dimensions
        for aspect in aspects:
            dimensions(aspect)
        result=run_folder(a.clips,a.out,aspects=aspects,progress=lambda s:print(s,file=sys.stderr),**values(a))
        print(json.dumps(result,indent=2))
    except (ValueError,OSError,RuntimeError,TypeError,KeyError,subprocess.SubprocessError) as exc:
        print(f"zing match screen: {exc}",file=sys.stderr)
        return 1
    return 0


def render_payload(payload,args):
    from .models import ScreenPlan
    from .planner import dimensions
    from .render import render_screen
    plan=ScreenPlan.from_dict(payload)
    if any((args.voiceover_script,args.otio,args.framing,args.picture_crop,args.caption_options,args.target_mb,args.video_bitrate_kbps,args.max_upscale)):
        raise ValueError("Screen plans use their saved camera/caption options; use zing plan screen to change them. Voiceover/OTIO/bitrate overrides are not supported here.")
    if args.caption_mode:
        if args.caption_mode not in {"clean","punch","box","none"}:
            raise ValueError("Screen captions use clean, punch, box or none.")
        plan.caption_preset=args.caption_mode
    aspects=["16:9","1:1","9:16"] if args.aspect=="all" else (args.aspect or "16:9").split(",")
    short=args.short_side or 720
    for aspect in aspects:
        dimensions(aspect,short)
    output=(args.output or args.edl.with_suffix(".mp4")).resolve()
    if output==args.edl.resolve():
        raise ValueError("Render output would replace the plan JSON.")
    deliveries={}
    for aspect in aspects:
        dest=output.with_stem(output.stem+"-"+aspect.replace(":","x")) if len(aspects)>1 else output
        work=args.keep_work/aspect.replace(":","x") if args.keep_work else None
        deliveries[aspect]=render_screen(plan,dest,aspect=aspect,short_side=short,ffmpeg=args.ffmpeg,ffprobe=args.ffprobe,work_dir=work)
    return {"kind":"screen-demo","deliveries":deliveries}
