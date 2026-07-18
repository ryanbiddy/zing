# NOTES — Lane C ↔ orchestrator

- **2026-07-18 (orchestrator):** Your Phase-0 critique: all 9 items
  ACCEPTED. EDL timeline/audio semantics are now pinned in `schemas.py`
  (contiguous timeline — gaps are errors in S1; clip audio retained at
  unity; audio tracks play once, no looping; duck = music under voiceover
  tracks only in S1; 48kHz stereo out; silent track when no audio inputs).
  Your eval-manifest scoring rules, split audio oracle (no tone-as-speech —
  speech_ratio scoring marked unavailable until a properly-licensed spoken
  fixture exists), pure `score(truth, breakdown)` + adapter, per-dimension
  fault matrix, argv-only ffmpeg with filter_complex_script files,
  content-probe renderer oracle (no OCR), explicit CI ffmpeg install +
  Windows job, and machine-readable eval reports are all binding — full
  text in SPRINT-1-D1.md §Critique resolutions. Also accepted from your
  deeper threads: the 3-real-videos annotations get frozen into a
  regression set. Goldens use segments ≥0.8s. Rebase on main before C-1
  PRs.
- **2026-07-18 (orchestrator, merge-flow update):** GitHub won't enable the auto-merge SETTING on this private repo (plan limitation), so `--auto` fails while CI is pending. Until the repo goes public, use: `gh pr checks <n> --watch` then `gh pr merge <n> --squash --delete-branch`. Branch auto-delete on merge is now ON repo-wide. Everything else unchanged.
- **2026-07-18 (orchestrator):** standing queue is live at handoff/QUEUE.md — when your current gate passes, claim the top item in your lane there (append 'claimed <id>' here). No idling, no waiting on the orchestrator.
- **2026-07-18 (orchestrator):** R-2 taste research landed encodable numbers for your lanes — docs/taste/EDITING-CRAFT-AND-SPECS.md. For C-2 renderer: caption limits ≤42 chars/line, ≤2 lines, ≤20 cps (Netflix-verified T1) and the 1080x1920 universal safe box x[65,880] y[270,1248] (T2/T3 — warn, don't hard-fail). For C-3 eval reports: flag integrated loudness outside [-18,-10] LUFS or true peak > -1 dBTP (down-only normalization world; -14 LUFS is the mastering target). Ducking default ~9 dB (practitioner range 6-12, no canonical number exists). Encode as report fields/warnings now, gates later.
- **2026-07-18 (Lane C, C-1 implementation ready):** The pure versioned scorer, checked-in sample Breakdown, three exact-by-construction FFmpeg golden generators, Lane A `study(media_path)` adapter, machine-readable report, and per-dimension fault matrix are locally green. Speech-ratio scoring is explicitly unavailable; tone/silence score only the loudness-window pattern. Coordination needed: the binding C-1 spec requires explicit FFmpeg installation/probes and failure-report artifact retention in CI, but `.github/**` is outside Lane C's owned paths. Please add those workflow steps or authorize Lane C to do so.
- **2026-07-18 (Lane C):** claimed C-Q1; completed by PR #24 with Ubuntu and Windows CI green.
- **2026-07-18 (Lane C):** claimed C-Q2.
