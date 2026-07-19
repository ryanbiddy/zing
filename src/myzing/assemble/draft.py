"""draft_edl: direction keepers -> a valid, contiguous draft EDL.

The AI's direction (validated by tools/eval/direction_format) chose WHICH
spans to use and in WHAT order; this module does the measured half:
- trims each chosen span from the studied source media,
- lays them contiguously on the timeline (EDL S1 semantics: gaps and
  overlaps are errors, so a draft must never contain them),
- validates every span against the measured media duration,
- cross-checks the AI's spans against the MEASURED keepers from raw-mode
  study and NAMES divergences in warnings — the AI may choose freely, but
  a chosen span that measurement never blessed is worth a flag, not
  silence.

Failures are loud: an EDL that cannot be honest does not get produced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from myzing import storage
from myzing.schemas import Breakdown, Clip, EDL

MIN_CLIP_S = 0.2
KEEPER_MATCH_TOLERANCE_S = 0.35


class AssembleError(RuntimeError):
    """A draft EDL could not be produced honestly."""


@dataclass
class DraftResult:
    edl: EDL
    warnings: list[str] = field(default_factory=list)


def draft_edl(
    breakdown: Breakdown,
    direction: dict[str, Any],
    media_path: Path,
) -> DraftResult:
    """Build a draft EDL from a direction's keeper choices.

    Raises AssembleError when the direction has no usable keeper spans or
    a span exceeds the measured media; everything recoverable becomes a
    named warning.
    """
    chosen = direction.get("keepers") or []
    if not chosen:
        raise AssembleError(
            "direction has no keepers — nothing measurable to assemble; "
            "the gaps/shot_prompts must be filmed first"
        )
    if not media_path.is_file():
        raise AssembleError(f"source media missing: {media_path}")

    duration = breakdown.meta.duration
    warnings: list[str] = []
    measured = _measured_keeper_spans(breakdown)
    if measured is None:
        warnings.append(
            "draft EDL: study ran without raw mode, so chosen spans could "
            "not be cross-checked against measured keepers"
        )

    clips: list[Clip] = []
    cursor = 0.0
    for index, keeper in enumerate(chosen):
        start, end = _span_of(keeper, index)
        if duration > 0 and (start >= duration or end > duration + 0.05):
            raise AssembleError(
                f"direction keeper {index} ({start:.2f}-{end:.2f}s) exceeds "
                f"the measured media duration ({duration:.2f}s) — refusing "
                "to trim footage that does not exist"
            )
        if end - start < MIN_CLIP_S:
            warnings.append(
                f"draft EDL: keeper {index} ({start:.2f}-{end:.2f}s) shorter "
                f"than {MIN_CLIP_S}s — dropped"
            )
            continue
        if measured is not None and not _matches_measured(start, end, measured):
            warnings.append(
                f"draft EDL: chosen span {start:.2f}-{end:.2f}s is not a "
                "measured keeper (AI's call — flagged, not blocked): "
                f'"{str(keeper.get("why", ""))[:60]}"'
            )
        clips.append(Clip(
            src=str(media_path),
            src_in=round(start, 3),
            src_out=round(end, 3),
            timeline_start=round(cursor, 3),
        ))
        cursor += end - start

    if not clips:
        raise AssembleError(
            "every direction keeper was too short to trim — no draft EDL"
        )

    # Lane C P2 finding: inventing 1080x1920@30 for missing measurements
    # revived the hard-coded portrait behavior C-Q5 removed. A breakdown
    # without measured dimensions is a broken input — fail loudly instead
    # of fabricating the output orientation.
    if not (breakdown.meta.width and breakdown.meta.height and breakdown.meta.fps):
        raise AssembleError(
            "breakdown lacks measured width/height/fps "
            f"({breakdown.meta.width}x{breakdown.meta.height}"
            f"@{breakdown.meta.fps:g}) — re-run 'zing study' rather than "
            "inventing an output orientation"
        )
    edl = EDL(
        clips=clips,
        width=breakdown.meta.width,
        height=breakdown.meta.height,
        fps=breakdown.meta.fps,
    )
    return DraftResult(edl=edl, warnings=warnings)


def _span_of(keeper: dict[str, Any], index: int) -> tuple[float, float]:
    try:
        start = float(keeper["start"])
        end = float(keeper["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AssembleError(
            f"direction keeper {index} lacks numeric start/end"
        ) from exc
    if end <= start or start < 0:
        raise AssembleError(
            f"direction keeper {index} has an impossible span "
            f"({start}-{end})"
        )
    return start, end


def _measured_keeper_spans(
    breakdown: Breakdown,
) -> list[tuple[float, float]] | None:
    raw_mode = breakdown.provenance.get("raw_mode")
    if not isinstance(raw_mode, dict) or "keepers" not in raw_mode:
        return None
    return [
        (float(k["start"]), float(k["end"]))
        for k in raw_mode["keepers"]
        if isinstance(k, dict) and "start" in k and "end" in k
    ]


def _matches_measured(
    start: float, end: float, measured: list[tuple[float, float]]
) -> bool:
    """The chosen span lies within some measured keeper (tolerance for the
    AI trimming a little tighter or looser at the edges)."""
    return any(
        start >= m_start - KEEPER_MATCH_TOLERANCE_S
        and end <= m_end + KEEPER_MATCH_TOLERANCE_S
        for m_start, m_end in measured
    )


def draft_for_slug(slug: str, direction: dict[str, Any]) -> DraftResult:
    """Storage-integrated entry: load the breakdown + media for ``slug``
    and write draft-edl.json next to them."""
    breakdown = storage.load_breakdown(slug)
    media = storage.find_media(slug)
    if media is None:
        raise AssembleError(
            f"no stored media for '{slug}' — re-run 'zing study' first"
        )
    result = draft_edl(breakdown, direction, media)
    target = storage.breakdown_dir(slug) / "draft-edl.json"
    target.write_text(result.edl.to_json(indent=2) + "\n", encoding="utf-8")
    return result
