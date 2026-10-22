"""Standalone Composition v2 caption adapter; no pipeline routing or grading."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Iterable

from myzing.composition import CompositionCaption
from myzing.composition.timebase import rate_fraction
from myzing.project.models import Rational
from myzing.storage import resolve_workspace
from .hyperframes_adapter import (
    HyperframesError, HyperframesPlan, validate_plan, verify_output,
    _asset, _number, _run_process,
)
from .hyperframes_publish import reserve_output, publish_pair


def captions_to_plan(
    captions: Iterable[CompositionCaption], *, width: int, height: int,
    fps: Rational, duration: float, base_dir: Path | None = None,
) -> HyperframesPlan:
    """Select HyperFrames events, preserve output times, and verify exact fonts.

    ASS events are left to the caller's other backend. Input records are copied
    and validated; confidence, timing provenance and layout safety stay in v2.
    Fractional FPS, untimed words and layout shrink requests are unsupported.
    """
    try:
        rate = rate_fraction(fps)
    except (TypeError, ValueError) as exc:
        raise HyperframesError(f"HyperFrames fps: {exc}") from exc
    if rate.denominator != 1:
        raise HyperframesError("HyperFrames supports integer fps only; fractional FPS is unsupported")
    events = []
    ids = set()
    for original in captions:
        try:
            event = CompositionCaption.from_dict(original.to_dict())
        except (AttributeError, TypeError, ValueError) as exc:
            raise HyperframesError(f"Invalid CompositionCaption: {exc}") from exc
        if event.id in ids:
            raise HyperframesError(f"Duplicate caption id: {event.id}")
        ids.add(event.id)
        if event.backend != "hyperframes":
            continue
        if not event.word_timed or not event.words:
            raise HyperframesError(f"Caption {event.id}: HyperFrames requires word_timed=true and per-word timings")
        if " ".join(event.text.split()) != " ".join(" ".join(w.text for w in event.words).split()):
            raise HyperframesError(f"Caption {event.id}: phrase text must match the ordered words")
        layout, font = event.layout, event.font
        if layout.scale != 1:
            raise HyperframesError(f"Caption {event.id}: layout.scale != 1 is unsupported; supply final font size and geometry")
        style = event.style.to_dict()
        style.pop("version")
        if style["box_color"] is None:
            style.pop("box_color")
        style.update(font=font.path, font_sha256=font.sha256)
        def box(value):
            return {k: getattr(value, k) for k in ("x", "y", "width", "height")}
        converted = {
            "start": event.start, "end": event.end, "template": event.template,
            "words": [{"text": w.text.upper() if event.all_caps else w.text,
                       "start": w.start, "end": w.end} for w in event.words],
            "style": style,
        }
        if layout.box is not None:
            converted["box"] = box(layout.box)
        else:
            converted["path"] = [{"time": k.time, "box": box(k.box)} for k in layout.path]
        events.append(converted)
    data = {"version": 1, "width": width, "height": height, "fps": int(rate),
            "duration": duration, "background": {"transparent": True}, "captions": events}
    return HyperframesPlan.from_dict(validate_plan(data, base_dir=(base_dir or Path.cwd()).resolve()))


def composite_overlay(
    video_path: Path, overlay_path: Path, output_path: Path, *, plan: HyperframesPlan,
    workspace: Path | None = None, overwrite: bool = False, timeout: float = 180,
    ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe",
) -> dict:
    """Composite a matching full-length cut with straight-alpha ProRes captions.

    Both inputs must match the plan's CFR, size, duration and decoded frame count.
    The helper preserves the cut's optional audio and performs no grade or resize.
    """
    p = plan.to_dict()
    if p["background"] != {"transparent": True}:
        raise HyperframesError("composite_overlay requires a transparent caption plan")
    output = Path(output_path).resolve()
    if output.suffix.lower() != ".mp4":
        raise HyperframesError("Composite output must use .mp4")
    _number(timeout, .01, 86400, "timeout")
    video = Path(_asset(str(video_path), "composite video", Path.cwd()))
    overlay = Path(_asset(str(overlay_path), "caption overlay", Path.cwd()))
    if output in (video, overlay):
        raise HyperframesError("Composite output must differ from both inputs")
    opaque = {**p, "background": {"color": "#000000"}}
    work = None
    try:
        with reserve_output(output, overwrite=overwrite):
            verify_output(video, opaque, ffprobe)
            verify_output(overlay, p, ffprobe)
            jobs = resolve_workspace(workspace) / "hyperframes" / "jobs"
            jobs.mkdir(parents=True, exist_ok=True)
            work = Path(tempfile.mkdtemp(prefix="hf-job-", dir=jobs))
            staged = work / "composite.mp4"
            command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
                       "-protocol_whitelist", "file,pipe,fd", "-i", str(video),
                       "-protocol_whitelist", "file,pipe,fd", "-i", str(overlay),
                       "-filter_complex", "[0:v]setpts=PTS-STARTPTS[cut];[1:v]setpts=PTS-STARTPTS[cap];[cut][cap]overlay=alpha=straight:eof_action=pass:repeatlast=0:format=auto,format=yuv420p[out]",
                       "-map", "[out]", "-map", "0:a?", "-c:v", "libx264", "-crf", "16",
                       "-c:a", "copy", "-t", str(p["duration"]), "-movflags", "+faststart", str(staged)]
            _run_process(command, env=os.environ.copy(), timeout=timeout, log=work / "composite.log")
            probe = verify_output(staged, opaque, ffprobe)
            receipt = {"version": 1, "output": str(output), "video": str(video),
                       "overlay": str(overlay), "plan": p, "probe": probe, "work_cleaned": True}
            publish_pair(staged, output, receipt, overwrite=overwrite)
            shutil.rmtree(work)
            return receipt
    except (OSError, ValueError, HyperframesError) as exc:
        raise HyperframesError(f"{exc}" + (f"; job retained at {work}" if work else "")) from exc
