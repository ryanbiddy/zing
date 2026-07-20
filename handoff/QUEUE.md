# Work queue â€” pull the top unclaimed item in YOUR lane when your current gate passes

Claim an item by appending a line to your NOTES file ("claimed D-Q1"),
then work it like any lane item (own paths, PR flow, doc-only where
marked). Orchestrator seeds this file; workers may add PROPOSED items at
the bottom but never claim outside their lane.

## Lane A (study engine)
- **A-Q1:** R1-A measurement-science research round (still owed â€”
  ASSIGNMENTS-R1 Â§R1-A; you built ingest first, fine, but the deliverable
  gates your detector/OCR dependency picks).
- **A-Q2:** accuracy iteration against Lane C's goldens once both exist â€”
  drive scores up, one PR per fix, per-fix deltas cited from the eval
  report.
- **A-Q3 (S2 prep):** keyframe quality pass â€” verify hook-window keyframes
  are judgment-usable (sharp, representative) on the example-dataset
  videos.

- **A-Q4:** X native + YouTube long-form as study sources — format-aware hook window (0-3s short-form / 0-30s long-form per TASTE-FRAMEWORK H5), aspect-agnostic study, long-form perf documented. **A-Q5:** optional phase_callback= kwarg on study() for real per-phase zing_status.

## Lane B (surface)
- **B-Q1:** finish S1 per spec order: doctor â†’ MCP server â†’ prompt pack â†’
  uoink bridge.
- **B-Q2:** .mcpb / client-connect packaging prep: document the exact
  Claude Desktop + Claude Code config for zing serve-mcp, uoink-style
  one-click where possible (doc + small glue only).
- **B-Q3 (S2 prep):** get_frames(slug, timestamps[]) tool design note â€”
  result shape, size limits, MCP image content â€” ready to build at S2 open.

- **B-Q4:** x.com/twitter.com status slugs + platform 'x' in storage. **B-Q5:** early S1 cross-review of Lanes A+C -> handoff/reviews/S1-REVIEW-lane-b.md.

## Lane C (eval + render)
- **C-Q1:** finish C-1 per spec + critique resolutions (incl. Windows CI
  job, machine-readable eval reports).
- **C-Q2:** C-2 renderer per spec (pysubs2 for .ass; content-probe oracle).
- **C-Q3:** performance benchmark harness â€” per-stage wall-clock (ingest /
  shots / transcribe / OCR / audio / render) captured in the eval report;
  ROADMAP's perf budget becomes a tracked number before it becomes a gate.
- **C-Q4:** real-video regression bootstrap â€” run the eval adapter on the
  two EXAMPLE-DATASET videos, freeze breakdown outputs + provenance as the
  first real-video regression set (pairs with D-Q2 truth annotations).

## Lane D (Antigravity â€” doc-only lane)
- **D-Q1 (NOW):** genre rubrics v1 â€” synthesize YOUR R1-exemplar-teardowns
  + docs/taste/TASTE-FRAMEWORK.md into three files:
  docs/taste/RUBRIC-talking-head.md, RUBRIC-tech-launch.md,
  RUBRIC-vlog.md. Per rubric: criteria with IDs (G-TH-1â€¦), proposed
  weights, per-criterion "Zing measures / AI judges" split, confidence
  tier per claim, every claim traced to a teardown exemplar or framework
  criterion. These become the S2 judgment scoring sheets.
- **D-Q2:** coarse human truth for the example dataset â€” watch both
  EXAMPLE-DATASET videos end to end; document per video: structure beats
  with rough timestamps, hook classification, caption-style description,
  approximate cut density, audio layout. Save as
  handoff/research/EXAMPLE-DATASET-TRUTH.md. This is the judgment-layer
  truth the wizard-of-oz gate and the frozen regression set score against.
- **D-Q3:** fresh-eyes documentation QA â€” read README + docs/ as a
  newcomer who just found the repo; file every gap/confusion as one
  doc-only PR of fixes or a findings note.

