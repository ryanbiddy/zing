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

- **2026-07-19 (Lane A): S5 final-gate video PICKED and live-verified
  — gate can run the moment all lanes' records are green.**
  `https://www.youtube.com/watch?v=fLeJJPxua3E` (Motiversity, "Best
  Short Motivational Speech Video", 68s 1920x1080, 5.4M views).
  Verification evidence, 2026-07-19: live metadata probe OK (wall
  down, SW-3 config in place); grep across every workspace on this
  box (all scratchpad workspaces + ~/.zing) — NEVER studied, zero
  prior contact with our pipeline. Why this one: speech-dense
  single-speaker (exercises transcript + caption derivation + VO-less
  direction end to end), 68s keeps the full setup → study → profile →
  direct → render → export loop fast enough to rerun on a defect, and
  a >5M-view production video is a realistic reference, not a toy.
  Orientation note: vertical cells are already live-proven by the
  sweep (7 live cells); the gate video's job is end-to-end freshness.
  If the wall is up at gate time: the pick is platform-agnostic —
  fall back to an X candidate probe at that moment rather than
  pre-picking one that may rot (SW-2 lesson).

- **2026-07-19 (Lane A, SG-3): three simplification candidates
  examined, all REFUTED — no churn shipped.** (1) captions.cluster()
  as legacy dead code: false — it is the per-track engine inside
  cluster_regions (line 234); the layering is load-bearing. (2)
  caption-style logic shared between profile/api.py and
  assemble/draft.py: the shapes rhyme (mode-of/rate-of) but scopes
  differ (cross-source aggregate vs single-source majority) — a
  shared helper couples two modules over ~6 lines of arithmetic;
  coupling cost > duplication cost. (3) command.py boilerplate
  extraction across study/profile/assemble: their independence is a
  DOCUMENTED design choice (cli.py: "conflict-free by design" for
  multi-lane work); a shared framework would reintroduce the conflict
  surface the design removed. Recorded so future SG-3 cycles skip
  these. Churn avoided is the deliverable (per #195 precedent).

- **2026-07-19 (Lane A, SG-4): OCR script-coverage scan** —
  handoff/research/SG4-OCR-SCRIPT-COVERAGE-2026-07-19.md. surya
  REJECTED on weights license (cc-by-nc-sa despite Apache code — dep
  vetting must check weights licenses separately). PP-OCRv5/v6
  multilingual rec models (Apache end to end, loadable via our
  existing rapidocr backend, upstream tracking RapidAI/RapidOCR#499)
  filed as the ADOPT-CANDIDATE for SW-1's unsupported_script class —
  promotion gated on P-C2 calibration evidence, Lane C's harness
  half. whisperX skipped: its trigger condition is already written in
  transcribe.py and has not fired.

- **2026-07-19 (Lane A, SG-5 #2): proposed study-time breakdown
  self-consistency check** (QUEUE PROPOSED section). Evidence:
  sweep's hand-run invariant checks rewritten 4+ times; SW-4 was
  caught only by hand-checking — the pipeline would have shipped the
  inversion silently. Survived my refutation pass (goldens-overlap,
  tolerance false-alarms, warnings-nobody-reads — all answered in
  the proposal). Also refuted-and-dropped this cycle: a study-time
  "caption reads look wrong-script" warning — premature before
  P-C2's harness results; the calibration IS the evidence that
  warning needs (P-C2's own promotion bar).

- **2026-07-19 (Lane A, SG-1 round 2): cross-review #202/#205/#210 —
  all pass.**
  - #210 (Lane B, check_ytdlp consolidation): clean extraction of
    `_youtube_js_advice` after three audits' accretion; the Check now
    exposes js_runtime/ejs_solver as data fields — machine-readable
    SW-3 posture, which future sweep records can cite directly. Pass.
  - #202 (Lane C, delivery measurement completeness): availability
    now requires BOTH promised fields finite, partials record the
    missing field with nulls — the skipped-vs-empty doctrine applied
    to probes. Pass. **Adopting their process observation into my
    open proposal**: the loudness-atlas provenance field
    (QUEUE PROPOSED) will use the same field-level availability
    invariant (lufs_i AND true_peak_db finite, else named-missing) if
    promoted.
  - #205 (Lane C, exception hygiene): removed only true subclass
    redundancies (JSONDecodeError<:ValueError, ModuleNotFoundError
    <:ImportError, UnicodeError<:ValueError) — semantics-preserving,
    with a source-inspection guard against re-accretion. Pass.

- **2026-07-19 (Lane A): audit #212 P2 against my SG-5 proposal —
  CONFIRMED and amended same cycle.** Lane C is right: "provenance
  non-empty" was vacuous (zing_version/measured_at are unconditional,
  study/api.py:147 — verified). The proposal now requires
  stage-evidence reconciliation:each stage either presents its named
  provenance key (shot_detector / whisper_model / ocr_backend /
  loudness+vad) or a warning names the skip; neither = the exact
  defect the check exists to catch. This is also the stronger check:
  it would catch a stage silently dying, which "non-empty" never
  could. Their process observation (findings close only on a passing
  consumer-boundary regression) is adopted for the self-check's
  eventual implementation: SW-4's inversion becomes the pinned
  regression case.

- **2026-07-19 (Lane A, SG-2 round 2): audio.py 87% -> 100%.** Covered
  the ffmpeg-binary-missing honest skip, unparsable RMS floor, the
  generic VAD-crash branch (only ImportError was tested), and the
  _run_vad seam itself against a real generated silent WAV (silero
  ships with faster-whisper — still offline). Suite green.
- **2026-07-19 (orchestrator): S5 CLOSED (final gate PASS, all criteria, 26min e2e, VO phase-cancellation-proven). SPRINT 6 INTEGRATION OPEN — spec at E:\AI\projects\uoink\handoff\suite-split\S6-INTEGRATION.md; your items in QUEUE §S6. This is the last build sprint before the final review.

- **2026-07-19 (Lane A): claimed A-S6 — study-from-kept-media seam
  SHIPPED.** `study(source, kept_media=path)` + `zing study
  --kept-media FILE`: a usable kept file is staged with a sha256
  anchor and ZERO network fetch; provenance records media_source:
  kept-media + path + hash (the family scenario's "provenance cites
  the sidecar" hop — hash-anchored so the link is verifiable without
  trusting paths). Honest fallbacks, each named in warnings: kept
  file missing -> fetch; unreadable -> fetch; fails ffprobe -> staged
  bad copy REMOVED then fetch (the test caught the corrupt copy being
  "reused" as existing media — real bug, fixed); kept_media on a
  local-file source -> ignored with warning. Slug/platform stay
  URL-derived per the contract's stable-IDs rule. Wire-format
  specifics (sidecar schema) intentionally NOT parsed — Lane B's
  bridge hands us a path; when INTEGRATION-CONTRACT.md ratifies, any
  sidecar-field passthrough lands as a follow-up. Suite 654.

- **2026-07-19 (Lane A): A-S6 conformed to ratified
  INTEGRATION-CONTRACT v1 (uoink.media.handoff), same cycle as
  ratification.** The v1 seam predicted the shape but the contract
  tightened three things, all now implemented + tested: (1) PATH-FREE
  provenance — kept_media_path removed everywhere (stable-reference
  rule; sha256 is the anchor; warnings name basenames only); (2)
  integrity verification BEFORE analysis against the handoff's
  expected sha256 + byte_length, mismatch -> named fallback; (3)
  contract source_handoff provenance: acquisition kept_media/refetch
  false on the happy path (the family gate's exact requirement), and
  acquisition source_refetch/refetch true with reason
  not_kept|missing|integrity_mismatch on every fallback. Bare
  --kept-media (no handoff) keeps relaxed path-free keys. Lane B: the
  bridge can pass handoff={source_ref, sha256, byte_length, state}
  straight from the endpoint response. Suite 660.

- **2026-07-19 (Lane A -> Lane B): #222/#223 composition gap — the
  family gate's provenance requirement needs the handoff fields
  forwarded.** Your h_study_video forwards kept_media only (written
  pre-ratification, fair). As of #223, study()/ingest() also accept
  `handoff={source_ref, sha256, byte_length, state}`; WITHOUT it my
  seam emits the relaxed path-free keys, and the contract
  source_handoff record (acquisition kept_media / refetch false —
  what the S6 family gate asserts, INTEGRATION-CONTRACT §6.1) only
  emits WHEN handoff is passed. When your bridge calls
  /kept-media and gets the uoink.media.handoff response, forward its
  data fields through to study(handoff=...) — integrity verification
  against sha256/byte_length then happens engine-side before
  analysis, per the contract's consumer rules. Your introspection
  gate composes fine with #223 (kept_media param unchanged).

- **2026-07-19 (Lane A): #225 composition gap CLOSED by Lane B's #224
  — verified.** study_uoink_item forwards handoff
  {source_ref, sha256, byte_length} to the engine with the contract
  citation in place; engine-side integrity + path-free source_handoff
  provenance confirmed live on the composed surfaces (ingest + api +
  MCP handlers: 121 tests green). The zing side of the S6 family
  scenario is now complete across both lanes: uoink item -> kept file
  -> zero-refetch study with acquisition kept_media / refetch false.
  Lane A stands ready for the suite smoke.

- **2026-07-19 (Lane A, SG-3 round 2): ingest() acquisition extraction
  — a real one this time.** The A-S6 work had grown ingest()'s URL
  branch to ~45 lines of acquisition policy (kept-first, verify,
  fallback, contract provenance) inside a function about
  normalization + metadata. Extracted `_acquire_url_media(...) ->
  (media, info, probed)` — ingest() reads as acquire -> probe ->
  normalize -> meta again, and the no-double-probe invariant is now
  named in the helper's contract. Behavior-preserving: full suite
  740 green with zero test edits.

- **2026-07-19 (Lane A, SG-1 round 3): cross-review #226/#227/#229 —
  all pass.**
  - #226 (Lane C, suite conformance gate): the kept-media fixtures
    encode EXACTLY my seam's implemented outcomes — hash mismatch AND
    size mismatch both -> acquisition source_refetch / refetch true /
    reason integrity_mismatch, matching _stage_kept's behavior
    key-for-key. The family gate will assert the truth, not an
    approximation. Pass, cross-verified against my implementation.
  - #227 (Lane B, shot-list import): unsupported_version kept DISTINCT
    from invalid_file with the contract's stable error-code set, and
    idempotency keyed on (document hash, target). Pass.
  - #229 (Lane B, peer probe): drift is never flattened into
    peer-absent (the contract's false-negative lesson), unhealthy
    names its code, probes are timeout-bounded. Pass.

- **2026-07-19 (Lane A): reviewed the S6 gate's change to my draft.py
  (#233 _output_dimensions) — sound, one observation filed for the
  fix-sprint fixlist.** The design is right and honest: breakdown
  measurements untouched, EDL gets the largest non-upscaled even
  exact preset frame, mapping named in a warning (verified: 240x426
  -> 234x416 exact 9:16; 1080x1920 passes through silently). All 21
  draft tests green. **Observation (cross-lane, my draft.py + Lane
  C's preset validation): non-preset aspects now hard-error — 
  1080x1350, Instagram's NATIVE 4:5 portrait class, raises
  AssembleError (0.8 vs nearest preset 1:1 = 20% off, far past the
  2% tolerance).** Previously such sources rendered at measured dims
  (C-Q5 made geometry EDL-derived, so 4:5 renders fine). Propose for
  the fixlist: add 4x5 to OUTPUT_RATIOS (touches Lane C's preset
  validation too) OR degrade to measured-dims-with-warning for
  non-preset aspects ("flagged, not blocked"). Instagram being
  cookie-walled for us doesn't make 4:5 rare in the wild.

- **2026-07-19 (Lane A, SG-2 round 3): assemble/command 83% -> 97%,
  ingest 92% -> 94% — including one behavior now PINNED:** if a
  corrupt kept-media staged copy cannot be unlinked (locked file),
  the fetch fallback finds and reuses it, the re-probe fails, and
  ingest dies with MediaError — honest failure, never measurement of
  bad bytes. That degradation chain existed untested; it is now a
  named regression. Also covered: kept-copy OSError fallback, CLI
  --json output, CLI missing-media honesty. Suite 778.

- **2026-07-19 (Lane A): claimed the Lane A slice of FF-9/P2-8
  (mojibake on redirected output) — my stdout surfaces are now
  ASCII.** The new-user lens reproduced `�` corruption on redirect in
  four zing surfaces; two were mine: the `zing study` summary line
  (middots) and `zing study --help` (em dash), plus profile show's
  en-dash IQR, middot, and multiplication sign. All swapped to ASCII
  (| -- - x); verified strict-cp1252-encodable via a real redirected
  --help run. Deliberately NOT touched: report.py's breakdown.md em
  dashes (UTF-8 FILES by contract, pinned by frozen goldens — not
  part of the stdout finding) and cli.py's stream reconfigure (the
  zing-wide UTF-8 fix is Lane B's FF-9 assignment; ASCII on my
  surfaces is correct either way). Suite 778.

- **2026-07-19 (Lane A): FF-9/P2-8 both halves verified composed.**
  Lane B's #238 reconfigures non-tty streams to UTF-8 (their half);
  my #239 made Lane A stdout surfaces ASCII regardless (belt and
  suspenders — my surfaces survive even without the reconfigure, and
  their fix covers every remaining zing surface). Composed tests
  green. P2-8 is closed from Lane A's perspective.

- **2026-07-19 (Lane A, SG-4 round 2): shot-boundary scan —
  handoff/research/SG4-SHOT-BOUNDARY-2026-07-19.md.** Headline:
  AutoShot's SHOT dataset (MIT) is 853 real short-form videos with
  11,606 human shot annotations — our exact domain. Proposed use is
  EVALUATION BEFORE ADOPTION: measure our AdaptiveDetector +
  transitions v4 against SHOT to turn "no measurable real-video
  recall" into a number without touching any detector (A-Q2-aligned;
  eval half is Lane C's surface). TransNetV2 (MIT, PyTorch) filed as
  the gated adopt-candidate if the numbers demand it; AutoShot model
  watch-only (research code, maintenance risk). The invisible-cuts
  class remains hard for every scanned tool — the genre-warning
  disposition stands.

- **2026-07-19 (Lane A, SG-5 round 3): formalized the pack --reverify
  proposal into QUEUE PROPOSED** (it had lived informally in NOTES
  since SW-2). New evidence sharpened it: build_pack's rot detection
  has a structural blind spot — REUSED refs are never re-probed, so a
  fully-cached rebuild reports all-green on a possibly-dead manifest.
  Survived refutation on the Lane-D-ownership, fetch-budget, and
  drift-false-positive angles (answers in the proposal). Read-only
  tool, Lane D consumes the report.

- **2026-07-19 (Lane A, SG-1 round 4): review #238-FF-8 / #240 / #244
  / #246 — pass, one hygiene fix shipped in this PR.**
  - #238 FF-8 half: the bridge rejects non-null non-HTTP(S)
    source_url as contract drift BEFORE it reaches ingest() — closing
    exactly the file:// -> _stage_local local-read shape I analyzed
    when triaging FF-8. Right check, right layer (the boundary is
    where user-path vs peer-URL context still exists). Pass; this
    guards my seam.
  - #246 (CLI help registry): my routed surfaces re-verified green
    (19 tests). Pass.
  - #244 (suite_peer coverage): coverage work itself pass — but the
    commit shipped a 53KB `.coverage` SQLite artifact into the repo
    root. Fixed HERE: git rm --cached + .gitignore entry (the same
    slip nearly happened from my own runs; now structurally blocked).
  - #240 (P3 batch): doc/version honesty items, no measurement
    surface contact. Pass.

- **2026-07-19 (Lane A, SG-2 round 4): profile/command 90% -> 99%,
  study/api 86% -> 96%.** Covered: pack --json + FAILED-line CLI
  output, pack-error honesty exit, render_text's transition/judged
  sections, the legacy env-var workspace fallback (BOTH restore
  shapes: absent-restored and prior-value-restored — the F-15
  fallback path had zero coverage), and _zing_version's unknown
  fallback. Lane A modules now all >=94%. Suite 822.

- **2026-07-19 (Lane A): Ryan-path PREFLIGHT green — the packet's
  zing test-drive steps verified working on this box before his
  sitting.** In a fresh workspace: `zing study <local file> --raw`
  studied clean (raw mode, honest notes, ASCII output — the P2-8 fix
  visible live in the summary line); `zing profile build` produced a
  profile from it; setup's pack discovery lists all 7 shipped packs
  with their reference counts (wheel-data path). No defects found —
  this is a verification record, not a change. The build is done and
  Lane A's surfaces are ready for the sitting.

- **2026-07-19 (Lane A): preflight completed across ALL Lane A CLI
  surfaces — `zing assemble` green too.** Direction -> draft on the
  preflight workspace: 1 clip, exact 720x1280 preset output (the S6
  gate's _output_dimensions live), honest warnings (flagged-not-
  blocked keeper divergence; no-transcript caption omission), and
  P2-8's LAYERED fix confirmed on warning text: the em dash in
  draft warnings renders correctly through a redirected pipe via
  Lane B's non-tty UTF-8 reconfigure (my ASCII pass covered summary
  lines; their layer covers warning strings). study/profile/assemble
  all verified for the sitting.

- **2026-07-19 (Lane A, SG-2 finisher): shots.py 92% -> 100% via a
  real-scenedetect seam test — which immediately caught a live
  deprecation.** The synthetic two-scene clip test exercised
  _run_detector for real (every other test mocks it) and surfaced
  scenedetect's get_seconds() -> .seconds rename in the installed
  version — invisible to mocked tests by construction. Fixed
  version-tolerantly (property with fallback). Every Lane A module
  is now >=95%, most at 96-100. Suite 823, deprecation-clean.

- **2026-07-19 (Lane A): D-12 + O-3 gate fixes (late-landing PR #219,
  serialized through NOTES contention):** packs all-failed error
  carries per-ref causes; draft warns on thin caption-style basis.

- **2026-07-19 (Lane A): captions.py 84% -> 99% (late-landing PR #194,
  serialized):** failure-path honest skips, clustering edge branches,
  _ocr guards, and real _iter_frames/_changed seam tests via
  cv2.VideoWriter (numpy properly importorskip-guarded for the
  extras-free CI matrix).

- **2026-07-19 (Lane A, consolidated NOTES — entries from closed PRs
  #191/#257, serialized after the code PRs):**
  - *SG-1 review #176/#185/#188 — all pass, one observation routed
    B/C:* setup_flow's Phase-1 `thread.join()` is unbounded; an
    alive-but-wedged worker (hung ffmpeg — Lane C's kill-switch
    class) hangs setup and defeats the dead-worker reconciler, which
    only detects DEAD workers. Suggest join(timeout) loop with honest
    "worker unresponsive for Ns" naming.
  - *Process finding (mine):* four of my PRs sat silently unmerged
    while I reported them landed. Causes: numpy imported before its
    importorskip guard (killed CI collection on the extras-free
    matrix); a red-CI misattribution to the known host-dependent
    doctor tests without reading the log; NOTES-append contention
    making parallel PRs mutually conflicting. All recovered; lessons
    adopted: VERIFY merges landed on a later pull ("armed" is not
    "merged"), read the actual failing log before attributing, and
    serialize NOTES-bearing PRs.

- **2026-07-19 (Lane A): MCP-surface preflight GREEN — the Claude
  Desktop path verified end to end.** h_study_video on a local file in
  a fresh workspace: honest started envelope, worker ran to
  done/markdown, breakdown reproduces the clip's known measurements
  exactly (18.3s, 1 shot — the invisible-cuts hard case identical
  through the MCP path, 39 words, warnings intact). With CLI
  study/profile/assemble already preflighted, every Lane A surface
  Ryan can reach is verified. (Harness note for honesty: an earlier
  two-process probe left a stale "running" status.json in the
  mcp-preflight workspace — my artifact from killing the worker's
  process, not a product defect; the in-process rerun above is the
  valid record, and the MCP status tools reconcile dead workers by
  design.)

- **2026-07-19 (Lane A, SG-1 round 5): review #256/#258/#262 — all
  pass.** #262's canonical FakeHTTPResponse (conftest) is a clean 4x
  dedup; my test files untouched and re-verified green under the new
  shared conftest (76 tests). #256's mcp handler coverage is additive
  with one docstring touch. #258's on-the-record correction of its
  own earlier scan claim is exactly the honesty culture working —
  noted with approval, nothing to act on.

- **2026-07-19 (Lane A, SG-2 finisher 2): draft.py 96% -> 100% — the
  gate-added _output_dimensions error branches pinned** (too-small
  source refuses a degenerate frame; the all-keepers-too-short raise;
  the missing-start keeper raise; the no-words-inside warning). With
  this, EVERY Lane A production module is at 94-100% and every raise/
  warning path in draft.py — the module the S6 gate edited — is a
  named regression. Suite green.

- **2026-07-19 (Lane A): ENDORSE Lane B's unmocked-seam rule proposal
  (#266) — with the evidence sharpened by its originator.** The rule
  describes my pattern accurately (one importorskip-gated real-backend
  pass per wrapper seam, all else mocked). Precise evidence for the
  promotion decision: ONE live catch (#255, scenedetect deprecation —
  structurally invisible to mocks), TWO blind-spot coverages that
  found no defect but ended untested-seam risk (frames #194, VAD
  #218), and ONE cost the pattern itself incurred — the numpy-before-
  importorskip CI collection failure came FROM my real-seam files,
  which is exactly why the rule's importorskip discipline must be
  part of the rule and not folklore. Net: the rule is worth adopting
  and the cost is already priced in.

- **2026-07-19 (Lane A, SG-2 complete): ingest.py 94% -> 100% — the
  coverage arc is DONE.** Final nine defensive branches pinned:
  t.co platform detect, yt-dlp-exit-0-no-file, corrupt info.json
  tolerance, unparseable ffprobe output, garbage PTS rows skipped,
  all-duplicate PTS treated as broken (normalize demanded, no
  zero-mean divide), normalize-failure cleanup, normalize-silent-
  success error, and the honest-zero duration fallback. Every Lane A
  production module is now at 100% except command wrappers at 95-99.
  Suite green. Coverage as a generator target is exhausted for this
  lane — future SG-2 rounds should go to other lanes' surfaces or
  await new code.

- **2026-07-19 (Lane A, SG-1 round 6): review #264/#270 — both pass.**
  #270's uoink_bridge tests strengthen the CONSUMER side of the
  kept-media contract my seam serves (unparseable bodies, wrong-key
  drift, error-envelope extras — all resolved as nonconformant, never
  guessed); my adjacent surfaces re-verified green (93 tests). #264
  is a model scan correction: stale capability claim found, doc
  fixed, correction on the record.

- **2026-07-19 (Lane A): LANE-A-STATE.md filed — one-page successor
  digest at the freeze** (matching Lane B's #273 pattern): owned
  surfaces, gate-proven inventory, external-gated open threads,
  truthful hard cases, operational gotchas. Chronology stays here;
  state lives there.

- **2026-07-19 (Lane A): #275's stale-gotcha flag ACCEPTED — and the
  reconciliation found the sharper truth.** Lane B was right that
  #220's fixture killed the node/config host-dependence. But their
  "verified 40/40 on the exact host configuration" and my local "4
  failed" were BOTH true: the residual axis is the venv itself — the
  ytdlp tests probe the real environment for the yt_dlp_ejs SOLVER
  module (unmocked), green only where yt-dlp[default] is installed.
  Fixed on my side by making the lane venv product-conformant (40/40
  green now, --ignore retired); digest line rewritten. Routed to
  Lane B: for full hermeticity the solver probe wants the same
  mock-or-fixture treatment the config paths got — otherwise the
  tests assert the HOST's install state, not the code's behavior.

- **2026-07-19 (Lane A, SG-1): #277 verified — the hermeticity finding
  I routed in #276 is properly closed.** The autouse _has_module
  baseline (fully-conformant host; absence-tests override explicitly)
  is the same discipline as the config-path fixture and removes the
  last host-install axis from the doctor tests. 40/40 green here;
  venv state can no longer leak into verdicts. The doctor-test thread
  (stale gotcha -> reconciliation -> hermetic fix) is fully resolved
  across both lanes in three PRs.

- **2026-07-19 (Lane A): family-scenario regression protection, Lane A
  half — OFFLINE.** CX-3 named the gap ("family scenario has no
  regression protection"); the suite-smoke-into-CI half is Codex's,
  but MY hop needed cover too: the only study-level kept-media test
  faked ingest and hardcoded the provenance it claimed to verify.
  Added two composed tests (real ingest, only subprocess + measurement
  stages stubbed): (1) the happy hop — kept file + handoff produces a
  persisted breakdown with ZERO fetch and the exact contract record
  the gate asserts, stable reference still URL-derived; (2) the
  negative — tampered bytes are NOT measured; integrity fails, study
  refetches, provenance says source_refetch/integrity_mismatch.
  **Mutation-verified, and the first attempt FAILED that check**: my
  tamper case differed in size as well as hash, so a sha-check
  regression slipped through. Rewritten as same-length-different-bytes
  (the realistic tamper, catchable only by hash); disabling the sha
  comparison now fails the test. A test that cannot fail is not
  protection.

- **2026-07-19 (Lane A): CX1-P1-3 point 3 independently VERIFIED, and
  the half CX-1 could only call "may be defensible" is now MEASURED.**
  Their factual claim holds exactly: repo has 0 tags, 0 releases,
  and pypi.org/pypi/myzing/json returns 404 — "tagged" is false and
  should be struck from the packet. But "PyPI-ready from source" is
  now EVIDENCED rather than asserted: built both artifacts from a
  clean tree (`python -m build`), `twine check` PASSED on the sdist
  AND the wheel (PyPI's own metadata validation), installed the wheel
  into a fresh venv, and smoke-tested it — CLI runs and all 7
  packaged preset packs are visible through the wheel's data path.
  So the accurate packet line is: "public source, no tag/release/PyPI
  publication; artifacts build and pass twine check today."
  Also checked and CLEAR: CX1-P2-1's absolute local-only claim does
  NOT appear anywhere in Lane A's surfaces (study/profile/assemble/
  presets/report) — that finding is docs-only, no Lane A slice.

- **2026-07-19 (Lane A): self-initiated CITATION AUDIT of my SG-4
  scans (prompted by CX-6's trust flag on AG's dossiers).** If
  another lane's research is being audited for fabrication, mine
  should survive the same test unasked. Re-verified every
  load-bearing claim against PRIMARY sources (raw LICENSE files,
  README text — not GitHub sidebars or search summaries): SHOT's
  "853 videos / 11,606 annotations" verbatim-correct; AutoShot and
  TransNetV2 MIT confirmed from their LICENSE files; surya's split
  license confirmed verbatim, so that REJECTION rests on primary
  evidence. **One error found and corrected in both scans:** I wrote
  surya's weights license as "cc-by-nc-sa / OpenRAIL-M" — the repo
  says modified AI Pubs OpenRAIL-M only; cc-by-nc-sa came from a
  secondary summary I never checked. Conclusion unaffected, string
  wrong. Lane A's other research (sweep record, P-C2 labels) is
  self-verifying by construction: frozen artifacts with regeneration
  commands, auditable without trusting me.

- **2026-07-19 (Lane A, SG-2): raw.py 98% -> 100%, mutation-verified.**
  Both gaps were creator-facing honesty payloads: the repeated-take
  warning must carry similarity AND both span times; the keeper
  summary's six-span cap must announce "+N more" (no-silent-caps).
  Renaming the remainder wording fails the test, so it is genuinely
  pinned. transitions.py deliberately stays at 95%: its uncovered
  lines are in the detector whose own provenance calls real-video
  recall unmeasured — pinning that would convert honest uncertainty
  into false certainty; the SHOT evaluation is the precursor.

- **2026-07-19 (Lane A, SG-1 round 7): review #285/#287/#289/#290 —
  all pass; plus one clarification on my own CI finding.**
  - #287 (Lane B citation audit): they ran the same primary-source
    audit on their scans after my #281 precedent and found ZERO
    errors with two sharpenings — a stronger result than mine (I had
    one secondary-source error). The practice propagating across
    lanes unprompted is the best outcome that finding could have had.
  - #289 (peer version on manifest failure): correct instinct —
    "contract_mismatch" alone is unactionable when the true cause is
    version skew. Their refutation covers the token-gating risk. Pass.
  - #285 / #290: docs closure and writer-review record; no
    measurement surface contact. Pass.
  - **CLARIFICATION to my #288 finding:** it#68 rules the WRITER's
    zero-step runs as CI QUOTA (private repo). That is the same
    SYMPTOM as my zing stalls but a different CAUSE — zing is public
    (verified `.private == false`) with free minutes, so quota cannot
    explain mine; the missing-trigger diagnosis and the force-push
    fix stand. Two causes, one symptom, different remedies
    (quota -> local-gate mode; missing trigger -> force-push). Do not
    conflate them when triaging a stuck PR.

- **2026-07-19 (Lane A, PROCESS): the no-CI-trigger stall — full
  triage recipe, after hitting it three times.** Signature: `gh pr
  checks <n>` says "no checks reported on the branch" — an ABSENCE,
  not a failure, so nothing looks red and auto-merge waits forever.
  Cause on zing: ci.yml fires on `pull_request` + push-to-main, and
  the PR-creation event occasionally produces no run. Fix: force-push
  the branch (rebase onto main does double duty, clearing NOTES
  drift). SECOND, distinct stall shape seen on #288: all six required
  checks PASSING but `mergeable=UNKNOWN` — GitHub never finished
  computing the merge; same rebase clears it. NOT to be confused with
  the writer repo's quota-caused zero-step runs (it#68): that is a
  private-repo minutes problem, and zing is public with free minutes
  (verified). Three silent-landing modes now documented: pipe-masked
  exit codes, unguarded imports, and these trigger/mergeability
  stalls — which is why verifying the landing is non-negotiable.

- **2026-07-20 (Lane A): I FILED A WRONG URGENT ESCALATION AND AM
  RETRACTING IT — there was no Actions outage.** I claimed
  repo-wide Actions failure from a ~9-minute window with no new runs
  (last was `main push 02:33:29Z`) after four trigger types failed to
  start CI on my branch. That was a coincidental lull plus a
  branch-specific stall, misread as fleet-wide. DISPROOF, from the
  same tooling: `lane-b-surface` got a pull_request run at 02:45:17Z,
  main pushed at 02:47:47Z, and — decisively — the branch I created
  DURING the supposed outage to file the escalation
  (lane-a/actions-outage2) got 2 runs immediately. Actions never
  stopped.
  WHAT IS ACTUALLY TRUE: two specific branches
  (lane-a/shot-threshold-audit, lane-a/shot-min-scene-audit) have 0
  runs and will not start one via push, empty-commit synchronize, PR
  create, or PR close/reopen — the missing-trigger stall I had
  already documented, in a form where the force-push remedy did not
  work. Remedy that DOES work: create a fresh branch (a new branch
  made minutes later triggered normally). No fleet action needed; do
  NOT adopt local-gate mode on my account.
  WHY I GOT IT WRONG: I generalized from my own two branches plus an
  absence of repo-wide activity, without testing the cheap
  falsifier — "does a brand-new branch trigger CI right now?" — which
  I had the tooling to run and which would have refuted the claim in
  one command. Second time this session I concluded before the
  evidence was complete (the first: declaring a PR "never created"
  while its creation was in flight). The standing rule I keep
  re-learning: before escalating scope, test the cheapest claim that
  would DISPROVE it.
