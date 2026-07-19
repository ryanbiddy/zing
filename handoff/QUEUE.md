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

## Lane A — post-fix-sprint queue (orchestrator, 2026-07-18 morning)
- **A-Q6:** keyframes into the judgment loop — the wizard-of-oz run showed visual criteria go dark because keyframes are not committed with frozen regression baselines and not surfaced to the judging AI. Ship keyframes alongside breakdown.json in the baselines (small, license-safe JPEGs), and verify hook-window keyframes are sharp/representative on both real videos.
- **A-Q7 (with Lane B):** F-15 — pass workspace explicitly through study() instead of the thread-unsafe env-var override.
- **A-Q2 (continuing):** accuracy iteration vs goldens + real-video baselines; per-fix deltas cited from eval reports.

## Lane B — post-fix-sprint queue (orchestrator, 2026-07-18 morning)
- **B-Q6:** prompt pack v0.2 from wizard-of-oz findings (handoff/WIZARD-OF-OZ-2026-07-18.md §4): add curiosity_gap/open-loop to the hook vocabulary; scale sync-judgment claims to OCR sampling resolution; OCR layer-separation guidance (UI labels vs burned captions); retake vocabulary for raw-footage judgment. Version-bump the pack.
- **B-Q4 (still open):** x.com/twitter.com status slugs + platform 'x' in storage.
- **B-Q7 (with Lane A):** F-15 workspace threading — your MCP job runner side.
- (B-Q5 cross-review: DONE by stand-in agent; read handoff/reviews/S1-REVIEW-lane-b.md and flag disagreements in your NOTES.)

## Lane D (Antigravity) — queue (orchestrator, 2026-07-18 morning)
- **D-Q4:** F-16 — your EXAMPLE-DATASET-TRUTH.md is wrong about the "raw" clip (measurements prove 33 cuts + captions + music; see handoff/WIZARD-OF-OZ-2026-07-18.md §2). Re-watch, correct the truth doc, and source ONE genuinely unedited talking-head replacement (verify by eye before writing it down); document both.
- **D-Q5:** R-4 kickoff (handoff/research/ASSIGNMENTS-R3.md §R-4) — creator-genre taste corpus, first two genres: TECH and COMEDY. Top 3 creators each on YouTube + TikTok, teardown per your R1-D format, feeding genre rubric v2. Doc-only.

## Gated prototypes (claim only when the named research has landed on main)
- **C-Q9 (gated on docs/taste/TRANSITIONS-AND-MIX.md):** transition-detection prototype — implement frame-diff/optical-flow/audio features for the top 5 detectable transition signatures from R3-A; extend make_goldens with synthetic transitions (dissolve, wipe, zoom punch); report per-signature precision on goldens. Honest about what is NOT detectable.
- **C-Q10 (gated on docs/taste/PACKAGING-INTROS-THUMBNAILS.md):** `zing thumbs` deterministic half — candidate freeze-frame selection per the R3-B spec (emotional peaks via audio energy, object reveals via shot boundaries, contrast/sharpness scoring), CLI + MCP tool emitting frames + the three crafted image-LLM prompts from the spec template.
- **D-Q6:** Zing product-surface UX study (doc-only): audit the CLI/breakdown.md/MCP ergonomics as a NEW USER; study uoink's brand system at E:\AI\projects\uoink\brand (brand-system HTML + launch kit) and propose how Zing's look/voice should rhyme with it (sibling, not clone); sketch the eventual local dashboard surface (uoink-style) as a doc. Design implementation stays LATER — this is the thinking doc.

## V-round: define VIRALITY per platform (Ryan, 2026-07-18) — one per lane, doc-only
The taste director must know what virality measurably IS on each channel.
Per platform: a measurable definition (metrics/thresholds that mark a video
as viral there), the spread mechanism (what surfaces drive it), leading
indicators in the first hours, genre differences, and what the taste engine
should score as viral-potential. House format: tiers, sources, Deeper
Threads. Deliverable: docs/taste/VIRALITY-<platform>.md.
- **V-A · Lane A:** YouTube + Shorts.
- **V-B · Lane B:** TikTok.
- **V-C · Lane C:** X native video (fold in handoff/research/R3-grok-x-findings.md when it lands).
- **V-D · Lane D (AG):** Instagram Reels.
Orchestrator synthesizes the cross-platform comparison after all four land.

