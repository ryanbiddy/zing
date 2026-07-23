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
from myzing.schemas import Breakdown, CaptionSpec, Clip, EDL, Word
from myzing.study import formats

MIN_CLIP_S = 0.2
KEEPER_MATCH_TOLERANCE_S = 0.35
WORD_BOUNDARY_TOLERANCE_S = 0.02
CAPTION_GAP_S = 0.6           # word gap that closes a caption window
CAPTION_MAX_WORDS = 5
OUTPUT_ASPECT_TOLERANCE = 0.02
OUTPUT_RATIOS = {
    "vertical": (9, 16),
    "landscape": (16, 9),
    "square": (1, 1),
}
THIN_STYLE_BASIS_EVENTS = 15  # O-3: fewer measured events than this = warn


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
        warnings.extend(
            _trim_boundary_warnings(
                breakdown.words,
                start=start,
                end=end,
                keeper_index=index,
            )
        )
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
    output_width, output_height, output_warning = _output_dimensions(
        breakdown.meta.width,
        breakdown.meta.height,
    )
    if output_warning:
        warnings.append(output_warning)
    captions = _caption_specs(breakdown, clips)
    style_risks = _caption_style_risks(breakdown)
    if captions and style_risks:
        warnings.append(
            f"draft EDL: caption style came from {len(breakdown.captions)} "
            f"on-screen text event(s) and was applied to {len(captions)} "
            f"derived caption(s) — {'; '.join(style_risks)}. Treat the "
            "style as a guess and verify it against a frame"
        )
    if not captions and breakdown.words:
        warnings.append(
            "draft EDL: no transcript words fall inside the chosen spans — "
            "captions omitted"
        )
    elif not breakdown.words:
        warnings.append(
            "draft EDL: captions omitted — the breakdown has no transcript"
        )

    edl = EDL(
        clips=clips,
        captions=captions,
        width=output_width,
        height=output_height,
        fps=breakdown.meta.fps,
    )
    return DraftResult(edl=edl, warnings=warnings)


def _output_dimensions(
    measured_width: int,
    measured_height: int,
) -> tuple[int, int, str]:
    """Map a measured near-preset stream to an exact, even render frame.

    Short-video encoders commonly round one side to the nearest even pixel
    (for example 240x426 for a 9:16 source). The breakdown retains those
    measured dimensions. The EDL uses the largest non-upscaled, even exact
    preset frame that fits inside them so the renderer need not pretend the
    source itself had a different shape.
    """
    measured_ratio = measured_width / measured_height
    ranked = sorted(
        (
            (
                abs(
                    measured_ratio - ratio_width / ratio_height
                ) / (ratio_width / ratio_height),
                name,
                ratio_width,
                ratio_height,
            )
            for name, (ratio_width, ratio_height)
            in OUTPUT_RATIOS.items()
        ),
        key=lambda candidate: candidate[0],
    )
    distance, preset, ratio_width, ratio_height = ranked[0]
    if distance > OUTPUT_ASPECT_TOLERANCE:
        raise AssembleError(
            "measured source aspect "
            f"{measured_width}x{measured_height} is not within "
            "2% of a 9:16, 16:9, or 1:1 render preset"
        )
    scale = min(
        measured_width // ratio_width,
        measured_height // ratio_height,
    )
    # Both dimensions must be even for yuv420p. Each supported ratio has
    # at least one odd side, so an even scale guarantees both are even.
    scale -= scale % 2
    if scale <= 0:
        raise AssembleError(
            "measured source is too small for an even preset render frame"
        )
    width = ratio_width * scale
    height = ratio_height * scale
    if (width, height) == (measured_width, measured_height):
        return width, height, ""
    warning = (
        "draft EDL: measured "
        f"{measured_width}x{measured_height} mapped to exact {preset} "
        f"output {width}x{height}; source measurements remain unchanged "
        "in the breakdown"
    )
    return width, height, warning



def _caption_style_risks(breakdown: Breakdown) -> list[str]:
    """Reasons the measured caption style may not describe real captions.

    These were two separate warnings until both fired on one draft with
    overlapping text — redundant noise in the list judging AIs are told
    to read FIRST, which trains exactly the skimming the list exists to
    prevent. One warning, naming whichever risks apply.
    """
    risks: list[str] = []
    count = len(breakdown.captions)
    if not count:
        return risks
    if breakdown.meta.duration > formats.SHORT_FORM_MAX_S:
        # MEASURED, not inferred: past the short-form boundary the overlay
        # exclusion in captions.py effectively cannot fire (see its MEASURED
        # LIMIT note), so captions[] may carry watermarks, HUD and score
        # counters — a 430s cell yielded 1,882 entries with ZERO real
        # captions.
        risks.append(
            f"past {formats.SHORT_FORM_MAX_S:.0f}s the overlay exclusion is "
            "measured to under-fire, so this basis may include watermarks "
            "or HUD text"
        )
    if count < THIN_STYLE_BASIS_EVENTS:
        # O-3 (S5 gate): a handful of events, which may be overlays rather
        # than speech captions, styling every derived caption.
        risks.append(
            f"only {count} event(s) is a thin basis, possibly non-caption "
            "text"
        )
    return risks


