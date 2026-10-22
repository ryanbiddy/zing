"""Transactional local inventories for the future match pipeline."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tempfile
from collections import defaultdict, deque
from pathlib import Path

from myzing.study.proc import MediaError, ToolMissing
from myzing.urls import is_http_url
from .locking import LOCK_NAME, lock_description, project_lock
from .models import Asset, ProjectError, ProjectManifest, Reference, SourceRecord
from .paths import resolve_path
from .probe import probe_file, unsupported_extension

MANIFEST_NAME = "project.json"


def stored_path(path: Path, project: Path) -> str:
    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(project).as_posix()
    except ValueError:
        return str(resolved)


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_project(project: str | Path) -> ProjectManifest:
    path = Path(project).expanduser().resolve() / MANIFEST_NAME
    try:
        return ProjectManifest.from_dict(json.loads(path.read_text(encoding="utf-8")), path.parent)
    except FileNotFoundError as exc:
        raise ProjectError(f"No manifest at {path}. Run 'zing project init' first.") from exc
    except (ValueError, TypeError) as exc:
        raise ProjectError(f"Cannot load {path}: {exc}") from exc


def _save(root: Path, manifest: ProjectManifest) -> None:
    target = root / MANIFEST_NAME
    if target.is_symlink():
        raise ProjectError(f"Refusing to replace symlink {target}; use a regular project.json.")
    payload = json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    # A no-op scan also preserves the manifest's mtime.
    if target.exists() and target.read_text(encoding="utf-8") == payload:
        return
    fd, name = tempfile.mkstemp(prefix=".project-", suffix=".tmp", dir=root)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _files(clips: Path, root: Path) -> list[Path]:
    if not clips.exists():
        return []
    if not clips.is_dir():
        raise ProjectError(f"Clip folder is no longer a directory: {clips}. Restore it and scan again.")

    def on_error(error):
        # A permission error must not masquerade as removed media.
        raise error

    found = []
    for directory, dirs, names in os.walk(clips, followlinks=False, onerror=on_error):
        parent = Path(directory)
        dirs[:] = sorted(d for d in dirs if not (parent / d).is_symlink()
                         and not (getattr((parent / d).lstat(), "st_file_attributes", 0)
                                  & stat.FILE_ATTRIBUTE_REPARSE_POINT)
                         and (parent / d).resolve() != root)
        for name in sorted(names):
            path = parent / name
            if parent == root and (name in {MANIFEST_NAME, LOCK_NAME, "brief.json"}
                                   or (name.startswith((".project-", ".brief-")) and name.endswith(".tmp"))):
                continue
            if not path.is_symlink() and stat.S_ISREG(path.stat().st_mode):
                found.append(path)
    return sorted(found)


def _signature(path: Path) -> tuple[int, int]:
    info = path.stat()
    return info.st_size, info.st_mtime_ns


def _scan(root: Path, manifest: ProjectManifest) -> ProjectManifest:
    clips = resolve_path(manifest.clips_root, root, entry="clips_root")
    files = _files(clips, root)
    by_path = defaultdict(list)
    for asset in sorted(manifest.assets, key=lambda a: (a.state == "missing", a.path, a.id)):
        by_path[asset.path].append(asset)
    existing_ids = {asset.id for asset in manifest.assets}
    observations = []
    for path in files:
        key = stored_path(path, root)
        cached = next(iter(by_path[key]), None)
        signature = _signature(path)
        if cached and signature == (cached.size, cached.mtime_ns):
            digest = cached.sha256
        else:
            digest = hash_file(path)
        if _signature(path) != signature:
            raise ProjectError(f"Source changed during scan: {path}. Wait for writes to finish and scan again.")
        observations.append((path, key, signature, digest))

    # Reserve exact path/content matches, then follow content across moves, then
    # treat remaining same-path records as edits. This also handles name swaps
    # and a moved file whose old name was immediately reused by a new source.
    assignments, used = {}, set()
    for _, key, _, digest in observations:
        asset = next((a for a in by_path[key] if a.sha256 == digest and a.id not in used), None)
        if asset:
            assignments[key] = asset
            used.add(asset.id)
    available = defaultdict(deque)
    for asset in sorted(manifest.assets, key=lambda a: (a.state == "missing", a.path, a.id)):
        if asset.id not in used:
            available[asset.sha256].append(asset)
    for _, key, _, digest in observations:
        if key not in assignments and available[digest]:
            asset = available[digest].popleft()
            assignments[key] = asset
            used.add(asset.id)
    for _, key, _, _ in observations:
        if key not in assignments:
            asset = next((a for a in by_path[key] if a.id not in used), None)
            if asset:
                assignments[key] = asset
                used.add(asset.id)

    for path, key, signature, digest in observations:
        asset = assignments.get(key)
        stat_changed = asset is None or signature != (asset.size, asset.mtime_ns)
        was_unlisted = asset is not None and unsupported_extension(Path(asset.path)) is not None
        if asset:
            if asset.path != key:
                asset.previous_paths.append(asset.path)
                asset.path = key
        else:
            # Deterministic first IDs make a failed first scan reproducible.
            identity = hashlib.sha256((key + "\0" + digest).encode("utf-8")).hexdigest()[:32]
            asset = Asset(
                id="asset_" + identity, path=key, original_path=key, sha256=digest,
                size=signature[0], mtime_ns=signature[1],
                source=SourceRecord(key, manifest.source.supplied_by, manifest.source.license),
                probe=None,
            )
            base_id, suffix = asset.id, 2
            while asset.id in existing_ids:
                asset.id = f"{base_id}_{suffix}"
                suffix += 1
            manifest.assets.append(asset)
            existing_ids.add(asset.id)
        content_changed = asset.sha256 != digest
        unsupported = unsupported_extension(path)
        if unsupported:
            asset.probe = None
            asset.error = unsupported
        elif content_changed or was_unlisted or (asset.probe is None and (asset.error is None or stat_changed)):
            try:
                asset.probe = probe_file(path)
                asset.error = None
            except ToolMissing:
                raise  # install guidance; do not label every source unsupported
            except (MediaError, subprocess.TimeoutExpired) as exc:
                asset.probe = None
                asset.error = str(exc)
        if _signature(path) != signature:
            raise ProjectError(f"Source changed during scan: {path}. Wait for writes to finish and scan again.")
        if content_changed:
            asset.revision += 1
        asset.sha256 = digest
        asset.size, asset.mtime_ns = signature
        asset.state = "unsupported" if asset.error or (asset.probe and asset.probe.flags) else "ready"
        used.add(asset.id)
    for asset in manifest.assets:
        if asset.id not in used:
            asset.state = "missing"
    manifest.assets.sort(key=lambda asset: asset.id)
    _save(root, manifest)
    return manifest


def init_project(
    reference: str, clips: str | Path, out: str | Path, *,
    supplied_by: str = "user", license: str = "user-supplied",
) -> ProjectManifest:
    root = Path(out).expanduser().resolve()
    clips_path = Path(clips).expanduser().resolve()
    if not clips_path.is_dir():
        raise ProjectError(f"Clip folder does not exist: {clips_path}. Supply a local folder with --clips.")
    if not reference.strip():
        raise ProjectError("Supply one URL, local file, or uoink:<item-id> with --reference.")
    if reference.startswith("uoink:"):
        if not reference[6:].strip():
            raise ProjectError("A Uoink reference needs an item ID: uoink:<item-id>.")
        kind, value = "uoink", reference
    elif is_http_url(reference):
        kind, value = "url", reference
    else:
        if "://" in reference:
            raise ProjectError("Reference URLs must use http or https, or supply a local file.")
        kind, value = "file", stored_path(Path(reference), root)
    root.mkdir(parents=True, exist_ok=True)
    with project_lock(root):
        if (root / MANIFEST_NAME).exists():
            raise ProjectError(f"Project already exists at {root}. Use 'zing project scan' to resume.")
        source = SourceRecord(stored_path(clips_path, root), supplied_by, license)
        manifest = ProjectManifest(
            reference=Reference(value, kind, SourceRecord(value, supplied_by, license)),
            clips_root=source.origin, source=source,
        )
        # Even an interrupted initial inventory leaves a valid resumable project.
        _save(root, manifest)
        return _scan(root, manifest)


def scan_project(project: str | Path) -> ProjectManifest:
    root = Path(project).expanduser().resolve()
    if not root.is_dir():
        raise ProjectError(f"Project folder does not exist: {root}. Run 'zing project init' first.")
    with project_lock(root):
        return _scan(root, load_project(root))


def project_status(project: str | Path) -> dict:
    """Read-only status: live stat checks never hash, probe, or change the inventory."""
    root = Path(project).expanduser().resolve()
    manifest = load_project(root)
    counts = {state: 0 for state in ("ready", "missing", "changed", "unsupported")}
    occupied_paths = {a.path for a in manifest.assets if a.state != "missing"}
    rows = []
    for asset in manifest.assets:
        needs_scan, error = False, asset.error
        try:
            path = resolve_path(asset.path, root, entry=f"asset {asset.id}.path")
            if not path.is_file() or (asset.state == "missing" and asset.path in occupied_paths):
                state = "missing"
            elif _signature(path) != (asset.size, asset.mtime_ns) or asset.state == "missing":
                state, needs_scan = "changed", True
            elif asset.state == "unsupported":
                state = "unsupported"
            else:
                state = "changed" if asset.revision > 1 else "ready"
        except OSError as exc:
            state, error = "unsupported", str(exc)
        counts[state] += 1
        rows.append({
            "id": asset.id, "path": asset.path, "state": state, "revision": asset.revision,
            "sha256": asset.sha256, "needs_scan": needs_scan, "error": error,
            "orientation": asset.probe.orientation if asset.probe else None,
            "flags": asset.probe.flags if asset.probe else [],
        })
    return {
        "version": 1, "manifest_path": str(root / MANIFEST_NAME),
        "reference": manifest.reference.to_dict(), "counts": counts, "assets": rows,
        "lock": lock_description(root / LOCK_NAME) if (root / LOCK_NAME).exists() else None,
    }
