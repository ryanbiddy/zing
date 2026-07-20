"""Regression gate for the persistent-overlay rule, scored against the
P-C2 frozen labels.

`cluster_regions` diverts long-lived on-screen text into a warning
("persistent on-screen text (likely watermark/label) excluded from
captions"). P-C2 asked for a signal that separates a failure class
without costing caption recall. Running the SHIPPED rule over 7
hand-labeled cells (15,999 lines) gives a split verdict
(handoff/research/P-C2-BASELINE-2026-07-20.md):

- SAFE: across every captioned cell it diverts zero labeled captions.
- UNDER-FIRING: on the 430s HUD cell — 1,882 events, none of them
  real captions — it fires nothing at all.

Both halves are pinned here, so a threshold or clustering change has
to confront each. Offline: reads only committed frozen data.

Offline: reads only committed frozen data, no media, no network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from myzing.study.captions import Line, Observation, cluster_regions

RESEARCH = Path(__file__).resolve().parents[1] / "handoff" / "research"
CALIB = RESEARCH / "ocr-calibration"
FROZEN = CALIB / "frozen"
LABELS = CALIB / "labels"

# Cells whose labels contain captions; the overlay rule must not eat any.
# (The three zero-caption cells cannot exercise this property.)
CAPTIONED_CELLS = [
    "youtube-nlgyv0bmddi",
    "youtube-oyaneh0joqi",
    "youtube-fuxm3vz-keo",
    "youtube-se50vifj0aq",
]


def _observations(slug: str) -> tuple[list[Observation], float]:
    rows = (FROZEN / f"{slug}.jsonl").read_text(encoding="utf-8").splitlines()
    duration = float(json.loads(rows[0])["provenance"]["duration"])
    observations: list[Observation] = []
    for raw in rows[1:]:
        row = json.loads(raw)
        if "lines" not in row:            # a frame that failed to OCR
            continue
        observations.append(Observation(
            t=float(row["t"]),
            step=float(row["step"]),
            lines=[
                Line(
                    text=ln["text"],
                    score=float(ln["score"]),
                    y_center=float(ln["y_center"]),
                    x_center=float(ln.get("x_center", 0.0)),
                )
                for ln in row["lines"]
            ],
        ))
    return observations, duration


def _caption_texts(slug: str) -> set[str]:
    texts: set[str] = set()
    for raw in (LABELS / f"{slug}.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(raw)
        if row.get("label") == "likely_caption":
            texts.add(" ".join(row["text"].upper().split()))
    return texts


@pytest.mark.parametrize("slug", CAPTIONED_CELLS)
def test_overlay_rule_never_diverts_a_labeled_caption(slug: str) -> None:
    observations, duration = _observations(slug)
    captions = _caption_texts(slug)
    assert captions, f"{slug} should carry labeled captions"

    _events, notes = cluster_regions(observations, duration)

    diverted = [n for n in notes if "persistent on-screen text" in n]
    for note in diverted:
        # The note embeds the excluded text in quotes.
        quoted = note.split('"')[1] if '"' in note else ""
        normalized = " ".join(quoted.upper().split())
        assert normalized not in captions, (
            f"{slug}: the overlay rule diverted text the labels call a "
            f"caption: {quoted!r}. Precision on the failure class was "
            f"measured at 1.0000 with 0/577 captions lost — if a "
            f"threshold change is intended, re-run "
            f"handoff/research/pc2_baseline.py and update the note."
        )


def test_overlay_rule_under_fires_on_long_form_documented_limitation() -> None:
    """DOCUMENTED LIMITATION, pinned so it stays visible.

    The HUD-flood cell is 430s of gameplay whose 1,882 caption events
    are ALL non-captions — the exact failure class the overlay rule
    exists to catch. It catches none of them, for two compounding
    reasons found by running the real code (not by reasoning about it):

    1. the threshold is 25% of runtime = 107.6s on this video, and
    2. event clustering fragments persistent text. CORRECTED cause: the
       watermark itself reads perfectly stably ("GNN"/"TV"/"GAMING",
       60 sightings each). What breaks it is that `track_regions`
       MERGES that static watermark with the score counter beside it
       into one region, whose joined text then changes every frame
       ("TV GNN GAMING x6000042" -> "...x6000064" -> ...). That track
       has 978 observations and 972 DISTINCT texts, so `_same_event`
       closes an event almost every frame and the longest is 8.5s —
       even the 15s short-form floor could not fire.

    So the rule is SAFE (it never eats a caption — see above) but on
    long-form it is effectively unfirable, and its measured precision
    comes partly from silence. If clustering or the threshold is ever
    changed to fix this, update this test to assert that warnings DO
    appear, and re-run handoff/research/pc2_baseline.py.
    """
    observations, duration = _observations("youtube-uc6b5owmca")

    events, notes = cluster_regions(observations, duration)

    diverted = [n for n in notes if "persistent on-screen text" in n]
    longest = max((e.end - e.start) for e in events)
    assert not diverted, "if this now fires, the limitation is fixed — see docstring"
    assert longest < 15.0, (
        f"longest event {longest:.1f}s — if clustering now holds text "
        "together, the overlay rule may finally fire on long-form"
    )
