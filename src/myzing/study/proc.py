"""Subprocess wrapper for external tools (ffmpeg, ffprobe, yt-dlp).

One choke point so tests mock a single function and every call gets the
same Windows-safe text handling (UTF-8 with replacement — console tools
emit whatever they like, and cp1252 decode errors must never kill a study).
"""

from __future__ import annotations

import os
import subprocess


class MediaError(RuntimeError):
    """A study step failed in a way the user must hear about honestly."""


class ToolMissing(MediaError):
    """A required external tool is not installed / not on PATH."""

    def __init__(self, tool: str) -> None:
        super().__init__(
            f"'{tool}' was not found on PATH - it is required for this step. "
            f"Run 'zing doctor' for setup guidance."
        )
        self.tool = tool


class Timeout(MediaError, subprocess.TimeoutExpired):
    """A tool ran past its time limit; callers may catch either base."""

    def __init__(self, cmd, timeout: float) -> None:
        subprocess.TimeoutExpired.__init__(self, cmd, timeout)

    def __str__(self) -> str:
        return f"{self.cmd[0]} timed out after {self.timeout:g} seconds (TimeoutExpired)"


def run(cmd: list[str], timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    """Run a tool, capturing text output. Raises ToolMissing when the binary
    is absent; returns the completed process otherwise (caller checks
    returncode so it can attach step-specific context)."""
    process, job, finished = None, None, False
    try:
        pipes = dict(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                     text=True, encoding="utf-8", errors="replace")
        if timeout is None:
            return subprocess.run(cmd, **pipes)
        from myzing.match.process import WindowsJob, _stop_posix_tree
        options = {"start_new_session": True}
        if os.name == "nt":
            options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP | 0x4}  # Start suspended until attached.
            job = WindowsJob()
        process = subprocess.Popen(cmd, **pipes, **options)
        if job:
            job.attach(process)
            import ctypes
            resume = ctypes.WinDLL("ntdll").NtResumeProcess
            resume.argtypes, resume.restype = [ctypes.c_void_p], ctypes.c_long
            status = resume(int(process._handle))
            if status:
                raise OSError(f"Could not resume {cmd[0]} (NTSTATUS {status:#x}).")
        stdout, stderr = process.communicate(timeout=timeout)
        finished = True
        return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)
    except FileNotFoundError as e:
        raise ToolMissing(cmd[0]) from e
    except subprocess.TimeoutExpired as e:
        raise Timeout(cmd, timeout) from e
    finally:
        if job:
            job.close()
        elif process and not finished:
            _stop_posix_tree(process.pid)
        if process:
            if process.poll() is None:
                process.kill()
            process.wait()
            process.stdout.close()
            process.stderr.close()


def tail(text: str, lines: int = 5) -> str:
    """Last few lines of tool output — enough context for an error message
    without dumping a full log at the user."""
    kept = [ln for ln in text.strip().splitlines() if ln.strip()]
    return "\n".join(kept[-lines:])
