"""Music evidence travels with v2 plans without changing the legacy schemas."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from myzing.contracts import Record

PREFIX = "MUSIC1 evidence: "


@dataclass
class MusicPlan(Record):
    mode: str = "music-led"
    speech_spans: list[list[float]] = field(default_factory=list)
    tracks: list[dict] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    cut_summary: dict = field(default_factory=dict)
    speech_to_music_lu: float = 21.0
    beat_tolerance_seconds: float = .08
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        if self.mode not in {"speech-led", "music-led"}:
            raise ValueError("invalid music edit mode")
        for start, end in self.speech_spans:
            if not all(type(x) in (int, float) and math.isfinite(x) for x in (start, end)) or not 0 <= start < end:
                raise ValueError("music speech spans require finite 0 <= start < end")


def extract(plan):
    payloads = [w[len(PREFIX):] for w in plan.warnings if w.startswith(PREFIX)]
    if len(payloads) > 1:
        raise ValueError("plan has duplicate MUSIC1 evidence")
    return MusicPlan.from_dict(json.loads(payloads[0])) if payloads else MusicPlan()


def attach(plan, evidence):
    plan.warnings = [w for w in plan.warnings if not w.startswith(PREFIX)] + [PREFIX + json.dumps(evidence.to_dict(), allow_nan=False, sort_keys=True)]
    return plan
