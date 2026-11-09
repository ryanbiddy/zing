"""Content-checked checkpoints. An interrupted step never becomes complete."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from myzing.project.api import hash_file
from myzing.project.paths import local_paths, map_paths, portable, previous_roots, relocate, resolve_path

VERSION = 1
PATH_FIELDS = {"log", "path", "media", "geometry", "outputs", "comparison_path", "study_path",
               "video", "plan", "timeline", "report", "recipe", "comparison", "plans"}


def resolve_data(data, root):
    return local_paths(data, root, previous_roots(root), fields=PATH_FIELDS, mappings={"artifacts"}, values={"plans"})


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
        self.root, self.resume, self.progress = Path(root).resolve(), resume, progress
        self.path = self.root / "match-state.json"
        self.data = read(self.path) if self.path.exists() else {"version": VERSION, "steps": {}}
        if self.data.get("version") != VERSION:
            raise ValueError("Unsupported match checkpoint version; use a new --out folder.")
        if not self.data.get("relative_paths"):
            roots = []
            for entry in self.data["steps"].values():
                log = Path(entry.get("log", ""))
                if log.is_absolute():
                    entry["legacy_root"] = str(log.parent.parent)  # Retain the old hash basis until reuse.
                    roots.append(entry["legacy_root"])
            self.data["previous_roots"] = list(dict.fromkeys(roots))
            if roots and self.data.get("auto_moments"):
                self.data["auto_moments"]["legacy_root"] = roots[0]
        self.data = resolve_data(self.data, self.root)
        self.data["relative_paths"] = True
        self.used = []
        self.reused = []
        self.data.update(status="running", started_at=time.time())
        self.save()

    def save(self):
        data = map_paths(self.data, lambda p: portable(p, self.root))
        if "previous_roots" in self.data:
            data["previous_roots"] = self.data["previous_roots"]
        for name, entry in self.data["steps"].items():
            if "legacy_root" in entry:
                data["steps"][name]["legacy_root"] = entry["legacy_root"]
        if self.data.get("auto_moments", {}).get("legacy_root"):
            data["auto_moments"]["legacy_root"] = self.data["auto_moments"]["legacy_root"]
        write(self.path, data)

    def key(self, inputs):
        return fingerprint(map_paths(inputs, lambda p: portable(p, self.root)))

    def matches(self, old, inputs):
        if old.get("key") == self.key(inputs):
            return True
        root = old.get("legacy_root")
        if not root:
            return False
        def original(value):
            relative = portable(value, self.root)
            return str(Path(root) / relative) if relative != value else value
        return old.get("key") == fingerprint(map_paths(inputs, original))

    def step(self, name, inputs, action):
        inputs = {"version": VERSION, "inputs": inputs}
        key = self.key(inputs)
        old = self.data["steps"].get(name, {})
        self.used.append(name)
        if self.resume and old.get("status") == "done" and self.matches(old, inputs):
            try:
                valid = all(Path(p).is_file() and hash_file(Path(p)) == sha
                            for p, sha in old["artifacts"].items())
            except (OSError, KeyError, TypeError):
                valid = False
            if valid:
                old["key"] = key
                old.pop("legacy_root", None)
                self.save()
                self.reused.append(name)
                self.emit(name, "reused")
                return old["result"]
        filename = re.sub(r"[^A-Za-z0-9._-]", "-", name).lstrip(".") or "step"
        log = self.root / "logs" / (filename + ".log")
        log.parent.mkdir(parents=True, exist_ok=True)
        entry = {"status": "running", "key": key, "log": str(log), "started_at": time.time()}
        self.data["steps"][name] = entry
        self.save()
        self.emit(name, "starting")
        with log.open("w", encoding="utf-8") as stream:
            try:
                # Match's worker has its own interpreter. No other MCP job shares
                # these streams; the parent receives only explicit progress lines.
                with redirect_stdout(stream), redirect_stderr(stream):
                    result = action()
                artifacts = {str(Path(p).resolve()): hash_file(Path(p)) for p in result.get("outputs", [])}
                result["checkpoint"] = self.key({"key": key, "artifacts": artifacts})
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
                self.save()
        self.emit(name, "done")
        return result

    def emit(self, name, status):
        if self.progress:
            self.progress(f"{name}: {status}")

    def failures(self):
        return [{"step": name, "error": self.data["steps"][name]["error"],
                 "log": self.data["steps"][name]["log"]}
                for name in dict.fromkeys(self.used) if self.data["steps"][name]["status"] in {"failed", "cancelled"}]

    def finish(self, status):
        self.data.update(status=status, finished_at=time.time(), reused_steps=self.reused)
        self.save()


def interrupted(root, reason="cancelled"):
    root = Path(root).resolve()
    path = root / "match-state.json"
    if not path.exists():
        return
    data = read(path)
    roots = previous_roots(root)
    for name, entry in data.get("steps", {}).items():
        if entry.get("status") == "running":
            entry.update(status=reason, error=f"{name}: worker {reason}; rerun with --resume")
            log = resolve_path(relocate(entry["log"], root, roots), root)
            log.parent.mkdir(parents=True, exist_ok=True)
            entry["log"] = portable(str(log), root)
            with log.open("a", encoding="utf-8") as stream:
                stream.write(entry["error"] + "\n")
    data.update(status=reason, finished_at=time.time())
    write(path, data)
