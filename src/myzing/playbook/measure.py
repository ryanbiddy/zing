"""Local Study measurements, with an explicit opt-in to the Study downloader."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
import subprocess

from myzing import storage
from myzing.profile import api as profiles
from myzing.schemas import Breakdown
from myzing.study import api as study_api
from .common import SCHEMA_VERSION, library, read_json, utc_now, write_json


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
    # Never interpolate exception text: subprocess commands and stderr can carry
    # private paths, URLs and credentials. Fixed messages are bounded and safe.
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


def measure(root: Path, *, media_dir: Path | None = None, download=False, force=False) -> dict:
    data = library(root)
    media_dir = media_dir or root / "media"
    model_workspace = storage.workspace_root()
    rows = []
    summary = {"done": 0, "cached": 0, "unmeasured": 0, "failed": 0}
    for entry in data["entries"]:
        ident = entry["id"]
        target = root / "measured" / f"{ident}.json"
        failure = target.with_suffix(".failed.json")
        sidecar = target.with_suffix(".caption-geometry.json")
        work = root / "working" / ident
        row = {"id": ident, "source": "measured"}
        try:
            if failure.exists() and not force:
                row.update(status="failed", reason=read_json(failure)["reason"])
                summary["failed"] += 1
                rows.append(row)
                write_json(root / "features.json", {"schema_version": SCHEMA_VERSION, "entries": rows})
                continue
            if target.exists() and not force:
                b = Breakdown.from_dict(read_json(target))
                outcome = "cached"
            else:
                files = sorted(p for p in media_dir.glob(f"{ident}.*")
                               if p.is_file() and p.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"))
                if not files and not download:
                    row.update(status="unmeasured", reason="no local media")
                    summary["unmeasured"] += 1
                    rows.append(row)
                    write_json(root / "features.json", {"schema_version": SCHEMA_VERSION, "entries": rows})
                    continue
                # A URL reaches Study's existing ingest downloader ONLY on explicit opt-in.
                b = study_api.study(str(files[0]) if files else entry["url"], workspace=work,
                                    model_workspace=model_workspace, local_models_only=True, caption_geometry=True)
                write_json(target, b.to_dict())
                outcome = "done"
            geometries = sorted(work.rglob("caption-geometry.json")) if work.exists() else []
            if geometries and (force or not sidecar.exists()):
                write_json(sidecar, read_json(geometries[0]))
            elif force:
                sidecar.unlink(missing_ok=True)
            geometry = read_json(sidecar) if sidecar.exists() else None
            row.update(status="measured", **extract(b, geometry))
            failure.unlink(missing_ok=True)
            summary[outcome] += 1
        except Exception as exc:
            row.update(status="failed", reason=failure_reason(exc))
            write_json(failure, row)
            summary["failed"] += 1
        rows.append(row)
        write_json(root / "features.json", {"schema_version": SCHEMA_VERSION, "entries": rows})
    write_json(root / "features.json", {"schema_version": SCHEMA_VERSION, "created_at": utc_now(), "entries": rows})
    summary["entries"] = [{"id": r["id"], "status": r["status"], **({"reason": r["reason"]} if "reason" in r else {})} for r in rows]
    return summary