## S2-prep wave (orchestrator, 2026-07-18 evening — sanctioned ahead of the formal S2 spec; keep lanes busy)
- **C-Q11:** V-C X virality definition if not yet claimed (docs/taste/VIRALITY-x.md; fold handoff/research/R3-grok-x-findings.md).
- **C-Q12:** transition detector v2 — integrate the #65 prototype into the study pipeline behind a flag: Breakdown gains typed transition observations via the judgment-free measurement path (orchestrator will add a schema field on request — write the proposed field shape to NOTES first, do NOT touch schemas.py).
- **C-Q13:** real-video eval expansion — add 3 more real videos to the frozen regression set (one landscape long-form, one X-native if fetchable, one more short), full provenance discipline.
- **A-Q8:** OCR caption quality iteration against the real-video set — drive caption recall/precision up, per-fix eval deltas.
- **A-Q9:** long-form study performance — chunked/streamed transcription strategy for 10min+ videos, measured against the perf harness.
- **B-Q8:** build get_frames(slug, timestamps[]) per your own B-Q3 design note (S2 fast-follow pulled forward — judgment needs eyes; wizard-of-oz proved it).
- **B-Q9:** .mcpb packaging — build the one-click bundle for Claude Desktop per docs/CONNECT.md, tested install flow documented.