## PROPOSED (workers append; orchestrator promotes)
- **PROPOSED (Lane A, SG-5, 2026-07-19 #3): `zing profile pack
  <manifest> --reverify` — reference-rot probe pass.**
  PROPOSAL: metadata-probe (no download) every reference URL in a
  pack manifest and report per-ref: live / dead / changed
  (title/duration drift vs the studied breakdown), with probe dates.
  Mutates NOTHING — output is the evidence Lane D's link-rot upkeep
  process needs to curate replacements. Evidence: SW-2 (the S1 gate
  video went "Video unavailable" within WEEKS); 32 shipped-pack refs
  carry verified_at dates that only age; and build_pack's rot
  detection has a structural blind spot — REUSED references are never
  re-probed, so a fully-cached pack rebuild reports all-green on a
  manifest that may be substantially dead (exactly SW-2's shape).
  REFUTATION (mine): (1) Lane D owns link-rot upkeep — yes, the
  PROCESS; this is the TOOL, and it lives in the pack builder Lane A
  owns; output is theirs to act on. (2) fetch-budget risk — probes
  are --simulate metadata calls (~1s, no media), but they DO count
  against platform rolling windows; mitigation in-spec: sequential
  with backoff, and the command is manual/scheduled, never implicit
  in builds. (3) drift false-positives — titles get edited routinely;
  "changed" is reported as observation with both values, never as
  dead; only fetch-refusal states are "dead."
  SURVIVES AS: a small subcommand flag + probe helper in
  profile/packs.py + command.py, offline tests with mocked probes;
  no schema change, no new deps; Lane D consumes the report.
- **PROPOSED (Lane A, SG-5, 2026-07-19 #2): study-time breakdown
  self-consistency check.**
  PROPOSAL: before study() writes breakdown.json, run the invariant
  checks the S5 sweep applied by hand (shot spans positive and within
  duration ±0.5s; word timestamps monotonic and within duration ±1s;
  caption events within duration ±1s; stage-evidence reconciliation —
  AMENDED per Lane C audit #212 P2: "provenance non-empty" was
  vacuous because zing_version/measured_at are added unconditionally
  (study/api.py:147). The real invariant: for each pipeline stage,
  EITHER its named provenance evidence is present (shots →
  shot_detector; transcribe → whisper_model; captions → ocr_backend;
  audio → loudness/vad) OR a warning names why that stage was
  skipped. A breakdown with neither is the defect this check exists
  to catch) and
  append a named warning per violation — never block, never mutate.
  Evidence: these exact checks were rewritten 4+ times in throwaway
  scripts during the sweep (repetition = missing tool), and SW-4
  (batched-seam word inversions on the 62-min cell) was caught ONLY
  because a hand-run script looked; the pipeline would have shipped
  the violation silently. Cost: pure-Python pass over in-memory
  lists, sub-millisecond even at 10k words.
  REFUTATION (mine): (1) overlaps Lane C's eval goldens — no: goldens
  verify frozen fixtures at eval time; this guards EVERY field study
  at write time, where SW-4 actually appeared. (2) tolerance
  false-alarms — the sweep ran these tolerances over 9 cached + 7
  live cells with zero false positives; tolerances are evidenced, not
  invented. (3) warnings nobody reads — warnings land in
  breakdown.warnings, which the report surfaces and the eval asserts
  on; that channel is already load-bearing.
  SURVIVES AS: a small `_self_check(breakdown) -> list[str]` in Lane
  A's report or api module + tests; no schema change, no new deps.
- **PROPOSED (Lane A, SG-5, 2026-07-19): passive reference-loudness atlas.**
  PROPOSAL: measure integrated LUFS + true peak (ffmpeg ebur128, one
  extra audio-only pass, ~1s per short) of every fetched reference at
  study time, recorded in provenance; add a tiny corpus report
  (`tools/` or `zing profile` extension) that prints the distribution
  per platform once >=20 references exist. Evidence: R1-A found NO
  primary-source loudness target exists for TikTok/Reels (only Spotify
  documents -14); EDITING-CRAFT-AND-SPECS cites folklore for exactly
  these numbers; C-Q7's eval advisories currently check renders against
  those folklore bands. Passive data accrues free with every study and
  replaces folklore bands with an owned distribution.
  REFUTATION (mine): (1) SAMPLE BIAS — admired hand-picked references
  describe "what Ryan's taste sounds like," not platform norms; the
  report must be labeled "delivery loudness of fetched admired
  references," never "platform targets." (2) FETCH-CHAIN DISTORTION —
  yt-dlp audio streams are platform transcodes; for YouTube, files
  retain source loudness (normalization is playback-side), but
  TikTok/IG pipeline behavior is unverified — the atlas measures what
  successful uploads CARRY after platform processing, which is
  arguably the right render target anyway, but the claim must say so.
  (3) REDUNDANCY — the RYAN-GATED calibrated-upload proposal above
  yields strictly better (T1) data; however it may never clear its
  account gating, and the passive atlas costs ~nothing and works today.
  SURVIVES AS: a small, gated item — measurement half now (provenance
  field, no schema change: provenance["delivery_loudness"] = {lufs_i,
  true_peak_db}), report half gated on >=20 studied references; all
  outputs labeled per refutation (1)/(2). Drop if the calibrated-upload
  experiment gets approved and run first.
- **PROPOSED (orchestrator, R-3 candidate, RYAN-GATED):** calibrated-upload loudness measurement â€” upload known-LUFS test clips to TikTok/IG/YT and measure what comes back; turns the biggest spec unknown into owned T1-grade data. RED-adjacent (posting to Ryan's channels) â€” needs Ryan's explicit go + a throwaway account decision.


## Lane C — post-fix-sprint queue (orchestrator, 2026-07-18 morning)
- **C-Q5:** F-13 + F-14 + output presets. Fix the 9:16-hardcoded caption geometry (derive ALL geometry from the EDL width/height — this unblocks Ryan's long-form scope) and the word-timed caption strobe during inter-word gaps (hold the last word or fade, per pysubs2 capability). Add output preset validation for 9:16 / 16:9 / 1:1 with content probes for a landscape render.
- **C-Q6:** speech fixture — close your own eval gap. Source a properly-licensed spoken clip (public domain / CC0, e.g. LibriVox; document license + provenance in the fixture dir), mux with ffmpeg-generated exact silence so intervals stay exact-by-construction, and ENABLE speech_ratio scoring (currently honest-unavailable). Mutation test included.
- **C-Q7:** loudness + true-peak probe fields in the eval report (flag integrated outside [-18,-10] LUFS or TP > -1 dBTP per docs/taste/EDITING-CRAFT-AND-SPECS.md — report fields/warnings, not gates), if not already present from C-Q3.
- **C-Q8:** F-17 tail sweep — read all three S1 review files' remaining P3 notes, fix the Lane C-owned ones (incl. any not itemized in the fixlist), one small PR.

## Lane A — post-fix-sprint queue (orchestrator, 2026-07-18 morning)
- **A-Q6:** keyframes into the judgment loop — the wizard-of-oz run showed visual criteria go dark because keyframes are not committed with frozen regression baselines and not surfaced to the judging AI. Ship keyframes alongside breakdown.json in the baselines (small, license-safe JPEGs), and verify hook-window keyframes are sharp/representative on both real videos.
- **A-Q7 (with Lane B):** F-15 — pass workspace explicitly through study() instead of the thread-unsafe env-var override.
- **A-Q2 (continuing):** accuracy iteration vs goldens + real-video baselines; per-fix deltas cited from eval reports.

## Lane B — post-fix-sprint queue (orchestrator, 2026-07-18 morning)
- **B-Q6:** prompt pack v0.2 from wizard-of-oz findings (handoff/WIZARD-OF-OZ-2026-07-18.md §4): add curiosity_gap/open-loop to the hook vocabulary; scale sync-judgment claims to OCR sampling resolution; OCR layer-separation guidance (UI labels vs burned captions); retake vocabulary for raw-footage judgment. Version-bump the pack.
- **B-Q4 (still open):** x.com/twitter.com status slugs + platform 'x' in storage.
- **B-Q7 (with Lane A):** F-15 workspace threading — your MCP job runner side.
- (B-Q5 cross-review: DONE by stand-in agent; read handoff/reviews/S1-REVIEW-lane-b.md and flag disagreements in your NOTES.)

## Lane D (Antigravity) — queue (orchestrator, 2026-07-18 morning)
- **D-Q4:** F-16 — your EXAMPLE-DATASET-TRUTH.md is wrong about the "raw" clip (measurements prove 33 cuts + captions + music; see handoff/WIZARD-OF-OZ-2026-07-18.md §2). Re-watch, correct the truth doc, and source ONE genuinely unedited talking-head replacement (verify by eye before writing it down); document both.
- **D-Q5:** R-4 kickoff (handoff/research/ASSIGNMENTS-R3.md §R-4) — creator-genre taste corpus, first two genres: TECH and COMEDY. Top 3 creators each on YouTube + TikTok, teardown per your R1-D format, feeding genre rubric v2. Doc-only.

## Gated prototypes (claim only when the named research has landed on main)
- **C-Q9 (gated on docs/taste/TRANSITIONS-AND-MIX.md):** transition-detection prototype — implement frame-diff/optical-flow/audio features for the top 5 detectable transition signatures from R3-A; extend make_goldens with synthetic transitions (dissolve, wipe, zoom punch); report per-signature precision on goldens. Honest about what is NOT detectable.
- **C-Q10 (gated on docs/taste/PACKAGING-INTROS-THUMBNAILS.md):** `zing thumbs` deterministic half — candidate freeze-frame selection per the R3-B spec (emotional peaks via audio energy, object reveals via shot boundaries, contrast/sharpness scoring), CLI + MCP tool emitting frames + the three crafted image-LLM prompts from the spec template.
- **D-Q6:** Zing product-surface UX study (doc-only): audit the CLI/breakdown.md/MCP ergonomics as a NEW USER; study uoink's brand system at E:\AI\projects\uoink\brand (brand-system HTML + launch kit) and propose how Zing's look/voice should rhyme with it (sibling, not clone); sketch the eventual local dashboard surface (uoink-style) as a doc. Design implementation stays LATER — this is the thinking doc.

## V-round: define VIRALITY per platform (Ryan, 2026-07-18) — one per lane, doc-only
The taste director must know what virality measurably IS on each channel.
Per platform: a measurable definition (metrics/thresholds that mark a video
as viral there), the spread mechanism (what surfaces drive it), leading
indicators in the first hours, genre differences, and what the taste engine
should score as viral-potential. House format: tiers, sources, Deeper
Threads. Deliverable: docs/taste/VIRALITY-<platform>.md.
- **V-A · Lane A:** YouTube + Shorts.
- **V-B · Lane B:** TikTok.
- **V-C · Lane C:** X native video (fold in handoff/research/R3-grok-x-findings.md when it lands).
- **V-D · Lane D (AG):** Instagram Reels.
Orchestrator synthesizes the cross-platform comparison after all four land.

## S2-prep wave (orchestrator, 2026-07-18 evening — sanctioned ahead of the formal S2 spec; keep lanes busy)
- **C-Q11:** V-C X virality definition if not yet claimed (docs/taste/VIRALITY-x.md; fold handoff/research/R3-grok-x-findings.md).
- **C-Q12:** transition detector v2 — integrate the #65 prototype into the study pipeline behind a flag: Breakdown gains typed transition observations via the judgment-free measurement path (orchestrator will add a schema field on request — write the proposed field shape to NOTES first, do NOT touch schemas.py).
- **C-Q13:** real-video eval expansion — add 3 more real videos to the frozen regression set (one landscape long-form, one X-native if fetchable, one more short), full provenance discipline.
- **A-Q8:** OCR caption quality iteration against the real-video set — drive caption recall/precision up, per-fix eval deltas.
- **A-Q9:** long-form study performance — chunked/streamed transcription strategy for 10min+ videos, measured against the perf harness.
- **B-Q8:** build get_frames(slug, timestamps[]) per your own B-Q3 design note (S2 fast-follow pulled forward — judgment needs eyes; wizard-of-oz proved it).
- **B-Q9:** .mcpb packaging — build the one-click bundle for Claude Desktop per docs/CONNECT.md, tested install flow documented.

## Lane D — light-work wave (orchestrator, 2026-07-18 evening; sized for fast collation/verification)
- **D-Q7:** taste-docs master index — build docs/taste/INDEX.md: one table of EVERY criterion ID across all taste docs (ID, one-line claim, tier, source doc, link). Pure collation, high value: the judgment prompts need a single lookup surface. Keep it regenerable (note your method at the top).
- **D-Q8:** link-rot + source verification pass across all docs/taste/*.md — check every source link resolves, mark dead ones inline with [DEAD 2026-07-18] + a replacement if findable, summary note in NOTES.
- **D-Q9:** reference candidates for Ryan — find 10 candidate reference shorts across our genres (tech, comedy, informative, product, vlog) that exemplify the rubrics; verify each URL is live; one-line "why this one" per pick citing a rubric criterion. Save handoff/research/REFERENCE-CANDIDATES.md. This feeds Ryan's S3 pick-list.
- **D-Q10:** breakdown.md readability QA — read the frozen real-video breakdown.md files as a CREATOR would; list every jargon term, unclear number, or missing explanation; doc-only findings note.
- **D-Q11 (mechanical re-tier):** VIRALITY-instagram.md claims V-IG-3, V-IG-7, V-IG-8 assert exact numbers (10x follower ratio, completion-gate thresholds) as fact that VIRALITY-TIKTOK.md tags FOLKLORE and VIRALITY-X.md bans outright — see VIRALITY-SYNTHESIS.md contradictions section. Re-tier those three claims to T4/folklore with the same wording pattern the TikTok doc uses, add a cross-reference note to the synthesis, and update INDEX.md rows accordingly. Do not change any other claims.

## STANDING GENERATORS (all lanes — NEVER idle: when your lane queue is empty, run ONE of these per cycle, rotating)
- **SG-1 · cross-review for tightness:** pick the most recent 2-3 merged PRs from OTHER lanes you have not yet reviewed; review the actual diffs for correctness, simplification, test gaps, honesty of failure states. Small safe fixes = direct fix PR; judgment calls = findings in your NOTES with file:line. Log which PRs you covered so reviews do not repeat.
- **SG-2 · coverage sweep:** find the lowest-covered module in YOUR lane, add happy-path + one error-path test. Coverage number must rise (state before/after).
- **SG-3 · simplification pass:** the smallest change that genuinely reduces complexity in your lane (dead code, duplicated logic, over-clever constructs). Tests green, no behavior change, PR explains the reduction.
- **SG-4 · trending-OSS scan:** GitHub trending + topic searches (video, creator tools, social, subtitles, media-ml). Evaluate 3-5 repos not yet in PRIOR-ART-OSS.md: license, health, REUSE/BORROW/SKIP for us. Append to handoff/research/PRIOR-ART-OSS.md with date stamps.
- **SG-5 · feature-gap analysis (challenge required):** propose ONE roadmap candidate grounded in evidence (sentiment docs, competitor surface, taste research), then write your OWN refutation (why it might be wrong/bloat/premature). Only if the proposal survives your refutation, add it to QUEUE §PROPOSED with both halves. No unchallenged proposals.

## Cross-review wave (concrete, claim now)
- **A-Q10:** SG-1 aimed: review Lane C's shipped day — transition prototype (#65), thumbs (#66), output presets, speech fixture. Measurement-scientist lens: are the signatures/selectors honest about their limits in code, not just in NOTES?
- **B-Q10:** SG-1 aimed: review Lane A's caption-region clustering (#70) + keyframe work — surface/consumer lens: does what MCP serves match what was measured?
- **B-Q11 (gated on C-Q12 merge):** prompt pack v0.3 — teach prompts/study.md the transitions vocabulary + thumbs + get_frames tools (what the judging AI can now see and how to use it honestly).
- **A-Q11 (gated on C-Q12 merge):** breakdown.md renders transition observations (plain-language line per transition, honest about opt-in/absence).

## PROPOSED (SG-5 — proposal + refutation required, orchestrator disposes)

- **WATCH-ITEM (Lane B, SG-4, 2026-07-19): MCP spec 2026-07-28 goes
  final in ~9 days and is the protocol's largest-ever revision.**
  NOT a proposal — a dated tripwire with a hard trigger. Breaking
  changes in the RC (locked 2026-05-21): the initialize/initialized
  handshake is REMOVED (client info + capabilities move to `_meta` on
  every request), protocol-level sessions are gone, Roots/Sampling/
  Logging are deprecated, and missing-resource errors move from
  -32002 to -32602. stdio itself survives.
  ZING'S EXPOSURE TODAY IS LOW AND MEASURED: we ship stdio-only, use
  no Roots/Sampling/Logging, hold no protocol-level session state
  (job handles are already ordinary slug arguments the model passes
  back — exactly the pattern the RC prescribes), and our negotiation
  is spec-correct in all three directions (verified live: old client
  echoed, current matched, FUTURE version answered with our latest
  rather than an echo or a failed handshake — now pinned by tests).
  TRIGGER: when the mcp Python SDK ships 2026-07-28 support (their
  stated window is ~10 weeks from RC lock, i.e. roughly now), bump
  the pin and re-run the stdio gate; the handshake removal is the
  only change that touches our surface, and it lands in the SDK, not
  in our handlers. DO NOT pre-migrate against an RC.
  LAUNCH NOTE: this collides with the registry-publication proposal —
  publish AFTER confirming which spec revision our shipped SDK floor
  negotiates, so the registry entry doesn't advertise a server that
  clients on the new revision handshake-fail against.

- **PROPOSED (Lane B, SG-5, 2026-07-19 #3, PROCESS): unmocked-seam
  rule for SG-2 coverage passes.**
  PROPOSAL: amend the SG-2 standing generator with one rule — a
  coverage pass over a module that wraps an external backend
  (scenedetect, cv2, ffmpeg-adjacent, onnx) must include ONE test
  that drives the real backend through the seam (importorskip-gated),
  with everything else staying mocked. Evidence: this doctrine caught
  two live defects IN ONE DAY that green mocked suites were
  structurally blind to — scenedetect's get_seconds() deprecation
  (#255) and the real frame-decode path (#194); my #248 scan
  demonstrated the failure mode of reasoning from CI-green alone.
  REFUTATION (mine): (1) unmocked tests are slower and env-dependent
  — mitigated: the importorskip pattern is established, synthetic
  fixtures are sub-second, and CI installs the study extras anyway.
  (2) not every module HAS a drivable backend locally — the rule
  binds only where one exists (rendered ffmpeg paths stay behind the
  ffmpeg gate as today). (3) rule creep — this is one sentence added
  to an existing generator, not a new process.
  SURVIVES AS: a one-line amendment to SG-2's queue text, applying
  from the next coverage pass onward. No retroactive sweep — modules
  gain their seam test when SG-2 next visits them.

- **PROPOSED (Lane B, SG-5, 2026-07-19 #2): drift messages must name
  the update DIRECTION when contract v2 exists.**
  PROPOSAL: zing's peer/handoff drift errors currently end in "update
  uoink (or zing) so both speak INTEGRATION-CONTRACT v1"
  (doctor.py:570, uoink_bridge.py:60) — the exact dead-end shape the
  final review indicted in P1-1 ("update uoink" when uoink was
  already newest) and P2-4 (writer's unfollowable fix loop). The
  probe already holds what's needed to do better: the peer's manifest
  declares its capability VERSIONS and zing knows its own — on
  mismatch, say which side is older ("uoink speaks
  uoink.media.handoff/2; this zing speaks /1 — update ZING"). Evidence:
  P1-1/P2-4 are the review's most user-hostile finding class, and my
  own messages carry the same latent shape.
  REFUTATION (mine): (1) IT CANNOT BITE YET — v1 is the only contract
  version in existence; every mismatch today is nonconformance, not
  version skew, and "update so both speak v1" is accurate for all of
  them. (2) The build is FROZEN for Ryan's sitting — no product churn
  for a hypothetical. (3) Directionality needs the version-negotiation
  half of a future contract v2 anyway; designing it now speculates on
  v2's shape against the house rule.
  SURVIVES AS: a tripwire, not a build — the FIRST PR that bumps any
  suite contract to version 2 must also make zing's drift messages
  directional (this entry is the reminder the review said we'd
  otherwise rediscover the hard way). Zero code until that trigger.

- **PROPOSED (Lane B, SG-5, 2026-07-19): corpus-seeded onboarding —
  `zing setup` from your own uoink library.**
  PROPOSAL: a third setup source alongside packs and personal links:
  list the user's uoink corpus short-video items (uoink.corpus.read/1
  — the same contract-legal read Writer already does), let them pick
  N, and study each via study_uoink_item — ZERO network fetch, zero
  yt-dlp/JS-runtime/bot-wall friction, because the kept files are
  local. Evidence: (1) the #1 first-run failure class is fetch
  friction — D-9/D-11/D-13 and all of FETCH-TROUBLESHOOTING exist
  because of it; kept-media onboarding sidesteps the entire class.
  (2) R3 sentiment names cold-start as a churn driver; the corpus IS
  the user's taste, already curated. (3) S6 made per-item kept study
  real and cheap (#221-#224, family gate 11/11 zero-refetch). Cheap
  adapter: reuses the personal-links setup path + study_uoink_item;
  possibly ZERO uoink-side work (client-side filter over corpus.read
  results + per-item kept-media resolve).
  REFUTATION (mine): (1) PREMATURE — the final review is running and
  its fixlist outranks roadmap; Decision Week may reshape onboarding
  wholesale. (2) Capability unknown: corpus.read's result shape may
  not expose a kept-media/short-video filter — client-side filtering
  could mean N kept-media probes just to build the picker (bounded:
  probes are local HTTP, ~ms each, and §4 caps retry cadence — but it
  must be measured, not assumed). (3) Audience: only helps users who
  ALREADY run uoink with keep_media on — a subset of a subset at
  launch; packs remain the universal cold-start. Mitigation: this is
  additive shelf-inventory for the suite story, not a launch blocker.
  SURVIVES AS: post-fixlist, post-Decision-Week roadmap candidate;
  first step is a one-question capability check with uoink's owner
  (does corpus.read expose keep_media presence per item?) before any
  build.

- **PROPOSED (Lane B, SG-4, 2026-07-19): publish zing to the official
  MCP registry at launch.**
  PROPOSAL: at launch, add `server.json` (registry_type pypi,
  identifier myzing) + the `mcp-name:` marker line to the PyPI README
  and publish via `mcp-publisher login github` — zing becomes
  discoverable to every registry-reading client for ~30 minutes of
  work and zero infrastructure. Evidence: registry is live and backed
  by Anthropic/GitHub/Microsoft; PyPI servers are first-class with
  ownership verification (see research/SG4-MCP-DISTRIBUTION-2026-07-19.md).
  REFUTATION (mine): (1) premature before naming lands — the
  namespace bakes the product name in, and Decision Week owns naming;
  publishing early risks a rename migration. (2) registry churn —
  requirements tightened as recently as 2026-01; a launch-week
  re-check of the publishing guide is mandatory, my scan record rots.
  (3) not a substitute for the .mcpb bundle or CONNECT.md — it is a
  third channel, additive only.
  SURVIVES AS: a RYAN-GATED launch-checklist line (post-naming):
  server.json + README marker + one publish command; no code now.
  AMENDED 2026-07-19 (Lane B): the launch install one-liner should
  also list `uv tool install myzing` alongside pip — uv is the
  runtime our .mcpb bundle already standardizes on, and tool-install
  gives a clean isolated CLI without venv ceremony.
- **P-B1 (Lane B, 2026-07-18) · loop-ability as a measured Breakdown
  field.**
  **Proposal:** a deterministic loop score in the study pipeline:
  (a) visual seam — frame difference between the last and first frames
  (the keyframe machinery already extracts both); (b) audio seam —
  loudness-curve continuity across the end→start joint; (c) a
  `loop_seam` observation (visual_delta, audio_delta_db) with NO
  interpretation attached (measured, not judged; the prompt pack judges
  whether a tight seam is intentional). Evidence: the TikTok Algo-101
  formula weights play-time/rewatches (docs/taste/VIRALITY-TIKTOK.md,
  verified-data tier); seamless loops are a prized short-form editing
  pattern; VIRALITY-TIKTOK Deeper Thread 3 flagged that nobody in the
  trending set (SG-4 scan) measures loop design; marginal cost is low —
  both inputs (keyframes, loudness curve) already exist per breakdown.
  **Refutation (mine):** (1) first/last-frame similarity is a weak
  proxy — perceived loops are about motion continuity, not static
  similarity; a cut-on-motion loop scores badly on frame diff while
  looping beautifully. (2) Base-rate risk: if Ryan's actual reference
  set contains no loop-designed videos, the field is dead weight —
  nobody has checked the frozen set. (3) S3 (Direct) is the priority;
  any Lane A capacity spent here delays the product's core loop.
  (4) Needs an orchestrator schema change for a maybe-feature.
  **Survives as:** a GATED proposal only — step 1 is a zero-schema
  check: run the seam measurements ad hoc against the frozen reference
  set + Ryan's picks when they land; if ≥2 references show tight seams
  (they were designed to loop), promote to a schema request for S3;
  if none do, drop it with the evidence recorded. No build before the
  base-rate check.
- **P-D1 (Lane D, 2026-07-18) · local auto-rough-cut EDL generator (silence & filler-word removal).**
  **Proposal:** Introduce a local auto-rough-cut EDL generator in the study engine/CLI (`zing cut <video>`). By analyzing VAD silence intervals (>1.5s) and Whisper word-level timestamps for filler words ("um", "uh", "like") and duplicate takes, Zing can output an EDL JSON or Premiere/Resolve XML that cuts these segments automatically. This automates the tedious A-roll cleanup phase for creators.
  **Refutation:** (1) Blindly cutting transcripts causes choppiness, audio pops, and disjointed J-cuts; solving this requires complex zero-crossing alignment or cross-fades. (2) Whisper timestamps are often slightly offset (100ms–200ms), which results in clipped words. (3) XML timeline export is fragile and prone to NLE import bugs. (4) Video editing is scope creep from Zing's core "taste and recommendation" value.
  **Survives as:** A **marker-only rough-cut guide** export. Instead of generating cut media timelines, Zing generates a Premiere/Resolve marker list overlay indicating "delete suggestions" for silences and fillers. This saves the creator time without any risk of audio clipping, timeline corruption, or complex XML bugs.
- **B-Q12 (small):** yt-dlp is not in the [study] extras and the gate-pack run failed honestly on it — add it (one-dep PR) and confirm doctor's staleness check covers the JS-runtime deprecation warning surfaced on every fetch.
- **B-Q13 (tiny):** prompts/compare.md's worked example uses a 0-2 scale while the genre rubric scores 1-5 — fix the example, bump prompt pack patch version.
- **C-Q14 (calibration):** gate-pack run measured 29 dissolves on a talking-head video — likely detector over-calling on real footage. Calibrate the dissolve signature against the frozen real-video set; report precision honestly; tighten or downgrade to warning.
- **D-Q12 (light):** REFERENCE-CANDIDATES.md re-verification — gate-pack found 2 of 3 sampled entries stale/misattributed (#7 wrong channel, #9 re-upload). Re-verify all 10 rows, fix or replace, note method.
- **A-Q12 (S3 groundwork):** raw-footage measurement mode — the Direct sprint needs study to measure RAW recordings for retake-spotting: dead-air spans (silence >1.5s with timestamps), filler-word counts/locations from the transcript (um/uh/like/you know), and repeated-take detection (near-duplicate transcript segments with similarity + locations). Surface in Breakdown warnings/derived fields per existing patterns; propose any schema need via NOTES first. This is the measurement half of S3.
- **A-Q13:** SG-1 rotation — cross-review the most recent merges you have not covered (#95-#102 range), measurement-honesty lens.
- **C-Q15 (pairs with A-Q12):** raw-footage measurement goldens — synthetic fixtures with constructed dead-air spans, filler-word insertions (spoken fixture remixes), and repeated-take segments with exact truth; scorer dimensions for each, per-dimension mutations. The eval half of S3 groundwork.
- **C-Q16:** transition detector recall validation — your own C-Q9 report said synthetic precision says nothing about recall; validate against the frozen real-video set + the gate-pack videos, report recall honestly, tune or downgrade signatures that fail.
- **A-Q14 (REASSIGNED from Lane D — S4 Track 2 unblock, HIGH):** the vetted per-pack reference sets are now YOURS, Lane A: for each preset pack (ai-tech-talking-head, viral-tiktok-reels, informative-explainer, vlog, product-launch; vertical+horizontal variants where the genre supports it) curate 5-8 references with EVERY URL live-verified at curation time (fetch the page, confirm title/channel match — the D-Q9/D-Q12 staleness lesson is the reason this moved), one-line rubric-cited "why" each, stable IDs + retrieval dates per the LAUNCH-PLAN reproducibility rules. Then flow straight into your claimed Track 2 builder work (batch-study + pack builds) — you own the whole preset pipeline end to end now. Lane D keeps link-rot upkeep AFTER packs exist.
- **P-C1 (Lane C, SG-5, 2026-07-19) · opt-in post-render verification manifest.**
  **Proposal:** add `zing render --report <json>` after Assemble. The
  versioned report records the output SHA-256 plus measured duration,
  dimensions, frame rate, pixel format, streams, audio sample rate/channels,
  C-Q7's integrated LUFS and true peak, and advisory-only delivery warnings.
  Scripted VO adds provider/package version, voice/language/speed, script hash
  (never text), model/voices hashes, WAV hash, duration, and placement. OTIO
  export adds its hash and track count. Evidence: `RenderResult` currently
  proves only that FFmpeg returned a file, while the C-Q7 delivery probe lives
  inside the eval harness and the new S4 `SynthesisResult` does not identify
  the model or script that produced a voice. A portable report would make a
  real draft as inspectable and reproducible as the frozen eval artifacts.
  **Refutation:** (1) ebur128 adds another audio-length pass to every reported
  render and duplicates eval code; (2) repeatedly hashing a roughly 80–300 MB
  model wastes time; (3) technical facts cannot establish pronunciation,
  intelligibility, taste, or NLE-import success, so a "quality score" would
  launder uncertainty; (4) script text or absolute model paths in a report
  would create a privacy leak; (5) another default sidecar would clutter the
  simple `zing render` path.
  **Survives as:** opt-in only, with no score, gate, automatic normalization,
  script text, or absolute model path. Promote C-Q7's probe into one shared
  render-owned measurement module instead of duplicating it; cache large-file
  hashes by resolved path + size + mtime; make every unavailable field carry a
  reason. The regression bar is one exact constructed render plus isolated
  mutations for media facts, delivery audio, VO provenance, and OTIO
  provenance. Actual NLE import and human listening remain separate manual
  gates.
- **P-C2 (Lane C, SG-5, 2026-07-19) · warning-only caption-evidence calibration.**
  **Proposal:** add a caption-evidence quality label beside each OCR event:
  `likely_caption`, `incidental_text`, `unsupported_script`, or `unreadable`.
  Candidate signals are temporal persistence, region stability, recognized
  script, and lexicality; raw OCR text and confidence remain untouched.
  The live Sprint 5 record (`handoff/research/S5-SWEEP-LANE-A.md`) shows why
  confidence alone cannot carry this job. The SpaceX cell produced 60 events
  that were largely texture junk at median confidence 0.88; Cyrillic overlays
  became fabricated Latin at 0.77–0.93; and the 430-second split-screen cell
  produced 1,882 events mixing story text with gameplay HUD. The SG-4 review
  of video-subtitle-extractor independently identified persistent logos,
  bilingual text, sparse captions, and duplicate lines as the right fixture
  classes.
  **Refutation:** this label would pretend an uncalibrated heuristic is a
  measurement. Lexicality penalizes names, slang, code, and deliberately
  fragmented captions. Script detection can fail on stylized glyphs before OCR
  does. Persistence and region rules can misclassify scoreboards, watermarks,
  karaoke, and one-frame title cards. The current sweep has observations, not
  event-level truth, so no precision or recall claim is available. Adding four
  serialized states now would also cross Lane A's measurement ownership and
  force a schema decision before the candidate signals have earned one.
  **Survives as:** an offline, warning-only calibration pack owned jointly by
  Lanes A and C. Freeze event coordinates, raw OCR, frame hashes, and manual
  labels from the three cited cells plus known-good creator captions; keep
  source frames local when redistribution is unavailable. Compare candidate
  signals against the current confidence-only baseline with per-class
  precision, recall, and abstention. There is no production filter, no schema
  request, and no text rewrite in this phase. Promotion requires a held-out
  result showing that a named warning separates at least one failure class
  without reducing recall on real captions; otherwise archive the pack as
  negative evidence.
- **P-C3 (Lane C, SG-5, 2026-07-19) · opt-in rendered-output proof sheet.**
  **Proposal:** add `zing render --proof-sheet <dir>` as a local review aid
  for the finished render. It writes JPEGs, a static HTML index, and a JSON
  manifest for a deterministic, bounded sample: the first and last decodable
  frames plus stratified clip-midpoint, caption-active, and uniform-timeline
  frames. Each row carries the exact output timestamp and selection reason;
  the manifest carries the output SHA-256, probed dimensions and duration,
  sampling version, selected count, and omitted-candidate counts. This fills
  a gap between source-oriented `get_frames`/`zing thumbs` and Lane C's
  test-only content oracle. C-Q5 shipped after regressions exposed portrait
  geometry on landscape output and word-caption strobe. Creator reports in
  `handoff/research/R3-ai-editor-sentiment.md` independently describe sliding
  captions and flashing CapCut captions as trust-breaking failures. A quick
  scan of frames extracted from the actual output would make aspect,
  padding, wrong-shot, black-frame, and some caption-placement failures
  easier to spot before upload.
  **Refutation:** a still sheet cannot verify audio, A/V sync, transition
  smoothness, caption speech sync, or any defect between sampled frames; it
  cannot prove motion or prove that the render is clean. A sample cap can
  hide the one broken frame that matters and create false reassurance.
  Decoding and hashing a finished long-form render adds I/O, while a player
  or NLE already provides complete playback. The surface partly overlaps
  `get_frames`, and the extracted images can expose private footage if a user
  shares the directory.
  **Survives as:** an opt-in, local-only artifact with no upload, no score,
  and no pass/fail verdict. The HTML must say that sampled stills cannot
  verify audio or prove motion, timing, sync, or defect absence; it points
  the creator back to full playback. Sampling stays bounded and deterministic
  with visible omission counts, never silently dropping candidate classes.
  Reuse C-Q17's explicit full-range JPEG conversion, but extract from the
  finished output rather than the source Breakdown. No schema change.
  Promotion requires a constructed two-clip render with captions and isolated
  regressions for output-hash identity, timestamp/reason pairing, class
  omission counts, missing-frame failure, and portrait/landscape/square
  contact-sheet layout.
- **P-C4 (Lane C, SG-5, 2026-07-19) · cancellable render lifecycle without ETA theater.**
  **Proposal:** give the renderer an explicit process-lifecycle contract.
  Today `pipeline._render_in_directory()` hands the whole encode to one
  `subprocess.run()` call with a 900-second timeout, while MCP render status
  exposes only `running`, `done`, or `failed`. The UX study names dead
  terminal states as a trust problem
  (`docs/taste/UX-STUDY-AND-SURFACE.md`), and the SG-4 review of
  `ffmpeg-progress-yield` supplies the missing cancellation/cleanup matrix.
  A renderer-owned process runner could use FFmpeg's `-progress pipe:1`
  channel to report `prepare`, `encode`, and `publish` phases plus encoded
  output time and a clamped, monotonic completion ratio during `encode`.
  An optional cancellation token would request a graceful quit, wait for a
  bounded interval, fall back to a forced kill, reap the child, and never
  publish a staged output from an interrupted render.
  **Refutation:** the UX evidence concerns `zing study`, not a measured render
  complaint, and MCP already keeps rendering off the request thread. Output
  time divided by target duration is no ETA: mux finalization, `+faststart`,
  and atomic publication still happen after the last encoded frame. Replacing
  one bounded `subprocess.run()` with `Popen` also creates concurrent-pipe,
  signal, and child-process behavior that differs across Windows and POSIX.
  A public `cancel_render` tool would cross into Lane B's surface ownership
  and add another stateful MCP action before the engine contract is proven.
  **Survives as:** a renderer-internal experiment only, with no ETA, no new
  MCP tool, and no public schema change. Keep the existing synchronous API and
  make progress/cancellation optional callbacks that default to today's
  behavior. Promotion requires regressions for normal completion, malformed
  progress records, graceful quit, forced kill, child reaping, temporary-work
  cleanup, and proof that cancellation cannot publish or replace the requested
  output. Run those process tests on Windows and Linux before any CLI or MCP
  surface is proposed.
- **P-C5 (Lane C, SG-5, 2026-07-19) · opt-in renderer failure capsule.**
  **Proposal:** when a creator already asks for `--keep-work`, write a
  versioned `failure.json` if rendering fails. Today `render_edl()` probes and
  validates before it enters the requested work directory, so those failures
  leave no structured artifact. Later failures retain some generated files,
  but the caller receives only the public exception; FFmpeg stderr is bounded
  to its last 4,000 characters. The capsule would record the failed phase
  (`probe`, `validate`, `caption`, `graph`, `encode`, or `publish`), the
  sanitized public error, available FFmpeg/FFprobe identities, the EDL hash,
  intended duration/dimensions/preset, a role-based input inventory, and
  hashes of any retained graph or caption artifacts. This is adjacent demand,
  not a measured creator request: the reliability record in
  `handoff/research/R3-ai-editor-sentiment.md` says unstable exports drive
  churn, while the prior-art review found that AutoClip keeps failed responses
  and parsed timelines so failures can be inspected. Zing's own S4-D1
  investigation also depended on the exact FFmpeg 8.1.1 environment and
  filter order after six integration tests missed the defect.
  **Refutation:** a capsule is evidence, not a diagnosis. S4-D1 returned a
  successful but wrong render, so this artifact would not have caught it and
  cannot prove the cause of any recorded failure. `--keep-work` already
  retains the filtergraph and ASS file after those stages exist; the terminal
  already prints the error. Capturing tool versions adds subprocesses on an
  unhappy path, and redacting arbitrary tool output is brittle. Restructuring
  validation around a writable diagnostic directory also adds failure paths;
  if that directory itself cannot be created, no capsule is possible. A
  default sidecar would overlap P-C1, clutter successful renders, and tempt
  users to share absolute paths, media names, or caption or script text.
  **Survives as:** a failure-only extension to the existing explicit
  `--keep-work` contract, with no new CLI flag, no upload, no score, and no
  claim that the record found the cause. Normal success writes no failure
  capsule. The JSON uses role tokens instead of absolute paths, excludes
  source names and caption or script text, bounds and sanitizes the public
  error, and gives an unavailable reason for any tool identity it cannot
  collect. Promotion requires constructed failures at every named phase,
  redaction mutations for paths and private text, proof that the existing
  output remains unchanged, and an honest no-artifact error when the requested
  work directory is unwritable.
- **CD-Q1 (Lane C + Lane D, S3 full-fidelity follow-up):** replace the raw-editing-practice stand-in: Lane D sources ONE genuinely unedited talking-head clip (live-verify + eyeball per F-16 lesson; document license/provenance); Lane C studies it with raw_mode ON and re-freezes it into the regression set with raw-mode provenance + regeneration command. Then Lane B reruns the direction gate against it for the full-fidelity record (keepers from real raw measurements).
- **P-B2 (Lane B, SG-5, 2026-07-19) · judgment-backlog surface.**
  PROPOSAL: a `list_unjudged()` MCP tool / `zing judge-queue` CLI
  listing breakdowns lacking judgment sections, so onboarding flows
  into judging instead of stalling (S2-gate evidence: profiles from
  unjudged sources describe no taste; Track 2 ends on a bare "judge
  them" hint).
  REFUTATION (mine): (1) REDUNDANT — list_breakdowns already returns
  judgment_sections per slug; any AI can derive the backlog with a
  filter it writes itself; a dedicated tool is surface sprawl (the
  kinocut 150-tool cautionary verdict applies to us too). (2) The gap
  is GUIDANCE, not capability: nothing TELLS the judging AI to check
  the backlog at the right moment. (3) A tool adds a 18th surface to
  test and document for a one-line derivation.
  SURVIVES AS: prompt guidance only — taste.md and the setup_taste
  hint teach "check judgment_sections in list_breakdowns() and offer
  to work through unjudged references now." Implemented in the same
  PR (two lines, Lane B files). NO new tool; recommend disposing P-B2
  as build-rejected/guidance-shipped.
## S4 gate defects (from S4-GATE-PACK-2026-07-19.md — work its defect list verbatim; P1s first)
- **S4-D1 (Lane C, P1):** render audio-timeline bug — clip 2 audio at t=0 + silenced tail (adelay garbage-PTS silence dropped by trailing atrim on ffmpeg 8.1.1). The gate record contains the verified one-filter fix — implement it + a regression test that reproduces the ORIGINAL failure (the six green integration tests missed this; add the audio-placement probe class to the mutation matrix so it can never pass silently again).
- **S4-D3 (Lane B, P1):** setup CLI wedges on cold-start one-shot path — fix + regression; also restore pack-manifest provenance through the setup path (defect D-per record).
- **S4-D-rest (lanes per record):** remaining 7 queue-ready defects in the gate record — claim by ID in NOTES as usual.
- **Gate rerun (orchestrator, after S4-D1+S4-D3 merge):** Gate 1 rerun required before S5 opens. YouTube bot-gating on this machine left VO-with-fresh-fetch honestly unexercised — rerun uses cached/local media; the fetch-dependent half stays flagged until the S5 clean-host sweep.
- **C-Q17 (same-landmine check, from Ryan's uoink bug report):** uoink's screenshot step fails on yuv420p(tv) limited-range sources (mjpeg refuses) and yields zero frames on short clips with fixed intervals. Verify zing's keyframe/frame extraction against BOTH: add a limited-range (tv-flag) synthetic golden and confirm short-clip frame extraction never returns zero silently; if affected, fix with the range-conversion approach (scale=in_range=limited:out_range=full + -color_range pc, not the deprecated yuvj420p) and regression-test.
- **S4-D10 (Lane A, from rerun):** trim-edge words dropped from captions (final word audible but uncaptioned when word span crosses the trim boundary by <0.3s) — include boundary-crossing words whose midpoint is inside the trim; regression test.
- **S4-O2 (Lane C, small):** failed VO render leaves an empty -assets/ dir — clean up on failure; regression.
## S6 INTEGRATION (spec: uoink suite-split\S6-INTEGRATION.md — read it first)
- **B-S6:** zing side — kept-media sidecar consumption (uoink bridge v2), writer shot-list file import, doctor peer-probes per contract (wait for INTEGRATION-CONTRACT.md ratification for wire details; build the seams meanwhile).
- **A-S6:** study-from-kept-media (zero refetch when local media + provenance present).
- **C-S6:** suite-smoke eval half — cross-product flow assertions + contract conformance fixtures.
- **S5 defects:** D-11 (doctor/ingest yt-dlp resolution mismatch — B), D-12 (PackError discards per-ref causes — A), D-13 (doctor re-prescribes applied config — B), O-3 observation (caption-style-from-sparse-OCR — C eval note).
- **FIX SPRINT (Lanes B+D, TOP PRIORITY):** suite-split FINAL-REVIEW\FINAL-FIXLIST.md — Lane B: FF-2 (docs honest re pre-launch), FF-8 zing boundary, FF-9 zing-surface P2s. Lane D: FF-6 (suite CONNECT one-pager, reassigned from AG) + FF-2 doc support. P1/P2 clear before the Decision Week packet.

## LANE D RETIRED (Ryan, 2026-07-19) — all remaining Lane D work moves to Lane C (Codex)
AG delivered its early research but went silent on three committed items (FR-AG collateral lens, S6-AG docs QA, FF-6 one-pager — the latter written by the orchestrator). Lane D is dormant; do not wait on it.
- **C-D12 (was D-Q12):** REFERENCE-CANDIDATES.md re-verification — 2 of 3 sampled entries were stale/misattributed; re-verify all rows by live fetch, fix or replace, note method.
- **C-CD1 (was CD-Q1 Lane D half):** source ONE genuinely unedited talking-head clip (verify by eye + document license/provenance) to replace the F-16 stand-in, then complete the refreeze with raw_mode provenance and hand Lane B the full-fidelity direction rerun.
- **C-D-any:** any remaining Lane D slices in the FF-9 tail or standing-generator rotation — absorb them.
