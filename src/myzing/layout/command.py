"""CLI for explicit model fetching and standalone caption layout plans."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from myzing.storage import workspace_root
from myzing.study.proc import MediaError

from .chooser import choose_layout
from .debug import read_image, write_contact_sheet
from .detector import MODEL_LICENSE, MODEL_SHA256, MODEL_URL, LayoutError, YuNetDetector, fetch_model
from .masks import platform_masks
from .media import probe_duration, sample_frames
from .tracking import build_tracks
from .types import CaptionEvent, FrameDetections, Mask, number


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="zing layout")
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch-model", help="explicitly download and verify the pinned MIT YuNet model")
    fetch.add_argument("--workspace", type=Path, help="Zing workspace (default: ZING_HOME or ~/.zing)")
    captions = commands.add_parser("captions", help="plan boxes and write a debug contact sheet")
    captions.add_argument("--video", type=Path, required=True)
    captions.add_argument("--events", type=Path, required=True)
    captions.add_argument("--platform", choices=("tiktok", "reels", "shorts", "none", "custom"), default="none")
    captions.add_argument("--masks", type=Path, help="JSON array of named normalized masks; requires --platform custom")
    captions.add_argument("--out", type=Path, required=True)
    captions.add_argument("--workspace", type=Path)
    captions.add_argument("--fetch-model", action="store_true", help="explicitly allow the pinned model download")
    captions.add_argument("--sample-rate", type=float, default=2, help="maximum sample fps, 0.1 through 8 (default 2)")
    captions.add_argument("--face-margin", type=float, default=0.04, help="padding per side in frame units (default .04)")
    captions.add_argument("--max-gap", type=float, default=1.5, help="seconds to link/hold missing detections")
    captions.add_argument("--score-threshold", type=float, default=0.6)
    return parser


def read_events(path: Path) -> list[CaptionEvent]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        if type(data.get("version", 1)) is not int or data.get("version", 1) != 1:
            raise ValueError("unsupported caption events version")
        data = data.get("events")
    if not isinstance(data, list) or not data:
        raise ValueError("events JSON must be a nonempty array or a version 1 object with an events array")
    events = [CaptionEvent.from_dict(item) for item in data]
    if len({e.id for e in events}) != len(events):
        raise ValueError("caption event ids must be unique")
    return events


def _captions(args) -> dict:
    video, event_path, output = (p.expanduser().resolve() for p in (args.video, args.events, args.out))
    contact = output.with_suffix(".contact.png")
    inputs = {video, event_path}
    if args.masks:
        inputs.add(args.masks.expanduser().resolve())
    if output in inputs or contact in inputs or output == contact:
        raise ValueError("plan/contact sheet paths must differ from each other and all inputs")
    number(args.sample_rate, "sample_rate", 0.1, 8)
    number(args.face_margin, "face_margin", 0, 0.5)
    number(args.max_gap, "max_gap", 1e-6, 10)
    events = read_events(event_path)
    custom = None
    if args.masks:
        data = json.loads(args.masks.read_text(encoding="utf-8-sig"))
        if not isinstance(data, list):
            raise ValueError("custom masks JSON must be an array")
        custom = [Mask.from_dict(item) for item in data]
    masks = platform_masks(args.platform, custom)
    duration = probe_duration(video)
    if any(e.end > duration for e in events):
        raise ValueError(f"caption event extends beyond video duration {duration:.6f}s; correct event timing")
    if duration * args.sample_rate > 600:
        raise ValueError("sampling would exceed 600 frames; trim video or lower --sample-rate")
    workspace = (args.workspace or workspace_root()).expanduser().resolve()
    detector = YuNetDetector(workspace, download=args.fetch_model, score_threshold=args.score_threshold)
    work = workspace / "layout"
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="samples-", dir=work) as temporary:
        samples = sample_frames(video, Path(temporary), duration=duration, sample_rate=args.sample_rate)
        detections = [FrameDetections(time, detector.detect(read_image(path))) for time, path in samples]
        tracks = build_tracks(detections, duration=duration, margin=args.face_margin, max_gap=args.max_gap)
        plan = choose_layout(events, tracks, masks, platform=args.platform)
        plan.warnings.append("sampled_detection: faces may be missed or move nonlinearly between samples; "
                             "safe means clear of the supplied interpolated tracks and UI masks only")
        if not tracks:
            plan.warnings.append("no_faces_detected: this is not evidence that the footage contains no faces")
        if args.platform not in ("none", "custom"):
            plan.warnings.append("approximate_platform_masks: tune against the target device and publishing preview")
        for track in tracks:
            plan.warnings.extend(f"{track.id}: {warning}" for warning in track.warnings)
        if any(a.end > b.start for a, b in zip(sorted(events, key=lambda e: e.start),
                                              sorted(events, key=lambda e: e.start)[1:])):
            plan.warnings.append("concurrent_captions: caption-to-caption collision avoidance is outside PF")
        with video.open("rb") as stream:
            digest = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        plan.provenance.update({
            "video": str(video), "video_sha256": digest.hexdigest(), "duration": duration,
            "coordinates": "normalized display frame; x/y top-left; width/height; seconds from first video frame",
            "model_url": MODEL_URL, "model_sha256": MODEL_SHA256, "model_license": MODEL_LICENSE,
            "opencv_version": detector.cv2.__version__, "backend": "OpenCV DNN CPU",
            "sample_rate_limit": args.sample_rate, "sample_times": [t for t, _ in samples],
            "face_margin": args.face_margin, "max_gap": args.max_gap, "score_threshold": args.score_threshold,
            "detections": [f.to_dict() for f in detections], "tracks_are_padded": True,
            "contact_sheet": str(contact),
        })
        # Finish both artifacts in scratch before publishing the pair.
        staged_contact = write_contact_sheet(samples, detections, plan, Path(temporary) / "contact.png")
        encoded_plan = json.dumps(plan.to_dict(), indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        output.parent.mkdir(parents=True, exist_ok=True)
        contact.write_bytes(staged_contact.read_bytes())
        output.write_text(encoded_plan, encoding="utf-8")
    warnings = plan.warnings + [f"{e.id}: {w}" for e in plan.events for w in e.warnings]
    return {"plan": str(output), "contact_sheet": str(contact), "events": len(plan.events),
            "tracks": len(tracks), "unsafe_events": [e.id for e in plan.events if not e.overlap.safe],
            "warnings": warnings}


def run(argv: list[str]) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        if args.command == "fetch-model":
            path = fetch_model(args.workspace)
            print(json.dumps({"model": str(path), "sha256": MODEL_SHA256, "url": MODEL_URL,
                              "license": MODEL_LICENSE, "verified": True}, indent=2))
        else:
            print(json.dumps(_captions(args), indent=2))
        return 0
    except SystemExit as exc:
        return int(exc.code or 0)
    except (LayoutError, MediaError, OSError, ValueError, TypeError, subprocess.SubprocessError) as exc:
        print(f"zing layout: {exc}", file=sys.stderr)
        return 2
