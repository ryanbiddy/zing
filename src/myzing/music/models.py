"""Music evidence travels with v2 plans without changing the legacy schemas."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from types import SimpleNamespace
from myzing.contracts import Record
from .ducking import (DEFAULT_ATTACK_SECONDS, DEFAULT_DEPTH_DB, DEFAULT_HOLD_SECONDS, DEFAULT_PLATEAU_SECONDS,
                      DEFAULT_RELEASE_SECONDS, check_span_count)

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
    # Known-speech ducking (docs/MUSIC.md). Clause gaps shorter than the hold
    # stay ducked; the bed recovers only in longer pauses.
    duck_hold_seconds: float = DEFAULT_HOLD_SECONDS
    duck_depth_db: float = DEFAULT_DEPTH_DB
    duck_attack_seconds: float = DEFAULT_ATTACK_SECONDS
    duck_release_seconds: float = DEFAULT_RELEASE_SECONDS
    # A pause releases only with this much time at the recovered level.
    duck_plateau_seconds: float = DEFAULT_PLATEAU_SECONDS
    # Per-clip bed level on top of the duck: [output seconds, dB <= 0] points,
    # raised-cosine between them. Empty unless clip speech levels differ.
    bed_gain_points: list[list[float]] = field(default_factory=list)
    # Per-clip dialogue gain (and peak compressor) when clip speech levels
    # differ; output-time ranges, so framing splits keep them (dialogue.py).
    dialogue_gains: list[dict] = field(default_factory=list)
    # Planning estimates per clip and per clause (speech, music, separation).
    clip_levels: list[dict] = field(default_factory=list)
    clauses: list[dict] = field(default_factory=list)
    # The clip timeline the spans were planned against; empty means unrecorded.
    timeline: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        if self.mode not in {"speech-led", "music-led"}:
            raise ValueError("invalid music edit mode")
        for start, end in self.speech_spans:
            if not all(type(x) in (int, float) and math.isfinite(x) for x in (start, end)) or not 0 <= start < end:
                raise ValueError("music speech spans require finite 0 <= start < end")
        check_span_count(len(self.speech_spans))
        for name, low, high in (("duck_hold_seconds", 0, 5), ("duck_depth_db", 0, 30),
                                ("duck_attack_seconds", .02, 2), ("duck_release_seconds", .05, 5),
                                ("duck_plateau_seconds", 0, 2)):
            value = getattr(self, name)
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{name} must be in [{low}, {high}]")
        previous = -math.inf
        for point in self.bed_gain_points:
            if (len(point) != 2 or not all(type(x) in (int, float) and math.isfinite(x) for x in point)
                    or point[0] < max(0, previous) or not -60 <= point[1] <= 0):
                raise ValueError("bed_gain_points need ascending [seconds >= 0, -60 <= dB <= 0] pairs")
            previous = point[0]
        check_span_count(len(self.bed_gain_points) // 2, "bed gain changes")
        from .dialogue import validate
        validate(self.dialogue_gains)

    def duck(self) -> dict:
        return {"hold": self.duck_hold_seconds, "depth_db": self.duck_depth_db,
                "attack": self.duck_attack_seconds, "release": self.duck_release_seconds,
                "plateau": self.duck_plateau_seconds, "gain_points": [list(p) for p in self.bed_gain_points]}


def _contiguous(a: dict, b: dict) -> bool:
    return (a["asset_id"] == b["asset_id"] and abs(a["src_out"] - b["src_in"]) <= 1e-6
            and abs(a["timeline_start"] + a["src_out"] - a["src_in"] - b["timeline_start"]) <= 1e-6)


def timeline_of(clips) -> list[dict]:
    """Fingerprint of composition clips (or director candidates) in output order.

    Contiguous pieces of one source (same asset, continuous source and output
    time) merge, so framing splits at shot boundaries in the director or in a
    per-aspect delivery keep the planned speech-span timeline.
    """
    rows, cursor = [], 0.0
    for c in sorted(clips, key=lambda c: getattr(c, "timeline_start", 0.0)) if all(
            hasattr(c, "timeline_start") for c in clips) else clips:
        start = getattr(c, "timeline_start", cursor)
        src_in = getattr(c, "src_in", getattr(c, "start", None))
        src_out = getattr(c, "src_out", getattr(c, "end", None))
        row = {"asset_id": c.asset_id, "src_in": float(src_in), "src_out": float(src_out),
               "timeline_start": float(start)}
        if rows and _contiguous(rows[-1], row):
            rows[-1]["src_out"] = row["src_out"]
        else:
            rows.append(row)
        cursor = start + src_out - src_in
    return rows


def stale_timeline(evidence: MusicPlan, clips) -> str | None:
    """A reason when spans were planned for a different clip timeline."""
    if not evidence.timeline:
        return None
    current = timeline_of(clips)
    planned = timeline_of([SimpleNamespace(**row) for row in evidence.timeline])
    if len(current) != len(planned) or any(
            a["asset_id"] != b["asset_id"] or any(abs(a[k] - b[k]) > 1e-6 for k in ("src_in", "src_out", "timeline_start"))
            for a, b in zip(current, planned)):
        return ("MUSIC1 speech spans were planned for a different clip timeline (clips, trims or transition "
                "overlaps changed); re-run zing plan drafts before ducking under source speech")
    return None


def extract(plan):
    payloads = [w[len(PREFIX):] for w in plan.warnings if w.startswith(PREFIX)]
    if len(payloads) > 1:
        raise ValueError("plan has duplicate MUSIC1 evidence")
    return MusicPlan.from_dict(json.loads(payloads[0])) if payloads else MusicPlan()


def attach(plan, evidence):
    plan.warnings = [w for w in plan.warnings if not w.startswith(PREFIX)] + [PREFIX + json.dumps(evidence.to_dict(), allow_nan=False, sort_keys=True)]
    return plan
