# NOTES — Lane A ↔ orchestrator

- **2026-07-19 (Lane A): O-1 resolved — orientation-variant packs
  shipped.** Vertical-subset manifests for the two mixed packs (same
  verified references, `variant_of` field for Lane B's setup grouping):
  `ai-tech-talking-head-vertical` (5 refs) built entirely from stored
  studies — duration IQR tightens from the mixed pack's 38-374s to
  **41-55s and the coherence warning no longer fires**, which is O-1
  solved measurably. `vlog-vertical` (4 refs) builds from 2 with honest
  exclusions — it shares the parent's rate-limit dependency and
  completes with the same one-command retry. Gate-defect status: D-7 +
  D-8 fixed earlier this evening (#149); with #150's audio fix, Track
  1's rerun should have captioned, correctly-voiced drafts end to end.

- **2026-07-19 (Lane A): SG-1 review of #133/#134/#139 + vlog-retry
  probe.**
  - **#139 (setup consumes my pack format): pass, exemplary.** The
    dual-shape parser normalizes cleanly, path-traversal guards held
    through the refactor, and the INTEGRATION-TRUTH test that loads my
    real shipped manifests in CI means this seam can never silently
    break again — exactly the right response to a concurrent-design
    race. **I endorse Lane B's process observation for promotion to a
    house pattern**: cheap adapters at lane boundaries, with one side
    committed in writing to a one-function parser, beat coordination
    overhead. That's now proven twice (their phase_callback sniff, this
    pack seam).
  - **#133 (MCP render/export): pass at skim depth** — errors-as-data
    throughout, crash honesty (disk-state rewrite, pid stripped),
    honest ImportError guidance to [render] extras; consistent with the
    house patterns. **#134: pass** — severity-contract enforcement with
    a mutation test, already covered by Lane C's own notes.
  - **vlog retry probe (~21:45): YouTube's anti-bot wall still up** on
    the probe URL; the one-command retry stays parked per the A-Q14
    closing note. If Decision Week wants the pack complete sooner, the
    --cookies-from-browser route needs Ryan's session (his call).

- **2026-07-19 (Lane A): A-Q14 CLOSED — all five packs BUILT (30/32
  references studied; honest degradation on the last 5).**
  Outcomes: ai-tech-talking-head 7/7 · informative-explainer 5/5 ·
  product-launch 6/6 · viral-tiktok-reels 7/7 · **vlog 2/7** — the five
  vlog failures are NOT dead URLs but YouTube's anti-bot wall ("Sign in
  to confirm you're not a bot") kicking in after ~28 consecutive
  fetches; the pack built honestly from the 2 survivors with all five
  exclusions named in its warnings. **Retry is one command** (reuses the
  30 stored studies, refetches only the 5): `zing profile pack
  presets/vlog.json --workspace <ws>` after the rate limit clears, or
  with `--cookies-from-browser` if Ryan wants it now (his call — needs
  his browser session).
  - **The profiles differentiate taste measurably**: viral-tiktok-reels
    = 34s median, 1.27s shots (fastest of any pack), speech 0.52 with
    n=4 first-word coverage (three sources are near-wordless visual
    craft — honestly excluded); product-launch = 177s median, 5s first
    cut, music-forward; ai-tech-talking-head = speech 0.994, instant
    first word. The numbers read like the genres they are.
  - **Design question for the orchestrator**: my duration-coherence
    warning correctly fires on packs mixing vertical shorts with
    horizontal long-forms (ai-tech: 38-374s span). Worth deciding for
    S4: split orientation sub-profiles per pack (vertical/horizontal),
    or keep one profile and let the setup flow filter by orientation?
  - Provenance note: v0 packs measured with ZING_WHISPER_MODEL=small
    (recorded per-breakdown) for batch time; regeneration upgrades the
    model trivially. Built in a scratch workspace — packs regenerate
    anywhere from the manifests, which is the point.

- **2026-07-19 (Lane A): A-Q14 DELIVERED — full preset pipeline
  (curation + builder).** Curation: **32 references across all 5 packs,
  every URL double-verified live** (page fetch + oEmbed title/uploader/
  orientation cross-check) by two agents on 2026-07-19; rejection lists
  prove the verification bit — it caught fan-channel re-uploads
  masquerading as Zach King/Drew Binsky/Veritasium, and correctly
  excluded Apple's embed-locked launch films as unverifiable-by-pipeline
  (the D-Q9 staleness lesson, applied). Machine truth in
  `presets/<pack-id>.json` (stable IDs, verified_at dates); method +
  rejection evidence in handoff/research/PRESET-PACK-REFERENCES.md.
  Builder: `zing profile pack <manifest>` batch-studies unstudied refs,
  builds `pack-<id>` StyleProfile, records manifest sha256 +
  per-reference outcomes in provenance (regeneration = same command,
  drift detectable); dead refs excluded with NAMED warnings, all-dead =
  loud error ("a preset built from nothing would be a lie"). 8 new
  tests; suite 546+1skip. **Next: actual pack builds** (5 packs × ~6
  studies each ≈ network + whisper time) — will run as a background
  batch and report per-pack outcomes; genre-rubric note: viral-tiktok-
  reels + informative-explainer map to talking-head until dedicated
  rubrics exist (manifest field, trivially updatable).

- **2026-07-19 (Lane A): S4 Track 1 claimed + DELIVERED (my half) —
  draft-EDL production.** `myzing/assemble/draft.py`:
  `draft_edl(breakdown, direction, media)` maps the direction's chosen
  keeper spans onto a contiguous EDL timeline in the AI's order (EDL S1
  semantics honored: no gaps, no overlaps); every span validated against
  measured media duration (exceeding = loud AssembleError, "refusing to
  trim footage that does not exist"); chosen spans cross-checked against
  measured raw-mode keepers with named divergence warnings (AI's call —
  flagged, not blocked; 0.35s edge tolerance); `draft_for_slug` writes
  draft-edl.json into the breakdown folder. **End-to-end proof on the
  raw-practice clip:** direction citing my two measured keepers →
  draft EDL (zero warnings, spans matched measurement) → Lane C's real
  renderer → 25.9s mp4, exactly the sum of the trims — the S4 Track 1
  internal gate's shape, my half, working against real footage and the
  real renderer. 10 new tests; suite 523. **Track 2 (preset-pack
  builder) claimed next — starts when Lane D's reference sets land**
  (batch-study + preset profiles is buildable the moment a pack list
  with live URLs exists).

- **2026-07-19 (Lane A): Lane C's P1 against my raw.py FIXED (they were
  right) + SG-1 review of #114/#118/#122.**
  - **P1 acknowledged and closed:** keepers were derived even when VAD
    never ran, handing the AI the false evidence "no interior dead air"
    — precisely the conflation I flag in others' code; fair catch.
    Fix: keeper derivation now SKIPS with an explicit warning when
    speech segments are unavailable (its definition requires the
    dead-air check); Lane C's exact repro is the regression test. Also
    adopted their process observation wholesale: degraded states now
    surface at the consumer artifact — a keeper built without a
    loudness curve carries "CAVEAT: loudness not verified (no curve)"
    in its evidence instead of silently omitting the claim.
  - **#118: verified correct** — their production threading of my
    audio_probe_ok flag (provenance + named skip warning) is exactly
    the consumer-visible proof my #112 lacked. Their process
    observation ("prove the state at the first consumer-visible
    artifact, not the helper return") is right and now applied above.
  - **#114 (direction format validator): pass, well-built** — typed
    shape checks, criterion IDs validated against INDEX.md with
    fail-loud on an empty index, sha-stamped jargon list. Its direction
    `keepers` contract ({start, end, why}) aligns with my
    provenance.raw_mode.keepers shape — S3's loop closes cleanly.
  - **#122: pass** (small, test-backed env-field sharing).

- **2026-07-19 (Lane A): A-Q13 DELIVERED — cross-review of #95/#97/#99/
  #102 (+ sanity checks #109/#111), measurement-honesty lens.**
  - **#99 (C-Q14 dissolve calibration): exemplary.** The v3 gate
    (temporal monotonicity + mean-difference floors), the
    suppressed-candidate diagnostics, and especially refusing to report
    real-video "precision" without human truth ("calibration diagnostic,
    not precision") is exactly the discipline this project claims.
    Lane C's process observation — every fallback classifier needs an
    explicit abstain path — deserves promotion to a standing rule.
  - **#97, #102, #95:** pass. Doctor staleness carries structured data
    (version/age/stale) not just prose — good; compare.md scale fix
    matches the rubric; #102 is honest error-path coverage; #95 doc-only.
  - **#109 (their SG-1 fix on MY raw.py): verified correct** — digit
    preservation in take comparison closes a real false-match class
    ("take 123" vs "take 987"); their test is sound. Thanks.
  - **#111 (C-Q15 raw goldens): consumes my raw measurements correctly;**
    exact-by-construction dead-air/filler truths line up with my
    thresholds. No findings.
  - **Fixed directly (file in my tree): the A-Q10 audio-probe finding
    was still live in the production detector** — `_audio_onsets`
    returned bare `[]` on ffmpeg failure, so a failed probe read as
    measured-no-onsets and `audio_aligned_cut` could silently never
    fire. Now returns an explicit probed-ok flag; the report carries
    `audio_probe_ok`; regression test pins failed-probe ≠ measured-empty.
    (Prototype tools/eval/transitions.py has the same pattern — left for
    Lane C per ownership, same fix applies.)

- **2026-07-19 (Lane A): S3 LANE GATE PASSED — keepers delivered.**
  Keeper = maximal clean stretch inside a take: split at filler words
  and interior dead air, ≥4 words, ≥2s, loudness within 12 dB of speech
  level throughout; each keeper carries a citable evidence list and a
  repeated-take cross-reference ("compare before choosing") when its
  span has a near-duplicate. Surfaced in warnings (summary) +
  provenance.raw_mode.keepers (structured, per the sprint's
  no-schema-change constraint). **Design lesson from the gate video,
  encoded in a test:** the speaker never pauses >0.8s, so the whole 48s
  was one take and a single "literally" rejected everything — the fix
  (split-at-flaws) yields exactly the human answer: three keepers
  0.0-3.5s / 3.8-20.8s / 21.1-48.4s around the two fillers, dead-air
  outro excluded. Manual spot-check against the transcript confirms all
  three are genuinely usable stretches. Suite 480.

- **2026-07-19 (Lane A): claimed A-Q12 + A-Q13. A-Q12 DELIVERED** —
  raw-footage measurement mode: `study(raw_mode=True)` / `zing study
  --raw` measures dead-air spans (VAD gaps ≥1.5s incl. leading/trailing
  silence), filler words (fixed lexicon + bigrams: um/uh/erm/hmm/like/
  literally, "you know"/"i mean"/"sort of"/"kind of", counts + locations),
  and repeated takes (pause-split transcript chunks ≥4 words, pairwise
  similarity ≥0.75 with time ranges). Surfaced per the item's
  instruction: compact warning lines + provenance counts; structured
  results on the internal RawResult for S3 callers. **Real-video check
  on the raw-practice video: found the 6.6s trailing dead-air span
  (48.5–55.1s) that wizard-of-oz §2 independently flagged ("6.7s
  speech-free outro"), and literally×2 matching EXAMPLE-DATASET's
  documented filler.** Honest limits in the module docstring (ASR-dropped
  disfluencies invisible; re-phrasings below 0.75 don't match).
  **SCHEMA PROPOSAL (per item, orchestrator's call):** to get these into
  breakdown.json for S3's gap reports, add
  `Breakdown.raw_observations: dict[str, Any] | None = None` (or typed:
  `DeadAirSpan{start,end}`, `FillerWord{text,start}`,
  `RepeatedTake{first_start,first_end,second_start,second_end,
  similarity}` under a `RawObservations` dataclass) — opt-in-populated
  only in raw_mode, None otherwise so published-video breakdowns are
  unchanged. Until then the warnings carry the summary. A-Q13 (SG-1
  review of #95–#102) next cycle.

- **2026-07-18 (Lane A): both S2 gate-pack findings for Lane A FIXED**
  (thanks Lane B — both were real).
  1. Impossible percentiles: switched `_stat` to inclusive quartiles —
     percentiles now interpolate WITHIN the observed range (reproduced
     your −1.085s case exactly: exclusive quantiles on {0, 11.065} give
     p25 = −2.77; inclusive give 2.77). Regression test pins
     0 ≤ p25 ≤ p75 ≤ max on an n=2 first-word pair.
  2. Coherence warning: implemented on RAW duration spread (max > 3×min),
     not the IQR — with inclusive quartiles an 18s/635s pair compresses
     to an IQR that never trips a band×median rule; the raw spread is
     the honest signal. Warning text names the span and says "sources
     may not share a format". Fires on {18, 635}, quiet on {30, 45}
     (both tested).
  - Cross-lane note for Lane C: your profile scorer correctly CAUGHT the
    quartile-method change (nice) — `real-frozen/expected-profile.json`
    re-frozen from the fixed builder via your own adapter, medians
    untouched, only p25/p75 moved (the old expectation had duration
    p75 = 347.4s — the extrapolation artifact itself). Synthetic case
    needed no change (method-invariant by construction).

- **2026-07-18 (Lane A): S2 LANE GATE PASSED — profile builder complete.**
  `myzing/profile`: `build_profile(name, slugs, workspace=None)` per the
  S2 spec — robust stats via exclusive quartiles (StatSummary.n honest per
  field), cuts curve over 10 relative-runtime buckets (30s and 60s
  sources align, tested), per-field exclusions NAMED in warnings (no cut,
  no words, skipped speech ratio, inconclusive music, transitions
  not-run), judged sections copied verbatim keyed section→slug with
  prompt versions stamped, unjudged sources listed. CLI `zing profile
  build|show` (+ one dispatch line in cli.py per the registry pattern).
  **Gate evidence:** profile built from the 3 real S1-gate breakdowns
  (Cleo/raw/MKBHD) matches hand-computed stats — duration median 55.101s
  {42.6,55.1,60.8}, first-cut median 2.367s {0.29,2.37,6.01}, shot-length
  median 1.932s; Cleo's inconclusive-music measurement carried into the
  rate honestly; all three listed UNJUDGED (no judgments stored in that
  workspace — the honest-on-mixed-sets behavior, unit-tested both ways).
  9 new tests; suite 430. Awaiting judged sources / Lane B's
  profile-grounded judgment for the sprint gate proper.

- **2026-07-18 (Lane A): claimed A-Q11 (gate satisfied — contract +
  MCP landed), DELIVERED.** breakdown.md now renders transitions in all
  three honest states: observations as plain-language lines ("1.40s:
  hard cut — audio-aligned, onset +0.030s"; "3.20-3.80s (over 0.60s):
  dissolve"), ran-but-none stated explicitly, not-run stated as
  "detection not run (opt-in)" in the Pacing summary without padding an
  empty section. Micro-contract for Lane C's pipeline integration: the
  renderer treats any `transition*` provenance key as "detector ran" —
  matches the schema docstring's promise that provenance records
  detector/version/thresholds; keep that naming and the states light up
  correctly with zero coordination.

- **2026-07-18 (Lane A): A-Q10 DELIVERED — cross-review of Lane C's day,
  measurement-scientist lens. PRs covered: #65 (transitions), #66
  (thumbs), #51 (caption presets, skimmed), C-Q6 speech fixture.**
  Overall: honesty discipline is genuinely good — limitations blocks ship
  IN the artifacts (transition report, thumbs manifest), refusal paths
  raise instead of padding, the speech fixture carries provenance + a
  README. Findings (file:line), judgment calls for Lane C:
  1. `tools/eval/transitions.py:282` — `_audio_onsets` returns `[]` when
     ffmpeg audio decode FAILS: a failed probe is indistinguishable from
     measured-no-onsets, so `audio_aligned_cut` silently can't fire and
     the report shows an empty onset list as if measured. The
     skipped-vs-empty conflation the Breakdown contract bans — suggest
     raising TransitionProbeError or an `audio_probe: failed` field.
  2. `tools/eval/transitions.py:408` — a signature with zero predictions
     reports `precision: 0.0`; reads as "always wrong" when it means
     "never fired", and `macro_precision` averages those zeros down.
     Suggest `null` + excluding no-prediction signatures from the macro.
  3. `tools/eval/transitions.py:77,232` — pair times are frame-index/fps
     math off `r_frame_rate` (declared, not average). Fine on synthetic
     goldens; when C-Q12 integrates into the study pipeline it MUST
     consume ingest's CFR-normalized media (guaranteed post-F-06) — worth
     a code comment now so the integration can't grab raw source media.
  4. `src/myzing/thumbs.py:636,750` — `-ss` placed AFTER `-i` = output
     seeking: decodes from t=0 for every frame, so 5 candidates on a
     10-min video ≈ 5 full decodes. Input seeking (`-ss` before `-i`) is
     frame-exact on modern ffmpeg and O(1); my keyframes.py uses it.
  5. `src/myzing/thumbs.py:428` — hook-promise window hardcoded to 30s;
     for a 45s Short the "promise" quote may come from t≈30 (most of the
     video). Suggest `formats.hook_window_s(duration)` (3s short-form).
  **Fixed directly (my file): F-15 is now closed end-to-end** — found
  storage's new ContextVar `use_workspace()` while reviewing #66;
  `study(workspace=...)` now uses it (thread-safe, no process-global
  state) with the env mutation kept only as a fallback for older storage;
  test proves env is untouched even mid-study. My earlier root-param ask
  is withdrawn — the ContextVar design is better.

- **2026-07-18 (Lane A): A-Q9 DELIVERED (measured honestly)** — long-form
  (>180s) transcription now routes through faster-whisper's
  BatchedInferencePipeline (batch_size 8, VAD-segmented); short-form
  keeps sequential (its word timing feeds caption-sync judgment and the
  batched remapping has a bug history per R1-A); batched failure falls
  back to sequential with a warning; pipeline recorded in provenance.
  Measured on 564s of real speech (MKBHD long-form audio), CPU int8:
  small model 62.9s→44.8s (**1.40x**), tiny 1.10x; word counts within
  0.3%, batched timestamps monotonic and in-range. **Caveat: this dev
  env has no ctranslate2-visible CUDA** — the literature's 3-4x batching
  wins are GPU-side, and ROADMAP's budget assumes GPU whisper on Ryan's
  PC. Ask: someone with the GPU box run
  `python -c "import ctranslate2; print(ctranslate2.get_cuda_device_count())"`
  and if >0, re-run the comparison (script in PR body) so the perf
  harness gets real GPU numbers; if Ryan's PC also shows 0, that is a
  setup item (cuBLAS/cuDNN DLLs) worth a doctor check.

- **2026-07-18 (Lane A): claimed A-Q8 + A-Q9. A-Q8 DELIVERED** —
  region-tracked caption clustering v2: concurrent text regions (burned
  captions vs watermarks vs scene text) now cluster independently by
  vertical position; persistent static overlays are excluded from
  `captions` and reported as warnings (threshold max(15s, 25% of
  runtime)); OCR box-order flicker no longer shatters events (token-set
  equality). Real-video deltas: Cleo hook captions now word-synced and
  clean ("IN ANTARCTICA," / "YOU'RE NEVER ALLOWED TO" / "PEE ON THE
  ICE!" — previously "ANTARCT IN ANTARCTICA," with watermark fragments
  concatenated); jacket scene-text is one separate coherent event; the
  raw video's "Raw Video Preview:" label (0-16.8s) is excluded with an
  honest note. Goldens: all dimensions still PASS ×3 (no regression).
  Directly addresses wizard-of-oz §4 "one OCR stream, many text layers".
  NOTE for Lane C: fresh real-video runs will diff against the frozen
  caption baselines — expected and intended; re-freeze when convenient.
  **A-Q9 next** (long-form transcription perf vs the harness).

- **2026-07-18 (Lane A): claimed V-A, DELIVERED** —
  `docs/taste/VIRALITY-youtube.md` (YouTube + Shorts, house format,
  16 tiered claims, all sourced from two research sweeps; primary
  anchors: Goodrow blog + RecSys 2016/2019 papers, Sherman's Shorts
  interview, the 2025-03-31 view-count divergence). Headline for the
  synthesis: on both surfaces the official viral signature is NOT a high
  metric but a metric HOLDING while distribution scales (CTR under
  impression growth; engaged-view share under public-view inflation) —
  and the top-weighted official signal (satisfaction surveys) is
  invisible to creators and to Zing, which caps honest virality-score
  confidence (Deeper Thread 3).

- **2026-07-18 (Lane A): claimed A-Q6 + A-Q7; A-Q6 DELIVERED (PR #54),
  A-Q7 Lane-A half DELIVERED.** A-Q6: keyframes now ship with both frozen
  baselines (63 sha-tracked thumbnails ≤360px, extracted from
  SHA-verified media at the FROZEN shot boundaries — measurements
  untouched), consistency test updated to the new policy, and the truth-doc
  linkage break from D-Q4's section rename repaired (manifest
  truth_section + provenance re-recorded with notes). **A-Q7 (F-15), for
  Lane B:** `study()`/`ingest()` now thread `workspace` explicitly and
  skip the env-var override entirely once storage's path functions accept
  an explicit root — detected via signature sniffing on
  `storage.breakdown_dir`, same pattern as your phase_callback sniff. Ask:
  add `root: Path | None = None` (None = today's ZING_HOME behavior) to
  `breakdown_dir`, `media_target`, `find_media`, and `save_breakdown`;
  the moment that merges, concurrent MCP jobs get race-free workspaces
  with zero further Lane A changes. Until then the env override remains
  the documented single-threaded fallback.

- **2026-07-18 (Lane A): A-Q4 + A-Q5 DELIVERED; A-Q3 verified; queue
  empty.** A-Q5 (phase_callback on `study()`, matches the kwarg your MCP
  runner sniffs; PR #38) and A-Q4 (formats.py: hook window 0-3s/0-30s by
  duration split at 180s per TASTE-FRAMEWORK H5; OCR body sampling 4→2fps
  on long-form; x.com/twitter.com → platform "x"; PR #40) are merged.
  A-Q3 spot-check done on the gate artifacts: Cleo hook keyframes are
  judgment-usable (0s mid-gesture talking-head with caption visible, 2s
  sharp location reveal); refinement idea for S2 — grab the sharpest
  frame within ±0.2s instead of the exact boundary frame to cut motion
  blur on gesture-heavy openers. Lane A queue is now empty — standing by
  for the review round / next assignment; A-Q2 continues as Lane C's
  golden set grows.

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
- **2026-07-18 (orchestrator):** Lane B's real-engine run verified your seam end-to-end. Small official item (A-Q5): add the optional phase_callback= kwarg to study() so zing_status reports real phases (ingest/shots/transcribe/ocr/audio/markdown) — Lane B's runner already sniffs for it, zero coordination needed. Also note A-Q4 (X native + YouTube long-form, format-aware hook window) was misfiled under PROPOSED — it's in your lane section now.
- **2026-07-18 (orchestrator):** gate pass + A-Q4/A-Q5 confirmed. When A-Q2 eval iteration reaches diminishing returns, your S1 review-round duty: review Lanes B+C merged code → handoff/reviews/S1-REVIEW-lane-a.md.
- **2026-07-18 (orchestrator): S1 FIX SPRINT OPEN.** Your items are in handoff/reviews/S1-FIXLIST.md (Lane A: F-06/07/08 + P3 share; Lane B: F-02 SECURITY first, then F-03/04/05/10/11/15; Lane C: F-01 CI first, then F-09/12/13/14). One fix per PR, regression test that fails before the fix, P1s before P2s. Nothing new until P1/P2 clear.
- **2026-07-18 (orchestrator, STANDING RULE — process retro):** whenever you finish a queue item, append a short PROCESS OBSERVATION to this file: what about this multi-agent process (specs, queues, NOTES, reviews, CI, orchestration) helped, hurt, or should change — one concrete recommendation each time. The orchestrator folds accepted ones into the process. Critical observations wanted, not praise.
- **2026-07-18 (orchestrator): SPRINT 2 IS OPEN** — handoff/SPRINT-2-D2.md. StyleProfile + StatSummary contracts are live in schemas.py. S2 lane items take priority over standing generators; S2-prep items already done fold in (transitions, get_frames, prompt pack 0.4.0 are the foundation). Same discipline as S1.
- **2026-07-18 (orchestrator, PROTOCOL CHANGE — CI quota exhausted):** GitHub Actions refuses to start jobs (private-repo minutes gone; macOS 10x multiplier + today's volume). Until further notice: do NOT wait on checks (they will never run). REPLACEMENT GATE: run the FULL local suite with ffmpeg gates (ZING_REQUIRE_FFMPEG=1 python -m pytest) and paste the pass-count line into the PR body, then merge. Doc-only changes may merge with a stated 'doc-only' line instead. The discipline is the gate now — betray it and we are blind.
- **2026-07-19 (orchestrator): CI RESTORED (GitHub Pro) — local-gate mode retired.** Resume the normal flow: gh pr checks <n> --watch, merge only on all-green. Keep pasting the local suite line in PR bodies anyway — it proved its worth and costs nothing.
- **2026-07-19 (orchestrator): IDLE IS ABOLISHED.** Your loop's 'say idle' clause is superseded: when no lane items are unclaimed, a STANDING GENERATOR (QUEUE.md bottom section) IS your item — claim and run one per cycle, rotating. Never answer idle while generators exist. A-Q12 (S3 groundwork) + A-Q13 are also now queued for you.
- **2026-07-19 (orchestrator): repo now PUBLIC** — unlimited Actions minutes; TRUE AUTO-MERGE restored (gh pr merge --auto --squash --delete-branch); branch protection enforces all six checks so red merges are structurally impossible.
- **2026-07-19 (orchestrator): SPRINT 3 (DIRECT) IS OPEN — handoff/SPRINT-3-D3.md.** The anti-slop core. Naming/branding is parked by Ryan (research continues in background; build under existing names/codenames). S3 lane items take priority over generators.
- **2026-07-19 (orchestrator): LAUNCH MODE + SPRINT 4 OPEN** — Ryan's directive: build EVERYTHING fully, one major launch, he tests at launch. All Ryan-gates now internal. handoff/SPRINT-4-D4.md has your Track 1 (Assemble) + Track 2 (Taste Onboarding — preset packs like ai-tech-talking-head, viral-tiktok; zing setup flow) items. S3's open items finish first; then S4. Same discipline, no pauses.
- **2026-07-19 (orchestrator):** A-Q14 — per Ryan, Lane D's Track 2 curation is reassigned to YOU (it was blocking your claimed builder work; verification quality needs Claude-grade care). Curate with live-fetch verification per the queue item, then build the packs. You own preset packs end to end.
- **2026-07-19 (orchestrator): S4 CLOSED (Gate 1 rerun PASS with probe evidence — a creator-ready draft). SPRINT 5 HARDENING IS OPEN — handoff/SPRINT-5-D5.md. S5 items take priority; S4 leftovers D-10/O-2 queued.

- **2026-07-19 (Lane A): claimed S5 Lane A — real-video sweep + D-10.**
  D-10 fixed (midpoint-admit + clamp-to-trim in `_caption_specs`, both
  edges, regression test mirrors the gate's 93%-audible case). Sweep
  record started at `handoff/research/S5-SWEEP-LANE-A.md`: cached-cell
  inventory done (32 usable studies: yt short-vert 22, yt short-horiz 3,
  yt long-horiz 7); first LIVE cell running now — x/short/horizontal
  (SpaceX post; the `x` platform detect's first live exercise). Probe
  log: YouTube bot-wall still up; TikTok IP-blocked; Instagram
  cookie-walled. Retries at different times are part of the sweep per
  spec. CD-Q1 is Lane C/D-led — I pick the fresh end-to-end video when
  lanes' records are green.
  - Sweep live cell 1 landed: **x/short/horizontal** studied live
    (SpaceX flight-2 recap, 114s 1080p) — `x` platform detect correct
    on first live exercise; meta/shots/audio-honesty all sane. Filed
    **SW-1**: caption OCR emits HIGH-confidence junk on cinematic
    footage (texture misreads + mangled location tags, conf 0.75–1.0
    — threshold can't filter); needs an orchestrator call on
    lexicality heuristics vs flag-not-drop before I touch captions.py.
    Full record: handoff/research/S5-SWEEP-LANE-A.md.
  - **SW-2 (reference rot, observed live):** FHmXO-ViKdA — the S1
    gate video — is now "Video unavailable" on YouTube, weeks after
    we studied it. In NO pack manifest (grep-verified), so no shipped
    impact; cached study remains valid as measurement of stored
    bytes. Validates verified_at dating + Lane C's freeze-bytes
    policy. Packs should expect rot: suggest a `zing profile pack
    --reverify` pass that re-probes refs and marks dead ones (design
    call, queue-able).
  - **SW-3 (operational, FIXED on this box, product gap open):**
    yt-dlp ≥2026.07 deprecated YouTube extraction without a JS
    runtime — media downloads 403 on signature-challenge videos while
    others still pass (so it looks intermittent). This box now has
    %APPDATA%/yt-dlp/config -> `--js-runtimes node` (node v24 was
    present; affects all lanes on this machine — heads-up). Product
    gap: `zing doctor` should check for a JS runtime next to yt-dlp,
    and setup docs should name it. Routing to Lane B via orchestrator.

- **2026-07-19 (Lane A): claimed P-C2 (Lane A half) — OCR calibration
  pack freeze.** Building the frozen evidence set from the three sweep
  cells P-C2 cites (SpaceX texture-junk, Cyrillic fabrication, HUD
  flood) + known-good creator-caption cells from packs-ws: per-frame
  raw OCR (boxes, text, conf), frame hashes, sampling protocol, then
  manual labels per the four proposed classes. Warning-only, offline,
  no production filter — per the proposal's own guardrails. Data
  lands under handoff/research/ocr-calibration/. Lane C: eval-side
  comparison harness stays yours; ping in NOTES when the freeze is up.
  - **Vlog pack retry COMPLETE — A-Q14 fully closed: 32/32 refs, 7/7
    packs.** vlog rebuilt at 7/7 refs (first cut 2.369s median, IQR
    2.017–6.904s); vlog-vertical built at 4/4. Honesty note: unlike
    ai-tech-vertical, vlog-vertical KEEPS the duration-coherence
    warning (34–434s span among vertical vlogs) — orientation was the
    fixable half; duration variety is the genre, and the warning
    stands truthfully.
  - **SW-4 (found by the sweep's 62-min cell, fixed same cycle):**
    batched whisper seams emit rare sub-second word-order inversions
    (2 in 10,088 words). _collect_words now normalizes to monotonic
    order (whisper's own timestamps, sorted — no fabrication) with a
    seam-overlap regression test. Matrix is now 7 live cells; only
    instagram (policy wall, Ryan's cookies call) and the two thin
    tiktok cells remain non-live.

- **2026-07-19 (Lane A): P-C2 Lane A half COMPLETE — dataset handed to
  Lane C.** Freeze tooling (deterministic regeneration) + 5 frozen
  cells (2,020 frames) + 15,231 frame-grounded labels across all four
  proposed classes. Headline ground truth: 368 likely_caption lines,
  ALL in the two known-good cells; ZERO captions in the three failure
  cells whose 13,538 lines the confidence-only baseline accepted.
  Also two self-corrections recorded in-file (the HUD cell's
  "story overlay" myth; a draft rule miscasting price numerals).
  Lane C: the comparison harness and per-class precision/recall are
  yours; the promotion bar is P-C2's own held-out clause. S5 sweep
  status: 7 live cells; remaining threads are external (instagram
  cookies = Ryan, CD-Q1 = Lane D's sourcing, final gate video = all
  lanes green).
