"""P-C2 freeze: dump raw per-frame OCR evidence for calibration cells.

Re-runs the exact study-time sampling and OCR over a stored study's
media and writes frozen/<slug>.jsonl — one provenance header row, then
one row per sampled frame. Deterministic for a given media file + OCR
model; rerunning this script IS the regeneration command.

Usage:
    python freeze.py <workspace> <slug> [<slug> ...]

Research tooling (P-C2, warning-only phase): no production imports
back into the study pipeline; reuses captions.py internals read-only.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from myzing import storage
from myzing.study import captions


def freeze(workspace: Path, slug: str, out_dir: Path) -> Path:
    with storage.use_workspace(workspace):
        breakdown = storage.load_breakdown(slug)
        media = storage.find_media(slug)
    if media is None:
        raise SystemExit(f"{slug}: no stored media in {workspace}")
    duration = breakdown.meta.duration
    engine, version = captions._engine()

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{slug}.jsonl"
    rows = 0
    with target.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "provenance": {
                "slug": slug,
                "source_url": breakdown.meta.source_url,
                "duration": duration,
                "ocr_backend": f"rapidocr-{version}",
                "conf_threshold": captions.CONF_THRESHOLD,
                "sampling": captions.sampling_note(duration),
            }
        }) + "\n")
        for t, step, frame in captions._iter_frames(media, duration):
            try:
                lines = captions._ocr(engine, frame)
            except Exception as exc:  # frozen honestly, not silently
                fh.write(json.dumps({
                    "t": round(t, 3), "step": step,
                    "error": f"{type(exc).__name__}: {exc}"[:120],
                }) + "\n")
                continue
            fh.write(json.dumps({
                "t": round(t, 3),
                "step": step,
                "frame_sha256": hashlib.sha256(frame.tobytes()).hexdigest(),
                "lines": [
                    {
                        "text": ln.text,
                        "score": round(float(ln.score), 4),
                        "y_center": round(float(ln.y_center), 4),
                        "x_center": round(float(ln.x_center), 4),
                    }
                    for ln in lines
                ],
            }) + "\n")
            rows += 1
    print(f"{slug}: froze {rows} frames -> {target}")
    return target


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    ws = Path(sys.argv[1])
    here = Path(__file__).resolve().parent
    for s in sys.argv[2:]:
        freeze(ws, s, here / "frozen")
