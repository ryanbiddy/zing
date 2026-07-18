# NOTES — Lane B ↔ orchestrator

- **2026-07-18 (Lane B): GATE PASSED — S1 lane complete.** Shipped (PRs
  #5, #12, #16, #23, #26, #29 + this one): storage (slugs, judgment-
  preserving re-study, status.json job state, resolve_relpath), tiered
  doctor (+--json, yt-dlp staleness), MCP stdio server — 7 tools, B#2 job
  pattern, prompts capability, errors-as-data — prompt pack v0 (study
  0.1.0 with required_keys contract + worked example proven against
  save_judgment end-to-end; direct stub), `zing prompt` CLI, uoink bridge
  (POST /notes, X-Uoink-Token, honest failures). Gate evidence: the C-01
  stdio smoke test (initialize → tools/list → tools/call zing_status →
  prompts/list) is green in CI on ubuntu+windows; doctor bare-machine
  honesty is tested + verified live on this PC. Also in this PR: real
  Windows bug found by running the tool for real — `zing prompt study`
  crashed on cp1252 consoles (U+2192 in study.md); fixed in cli.main
  (reconfigure errors="replace", benefits every lane's output — video
  titles with emoji would have crashed `zing study` too) + subprocess
  regression test forcing PYTHONIOENCODING=cp1252.
  **Honest-missing:** (a) study_video auto-wires Lane A's study/api.py
  seam (signature-sniffs an optional phase callback) but has only run
  against a fake engine — first real integration run still owed once
  api.py merges; (b) push_to_uoink needs breakdown.md, which Lane A
  writes on study completion; (c) prompt pack is repo-relative only
  (wheel/.mcpb packaging = S5/B-Q2 territory); (d) get_frames is S2
  (B-Q3); (e) Deeper-thread 4 (citation validation in save_judgment)
  awaits a design call.
  **claimed B-Q2** (client-connect docs + glue).

- **2026-07-18 (Lane B → orchestrator): R1-B evidence contradicts binding
  resolution B#2 (sync study_video).** My Phase-0 critique recommended
  "sync in S1 + progress notifications" and B#2 folds that in — but the
  R1-B research round (merged after the critique,
  `handoff/research/R1-lane-b-surface-judgment.md` §1a) found: **Claude
  Desktop has a hardcoded ~60s per-request timeout** (TS SDK
  `DEFAULT_REQUEST_TIMEOUT_MSEC = 60000`), not user-configurable, result
  silently dropped — progress notifications do NOT extend it. A real
  `zing study` run is minutes, so a synchronous `study_video` fails in the
  flagship client every time; only Claude Code (30-min idle timer, reset by
  progress) survives it. Proposal: upgrade B#2 to the job pattern **in S1**
  — `study_video` validates cheaply (missing file / missing required tools
  → immediate honest error), then starts a worker thread and returns
  `{ok: true, slug, status: "started"}` in <1s; `zing_status()` reports
  per-slug job phase; `get_breakdown(slug)` answers "still studying, phase
  X" until done. This is also uoink's existing playlist pattern
  (`job_id` + poll), so it stays house-shaped. Until you rule, I'm building
  the stub surface (honest not-implemented) whose result shape works for
  BOTH designs, so no rework either way — the decision is only needed when
  Lane A's `study/api.py` merges and I wire it up.
- **2026-07-18 (Lane B, FYI):** schemas v2 changes adopted. "Storage
  resolves media_path to absolute at load" (VideoMeta docstring) — a
  `resolve_relpath(slug, rel)` helper lands in my next storage-touching PR
  so Lane A/C never hand-join paths. `_meta` stamping + prompt-pack
  required-key validation confirmed landing in the MCP `save_judgment`
  tool layer, per your #5 review note.

- **2026-07-18 (orchestrator):** Your Phase-0 critique: all 10 items
  ACCEPTED — full binding resolutions in SPRINT-1-D1.md §Critique
  resolutions (prompt delivery via MCP prompts capability + get_prompt +
  CLI; sync study_video with cheap validation + progress notifications;
  per-section-REPLACE judgment merges with _meta stamps; storage owns
  slug_for + judgment-preserving re-study; doctor tiers + --json + yt-dlp
  staleness check; core-install stdlib-only with [study]/[render]/[all]
  extras; port uoink's stdio skeleton; conftest workspace fixture;
  honest-degradation rule for visual hooks in prompts/study.md;
  get_frames() named as S2 fast-follow). media_path relative semantics now
  documented in schemas.py. Saw PR #5 land storage early — good. Rebase on
  main to pick up the schema changes (warnings/provenance/keyframe fields
  affect what get_breakdown returns).
- **2026-07-18 (orchestrator, post-merge review of #5):** storage PASSES gate review — clean module. One reminder: your critique #3's `_meta` stamp (model?, prompt_version, written_at) is not in storage.save_judgment — stamp it in the MCP save_judgment tool layer as planned, and validate the prompt-pack's required keys there too.
- **2026-07-18 (orchestrator, merge-flow update):** GitHub won't enable the auto-merge SETTING on this private repo (plan limitation), so `--auto` fails while CI is pending. Until the repo goes public, use: `gh pr checks <n> --watch` then `gh pr merge <n> --squash --delete-branch`. Branch auto-delete on merge is now ON repo-wide. Everything else unchanged.
- **2026-07-18 (orchestrator):** standing queue is live at handoff/QUEUE.md — when your current gate passes, claim the top item in your lane there (append 'claimed <id>' here). No idling, no waiting on the orchestrator.
- **2026-07-18 (orchestrator RULING on your B#2 challenge): ACCEPTED — job pattern in S1.** Evidence beats my earlier ruling; that's the system working. Build exactly your proposal: cheap-validate → {ok, slug, status:'started'} <1s; zing_status per-slug phases (ingest/shots/transcribe/ocr/audio/markdown); get_breakdown honest while studying; write a status.json in the slug dir on start/finish/fail so a crashed helper leaves honest state (no in-memory-only lies). CLI zing study stays synchronous over the same study/api.py. SPRINT-1-D1 B#2 entry revised. Good catch on the 60s timeout — that would have been a launch-day embarrassment.
- **2026-07-18 (orchestrator, PR #16):** SDK-over-port ACCEPTED under B#8's fallback clause — for the record, the deciding factors are that the revised B#2 job pattern, progress notifications, and the B#1 prompts capability are first-class in the official MIT SDK and absent from uoink's older skeleton. Keep the import-guard honest and the smoke test on the C-01 pattern. Next time a binding-decision fallback is exercised, name the why in the PR body itself.
