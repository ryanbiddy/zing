"""Version 1 audio observations, independent of the composition schemas.

Confidence values are heuristic evidence scores, not calibrated probabilities.
All times refer to decoded audio, starting at zero, in seconds.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, TypeVar

T = TypeVar("T", bound="Record")


class Record:
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls: type[T], data: dict[str, Any]) -> T:
        if data.get("version") != 1:
            raise ValueError(f"unsupported {cls.__name__} version: {data.get('version')!r}")
        return cls(**data)

    def __post_init__(self) -> None:
        if self.version != 1:
            raise ValueError(f"unsupported {type(self).__name__} version: {self.version}")
        for name, value in vars(self).items():
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"{name} must be finite; use None for unknown measurements")
            if "confidence" in name and not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass
class Tempo(Record):
    status: str = "unknown"  # steady | none | unknown
    bpm: float | None = None
    confidence: float = 0.0
    evidence: str = "insufficient evidence"
    downbeat_status: str = "unknown"
    downbeats: list[float] = field(default_factory=list)
    version: int = 1

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.status not in {"steady", "none", "unknown"}:
            raise ValueError("invalid tempo status")
        if (self.status == "steady") != (self.bpm is not None):
            raise ValueError("only a steady tempo can have a BPM estimate")
        if self.bpm is not None and self.bpm <= 0:
            raise ValueError("BPM must be positive")


@dataclass
class Onset(Record):
    time: float
    strength: float  # normalized positive spectral flux, relative to this file
    version: int = 1


@dataclass
class Segment(Record):
    start: float
    end: float
    label: str  # speech | music | silence | uncertain
    confidence: float
    evidence: str
    version: int = 1

    def __post_init__(self) -> None:
        super().__post_init__()
        if not 0 <= self.start < self.end:
            raise ValueError("segments require 0 <= start < end")
        if self.label not in {"speech", "music", "silence", "uncertain"}:
            raise ValueError("invalid audio segment label")


@dataclass
class Loudness(Record):
    integrated_lufs: float | None
    loudness_range_lu: float | None
    true_peak_dbtp: float | None
    method: str = "ffmpeg ebur128 peak=true; original channels; dualmono=false"
    version: int = 1


@dataclass
class GainRecommendation(Record):
    gain_db: float
    target_lufs: float
    target_dbtp: float
    limiter_required: bool
    limiter_ceiling_dbtp: float
    limiter_attack_ms: float
    limiter_release_ms: float
    limiter_sample_rate: int
    ffmpeg_filter: str
    predicted_lufs: float | None
    warnings: list[str] = field(default_factory=list)
    version: int = 1


@dataclass
class AudioMap(Record):
    source: str
    duration_seconds: float
    sample_rate: int
    max_seconds: float
    truncated: bool
    tempo: Tempo
    beats: list[float]
    onsets: list[Onset]
    segments: list[Segment]
    loudness: Loudness
    warnings: list[str] = field(default_factory=list)
    tool_versions: dict[str, str] = field(default_factory=dict)
    breakdown_source: str | None = None
    version: int = 1

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AudioMap:
        data = dict(data)
        if data.get("version") != 1:
            raise ValueError(f"unsupported AudioMap version: {data.get('version')!r}")
        data["tempo"] = Tempo.from_dict(data["tempo"])
        data["loudness"] = Loudness.from_dict(data["loudness"])
        data["onsets"] = [Onset.from_dict(item) for item in data["onsets"]]
        data["segments"] = [Segment.from_dict(item) for item in data["segments"]]
        return cls(**data)
