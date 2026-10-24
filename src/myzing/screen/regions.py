"""Local pixel evidence for whole UI regions. No OCR, accessibility API or model.

Flat-color connected components identify enclosing panels/buttons. These are
visual bounds, not recovered DOM elements. Unknown bounds fall back to the
whole source, never an arbitrary rectangle around the pointer.
"""

from __future__ import annotations

import math
import subprocess

from .analysis import input_args


def union(boxes):
    x = min(b[0] for b in boxes)
    y = min(b[1] for b in boxes)
    return [x, y, max(b[0]+b[2] for b in boxes)-x,
            max(b[1]+b[3] for b in boxes)-y]


def enclosing_region(rgb, width, height, point):
    """Prefer an enclosing panel over its smaller button or text fragment."""
    colors = [(rgb[i]//16, rgb[i+1]//16, rgb[i+2]//16)
              for i in range(0, len(rgb), 3)]
    visited = bytearray(width*height)
    px, py = point[0]*width, point[1]*height
    candidates = []
    for seed in range(width*height):
        if visited[seed]:
            continue
        color = colors[seed]
        stack = [seed]
        visited[seed] = 1
        left = right = seed % width
        top = bottom = seed // width
        count = 0
        while stack:
            i = stack.pop()
            x, y = i % width, i // width
            count += 1
            left, right = min(left, x), max(right, x)
            top, bottom = min(top, y), max(bottom, y)
            for j in (i-1 if x else -1, i+1 if x+1 < width else -1,
                      i-width if y else -1, i+width if y+1 < height else -1):
                if j >= 0 and not visited[j] and colors[j] == color:
                    visited[j] = 1
                    stack.append(j)
        area = (right-left+1)*(bottom-top+1)
        if (left <= px <= right+1 and top <= py <= bottom+1
                and .002*width*height <= area <= .60*width*height
                and right-left >= 6 and bottom-top >= 4 and count/area >= .45):
            # Include antialiased borders and the low-resolution probe error.
            x, y = max(0, left-2)/width, max(0, top-2)/height
            candidates.append([x, y, min(width, right+3)/width-x,
                               min(height, bottom+3)/height-y])
    return max(candidates, key=lambda b: b[2]*b[3], default=None)


def attach_regions(path, zooms, duration, ffmpeg="ffmpeg"):
    """Decode once, inspect event frames, retain the union over each hold.

    Sampling the start/action/end protects widgets that expand after a click.
    Processing is bounded to three small RGB frames per planned focus scene.
    """
    if not zooms:
        return
    width, height, rate = 320, 180, 4
    wanted = {}
    for i, zoom in enumerate(zooms):
        action = max(zoom.evidence, key=lambda e: e.get("confidence", 0))["t"]
        for t in (zoom.start, action+.25, min(zoom.end, duration-.05)):
            index = min(max(0, math.floor((duration-.05)*rate)), max(0, round(t*rate)))
            wanted.setdefault(index, set()).add(i)
    found = {i: [] for i in range(len(zooms))}
    proc = subprocess.Popen([ffmpeg, "-v", "error", "-nostdin", *input_args(path),
                             "-t", str(duration), "-vf", f"fps={rate},scale={width}:{height}",
                             "-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        for index in range(math.ceil(duration*rate)+3):
            frame = proc.stdout.read(width*height*3)
            if not frame:
                break
            if len(frame) != width*height*3:
                raise RuntimeError("Incomplete UI-region frame.")
            for i in wanted.get(index, ()):
                box = enclosing_region(frame, width, height, (zooms[i].x, zooms[i].y))
                if box:
                    found[i].append(box)
        if proc.wait(timeout=15):
            raise RuntimeError("FFmpeg could not decode UI-region frames.")
    finally:
        proc.stdout.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    for i, zoom in enumerate(zooms):
        boxes = found[i]
        kind = "enclosing-flat-color-region"
        if not boxes:
            boxes = [e["box"] for e in zoom.evidence if e.get("box")]
            kind = "frame-difference-region"
        if not boxes:
            # A click without a detectable enclosing element is not evidence
            # that nearby text can safely be cropped away.
            boxes = [[0., 0., 1., 1.]]
            kind = "unknown-full-source"
        zoom.box = union(boxes)
        zoom.box_evidence = {"kind": kind, "samples": len(found[i]),
                             "confidence": .65 if found[i] else .45 if kind != "unknown-full-source" else 0.}
