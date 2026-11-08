"""One bounded pass over local channels."""
from __future__ import annotations

import json
import math
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from myzing.factory import pipeline
from myzing.factory.judge import Judge
from myzing.model_fetch import _try_lock, _unlock
from myzing.playbook.common import append_jsonl, parse_time

from . import brief, kit, publish, queue, registry, watch

STALE = 3 * 3600


@contextmanager
def lock(now: datetime):
    root = registry.home()
    root.mkdir(parents=True, exist_ok=True)
    path = root / "tick.lock"
    with (root / ".tick.guard").open("a+b") as guard:
        if not _try_lock(guard):
            yield False
            return
        owned = False
        try:
            if path.exists():
                try:
                    started = parse_time(json.loads(path.read_text(encoding="utf-8"))["started"]).timestamp()
                except (ValueError, KeyError, TypeError):
                    started = path.stat().st_mtime
                if now.timestamp() - started < STALE:
                    yield False
                    return
                path.unlink()
            with path.open("x", encoding="utf-8") as stream:
                json.dump({"pid": os.getpid(), "started": now.isoformat()}, stream)
            owned = True
            yield True
        finally:
            if owned:
                path.unlink(missing_ok=True)
            _unlock(guard)


def channels(slugs: list[str] | None = None) -> list[str]:
    return list(dict.fromkeys(slugs)) if slugs is not None else [p.parent.name for p in sorted(registry.home().glob("*/channel.json"))]


def pending(project: Path) -> list[dict]:
    return [{"project": str(project), **row} for row in Judge(project).pending()
            if not (project / "answers" / f"{row['task']}.json").is_file()]


def _advance(slug: str, channel: dict, row: dict, runner, stop, say, now) -> None:
    chosen, retry = None, None
    for file in sorted((registry.directory(slug) / "projects").glob("*/factory.json")):
        if stop():
            return
        project = file.parent
        try:
            prompts = pending(project)
            row["pending"].extend(prompts)
            status = pipeline._read(project / "status.json", {})
            if status.get("state") == "done" and not status.get("failed"):
                continue
            failed = status.get("state") == "failed" or bool(status.get("failed"))
            attempts = pipeline._read(project / "tick_attempts.json", {}).get("attempts", 0)
            if failed and attempts >= 2:
                row.setdefault("notes", []).append(f"{project.name} skipped after two retries.")
                continue
            cfg = pipeline._read(file)
            src = registry.source(channel, cfg["source"]) if cfg.get("source") else None
            if cfg.get("rights") not in ("own", "permission", "licensed") or (src and registry.effective_rights(src, now) == "unknown"):
                row["blocked"][project.name] = ["Source rights need review."]
                continue
            if chosen is None and not (prompts and channel["judge"] == "host"):
                chosen = project
                retry = attempts + 1 if failed else None
        except (OSError, ValueError, KeyError, TypeError) as exc:
            row["errors"].append(f"{project.name} {exc}")
    if chosen is None or stop():
        return
    if retry is not None:
        pipeline._write(chosen / "tick_attempts.json", {"attempts": retry})
    try:
        result = runner(chosen, Judge(chosen, channel["judge"]), say=say, stop=stop)
    except Exception as exc:
        if not stop():
            row["errors"].append(f"{chosen.name} {str(exc) or type(exc).__name__}")
        return
    row["advanced"] += 1
    row["pending"] = [p for p in row["pending"] if p["project"] != str(chosen)]
    row["pending"].extend({"project": str(chosen), **p} for p in result.get("pending", []))
    row["errors"].extend(f"{chosen.name}/{clip} {error}" for clip, error in result.get("failed", {}).items())
    if result.get("error"):
        row["errors"].append(f"{chosen.name} {result['error']}")


def run(slugs: list[str] | None = None, *, max_minutes: float = 50, runner=None, watch_fn=None, say=print,
        now: datetime | None = None) -> dict:
    if isinstance(max_minutes, bool) or not math.isfinite(max_minutes) or max_minutes <= 0:
        raise registry.ChannelError("--max-minutes must be a positive number")
    clock, now = now, now or datetime.now(timezone.utc)
    deadline = time.monotonic() + max_minutes * 60
    results = {}
    with lock(now) as acquired:
        if not acquired:
            return {"message": "another tick is running", "channels": {}, "exit_code": 0}
        for slug in channels(slugs):
            root = None
            if time.monotonic() >= deadline:
                break
            began = time.monotonic()
            row = {"at": now.isoformat(), "found": 0, "started": 0, "advanced": 0, "queued": 0,
                   "kits": 0, "blocked": {}, "pending": [], "errors": [], "seconds": 0}

            def stopped():
                paused = (registry.home() / "PAUSE").exists() or root is not None and (root / "PAUSE").exists()
                reason = "paused" if paused else "out of time" if time.monotonic() >= deadline else None
                if reason:
                    row["stopped"] = reason
                return bool(reason)

            try:
                root = registry.directory(slug)
                if not stopped():
                    channel = registry.load(slug)
                    found = (watch_fn or watch.run)(slug, now=now, stop=stopped)
                    row.update(found=found["found"], started=found["started"])
                    row["errors"].extend(found.get("errors", []))
                    if not stopped():
                        try:
                            if brief.due(slug, now):
                                made = brief.make(slug, now=now, stop=stopped)
                                row["brief"] = len(made["items"])
                                row["errors"].extend(made.get("errors", []))
                        except Exception as exc:
                            if not (stopped() and isinstance(exc, registry.ChannelError)):
                                row["errors"].append(f"brief {str(exc) or type(exc).__name__}")
                    if not stopped():
                        _advance(slug, channel, row, runner or pipeline.run, stopped, say, now)
                    if not stopped():
                        queued = queue.build(slug, clock or datetime.now(timezone.utc), stop=stopped)
                        row["queued"] = queued["added"]
                        row["blocked"].update(queued["blocked"])
                    if not stopped():
                        made = kit.kit(slug, now=clock or datetime.now(timezone.utc), stop=stopped)
                        row["kits"] = made["made"]
                        row["blocked"].update(made["blocked"])
                    if not stopped() and channel["handles"].get("youtube"):
                        from .outcomes import track
                        row["tracked"] = track(slug, now=clock or datetime.now(timezone.utc))["matched"]
                    if not stopped() and channel["publish"]["youtube"] != "off":
                        uploaded = publish.upload(slug, now=clock or datetime.now(timezone.utc), stop=stopped)
                        row["uploaded"] = uploaded["uploaded"]
                        row["blocked"].update(uploaded["blocked"])
                        if uploaded["stopped"]:
                            row["errors"].append(uploaded["stopped"])
                    if not stopped() and channel.get("youtube") and publish.analytics_due(slug, clock):
                        row["analytics"] = publish.analytics(slug, now=clock, stop=stopped)["matched"]
            except Exception as exc:
                stopped()
                if not (row.get("stopped") == "paused" and isinstance(exc, registry.ChannelError)):
                    row["errors"].append(str(exc) or type(exc).__name__)
            row["seconds"] = round(time.monotonic() - began, 3)
            try:
                if root is not None:
                    append_jsonl(root / "ticks.jsonl", [row])
            except OSError as exc:
                row["errors"].append(f"Could not write ticks.jsonl. {exc}")
            results[slug] = row
    return {"channels": results, "exit_code": int(bool(results) and all(r["errors"] for r in results.values()))}
