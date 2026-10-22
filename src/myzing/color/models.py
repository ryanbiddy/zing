"""Versioned standalone contracts; no changes to the composition schema."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any


class Contract:
    def __post_init__(self):
        if type(self.version) is not int or self.version != 1:
            raise ValueError(f"unsupported {type(self).__name__} version: {self.version}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]):
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError(f"unsupported or missing {cls.__name__} version")
        return cls(**data)


@dataclass
class Statistics(Contract):
    luma_percentiles: list[float]  # encoded Rec.709 Y', p1/5/25/50/75/95/99
    lightness_percentiles: list[float]  # CIELAB L*, same percentiles
    contrast: float  # L* p95 - p5
    ab_mean: list[float]
    ab_spread: list[float]
    ab_percentiles: list[list[float]]
    saturation: list[float]  # CIELAB chroma p5/25/50/75/95
    tone_ab: list[list[float]]  # mean a*/b* in L* quartiles
    palette: list[list[float]]  # median-cut CIELAB centroids
    palette_weights: list[float]
    clipping: dict[str, float]  # any channel <=1/255 or >=254/255
    pixel_count: int
    version: int = 1


@dataclass
class Sample(Contract):
    timestamp: float  # requested seek seconds, not a claim of exact decoded PTS
    shot_index: int | None
    stats: Statistics
    version: int = 1

    @classmethod
    def from_dict(cls, data):
        return super().from_dict({**data, "stats": Statistics.from_dict(data["stats"])})


@dataclass
class Measurement(Contract):
    path: str
    sha256: str
    duration: float
    samples: list[Sample]
    aggregate: Statistics
    coverage: dict[str, float]
    confidence: float  # heuristic evidence quality, never a probability
    color_metadata: dict[str, str]
    warnings: list[str]
    version: int = 1

    @classmethod
    def from_dict(cls, data):
        return super().from_dict({
            **data, "samples": [Sample.from_dict(v) for v in data["samples"]],
            "aggregate": Statistics.from_dict(data["aggregate"]),
        })


@dataclass
class LookParameters(Contract):
    contrast: float = 1.0
    saturation: float = 1.0
    gamma: float = 1.0
    lift: float = 0.0
    gain: list[float] = field(default_factory=lambda: [1.0, 1.0, 1.0])
    shadows: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    highlights: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        for name, low, high in (("contrast", 0.1, 2), ("saturation", 0, 2),
                                ("gamma", 0.25, 3), ("lift", 0, 0.5)):
            value = getattr(self, name)
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"invalid look parameter {name}")
        for name, low, high in (("gain", 0.25, 2), ("shadows", -0.5, 0.5), ("highlights", -0.5, 0.5)):
            values = getattr(self, name)
            if len(values) != 3 or not all(math.isfinite(v) and low <= v <= high for v in values):
                raise ValueError(f"invalid look parameter {name}")


@dataclass
class Transform(Contract):
    look: str
    parameters: LookParameters
    strength: float = 1.0
    exposure_ev: float = 0.0
    temperature: float = 0.0
    tint: float = 0.0
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        for name, low, high in (
            ("strength", 0.0, 1.0), ("exposure_ev", -0.5, 0.5),
            ("temperature", -0.06, 0.06), ("tint", -0.06, 0.06),
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{name} must be finite and in [{low}, {high}]")

    @classmethod
    def from_dict(cls, data):
        return super().from_dict({
            **data, "parameters": LookParameters.from_dict(data["parameters"]),
        })


@dataclass
class Candidate(Contract):
    transform: Transform
    score: float
    components: dict[str, float]
    reasons: list[str]
    version: int = 1

    @classmethod
    def from_dict(cls, data):
        return super().from_dict({**data, "transform": Transform.from_dict(data["transform"])})


@dataclass
class MatchResult(Contract):
    candidates: list[Candidate]
    chosen: Candidate
    baseline_score: float
    confidence: float
    warnings: list[str]
    version: int = 1

    @classmethod
    def from_dict(cls, data):
        return super().from_dict({
            **data, "candidates": [Candidate.from_dict(v) for v in data["candidates"]],
            "chosen": Candidate.from_dict(data["chosen"]),
        })


@dataclass
class Recipe(Contract):
    reference: Measurement
    clip: Measurement
    match: MatchResult
    graded_stats: Statistics
    cube_path: str
    cube_sha256: str
    preview_path: str
    color_space: str
    warnings: list[str]
    tool_version: str
    color_version: str
    interpretation: str = "Matched approximation; the creator's original LUT is unknown."
    version: int = 1

    @classmethod
    def from_dict(cls, data):
        return super().from_dict({
            **data, "reference": Measurement.from_dict(data["reference"]),
            "clip": Measurement.from_dict(data["clip"]),
            "match": MatchResult.from_dict(data["match"]),
            "graded_stats": Statistics.from_dict(data["graded_stats"]),
        })
