"""Resolve stored manifest paths without expanding user input."""

from __future__ import annotations

import json
from functools import lru_cache
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


def _state_roots(data, name):
    roots = []
    if name == "match-state.json":
        roots.extend(Path(p) for p in data.get("previous_roots", []))
        for step in data.get("steps", {}).values():
            if step.get("legacy_root"):
                roots.append(Path(step["legacy_root"]))
            log = Path(step.get("log", ""))
            if log.is_absolute() and log.parent.name == "logs":
                roots.append(log.parent.parent)
    else:
        roots.append(Path(data.get("answers", {}).get("project", "")))
    return tuple(roots)


@lru_cache(maxsize=128)
def _file_roots(path, mtime_ns, size):
    try:
        return _state_roots(json.loads(path.read_text(encoding="utf-8-sig")), path.name)
    except (OSError, ValueError, TypeError, AttributeError):
        return ()


def previous_roots(project: Path, *, state=None, session=None) -> list[Path]:
    roots = []
    for name, data in (("match-state.json", state), ("studio-session.json", session)):
        try:
            if data is not None:
                roots.extend(_state_roots(data, name))
            else:
                path = project / name
                info = path.stat()
                roots.extend(_file_roots(path, info.st_mtime_ns, info.st_size))
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    result = []
    for path in dict.fromkeys(roots):
        if not path.is_absolute():
            continue
        try:
            resolved = path.resolve()
            if (resolved.parent != resolved and resolved != Path.home().resolve()
                    and not project.resolve().is_relative_to(resolved)):
                result.append(path)
        except (OSError, ValueError, RuntimeError):
            continue
    return result


def relocate(value: str, project: Path, roots) -> str:
    try:
        path = Path(value)
        if path.is_absolute() and not path.is_relative_to(project):
            for old in roots:
                if path.is_relative_to(old):
                    relative = path.relative_to(old)
                    moved = resolve_path(relative.as_posix(), project)
                    return str(moved) if moved.exists() or not path.exists() else value
    except (ProjectError, OSError, RuntimeError):
        pass
    return value


def portable(value: str, project: Path) -> str:
    path = Path(value)
    if path.is_absolute() and path.is_relative_to(project) and path.resolve().is_relative_to(project):
        return path.relative_to(project).as_posix()
    return value


def local_paths(value, project, roots=(), *, fields=(), mappings=(), values=(), literals=(), key=""):
    def path(text):
        return str(resolve_path(text, project, roots=roots))

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


def resolve_path(value: str, project: Path | None, *, entry: str = "path", roots=None) -> Path:
    if not isinstance(value, str) or not value or "\0" in value:
        raise ProjectError(f"Invalid {entry}: expected a nonempty path without NUL characters.")
    path = Path(value)
    windows = PureWindowsPath(value)
    if (windows.drive and not windows.root) or (path.anchor and not path.is_absolute()):
        raise ProjectError(f"Invalid {entry} {value!r}: drive-relative or root-relative paths are ambiguous. "
                           "Use a project-relative path or a fully absolute path.")
    if path.is_absolute():
        if project is not None and not path.is_relative_to(project):
            return Path(relocate(value, project, previous_roots(project) if roots is None else roots))
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
