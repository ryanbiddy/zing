"""Shared, stdlib-only FFmpeg capability checks for render and doctor."""

from __future__ import annotations

import functools
import re
import shutil
import subprocess
from pathlib import Path


# Verified against the Homebrew formula and MacPorts Portfile on 2026-10-21.
# ffmpeg-full is keg-only: installing it alone does not change PATH.
LIBASS_REMEDY = (
    "On macOS, run `brew install ffmpeg-full` and "
    '`export PATH="$(brew --prefix ffmpeg-full)/bin:$PATH"`, '
    "or install MacPorts FFmpeg with `sudo port install ffmpeg` and put "
    "/opt/local/bin first on PATH. See https://formulae.brew.sh/formula/ffmpeg-full "
    "and https://ports.macports.org/port/ffmpeg/. On other platforms, install "
    "an FFmpeg build with libass. The HyperFrames caption sidecar does not need libass."
)


class FFmpegCapabilityError(RuntimeError):
    """The selected FFmpeg could not provide a required capability."""


@functools.lru_cache(maxsize=8)
def _filters_for_executable(executable: str) -> frozenset[str]:
    try:
        result = subprocess.run(
            [executable, "-hide_banner", "-filters"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise FFmpegCapabilityError(
            f"could not probe FFmpeg filters for {executable}: {exc}"
        ) from exc
    if result.returncode:
        raise FFmpegCapabilityError(
            f"could not probe FFmpeg filters for {executable}: "
            f"{result.stderr.strip()[-2000:] or 'unknown FFmpeg error'}"
        )
    return frozenset(
        # FFmpeg 6 prints three flag columns; recent builds print two.
        re.findall(r"^\s*[TSC.]+\s+(\w+)\s+\S+->\S+", result.stdout, re.MULTILINE)
    )


def caption_filter(ffmpeg: str = "ffmpeg") -> str:
    """Select an available ASS renderer, caching the probe per resolved binary."""
    executable = shutil.which(ffmpeg)
    if executable is None:
        raise FFmpegCapabilityError(f"ffmpeg executable not found: {ffmpeg}")
    executable = str(Path(executable).resolve())
    filters = _filters_for_executable(executable)
    for name in ("ass", "subtitles"):
        if name in filters:
            return name
    raise FFmpegCapabilityError(
        f"Caption burn-in needs libass: this FFmpeg build has no libass support "
        f"(missing ass/subtitles filters): {executable}. {LIBASS_REMEDY}"
    )
