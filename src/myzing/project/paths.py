"""Resolve stored manifest paths without expanding user input."""

from __future__ import annotations

import json
from pathlib import Path, PureWindowsPath

from .models import ProjectError


def stored_path(path: Path, project: Path) -> str:
    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(project.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def map_paths(value, change):
    if isinstance(value, dict):
        return {change(k): map_paths(v, change) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [map_paths(v, change) for v in value]
    return change(value) if isinstance(value, str) else value


def previous_roots(project: Path) -> list[Path]:
    roots = []
    for name in ("match-state.json", "studio-session.json", "project.json"):
        try:
            data = json.loads((project / name).read_text(encoding="utf-8-sig"))
            if name == "match-state.json":
                roots.extend(Path(p) for p in data.get("previous_roots", []))
                for step in data.get("steps", {}).values():
                    if step.get("legacy_root"):
                        roots.append(Path(step["legacy_root"]))
                    log = Path(step.get("log", ""))
                    if log.is_absolute() and log.parent.name == "logs":
                        roots.append(log.parent.parent)
            elif name == "studio-session.json":
                roots.append(Path(data.get("answers", {}).get("project", "")))
            else:
                path = Path((data.get("reference", {}).get("study") or {}).get("breakdown_path", ""))
                if path.is_absolute():
                    for parent in path.parents:
                        if parent.name == "breakdowns":
                            old = parent.parent.parent if parent.parent.name == "reference" else parent.parent
                            if (project / path.relative_to(old)).is_file():
                                roots.append(old)
                            break
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return list(dict.fromkeys(p for p in roots if p.is_absolute() and p != project))


def relocate(value: str, project: Path, roots) -> str:
    path = Path(value)
    if path.is_absolute() and not path.is_relative_to(project):
        for old in roots:
            if path.is_relative_to(old):
                relative = path.relative_to(old)
                return str(resolve_path(relative.as_posix(), project))
    return value


def portable(value: str, project: Path) -> str:
    path = Path(value)
    if path.is_absolute() and path.is_relative_to(project) and path.resolve().is_relative_to(project):
        return path.relative_to(project).as_posix()
    return value


def local_paths(value, project, roots=(), *, fields=(), mappings=(), values=(), literals=(), key=""):
    def path(text):
        return str(resolve_path(relocate(text, project, roots), project))

    if isinstance(value, dict):
        return {path(k) if key in mappings else k: v if k in {"legacy_root", "previous_roots"} else
                local_paths(v, project, roots, fields=fields, mappings=mappings, values=values, literals=literals,
                            key=key if key in values else k) for k, v in value.items()}
    if isinstance(value, list):
        return [local_paths(v, project, roots, fields=fields, mappings=mappings, values=values,
                            literals=literals, key=key) for v in value]
    if isinstance(value, str):
        if key in fields and value and value not in literals and "://" not in value and not value.startswith("uoink:"):
            return path(value)
        return relocate(value, project, roots)
    return value


def resolve_path(value: str, project: Path | None, *, entry: str = "path") -> Path:
    if not isinstance(value, str) or not value or "\0" in value:
        raise ProjectError(f"Invalid {entry}: expected a nonempty path without NUL characters.")
    path = Path(value)
    windows = PureWindowsPath(value)
    if (windows.drive and not windows.root) or (path.anchor and not path.is_absolute()):
        raise ProjectError(f"Invalid {entry} {value!r}: drive-relative or root-relative paths are ambiguous. "
                           "Use a project-relative path or a fully absolute path.")
    if path.is_absolute():
        if project is not None and not path.is_relative_to(project):
            moved = Path(relocate(value, project, previous_roots(project)))
            if moved != path and moved.exists():
                return moved
        return path
    if project is None:
        raise ProjectError(f"Invalid {entry} {value!r}: supply the project folder to validate relative paths.")
    try:
        root = project.resolve()
        resolved = (root / path).resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProjectError(f"Invalid {entry} {value!r}: cannot resolve path: {exc}") from exc
    if not resolved.is_relative_to(root):
        raise ProjectError(f"Invalid {entry} {value!r}: relative path resolves outside the project folder. "
                           "Use a path inside the project or an explicit absolute path.")
    return resolved
