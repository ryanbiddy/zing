# NOTES — Lane A ↔ orchestrator

- **2026-07-18 (Lane A): claimed A-Q11 (gate satisfied — contract +
  MCP landed), DELIVERED.** breakdown.md now renders transitions in all
  three honest states: observations as plain-language lines ("1.40s:
  hard cut — audio-aligned, onset +0.030s"; "3.20-3.80s (over 0.60s):
  dissolve"), ran-but-none stated explicitly, not-run stated as
  "detection not run (opt-in)" in the Pacing summary without padding an
  empty section. Micro-contract for Lane C's pipeline integration: the
  renderer treats any `transition*` provenance key as "detector ran" —
  matches the schema docstring's promise that provenance records
  detector/version/thresholds; keep that naming and the states light up
  correctly with zero coordination.

- **2026-07-18 (Lane A): A-Q10 DELIVERED — cross-review of Lane C's day,
  measurement-scientist lens. PRs covered: #65 (transitions), #66
  (thumbs), #51 (caption presets, skimmed), C-Q6 speech fixture.**
  Overall: honesty discipline is genuinely good — limitations blocks ship
  IN the artifacts (transition report, thumbs manifest), refusal paths
  raise instead of padding, the speech fixture carries provenance + a
  README. Findings (file:line), judgment calls for Lane C:
  1. `tools/eval/transitions.py:282` — `_audio_onsets` returns `[]` when
     ffmpeg audio decode FAILS: a failed probe is indistinguishable from
     measured-no-onsets, so `audio_aligned_cut` silently can't fire and
     the report shows an empty onset list as if measured. The
     skipped-vs-empty conflation the Breakdown contract bans — suggest
     raising TransitionProbeError or an `audio_probe: failed` field.
  2. `tools/eval/transitions.py:408` — a signature with zero predictions
     reports `precision: 0.0`; reads as "always wrong" when it means
     "never fired", and `macro_precision` averages those zeros down.
     Suggest `null` + excluding no-prediction signatures from the macro.
  3. `tools/eval/transitions.py:77,232` — pair times are frame-index/fps
     math off `r_frame_rate` (declared, not average). Fine on synthetic
     goldens; when C-Q12 integrates into the study pipeline it MUST
     consume ingest's CFR-normalized media (guaranteed post-F-06) — worth
     a code comment now so the integration can't grab raw source media.
  4. `src/myzing/thumbs.py:636,750` — `-ss` placed AFTER `-i` = output
     seeking: decodes from t=0 for every frame, so 5 candidates on a
     10-min video ≈ 5 full decodes. Input seeking (`-ss` before `-i`) is
     frame-exact on modern ffmpeg and O(1); my keyframes.py uses it.
  5. `src/myzing/thumbs.py:428` — hook-promise window hardcoded to 30s;
     for a 45s Short the "promise" quote may come from t≈30 (most of the
     video). Suggest `formats.hook_window_s(duration)` (3s short-form).
  **Fixed directly (my file): F-15 is now closed end-to-end** — found
  storage's new ContextVar `use_workspace()` while reviewing #66;
  `study(workspace=...)` now uses it (thread-safe, no process-global
  state) with the env mutation kept only as a fallback for older storage;
  test proves env is untouched even mid-study. My earlier root-param ask
  is withdrawn — the ContextVar design is better.

- **2026-07-18 (Lane A): A-Q9 DELIVERED (measured honestly)** — long-form
  (>180s) transcription now routes through faster-whisper's
  BatchedInferencePipeline (batch_size 8, VAD-segmented); short-form
  keeps sequential (its word timing feeds caption-sync judgment and the
  batched remapping has a bug history per R1-A); batched failure falls
  back to sequential with a warning; pipeline recorded in provenance.
  Measured on 564s of real speech (MKBHD long-form audio), CPU int8:
  small model 62.9s→44.8s (**1.40x**), tiny 1.10x; word counts within
  0.3%, batched timestamps monotonic and in-range. **Caveat: this dev
  env has no ctranslate2-visible CUDA** — the literature's 3-4x batching
  wins are GPU-side, and ROADMAP's budget assumes GPU whisper on Ryan's
  PC. Ask: someone with the GPU box run
  `python -c "import ctranslate2; print(ctranslate2.get_cuda_device_count())"`
  and if >0, re-run the comparison (script in PR body) so the perf
  harness gets real GPU numbers; if Ryan's PC also shows 0, that is a
  setup item (cuBLAS/cuDNN DLLs) worth a doctor check.

- **2026-07-18 (Lane A): claimed A-Q8 + A-Q9. A-Q8 DELIVERED** —
  region-tracked caption clustering v2: concurrent text regions (burned
  captions vs watermarks vs scene text) now cluster independently by
  vertical position; persistent static overlays are excluded from
  `captions` and reported as warnings (threshold max(15s, 25% of
  runtime)); OCR box-order flicker no longer shatters events (token-set
  equality). Real-video deltas: Cleo hook captions now word-synced and
  clean ("IN ANTARCTICA," / "YOU'RE NEVER ALLOWED TO" / "PEE ON THE
  ICE!" — previously "ANTARCT IN ANTARCTICA," with watermark fragments
  concatenated); jacket scene-text is one separate coherent event; the
  raw video's "Raw Video Preview:" label (0-16.8s) is excluded with an
  honest note. Goldens: all dimensions still PASS ×3 (no regression).
  Directly addresses wizard-of-oz §4 "one OCR stream, many text layers".
  NOTE for Lane C: fresh real-video runs will diff against the frozen
  caption baselines — expected and intended; re-freeze when convenient.
  **A-Q9 next** (long-form transcription perf vs the harness).

- **2026-07-18 (Lane A): claimed V-A, DELIVERED** —
  `docs/taste/VIRALITY-youtube.md` (YouTube + Shorts, house format,
  16 tiered claims, all sourced from two research sweeps; primary
  anchors: Goodrow blog + RecSys 2016/2019 papers, Sherman's Shorts
  interview, the 2025-03-31 view-count divergence). Headline for the
  synthesis: on both surfaces the official viral signature is NOT a high
  metric but a metric HOLDING while distribution scales (CTR under
  impression growth; engaged-view share under public-view inflation) —
  and the top-weighted official signal (satisfaction surveys) is
  invisible to creators and to Zing, which caps honest virality-score
  confidence (Deeper Thread 3).

- **2026-07-18 (Lane A): claimed A-Q6 + A-Q7; A-Q6 DELIVERED (PR #54),
  A-Q7 Lane-A half DELIVERED.** A-Q6: keyframes now ship with both frozen
  baselines (63 sha-tracked thumbnails ≤360px, extracted from
  SHA-verified media at the FROZEN shot boundaries — measurements
  untouched), consistency test updated to the new policy, and the truth-doc
  linkage break from D-Q4's section rename repaired (manifest
  truth_section + provenance re-recorded with notes). **A-Q7 (F-15), for
  Lane B:** `study()`/`ingest()` now thread `workspace` explicitly and
  skip the env-var override entirely once storage's path functions accept
  an explicit root — detected via signature sniffing on
  `storage.breakdown_dir`, same pattern as your phase_callback sniff. Ask:
  add `root: Path | None = None` (None = today's ZING_HOME behavior) to
  `breakdown_dir`, `media_target`, `find_media`, and `save_breakdown`;
  the moment that merges, concurrent MCP jobs get race-free workspaces
  with zero further Lane A changes. Until then the env override remains
  the documented single-threaded fallback.

- **2026-07-18 (Lane A): A-Q4 + A-Q5 DELIVERED; A-Q3 verified; queue
  empty.** A-Q5 (phase_callback on `study()`, matches the kwarg your MCP
  runner sniffs; PR #38) and A-Q4 (formats.py: hook window 0-3s/0-30s by
  duration split at 180s per TASTE-FRAMEWORK H5; OCR body sampling 4→2fps
  on long-form; x.com/twitter.com → platform "x"; PR #40) are merged.
  A-Q3 spot-check done on the gate artifacts: Cleo hook keyframes are
  judgment-usable (0s mid-gesture talking-head with caption visible, 2s
  sharp location reveal); refinement idea for S2 — grab the sharpest
  frame within ±0.2s instead of the exact boundary frame to cut motion
  blur on gesture-heavy openers. Lane A queue is now empty — standing by
  for the review round / next assignment; A-Q2 continues as Lane C's
  golden set grows.

- **2026-07-18 (Lane A): GATE PASSED — study engine complete. claimed A-Q2.**
  Shipped across 8 PRs: ingest (yt-dlp/ffprobe, CFR-normalize policy),
  storage adoption, shot detection (tuned AdaptiveDetector), transcription
  (large-v2 + word confidence), caption OCR (rapidocr/PP-OCRv6,
  pop-caption clustering), audio (pinned loudness/speech_ratio, honest
  has_music), keyframes, breakdown.md, `study()` seam + CLI, eval-driven
  fixes. 171 offline tests; Windows+Ubuntu CI green.
  - **Gate evidence:** (1) 3 real videos spot-checked locally — Cleo short
    (hook transcript verbatim, word-pop caps captions, front-loaded cut
    density), the EXAMPLE-DATASET "raw" video, and an MKBHD short (slower
    talking-head pacing reads correctly). (2) `from_json(to_json())`
    lossless on all three real breakdowns. (3) **Lane C's eval harness:
    all scored dimensions PASS on all 3 goldens** (baseline had audio
    FAIL×3 + captions FAIL×1 — fixed: AAC-padding trailing loudness
    bucket trimmed to ceil(duration); OCR line join is now row-major so
    y-jitter can't scramble word order). speech_ratio N/A by scorer
    design until a spoken fixture lands.
  - **Finding for R-C/D-Q2 (needs orchestrator attention):** the
    EXAMPLE-DATASET "raw no-edit" video is NOT unedited as uploaded — my
    keyframes prove the 20–30s stretch is a fast-cut b-roll montage
    (watch close-ups, car interior; 15 cuts in that window). The genuinely
    raw file is behind the video's download link. Either fetch that file
    or pick a new no-edit proxy before it's used as regression truth.
  - **Finding for D-Q1:** at least one R1-exemplar-teardowns video ID is
    fabricated (kYJ-wL3m-64 → "Video unavailable"). Verify every URL
    before the rubrics cite them.
  - **Honest-missing (tracked):** OCR mixes watermarks/scene text into
    caption events (Cleo "WHITE DESERT", MKBHD logo garble) — S2
    caption-vs-scene-text separation; emoji unrepresentable (classic OCR
    limitation); music call on wall-to-wall-speech videos is honest
    unknown (S2 tagger anchor); word-spacing repair via word boxes
    pending (S2). All pre-documented in R1-lane-a-measurement.md.
  - **A-Q1 note:** already delivered before the queue existed —
    handoff/research/R1-lane-a-measurement.md merged as PR #13.
  - **claimed A-Q2** (first iteration = the eval fixes above; continuing
    as Lane C's golden set / real-video regression grows).

- **2026-07-18 (Lane A, tooling heads-up for ALL lanes):** the three lane
  worktrees share one user Python environment, so `pip install -e .`
  clobbers across lanes — mid-session my `myzing` import silently started
  resolving to lane-c's worktree (their editable install won). Fix I
  adopted: per-lane venv (`python -m venv .venv` in the worktree, already
  gitignored; `.venv/Scripts/python -m pip install -e .[dev,study]`, run
  pytest via `.venv/Scripts/python -m pytest`). Recommend Lanes B/C do the
  same before their next test run — symptoms are stale/foreign module
  errors that look like phantom test failures.

- **2026-07-18 (Lane A):** Critique resolutions received — all adopted.
  Ingest PR (#6) merged; next PR migrates it onto Lane B's storage
  (`slug_for()`, `ZING_HOME`, `zing_workspace` fixture) and retires my
  interim workspace shim. One repo-level blocker for ALL lanes:
  **GitHub's "Allow auto-merge" setting is OFF** — `gh pr merge --auto`
  fails with "Auto merge is not allowed for this repository" whenever CI is
  still running (PRs #3/#6 only went through because checks had already
  finished, letting gh fall through to a direct merge). Ask: Ryan enables
  *Settings → General → Allow auto-merge* (and ideally *Automatically
  delete head branches*). Until then I'm using
  `gh pr checks <n> --watch --fail-fast && gh pr merge <n> --squash` plus a
  manual remote-branch delete — worth telling Lanes B/C so nobody's PR
  silently sits unmerged.

- **2026-07-18 (orchestrator):** Your Phase-0 critique: all 10 items
  ACCEPTED. Contract changes are live in `schemas.py` @ main (warnings,
  Shot.keyframe, Word.confidence, music_confidence, provenance, pinned
  measurement definitions incl. your proposed loudness/speech_ratio/
  cuts_per_10s definitions, media_path relative rule). Your VFR policy,
  `study()` seam, keyframe extraction, and 8–10fps hook-window OCR sampling
  are now binding — full resolutions in SPRINT-1-D1.md §Critique
  resolutions. Windows CI matrix job added. Rebase on main before your
  first build PR. Note: Lane B's storage PR (#5) defines `slug_for()` and
  the workspace fixture — adopt it when it merges.
- **2026-07-18 (orchestrator):** auto-merge was indeed disabled at the repo level — now ENABLED (allow_auto_merge + delete_branch_on_merge). `gh pr merge --auto --squash --delete-branch` works for all lanes from here; PR #7 armed as the first proof. Thanks for flagging repo-wide instead of working around it.
- **2026-07-18 (orchestrator, merge-flow update):** GitHub won't enable the auto-merge SETTING on this private repo (plan limitation), so `--auto` fails while CI is pending. Until the repo goes public, use: `gh pr checks <n> --watch` then `gh pr merge <n> --squash --delete-branch`. Branch auto-delete on merge is now ON repo-wide. Everything else unchanged.
- **2026-07-18 (orchestrator):** standing queue is live at handoff/QUEUE.md — when your current gate passes, claim the top item in your lane there (append 'claimed <id>' here). No idling, no waiting on the orchestrator.
- **2026-07-18 (orchestrator):** Lane B's real-engine run verified your seam end-to-end. Small official item (A-Q5): add the optional phase_callback= kwarg to study() so zing_status reports real phases (ingest/shots/transcribe/ocr/audio/markdown) — Lane B's runner already sniffs for it, zero coordination needed. Also note A-Q4 (X native + YouTube long-form, format-aware hook window) was misfiled under PROPOSED — it's in your lane section now.
- **2026-07-18 (orchestrator):** gate pass + A-Q4/A-Q5 confirmed. When A-Q2 eval iteration reaches diminishing returns, your S1 review-round duty: review Lanes B+C merged code → handoff/reviews/S1-REVIEW-lane-a.md.
- **2026-07-18 (orchestrator): S1 FIX SPRINT OPEN.** Your items are in handoff/reviews/S1-FIXLIST.md (Lane A: F-06/07/08 + P3 share; Lane B: F-02 SECURITY first, then F-03/04/05/10/11/15; Lane C: F-01 CI first, then F-09/12/13/14). One fix per PR, regression test that fails before the fix, P1s before P2s. Nothing new until P1/P2 clear.
- **2026-07-18 (orchestrator, STANDING RULE — process retro):** whenever you finish a queue item, append a short PROCESS OBSERVATION to this file: what about this multi-agent process (specs, queues, NOTES, reviews, CI, orchestration) helped, hurt, or should change — one concrete recommendation each time. The orchestrator folds accepted ones into the process. Critical observations wanted, not praise.
