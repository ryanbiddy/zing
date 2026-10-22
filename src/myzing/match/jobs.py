"""Supervision shared by the terminal and MCP background workers."""

from __future__ import annotations

import json
import os
import sys
from contextlib import nullcontext
from pathlib import Path
from uuid import uuid4

from .process import run_lock, run_owned
from .state import interrupted, read, write


def worker_command():
    return [sys.executable, "-m", "myzing.match.worker"]


def execute(options, *, progress=None, cancel=None, locked=False):
    options = {**options, "run_id": uuid4().hex}
    root = Path(options["out"]).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    with nullcontext() if locked else run_lock(root):
        log = root / "logs" / "worker.log"
        log.parent.mkdir(exist_ok=True)
        pid = None

        def started(value):
            nonlocal pid
            pid = value

        with log.open("a", encoding="utf-8") as stream:
            def line(text):
                stream.write(text + "\n")
                stream.flush()
                if progress:
                    progress(text)
            try:
                from myzing import storage
                code = run_owned(worker_command(), json.dumps(options),
                                 progress=line, cancel=cancel, on_started=started,
                                 env={**os.environ, "ZING_HOME": str(storage.resolve_workspace()),
                                      "PYTHONIOENCODING": "utf-8", "HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1"})
                if code not in (0, 1) or not (root / "comparison.json").exists():
                    raise RuntimeError(f"match worker exited {code}; log: {log}")
                result = read(root / "comparison.json")
                # A crash must not resurrect an older successful comparison.
                state = read(root / "match-state.json")
                if state["status"] == "running" or result.get("run_id") != options["run_id"]:
                    raise RuntimeError(f"match worker interrupted before publishing; log: {log}")
                return result
            except BaseException as exc:
                status = "cancelled" if isinstance(exc, KeyboardInterrupt) else "failed"
                interrupted(root, status)
                stream.write(f"{status}: {exc}\n")
                result = {"version": 1, "project": str(root), "status": status, "ready": 0, "requested": 3,
                          "summary": "0 of 3 ready (run interrupted; resume to validate completed drafts)",
                          "drafts": {}, "shortages": [], "warnings": [],
                          "failures": [{"step": "worker", "error": str(exc), "log": str(log)}]}
                write(root / "comparison.json", result)
                from .evidence import markdown
                (root / "comparison.md").write_text(markdown(result), encoding="utf-8")
                if isinstance(exc, KeyboardInterrupt):
                    return result
                raise
            finally:
                # Project producers use short exclusive locks. Kill may bypass
                # their finally block; release only this now-reaped worker's locks.
                for folder in (root, root / "director"):
                    lock = folder / ".project.lock"
                    try:
                        if pid is not None and read(lock).get("pid") == pid:
                            lock.unlink()
                    except (FileNotFoundError, ValueError, OSError):
                        pass
