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
