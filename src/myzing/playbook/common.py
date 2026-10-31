"""Playbook-owned contracts and atomic local persistence."""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_name(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("IDs, handles and versions must contain only letters, digits, _ or -")
    return value


def number(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def library(root: Path) -> dict:
    data = read_json(root / "library.json")
    if data.get("schema_version") != SCHEMA_VERSION or not isinstance(data.get("entries"), list):
        raise ValueError("unsupported library schema")
    seen = set()
    for entry in data["entries"]:
        ident = safe_name(entry["id"])
        safe_name(entry["channel"])
        if ident in seen or entry.get("set") not in ("worked", "didnt"):
            raise ValueError("duplicate ID or invalid comparison set in library")
        seen.add(ident)
        if entry.get("platform") != "youtube" or entry.get("url") != f"https://www.youtube.com/shorts/{ident}":
            raise ValueError("library entries must use canonical public YouTube Shorts URLs")
    return data