## Lane D — light-work wave (orchestrator, 2026-07-18 evening; sized for fast collation/verification)
- **D-Q7:** taste-docs master index — build docs/taste/INDEX.md: one table of EVERY criterion ID across all taste docs (ID, one-line claim, tier, source doc, link). Pure collation, high value: the judgment prompts need a single lookup surface. Keep it regenerable (note your method at the top).
- **D-Q8:** link-rot + source verification pass across all docs/taste/*.md — check every source link resolves, mark dead ones inline with [DEAD 2026-07-18] + a replacement if findable, summary note in NOTES.
- **D-Q9:** reference candidates for Ryan — find 10 candidate reference shorts across our genres (tech, comedy, informative, product, vlog) that exemplify the rubrics; verify each URL is live; one-line "why this one" per pick citing a rubric criterion. Save handoff/research/REFERENCE-CANDIDATES.md. This feeds Ryan's S3 pick-list.
- **D-Q10:** breakdown.md readability QA — read the frozen real-video breakdown.md files as a CREATOR would; list every jargon term, unclear number, or missing explanation; doc-only findings note.
- **D-Q11 (mechanical re-tier):** VIRALITY-instagram.md claims V-IG-3, V-IG-7, V-IG-8 assert exact numbers (10x follower ratio, completion-gate thresholds) as fact that VIRALITY-TIKTOK.md tags FOLKLORE and VIRALITY-X.md bans outright — see VIRALITY-SYNTHESIS.md contradictions section. Re-tier those three claims to T4/folklore with the same wording pattern the TikTok doc uses, add a cross-reference note to the synthesis, and update INDEX.md rows accordingly. Do not change any other claims.

## STANDING GENERATORS (all lanes — NEVER idle: when your lane queue is empty, run ONE of these per cycle, rotating)
- **SG-1 · cross-review for tightness:** pick the most recent 2-3 merged PRs from OTHER lanes you have not yet reviewed; review the actual diffs for correctness, simplification, test gaps, honesty of failure states. Small safe fixes = direct fix PR; judgment calls = findings in your NOTES with file:line. Log which PRs you covered so reviews do not repeat.
- **SG-2 · coverage sweep:** find the lowest-covered module in YOUR lane, add happy-path + one error-path test. Coverage number must rise (state before/after).
- **SG-3 · simplification pass:** the smallest change that genuinely reduces complexity in your lane (dead code, duplicated logic, over-clever constructs). Tests green, no behavior change, PR explains the reduction.
- **SG-4 · trending-OSS scan:** GitHub trending + topic searches (video, creator tools, social, subtitles, media-ml). Evaluate 3-5 repos not yet in PRIOR-ART-OSS.md: license, health, REUSE/BORROW/SKIP for us. Append to handoff/research/PRIOR-ART-OSS.md with date stamps.
- **SG-5 · feature-gap analysis (challenge required):** propose ONE roadmap candidate grounded in evidence (sentiment docs, competitor surface, taste research), then write your OWN refutation (why it might be wrong/bloat/premature). Only if the proposal survives your refutation, add it to QUEUE §PROPOSED with both halves. No unchallenged proposals.

## Cross-review wave (concrete, claim now)
- **A-Q10:** SG-1 aimed: review Lane C's shipped day — transition prototype (#65), thumbs (#66), output presets, speech fixture. Measurement-scientist lens: are the signatures/selectors honest about their limits in code, not just in NOTES?
- **B-Q10:** SG-1 aimed: review Lane A's caption-region clustering (#70) + keyframe work — surface/consumer lens: does what MCP serves match what was measured?
- **B-Q11 (gated on C-Q12 merge):** prompt pack v0.3 — teach prompts/study.md the transitions vocabulary + thumbs + get_frames tools (what the judging AI can now see and how to use it honestly).
- **A-Q11 (gated on C-Q12 merge):** breakdown.md renders transition observations (plain-language line per transition, honest about opt-in/absence).

## PROPOSED (SG-5 — proposal + refutation required, orchestrator disposes)
- **P-B1 (Lane B, 2026-07-18) · loop-ability as a measured Breakdown
  field.**
  **Proposal:** a deterministic loop score in the study pipeline:
  (a) visual seam — frame difference between the last and first frames
  (the keyframe machinery already extracts both); (b) audio seam —
  loudness-curve continuity across the end→start joint; (c) a
  `loop_seam` observation (visual_delta, audio_delta_db) with NO
  interpretation attached (measured, not judged; the prompt pack judges
  whether a tight seam is intentional). Evidence: the TikTok Algo-101
  formula weights play-time/rewatches (docs/taste/VIRALITY-TIKTOK.md,
  verified-data tier); seamless loops are a prized short-form editing
  pattern; VIRALITY-TIKTOK Deeper Thread 3 flagged that nobody in the
  trending set (SG-4 scan) measures loop design; marginal cost is low —
  both inputs (keyframes, loudness curve) already exist per breakdown.
  **Refutation (mine):** (1) first/last-frame similarity is a weak
  proxy — perceived loops are about motion continuity, not static
  similarity; a cut-on-motion loop scores badly on frame diff while
  looping beautifully. (2) Base-rate risk: if Ryan's actual reference
  set contains no loop-designed videos, the field is dead weight —
  nobody has checked the frozen set. (3) S3 (Direct) is the priority;
  any Lane A capacity spent here delays the product's core loop.
  (4) Needs an orchestrator schema change for a maybe-feature.
  **Survives as:** a GATED proposal only — step 1 is a zero-schema
  check: run the seam measurements ad hoc against the frozen reference
  set + Ryan's picks when they land; if ≥2 references show tight seams
  (they were designed to loop), promote to a schema request for S3;
  if none do, drop it with the evidence recorded. No build before the
  base-rate check.
- **B-Q12 (small):** yt-dlp is not in the [study] extras and the gate-pack run failed honestly on it — add it (one-dep PR) and confirm doctor's staleness check covers the JS-runtime deprecation warning surfaced on every fetch.
- **B-Q13 (tiny):** prompts/compare.md's worked example uses a 0-2 scale while the genre rubric scores 1-5 — fix the example, bump prompt pack patch version.
- **C-Q14 (calibration):** gate-pack run measured 29 dissolves on a talking-head video — likely detector over-calling on real footage. Calibrate the dissolve signature against the frozen real-video set; report precision honestly; tighten or downgrade to warning.
- **D-Q12 (light):** REFERENCE-CANDIDATES.md re-verification — gate-pack found 2 of 3 sampled entries stale/misattributed (#7 wrong channel, #9 re-upload). Re-verify all 10 rows, fix or replace, note method.
- **A-Q12 (S3 groundwork):** raw-footage measurement mode — the Direct sprint needs study to measure RAW recordings for retake-spotting: dead-air spans (silence >1.5s with timestamps), filler-word counts/locations from the transcript (um/uh/like/you know), and repeated-take detection (near-duplicate transcript segments with similarity + locations). Surface in Breakdown warnings/derived fields per existing patterns; propose any schema need via NOTES first. This is the measurement half of S3.
- **A-Q13:** SG-1 rotation — cross-review the most recent merges you have not covered (#95-#102 range), measurement-honesty lens.
- **C-Q15 (pairs with A-Q12):** raw-footage measurement goldens — synthetic fixtures with constructed dead-air spans, filler-word insertions (spoken fixture remixes), and repeated-take segments with exact truth; scorer dimensions for each, per-dimension mutations. The eval half of S3 groundwork.
- **C-Q16:** transition detector recall validation — your own C-Q9 report said synthetic precision says nothing about recall; validate against the frozen real-video set + the gate-pack videos, report recall honestly, tune or downgrade signatures that fail.
