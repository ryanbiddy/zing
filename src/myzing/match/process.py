"""Own a worker and its descendants, without global Popen monkeypatches."""

from __future__ import annotations

import os
import queue
import signal
import subprocess
import threading
from contextlib import contextmanager


class Cancelled(KeyboardInterrupt):
    pass


def _stop_posix_tree(pid):
    # A nested Node helper may start its own session. Freeze the worker before
    # walking parentage, then freeze each discovered generation before killing.
    owned = {pid}
    try:
        os.killpg(pid, signal.SIGSTOP)
    except ProcessLookupError:
        pass
    for _ in range(16):
        try:
            table = subprocess.run(["ps", "-axo", "pid=,ppid="], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            break  # Always continue to group termination/reaping below.
        if table.returncode:
            break
        found = {int(row[0]) for line in table.stdout.splitlines()
                 if len(row := line.split()) == 2 and int(row[1]) in owned} - owned
        if not found:
            break
        for child in found:
            try:
                os.kill(child, signal.SIGSTOP)
            except ProcessLookupError:
                pass
        owned.update(found)
    for child in sorted(owned - {pid}, reverse=True):
        try:
            os.kill(child, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


class WindowsJob:
    """Kill-on-close Job Object; attach before the worker's start handshake."""

    def __init__(self):
        import ctypes as c
        from ctypes import wintypes as w

        class Limits(c.Structure):
            _fields_ = [("process_time", c.c_int64), ("job_time", c.c_int64), ("flags", w.DWORD),
                        ("min_working", c.c_size_t), ("max_working", c.c_size_t), ("processes", w.DWORD),
                        ("affinity", c.c_size_t), ("priority", w.DWORD), ("scheduling", w.DWORD)]

        class IO(c.Structure):
            _fields_ = [(name, c.c_uint64) for name in ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

        class Extended(c.Structure):
            _fields_ = [("basic", Limits), ("io", IO), ("process_memory", c.c_size_t),
                        ("job_memory", c.c_size_t), ("peak_process", c.c_size_t), ("peak_job", c.c_size_t)]

        self.kernel = c.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [c.c_void_p, w.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = w.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise c.WinError(c.get_last_error())
        limits = Extended()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, c.byref(limits), c.sizeof(limits)):
            error = c.WinError(c.get_last_error())
            self.close()
            raise error

    def attach(self, process):
        import ctypes
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def run_owned(command, payload, *, cancel=None, progress=None, on_started=None, env=None):
    """The command must wait for one stdin line before launching any children.

    Windows descendants inherit the job, even if they create process groups.
    POSIX descendants inherit the session/group used by local media producers.
    Cleanup runs on success too, so a producer cannot leave a background child.
    """
    job, process, reader = None, None, None
    lines = queue.Queue()
    try:
        options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        if os.name == "nt":
            job = WindowsJob()
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace", env=env, **options)
        if job:
            job.attach(process)
        if on_started:
            on_started(process.pid)

        def drain():
            for line in process.stdout:
                lines.put(line.rstrip())
        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        process.stdin.write(payload + "\n")
        process.stdin.flush()
        process.stdin.close()
        while True:
            if cancel and cancel.is_set():
                raise Cancelled("Match cancelled; owned processes stopped.")
            try:
                line = lines.get(timeout=.1)
                if progress:
                    progress(line)
            except queue.Empty:
                pass
            if process.poll() is not None and lines.empty():
                return process.returncode
    finally:
        # No PID-name scans, taskkill /IM, or unrelated process termination.
        if job:
            job.close()
        elif process and os.name != "nt":
            _stop_posix_tree(process.pid)
        if process:
            if process.poll() is None:
                process.kill()  # also handles a failed Windows attachment
            process.wait(timeout=10)
            if reader:
                reader.join(timeout=5)
            for stream in (process.stdin, process.stdout):
                if stream:
                    stream.close()


@contextmanager
def run_lock(root):
    """An OS-released lock survives cancellation without stale lock files."""
    directory = root / "match-job"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "run.lock").open("a+b") as stream:
        stream.seek(0)
        if stream.read(1) == b"":
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("A match already owns this output folder; poll match_status or wait.") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)
