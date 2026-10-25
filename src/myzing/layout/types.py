"""PF v1 contracts. Coordinates are normalized, times are video seconds.

The boxes include the full visible caption extent (outline/plate/animation).
These contracts deliberately do not depend on the composition schemas.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Any, ClassVar


def number(value: float, name: str, low: float = 0, high: float = math.inf) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be finite and between {low} and {high}")


def identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")


@dataclass(frozen=True, kw_only=True)
class Record:
    version: int = 1
    _nested: ClassVar[dict[str, tuple[type, bool]]] = {}

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != 1:
            raise ValueError(f"unsupported {type(self).__name__} version: {self.version}")

    def to_dict(self) -> dict[str, Any]:
        def encode(value):
            if is_dataclass(value):
                return {f.name: encode(getattr(value, f.name)) for f in fields(value)
                        if not (f.metadata.get("omit_default") and not getattr(value, f.name))}
            if isinstance(value, list):
                return [encode(v) for v in value]
            if isinstance(value, dict):
                return {k: encode(v) for k, v in value.items()}
            return value
        return encode(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        if not isinstance(data, dict):
            raise ValueError(f"{cls.__name__} must be a JSON object")
        values = dict(data)
        for name, (kind, many) in cls._nested.items():
            if name in values and values[name] is not None:
                if many and not isinstance(values[name], list):
                    raise ValueError(f"{name} must be a JSON array")
                values[name] = (
                    [kind.from_dict(item) for item in values[name]]
                    if many else kind.from_dict(values[name])
                )
        try:
            return cls(**values)
        except TypeError as exc:
            raise ValueError(f"invalid {cls.__name__}: {exc}") from exc


@dataclass(frozen=True)
class Box(Record):
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        super().__post_init__()
        for name in ("x", "y", "width", "height"):
            number(getattr(self, name), name, 0, 1)
        if self.width <= 0 or self.height <= 0:
            raise ValueError("box width and height must be positive")
        if self.right > 1 + 1e-12 or self.bottom > 1 + 1e-12:
            raise ValueError("box must fit inside the normalized frame")

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.width / 2, self.y + self.height / 2

    def pad(self, margin: float) -> Box:
        """Margin is a fraction of frame width/height, on each side."""
        number(margin, "face margin", 0, 0.5)
        return bounds(max(0, self.x - margin), max(0, self.y - margin),
                      min(1, self.right + margin), min(1, self.bottom + margin))


def bounds(left: float, top: float, right: float, bottom: float) -> Box:
    return Box(left, top, right - left, bottom - top)


def union(boxes: list[Box]) -> Box:
    return bounds(min(b.x for b in boxes), min(b.y for b in boxes),
                  max(b.right for b in boxes), max(b.bottom for b in boxes))


def lerp(a: Box, b: Box, ratio: float) -> Box:
    return Box(*(getattr(a, n) * (1 - ratio) + getattr(b, n) * ratio
                 for n in ("x", "y", "width", "height")))


@dataclass(frozen=True)
class Keyframe(Record):
    time: float
    box: Box
    _nested: ClassVar = {"box": (Box, False)}

    def __post_init__(self) -> None:
        super().__post_init__()
        number(self.time, "keyframe time")


def validate_path(path: list[Keyframe]) -> None:
    if not path or any(a.time >= b.time for a, b in zip(path, path[1:])):
        raise ValueError("keyframes must be nonempty and strictly increasing in time")


def box_at(path: list[Keyframe], time: float) -> Box:
    """Piecewise linear interpolation; hold the endpoints."""
    if time <= path[0].time:
        return path[0].box
    for a, b in zip(path, path[1:]):
        if time <= b.time:
            return lerp(a.box, b.box, (time - a.time) / (b.time - a.time))
    return path[-1].box


@dataclass(frozen=True)
class Detection(Record):
    box: Box
    confidence: float
    appearance: list[float] = field(default_factory=list, metadata={"omit_default": True})
    class_name: str = field(default="", metadata={"omit_default": True})
    detector: str = field(default="", metadata={"omit_default": True})
    _nested: ClassVar = {"box": (Box, False)}

    def __post_init__(self) -> None:
        super().__post_init__()
        number(self.confidence, "confidence", 0, 1)
        for value in self.appearance:
            number(value, "appearance histogram", 0, 1)


@dataclass(frozen=True)
class TrackObservation(Record):
    time: float
    box: Box
    appearance: list[float] = field(default_factory=list)
    confidence: float | None = field(default=None, metadata={"omit_default": True})
    class_name: str = field(default="", metadata={"omit_default": True})
    detector: str = field(default="", metadata={"omit_default": True})
    _nested: ClassVar = {"box": (Box, False)}

    def __post_init__(self):
        super().__post_init__()
        number(self.time, "observation time")
        if self.confidence is not None:
            number(self.confidence, "observation confidence", 0, 1)
        for value in self.appearance:
            number(value, "appearance histogram", 0, 1)


@dataclass(frozen=True)
class FrameDetections(Record):
    time: float
    detections: list[Detection]
    _nested: ClassVar = {"detections": (Detection, True)}

    def __post_init__(self) -> None:
        super().__post_init__()
        number(self.time, "sample time")


@dataclass(frozen=True)
class FaceTrack(Record):
    id: str
    keyframes: list[Keyframe]
    confidence: float = 1.0
    warnings: list[str] = field(default_factory=list)
    observations: list[TrackObservation] = field(default_factory=list, metadata={"omit_default": True})
    stitching: list[dict] = field(default_factory=list, metadata={"omit_default": True})
    padding: float | None = None
    _nested: ClassVar = {"keyframes": (Keyframe, True), "observations": (TrackObservation, True)}

    def __post_init__(self) -> None:
        super().__post_init__()
        identifier(self.id, "track id")
        validate_path(self.keyframes)
        number(self.confidence, "confidence", 0, 1)
        if self.padding is not None:
            number(self.padding, "track padding", 0, .5)


ZONES = {
    "top": (0.5, 0.12), "upper-third": (0.5, 1 / 3),
    "center": (0.5, 0.5), "lower-third": (0.5, 2 / 3),
    "bottom": (0.5, 0.88), "left": (0.2, 0.5), "right": (0.8, 0.5),
}


@dataclass(frozen=True)
class CaptionEvent(Record):
    id: str
    start: float
    end: float
    width: float
    height: float
    preferred_anchor: str | list[float] = "lower-third"
    path: list[Keyframe] = field(default_factory=list)
    _nested: ClassVar = {"path": (Keyframe, True)}

    def __post_init__(self) -> None:
        super().__post_init__()
        identifier(self.id, "event id")
        number(self.start, "start")
        number(self.end, "end")
        if self.end <= self.start:
            raise ValueError("caption end must be after start")
        number(self.width, "caption width", 1e-6, 1)
        number(self.height, "caption height", 1e-6, 1)
        if isinstance(self.preferred_anchor, str):
            if self.preferred_anchor not in ZONES:
                raise ValueError(f"unknown preferred anchor: {self.preferred_anchor}")
        else:
            if not isinstance(self.preferred_anchor, list) or len(self.preferred_anchor) != 2:
                raise ValueError("preferred_anchor must be a zone name or [center_x, center_y]")
            for value in self.preferred_anchor:
                number(value, "anchor coordinate", 0, 1)
        if self.path:
            validate_path(self.path)
            if self.path[0].time != self.start or self.path[-1].time != self.end:
                raise ValueError("explicit path must cover the exact event start and end")
            if len(self.path) > 16:
                raise ValueError("explicit path is limited to 16 keyframes")
            if any(abs(k.box.width - self.width) > 1e-9 or
                   abs(k.box.height - self.height) > 1e-9 for k in self.path):
                raise ValueError("explicit path boxes must match the event width and height")


@dataclass(frozen=True)
class Mask(Record):
    name: str
    box: Box
    _nested: ClassVar = {"box": (Box, False)}

    def __post_init__(self) -> None:
        super().__post_init__()
        identifier(self.name, "mask name")


@dataclass(frozen=True)
class OverlapCheck(Record):
    safe: bool
    face_ids: list[str] = field(default_factory=list)
    mask_names: list[str] = field(default_factory=list)
    method: str = "continuous-piecewise-linear"
    scope: str = "supplied face tracks and masks; not proof of detector recall"

    def __post_init__(self) -> None:
        super().__post_init__()
        if type(self.safe) is not bool or self.safe != (not self.face_ids and not self.mask_names):
            raise ValueError("overlap safe flag must agree with collisions")


@dataclass(frozen=True)
class EventLayout(Record):
    id: str
    start: float
    end: float
    reason: str
    overlap: OverlapCheck
    box: Box | None = None
    path: list[Keyframe] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fallback: str | None = None
    scale: float = 1.0
    _nested: ClassVar = {"box": (Box, False), "path": (Keyframe, True),
                        "overlap": (OverlapCheck, False)}

    def __post_init__(self) -> None:
        super().__post_init__()
        identifier(self.id, "event id")
        number(self.start, "start")
        number(self.end, "end")
        number(self.scale, "scale", 1e-6, 1)
        if self.end <= self.start or (self.box is None) == (not self.path):
            raise ValueError("layout needs a positive interval and exactly one box or path")
        if self.path:
            validate_path(self.path)
            if self.path[0].time != self.start or self.path[-1].time != self.end:
                raise ValueError("layout path must cover the event interval")
        if not self.overlap.safe and not self.warnings:
            raise ValueError("unsafe layout must carry a warning")

    def as_path(self) -> list[Keyframe]:
        return self.path or [Keyframe(self.start, self.box), Keyframe(self.end, self.box)]


@dataclass(frozen=True)
class LayoutPlan(Record):
    events: list[EventLayout]
    tracks: list[FaceTrack]
    masks: list[Mask]
    platform: str = "none"
    warnings: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    _nested: ClassVar = {"events": (EventLayout, True), "tracks": (FaceTrack, True),
                        "masks": (Mask, True)}
