"""build_profile: N breakdowns of admired references -> one StyleProfile.

Aggregation rules (S2 spec, binding):
- MEASURED aggregates only, robust stats (median/p25/p75) per contract
  field; a source missing a measurement is EXCLUDED from that stat and
  named in warnings — ``StatSummary.n`` tells the truth about coverage.
- cuts_per_10s_curve is over NORMALIZED position: each source's cuts land
  in 10 buckets of relative runtime, so a 30s and a 60s reference align.
- Transition counts come only from sources whose detector actually ran
  (transition* provenance key); the rest are named in warnings.
- JUDGED sections are copied verbatim, keyed by section then slug; prompt
  versions seen are stamped into ``judged["_meta"]``; sources with no
  judgment at all are listed in ``unjudged_source_slugs``. Zing collects
  judgment; it never computes it.
"""

from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from statistics import median, quantiles
from typing import Any

from myzing import storage
from myzing.schemas import Breakdown, StatSummary, StyleProfile

CURVE_BUCKETS = 10


class ProfileError(RuntimeError):
    """A profile could not be built honestly."""


def build_profile(
    name: str,
    slugs: list[str],
    workspace: Path | None = None,
    *,
    genre: str = "",
    platform: str = "",
) -> StyleProfile:
    """Build and persist a StyleProfile from stored breakdowns.

    Raises ProfileError when a named source has no stored breakdown —
    a profile must not silently aggregate a subset of what was asked for.
    """
    if not slugs:
        raise ProfileError("a profile needs at least one source slug")
    context = (
        storage.use_workspace(workspace)
        if workspace is not None and hasattr(storage, "use_workspace")
        else nullcontext()
    )
    with context:
        storage.validate_profile_name(name)
        sources: list[tuple[str, Breakdown]] = []
        for slug in slugs:
            try:
                sources.append((slug, storage.load_breakdown(slug)))
            except FileNotFoundError as exc:
                raise ProfileError(
                    f"no stored breakdown for source '{slug}' — study it "
                    "first; a profile must not silently drop requested "
                    "sources"
                ) from exc

        profile = _aggregate(name, sources, genre=genre, platform=platform)
        storage.save_profile(profile)
        return profile


# -- measured aggregation ---------------------------------------------------

def _stat(values: list[float]) -> StatSummary:
    if not values:
        return StatSummary()
    if len(values) == 1:
        v = round(values[0], 3)
        return StatSummary(median=v, p25=v, p75=v, n=1)
    # Inclusive method: percentiles interpolate WITHIN the observed range.
    # The exclusive default extrapolates beyond it at small n — the S2
    # gate run produced time_to_first_word p25 = −1.085s from two
    # non-negative observations, which reads as a bug to every consumer.
    q1, q2, q3 = quantiles(sorted(values), n=4, method="inclusive")
    return StatSummary(
        median=round(q2, 3), p25=round(q1, 3), p75=round(q3, 3), n=len(values)
    )


def _collect(
    sources: list[tuple[str, Breakdown]],
    warnings: list[str],
    what: str,
    value_of,
) -> list[float]:
    """Gather one scalar per source; name excluded sources honestly."""
    values: list[float] = []
    excluded: list[str] = []
    for slug, b in sources:
        value = value_of(b)
        if value is None:
            excluded.append(slug)
        else:
            values.append(float(value))
    if excluded:
        warnings.append(f"{what}: no value from {', '.join(sorted(excluded))}")
    return values


def _first_cut(b: Breakdown) -> float | None:
    return b.shots[1].start if len(b.shots) >= 2 else None


def _first_word(b: Breakdown) -> float | None:
    return min((w.start for w in b.words), default=None)


def _first_caption(b: Breakdown) -> float | None:
    return min((c.start for c in b.captions), default=None)


def _speech_ratio(b: Breakdown) -> float | None:
    if any("speech ratio skipped" in w for w in b.warnings):
        return None
    return b.audio.speech_ratio


def _normalized_curve(b: Breakdown) -> list[float] | None:
    """Cuts per bucket of RELATIVE runtime (10 buckets), so sources of
    different lengths align. None when the source has no usable timeline."""
    if b.meta.duration <= 0 or len(b.shots) < 1:
        return None
    counts = [0.0] * CURVE_BUCKETS
    for shot in b.shots[1:]:
        bucket = min(int(shot.start / b.meta.duration * CURVE_BUCKETS),
                     CURVE_BUCKETS - 1)
        counts[bucket] += 1.0
    return counts


def _transitions_ran(b: Breakdown) -> bool:
    return any(key.startswith("transition") for key in b.provenance)


