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
- **2026-07-18 (Lane B): B-Q10 done — SG-1 review of Lane A's #70
  (caption-region clustering v2) + keyframes.py (post-F-07), surface/
  consumer lens.** Verdict: the measurement is a real fix for the
  wizard-of-oz layer-conflation finding and the code is honest about its
  thresholds. Two seam gaps found ON MY SIDE, fixed in this PR:
  (1) `get_breakdown` served breakdown-relative paths (meta.media_path,
  shots[].keyframe) with no base dir in the same response — dead ends
  for a filesystem-capable MCP client; result now carries `dir`.
  (2) prompts/study.md 0.3.1: layer-separation rule updated to A-Q8
  reality (persistent overlays pre-excluded → read warnings; shorter
  labels may still pollute), keyframe access now via the `dir` field
  incl. the frames/hook_*.jpg stills.
  **Judgment calls for Lane A (file:line, no action required from me):**
  (a) captions.py `_overlay_threshold_s` — sub-threshold overlays (e.g.
  a 10s location tag on a 30s short → threshold 15s) still enter
  captions[]; residual pollution my prompt still guards. S2 idea:
  position-persistence as a secondary signal, not just duration.
  (b) keyframes.py writes frames/hook_<second>.jpg but nothing in the
  Breakdown references them — only discoverable by listing the dir. My
  `dir` field makes them REACHABLE; consider recording them in
  provenance (or a schema field, orchestrator's call) so clients don't
  glob. SG-1 coverage log: reviewed #70 (captions), keyframes.py
  (current main). PROCESS OBSERVATION: the aimed-review queue item
  named the exact lens ("does what MCP serves match what was
  measured?") — that focus found two real seam gaps a generic review
  would have skimmed past; recommend every SG-1 assignment name a lens.
- **2026-07-18 (Lane B): SG-2 coverage sweep (standing generator, queue
  empty this cycle).** Target: mcp_server.py, my lowest-covered module
  (86%, worst in lane; storage 94, doctor 93, prompt_pack 95, bridge
  94). The uncovered cluster was the F-03 crash-honesty machinery —
  _pid_alive (incl. the Windows kernel32 branch), _parse_ts, and every
  _reconcile_running branch (orphaned own-pid, dead foreign pid, live
  foreign pid with fresh/stale/absent heartbeat, no-pid legacy). 13 new
  tests using real spawned live/dead processes, not mocks. **Coverage
  86% → 89%** (53 → 42 missed lines; remainder is the FastMCP
  registration body exercised only via the stdio smoke test). Also
  noted: F-15 fully closed by Lane A's #80 adopting use_workspace —
  the NOTES-relay handshake worked end to end. SG rotation log: SG-1
  done (B-Q10, aimed), SG-2 done (this); next idle cycle: SG-3.
- **2026-07-18 (Lane B): claimed B-Q11 (gate opened by #84) → done in
  this PR.** study.md 0.4.0: transitions[] reading rules (the three
  honest states from A-Q11's render logic, mirrored for the AI: observed
  / ran-none / not-run via provenance; the deliberate no-per-event-
  confidence rule quoted from the contract; audio-aligned cuts taught as
  beat evidence with the example modeling a citation), a compact tools
  overview (incl. generate_thumbnails: it measures, you judge the art),
  changelog. get_frames teaching was already in 0.3.x. PROCESS
  OBSERVATION: the C-Q12 contract docstring was written so precisely
  (three states, why confidence is absent) that the prompt teaching was
  mostly transcription — contract docstrings that explain WHY are the
  cheapest cross-lane documentation this process has; recommend the
  schema-change checklist require a why-sentence per new field.
- **2026-07-18 (Lane B): SG-3 simplification pass (standing generator,
  queue empty this cycle).** Three duplications removed, zero behavior
  change (401 tests green unchanged): (1) the unknown-slug error message
  existed twice in mcp_server and had already drifted in wording —
  now one _missing_slug_err; (2) h_get_frames hand-rolled the slug
  validation _check_slug exists for — now consistent with every other
  handler (and kept the corrupt-json ValueError catch the old inline
  code had); (3) breakdown.json serialization existed in two storage
  sites — now one _write_breakdown_json so the format can't drift.
  Net -6 lines of logic, +2 single-purpose helpers. SG rotation: SG-1
  done, SG-2 done, SG-3 done (this); next idle cycle: SG-4
  (trending-OSS scan).
- **2026-07-18 (Lane B): CI caught a REAL dispatch race on PR #87** (not
  an SG-3 breakage — latent since the B#2 job runner, exposed by slower
  CI runners): a completed worker thread is briefly still alive and
  registered in _JOBS between its final status write and its cleanup
  pop; a re-study of the same slug arriving in that window got
  'already_studying' and never started — user-visible bug, not just
  test flake. Fix: already_studying now requires thread-alive AND
  on-disk state 'running'; the worker's cleanup pop is identity-guarded
  so a finishing old thread can't evict a new registration (which would
  have made _reconcile_running falsely kill the live job). Two
  regression tests, red-then-green proven. PROCESS OBSERVATION: the
  test that caught this asserted only result['ok'], not
  result['status'] — a stricter assertion would have caught the race
  locally months of CPU-time earlier; when a tool has distinct success
  shapes, tests should pin WHICH one.
- **2026-07-18 (orchestrator): SPRINT 2 IS OPEN** — handoff/SPRINT-2-D2.md. StyleProfile + StatSummary contracts are live in schemas.py. S2 lane items take priority over standing generators; S2-prep items already done fold in (transitions, get_frames, prompt pack 0.4.0 are the foundation). Same discipline as S1.
- **2026-07-18 (Lane B): SG-4 trending-OSS scan (standing generator,
  queue empty this cycle).** Five repos appended to PRIOR-ART-OSS.md,
  licenses API-verified: pyloudnorm (MIT, REUSE — closes the P9 LUFS
  gap the wizard-of-oz flagged), pyannote-audio (MIT, REUSE as
  extras-gated S2+ option), Qwen3-VL (Apache incl. weights, REUSE for
  D-3 — but flagged: bundling it as a judge would cross the no-bundled-
  model line; orchestrator call), VideoLingo (Apache, BORROW its
  subtitle line-splitting), FireRed-OpenStoryline (Apache, BORROW its
  planner/Style-Skills architecture — closest published system to our
  thesis). Strategic read for the roadmap: the middle layer we occupy
  (measurement → style aggregation → deterministic render) is still
  unclaimed in the trending set; our moat is quantitative grounding.
  SG rotation: 1,2,3,4 done; next idle cycle: SG-5.
- **2026-07-18 (Lane B): S2 open — claimed my lane (storage first, same
  play as S1 so Lane A's builder lands onto it).** This PR: profile
  storage (profiles/<name>/profile.json, .bak on rebuild, honest index)
  + validate_profile_name sharing the F-02 validator via a _validate_name
  refactor (slug behavior unchanged, tests prove it). Next PR: the three
  MCP tools + prompts/compare.md v0.5.
- **2026-07-18 (Lane B): S2-B2 done (this PR)** — build_profile /
  get_profile / list_profiles MCP tools (Lane A seam auto-wire with
  genre/platform signature-sniff, honest not-implemented until
  profile/api.py lands, idempotent save mirroring the study_video rule)
  + prompts/compare.md 0.5.0: band rules (inside/near/outside via
  p25-p75 with both numbers cited verbatim), low-n humility, bucket-by-
  bucket curve comparison, criterion IDs from docs/taste or
  rubric_scores cannot_judge, deviations with meaningful calls, example
  proven against save_judgment(section='compare') end-to-end.
  **Gate status:** MCP round-trip half is in CI (12-tool stdio surface);
  the real Cleo-vs-profile judgment half needs Lane A's builder —
  will run it the cycle their api.py merges. build_profile is sync (ms
  aggregation — the B#2 timeout math doesn't apply).
- **2026-07-18 (Lane B): SG-5 feature-gap analysis (standing generator;
  S2 lane items done on my side, gate half blocked on Lane A's
  builder).** Proposed P-B1 (loop-ability as a measured Breakdown
  field) to QUEUE §PROPOSED with the required self-refutation. The
  refutation bit hard enough that the surviving form is gated: a
  zero-schema base-rate check against the frozen references BEFORE any
  build — if no admired reference actually loops, the feature dies
  with evidence instead of shipping as speculation. SG rotation:
  1-5 all run once; restarting at SG-1 next idle cycle. PROCESS
  OBSERVATION: SG-5's mandatory self-refutation changed the proposal
  materially (unconditional build → gated check) — the mechanism works;
  suggest requiring the refutation to name the CHEAPEST test that would
  kill the proposal, since that's what reshaped this one.
- **2026-07-18 (Lane B): S2 GATE COMPLETE — real chain run** (record:
  handoff/S2-GATE-lane-b.md). Lane A's builder (#92) auto-wired through
  my build_profile tool on first contact (keyword-only genre/platform
  sniff worked); real profile from 3 frozen real breakdowns; real
  compare judgment of Cleo per compare.md 0.5.0, saved through
  save_judgment with the 0.5.0 stamp. Honest headline: the gate profile
  describes NO coherent taste (heterogeneous unjudged sources → bands
  unfalsifiable) and the judgment SAYS so — which is the anti-slop
  design working. Two Lane A findings filed in the gate record:
  n=2 percentile interpolation emits negative time values (clamp to
  observed range), and a profile-coherence warning would name loose
  profiles before judgment. Sprint-gate remainder is Ryan-side: real
  reference set, then his read. PROCESS OBSERVATION: the frozen
  real-video set paid for itself again — a full S2 gate ran with zero
  network and zero heavy deps because real measurements were checked
  in; keep growing that set.
- **2026-07-18 (Lane B): claimed B-Q12 + B-Q13** (gate-pack defects).
  This tiny PR: yt-dlp into [study] (doctor's fix command finally
  installs what it promises). Next PR: doctor JS-runtime data point +
  compare.md 1-5 scale fix.
- **2026-07-18 (orchestrator, PROTOCOL CHANGE — CI quota exhausted):** GitHub Actions refuses to start jobs (private-repo minutes gone; macOS 10x multiplier + today's volume). Until further notice: do NOT wait on checks (they will never run). REPLACEMENT GATE: run the FULL local suite with ffmpeg gates (ZING_REQUIRE_FFMPEG=1 python -m pytest) and paste the pass-count line into the PR body, then merge. Doc-only changes may merge with a stated 'doc-only' line instead. The discipline is the gate now — betray it and we are blind.
- **2026-07-18 (Lane B): B-Q12 + B-Q13 done** (yt-dlp dep landed in
  #96; this PR is the rest). Doctor answer to B-Q12's question: the
  staleness check did NOT cover the JS-runtime warning — different
  mechanism entirely — so check_ytdlp now detects deno/node, warns with
  a winget fix when absent, and reports js_runtime in --json;
  fix lines now always print when present. compare.md 0.5.1: rubric
  scores on the rubric's own 1-5 scale, real G-TH-* ids in the example,
  changelog added; integrity test now rejects any example whose scores
  never exceed 2 (the 0-2 tell). PROCESS OBSERVATION: this defect
  existed because compare.md was written against INDEX.md's criterion
  IDs without opening the rubric file itself — one hop short. Rule of
  thumb worth adopting: prompts that cite a doc's scale must quote the
  scale line from THAT doc, not its index.
- **2026-07-18 (Lane B, URGENT — CI IS DOWN REPO-WIDE, RYAN ACTION
  NEEDED):** every job on PR #97 failed in 3s with GitHub's billing
  error: "The job was not started because recent account payments have
  failed or your spending limit needs to be increased." This is an
  ACCOUNT problem (Settings → Billing & plans), not a code problem —
  no lane can merge anything until it's fixed (CI is the merge gate).
  My B-Q12b/B-Q13 PR #97 is complete and locally green (449 tests);
  it waits on the billing fix + a checks re-run. Not merging without
  green checks per the never-merge-red rule — the orchestrator can
  overrule if they judge a billing outage differently.
- **2026-07-18 (Lane B): SG-1 review (rotation restart; queue empty) —
  PRs #98 (Lane A) + #99 (Lane C), consumer/surface lens.** #98 VERIFIED
  EMPIRICALLY, not just read: re-ran the exact S2 gate build that
  exposed both findings — time_to_first_word p25 is now 2.965s (was the
  impossible −1.085s; inclusive quantiles interpolate within the
  observed range, correct method choice) and the coherence warning
  fires on the 18–635s gate mix with actionable wording. Both of my
  gate-record findings are closed. One observation, not a defect:
  coherence is checked on duration only; if a mixed-format set ever
  shares duration, pacing incoherence would slip through — fine for S2,
  noted for the review round. #99: dissolve gets a temporal-monotonicity
  gate (net-vs-path change — camera motion oscillates, dissolves
  progress), thresholds are named constants recorded in provenance,
  DETECTOR_VERSION bumped honestly to 3; no TransitionObservation shape
  change, my surface unaffected. Both PASS. SG-1 coverage log: #70,
  keyframes.py, #98, #99. PROCESS OBSERVATION: the finding→fix→verify
  loop closed inside one working day across three parties (my gate
  record → Lane A's fix citing it → my empirical re-verification) —
  the NOTES relay is doing real code-review work; keep findings
  file:line-specific so fixes can cite them.
- **2026-07-18 (Lane B): SG-2 second pass (rotation; queue empty).**
  mcp_server still my lowest module (88%): the remaining real gaps were
  error-honesty paths again — builder-raises in build_profile
  (errors-as-data envelope), genre/platform tagging when the seam lacks
  the kwargs, corrupt profile.json in get_profile, and the SDK-missing
  guard in run(). 4 tests, **88% → 90%** (55 → 44 missed; what remains
  is FastMCP registration glue exercised by the stdio smoke test and
  Windows-only ctypes branches exercised on Windows only — adding
  fake-coverage for those would be theater, so stopping here). SG log:
  1,1,2,2,3,4,5 run.
- **2026-07-19 (orchestrator): CI RESTORED (GitHub Pro) — local-gate mode retired.** Resume the normal flow: gh pr checks <n> --watch, merge only on all-green. Keep pasting the local suite line in PR bodies anyway — it proved its worth and costs nothing.
- **2026-07-19 (Lane B): CI-restored protocol acknowledged; SG-1 quick
  pass on #101 (Lane A proc-seam tests) — PASS, nothing to flag:**
  real-subprocess tests through the actual choke point using the
  running interpreter as the child (offline, cross-platform) — the same
  real-not-mocked pattern as my F-03 liveness sweep; test-only, no
  contract or surface impact. SG-1 coverage log: +#101. PROCESS
  OBSERVATION: generator cycles are trending toward smaller findings
  (this one: none) — suggest the orchestrator consider relaxing
  never-idle to every-other-cycle once the S2 review round opens, so
  generator output stays signal.
- **2026-07-19 (orchestrator): IDLE IS ABOLISHED** — same rule as Lane A: no unclaimed lane items means you claim a STANDING GENERATOR (QUEUE.md), one per cycle, rotating. Never answer idle while generators exist.
- **2026-07-19 (orchestrator): repo now PUBLIC** — unlimited Actions minutes; TRUE AUTO-MERGE restored (gh pr merge --auto --squash --delete-branch); branch protection enforces all six checks so red merges are structurally impossible.
- **2026-07-19 (Lane B): SG-1 on #104 (Lane A dead-code removal) —
  PASS; F-15 thread formally CLOSED.** _workspace_override now
  delegates to storage.use_workspace (the exact one-liner from my
  convergence note) and the dead root= sniff scaffolding is gone
  (−99/+18). Both halves of F-15 now share one mechanism: ContextVar,
  no process-global state, thread-safe under concurrent MCP jobs.
  Suite green locally (463). SG-1 coverage log: +#104.
- **2026-07-19 (orchestrator): SPRINT 3 (DIRECT) IS OPEN — handoff/SPRINT-3-D3.md.** The anti-slop core. Naming/branding is parked by Ryan (research continues in background; build under existing names/codenames). S3 lane items take priority over generators.
- **2026-07-19 (orchestrator): LAUNCH MODE + SPRINT 4 OPEN** — Ryan's directive: build EVERYTHING fully, one major launch, he tests at launch. All Ryan-gates now internal. handoff/SPRINT-4-D4.md has your Track 1 (Assemble) + Track 2 (Taste Onboarding — preset packs like ai-tech-talking-head, viral-tiktok; zing setup flow) items. S3's open items finish first; then S4. Same discipline, no pauses.
- **2026-07-19 (Lane B): S3+S4 assignments acknowledged; S3 remainder
  in progress.** This PR: prompts/direct.md v1.0.0 — the real direction
  contract (was the S1 stub): gap/keeper/shot-prompt shape per
  SPRINT-3-D3 with required_keys wired into save_judgment validation;
  every gap cites both sides; keepers grounded in
  provenance.raw_mode.keepers; shot prompts under a plain-language hard
  rule (<=2 sentences, internal vocabulary banned from instructions —
  aligned with Lane C's conformance heuristics); rubric-only mode with
  stated caveat when no profile exists; visual gaps require eyes or
  become human-check instructions. The stub-police test flipped into a
  v1-contract test: example passes save_judgment(section='direct')
  end-to-end, severity ordering enforced, jargon ban asserted. Next
  PRs: direction.md renderer, MCP flow doc + gate run.
- **2026-07-19 (Lane B): S3-B part 2 — direction.md renderer (this
  PR).** New module myzing/direction.py claimed for Lane B: renders
  judgment['direct'] in creator order (what works → what's missing →
  what to film), severity labels in plain words (MUST FIX/SHOULD FIX/
  POLISH), internal evidence collapsed into a receipts section instead
  of deleted, honest fallbacks on empty sections. Wired into
  save_judgment(section='direct') — render failure degrades to an
  honest receipt note, never loses the saved judgment. The shipped
  prompt's worked example IS the render fixture, so prompt, tool, and
  renderer cannot drift apart. Part 3 (flow doc + gate run) next.
- **2026-07-19 (Lane B): S3-B COMPLETE (3/3, this PR)** — flow doc
  (docs/DIRECT-FLOW.md) + gate run record (handoff/S3-GATE-lane-b.md).
  The real chain ran end to end: frozen raw clip directed against the
  gate profile per direct.md v1.0.0 → save_judgment validated →
  direction.md rendered in creator order; the two shot prompts read as
  filmable by a person holding a phone. Honest limits recorded: the
  clip is F-16-edited standing in for raw, keeper machinery predates
  this freeze (direction SAYS so), full-fidelity gate needs the
  re-frozen genuinely-raw clip with raw_mode provenance (Lane C/D).
  Next: S4 Track 1 (TTS provider plugin surface) and Track 2
  (zing setup onboarding), in that order unless the orchestrator
  reorders.
- **2026-07-19 (Lane B): S4 Track 1 part 1 (this PR) — TTS provider
  plugin surface.** New module myzing/tts_providers.py (claimed):
  registry resolution (explicit > ZING_TTS_PROVIDER > kokoro default),
  ElevenLabsProvider as the optional key-gated plugin (stdlib urllib,
  no SDK dep; PCM->wav locally so the renderer never cares which
  provider made a track; every failure names its fix and the offline
  alternative), tts_status() as the honest per-provider state, doctor
  gains an optional-tier tts check ("renders proceed without voiceover
  tracks" as the stated degraded mode). Remaining Track 1: MCP
  render/export tools (job-pattern for renders) — next cycle. Then
  Track 2 zing setup.
- **2026-07-19 (Lane B): S4 Track 1 COMPLETE (2/2, this PR) — MCP
  render/export tools.** render_edl: cheap validation (missing/malformed
  EDL, no ffmpeg → sync errors-as-data), then the proven job pattern
  (render id from EDL path, status.json under renders/<id>/ via new
  generic storage.write_status_at/read_status_at — study status
  refactored onto the same helpers; crash honesty: get_render rewrites
  an orphaned 'running' exactly like studies). get_render: state with
  the internal pid stripped. export_otio: sync, honest ImportError
  guidance to [render] extras, errors-as-data. 15-tool stdio surface.
  Lane C's pipeline/otio seams imported, not touched. Track 2
  (zing setup) next cycle.
- **2026-07-19 (Lane B): S4 Track 2 built (this PR) — zing setup +
  onboarding tools.** New module myzing/setup_flow.py (claimed): `zing
  setup` CLI (non-interactive by design — the same flow an AI drives;
  exit 3 = studies in progress for scriptable polling) + MCP
  list_presets / setup_taste. Onboarding is IDEMPOTENT and re-entrant:
  inspects studied state, starts only missing studies on the existing
  job machinery, builds the profile when all references are studied;
  multiple named tastes first-class. prompts/taste.md 0.1.0: "this
  taste in words" — 3-5 plain grounded sentences, hedged by n/unjudged
  coverage, the wrong-reference-set escape hatch named. 17-tool
  surface.
  **SEAM PROPOSAL for Lane A (A-Q14):** pack manifest contract my
  surface consumes — presets/<pack-name>/pack.json {name, genre,
  platform, description, references: [{id, url, why}]}; search order
  ZING_PRESETS_DIR then repo-root presets/. Malformed packs fail loud;
  missing dir is honest-empty with the personal path offered. If you
  want a different shape, say so before packs land — my parser is one
  function (setup_flow.load_pack).
- **2026-07-19 (orchestrator RULING): S3 INTERNAL GATE — PASS on mechanics.** The gate record is the standard: real chain, real gap found (silent tail + filmable fix), limits stated instead of papered. The two flagged dependencies are now queued (refreeze with genuinely-raw clip; quality judgment deferred to Decision Week inputs per LAUNCH-PLAN). S3 is CLOSED; Lane B fully onto S4.
- **2026-07-19 (Lane B): pack seam RESOLVED my side (this PR).** Lane
  A's A-Q14 packs shipped as flat presets/<id>.json with pack_id (their
  branch was in flight before my seam proposal landed — nobody's
  fault, classic concurrent-lanes race). As promised, the parser was
  one function: load_pack/list_packs now consume BOTH shapes (flat
  canonical, dir form kept), name normalizes from pack_id, description
  synthesizes from genre+curated_at when absent. Verified live: `zing
  setup --list` shows all five shipped packs. NEW INTEGRATION-TRUTH
  test loads the real shipped packs in CI — this seam can never break
  silently again. No Lane A changes needed. PROCESS OBSERVATION: two
  lanes designed the same seam concurrently and diverged harmlessly
  ONLY because one side had committed in writing to a one-function
  parser; cheap adapters at lane boundaries beat coordination overhead
  — recommend it as an explicit house pattern.
- **2026-07-19 (Lane B): SG-3 second pass (standing generator; queue
  empty).** Target: my own newest code — the render tools had copied
  the study job machinery's two subtle race guards (the #87
  alive-AND-disk-running dispatch rule, and the identity-guarded
  worker-side pop). Four duplicated blocks → two documented helpers
  (_job_is_live/_job_cleanup) shared by both registries; the race rule
  that CI once caught the hard way now has exactly ONE implementation
  to keep correct. 580 tests green unchanged (the #87 regression tests
  cover both semantics). PROCESS OBSERVATION: the duplication existed
  for exactly two cycles before this sweep found it — generator
  rotation is working as the intended self-cleaning mechanism; no
  change recommended.
- **2026-07-19 (Lane B): SG-2 third pass (standing generator; queue
  empty).** Newest-module sweep: setup_flow.py was my lowest at 74% —
  the untested paths were the CLI's whole --pack branch (happy path
  with name/genre defaulting from the pack, unknown-pack listing,
  malformed-pack loudness), the build-failure exit, bad profile names,
  and load_pack's path-shaped-name rejections. 8 tests, **74% → 93%**
  (direction.py 96%, tts_providers 91% — healthy). Remaining misses are
  argparse plumbing and print formatting. SG rotation log updated.
- **2026-07-19 (Lane B): SG-1 (rotation; queue empty) — #137, #140,
  #143 reviewed, all PASS.** #143 is the standout: refusing to
  fabricate output orientation from unmeasured dimensions (the invented
  1080x1920@30 default had quietly revived the hard-coded portrait
  behavior C-Q5 removed) with a re-study-pointing error — exactly the
  house honesty discipline; my render surface consumes EDLs directly
  and is unaffected. #137 real-dependency transcribe tests (house
  pattern), #140 six-line workspace cleanup. Nothing to flag. SG-1
  coverage log: +#137, #140, #143.
- **2026-07-19 (Lane B): SG-5 second pass (rotation; queue empty) —
  P-B2 proposed, refuted, and its SURVIVING form shipped in the same
  PR.** Proposal was a judgment-backlog tool (list_unjudged); my
  refutation killed the tool (the backlog is a one-line derivation over
  list_breakdowns' judgment_sections — an 18th tool would be surface
  sprawl per our own kinocut verdict) and identified the real gap as
  GUIDANCE: nothing tells the judging AI to check the backlog at the
  right moment. Shipped: taste.md 0.1.1 flows a confirmed taste into
  "offer to judge the unjudged references now" + a pinning test.
  Recommend disposing P-B2 as build-rejected/guidance-shipped. SG-5
  score so far: two proposals, zero unnecessary builds — the refutation
  requirement is earning its keep.
- **2026-07-19 (Lane B): S4 gate defects FIXED (this PR) — D-3 (P1),
  D-4, D-5, D-6, D-9-doctor.** D-3: `zing setup` now owns its jobs'
  lifetime — the pack path routes through build_pack (synchronous
  in-process studies; nothing daemonic dies), and the links path
  advances → waits on its own jobs (reconciling status reads so a dead
  worker can't spin the wait forever) → re-advances, bounded restart
  rounds, honest per-slug failure report on give-up. D-4: advance_setup
  restarts failed studies (it was telling users "call study_video
  again" while never doing so itself). D-5: pack builds route through
  Lane A's build_pack — manifest_sha + per-ref provenance stamped;
  pack profiles adopt their pack-<id> naming convention (setup_taste
  reports profile_name). D-6: doctor's tts hint no longer promises an
  auto-download tts.py never does. D-9 doctor half: missing JS runtime
  now says YouTube fetches WILL fail (S2's warning came true);
  fetch-side bot-gate surfacing is Lane A's half. CORRECTION to the
  gate doc: B-Q12's yt-dlp extra is NOT still open — it landed in #96
  (pyproject line 17); the gate likely ran against an older checkout.
- **2026-07-19 (Lane B): SG-4 targeted scan (rotation; queue empty) —
  D-9's open half now has a concrete, license-clean plan** (full
  findings + sources appended to PRIOR-ART-OSS.md). Headline: the
  community-standard bot-gating fix (bgutil PO-token provider) is
  GPL-3.0 — REUSE only as a user-installed yt-dlp plugin, NEVER
  vendored; deno is now hard-required by yt-dlp itself (my D-9 doctor
  wording was right). PROPOSED QUEUE ITEMS for the orchestrator:
  (B) doctor detects PO-token-provider registration + maps
  LOGIN_REQUIRED/'Sign in to confirm' fetch errors to a distinct
  diagnostic; docs troubleshooting page (update→deno→bgutil→cookies
  order, account-flag warning on cookies); (A) ingest surfaces
  bot-gate errors distinctly (their D-9 half); (C) VMAF/ssim
  perceptual render-QA probe (BSD, ffmpeg-native — natural content-
  probe extension). SG rotation: 4 done again; next idle cycle SG-1.
- **2026-07-19 (orchestrator): S4 CLOSED (Gate 1 rerun PASS with probe evidence — a creator-ready draft). SPRINT 5 HARDENING IS OPEN — handoff/SPRINT-5-D5.md. S5 items take priority; S4 leftovers D-10/O-2 queued.
- **2026-07-19 (Lane B): SG-1 (rotation) — #152/#153/#154 reviewed, all
  PASS.** #152 (C-Q17, from Ryan's bug report) touched MY get_frames
  extraction and Lane A's keyframes identically: limited-range (tv)
  sources were emitting gray-lifted JPEGs — scale=in_range=auto:
  out_range=full + -color_range pc is the right fix, applied at both
  sites, with real limited-range and subsecond-clip gated tests.
  Verified with ZING_REQUIRE_FFMPEG=1 locally (20/20). As the owner of
  h_get_frames I co-sign the change; the judgment AI's eyes now see
  correct blacks. #153 (vertical variant manifests — my pack surface
  consumes them via the existing loader, no changes needed) and #154
  (eval preflight reporting) both clean. SG-1 log: +#152,#153,#154.
- **2026-07-19 (Lane B): S5 fresh-host installs — part 1 (this PR):
  wheel data packaging.** The predictable first defects, fixed before
  the harness finds them: prompts/ and presets/ live at repo root (spec
  paths) and were absent from any wheel — an installed Zing had no
  prompt pack and no preset packs (S1 honest-missing (c), now due).
  Fix: byte-identical mirrors under src/myzing/_data/ shipped as
  package-data; loaders fall back repo-root → packaged; a DRIFT GATE
  test fails CI the moment either side changes without the other (the
  pack-seam lesson, applied preemptively). Part 2 next cycle:
  packaging/clean_host_check.py (wheel build → temp venv → doctor/
  setup/prompt/cached-study), local Windows gate run, CI clean-install
  jobs, S5-INSTALL-GATE record.
- **2026-07-19 (Lane B): S5-B part 2 (this PR) — clean-host harness +
  Windows gate run + CI matrix job.** packaging/clean_host_check.py:
  wheel → pristine venv (+[mcp]) → first-run surface from a neutral cwd
  with NO repo on the tested path; per-step gate record (JSON +
  console). **Windows local run: 7/7 PASS** — including a full
  cached-media study from the bare install with honest skip warnings;
  the prompt-pack and preset-pack steps pass only BECAUSE of #156's
  mirror (they'd have failed before it). CI: clean-install matrix job
  on all three OS runners uploading per-OS gate records as artifacts
  (ci.yml edit — assigned to Lane B by the sprint item, flagged per
  shared-file discipline). Records + two non-blocking first-run
  rough-edge observations in handoff/S5-INSTALL-GATE-lane-b.md.
- **2026-07-19 (Lane B): S5 first-run rough edges FIXED (this PR)** —
  the two defect candidates my own install-gate run observed, closed
  under the sprint's every-rough-edge-is-a-defect rule: (1) `zing
  setup --list` now ends with the next command (onboard-one usage
  line); (2) `zing doctor` opens with a one-line verdict (NOT ready /
  ready-with-N-degraded / fully ready) so a new user learns readiness
  from line one instead of scanning seven items. Both verified live
  and pinned by tests; the clean-host harness re-run passes 7/7
  against the new output. PROCESS OBSERVATION: the install gate's
  "record rough edges as defects" framing turned a green run into two
  concrete improvements — verification that reports only pass/fail
  would have shipped the friction; keep the observations section
  mandatory in gate records.
- **2026-07-19 (Lane B): SG-2 fourth pass (rotation; queue empty).**
  Target: setup_flow after the D-3/D-4 rewrite dropped it to 82% — and
  the dark paths were exactly the gate-defect machinery: the wait
  loop's orphaned-running reconcile exit (now proven to return, not
  spin), the bounded-retry give-up flow (always-failing engine → retry
  announcements → per-slug failure report with the error text and a
  doctor pointer, exit 1), and finish_pack's PackError/ImportError
  envelopes. 3 tests, **82% → 91%**; remainder is argparse/print
  plumbing. The D-3 fix's most subtle behavior (a dead worker can't
  hang the CLI wait) is now regression-pinned.
- **2026-07-19 (Lane B): SG-1 on #167/#168 (Lane A S5 sweep) — and the
  aimed review found a defect in MY check (fixed in this PR).** SW-3
  routed "doctor should check for a JS runtime" to me; it already does
  (B-Q12/#97, D-9/#148) — but the sweep's own evidence shows my check
  was falsely comforting: node-on-PATH satisfied it while yt-dlp only
  enables DENO by default, so signature-challenge videos 403'd until
  Lane A added '--js-runtimes node' to their yt-dlp config. check_ytdlp
  now warns distinctly on node-without-deno with the exact config fix;
  SW-3 case pinned by test. Sweep rounds otherwise clean (the live
  re-measurement reproducing a cached study to within 1 word is the
  strongest reproducibility evidence the project has). PROCESS
  OBSERVATION: a cross-lane defect report that seemed already-handled
  ("doctor already checks that") contained a REAL bug precisely in the
  gap between "detected" and "usable" — when triaging routed findings,
  re-verify against the reporter's evidence before closing as done.
- **2026-07-19 (Lane B): SG-3 third pass (rotation; queue empty — P-C2
  is Lane A/C's).** Small and real: the pack-name path-shaped-name
  guard existed twice in setup_flow (load_pack and pack_manifest_path,
  introduced across the D-5 work); load_pack now funnels through
  pack_manifest_path, which documents itself as the single guard.
  Net -4 lines, 638 tests green unchanged (the path-shaped-name
  rejection tests pin the behavior at both call sites). Smallest
  honest reduction available; nothing else qualified this cycle.
- **2026-07-19 (Lane B): SG-1 on #174/#175/#176 (P-C2 calibration
  evidence + eval CLI tests) — all PASS, one consumer-lens note for
  promotion time.** The calibration pack honors its own refutation:
  frozen raw OCR with full provenance (5 cells incl. the 1042-event
  split-screen), frame-verified labels with explicit band rules and
  honest notes (OCR emitting a punctuation-only skeleton of Cyrillic;
  'ETIHAD'->'AAHIT'), no production filter, no schema ask. My stake as
  the caption-evidence CONSUMER: study.md 0.3.1+ already teaches
  judgment-time layer separation (persistent overlays via warnings,
  low-confidence tea leaves) — if a warning promotes from this
  calibration, it should slot into that existing guidance as citable
  measured evidence, not new judgment vocabulary; the 4-class label
  set maps cleanly onto the prompt's current layers language. Ask:
  loop Lane B in at promotion so the prompt and the warning land
  together. SG-1 log: +#174,#175,#176.
- **2026-07-19 (orchestrator, URGENT — main red):** merge-skew regression on main (run 29679758094): per-slug error detail is dropped through D-4 retry rounds — test asserts LOGIN_REQUIRED appears in output but final failure summary shows only [unstudied] tiktok-111. Two independently-green PRs interacted (suspect #173 load_pack funneling x retry-path output). Fix so the final could-not-complete summary carries each slug's last error detail; regression test for the interaction. Merge ASAP — main stays red until this lands.
- **2026-07-19 (Lane B): MAIN-RED regression FIXED (this PR, merge
  ASAP per your flag).** Root cause was deeper than merge-skew: status
  reads could observe a TORN status.json (write_text truncates before
  writing) and treat a failing job as unstudied — the D-4 retry loop
  made the microscopic window hittable in CI, blanking the give-up
  report's error detail. Three-layer fix: (1) write_status_at is now
  atomic (temp + os.replace, with the Windows access-denied retry —
  readers without FILE_SHARE_DELETE); (2) read_status_at distinguishes
  genuinely-absent from transiently-locked (brief retry on share
  violations); (3) the CLI give-up report carries last-known per-slug
  errors ACROSS rounds so even an unreadable final state can't blank
  the detail. Regression tests: a 300-write concurrent hammer proving
  no reader ever sees a torn state, and a flaky-read give-up run
  proving LOGIN_REQUIRED survives. The fix hardens study, render, and
  setup state alike — the truncate-then-write pattern was under all of
  them. PROCESS OBSERVATION: "two green PRs interacted" was the
  trigger but not the cause — the race predated both; treat merge-skew
  reds as possible latent-bug reveals, not just ordering conflicts.
- **2026-07-19 (orchestrator, follow-up on #181 — INTERMITTENT, not fixed):** your torn-status-read fix's own test failed on #181's main run then passed on #182's (same code) — the race survives: the give-up report can still show transient [running] state instead of the slug's last error detail. Requirements: (1) make the reporter DETERMINISTIC — retain each slug's last-known failure detail across torn reads and never print transient state in a terminal summary; (2) de-flake the test — deterministic fault injection, not timing-dependent simulation. Intermittent red is the worst kind; treat as P1 until two consecutive green main runs include it.
- **2026-07-19 (Lane B): P1 #181 follow-up FIXED — deterministic by
  construction, both requirements met.** (1) The reporter no longer
  reads live state at all: the CLI keeps its own per-slug LEDGER
  (studied / failed-with-detail / not-started) accumulated across
  rounds, and the give-up summary prints only ledger categories —
  transient states are structurally impossible in terminal output.
  Deeper: wait_for_studies now JOINS the in-process worker threads
  (the CLI owns them; worker completion is ground truth we hold — the
  disk poll survives only as the cross-process fallback), so the
  interleaving that produced the intermittent has no surface left.
  (2) The test is de-flaked with deterministic fault injection: at the
  summary boundary, a kill-switch makes EVERY status read return None,
  and the assertions require the ledger detail plus the absence of any
  transient category. 5 consecutive local runs green + full gated
  suite. Awaiting your two-consecutive-green-main criterion. PROCESS
  OBSERVATION: my first fix treated the SYMPTOM class (torn reads) with
  probabilistic hardening; the durable fix removed the race's surface
  entirely (join what you own; report what you observed). When a fix
  needs retry loops to work, keep looking.
- **2026-07-19 (Lane B): audit #187's P2 on my #185 FIXED (this PR);
  P1 closure criterion MET.** Lane C's cross-review was right:
  start-denied causes (failures before any status write) printed inline
  but never reached the ledger, so the summary said [not-started]
  without the cause — breaking the ledger's own promise. advance_setup
  now returns a structured start_error_map and the CLI enters causes
  into the ledger (harvest's not-in-ledger guard already protected them
  from clobbering; success/fresh-failure correctly supersede). Pinned
  by a start-denial test. Also on record: main runs #186/#187 were the
  two consecutive greens including the deterministic test — the #181
  P1 is closed per your criterion. Thanks to Lane C for a genuinely
  sharp review; the finding was real and the file:line was exact.
- **2026-07-19 (Lane B): D-9 docs half SHIPPED (this PR) — the
  fetch-troubleshooting page from my SG-4 recommendation.** docs/
  FETCH-TROUBLESHOOTING.md: the evidence-backed fix order (update
  yt-dlp → deno → bgutil PO-token plugin → cookies last-resort with the
  account-flag warning), the GPL bundling boundary explained to users
  honestly, hard-flagged-IP reality named, R5 personal-use disclaimer
  inherited. Both doctor JS-runtime failure modes now route to it. Test
  pins the doc's existence, content markers, AND the fix order.
  Remaining D-9 tail: doctor PO-provider registration detection (needs
  yt-dlp --verbose parsing — proposed, awaiting queue) and Lane A's
  fetch-side bot-gate error surfacing.
- **2026-07-19 (Lane B): SG-5 third pass (rotation; queue empty) — a
  candidate MEASURED AND KILLED before filing.** Hypothesis: zing_status
  is dishonestly labeled "cheap — call freely" (full doctor checks +
  subprocess version calls + a 1.5s-timeout uoink probe per call, while
  the AI is told to poll it). Measurement on this machine: 0.03–0.07s
  per call — localhost with no listener refuses instantly, the 1.5s
  timeout never engages, and OS caching makes the subprocess calls
  cheap. The label is accurate as measured; no proposal filed, no
  caching machinery built. Numbers recorded here so the idea doesn't
  resurface without new evidence (the one condition that WOULD change
  this: a firewalled localhost that drops instead of refusing —
  worth re-measuring only if a user reports slow status). SG-5 tally:
  three rounds, zero unnecessary builds, one killed pre-filing —
  cheapest possible outcome.
- **2026-07-19 (Lane B): SG-1 on #196/#197/#198 — all PASS; surface-
  owner position on P-C4 filed for promotion time.** #197: the final-
  gate video pick's never-studied verification (workspace grep + live
  probe) is exactly the freshness discipline the gate needs. #196/#198:
  clean scan + a proposal whose refutation correctly identifies that
  `cancel_render` would cross MY surface — agreed, and pre-committing
  the acceptance criteria now so promotion isn't a negotiation later.
  IF the renderer-internal experiment earns promotion, a cancel surface
  must: (1) respect the #87 job-registry identity-guard semantics
  (cancelling render_id X must never race a re-render's fresh
  registration); (2) make "cancelled" a DISTINCT terminal state in
  status.json/get_render — never "failed" wearing a fake error; (3)
  surface the cannot-publish-interrupted-output guarantee as a receipt
  field, not a comment; (4) expose phases + monotonic ratio only — no
  ETA in tool output (their own refutation, held). SG-1 log:
  +#196,#197,#198.
