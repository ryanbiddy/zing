# Work queue â€” pull the top unclaimed item in YOUR lane when your current gate passes

Claim an item by appending a line to your NOTES file ("claimed D-Q1"),
then work it like any lane item (own paths, PR flow, doc-only where
marked). Orchestrator seeds this file; workers may add PROPOSED items at
the bottom but never claim outside their lane.

## Lane A (study engine)
- **A-Q1:** R1-A measurement-science research round (still owed â€”
  ASSIGNMENTS-R1 Â§R1-A; you built ingest first, fine, but the deliverable
  gates your detector/OCR dependency picks).
- **A-Q2:** accuracy iteration against Lane C's goldens once both exist â€”
  drive scores up, one PR per fix, per-fix deltas cited from the eval
  report.
- **A-Q3 (S2 prep):** keyframe quality pass â€” verify hook-window keyframes
  are judgment-usable (sharp, representative) on the example-dataset
  videos.

- **A-Q4:** X native + YouTube long-form as study sources — format-aware hook window (0-3s short-form / 0-30s long-form per TASTE-FRAMEWORK H5), aspect-agnostic study, long-form perf documented. **A-Q5:** optional phase_callback= kwarg on study() for real per-phase zing_status.

## Lane B (surface)
- **B-Q1:** finish S1 per spec order: doctor â†’ MCP server â†’ prompt pack â†’
  uoink bridge.
- **B-Q2:** .mcpb / client-connect packaging prep: document the exact
  Claude Desktop + Claude Code config for zing serve-mcp, uoink-style
  one-click where possible (doc + small glue only).
- **B-Q3 (S2 prep):** get_frames(slug, timestamps[]) tool design note â€”
  result shape, size limits, MCP image content â€” ready to build at S2 open.

- **B-Q4:** x.com/twitter.com status slugs + platform 'x' in storage. **B-Q5:** early S1 cross-review of Lanes A+C -> handoff/reviews/S1-REVIEW-lane-b.md.

## Lane C (eval + render)
- **C-Q1:** finish C-1 per spec + critique resolutions (incl. Windows CI
  job, machine-readable eval reports).
- **C-Q2:** C-2 renderer per spec (pysubs2 for .ass; content-probe oracle).
- **C-Q3:** performance benchmark harness â€” per-stage wall-clock (ingest /
  shots / transcribe / OCR / audio / render) captured in the eval report;
  ROADMAP's perf budget becomes a tracked number before it becomes a gate.
- **C-Q4:** real-video regression bootstrap â€” run the eval adapter on the
  two EXAMPLE-DATASET videos, freeze breakdown outputs + provenance as the
  first real-video regression set (pairs with D-Q2 truth annotations).

## Lane D (Antigravity â€” doc-only lane)
- **D-Q1 (NOW):** genre rubrics v1 â€” synthesize YOUR R1-exemplar-teardowns
  + docs/taste/TASTE-FRAMEWORK.md into three files:
  docs/taste/RUBRIC-talking-head.md, RUBRIC-tech-launch.md,
  RUBRIC-vlog.md. Per rubric: criteria with IDs (G-TH-1â€¦), proposed
  weights, per-criterion "Zing measures / AI judges" split, confidence
  tier per claim, every claim traced to a teardown exemplar or framework
  criterion. These become the S2 judgment scoring sheets.
- **D-Q2:** coarse human truth for the example dataset â€” watch both
  EXAMPLE-DATASET videos end to end; document per video: structure beats
  with rough timestamps, hook classification, caption-style description,
  approximate cut density, audio layout. Save as
  handoff/research/EXAMPLE-DATASET-TRUTH.md. This is the judgment-layer
  truth the wizard-of-oz gate and the frozen regression set score against.
- **D-Q3:** fresh-eyes documentation QA â€” read README + docs/ as a
  newcomer who just found the repo; file every gap/confusion as one
  doc-only PR of fixes or a findings note.

## PROPOSED (workers append; orchestrator promotes)
- **PROPOSED (orchestrator, R-3 candidate, RYAN-GATED):** calibrated-upload loudness measurement â€” upload known-LUFS test clips to TikTok/IG/YT and measure what comes back; turns the biggest spec unknown into owned T1-grade data. RED-adjacent (posting to Ryan's channels) â€” needs Ryan's explicit go + a throwaway account decision.


## Lane C — post-fix-sprint queue (orchestrator, 2026-07-18 morning)
- **C-Q5:** F-13 + F-14 + output presets. Fix the 9:16-hardcoded caption geometry (derive ALL geometry from the EDL width/height — this unblocks Ryan's long-form scope) and the word-timed caption strobe during inter-word gaps (hold the last word or fade, per pysubs2 capability). Add output preset validation for 9:16 / 16:9 / 1:1 with content probes for a landscape render.
- **C-Q6:** speech fixture — close your own eval gap. Source a properly-licensed spoken clip (public domain / CC0, e.g. LibriVox; document license + provenance in the fixture dir), mux with ffmpeg-generated exact silence so intervals stay exact-by-construction, and ENABLE speech_ratio scoring (currently honest-unavailable). Mutation test included.
- **C-Q7:** loudness + true-peak probe fields in the eval report (flag integrated outside [-18,-10] LUFS or TP > -1 dBTP per docs/taste/EDITING-CRAFT-AND-SPECS.md — report fields/warnings, not gates), if not already present from C-Q3.
- **C-Q8:** F-17 tail sweep — read all three S1 review files' remaining P3 notes, fix the Lane C-owned ones (incl. any not itemized in the fixlist), one small PR.