def _aggregate(
    name: str,
    sources: list[tuple[str, Breakdown]],
    *,
    genre: str,
    platform: str,
) -> StyleProfile:
    warnings: list[str] = []

    curves: list[list[float]] = []
    curve_excluded: list[str] = []
    for slug, b in sources:
        curve = _normalized_curve(b)
        if curve is None:
            curve_excluded.append(slug)
        else:
            curves.append(curve)
    if curve_excluded:
        warnings.append(
            "cut curve: no usable timeline from "
            + ", ".join(sorted(curve_excluded))
        )
    curve_stats = [
        _stat([curve[bucket] for curve in curves])
        for bucket in range(CURVE_BUCKETS)
    ] if curves else []

    all_captions = [c for _, b in sources for c in b.captions]
    caption_sources = sum(1 for _, b in sources if b.captions)
    if caption_sources < len(sources):
        missing = [slug for slug, b in sources if not b.captions]
        warnings.append(
            "caption style: no caption events from "
            + ", ".join(sorted(missing))
        )
    words_visible = [c.words_visible for c in all_captions]

    music_known = [
        b.audio.has_music
        for _, b in sources
        if b.audio.music_confidence > 0.0
    ]
    music_unknown = [
        slug for slug, b in sources if b.audio.music_confidence == 0.0
    ]
    if music_unknown:
        warnings.append(
            "music rate: inconclusive measurement from "
            + ", ".join(sorted(music_unknown))
        )

    transition_counts: dict[str, int] = {}
    transitions_not_run = []
    for slug, b in sources:
        if not _transitions_ran(b):
            transitions_not_run.append(slug)
            continue
        for t in b.transitions:
            transition_counts[t.kind] = transition_counts.get(t.kind, 0) + 1
    if transitions_not_run:
        warnings.append(
            "transition counts: detection not run for "
            + ", ".join(sorted(transitions_not_run))
        )

    judged: dict[str, Any] = {}
    unjudged: list[str] = []
    prompt_versions: set[str] = set()
    for slug, b in sources:
        if not b.judgment:
            unjudged.append(slug)
            continue
        for section, content in b.judgment.items():
            judged.setdefault(section, {})[slug] = content
            if isinstance(content, dict):
                version = (content.get("_meta") or {}).get("prompt_version")
                if version:
                    prompt_versions.add(str(version))
    if judged:
        judged["_meta"] = {"prompt_versions": sorted(prompt_versions)}

    duration_values = _collect(
        sources, warnings, "duration",
        lambda b: b.meta.duration if b.meta.duration > 0 else None,
    )
    duration_stat = _stat(duration_values)
    # Coherence check (S2 gate-pack finding): quartiles smooth over an
    # 18s-next-to-635s source mix, but such a profile can't falsify
    # anything on duration. Judge the RAW spread and say so up front.
    if len(duration_values) >= 2:
        low, high = min(duration_values), max(duration_values)
        if low > 0 and high > 3 * low:
            warnings.append(
                f"profile coherence: source durations span {low:g}–{high:g}s "
                f"(more than 3× spread) — sources may not share a format"
            )
    shot_stat = _stat(_collect(
        sources, warnings, "shot duration",
        lambda b: b.avg_shot_duration if b.shots else None,
    ))
    first_cut_stat = _stat(_collect(
        sources, warnings, "time to first cut", _first_cut,
    ))
    first_word_stat = _stat(_collect(
        sources, warnings, "time to first word", _first_word,
    ))
    first_caption_stat = _stat(_collect(
        sources, warnings, "time to first caption", _first_caption,
    ))
    return StyleProfile(
        name=name,
        source_slugs=[slug for slug, _ in sources],
        genre=genre,
        platform=platform,
        duration=duration_stat,
        shot_duration=shot_stat,
        cuts_per_10s_curve=curve_stats,
        time_to_first_cut=first_cut_stat,
        time_to_first_word=first_word_stat,
        time_to_first_caption=first_caption_stat,
        caption_all_caps_rate=round(
            sum(c.all_caps for c in all_captions) / len(all_captions), 3
        ) if all_captions else 0.0,
        caption_words_visible_mode=(
            max(set(words_visible), key=words_visible.count)
            if words_visible else 0
        ),
        speech_ratio=_stat(_collect(
            sources, warnings, "speech ratio", _speech_ratio,
        )),
        music_present_rate=round(
            sum(music_known) / len(music_known), 3
        ) if music_known else 0.0,
        transition_kind_counts=dict(sorted(transition_counts.items())),
        judged=judged,
        unjudged_source_slugs=sorted(unjudged),
        warnings=warnings,
        provenance={
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "zing_version": _zing_version(),
            "curve": f"cuts per {CURVE_BUCKETS} buckets of relative runtime",
            "caption_rates": "pooled over all caption events across sources",
            "music_rate": "over sources with conclusive music measurement",
            "source_count": len(sources),
        },
    )


def _zing_version() -> str:
    try:
        from importlib.metadata import version

        return version("myzing")
    except Exception:
        return "unknown"
