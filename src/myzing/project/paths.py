"""Resolve stored manifest paths without expanding user input."""

from __future__ import annotations

from pathlib import Path, PureWindowsPath

from .models import ProjectError


def resolve_path(value: str, project: Path | None, *, entry: str = "path") -> Path:
    if not isinstance(value, str) or not value or "\0" in value:
        raise ProjectError(f"Invalid {entry}: expected a nonempty path without NUL characters.")
    path = Path(value)
    windows = PureWindowsPath(value)
    if (windows.drive and not windows.root) or (path.anchor and not path.is_absolute()):
        raise ProjectError(f"Invalid {entry} {value!r}: drive-relative or root-relative paths are ambiguous. "
                           "Use a project-relative path or a fully absolute path.")
    if path.is_absolute():
        # Absolute paths are an explicit opt-in to external media. Do not resolve
        # links, expand '~', or reinterpret them relative to the project.
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
