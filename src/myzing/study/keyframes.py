"""Keyframe extraction: give the judgment AI eyes (critique A#2, binding).

Writes into the breakdown folder:
- ``frames/shot_<index>.jpg`` — the first frame of every shot; the relative
  path lands in ``Shot.keyframe``.
- ``frames/hook_<second>.jpg`` — ~1 fps over the format's hook window
  (0-3s short-form, 0-30s long-form; see formats.py), so the visual hook
  is inspectable even when shot 0 is long.

Extraction failures degrade per-frame (empty keyframe + one warning), the
study never dies over a thumbnail.
"""

from __future__ import annotations

from pathlib import Path

from myzing.schemas import Shot

from . import formats, proc

FRAMES_DIR = "frames"
JPEG_QUALITY = "3"                # ffmpeg -q:v scale; 2-5 is visually fine


def extract_keyframes(
    media_path: Path,
    breakdown_dir: Path,
    shots: list[Shot],
    duration: float,
    warnings: list[str],
) -> None:
    """Mutates ``shots`` in place, setting relative keyframe paths."""
    frames_dir = breakdown_dir / FRAMES_DIR
    frames_dir.mkdir(parents=True, exist_ok=True)
    failures = 0

    for shot in shots:
        target = frames_dir / f"shot_{shot.index:03d}.jpg"
        if _grab(media_path, shot.start, target):
            shot.keyframe = f"{FRAMES_DIR}/{target.name}"
        else:
            failures += 1

    second = 0.0
    while second < min(formats.hook_window_s(duration), duration):
        target = frames_dir / f"hook_{second:.0f}s.jpg"
        if not _grab(media_path, second, target):
            failures += 1
        second += 1.0

    if failures:
        warnings.append(
            f"keyframes: {failures} frame(s) could not be extracted"
        )


def _grab(media_path: Path, at: float, target: Path) -> bool:
    if target.exists():
        return True
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(0.0, at):.3f}", "-i", str(media_path),
        "-frames:v", "1", "-q:v", JPEG_QUALITY,
        "-y", str(target),
    ]
    try:
        res = proc.run(cmd, timeout=60)
    except proc.ToolMissing:
        return False
    return res.returncode == 0 and target.is_file()
