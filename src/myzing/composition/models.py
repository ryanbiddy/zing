"""Composition v2: shared planning contract with explicit renderer capabilities.

Clip, CaptionSpec and AudioTrack retain their legacy fields. Inventory rates,
layout boxes/paths/safety, color parameters, audio evidence and P14 transition
evidence are the existing contracts, not parallel definitions.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Literal

from myzing.audio.models import Segment
from myzing.brief.models import Brief
from myzing.color.models import Recipe as ColorRecipe, Transform
from myzing.contracts import Record, bounded, digest, interval, nonempty, typed
from myzing.layout.types import EventLayout
from myzing.project.models import Rational
from myzing.schemas import AudioTrack, CaptionSpec, Clip
from myzing.study.transitions import TransitionEvidence
from myzing.timing import interval_problem
from .timebase import rate_fraction

EPSILON = 1e-6  # Same seconds tolerance as the legacy renderer.
TransitionKind = Literal["hard_cut", "dissolve", "wipe", "zoom_punch"]
AudioRole = Literal["speech", "music", "silence", "uncertain", "voiceover", "sfx", "ambience"]


@dataclass
class AssetRef(Record):
    id: str
    path: str
    sha256: str | None
    duration: float | None = None
    aliases: list[str] = field(default_factory=list)
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        nonempty(self.id, "asset id")
        nonempty(self.path, "asset path")
        digest(self.sha256, "asset sha256")
        if self.duration is not None and self.duration <= 0:
            raise ValueError("asset duration must be positive or null when unknown")
        for alias in self.aliases:
            nonempty(alias, "asset alias")


@dataclass
class SourceRange(Record):
    src_in: float
    src_out: float
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        interval(self.src_in, self.src_out, "source range")


@dataclass
class SpeedSegment(Record):
    src_in: float
    src_out: float
    rate: float  # Source seconds per output second; positive, piecewise constant.
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        interval(self.src_in, self.src_out, "speed segment")
        if self.rate <= 0:
            raise ValueError("speed rate must be positive; reverse/freeze are unsupported")


@dataclass
class FontAsset(Record):
    path: str
    sha256: str
    license: str
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        for name in ("path", "license"):
            nonempty(getattr(self, name), f"font {name}")
        digest(self.sha256, "font sha256")


@dataclass
class CaptionStyle(Record):
    # Names/units match PH v1 style; font identity is in FontAsset.
    size: float  # Output pixels.
    color: str = "#FFFFFF"
    highlight: str = "#FFFF00"
    outline_color: str = "#000000"
    outline_width: float = 2.0  # Output pixels.
    box_color: str | None = None
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        bounded(self.size, 1, 512, "caption size")
        bounded(self.outline_width, 0, 20, "caption outline_width")
        for name in ("color", "highlight", "outline_color", "box_color"):
            value = getattr(self, name)
            if value is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                raise ValueError(f"caption {name} must use #RRGGBB")


@dataclass
class ColorTransform(Record):
    lut_path: str
    sha256: str
    strength: float
    color_space: str
    # Describes the transform baked into the cube, not a second grading pass.
    baked_transform: Transform | None = None
    stage: Literal["before_captions"] = "before_captions"
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        nonempty(self.lut_path, "LUT path")
        nonempty(self.color_space, "LUT color_space assumption")
        digest(self.sha256, "LUT sha256")
        bounded(self.strength, 0, 1, "LUT strength")

    @classmethod
    def from_recipe(cls, recipe: ColorRecipe) -> ColorTransform:
        # PC's .cube already includes chosen.strength and corrective controls.
        return cls(recipe.cube_path, recipe.cube_sha256, 1.0, recipe.color_space,
                   Transform.from_dict(recipe.match.chosen.transform.to_dict()))


@dataclass(kw_only=True)
class CompositionClip(Record, Clip):
    id: str
    asset_id: str
    speed_map: list[SpeedSegment] = field(default_factory=list)
    color: ColorTransform | None = None
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        for name in ("id", "asset_id", "src"):
            nonempty(getattr(self, name), f"clip {name}")
        interval(self.src_in, self.src_out, "clip trim")
        if self.timeline_start < 0:
            raise ValueError("clip timeline_start must be non-negative")
        if self.speed_map:
            cursor = self.src_in
            for segment in self.speed_map:
                segment.__post_init__()
                if not math.isclose(segment.src_in, cursor, abs_tol=EPSILON, rel_tol=0):
                    raise ValueError("speed map must tile the source trim without gaps or overlaps")
                cursor = segment.src_out
            if not math.isclose(cursor, self.src_out, abs_tol=EPSILON, rel_tol=0):
                raise ValueError("speed map must cover the complete source trim")
        if not math.isfinite(self.timeline_end):
            raise ValueError("clip timeline end must be finite")

    @property
    def duration(self) -> float:
        return (sum((s.src_out - s.src_in) / s.rate for s in self.speed_map)
                if self.speed_map else self.src_out - self.src_in)

    @property
    def timeline_end(self) -> float:
        return self.timeline_start + self.duration

    def source_at(self, time: float) -> float:
        typed(time, float, "output time")
        if not self.timeline_start - EPSILON <= time <= self.timeline_end + EPSILON:
            raise ValueError("output time lies outside the clip")
        remaining = max(0.0, time - self.timeline_start)
        for segment in self.speed_map:
            length = (segment.src_out - segment.src_in) / segment.rate
            if remaining <= length + EPSILON:
                return min(segment.src_out, segment.src_in + remaining * segment.rate)
            remaining -= length
        return self.src_out if self.speed_map else min(self.src_out, self.src_in + remaining)


def validate_evidence(evidence: TransitionEvidence) -> None:
    typed(evidence, TransitionEvidence, "transition evidence")
    if evidence.signature not in {"hard_cut", "dissolve", "wipe", "zoom_punch", "unknown"}:
        raise ValueError("unsupported transition evidence signature")
    if not (0 <= evidence.evidence_start_seconds <= evidence.start_seconds
            <= evidence.end_seconds <= evidence.evidence_end_seconds):
        raise ValueError("transition evidence window must contain the observation")
    bounded(evidence.confidence, 0, 1, "transition evidence confidence")
    if evidence.detector_version <= 0:
        raise ValueError("transition detector_version must be positive")
    nonempty(evidence.reason, "transition evidence reason")
    if evidence.direction not in (None, "left", "right", "up", "down"):
        raise ValueError("transition wipe direction must be left, right, up, down, or null")
    if evidence.direction is not None and evidence.signature != "wipe":
        raise ValueError("only wipe evidence has a direction")
    if evidence.signature == "unknown" and evidence.observation_index is not None:
        raise ValueError("unknown transition evidence cannot point to a legacy observation")


@dataclass
class TransitionRecipe(Record):
    kind: TransitionKind
    duration_seconds: float
    reason: str  # Why this stand-in was chosen; not a recovered preset.
    direction: Literal["left", "right", "up", "down"] | None = None
    observation: TransitionEvidence | None = None
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        nonempty(self.reason, "transition recipe reason")
        if self.duration_seconds < 0 or ((self.kind == "hard_cut") != (self.duration_seconds == 0)):
            raise ValueError("hard cuts need zero duration; other transition recipes need positive duration")
        if (self.kind == "wipe") != (self.direction is not None):
            raise ValueError("only a wipe recipe requires a direction")
        if self.observation is not None:
            validate_evidence(self.observation)


@dataclass
class Transition(Record):
    id: str
    outgoing_clip: str
    incoming_clip: str
    start: float
    end: float
    recipe: TransitionRecipe
    outgoing_handle: SourceRange | None = None
    incoming_handle: SourceRange | None = None
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        for name in ("id", "outgoing_clip", "incoming_clip"):
            nonempty(getattr(self, name), f"transition {name}")
        if self.start < 0 or self.end < self.start:
            raise ValueError("transition window requires 0 <= start <= end")
        self.recipe.__post_init__()
        if not math.isclose(self.end - self.start, self.recipe.duration_seconds,
                            rel_tol=0, abs_tol=EPSILON):
            raise ValueError("transition overlap window must match recipe duration")
        if self.recipe.kind != "hard_cut" and (self.outgoing_handle is None or self.incoming_handle is None):
            raise ValueError("transition overlap is missing required source handles for both clips")
        if self.recipe.kind == "hard_cut" and (self.outgoing_handle is not None or self.incoming_handle is not None):
            raise ValueError("hard cuts have no source handles")


@dataclass(kw_only=True)
class CompositionCaption(Record, CaptionSpec):
    id: str
    alignment: Literal["left", "center", "right"] = "center"
    layout: EventLayout | None = None
    font: FontAsset | None = None
    style: CaptionStyle | None = None
    backend: Literal["ass", "hyperframes"] = "ass"
    template: Literal["phrase-highlight", "kinetic"] | None = None
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        nonempty(self.id, "caption id")
        nonempty(self.text, "caption text")
        interval(self.start, self.end, "caption interval")
        if self.position not in {"top", "center", "lower", "bottom"}:
            raise ValueError("caption position must use a legacy anchor: top, center, lower, bottom")
        if self.word_timed and not self.words:
            raise ValueError("word-timed caption requires words")
        previous = self.start
        for word in self.words:
            problem = interval_problem(word.start, word.end, self.end + EPSILON)
            if problem or word.start < previous - EPSILON:
                raise ValueError(f"caption word timing: {problem or 'outside caption or overlapping words'}")
            nonempty(word.text, "word text")
            bounded(word.confidence, 0, 1, "word confidence")
            previous = word.end
        if self.layout is not None:
            self.layout.__post_init__()
            if (self.layout.id, self.layout.start, self.layout.end) != (self.id, self.start, self.end):
                raise ValueError("caption layout id and interval must match its event")
        if self.backend == "hyperframes" and any(v is None for v in (self.layout, self.font, self.style, self.template)):
            raise ValueError("hyperframes caption needs layout, font, style and template")
        if self.backend == "ass" and self.template is not None:
            raise ValueError("caption template belongs to the hyperframes backend")


@dataclass(kw_only=True)
class CompositionAudio(Record, AudioTrack):
    id: str
    asset_id: str
    role: AudioRole
    role_evidence: Segment | None = None  # Source coordinates from AudioMap.
    src_in: float = 0.0
    src_out: float | None = None
    duck_scope: Literal["voiceover", "source_speech", "all_speech"] = "voiceover"
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        for name in ("id", "asset_id", "src", "kind"):
            nonempty(getattr(self, name), f"audio {name}")
        if self.src_in < 0 or self.timeline_start < 0:
            raise ValueError("audio source/timeline starts must be non-negative")
        if self.src_out is not None:
            interval(self.src_in, self.src_out, "audio trim")
        if self.duck_under_speech and self.role != "music":
            raise ValueError("only music can duck under speech")
        if self.role_evidence is not None and self.role != self.role_evidence.label:
            raise ValueError("audio role must agree with its AudioMap segment label")


@dataclass
class LoudnessTarget(Record):
    integrated_lufs: float
    true_peak_dbtp: float
    loudness_range_lu: float = 11.0
    version: int = 1

    def __post_init__(self):
        super().__post_init__()
        bounded(self.integrated_lufs, -70, -5, "target integrated LUFS")
        bounded(self.true_peak_dbtp, -9, 0, "target true peak dBTP")
        bounded(self.loudness_range_lu, 1, 50, "target loudness range LU")


@dataclass
class Composition(Record):
    assets: list[AssetRef] = field(default_factory=list)
    clips: list[CompositionClip] = field(default_factory=list)
    captions: list[CompositionCaption] = field(default_factory=list)
    audio: list[CompositionAudio] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    width: int = 1080
    height: int = 1920
    fps: Rational = field(default_factory=lambda: Rational(30, 1))
    loudness_target: LoudnessTarget | None = None
    warnings: list[str] = field(default_factory=list)
    accepted_unsafe_layouts: list[str] = field(default_factory=list)
    brief: Brief | None = None
    # Migration spelling, including int vs float, for byte-identical v1 lowering.
    legacy_fps: float | None = None
    # JSON-pointer -> ordered object keys within legacy Word.timing payloads.
    # Canonical v2 JSON sorts objects; these arrays retain the v1 byte spelling.
    legacy_timing_order: dict[str, list[str]] = field(default_factory=dict)
    schema_version: Literal[2] = 2

    def __post_init__(self):
        super().__post_init__()
        rate_fraction(self.fps)
        if self.width <= 0 or self.height <= 0:
            raise ValueError("composition width and height must be positive integers")
        if self.legacy_fps is not None and self.legacy_fps <= 0:
            raise ValueError("legacy_fps must be positive")
        for name in ("assets", "clips", "captions", "audio", "transitions"):
            items = getattr(self, name)
            if len({item.id for item in items}) != len(items):
                raise ValueError(f"duplicate {name} ids")
        caption_ids = {c.id for c in self.captions}
        if (len(set(self.accepted_unsafe_layouts)) != len(self.accepted_unsafe_layouts)
                or any(cid not in caption_ids for cid in self.accepted_unsafe_layouts)):
            raise ValueError("accepted_unsafe_layouts must contain unique existing caption ids")
        assets = {a.id: a for a in self.assets}
        for item in [*self.clips, *self.audio]:
            item.__post_init__()
            asset = assets.get(item.asset_id)
            if asset is None:
                raise ValueError(f"{item.id}: unknown asset_id {item.asset_id}")
            if item.src not in [asset.path, *asset.aliases]:
                raise ValueError(f"{item.id}: src must match the asset path or a recorded alias")
            if asset.duration is not None and item.src_out is not None and item.src_out > asset.duration + 0.05:
                raise ValueError(f"{item.id}: source trim exceeds asset duration")
        ordered = sorted(self.clips, key=lambda c: c.timeline_start)
        pairs = {(a.id, b.id): (a, b) for a, b in zip(ordered, ordered[1:])}
        declared = {}
        for transition in self.transitions:
            transition.__post_init__()
            key = (transition.outgoing_clip, transition.incoming_clip)
            if key not in pairs or key in declared:
                raise ValueError("transition must link two adjacent clips exactly once")
            declared[key] = transition
            a, b = pairs[key]
            length = transition.end - transition.start
            if length > min(a.duration, b.duration) + EPSILON:
                raise ValueError("transition overlap is longer than either clip")
            if not (math.isclose(transition.start, b.timeline_start, abs_tol=EPSILON, rel_tol=0)
                    and math.isclose(transition.end, a.timeline_end, abs_tol=EPSILON, rel_tol=0)):
                raise ValueError("transition window must equal the clips' timeline overlap")
            if transition.recipe.kind != "hard_cut":
                for clip, handle in ((a, transition.outgoing_handle), (b, transition.incoming_handle)):
                    handle.__post_init__()
                    expected = (clip.source_at(transition.start), clip.source_at(transition.end))
                    if not all(math.isclose(x, y, abs_tol=EPSILON, rel_tol=0)
                               for x, y in zip((handle.src_in, handle.src_out), expected)):
                        raise ValueError("required source handles must cover the entire overlap through the speed map")
        if ordered and abs(ordered[0].timeline_start) > EPSILON:
            raise ValueError("composition must start at zero")
        for (aid, bid), (a, b) in pairs.items():
            gap = b.timeline_start - a.timeline_end
            if gap > EPSILON:
                raise ValueError("composition has an unsupported timeline gap")
            if gap < -EPSILON and (aid, bid) not in declared:
                raise ValueError("clip overlap needs an explicit transition and source handles")
        if any(a.timeline_end > c.timeline_start + EPSILON for a, c in zip(ordered, ordered[2:])):
            raise ValueError("three-way clip overlaps are unsupported")
        duration = max((c.timeline_end for c in ordered), default=0.0)
        for caption in self.captions:
            caption.__post_init__()
            if caption.end > duration + EPSILON:
                raise ValueError("caption interval exceeds composition duration")
