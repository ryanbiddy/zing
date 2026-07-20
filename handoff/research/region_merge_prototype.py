"""Prototype + evidence for the queued region-merge fix.

THE DEFECT (measured, see P-C2-BASELINE-2026-07-20.md): on long-form,
`cluster_regions` emits zero persistent-overlay warnings even when
every caption event is HUD text. `track_regions` merges a static
watermark with the changing counter beside it, so the region's JOINED
TEXT differs almost every frame and no event ever ages.

THE IDEA: measure persistence on the STABLE TOKEN SET of a region
rather than its joined string. Intersect the token sets of consecutive
observations; a watermark's tokens survive the intersection while a
counter's digits do not.

THIS SCRIPT IS EVIDENCE, NOT A PATCH. It reads the frozen P-C2 cells
and reports what the idea would do, so whoever takes the queue item
starts from a measured result instead of a description. Nothing in
`src/` is modified.

Run:  python handoff/research/region_merge_prototype.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from myzing.study.captions import (  # noqa: E402
    Line,
    Observation,
    _overlay_threshold_s,
    cluster_regions,
    track_regions,
)

FROZEN = Path(__file__).resolve().parent / "ocr-calibration" / "frozen"
LABELS = Path(__file__).resolve().parent / "ocr-calibration" / "labels"

HUD_CELL = "youtube-uc6b5owmca"
CAPTIONED = [
    "youtube-nlgyv0bmddi",
    "youtube-oyaneh0joqi",
    "youtube-fuxm3vz-keo",
    "youtube-se50vifj0aq",
]


def load(slug: str) -> tuple[list[Observation], float]:
    rows = (FROZEN / f"{slug}.jsonl").read_text(encoding="utf-8").splitlines()
    duration = float(json.loads(rows[0])["provenance"]["duration"])
    out: list[Observation] = []
    for raw in rows[1:]:
        row = json.loads(raw)
        if "lines" not in row:
            continue
        out.append(Observation(
            t=float(row["t"]), step=float(row["step"]),
            lines=[
                Line(
                    text=ln["text"], score=float(ln["score"]),
                    y_center=float(ln["y_center"]),
                    x_center=float(ln.get("x_center", 0.0)),
                )
                for ln in row["lines"]
            ],
        ))
    return out, duration


def caption_tokens(slug: str) -> set[str]:
    out: set[str] = set()
    for raw in (LABELS / f"{slug}.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(raw)
        if row.get("label") == "likely_caption":
            out |= set(row["text"].upper().split())
    return out


def longest_stable(track) -> tuple[float, frozenset[str]]:
    """Longest span over which SOME token set survives intersection."""
    tokens = [frozenset(o.text.upper().split()) for o in track.observations]
    times = [o.t for o in track.observations]
    best: tuple[float, frozenset[str]] = (0.0, frozenset())
    current, start = tokens[0], times[0]
    for i in range(1, len(tokens)):
        nxt = current & tokens[i]
        if nxt:
            current = nxt
            if times[i] - start > best[0]:
                best = (times[i] - start, current)
        else:
            current, start = tokens[i], times[i]
    return best


def main() -> int:
    observations, duration = load(HUD_CELL)
    threshold = _overlay_threshold_s(duration)
    _events, notes = cluster_regions(observations, duration)
    shipped = len([n for n in notes if "persistent on-screen text" in n])
    caught = [
        (span, sorted(tokens))
        for span, tokens in map(longest_stable, track_regions(observations))
        if span >= threshold
    ]
    print(f"HUD cell ({duration:.0f}s, threshold {threshold:.1f}s)")
    print(f"  shipped rule    : {shipped} overlay warning(s)")
    print(f"  prototype       : {len(caught)} region(s) flagged")
    for span, tokens in caught:
        print(f"      stable {tokens[:4]} persisted {span:.1f}s")

    print("\nsafety check — does it eat real captions?")
    any_bad = False
    for slug in CAPTIONED:
        obs, dur = load(slug)
        thr = _overlay_threshold_s(dur)
        caps = caption_tokens(slug)
        bad = [
            sorted(tokens)[:5]
            for span, tokens in map(longest_stable, track_regions(obs))
            if span >= thr and (tokens & caps)
        ]
        any_bad = any_bad or bool(bad)
        print(f"  {slug:24} {'CAPTION TOKENS FLAGGED: ' + str(bad) if bad else 'none'}")

    print("\nLIMITS (do not read this as ready to ship):")
    print("  - 5 cells only; all English, all short-form except the HUD cell.")
    print("  - Replaces the PERSISTENCE MEASURE only. Clustering, event")
    print("    boundaries and warning text are untouched, and their")
    print("    interaction with this measure is unmeasured.")
    print("  - NOT run against Lane C's frozen eval fixtures, so regression")
    print("    risk on the real-video regression set is unknown.")
    print("  - A token that legitimately recurs across a whole video (a")
    print("    speaker's name in every caption) would look stable here.")
    return 0 if not any_bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
