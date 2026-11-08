"""Subprocess wrapper for external tools (ffmpeg, ffprobe, yt-dlp).

One choke point so tests mock a single function and every call gets the
same Windows-safe text handling (UTF-8 with replacement — console tools
emit whatever they like, and cp1252 decode errors must never kill a study).
"""

from __future__ import annotations

import os
import subprocess
import threading
from contextlib import contextmanager


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
    try:
        pipes = dict(stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                     text=True, encoding="utf-8", errors="replace")
        if timeout is None:
            return subprocess.run(cmd, **pipes)
        with _process(cmd, **pipes) as (process, stop):
            stdout, stderr = process.communicate(timeout=timeout)
            return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)
    except FileNotFoundError as e:
        raise ToolMissing(cmd[0]) from e
    except subprocess.TimeoutExpired as e:
        raise Timeout(cmd, timeout) from e


def _resume(process):
    import ctypes
    resume = ctypes.WinDLL("ntdll").NtResumeProcess
    resume.argtypes, resume.restype = [ctypes.c_void_p], ctypes.c_long
    status = resume(int(process._handle))
    if status:
        raise OSError(f"Could not resume {process.args[0]} (NTSTATUS {status:#x}).")


@contextmanager
def _process(cmd, **pipes):
    from myzing.match.process import WindowsJob, _stop_posix_tree

    process, job, stopped = None, None, False
    lock = threading.Lock()

    def stop():
        nonlocal stopped
        with lock:
            if stopped:
                return
            stopped = True
            try:
                if job:
                    job.close()
                elif process:
                    _stop_posix_tree(process.pid)
            finally:
                if process:
                    if process.poll() is None:
                        process.kill()
                    process.wait()

    try:
        options = {"start_new_session": True}
        if os.name == "nt":
            options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP | 0x4}  # Start suspended until attached.
            job = WindowsJob()
        try:
            process = subprocess.Popen(cmd, **pipes, **options)
        except FileNotFoundError as exc:
            raise ToolMissing(cmd[0]) from exc
        if job:
            job.attach(process)
            _resume(process)
        yield process, stop
    finally:
        try:
            if job or (process and process.poll() is None):
                stop()  # a POSIX tool that already exited needs no tree walk
        finally:
            if process:
                for stream in (process.stdout, process.stderr):
                    if stream:
                        stream.close()


def tail(text: str, lines: int = 5) -> str:
    """Last few lines of tool output — enough context for an error message
    without dumping a full log at the user."""
    kept = [ln for ln in text.strip().splitlines() if ln.strip()]
    return "\n".join(kept[-lines:])
