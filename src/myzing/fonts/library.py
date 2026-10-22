"""Offline font inventory and explicit, hash-checked provisioning."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from urllib.request import urlopen

from myzing import storage

DATA = Path(__file__).resolve().parents[1] / "_data" / "fonts"
MANIFEST = DATA / "library.json"
INSTALL_HINT = 'python -m pip install "myzing[fonts]"'


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest() -> dict:
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if value.get("version") != 1:
        raise ValueError("unsupported font library version; reinstall Zing")
    return value


def _cache(entry: dict, workspace: Path | None) -> Path:
    root = storage.resolve_workspace(workspace)
    folder = root / "fonts" / entry["id"]
    if not folder.resolve().is_relative_to(root):
        raise ValueError("font cache resolves outside the Zing workspace")
    return folder


def _verified(path: Path, digest: str) -> bool:
    return path.is_file() and sha256(path) == digest


def inventory(workspace: Path | None = None) -> list[dict]:
    """Only verified font/license pairs are available; never scan system fonts."""
    result = []
    for entry in manifest()["fonts"]:
        row = dict(entry, available=False, status="not fetched", path=None)
        folders = [(DATA, "bundled")] if entry["bundled"] else []
        folders.append((_cache(entry, workspace), "fetched"))
        for folder, label in folders:
            font, license_path = folder / entry["file"], folder / entry["license_file"]
            try:
                valid = _verified(font, entry["sha256"]) and _verified(license_path, entry["license_sha256"])
            except OSError:
                valid = False
            if valid:
                row.update(available=True, status=label, path=str(font.resolve()))
                break
            if font.exists() or license_path.exists():
                row["status"] = "corrupt or incomplete; run zing fonts fetch " + entry["id"]
        result.append(row)
    return result


def fetch(ids: list[str], workspace: Path | None = None) -> list[dict]:
    """The only network boundary. Verify BOTH payloads before publishing either."""
    rows = inventory(workspace)
    known = {r["id"] for r in rows}
    unknown = set(ids) - known
    if unknown:
        raise ValueError(f"unknown font(s): {', '.join(sorted(unknown))}; run zing fonts list")
    for row in rows:
        if row["id"] not in ids or row["available"]:
            continue
        folder = _cache(row, workspace)
        folder.mkdir(parents=True, exist_ok=True)
        staged = []
        try:
            for prefix in ("", "license_"):
                destination = folder / row[prefix + "file"]
                if not destination.resolve().is_relative_to(folder.resolve()):
                    raise ValueError("font asset resolves outside its cache folder")
                with urlopen(row[prefix + "url"], timeout=60) as response:
                    payload = response.read(16 * 1024 * 1024 + 1)
                if len(payload) > 16 * 1024 * 1024 or hashlib.sha256(payload).hexdigest() != row[prefix + "sha256"]:
                    raise ValueError(f"font asset SHA-256 mismatch: {row['id']} {prefix or 'font'}; no unverified asset installed")
                with tempfile.NamedTemporaryFile(dir=folder, suffix=".part", delete=False) as stream:
                    staged.append((Path(stream.name), destination))
                    stream.write(payload)
            for temporary, destination in staged:
                os.replace(temporary, destination)
        finally:
            for temporary, _ in staged:
                temporary.unlink(missing_ok=True)
    return [r for r in inventory(workspace) if r["id"] in ids]
