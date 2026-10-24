"""Public local planning API, shared by CLI, match and Studio."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import analysis
from .models import ScreenPlan, read_cursor, number
from .planner import protected_idle, zoom_candidates


def plan_screen(video, *, cursor=None, cursor_offset=0., sync_creation_time=False,
                words=None, idle_speed=4., max_zoom=1.8, ui_text_px=24.,
                caption_preset="clean", click_highlights=False, ffmpeg="ffmpeg"):
    from myzing.project.probe import probe_file
    from myzing.project.api import hash_file
    from myzing.render.framing import display_dimensions
    path = Path(video).expanduser().resolve()
    if "://" in str(video) or str(video).startswith(("//", "\\\\")) or not path.is_file():
        raise ValueError("Supply an existing local video file.")
    probe = probe_file(path)
    if not probe.width or not probe.height or not probe.duration:
        raise ValueError("Screen planning needs a video with known dimensions and duration.")
    number(probe.duration, "screen duration", .01, 3600)
    if set(probe.flags) & {"hdr", "log"}:
        raise ValueError("Screen planning supports SDR; convert this HDR/LOG recording explicitly first.")
    stream = next(s for s in probe.streams if s.get("codec_type") == "video")
    width, height = display_dimensions(stream)
    events, sync, warnings = [], {}, []
    if cursor:
        header, _, stopped = read_cursor(cursor)
        if sync_creation_time:
            created = stream.get("tags", {}).get("creation_time") or probe.format.get("tags", {}).get("creation_time")
            if not created:
                raise ValueError("Video has no creation_time; use the GO marker and --cursor-offset instead.")
            start = datetime.fromisoformat(header["wall_time"].replace("Z", "+00:00"))
            video_start = datetime.fromisoformat(created.replace("Z", "+00:00"))
            if start.tzinfo is None or video_start.tzinfo is None:
                raise ValueError("Creation-time sync requires timezone-aware timestamps.")
            cursor_offset = (start-video_start).total_seconds()
            warnings.append("Creation time can be mux/finalization time; verify alignment against the visible action.")
        _, events, _ = read_cursor(cursor, offset=cursor_offset)
        events = [e for e in events if 0 <= e["t"] <= probe.duration]
        if not any(e["type"] == "cursor" for e in events):
            raise ValueError("Cursor log has no positions inside this video; correct --cursor-offset or capture region.")
        if not stopped:
            warnings.append("Cursor log has no stop marker; using the complete samples before interruption.")
        sync = {"cursor_file": str(Path(cursor).resolve()), "cursor_sha256": hash_file(Path(cursor)),
                "offset_seconds": cursor_offset, "method": "creation-time" if sync_creation_time else "GO/manual-offset",
                "wall_time": header.get("wall_time"), "bounds": header.get("bounds")}
    elif sync_creation_time or cursor_offset:
        raise ValueError("Cursor alignment options require --cursor.")
    else:
        warnings.append("No cursor telemetry: frame-difference UI activity targets have lower confidence (0.45); cursor and text identity are unknown.")
    plan = ScreenPlan(str(path), hash_file(path), width, height, probe.duration,
                      words=list(words or []), sync=sync, warnings=warnings, idle_speed=idle_speed,
                      max_zoom=max_zoom, ui_text_px=ui_text_px, caption_preset=caption_preset,
                      click_highlights=click_highlights)
    # Validate options and timed words before decoding anything.
    ScreenPlan.from_dict(plan.to_dict())
    frozen = analysis.freezes(path, plan.duration, ffmpeg)
    if probe.has_audio and not plan.words:
        # Pixel stillness is not speech silence. Unknown narration must not be
        # accelerated. Users can supply timed words or choose --idle-speed 1.
        frozen = []
        plan.warnings.append("Source has audio but no supplied word timings; idle speed-up disabled to preserve possible narration.")
    changes = analysis.activity(path, plan.duration, ffmpeg)
    # Global freeze noise thresholds can miss a tiny but meaningful UI update.
    # Local tile changes therefore veto compression, even with cursor telemetry.
    protection = [*events, *[{**e,"type":"activity"} for e in changes]]
    plan.idle = protected_idle(frozen, protection, plan.words, plan.duration)
    plan.zooms = zoom_candidates(events, [] if cursor else changes, plan.idle, plan.duration)
    from .regions import attach_regions
    attach_regions(path, plan.zooms, plan.duration, ffmpeg=ffmpeg)
    plan.clicks = [e for e in events if e["type"] == "click"]
    if not plan.zooms:
        plan.warnings.append("No supported focus candidates; camera holds the initial framing.")
    return ScreenPlan.from_dict(plan.to_dict())


def save_plan(plan, out):
    path = Path(out).expanduser().resolve()
    protected = {Path(plan.source).resolve()}
    if plan.sync.get("cursor_file"):
        protected.add(Path(plan.sync["cursor_file"]).resolve())
    if path in protected:
        raise ValueError("Plan output would overwrite a source; choose a different --out.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan.to_dict(), indent=2, allow_nan=False)+"\n", encoding="utf-8")
    return path


def run_folder(clips, out, *, cursor=None, aspects=("16:9",), progress=print, speech_model=None, music=None, **options):
    """Preserve each recording's continuity; render one demo per local source."""
    from myzing.studio.evidence import media_files
    from .render import render_screen
    root = Path(out).resolve()
    files = media_files(clips, root)
    if not files:
        raise ValueError("No supported local screen recordings in the clips folder.")
    if cursor and len(files) != 1:
        raise ValueError("One cursor session aligns to one video. Use a folder containing only that recording, or omit the log.")
    if options.get("words") and len(files) != 1:
        raise ValueError("Supplied word timings align to one recording; use a folder containing only that video.")
    results = []
    for i, source in enumerate(files):
        progress(f"Plan screen demo: {source.name}")
        local_options = dict(options)
        if speech_model and speech_model != "skip":
            from myzing.study.api import study
            from myzing import storage
            measured = study(str(source), workspace=root, raw_mode=True, local_models_only=True,
                             model_workspace=storage.resolve_workspace(), speech_model=speech_model)
            local_options["words"] = [{"text":w.text,"start":w.start,"end":w.end} for w in measured.words]
        plan = plan_screen(source, cursor=cursor, **local_options)
        if not plan.words and plan.caption_preset != "none":
            plan.warnings.append("No supplied/transcribed word timings; no spoken captions were added.")
        if isinstance(music,list):
            plan.warnings.append("Screen-demo mode preserves source audio; supplied music beds are not mixed in this version.")
        folder = root / f"screen-{i+1}-{source.stem}"
        plan_path = save_plan(plan, folder / "plan.json")
        deliveries = {}
        for aspect in aspects:
            progress(f"Render smooth screen camera: {aspect}")
            deliveries[aspect] = render_screen(plan, folder / (aspect.replace(":", "x")+".mp4"), aspect=aspect)
        results.append({"plan": str(plan_path), "deliveries": deliveries, "warnings": plan.warnings})
    return {"status": "ready", "screens": results,
            "summary": f"Rendered {len(results)} continuous screen demos.",
            "warnings": ["Screen-demo mode follows UI activity. Reference hard-cut pacing is not applied."]}
