"""Versioned crop geometry in display-oriented, square-pixel source coordinates."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from myzing.contracts import Record, bounded, nonempty
from .speakers import SpeakerTurn


@dataclass
class CropAssessment(Record):
    mode: Literal["fit", "fill", "reframe", "zoomfill", "blurfill"]
    sharp_height_share: float
    sharp_area_share: float
    enlargement: float
    retained_area: float
    subject_coverage: float
    headroom_safe: bool
    evidence_gaps: bool
    reasons: list[str] = field(default_factory=list)
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        for name in ("sharp_height_share", "sharp_area_share", "retained_area", "subject_coverage"):
            bounded(getattr(self, name), 0, 1, name)
        if self.enlargement <= 0:
            raise ValueError("enlargement must be positive")


@dataclass
class CropBounds(Record):
    x: float
    y: float
    width: float
    height: float
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        if min(self.x, self.y) < 0 or min(self.width, self.height) <= 0:
            raise ValueError("crop bounds need nonnegative origins and positive dimensions")


@dataclass
class CropKeyframe(Record):
    time: float  # Seconds from this clip's first output frame, after speed mapping.
    center_x: float
    center_y: float
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        if min(self.time, self.center_x, self.center_y) < 0:
            raise ValueError("crop keyframe time and center must be nonnegative")


@dataclass
class Framing(Record):
    mode: Literal["fit", "fill", "reframe", "zoomfill", "blurfill"]
    source_width: int
    source_height: int
    bounds: CropBounds
    width: int
    height: int
    center_x: float
    center_y: float
    keyframes: list[CropKeyframe] = field(default_factory=list)
    interpolation: Literal["smoothstep"] = "smoothstep"
    max_velocity: float = 240.0  # Source pixels / output second; Euclidean peak.
    max_upscale: float = 2.5  # Linear scale; matches the auto policy default. Exceeding it warns.
    confidence: float = 0.0
    method: str = "user-specified"
    warnings: list[str] = field(default_factory=list)
    assessments: list[CropAssessment] = field(default_factory=list, metadata={"omit_default": True})
    speaker_turns: list[SpeakerTurn] = field(default_factory=list, metadata={"omit_default": True})
    picture: dict = field(default_factory=dict, metadata={"omit_default": True})
    # Blurfill/zoomfill sharp-picture top as a share of output height. None
    # centers it; caption planning raises it to open a lower caption band.
    foreground_top: float | None = field(default=None, metadata={"omit_default": True})
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        if min(self.source_width, self.source_height, self.width, self.height) <= 0:
            raise ValueError("framing dimensions must be positive")
        bounded(self.confidence, 0, 1, "framing confidence")
        if self.max_velocity <= 0 or self.max_upscale < 1:
            raise ValueError("framing needs positive max_velocity and max_upscale >= 1")
        nonempty(self.method, "framing method")
        b = self.bounds
        b.__post_init__()
        if b.x + b.width > self.source_width or b.y + b.height > self.source_height:
            raise ValueError("crop bounds exceed source dimensions")
        for x, y in [(self.center_x, self.center_y), *[(k.center_x, k.center_y) for k in self.keyframes]]:
            if (x - self.width / 2 < b.x - 1e-6 or y - self.height / 2 < b.y - 1e-6
                    or x + self.width / 2 > b.x + b.width + 1e-6
                    or y + self.height / 2 > b.y + b.height + 1e-6):
                raise ValueError("crop window exceeds stated bounds/source dimensions")
        if self.mode in ("reframe", "zoomfill"):
            if not self.keyframes or self.keyframes[0].time != 0:
                raise ValueError("reframe keyframes must start at clip-local time zero")
            if len(self.keyframes) > 256:
                raise ValueError("reframe supports at most 256 keyframes; reduce the sampling rate")
            first = self.keyframes[0]
            if (first.center_x, first.center_y) != (self.center_x, self.center_y):
                raise ValueError("reframe center must match its first keyframe")
            for a, c in zip(self.keyframes, self.keyframes[1:]):
                dt = c.time - a.time
                if dt <= 0:
                    raise ValueError("reframe keyframes must be strictly increasing")
                # Smoothstep has peak derivative 1.5; all intermediate windows
                # lie on the segment and therefore inside the validated bounds.
                speed = 1.5 * math.hypot(c.center_x - a.center_x, c.center_y - a.center_y) / dt
                if speed > self.max_velocity + 1e-6:
                    raise ValueError("reframe keyframes exceed max_velocity")
        elif self.keyframes:
            raise ValueError("only reframe and zoomfill accept keyframes")
        if any(a.end > b.start for a, b in zip(self.speaker_turns, self.speaker_turns[1:])):
            raise ValueError("speaker turns must be ordered without overlap")
        if self.foreground_top is not None:
            bounded(self.foreground_top, 0, 1, "framing foreground_top")
            if self.mode not in ("blurfill", "zoomfill"):
                raise ValueError("foreground_top applies to blurfill and zoomfill only")

    def center_at(self, time: float) -> tuple[float, float]:
        if not self.keyframes:
            return self.center_x, self.center_y
        for a, b in zip(self.keyframes, self.keyframes[1:]):
            if time <= b.time:
                u = max(0, min(1, (time - a.time) / (b.time - a.time)))
                u = u * u * (3 - 2 * u)
                return (a.center_x + (b.center_x - a.center_x) * u,
                        a.center_y + (b.center_y - a.center_y) * u)
        return self.keyframes[-1].center_x, self.keyframes[-1].center_y

    def validate_output(self, width: int, height: int, duration: float) -> None:
        self.__post_init__()
        if self.mode not in ("fit", "blurfill", "zoomfill") and self.width * height != self.height * width:
            raise ValueError("crop aspect must equal the output aspect")
        if self.mode == "zoomfill" and self.width * height < self.height * width:
            raise ValueError("zoomfill crop must fit the output height when scaled to output width")
        if self.keyframes and self.keyframes[-1].time > duration + 1e-6:
            raise ValueError("reframe keyframe exceeds the clip duration")
        if self.speaker_turns and self.speaker_turns[-1].end > duration + 1e-6:
            raise ValueError("speaker turn exceeds the clip duration")

    @property
    def fit_source(self) -> tuple[float, float]:
        """Source size a fit/blurfill foreground scales: the live picture after a
        picture crop, else the whole source (bounds then only describe it)."""
        return (self.bounds.width, self.bounds.height) if self.picture else (self.source_width, self.source_height)

    def foreground_size(self, width: int, height: int) -> tuple[int, int]:
        """Even sharp-picture size in output pixels for fit, blurfill and zoomfill.

        Blurfill and zoomfill scale their foreground to exactly this size, so
        planning, caption bands and rendered pixels agree on every FFmpeg
        version, and the vertical scale never exceeds the horizontal
        enlargement. Fit keeps the legacy graph (FFmpeg can round one row
        pair larger), so this is a conservative fit content box.
        """
        sw, sh = ((self.width, self.height) if self.mode == "zoomfill" else self.fit_source)
        scale = min(width / sw, height / sh)
        return max(2, math.floor(sw * scale / 2) * 2), max(2, math.floor(sh * scale / 2) * 2)

    def foreground_origin(self, width: int, height: int) -> tuple[int, int]:
        """Top-left of the blurfill/zoomfill sharp picture in output pixels.

        Centered (or at foreground_top), then rounded down to even: FFmpeg's
        4:2:0 overlay does that to any odd position, so the graph receives
        this exact origin.
        """
        w, h = self.foreground_size(width, height)
        y = (height - h) // 2 if self.foreground_top is None else min(height - h, round(self.foreground_top * height))
        return (width - w) // 2 // 2 * 2, max(0, y) // 2 * 2

    def upscale_warning(self, width: int, height: int) -> list[str]:
        scale = (min(width / self.fit_source[0], height / self.fit_source[1]) if self.mode in ("fit", "blurfill")
                 else width / self.width if self.mode == "zoomfill"
                 else max(width / self.width, height / self.height))
        return ([f"Framing upscale {scale:.3f}x exceeds stated {self.max_upscale:g}x limit; source detail cannot be recovered."]
                if scale > self.max_upscale + 1e-9 else [])
