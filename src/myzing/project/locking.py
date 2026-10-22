"""Exclusive local scan lock. Stale locks are reported, never stolen."""

from __future__ import annotations

import json
import os
import socket
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .models import ProjectError

LOCK_NAME = ".project.lock"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # access denied/unknown: do not steal
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lock_description(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        pid = data["pid"]
        if type(pid) is not int or pid <= 0:
            raise ValueError("invalid pid")
        if data["host"] == socket.gethostname() and not _pid_alive(pid):
            return f"Stale project lock at {path} (owner PID {pid} is no longer running)."
        return f"Project is locked at {path} by PID {pid} on {data['host']}; a scan may be running."
    except (OSError, ValueError, KeyError, TypeError):
        return f"Project lock at {path} is unreadable or incomplete; its owner cannot be verified."


@contextmanager
def project_lock(root: Path):
    path = root / LOCK_NAME
    token = uuid4().hex
    try:
        handle = path.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise ProjectError(
            lock_description(path) + " Wait for the scan to finish. If its owner has stopped, "
            "remove only this lock file and rerun 'zing project scan'."
        ) from exc
    try:
        with handle:
            json.dump({"pid": os.getpid(), "host": socket.gethostname(),
                       "created_at": time.time(), "token": token}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        yield
    finally:
        # A manually replaced lock belongs to someone else.
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("token") == token:
                path.unlink()
        except (FileNotFoundError, ValueError):
            pass
