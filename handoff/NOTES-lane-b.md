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
- **2026-07-18 (Lane B):** B-Q2 done (PR #33: docs/CONNECT.md +
  `zing serve-mcp --print-config`). **claimed B-Q3** → done in the same
  doc-only PR as this note: `handoff/research/B-Q3-get-frames-design.md`
  (result shape, 6-frame/1024px budgets with token math, error surface,
  shot-boundary sampling guidance, study.md bump plan, offline test
  plan; one non-blocking open question on shot_index sugar). Lane B
  queue is now EMPTY — stopping per the lane prompt; awaiting the next
  assignment or the S1 review round.
- **2026-07-18 (Lane B): honest-missing (a) CLOSED.** Ran the first real
  integration after Lane A's api.py merged (#32): synthetic 2.5s video →
  `h_study_video` on the REAL engine → job returned in <1s, status.json
  running→done, breakdown.json + breakdown.md + media.mp4 persisted,
  get_breakdown served summary. Engine degraded honestly in a bare venv
  (each skip named with its pip fix in warnings). The B#2 job pattern and
  the seam auto-wire are verified against the real engine, not the fake.
  Note for Lane A: seam has no phase callback, so zing_status shows phase
  "ingest" until done — an optional `phase_callback=` kwarg on study()
  would light up the per-phase reporting the B#2 ruling names (my runner
  already sniffs for it; zero changes needed on my side).
- **2026-07-18 (orchestrator):** S1 gate CONFIRMED — the real-engine integration run is exactly the proof the gate wanted; excellent close. My earlier B-Q4 landed under PROPOSED by my formatting mistake — it's yours and now properly queued: (B-Q4) x.com/twitter.com status slugs + platform 'x' tagging in storage (schemas enum already updated; scope: Ryan added X native + YouTube long-form as study sources). Then (B-Q5) EARLY cross-review: your S1 review-round duty pulled forward since you're idle — review Lane A's + Lane C's merged code (correctness, failure-state honesty, integration seams, test gaps) and land handoff/reviews/S1-REVIEW-lane-b.md. Review vs the specs INCLUDING today's scope add (format-aware hook window).
- **2026-07-18 (orchestrator): S1 FIX SPRINT OPEN.** Your items are in handoff/reviews/S1-FIXLIST.md (Lane A: F-06/07/08 + P3 share; Lane B: F-02 SECURITY first, then F-03/04/05/10/11/15; Lane C: F-01 CI first, then F-09/12/13/14). One fix per PR, regression test that fails before the fix, P1s before P2s. Nothing new until P1/P2 clear.
- **2026-07-18 (orchestrator, STANDING RULE — process retro):** whenever you finish a queue item, append a short PROCESS OBSERVATION to this file: what about this multi-agent process (specs, queues, NOTES, reviews, CI, orchestration) helped, hurt, or should change — one concrete recommendation each time. The orchestrator folds accepted ones into the process. Critical observations wanted, not praise.
- **2026-07-18 (Lane B): claimed B-Q6, B-Q4, B-Q7** (working in that
  order). Stand-in review read + disagreement pass coming with the B-Q7
  PR.
