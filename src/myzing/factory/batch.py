"""Clip the stable episodes in a folder, resuming each project on later passes."""
from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime
from pathlib import Path, PureWindowsPath

from . import pipeline
from .judge import Judge
from .tools import FactoryError

MEDIA = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
STABLE_SECONDS = 3


def _project(out: Path, media: Path) -> Path:
    stem = re.sub(r"[^\w.-]+", "-", media.stem).strip(".-") or "episode"
    if PureWindowsPath(stem).is_reserved():
        stem = "_" + stem
    return out / stem


def _stamp(media: Path) -> tuple[int, int]:
    st = media.stat()
    return st.st_size, st.st_mtime_ns


def _settings(media: Path, settings: dict) -> dict:
    path = media.with_suffix(".info.json")
    info = json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else {}
    if not isinstance(info, dict):
        raise FactoryError(f"{path.name} must contain a JSON object")
    date = settings.get("date")
    if date is None:
        date = datetime.strptime(info["upload_date"], "%Y%m%d").date().isoformat() if info.get("upload_date") else ""
    transcript = next((p for ext in (".srt", ".vtt", ".json") if (p := media.with_suffix(ext)).is_file()), None)
    defaults = {"name": info.get("title"), "url": info.get("webpage_url") or "", "date": date,
                "tag": info.get("uploader") or info.get("channel") or "", "transcript": transcript}
    return {**defaults, **{k: v for k, v in settings.items() if v is not None}}


def _summary(media: Path, project: Path, status: dict, error: str | None = None) -> dict:
    return {"file": str(media), "project": str(project), "state": "failed" if error else status.get("state", "new"),
            "clips": sum(bool(c.get("renders")) for c in status.get("clips", [])),
            "pending": [p["task"] for p in status.get("pending", [])],
            "cost_usd": status.get("usage", {}).get("cost_usd", 0),
            "error": error or status.get("error") or "; ".join(f"{k} {v}" for k, v in status.get("failed", {}).items()) or None}


def _episodes(inbox: Path, out: Path, judge: str, limit: int | None, settings: dict, say):
    files = []
    for media in inbox.iterdir():
        if media.suffix.lower() not in MEDIA:
            continue
        try:
            if media.is_file():
                files.append((media, _stamp(media)))
        except OSError as exc:
            yield _summary(media, _project(out, media), {}, str(exc))
    if files:
        time.sleep(STABLE_SECONDS)
    new = 0
    for media, stamp in sorted(files, key=lambda item: (item[1][1], item[0].name)):
        project, status, error = _project(out, media), {}, None
        try:
            if _stamp(media) != stamp:
                continue
            if project.resolve().parent != out:
                raise FactoryError(f"project must stay inside {out}")
            if project.exists():
                src = pipeline._read(project / "source.json", {})
                if src.get("media") and Path(src["media"]).resolve() != media.resolve():
                    raise FactoryError(f"{project} belongs to another episode")
                status = pipeline.status(project)
                if status["state"] == "done":
                    retries = pipeline._read(project / "batch.json", {}).get("retries", 0)
                    if not status.get("failed") or retries >= 2:
                        continue
                    pipeline._write(project / "batch.json", {"retries": retries + 1})
                if status["state"] == "waiting" and status.get("pending") and not any(
                        (project / "answers" / f"{p['task']}.json").is_file() for p in status["pending"]):
                    continue
            else:
                if limit is not None and new >= limit:
                    continue
                new += 1
                pipeline.init(project, media, **_settings(media, settings))
            status = pipeline.run(project, Judge(project, judge), say=say)
        except Exception as exc:
            error = str(exc) or type(exc).__name__
            try:
                status = pipeline.status(project)
            except Exception:
                pass
        yield _summary(media, project, status, error)


def _record(out: Path, result: dict) -> dict:
    result = {"at": pipeline._now(), **result}
    with (out / "batch.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")
    return result


def run(inbox: Path, out: Path, *, judge: str = "host", watch: bool = False, every: float = 60,
        limit: int | None = None, say=print, **settings) -> dict | None:
    inbox, out = Path(inbox).resolve(), Path(out).resolve()
    if not inbox.is_dir():
        raise FactoryError(f"inbox folder not found {inbox}")
    if judge not in ("host", "claude"):
        raise FactoryError("judge must be host or claude")
    if not math.isfinite(every) or every <= 0:
        raise FactoryError("--every must be a positive number of seconds")
    if limit is not None and limit < 0:
        raise FactoryError("--limit must be 0 or more")
    out.mkdir(parents=True, exist_ok=True)
    try:
        while True:
            episodes = []
            for result in _episodes(inbox, out, judge, limit, settings, say):
                if watch:
                    print(json.dumps(_record(out, result), ensure_ascii=False), flush=True)
                else:
                    episodes.append(result)
            if not watch:
                return _record(out, {"episodes": episodes})
            time.sleep(every)
    except KeyboardInterrupt:
        if not watch:
            raise
    return None
