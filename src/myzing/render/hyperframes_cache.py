"""Verified full-composition caption overlays retained in the render work folder."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from . import hyperframes_adapter as hf
from .hyperframes_publish import reserve_output


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def overlay_key(plan: hf.HyperframesPlan) -> str:
    data = plan.to_dict()
    for event in [*data["captions"], *data.get("graphics", [])]:
        # Identity is font bytes, not the machine's asset directory spelling.
        style = event["style"]
        if "font" not in style:
            continue  # A textless graphic embeds no font.
        digest = _sha256(Path(style.pop("font")))
        if digest != style.get("font_sha256"):
            raise hf.HyperframesError("HyperFrames font SHA-256 mismatch; restore the declared font file")
    contract = {"version": 1, "hyperframes": hf.HYPERFRAMES_VERSION,
                "alpha": "straight", "plan": data}
    # Template/sidecar fixes must invalidate an old render, even at the same pin.
    sidecar = hf.sidecar_directory()
    contract["sidecar"] = {name: _sha256(sidecar / name) for name in
                           ("render.mjs", "plan.mjs", "templates.mjs", "offline.cjs", "package-lock.json")}
    return hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def cached_overlay(plan: hf.HyperframesPlan, directory: Path, *, ffmpeg: str, ffprobe: str) -> Path:
    """The adapter call is the CI seam; production never substitutes another backend.

    Cache hits still decode/probe the overlay and verify its content hash. A lock
    covers the cache manifest and the adapter's atomic output/receipt publication.
    """
    root = directory / "hyperframes-overlays"
    try:
        key = overlay_key(plan)
        overlay = root / f"{key}.mov"
        manifest = root / f"{key}.json"
        with reserve_output(manifest, overwrite=True):
            if overlay.is_file() and manifest.is_file():
                entry = json.loads(manifest.read_text(encoding="utf-8"))
                hf.verify_output(overlay, plan, ffprobe)
                if (not isinstance(entry, dict) or entry.get("version") != 1
                        or entry.get("alpha") != "straight" or entry.get("key") != key
                        or entry.get("sha256") != _sha256(overlay)):
                    raise hf.HyperframesError(f"HyperFrames cache integrity mismatch: {overlay}; remove this cache entry and rerender")
            else:
                hf.render_hyperframes(plan, overlay, workspace=directory, overwrite=True,
                                      ffmpeg=ffmpeg, ffprobe=ffprobe)
                probe = hf.verify_output(overlay, plan, ffprobe)
                entry = {"version": 1, "key": key, "sha256": _sha256(overlay),
                         "alpha": "straight", "stage": "after_transitions_before_ass",
                         "plan": plan.to_dict(), "probe": probe}
                stage = manifest.with_suffix(".json.part")
                stage.write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")
                os.replace(stage, manifest)
    except (OSError, ValueError) as exc:
        raise hf.HyperframesError(f"Could not prepare HyperFrames overlay cache {root}: {exc}") from exc
    return overlay
