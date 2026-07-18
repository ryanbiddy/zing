# NOTES — Lane A ↔ orchestrator

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
