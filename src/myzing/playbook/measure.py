"""Local Study measurements, with an explicit opt-in to the Study downloader."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
import subprocess
import time

from myzing import storage
from myzing.profile import api as profiles
from myzing.schemas import Breakdown
from myzing.study import api as study_api
from myzing.study.ingest import download_category
from .common import SCHEMA_VERSION, library, number, read_json, utc_now, warn_channels, write_json

DOWNLOAD_HINTS = {
    "download_bot_check": "YouTube blocked downloads for now. Wait, then run measure --download --retry-failed.",
    "download_rate_limited": "YouTube blocked downloads for now. Wait, then run measure --download --retry-failed.",
    "download_unavailable": "The video cannot be downloaded.",
    "ytdlp_missing": "Install yt-dlp: zing doctor.",
}


@dataclass(frozen=True)
class Feature:
    kind: str
    field: str
    unit: str
    categories: tuple = ()


FEATURES = {
    "duration": Feature("numeric", "meta.duration", "seconds"),
    "avg_shot_duration": Feature("numeric", "avg_shot_duration", "seconds"),
    "time_to_first_cut": Feature("numeric", "shots[1].start (profile helper)", "seconds"),
    "time_to_first_word": Feature("numeric", "min(words.start) (profile helper)", "seconds"),
    "time_to_first_caption": Feature("numeric", "min(captions.start) (profile helper)", "seconds"),
    "speech_ratio": Feature("numeric", "audio.speech_ratio (profile helper)", "fraction"),
    "music_present": Feature("categorical", "provenance.audio_tags; audio.has_music with confidence", "boolean", (False, True)),
    "caption_presence": Feature("categorical", "captions; OCR provenance", "boolean", (False, True)),
    "caption_words_visible_mode": Feature("numeric", "captions.words_visible (StyleProfile)", "words"),
    "caption_all_caps_share": Feature("numeric", "captions.all_caps (StyleProfile)", "fraction of events"),
    "caption_position_mode": Feature("categorical", "captions.position", "position", ("top", "center", "lower", "bottom")),
    "words_per_second_first_3s": Feature("numeric", "words.start in [0, min(3, duration))", "words/second"),
    "source_aspect": Feature("numeric", "meta.width / meta.height", "width/height"),
    "face_presence_share": Feature("numeric", "caption-geometry frames.face_boxes", "fraction of observed samples"),
    "largest_face_area_share": Feature("numeric", "caption-geometry frames.face_boxes (normalized edges)", "mean largest face/frame area"),
}


def music_present(b: Breakdown) -> bool | None:
    tags = b.provenance.get("audio_tags", {})
    if tags.get("status") == "measured":
        from myzing.audio.tagging import WEAK_THRESHOLD
        return bool(tags.get("music_under_speech")) or any(
            row.get("music", 0) >= WEAK_THRESHOLD for row in tags.get("windows", []))
    return b.audio.has_music if b.audio.music_confidence > 0 else None


def failure_reason(exc: Exception) -> str:
    pending, seen = [exc], set()
    while pending:
        error = pending.pop()
        if error is None or id(error) in seen:
            continue
        seen.add(id(error))
        category = download_category(str(error))
        if category:
            return f"{type(exc).__name__[:64]}: {category}"  # never persist exception text
        pending.extend((error.__context__, error.__cause__))
    message = "tool timed out" if isinstance(exc, subprocess.TimeoutExpired) else "measurement failed; details omitted"
    return f"{type(exc).__name__[:64]}: {message}"


def extract(b: Breakdown, geometry: dict | None = None) -> dict:
    # Reuse the existing per-source profile definitions, including missing-data rules.
    p = profiles._aggregate("playbook", [("source", b)], genre="podcast", platform="youtube")
    duration = b.meta.duration if b.meta.duration > 0 else None
    ocr_ran = bool(b.captions) or "ocr_backend" in b.provenance or bool((geometry or {}).get("frames"))
    ocr_failed = any("ocr" in w.lower() and any(x in w.lower() for x in ("skipped", "failed", "no confidence")) for w in b.warnings)
    if geometry is not None:
        ocr_failed = ocr_failed or any(f.get("status") == "ocr_error" for f in geometry.get("frames", []))
        ocr_failed = ocr_failed or any("not measured" in w.lower() or "incomplete" in w.lower() for w in geometry.get("warnings", []))
    asr_ran = bool(b.words) or "whisper_model" in b.provenance
    values = {
        "duration": duration,
        "avg_shot_duration": p.shot_duration.median if p.shot_duration.n else None,
        "time_to_first_cut": profiles._first_cut(b),
        "time_to_first_word": profiles._first_word(b),
        "time_to_first_caption": profiles._first_caption(b),
        "speech_ratio": profiles._speech_ratio(b),
        "music_present": music_present(b),
        "caption_presence": bool(b.captions) if ocr_ran and not ocr_failed else None,
        "caption_words_visible_mode": p.caption_words_visible_mode if b.captions else None,
        "caption_all_caps_share": p.caption_all_caps_rate if b.captions else None,
        "caption_position_mode": Counter(c.position for c in b.captions).most_common(1)[0][0] if b.captions else None,
        "words_per_second_first_3s": sum(0 <= w.start < min(3, duration) for w in b.words) / min(3, duration) if duration and asr_ran else None,
        "source_aspect": b.meta.width / b.meta.height if b.meta.width > 0 and b.meta.height > 0 else None,
        "face_presence_share": None, "largest_face_area_share": None,
    }
    frames = [f for f in (geometry or {}).get("frames", [])
              if f.get("face_boxes") is not None and f.get("width", 0) > 0 and f.get("height", 0) > 0]
    if frames:
        values["face_presence_share"] = mean(bool(f["face_boxes"]) for f in frames)
        values["largest_face_area_share"] = mean(
            max((max(0, x2-x1) * max(0, y2-y1)
                 for x1, y1, x2, y2 in f["face_boxes"]), default=0) for f in frames)
    return values


def measure(root: Path, *, media_dir: Path | None = None, download=False, force=False,
            retry_failed=False, max_blocks=3, gap=3, sleep=None) -> dict:
    if force and retry_failed:
        raise ValueError("use one of --force or --retry-failed")
    if type(max_blocks) is not int or max_blocks < 1:
        raise ValueError("--max-blocks must be an integer of at least 1")
    if not number(gap) or gap < 0:
        raise ValueError("--gap must be a finite number of at least 0 seconds")
    data = library(root)
    warn_channels(data)
    media_dir = media_dir or root / "media"
    model_workspace = storage.workspace_root()
    sleep = sleep or time.sleep
    blocks, attempted = 0, False
    rows = []
    summary = {"done": 0, "cached": 0, "unmeasured": 0, "failed": 0, "paused": 0}
    for entry in data["entries"]:
        ident = entry["id"]
        target = root / "measured" / f"{ident}.json"
        failure = target.with_suffix(".failed.json")
        sidecar = target.with_suffix(".caption-geometry.json")
        work = root / "working" / ident
        row = {"id": ident, "source": "measured"}
        try:
            retry = retry_failed and failure.exists()
            if failure.exists() and not (force or retry):
                row.update(status="failed", reason=read_json(failure)["reason"])
                category = row["reason"].partition(": ")[2]
                if category in DOWNLOAD_HINTS:
                    row["hint"] = DOWNLOAD_HINTS[category]
                summary["failed"] += 1
                rows.append(row)
                write_json(root / "features.json", {"schema_version": SCHEMA_VERSION, "entries": rows})
                continue
            if target.exists() and not (force or retry):
                b = Breakdown.from_dict(read_json(target))
                outcome = "cached"
            else:
                files = sorted(p for p in media_dir.glob(f"{ident}.*")
                               if p.is_file() and p.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"))
                reason = None
                if retry_failed and not retry:
                    reason = "no failure record"
                elif not files and not download:
                    reason = "no local media"
                elif not files and summary.get("stopped"):
                    reason = "download paused after YouTube blocks"
                    summary["paused"] += 1
                if reason:
                    row.update(status="unmeasured", reason=reason)
                    summary["unmeasured"] += 1
                    rows.append(row)
                    write_json(root / "features.json", {"schema_version": SCHEMA_VERSION, "entries": rows})
                    continue
                if not files:
                    if attempted and gap:
                        sleep(gap)
                    attempted = True
                if retry:
                    failure.unlink()
                b = study_api.study(str(files[0]) if files else entry["url"], workspace=work,
                                    model_workspace=model_workspace, local_models_only=True, caption_geometry=True)
                write_json(target, b.to_dict())
                outcome = "done"
            geometries = sorted(work.rglob("caption-geometry.json")) if work.exists() else []
            if geometries and (force or retry or (not retry_failed and not sidecar.exists())):
                write_json(sidecar, read_json(geometries[0]))
            elif force or retry:
                sidecar.unlink(missing_ok=True)
            geometry = read_json(sidecar) if sidecar.exists() else None
            row.update(status="measured", **extract(b, geometry))
            failure.unlink(missing_ok=True)
            summary[outcome] += 1
            blocks = 0
        except Exception as exc:
            row.update(status="failed", reason=failure_reason(exc))
            category = row["reason"].partition(": ")[2]
            if category in DOWNLOAD_HINTS:
                row["hint"] = DOWNLOAD_HINTS[category]
            write_json(failure, row)
            summary["failed"] += 1
            blocks = blocks + 1 if category in ("download_bot_check", "download_rate_limited") else 0
            if blocks >= max_blocks and not summary.get("stopped"):
                summary["stopped"] = category
        rows.append(row)
        write_json(root / "features.json", {"schema_version": SCHEMA_VERSION, "entries": rows})
    write_json(root / "features.json", {"schema_version": SCHEMA_VERSION, "created_at": utc_now(), "entries": rows})
    summary["entries"] = [{"id": r["id"], "status": r["status"],
                           **{key: r[key] for key in ("reason", "hint") if key in r}} for r in rows]
    return summary
