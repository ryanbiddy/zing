# S1 fixlist — deduped from the three cross-reviews (2026-07-18)

Sources: S1-REVIEW-lane-c.md (Sol, reviewed A+B), S1-REVIEW-lane-a.md
(fresh-eyes agent, reviewed B+C), S1-REVIEW-lane-b.md (fresh-eyes agent,
reviewed A+C). Details + repros live in those files — this list is the
work order. **Fix-sprint rule (ROADMAP): nothing new starts until P1/P2
are clear.** One fix per PR where practical; every fix lands with a
regression test that fails before the fix.

## P1 — trust breakers

- **F-01 · Lane C · CI gate is hollow.** ffmpeg is never installed in CI;
  the eval scorer and render oracle silently skip on GitHub runners —
  "CI green" currently proves mocked unit tests only (binding C-1.3 /
  C#8 / C#9 violated). Add ffmpeg install + version/filter probes +
  scorer/render jobs + failure-artifact retention (Ubuntu full, Windows
  focused). *Orchestrator's honest note: I accepted the C-Q1 gate claim
  without checking the workflow file — my gate-review miss, logged.*
- **F-02 · Lane B · MCP slug path traversal (SECURITY).**
  `h_get_breakdown` / `h_save_judgment` / `h_push_to_uoink` pass
  caller-supplied slugs straight to `breakdown_dir()`; `../../escape`
  reads/WRITES outside ZING_HOME — and tool args are AI-generated, so
  untrusted video text can influence them. One canonical slug validator in
  storage (reject separators/dots/absolute/oversize; verify resolved path
  under breakdowns_root), applied at every public slug boundary; traversal
  tests on Windows + POSIX inputs.
- **F-03 · Lane B · crash states never become honest.** status.json stays
  `running` after the server dies → `get_breakdown` says "still studying"
  forever, `zing_status` lists phantom jobs. Stamp a liveness marker (pid +
  heartbeat) and have readers reclassify dead-runner states as failed with
  an actionable message.
- **F-04 · Lane B · stale breakdown served as ready during re-study.**
  Status is consulted only when the file is missing; re-study serves
  superseded measurements with `ready=true`. Check status FIRST; expose
  `state` on every get_breakdown response.
- **F-05 · Lane B · doctor's OCR verdict checks the wrong packages.**
  Blesses `rapidocr_onnxruntime`/tesseract while the pipeline imports
  `rapidocr` only → doctor prints ok while every study skips OCR (a test
  enshrines the lie). Align doctor checks with what the pipeline actually
  imports; fix the test.

## P2 — correctness / honesty

- **F-06 · Lane A · VFR gate hole.** Locally-VFR H.264 passes the 2%
  avg-fps check; frame-index shot/OCR timestamps drift past the eval's own
  ±0.15s budget with no warning (pinned PTS rule violated). Tighten
  detection (per-frame PTS deltas) or always derive from PTS; warn when
  normalization was skipped but drift is possible.
- **F-07 · Lane A · stale keyframe cache.** `_grab` reuses existing
  shot_NNN.jpg by index — re-study after detector changes attaches
  old-timestamp frames to new boundaries; the judgment AI sees wrong
  images. Invalidate on re-study (hash boundary times into names or clear
  the dir).
- **F-08 · Lane A · OCR fails closed silently.** If rapidocr returns no
  scores (API drift), every line scores 0.0 and is dropped — "no captions"
  becomes a guess. Detect the no-scores condition and record a warning
  instead.
- **F-09 · Lane C · cut scorer fabricates pairs.** Leftover missing/extra
  cuts get positionally zipped into "out-of-tolerance matches," corrupting
  per-event reports (C#3 separate-reporting rule). Report
  missing/extra/out-of-tolerance strictly separately.
- **F-10 · Lane B · doctor omits scenedetect.** Fresh install prints
  "Ready." yet measures zero shots — the core measurement is unchecked.
  Add it to the recommended tier with its pip fix.
- **F-11 · Lane B · study_video path mismatch.** Validates the
  expanduser'd path but dispatches the raw one → ok/started followed by an
  async "no such file". Dispatch the validated path.
- **F-12 · Lane C · eval matcher recursion.** Recursive matcher blows the
  stack at real-video caption counts — iterative rewrite before S2 points
  it at real footage. (Flagged independently by both fresh-eyes reviews.)

## P3 — quality (fix after P1/P2 or bundle where trivial)

- **F-13 · Lane C ·** 9:16-hardcoded caption geometry mis-places captions
  on landscape EDLs (matters once long-form output exists).
- **F-14 · Lane C ·** word-timed captions strobe during inter-word gaps.
- **F-15 · Lane B (+A) ·** env-var workspace override is thread-unsafe
  under the MCP job pattern — pass workspace explicitly through study().
- **F-16 · Lane D/orchestrator ·** truth-data error: the "raw, no-edit"
  example video measured 34 shots (15 cuts in 20–30s) — either D-Q2's
  truth is wrong or the clip genuinely has cuts. Re-verify by eye; replace
  the clip if it's actually edited; correct EXAMPLE-DATASET(-TRUTH).md.
- **F-17 · all ·** remaining P3s as listed in the three review files
  (review each file's tail section during the fix sprint).

## Passed with credit

The pinned measurement definitions, EDL S1 semantics, judgment-preserving
storage, honest-warnings discipline, and the MCP errors-as-data envelope
were checked by reviewers and held. The system's core promises survived
adversarial review; the failures above are fixable seams, not thesis
problems.
