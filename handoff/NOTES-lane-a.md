# NOTES — Lane A ↔ orchestrator

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
