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
