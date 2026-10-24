"""60 Hz polling. Platform key identifiers never cross the sampler boundary."""

from __future__ import annotations

import argparse
import ctypes
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


class WindowsSampler:
    def __init__(self):
        from ctypes import wintypes
        self.api = ctypes.windll.user32
        # Coordinates and capture bounds must use physical pixels on HiDPI.
        try:
            self.api.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except AttributeError:
            self.api.SetProcessDPIAware()
        self.point = wintypes.POINT()
        self.api.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        self.api.GetCursorPos.restype = wintypes.BOOL
        self.api.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.api.GetAsyncKeyState.restype = ctypes.c_short
        self.bounds = tuple(self.api.GetSystemMetrics(i) for i in (76, 77, 78, 79))
        self.previous_keys = set()

    def poll(self):
        if not self.api.GetCursorPos(ctypes.byref(self.point)):
            raise OSError("Cannot read the interactive desktop cursor. Run in a signed-in desktop session.")
        buttons = [name for code, name in ((1, "left"), (2, "right"), (4, "middle"))
                   if self.api.GetAsyncKeyState(code) & 0x8000]
        # Identifiers are transient polling state, never returned or serialized.
        keys = {code for code in range(8, 255) if self.api.GetAsyncKeyState(code) & 0x8000}
        pressed = bool(keys - self.previous_keys)
        self.previous_keys = keys
        return self.point.x, self.point.y, buttons, pressed


class MacSampler:
    def __init__(self):
        try:
            import Quartz
        except ImportError as exc:
            raise RuntimeError('macOS cursor recording needs: pip install "myzing[screen]"') from exc
        self.q = Quartz
        if hasattr(Quartz, "CGPreflightListenEventAccess") and not Quartz.CGPreflightListenEventAccess():
            raise RuntimeError("Allow Input Monitoring for this terminal in macOS System Settings, then retry.")
        b = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
        self.bounds = (b.origin.x, b.origin.y, b.size.width, b.size.height)
        self.previous_keys = set()

    def poll(self):
        q = self.q
        p = q.CGEventGetLocation(q.CGEventCreate(None))
        buttons = [name for i, name in enumerate(("left", "right", "middle"))
                   if q.CGEventSourceButtonState(q.kCGEventSourceStateCombinedSessionState, i)]
        keys = {i for i in range(128) if q.CGEventSourceKeyState(q.kCGEventSourceStateCombinedSessionState, i)}
        pressed = bool(keys - self.previous_keys)
        self.previous_keys = keys
        return p.x, p.y, buttons, pressed


def sampler():
    if sys.platform == "win32":
        return WindowsSampler()
    if sys.platform == "darwin":
        return MacSampler()
    raise RuntimeError("record-cursor supports Windows and macOS. Linux/Wayland is not supported; plan screen works without telemetry.")


def record(path, *, duration=None, countdown=3, region=None, source=None,
           clock=time.monotonic, sleep=time.sleep, output=print):
    if duration is not None and (not math.isfinite(duration) or duration <= 0):
        raise ValueError("--duration must be finite and greater than zero.")
    if not 0 <= countdown <= 30:
        raise ValueError("--countdown must be 0-30 seconds.")
    source = source or sampler()
    bounds = tuple(region or source.bounds)
    if len(bounds) != 4 or not all(math.isfinite(v) for v in bounds) or min(bounds[2:]) <= 0:
        raise ValueError("--region requires x,y,width,height in desktop coordinates, with positive size.")
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if output is print:
        output = lambda message: print(message, flush=True)
    # Exclusive creation protects existing recordings.
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        def emit(row):
            handle.write(json.dumps(row, allow_nan=False, separators=(",", ":")) + "\n")
        output("Local cursor positions, mouse clicks and anonymous key-press times only. No key contents, codes, text, windows or network.")
        try:
            for n in range(countdown, 0, -1):
                output(f"Start video at GO: {n}")
                sleep(1)
        except KeyboardInterrupt:
            # This exclusively-created file contains no session yet. Windows
            # requires closing it before unlinking it.
            handle.close()
            path.unlink()
            output("Countdown cancelled; removed the empty cursor log.")
            raise
        start = clock()
        emit({"type": "start", "version": 1, "t": 0, "wall_time": datetime.now(timezone.utc).isoformat(),
              "hz": 60, "bounds": list(bounds), "coordinates": "normalized-capture-region",
              "sync": "GO is t=0; --cursor-offset is the video time of GO. Creation-time sync is optional."})
        handle.flush()
        output("GO - telemetry t=0. Stop with Ctrl+C.")
        previous_buttons, ticks = set(), 0
        deadline = start
        try:
            while duration is None or clock() - start < duration:
                stamp = clock() - start
                x, y, buttons, pressed = source.poll()
                x, y = (x-bounds[0])/bounds[2], (y-bounds[1])/bounds[3]
                inside = 0 <= x <= 1 and 0 <= y <= 1
                # Outside-window positions are not clamped into fake edge dwells.
                if inside:
                    emit({"type": "cursor", "t": round(stamp, 6), "x": x, "y": y})
                    for button in sorted(set(buttons)-previous_buttons):
                        if button in ("left", "right", "middle"):
                            emit({"type": "click", "t": round(stamp, 6), "x": x, "y": y, "button": button})
                if pressed:
                    emit({"type": "key", "t": round(stamp, 6)})
                previous_buttons = set(buttons)
                ticks += 1
                if ticks % 60 == 0:
                    handle.flush()
                deadline += 1/60
                if deadline < clock():
                    deadline = clock()+1/60
                sleep(max(0, deadline-clock()))
        except KeyboardInterrupt:
            pass
        finally:
            emit({"type": "stop", "t": round(clock()-start, 6), "samples": ticks})
    return path


def run(argv):
    p = argparse.ArgumentParser(prog="zing record-cursor", description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--duration", type=float)
    p.add_argument("--countdown", type=int, default=3)
    p.add_argument("--region", help="recorded desktop rectangle: x,y,width,height; default is desktop (macOS main display)")
    a = p.parse_args(argv)
    try:
        region = tuple(map(float, a.region.split(","))) if a.region else None
        print(record(a.out, duration=a.duration, countdown=a.countdown, region=region))
    except KeyboardInterrupt:
        print("Cursor recording cancelled before GO.",file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"zing record-cursor: {exc}", file=sys.stderr)
        return 1
    return 0
