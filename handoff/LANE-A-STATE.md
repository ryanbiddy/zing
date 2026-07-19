# LANE-A-STATE — one-page digest at the freeze (2026-07-19)

For any successor (human, model, or future session) picking up the study
engine without archaeology. Chronology lives in NOTES-lane-a.md; this is
the state.

## Owned surfaces

`src/myzing/study/*` (ingest, shots, transcribe, captions, audio, raw,
keyframes, transitions, report, api, command), `src/myzing/profile/*`
(api, packs, command), `src/myzing/assemble/*` (draft, command),
`presets/*.json` (7 pack manifests), their tests, and
`handoff/research/ocr-calibration/` (P-C2 dataset + freeze tooling).

## Shipped and gate-proven

- Full measurement pipeline, S1–S6, every gate passed (S5: never-seen
  video end-to-end; S6: family scenario 11/11 incl. my kept-media hop).
- Kept-media seam per ratified `uoink.media.handoff` v1: path-free
  provenance, sha256+size integrity BEFORE analysis, contract
  source_handoff records on happy path and every named fallback.
- 7 preset packs (5 base + 2 orientation variants), 32 live-verified
  refs, manifest-sha provenance, reproducible rebuilds.
- Draft-EDL: contiguous clips, measured-keeper cross-check ("flagged,
  not blocked"), word-timed captions with trim-edge clamping (D-10),
  thin-style-basis warning (O-3), exact even preset output frames
  (gate-added `_output_dimensions`).
- Coverage 95–100% across all modules, incl. one real-backend pass per
  wrapper seam (VAD / frame-decode / scenedetect — the last caught a
  live API deprecation; rule proposed as process, Lane B #266).

## Open threads (all external-gated)

- 4 QUEUE proposals pending orchestrator promotion: study-time
  self-check (amended per audit #212 — stage-evidence reconciliation),
  passive loudness atlas, pack `--reverify` (reused-refs blind spot),
  and the unmocked-seam rule (Lane B's, endorsed with sharpened
  evidence).
- P-C2: dataset complete (5 frozen cells, 15,231 frame-grounded labels;
  zero captions in failure cells, 368 in known-good). Lane C's
  comparison harness has not run; PP-OCR multilingual second pass is
  the gated adopt-candidate for the unsupported_script class.
- Transitions v4 has synthetic-only calibration; the SHOT dataset (MIT,
  853 short-form videos) is the filed evaluation-before-adoption path.
- 4:5 aspect (Instagram-native 1080x1350) hard-errors in
  `_output_dimensions` — observation filed with two fix shapes; needs a
  fixlist slot (cross-lane with Lane C's preset validation).
- Instagram fetches: hard login wall; cookies route is Ryan's call.

## Known truthful hard cases (recorded, not "fixed")

Zach King invisible cuts = 1 shot IS the measurement; no-cut gameplay
formats measure cut-rate 0; wall-to-wall speech yields inconclusive
music detection. Genre-keyed warnings are the honest fix shape if ever
needed.

## Operational gotchas (details in NOTES)

Per-lane venv only (`./.venv/Scripts/python`); CI test matrix has no
[study] extra — importorskip-guard every heavy import including numpy;
test_doctor.py ytdlp tests are host-dependent (fail with real node +
user yt-dlp config; clean on CI); yt-dlp needs a JS runtime for YouTube
(SW-3); verify auto-merges actually landed; serialize NOTES-bearing PRs.
