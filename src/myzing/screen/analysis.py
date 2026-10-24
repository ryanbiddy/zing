"""FFmpeg-only screen measurements. No models, OCR or network."""

from __future__ import annotations

import re
import subprocess
import shutil

from myzing.project.probe import MEDIA_DEMUXERS


def input_args(path):
    return ["-protocol_whitelist", "file,pipe", "-format_whitelist", MEDIA_DEMUXERS, "-i", str(path)]


def parse_freezes(text, duration):
    spans, start = [], None
    for kind, stamp in re.findall(r"freeze_(start|end):\s*([\d.]+)", text):
        stamp = min(duration, float(stamp))
        if kind == "start":
            start = stamp
        elif start is not None:
            if stamp > start:
                spans.append({"start": start, "end": stamp})
            start = None
    if start is not None and start < duration:
        spans.append({"start": start, "end": duration})
    return spans


def freezes(path, duration, ffmpeg="ffmpeg"):
    if shutil.which(ffmpeg) is None:
        raise RuntimeError("Screen planning requires FFmpeg and ffprobe on PATH; install FFmpeg, then retry.")
    result = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", *input_args(path),
                             "-vf", "freezedetect=n=-70dB:d=1.8", "-an", "-f", "null", "-"],
                            capture_output=True, timeout=max(60, duration*4))
    if result.returncode:
        raise RuntimeError("Screen idle analysis failed: " + result.stderr.decode(errors="replace")[-1500:])
    return parse_freezes(result.stderr.decode(errors="replace"), duration)


def activity(path, duration, ffmpeg="ffmpeg"):
    """4fps luma differences; largest connected changed tile region, confidence .45.

    Isolated cursor-sized changes and whole-screen changes are rejected. This is
    UI activity evidence, never cursor or text recognition.
    """
    w, h, rate, tile = 192, 108, 4, 6
    proc = subprocess.Popen([ffmpeg, "-v", "error", "-nostdin", *input_args(path),
                             "-t", str(duration), "-vf", f"fps={rate},scale={w}:{h}", "-an", "-pix_fmt", "gray", "-f", "rawvideo", "pipe:1"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    previous, events, index = None, [], 0
    try:
        while index <= duration*rate+2:
            frame = proc.stdout.read(w*h)
            if not frame:
                break
            if len(frame) != w*h:
                raise RuntimeError("Incomplete screen activity frame.")
            if previous is not None:
                counts = {}
                for i, (a,b) in enumerate(zip(frame, previous)):
                    if abs(a-b) > 18:
                        cell = (i%w//tile, i//w//tile)
                        counts[cell] = counts.get(cell, 0)+1
                cells = {c for c,n in counts.items() if n >= 4}
                components = []
                while cells:
                    stack, group = [cells.pop()], []
                    while stack:
                        x,y = stack.pop()
                        group.append((x,y))
                        for neighbor in ((x-1,y),(x+1,y),(x,y-1),(x,y+1)):
                            if neighbor in cells:
                                cells.remove(neighbor)
                                stack.append(neighbor)
                    components.append(group)
                region = max(components, key=len, default=[])
                if 3 <= len(region) < (w*h/tile**2)*.6:
                    x = sum((c[0]+.5)*tile/w for c in region)/len(region)
                    y = sum((c[1]+.5)*tile/h for c in region)/len(region)
                    if not events or index/rate-events[-1]["t"] >= .75:
                        events.append({"kind": "activity", "t": index/rate, "x": x, "y": y,
                                       "confidence": .45, "changed_tiles": len(region)})
            previous, index = frame, index+1
        if proc.wait(timeout=15):
            raise RuntimeError("FFmpeg could not decode screen activity frames.")
    finally:
        proc.stdout.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    return events
