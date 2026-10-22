"""Explicit v1 EDL coordinates. Intervals are half-open; cuts belong to the right clip."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from pathlib import Path

from myzing.schemas import EDL, Word
from . import InspectionError


def finite(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise InspectionError(f"{name} must be a finite number of seconds.")
    return float(value)


@dataclass(frozen=True)
class TimeSpan:
    clip_index: int
    source: str
    source_start: float
    source_end: float
    output_start: float
    output_end: float
    version: int = 1

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> TimeSpan:
        if data.get("version", 1) != 1:
            raise InspectionError("Unsupported inspection time-map version; expected 1.")
        return cls(**data)


def build_time_map(edl: EDL, base_dir: Path) -> list[TimeSpan]:
    """Map v1 unity-speed, contiguous clips without reopening the source assets.

    source_time = source_start + output_time - output_start.
    Source files may be archived: only the supplied rendered video is decoded.
    """
    if edl.schema_version != 1:
        raise InspectionError("Inspection supports EDL schema_version 1 only; speed/overlap maps are not supported.")
    if not 1 <= len(edl.clips) <= 4096:
        raise InspectionError("EDL must contain 1-4096 clips.")
    finite(edl.fps, "EDL fps")
    if edl.fps <= 0:
        raise InspectionError("EDL fps must be positive.")
    ordered = []
    for index, clip in enumerate(edl.clips):
        start = finite(clip.timeline_start, f"clips[{index}].timeline_start")
        a = finite(clip.src_in, f"clips[{index}].src_in")
        b = finite(clip.src_out, f"clips[{index}].src_out")
        if start < 0 or a < 0 or b <= a:
            raise InspectionError(f"clips[{index}] requires nonnegative times and src_in < src_out.")
        if not isinstance(clip.src, str) or not clip.src.strip() or "://" in clip.src:
            raise InspectionError(f"clips[{index}].src must be a local path.")
        source = Path(clip.src).expanduser()
        if not source.is_absolute():
            source = base_dir / source
        ordered.append(TimeSpan(index, str(source.resolve()), a, b, start, start + b - a))
    ordered.sort(key=lambda span: span.output_start)
    end = 0.0
    for span in ordered:
        if abs(span.output_start - end) > 1e-6:
            raise InspectionError("EDL clips must be contiguous from 0 with no gaps or overlaps.")
        end = span.output_end
    return ordered


def output_to_source(spans: list[TimeSpan], time: float) -> dict:
    time = finite(time, "output time")
    for span in spans:
        if span.output_start <= time < span.output_end:
            return {"clip_index": span.clip_index, "source": span.source,
                    "source_time": span.source_start + time - span.output_start}
    raise InspectionError("Output time falls outside the half-open EDL timeline.")


def cut_points(spans: list[TimeSpan]) -> list[dict]:
    return [
        {"output_time": right.output_start,
         "left": {"clip_index": left.clip_index, "source": left.source, "source_time": left.source_end},
         "right": {"clip_index": right.clip_index, "source": right.source, "source_time": right.source_start}}
        for left, right in zip(spans, spans[1:])
    ]


def validate_words(words: list[Word], duration: float) -> None:
    if len(words) > 20000:
        raise InspectionError("Transcript exceeds 20000 words; split the inspection input.")
    for index, word in enumerate(words):
        a = finite(word.start, f"word {index} start")
        b = finite(word.end, f"word {index} end")
        if a < 0 or b <= a or b > duration + 1e-6:
            raise InspectionError(f"Word {index} has invalid timing ({a:g}-{b:g}s); correct it before inspection.")
        if not isinstance(word.text, str) or not word.text.strip() or len(word.text) > 256:
            raise InspectionError(f"Word {index} needs 1-256 text characters.")


def source_words_to_output(words: list[Word], source: Path, spans: list[TimeSpan]) -> list[Word]:
    """Clip words to kept source intervals, including every repeated use of a source."""
    mapped = []
    source = source.resolve()
    for span in spans:
        if Path(span.source) != source:
            continue
        for word in words:
            a, b = max(word.start, span.source_start), min(word.end, span.source_end)
            if a < b:
                mapped.append(Word(word.text, span.output_start + a - span.source_start,
                                   span.output_start + b - span.source_start, word.confidence))
    return sorted(mapped, key=lambda word: (word.start, word.end))
