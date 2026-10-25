"""Versioned studio records; independent of the shared media schemas."""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from myzing.contracts import Record
from myzing.project.locking import project_lock
from myzing.project.models import ProjectError

SESSION_NAME = "studio-session.json"


@dataclass
class Question(Record):
    id: str
    prompt: str
    options: list[dict]
    recommended: Any
    reason: str
    evidence: dict
    required: bool = False
    version: int = 1


@dataclass
class Session(Record):
    answers: dict = field(default_factory=dict)
    history: list[str] = field(default_factory=list)
    questions_asked: int = 0
    status: str = "interview"
    result: dict = field(default_factory=dict)
    automatic_answers: dict = field(default_factory=dict)
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        if self.status not in {"interview", "paused", "planned", "running", "ready", "partial", "failed", "shortage", "cancelled", "interrupted"}:
            raise ValueError("Invalid studio session status")
        if self.questions_asked < 0 or len(set(self.history)) != len(self.history):
            raise ValueError("Invalid studio question history")
        if any(key not in self.answers for key in self.history):
            raise ValueError("Studio history refers to a missing answer")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f"Refusing to replace symlink {path}")
    fd, temporary = tempfile.mkstemp(prefix=".studio-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(50):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                # A Windows status reader can briefly hold the old file open
                # without delete sharing. Keep the complete replacement intact.
                if os.name != "nt" or attempt == 49:
                    raise
                time.sleep(.02)
    finally:
        Path(temporary).unlink(missing_ok=True)


def save_session(project, session):
    root = Path(project).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / SESSION_NAME
    for key in ("source", "reference", "context", "music", "tracks"):
        values = session.answers.get(key, [])
        for value in values if isinstance(values, list) else [values]:
            if isinstance(value, str) and "://" not in value and Path(value).expanduser().resolve() == target:
                raise ValueError(f"Session output would replace input {target}; use another project.")
    for attempt in range(100):
        try:
            lock = project_lock(root)
            lock.__enter__()
            break
        except ProjectError as exc:
            # The lock is held only for one small write. Wait out another
            # session or scan briefly instead of failing with scan advice.
            if attempt == 99:
                raise ValueError(f"Another studio session or scan is writing to {root}; wait for it to finish, "
                                 f"or use another output folder. ({exc})") from None
            time.sleep(.02)
    try:
        if target.exists():
            try:
                Session.from_dict(read_json(target))
            except (ValueError, OSError) as exc:
                raise ValueError(f"Existing {target} is not a studio session; use another project.") from exc
        write_json(target, session.to_dict())
    finally:
        lock.__exit__(None, None, None)
    return target


def load_session(project):
    return Session.from_dict(read_json(Path(project).expanduser().resolve() / SESSION_NAME))
