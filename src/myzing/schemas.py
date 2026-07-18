"""The interface contract for Zing.

Every lane builds against these shapes. Change them only via an
orchestrator-approved PR that updates ALL producers and consumers in the
same change — this is the file that lets three workers build in parallel
without colliding.

Design rules:
- stdlib only (dataclasses + json). No pydantic, no third-party deps in core.
- All times are seconds from the start of the video, as floats.
- Everything serializes to/from plain JSON via to_dict()/from_dict() so the
  MCP layer, the CLI, and files on disk all speak the same shape.
- Deterministic measurement lives here. AI judgment (hook type, beat labels,
  gap reports) is produced by the user's AI over MCP and stored in the
  free-form `judgment` slots — never computed by Zing's own code.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Measurement primitives (Lane A produces these)
# ---------------------------------------------------------------------------

@dataclass
class Shot:
    """One camera shot between two cuts.

    All timestamps in this contract derive from container PTS, never frame
    indices; VFR sources are normalized to CFR on ingest and VideoMeta.fps
    records the normalized rate (Lane A critique #5, accepted 2026-07-18).
    """
    index: int
    start: float
    end: float
    # First frame of the shot, path RELATIVE to the breakdown's directory
    # ("" = not extracted). Lane A writes these during study so the judgment
    # AI can see the video, not just read about it.
    keyframe: str = ""

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Word:
    """One transcript word with timing (faster-whisper word timestamps)."""
    text: str
    start: float
    end: float
    confidence: float = 1.0   # ASR per-word probability; 1.0 = not reported


@dataclass
class CaptionEvent:
    """On-screen text observed via OCR: what, when, and roughly how it looks."""
    text: str
    start: float
    end: float
    # Style observations — best-effort, honest about uncertainty:
    position: str = "center"      # top | center | lower | bottom
    all_caps: bool = False
    words_visible: int = 1        # words shown at once (1 = word-timed pop)
    confidence: float = 0.0       # OCR confidence 0..1


@dataclass
class AudioLayout:
    """Coarse audio structure. Approximate by design — we say what we
    measured, not what we guessed (no track ID, no effect detection).

    Pinned definitions (accepted 2026-07-18, binding for pipeline AND eval):
    - speech_ratio: fraction of duration covered by VAD speech.
    - loudness_curve: per-1-second mean RMS in dBFS via ffmpeg astats
      (S1 floor; EBU R128 LUFS is the S2 candidate if platform targets
      require it).
    """
    has_music: bool = False
    music_confidence: float = 0.0  # 0 = no evidence; keeps the bool honest
    has_voiceover: bool = False
    speech_ratio: float = 0.0     # fraction of runtime with speech
    loudness_curve: list[float] = field(default_factory=list)  # 1 sample/sec, dBFS


@dataclass
class VideoMeta:
    source_url: str
    platform: str                 # tiktok | instagram | youtube | file
    author: str = ""
    title: str = ""
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0              # normalized (CFR) rate after ingest
    # Local media file the measurements came from, stored RELATIVE to the
    # breakdown's own directory (portable: a breakdown folder survives being
    # moved/synced). Storage resolves to absolute at load.
    media_path: str = ""


@dataclass
class Breakdown:
    """The complete deterministic measurement of one video.

    This is Zing's atom: Lane A produces it, Lane B serves and renders it,
    the eval harness scores it, and the user's AI reasons over it.
    """
    meta: VideoMeta
    shots: list[Shot] = field(default_factory=list)
    words: list[Word] = field(default_factory=list)
    captions: list[CaptionEvent] = field(default_factory=list)
    audio: AudioLayout = field(default_factory=AudioLayout)
    # Derived pacing metrics (computed, not judged).
    # cuts_per_10s definition (pinned 2026-07-18): non-overlapping 10s
    # windows from t=0; trailing partial window counted raw, NOT scaled —
    # the window list length implies coverage.
    avg_shot_duration: float = 0.0
    cuts_per_10s: list[float] = field(default_factory=list)  # windowed cut rate
    # Measurement honesty: every skipped/degraded measurement MUST be named
    # here (e.g. "transcription skipped: faster-whisper not installed").
    # Empty lists downstream are ambiguous without this.
    warnings: list[str] = field(default_factory=list)
    # How this breakdown was produced (zing version, detector + threshold,
    # whisper model + compute type, OCR backend, measured_at ISO). Free-form
    # while S1 learns what belongs here; needed so eval scores are
    # comparable across runs.
    provenance: dict[str, Any] = field(default_factory=dict)
    # AI judgment slots — written back over MCP, never computed locally.
    # Binding merge rule (Lane B critique #3): namespaced by section with
    # per-section REPLACE (judgment["study"] = {...} wholesale, never deep
    # merge); writers stamp judgment[section]["_meta"] = {model?,
    # prompt_version, written_at}.
    judgment: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, **kw: Any) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, **kw)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Breakdown":
        return cls(
            meta=VideoMeta(**d["meta"]),
            shots=[Shot(**s) for s in d.get("shots", [])],
            words=[Word(**w) for w in d.get("words", [])],
            captions=[CaptionEvent(**c) for c in d.get("captions", [])],
            audio=AudioLayout(**d.get("audio", {})),
            avg_shot_duration=d.get("avg_shot_duration", 0.0),
            cuts_per_10s=d.get("cuts_per_10s", []),
            warnings=d.get("warnings", []),
            provenance=d.get("provenance", {}),
            judgment=d.get("judgment", {}),
            schema_version=d.get("schema_version", 1),
        )

    @classmethod
    def from_json(cls, s: str) -> "Breakdown":
        return cls.from_dict(json.loads(s))


# ---------------------------------------------------------------------------
# Assembly primitives (Lane C consumes these; D-2/D-3 produce them later)
# ---------------------------------------------------------------------------

@dataclass
class Clip:
    """One piece of source footage placed on the timeline."""
    src: str                      # path to local media file
    src_in: float                 # trim in-point within src
    src_out: float                # trim out-point within src
    timeline_start: float         # where it lands in the output


@dataclass
class CaptionSpec:
    """A caption to burn in, with the style the profile calls for."""
    text: str
    start: float
    end: float
    position: str = "lower"
    all_caps: bool = True
    word_timed: bool = True       # pop word-by-word using Word timings
    words: list[Word] = field(default_factory=list)


@dataclass
class AudioTrack:
    src: str
    kind: str                     # voiceover | music
    timeline_start: float = 0.0
    gain_db: float = 0.0
    duck_under_speech: bool = False


@dataclass
class EDL:
    """Edit decision list: everything the renderer needs, nothing it must guess.

    The renderer (Lane C) is deliberately dumb: it executes this exactly and
    fails loudly on anything malformed. All taste lives upstream.

    Binding S1 timeline/audio semantics (Lane C critique #1, accepted
    2026-07-18):
    - Clips are sorted by timeline_start; overlaps are an ERROR; gaps are an
      ERROR in S1 (the EDL producer must emit a contiguous timeline).
    - Source clip audio IS retained at unity gain (the user's footage is the
      primary content).
    - Each AudioTrack plays ONCE from its source start, placed at
      timeline_start, trimmed at output end, silence-padded — never looped.
    - duck_under_speech in S1 means: music ducks under VOICEOVER tracks
      only. (S4 extends ducking to speech in clip audio via VAD sidechain.)
    - Output audio: 48 kHz stereo; if there are no audio inputs at all the
      output carries a silent track. No auto-limiting in S1 (S4 adds
      loudnorm to platform targets).
    """
    clips: list[Clip] = field(default_factory=list)
    captions: list[CaptionSpec] = field(default_factory=list)
    audio: list[AudioTrack] = field(default_factory=list)
    width: int = 1080
    height: int = 1920
    fps: float = 30.0
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, **kw: Any) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, **kw)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EDL":
        return cls(
            clips=[Clip(**c) for c in d.get("clips", [])],
            captions=[
                CaptionSpec(
                    **{**c, "words": [Word(**w) for w in c.get("words", [])]}
                )
                for c in d.get("captions", [])
            ],
            audio=[AudioTrack(**a) for a in d.get("audio", [])],
            width=d.get("width", 1080),
            height=d.get("height", 1920),
            fps=d.get("fps", 30.0),
            schema_version=d.get("schema_version", 1),
        )

    @classmethod
    def from_json(cls, s: str) -> "EDL":
        return cls.from_dict(json.loads(s))