def _caption_style(breakdown: Breakdown) -> tuple[str, bool, bool]:
    """(position, all_caps, word_timed) — measured from the source's own
    captions when it has any, sensible short-form defaults otherwise
    (raw recordings have no captions to measure).

    KNOWN DEFECT, measured 2026-07-20, traced but NOT fixed here.
    This reads `breakdown.captions`, which on long-form can be entirely
    non-caption text: the overlay exclusion in captions.py cannot fire
    there (see its MEASURED LIMIT note), so gameplay HUD, scoreboards
    and watermarks arrive as "captions". On the P-C2 HUD cell — 1,882
    events, ZERO of them real captions by hand label — this function
    returns position='center', all_caps=False, word_timed=True, i.e. it
    styles a creator's draft from a scoreboard, silently.

    The O-3 thin-basis warning does NOT catch this: it fires below
    THIN_STYLE_BASIS_EVENTS, and here the basis is huge — just wrong.
    A rich basis is not a trustworthy one.

    Refuted candidate (measured, do not retry blind): position
    CONCENTRATION does not separate them. The HUD cell's dominant
    position holds 73.6% of events — HIGHER than two cells with real
    captions (47.6%, 60.3%).

    The upstream fix is the queued region-merge item: restoring overlay
    exclusion on long-form removes most of this text before it ever
    reaches here. Fixing it downstream would need the caption/
    non-caption discriminator that P-C2 showed does not yet exist.
    """
    measured = breakdown.captions
    if not measured:
        return "lower", True, True
    positions = [c.position for c in measured]
    position = max(set(positions), key=positions.count)
    all_caps = sum(c.all_caps for c in measured) / len(measured) > 0.5
    visible = [c.words_visible for c in measured]
    word_timed = max(set(visible), key=visible.count) <= 2
    return position, all_caps, word_timed


def _caption_specs(
    breakdown: Breakdown, clips: list[Clip]
) -> list[CaptionSpec]:
    """D-8: word-timed caption specs derived from the breakdown's measured
    words inside each trim, remapped onto the output timeline. Grouping:
    a window closes at a speech gap or at CAPTION_MAX_WORDS."""
    if not breakdown.words:
        return []
    position, all_caps, word_timed = _caption_style(breakdown)
    specs: list[CaptionSpec] = []
    for clip in clips:
        offset = clip.timeline_start - clip.src_in
        # D-10: a word straddling a trim edge is mostly audible in the
        # render when its midpoint lies inside the span — caption it with
        # start/end clamped to the trim instead of dropping it.
        inside = [
            _clamped(w, clip.src_in, clip.src_out)
            for w in breakdown.words
            if clip.src_in <= (w.start + w.end) / 2 < clip.src_out
        ]
        window: list[Word] = []
        for word in inside:
            if window and (
                word.start - window[-1].end > CAPTION_GAP_S
                or len(window) >= CAPTION_MAX_WORDS
            ):
                specs.append(_spec(window, offset, position, all_caps, word_timed))
                window = []
            window.append(word)
        if window:
            specs.append(_spec(window, offset, position, all_caps, word_timed))
    return specs


def _spec(
    window: list[Word],
    offset: float,
    position: str,
    all_caps: bool,
    word_timed: bool,
) -> CaptionSpec:
    text = " ".join(w.text.strip() for w in window)
    if all_caps:
        text = text.upper()
    return CaptionSpec(
        text=text,
        start=round(window[0].start + offset, 3),
        end=round(window[-1].end + offset, 3),
        position=position,
        all_caps=all_caps,
        word_timed=word_timed,
        words=[
            Word(
                text=w.text.strip().upper() if all_caps else w.text.strip(),
                start=round(w.start + offset, 3),
                end=round(w.end + offset, 3),
                confidence=w.confidence,
            )
            for w in window
        ],
    )


def _clamped(word: Word, src_in: float, src_out: float) -> Word:
    if word.start >= src_in and word.end <= src_out:
        return word
    return Word(
        text=word.text,
        start=max(word.start, src_in),
        end=min(word.end, src_out),
        confidence=word.confidence,
    )


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


def _trim_boundary_warnings(
    words: list[Word],
    *,
    start: float,
    end: float,
    keeper_index: int,
) -> list[str]:
    """Name the objective subset of context breaks: cutting through a word."""
    warnings: list[str] = []
    for label, boundary in (("starts", start), ("ends", end)):
        matches = [
            word for word in words
            if (
                word.start + WORD_BOUNDARY_TOLERANCE_S
                < boundary
                < word.end - WORD_BOUNDARY_TOLERANCE_S
            )
        ]
        if not matches:
            continue
        if label == "starts":
            word = max(matches, key=lambda item: item.end - boundary)
        else:
            word = max(matches, key=lambda item: boundary - item.start)
        text = " ".join(str(word.text).split())[:40].replace("'", "’")
        warnings.append(
            "draft EDL: context-boundary risk — "
            f"keeper {keeper_index} {label} at {boundary:.3f}s inside "
            f"measured word '{text}' ({word.start:.3f}-{word.end:.3f}s, "
            f"confidence {word.confidence:.2f}); "
            "adjust the trim or verify the audible cut"
        )
    return warnings


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
