"""Validate, save atomically, and resume a project's creative brief."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from myzing.project.api import load_project, resolve_path, stored_path
from myzing.project.locking import project_lock
from .models import Brief, BriefError

BRIEF_NAME = "brief.json"


def brief_path(project: str | Path) -> Path:
    return Path(project).expanduser().resolve() / BRIEF_NAME


def load_brief(path: str | Path) -> Brief:
    path = Path(path).expanduser().resolve()
    try:
        return Brief.from_dict(json.loads(path.read_text(encoding="utf-8-sig")))
    except FileNotFoundError as exc:
        raise BriefError(f"No brief at {path}. Run 'zing brief new <project-folder>' first.") from exc
    except (ValueError, UnicodeError) as exc:
        raise BriefError(f"Cannot load {path}: {exc}") from exc


def _asset(selector, assets):
    # Prefer stable IDs and exact stored paths; a basename is only a convenience
    # when unambiguous. Never guess between two clips with the same filename.
    exact = [a for a in assets if a.id == selector or a.path == selector]
    matches = exact or [a for a in assets if Path(a.path).name == selector]
    if len(matches) != 1:
        reason = "ambiguous" if matches else "unknown"
        raise BriefError(f"{reason} clip '{selector}': use an asset ID or path from 'zing project status --json'.")
    return matches[0]


def validate_for_project(project: str | Path, brief: Brief) -> Brief:
    root = Path(project).expanduser().resolve()
    manifest = load_project(root)
    data = brief.to_dict()
    for field in ("must_keep", "forbidden"):
        for moment in data[field]:
            if "clip" not in moment:
                continue  # Phrase matching is deferred until timed words exist.
            asset = _asset(moment["clip"], manifest.assets)
            moment["clip"] = asset.id
            if asset.probe and not any(s.get("codec_type") == "video" for s in asset.probe.streams):
                raise BriefError(f"{field}: '{asset.path}' has no video stream. Choose a clip.")
            if "end" in moment and asset.probe and asset.probe.duration is not None:
                if moment["end"] > asset.probe.duration:
                    raise BriefError(f"{field}: '{asset.path}' ends at {asset.probe.duration:g} s in the inventory; shorten the range or scan updated media.")
    for role in ("music", "sfx"):
        # Paths may be missing: record the choice, then name the gap in the
        # recommendation. Relative paths always belong to the project, not CWD.
        paths = []
        for value in data[role]["files"]:
            asset = next((a for a in manifest.assets if a.id == value), None)
            paths.append(asset.id if asset else stored_path(resolve_path(value, root), root))
        data[role]["files"] = paths
    return Brief.from_dict(data)  # Check conflicts again after ID resolution.


def save_brief(project: str | Path, brief: Brief, *, replace: bool = True) -> Brief:
    root = Path(project).expanduser().resolve()
    load_project(root)  # Give init guidance before attempting a lock.
    with project_lock(root):
        brief = validate_for_project(root, brief)
        target = root / BRIEF_NAME
        if target.is_symlink():
            raise BriefError(f"Refusing to replace symlink {target}; use a regular brief.json.")
        if target.exists() and not replace:
            raise BriefError("A brief was saved while you were answering. Run 'zing brief show' to review it, then use --restart to replace it.")
        payload = json.dumps(brief.to_dict(), indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if target.exists() and target.read_text(encoding="utf-8") == payload:
            return brief
        fd, name = tempfile.mkstemp(prefix=".brief-", suffix=".tmp", dir=root)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return brief


def brief_result(project: str | Path, brief: Brief) -> dict:
    from .recommend import recommend

    return {"brief_path": str(brief_path(project)), "brief": brief.to_dict(),
            "recommendation": recommend(project, brief)}
