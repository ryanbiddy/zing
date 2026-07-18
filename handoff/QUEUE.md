# Work queue — pull the top unclaimed item in YOUR lane when your current gate passes

Claim an item by appending a line to your NOTES file ("claimed D-Q1"),
then work it like any lane item (own paths, PR flow, doc-only where
marked). Orchestrator seeds this file; workers may add PROPOSED items at
the bottom but never claim outside their lane.

## Lane A (study engine)
- **A-Q1:** R1-A measurement-science research round (still owed —
  ASSIGNMENTS-R1 §R1-A; you built ingest first, fine, but the deliverable
  gates your detector/OCR dependency picks).
- **A-Q2:** accuracy iteration against Lane C's goldens once both exist —
  drive scores up, one PR per fix, per-fix deltas cited from the eval
  report.
- **A-Q3 (S2 prep):** keyframe quality pass — verify hook-window keyframes
  are judgment-usable (sharp, representative) on the example-dataset
  videos.

## Lane B (surface)
- **B-Q1:** finish S1 per spec order: doctor → MCP server → prompt pack →
  uoink bridge.
- **B-Q2:** .mcpb / client-connect packaging prep: document the exact
  Claude Desktop + Claude Code config for zing serve-mcp, uoink-style
  one-click where possible (doc + small glue only).
- **B-Q3 (S2 prep):** get_frames(slug, timestamps[]) tool design note —
  result shape, size limits, MCP image content — ready to build at S2 open.

## Lane C (eval + render)
- **C-Q1:** finish C-1 per spec + critique resolutions (incl. Windows CI
  job, machine-readable eval reports).
- **C-Q2:** C-2 renderer per spec (pysubs2 for .ass; content-probe oracle).
- **C-Q3:** performance benchmark harness — per-stage wall-clock (ingest /
  shots / transcribe / OCR / audio / render) captured in the eval report;
  ROADMAP's perf budget becomes a tracked number before it becomes a gate.
- **C-Q4:** real-video regression bootstrap — run the eval adapter on the
  two EXAMPLE-DATASET videos, freeze breakdown outputs + provenance as the
  first real-video regression set (pairs with D-Q2 truth annotations).

## Lane D (Antigravity — doc-only lane)
- **D-Q1 (NOW):** genre rubrics v1 — synthesize YOUR R1-exemplar-teardowns
  + docs/taste/TASTE-FRAMEWORK.md into three files:
  docs/taste/RUBRIC-talking-head.md, RUBRIC-tech-launch.md,
  RUBRIC-vlog.md. Per rubric: criteria with IDs (G-TH-1…), proposed
  weights, per-criterion "Zing measures / AI judges" split, confidence
  tier per claim, every claim traced to a teardown exemplar or framework
  criterion. These become the S2 judgment scoring sheets.
- **D-Q2:** coarse human truth for the example dataset — watch both
  EXAMPLE-DATASET videos end to end; document per video: structure beats
  with rough timestamps, hook classification, caption-style description,
  approximate cut density, audio layout. Save as
  handoff/research/EXAMPLE-DATASET-TRUTH.md. This is the judgment-layer
  truth the wizard-of-oz gate and the frozen regression set score against.
- **D-Q3:** fresh-eyes documentation QA — read README + docs/ as a
  newcomer who just found the repo; file every gap/confusion as one
  doc-only PR of fixes or a findings note.

## PROPOSED (workers append; orchestrator promotes)
- **PROPOSED (orchestrator, R-3 candidate, RYAN-GATED):** calibrated-upload loudness measurement — upload known-LUFS test clips to TikTok/IG/YT and measure what comes back; turns the biggest spec unknown into owned T1-grade data. RED-adjacent (posting to Ryan's channels) — needs Ryan's explicit go + a throwaway account decision.
