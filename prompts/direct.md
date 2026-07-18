---
name: direct
description: "STUB (S3): how to direct raw footage against a style profile — gap report + filmable shot prompts. Not usable yet."
version: 0.0.1
---

# Directing raw footage (D-3) — NOT IMPLEMENTED YET

This prompt ships early so the shape is public; the tools it needs
(`StyleProfile`, EDL drafting) arrive in Sprint 3. If you were sent here
by a tool result, that tool is telling you the truth: this doesn't work
yet.

## What this will do

Given (a) a breakdown of the user's RAW footage (studied like any video)
and (b) a style profile aggregated from breakdowns of references they
admire, you will produce — grounded in measurements, never invented:

1. **A draft mapping** — which spans of the raw footage can serve which
   beats of the profile's template (hook / build / payoff / cta), cited
   by timestamp.
2. **An honest gap report** — what the profile calls for that the
   footage does not contain. Each gap cites the profile requirement and
   the measurement showing its absence ("profile wants a spoken hook
   inside 1.5s; first words in raw footage start at 6.2s"). Never fill a
   gap with generated content — the gap IS the deliverable.
3. **Numbered shot prompts** — concrete, filmable instructions that
   close each gap, specific enough to shoot without interpretation:
   what to say (or the beat of it), framing, energy, target duration.
   Each prompt names the gap it closes.

## Output shape (draft — will change before S3)

```json
{
  "mapping":      [{"beat": "hook", "src_start": 0.0, "src_end": 2.1, "evidence": "..."}],
  "gaps":         [{"id": 1, "beat": "hook", "requirement": "...", "evidence_absent": "..."}],
  "shot_prompts": [{"id": 1, "closes_gap": 1, "instruction": "...", "target_duration": 2.0}]
}
```

The anti-slop stance is the product: an edit assembled from what exists,
plus direction for what doesn't — never fabrication of what's missing.
