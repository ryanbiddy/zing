# Morning digest — 2026-07-18 (night shift 1)

## TL;DR

**Sprint 1's build phase completed overnight — all three lane gates
passed.** 44 PRs opened, 40+ merged, main never broke. Zing studies a real
video end-to-end (measured breakdown + keyframes + honest warnings), serves
it to any AI over MCP with background jobs, and renders EDLs with
word-timed captions and ducking, verified by content probes on two OSes.
The taste framework exists with verified sources. The review round is in
flight; the wizard-of-oz gate is the last S1 box and needs Ryan.

## What shipped (by lane)

- **Lane A (study engine, Fable):** ingest with VFR-safe PTS timestamps +
  CFR normalization; shot detection + pacing; audio layout (VAD speech
  ratio, astats loudness, honest music call); OCR captions; keyframes per
  shot; `study()` seam; breakdown.md renderer; `zing study` CLI; gate
  passed on 3 real videos; eval-driven fixes; **X native + YouTube
  long-form as first-class sources with format-aware hook windows (0–3s
  short / 0–30s long, per YT's own Intro metric)**; phase_callback.
- **Lane B (surface, Fable):** storage with deterministic slugs +
  judgment-preserving re-study; tiered doctor (`--json`, yt-dlp staleness);
  MCP server (official MIT SDK) with **background study jobs** — built
  because Lane B *overturned an orchestrator ruling with evidence* (Claude
  Desktop's hardcoded 60s timeout); prompts capability + `zing prompt`;
  uoink bridge; client-connect docs + `--print-config`; real-engine e2e
  verified; get_frames S2 design note.
- **Lane C (eval + render, GPT-5.6 Sol):** exact-by-construction golden
  fixtures; pure versioned scorer with per-dimension fault matrix; Ubuntu +
  Windows CI with pinned ffmpeg; EDL renderer (pysubs2 karaoke captions,
  clip-audio retention, ~9dB ducking, 48kHz stereo, universal safe box
  warnings) verified by pixel/RMS/ASS content probes; perf harness
  (tracked-not-gated); real-video regression baselines frozen.
- **Lane D (Antigravity):** exemplar teardowns; genre rubrics v1
  (talking-head / tech launch / vlog); human truth annotations for the
  example dataset; developer guide + docs QA.
- **Research:** 105-agent verified taste round → `docs/taste/
  TASTE-FRAMEWORK.md` (5 pillars, confidence tiers); R-2 follow-up →
  Murch weights primary-confirmed, safe box + LUFS + caption numbers,
  anti-slop corrected by 56-paper meta-analysis (humans detect AI video at
  ~57% — quality must be enforced by design, not detection). OSS survey
  (34 repos) already changed the build (pysubs2 in, Piper out on license).
- **Uoink:** `keep_media` E-1 MERGED (#187) — short-video captures keep
  their mp4, opt-in, default off.

## In flight

- S1 cross-reviews: Lane C's landed; fresh-eyes agents are covering Lane
  A/B duties (their sessions ended). → S1-FIXLIST → fix sprint.
- Then: wizard-of-oz exit gate (below), then S2 opens (StyleProfile schema
  from orchestrator + rubric-grounded judgment).

## Wizard-of-oz gate — Ryan's 20 minutes

1. `zing study` the Cleo Abram reference + the raw talking-head video
   (EXAMPLE-DATASET.md has URLs; media refetches by URL).
2. Connect Claude to `zing serve-mcp` (docs/CONNECT.md), load
   `prompts/study.md`, judge both breakdowns; compare against AG's
   EXAMPLE-DATASET-TRUTH.md.
3. Verdict: are the judgment + gap-report outputs genuinely useful
   direction? If yes → S2 proceeds as planned; if no → S2 pivots to
   judgment quality first.

## Decisions waiting on Ryan

1. **Make ryanbiddy/zing public?** MIT anyway; restores true auto-merge;
   build-in-public optionality. (Everything works private, just slower
   merge flow.)
2. **Register myzing.app** — still unregistered as of last night.
3. R-3 calibrated-upload loudness measurement (QUEUE §PROPOSED) — needs
   your go (posting test clips) + throwaway-account decision.
4. Your S1 tasks from the plan: record 2–3 min raw talking-head footage;
   pick 5–10 admired shorts and uoink them (references for S2 profiles).

## Watch-list

- uoink's bundled yt-dlp is >90 days old (extractor rot risk for TikTok
  captures) — worth a bump in the next uoink release.
- Caption font not pinned in renderer (parked S2, OFL font).
- Speech-ratio eval scoring intentionally unavailable until a
  properly-licensed spoken fixture lands.
