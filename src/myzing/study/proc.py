"""Subprocess wrapper for external tools (ffmpeg, ffprobe, yt-dlp).

One choke point so tests mock a single function and every call gets the
same Windows-safe text handling (UTF-8 with replacement — console tools
emit whatever they like, and cp1252 decode errors must never kill a study).
"""

from __future__ import annotations

import subprocess


class MediaError(RuntimeError):
    """A study step failed in a way the user must hear about honestly."""


class ToolMissing(MediaError):
    """A required external tool is not installed / not on PATH."""

    def __init__(self, tool: str) -> None:
        super().__init__(
            f"'{tool}' was not found on PATH — it is required for this step. "
            f"Run 'zing doctor' for setup guidance."
        )
        self.tool = tool


def run(cmd: list[str], timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    """Run a tool, capturing text output. Raises ToolMissing when the binary
    is absent; returns the completed process otherwise (caller checks
    returncode so it can attach step-specific context)."""
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError as e:
        raise ToolMissing(cmd[0]) from e


def tail(text: str, lines: int = 5) -> str:
    """Last few lines of tool output — enough context for an error message
    without dumping a full log at the user."""
    kept = [ln for ln in text.strip().splitlines() if ln.strip()]
    return "\n".join(kept[-lines:])
