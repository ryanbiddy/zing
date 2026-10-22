"""Content-checked checkpoints. An interrupted step never becomes complete."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from myzing.project.api import hash_file

VERSION = 1


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".match-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


class StepFailed(RuntimeError):
    pass


class Checkpoints:
    def __init__(self, root, resume, progress=None):
        self.root, self.resume, self.progress = Path(root), resume, progress
        self.path = self.root / "match-state.json"
        self.data = read(self.path) if self.path.exists() else {"version": VERSION, "steps": {}}
        if self.data.get("version") != VERSION:
            raise ValueError("Unsupported match checkpoint version; use a new --out folder.")
        self.used = []
        self.reused = []
        self.data.update(status="running", started_at=time.time())
        write(self.path, self.data)

    def step(self, name, inputs, action):
        key = fingerprint({"version": VERSION, "inputs": inputs})
        old = self.data["steps"].get(name, {})
        self.used.append(name)
        if self.resume and old.get("status") == "done" and old.get("key") == key:
            try:
                valid = all(Path(p).is_file() and hash_file(Path(p)) == sha
                            for p, sha in old["artifacts"].items())
            except (OSError, KeyError, TypeError):
                valid = False
            if valid:
                self.reused.append(name)
                self.emit(name, "reused")
                return old["result"]
        log = self.root / "logs" / (name.replace("/", "-") + ".log")
        log.parent.mkdir(parents=True, exist_ok=True)
        entry = {"status": "running", "key": key, "log": str(log), "started_at": time.time()}
        self.data["steps"][name] = entry
        write(self.path, self.data)
        self.emit(name, "starting")
        with log.open("w", encoding="utf-8") as stream:
            try:
                # Match's worker has its own interpreter. No other MCP job shares
                # these streams; the parent receives only explicit progress lines.
                with redirect_stdout(stream), redirect_stderr(stream):
                    result = action()
                artifacts = {str(Path(p).resolve()): hash_file(Path(p)) for p in result.get("outputs", [])}
                result["checkpoint"] = fingerprint({"key": key, "artifacts": artifacts})
                entry.update(status="done", result=result, artifacts=artifacts)
            except BaseException as exc:
                traceback.print_exc(file=stream)
                entry.update(status="cancelled" if isinstance(exc, KeyboardInterrupt) else "failed",
                             error=f"{type(exc).__name__}: {exc}")
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                raise StepFailed(f"{name}: {exc}; log: {log}") from exc
            finally:
                entry["seconds"] = round(time.time() - entry["started_at"], 3)
                write(self.path, self.data)
        self.emit(name, "done")
        return result

    def emit(self, name, status):
        if self.progress:
            self.progress(f"{name}: {status}")

    def failures(self):
        return [{"step": name, "error": self.data["steps"][name]["error"],
                 "log": self.data["steps"][name]["log"]}
                for name in self.used if self.data["steps"][name]["status"] in {"failed", "cancelled"}]

    def finish(self, status):
        self.data.update(status=status, finished_at=time.time(), reused_steps=self.reused)
        write(self.path, self.data)


def interrupted(root, reason="cancelled"):
    path = Path(root) / "match-state.json"
    if not path.exists():
        return
    data = read(path)
    for name, entry in data.get("steps", {}).items():
        if entry.get("status") == "running":
            entry.update(status=reason, error=f"{name}: worker {reason}; rerun with --resume")
            with Path(entry["log"]).open("a", encoding="utf-8") as stream:
                stream.write(entry["error"] + "\n")
    data.update(status=reason, finished_at=time.time())
    write(path, data)
