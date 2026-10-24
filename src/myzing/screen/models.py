"""Versioned screen-demo contract; deliberately independent of schemas.py."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path


def number(value, label, lo=0, hi=3600):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f"{label} must be a finite number in [{lo}, {hi}].")
    return value


@dataclass
class Zoom:
    start: float
    end: float
    x: float
    y: float
    evidence: list[dict]
    confidence: float
    version: int = 1
    box: list[float] | None = None
    box_evidence: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError("Zoom must be a JSON object.")
        obj = cls(**value)
        if type(obj.version) is not int or obj.version != 1:
            raise ValueError("Unsupported screen zoom version.")
        number(obj.start, "zoom start")
        number(obj.end, "zoom end", obj.start + .001)
        for k in ("x", "y", "confidence"):
            number(getattr(obj, k), k, 0, 1)
        if obj.box is not None:
            if len(obj.box) != 4:
                raise ValueError("UI box must contain normalized x,y,width,height.")
            x, y, w, h = obj.box
            for v in (x, y, w, h):
                number(v, "UI box", 0, 1)
            if min(w, h) <= 0 or x+w > 1+1e-8 or y+h > 1+1e-8:
                raise ValueError("UI box must fit inside the source frame.")
        if not obj.evidence or any(e.get("kind") not in {"dwell", "click", "activity"} for e in obj.evidence):
            raise ValueError("Each zoom needs dwell, click or activity evidence.")
        return obj


@dataclass
class ScreenPlan:
    source: str
    sha256: str
    width: int
    height: int
    duration: float
    zooms: list[Zoom] = field(default_factory=list)
    idle: list[dict] = field(default_factory=list)
    clicks: list[dict] = field(default_factory=list)
    words: list[dict] = field(default_factory=list)
    sync: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    fps: int = 30
    idle_speed: float = 4
    max_zoom: float = 1.8
    ui_text_px: float = 24
    caption_preset: str = "clean"
    click_highlights: bool = False
    version: int = 1
    kind: str = "screen-demo"

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError("Screen plan must be a JSON object.")
        if value.get("version") != 1 or value.get("kind") != "screen-demo":
            raise ValueError("Unsupported screen-demo plan version; replan with zing plan screen.")
        obj = cls(**{**value, "zooms": [Zoom.from_dict(z) for z in value.get("zooms", [])]})
        number(obj.duration, "duration", .01)
        for key in ("width", "height"):
            number(getattr(obj, key), key, 16, 16384)
        number(obj.fps, "fps", 24, 60)
        number(obj.idle_speed, "idle_speed", 1, 8)
        number(obj.max_zoom, "max_zoom", 1, 2.5)
        number(obj.ui_text_px, "ui_text_px", 4, 256)
        if obj.caption_preset not in {"clean", "punch", "box", "none"}:
            raise ValueError("caption_preset: choose clean, punch, box or none.")
        if type(obj.click_highlights) is not bool:
            raise ValueError("click_highlights must be boolean.")
        if not isinstance(obj.source, str) or "://" in obj.source or obj.source.startswith(("//", "\\\\")):
            raise ValueError("Screen source must be a local media file.")
        if len(obj.sha256) != 64 or any(c not in "0123456789abcdef" for c in obj.sha256):
            raise ValueError("Screen source needs its SHA-256 fingerprint.")
        previous = 0
        for span in obj.idle:
            number(span["start"], "idle start", previous, obj.duration)
            number(span["end"], "idle end", span["start"]+.001, obj.duration)
            previous = span["end"]
        for zoom in obj.zooms:
            if zoom.end > obj.duration:
                raise ValueError("Zoom extends beyond source duration.")
        for event in obj.clicks:
            number(event["t"], "click time", 0, obj.duration)
            number(event["x"], "click x", 0, 1)
            number(event["y"], "click y", 0, 1)
        for word in obj.words:
            number(word["start"], "word start", 0, obj.duration)
            number(word["end"], "word end", word["start"]+.001, obj.duration)
            if not isinstance(word["text"], str) or not word["text"].strip():
                raise ValueError("Supplied caption words need nonempty text.")
        return obj


def read_cursor(path, *, offset=0):
    """Strict allowlist: reject key contents even in hand-authored input logs."""
    number(offset, "cursor offset", -3600, 3600)
    events, header, previous, stopped = [], None, -1, False
    allowed = {"start": {"type", "version", "t", "wall_time", "hz", "bounds", "coordinates", "sync"},
               "cursor": {"type", "t", "x", "y"}, "click": {"type", "t", "x", "y", "button"},
               "key": {"type", "t"}, "stop": {"type", "t", "samples"}}
    with Path(path).open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if line_no > 2_000_000 or len(line) > 8192:
                raise ValueError("Cursor log exceeds the one-hour recording budget.")
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"Cursor line {line_no} must be a JSON object.")
            kind = row.get("type")
            if kind not in allowed or set(row)-allowed[kind]:
                raise ValueError(f"Cursor line {line_no}: unexpected fields; key contents/codes are forbidden.")
            stamp = number(row.get("t"), "cursor time", previous)
            if stopped or (line_no == 1 and kind != "start"):
                raise ValueError("Cursor log needs one start marker first and no events after stop.")
            if kind == "start":
                if header is not None or row.get("version") != 1 or stamp != 0:
                    raise ValueError("Unsupported cursor start marker/version.")
                header = row
            elif kind == "stop":
                stopped = True
            else:
                if kind in {"cursor", "click"}:
                    number(row.get("x"), "cursor x", 0, 1)
                    number(row.get("y"), "cursor y", 0, 1)
                if kind == "click" and row.get("button") not in {"left", "right", "middle"}:
                    raise ValueError("Unknown mouse button.")
                events.append({**row, "t": stamp+offset})
            previous = stamp
    if header is None:
        raise ValueError("Empty cursor log; record it with zing record-cursor.")
    return header, events, stopped
