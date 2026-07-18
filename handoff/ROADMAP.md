# Zing build roadmap & sprint protocol

Owner: orchestrator (Ryan's Claude chat session). Ratified by Ryan 2026-07-18.
Priority: working > pretty. No brand/design/copy work until the tool is built.

## The cycle (repeats every sprint)

0. **PLAN-CRITIQUE (Phase 0, before Sprint 1 build only):** every worker
   reads the vision doc, this roadmap, `SPRINT-1-D1.md`, and
   `src/myzing/schemas.py`, then lands `handoff/reviews/PLAN-CRITIQUE-<lane>.md`:
   what's weak or missing in the plan, what tooling/harness/library choices
   would genuinely make the build better, ranked by leverage, each item with
   a concrete recommendation. PR it (auto-merge). THEN begin lane work.
   The orchestrator synthesizes accepted items into the sprint specs.
1. **BUILD:** lanes build to their gates. Small PRs, auto-merge behind CI,
   main always green.
2. **REVIEW:** when all lane gates for the sprint pass, the orchestrator
   opens the review round: each worker reviews the OTHER lanes' merged code
   (correctness, honesty of failure states, integration seams, test gaps) and
   lands `handoff/reviews/S<N>-REVIEW-<lane>.md`. The orchestrator dedupes
   findings into `handoff/reviews/S<N>-FIXLIST.md`.
3. **FIX:** a fix sprint clears the fixlist. Nothing new starts until it's
   clear.
4. **NEXT:** orchestrator seeds the next sprint spec (`SPRINT-<N+1>-*.md`),
   folding in any accepted critique items.

## Sprint sequence

- **S1 — D-1 Study (current, spec: SPRINT-1-D1.md):** measurement engine,
  doctor/storage/MCP surface, eval harness + renderer base.
- **S2 — D-2 Profile:** `zing profile` aggregating N breakdowns into a
  StyleProfile (schema added by orchestrator after S1 learnings); judgment
  pipeline proven end-to-end (AI reads breakdowns over MCP, writes judgment
  back); analysis-quality hardening against the eval harness.
- **S3 — D-3 Direct:** map raw footage (studied like any video) onto a
  StyleProfile → draft EDL + honest gap report + numbered, filmable shot
  prompts. The anti-slop core.
- **S4 — D-4 Assemble:** render quality pass; TTS providers — local default
  (Kokoro/Piper), ElevenLabs as optional plugin; executor export package.
- **S5 — Hardening:** end-to-end runs on real videos across all three
  platforms; eval set expansion; fresh-install path (`uvx myzing` → doctor →
  study) on a clean machine; failure-state honesty sweep.
- **S6 — Uoink integration:** orchestrator writes
  `handoff/INTEGRATION-UOINK.md` first (contract: how Zing reads saved
  shorts from the uoink corpus, writes breakdowns/profiles/shot-lists back,
  the `keep_media` enabler in the uoink repo — E-1 in
  `uoink\handoff\VIDEO-DIRECTOR-VISION-2026-07-17.md`); then lanes implement
  both sides.
- **FINAL:** all models run a full-repo final review → flagged issues → one
  fix sprint → done. The panel is both Fable lanes, Sol, the orchestrator,
  **plus Antigravity as fresh eyes** — a model that never wrote a line of
  this codebase reviews it cold.

## Done criteria

Fresh machine: `uvx myzing` → `zing doctor` → `zing study <tiktok url>` →
profile → direct → render produces a watchable vertical video; eval harness
green; MCP server passes the smoke test from Claude Desktop; every failure
state is honest and actionable. **Performance budget:** `zing study` on a
30–60s short completes in low single-digit minutes on Ryan's PC (GPU
whisper) with an honest CPU fallback — a correct-but-20-minute study is a
failed gate.

## Risk register (orchestrator watches these)

- R1 · Judgment quality is the product risk, not measurement — hence the S1
  wizard-of-oz exit gate (see SPRINT-1-D1.md). If it fails, S2 pivots to
  prompt-pack/judgment iteration before any S3 work.
- R2 · Real data: Ryan supplies raw footage + 5–10 admired references
  during S1; S3 cannot start without them.
- R3 · Contract turnaround: workers blocked on schemas.py wait on the
  orchestrator — NOTES-*.md files are read FIRST every loop iteration.
- R4 · OCR on stylized captions is approximate — timeboxed in S1, iterated
  in S2; confidence values keep it honest.
- R5 · ToS honesty: fetching TikTok/IG media for local analysis carries the
  same personal-use disclaimer uoink ships (C-06 pattern) — inherit it in
  docs before any public release.

## Standing rules

- `src/myzing/schemas.py` and all `handoff/SPRINT-*`/`ROADMAP` specs are
  orchestrator-owned. Workers propose via `handoff/NOTES-<lane>.md` or
  critique/review memos — never edit directly.
- Worker identities, workflow, and current assignment live in
  `handoff/prompts/LANE-{A,B,C}.md` — the canonical prompt files.