- **2026-07-18 (Lane B, URGENT — MAIN IS RED):**
  `test_eval_real_videos.py::test_checked_in_real_video_snapshots_are_self_consistent`
  fails on clean origin/main (both CI OSes; reproduced locally at
  621fdc0). Root cause: #52 (D-Q4) corrected EXAMPLE-DATASET truth, so
  the `human_truth` sha256 pinned in Lane C's frozen snapshot provenance
  no longer matches. Not my paths, and NOT a mechanical hash bump: the
  frozen annotations were made against the OLD truth doc, so the
  snapshot likely needs a Lane C re-freeze against the corrected truth
  (F-16's whole point). Every lane's merges are blocked until this
  lands. My open PR #53 (B-Q6) is CI-red only because of this; it will
  be re-pushed once main is green. Continuing B-Q4/B-Q7 locally
  meanwhile.
- **2026-07-18 (Lane B): B-Q5 stand-in review read — ENDORSED, no
  substantive disagreements.** The review is line-cited, correctly
  ranked, and its findings map 1:1 onto the fixlist that has since been
  cleared; its "passed" spot-check list matches my own reading of the
  seams I integrate with. One nuance to ADD (not a disagreement): its
  P3 note on `_stage_local`'s size-only media reuse compounds with my
  slug hash (first 1MB + size) — a same-size, same-first-MB re-export
  at the same path maps to the same slug AND reuses stale media, so the
  two low-probability holes line up. S2 polish suggestion for Lane A:
  full-hash or mtime check when re-staging. Filed here, not urgent.
- **2026-07-18 (Lane B): B-Q6 done (PR #53, blocked on red main),
  B-Q4 + B-Q7 done (committed locally, PRs follow serially once main is
  green).** B-Q7 note for Lane A: `storage.use_workspace(root)` now
  exists (ContextVar, thread-safe) — your `_workspace_override` env
  mutation can delegate to it in one line and F-15 closes fully.
  **PROCESS OBSERVATIONS (standing rule):**
  1. (B-Q6) The wizard-of-oz §4 verdict was written as a numbered
     "fixes for v0.2" list and converted straight into prompt edits with
     zero interpretation loss. Recommendation: REQUIRE that shape — every
     judgment-affecting deliverable ends with a numbered, actionable
     fix list naming its target file.
  2. (B-Q4) The queue wording "platform 'x' tagging in storage" sent me
     hunting for a storage-side platform tag that doesn't exist (Lane A's
     detect_platform already did it). Recommendation: queue items name
     the exact function/file when ownership is split.
  3. (B-Q7/red main) #52 corrected a truth doc and merged green while
     the snapshot test pinning that doc's hash turned main red — the
     hash-pinned fixture has no self-service path. Recommendation:
     hash-pinning tests must name the regeneration command in their
     failure message (e.g. "run tools/eval/freeze_real_videos.py
     --refresh-truth-hash") so a legitimate doc correction can't strand
     main red waiting for cross-lane archaeology.
- **2026-07-18 (Lane B → Lane A/orchestrator): F-15 convergence after
  A-Q7 (#57).** Our halves shipped different mechanisms: A-Q7 sniffs
  storage.breakdown_dir for a `root=` param (not provided), so its
  explicit-root path never activates and study() still env-overrides
  when a workspace is passed; my B-Q7 (merging now) adds
  `storage.use_workspace(root)` — a ContextVar override that pins the
  whole MCP job (worker + heartbeat threads) with zero env mutation.
  State after both: the MCP path is fully thread-safe (workspace=None →
  env override no-ops; my ContextVar governs). Remaining tail = explicit
  `study(workspace=...)` callers (CLI --workspace, eval adapter): still
  env-based, single-threaded-only. Recommendation: Lane A swaps
  `_workspace_override`'s env mutation for
  `with storage.use_workspace(workspace):` (one line, keeps their
  signature) and drops the root= sniff — F-15 closes fully. I'm not
  touching study/api.py per lane rules.
- **2026-07-18 (Lane B): claimed V-B** (TikTok virality definition,
  doc-only) — research agent run complete, doc PR follows.
- **2026-07-18 (Lane B): V-B done** — docs/taste/VIRALITY-TIKTOK.md
  (definition, mechanism, first-hours indicators, genre differences,
  6 ranked scoring implications, 5 deeper threads; folklore explicitly
  flagged and barred from calibration). PROCESS OBSERVATION (standing
  rule): the V-round spec named the deliverable path, the required
  sections, AND the house format in one queue entry — zero ambiguity,
  fastest item so far. That confirms observation #2 from my last batch:
  precision in the queue entry is the cheapest speedup this process has.
- **2026-07-18 (Lane B): claimed B-Q8 + B-Q9** (S2-prep wave). B-Q8
  lands first (this PR); B-Q9 (.mcpb) follows.
- **2026-07-18 (Lane B): B-Q8 done (PR #69), B-Q9 done (this PR).**
  B-Q9 verification chain: staged tree CI-tested; mcpb pack builds
  dist/myzing.mcpb (85KB, no compiled deps — uv resolves at install,
  dodging the pydantic landmine); the manifest's EXACT launch command
  verified cold from the staged bundle (initialize → 9 tools → both
  prompts via the ${__dirname}/prompts pin). Remaining human step:
  Ryan double-clicks the bundle in Claude Desktop — fallback is the
  manual config, same server. PROCESS OBSERVATIONS: (B-Q8) building
  from my own B-Q3 design note was near-zero-friction — the
  design-note-before-build pattern pays for itself; recommend it for
  C-Q12's transition-field proposal too. (B-Q9) the R1-B research
  flagged the pydantic bundling landmine 12 hours before I hit the
  packaging work — research rounds are cheap insurance; the uv-type
  manifest worked first try BECAUSE the failure mode was known in
  advance.
