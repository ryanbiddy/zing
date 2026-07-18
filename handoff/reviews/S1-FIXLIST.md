# S1 fixlist — deduped from the three cross-reviews (2026-07-18)

Sources: S1-REVIEW-lane-c.md (Sol, reviewed A+B), S1-REVIEW-lane-a.md
(fresh-eyes agent, reviewed B+C), S1-REVIEW-lane-b.md (fresh-eyes agent,
reviewed A+C). Details + repros live in those files — this list is the
work order. **Fix-sprint rule (ROADMAP): nothing new starts until P1/P2
are clear.** One fix per PR where practical; every fix lands with a
regression test that fails before the fix.

## P1 — trust breakers

- [x] **F-01 · FIXED #45 (agent) · CI gate is hollow.** ffmpeg gates now
  run for real: `ffmpeg-gates-ubuntu` (scorer + goldens + render oracle,
  skips-as-failures) and `ffmpeg-smoke-windows` (paths/ASS/render smoke),
  failure artifacts retained. File-verified on main post-merge.
  *Orchestrator's honest note: I accepted the original C-Q1 gate claim
  without checking the workflow file — my gate-review miss, logged.*
- [x] **F-02 · FIXED #46 (agent) · MCP slug path traversal (SECURITY).**
  Canonical `validate_slug` in storage (separators/dots/absolute/oversize
  rejected; resolved path verified under breakdowns_root) applied at every
  public slug boundary; Windows + POSIX traversal tests. File-verified on
  main post-merge.
- [x] **F-03 · FIXED (agent) · crash states never become
  honest.** status.json stays `running` after the server dies →
  `get_breakdown` says "still studying" forever, `zing_status` lists
  phantom jobs. Stamp pid + heartbeat; readers reclassify dead-runner
  states as failed with an actionable message.
- [x] **F-04 · FIXED (agent) · stale breakdown served as ready
  during re-study.** Check status FIRST; expose `state` on every
  get_breakdown response.
- [x] **F-05 · FIXED (agent) · doctor's OCR verdict checks the
  wrong packages.** Align doctor with the pipeline's actual import
  (`rapidocr`); fix the test that enshrines the lie.

## P2 — correctness / honesty

- [x] **F-06 · FIXED (agent) · VFR gate hole.** Locally-VFR
  H.264 passes the 2% avg-fps check; timestamps drift past ±0.15s with no
  warning. Per-frame PTS delta detection; warn on skipped normalization.
- [x] **F-07 · FIXED (agent) · stale keyframe cache.**
  Re-study attaches old-timestamp frames to new boundaries. Invalidate on
  re-study.
- [x] **F-08 · FIXED (agent) · OCR fails closed silently.**
  No-scores condition → recorded warning, not silent drop.
- [x] **F-09 · FIXED (agent) · cut scorer fabricates pairs.**
  Report missing/extra/out-of-tolerance strictly separately (C#3).
- [x] **F-10 · FIXED (agent) · doctor omits scenedetect.**
  Recommended tier + pip fix.
- [x] **F-11 · FIXED (agent) · study_video path mismatch.**
  Dispatch the validated path, not the raw one.
- [x] **F-12 · FIXED (agent) · eval matcher recursion.**
  Iterative rewrite, tested at 5000+ events; scorer version bumped.

## P3 — quality (fix after P1/P2 or bundle where trivial)

- [x] **F-13 · FIXED #51 ·** caption geometry now derives from validated
  9:16, 16:9, or 1:1 output presets, with a real landscape content probe.
- [x] **F-14 · FIXED #51 ·** word-timed captions hold through inter-word
  gaps and to the caption end.
- [ ] **F-15 · Lane B (+A) ·** env-var workspace override is thread-unsafe
  under the MCP job pattern — pass workspace explicitly through study().
- [x] **F-16 · FIXED #52/#54 ·** the published upload is now labeled an
  extremely edited showcase; the corrected truth and dependent Lane C
  provenance were re-verified and re-pinned.
- [ ] **F-17 · all ·** remaining P3s as listed in the three review files
  (review each file's tail section during the fix sprint).
  - **Lane C sweep complete (C-Q8):** fixed canonical-platform derivation
    in real-video freezes, cross-filesystem render publishing, and explicit
    default-sample CLI disclosure. The overlapping-word item remains an
    upstream EDL-sanitization contract; F-15 remains assigned to Lanes A+B.

## Passed with credit

The pinned measurement definitions, EDL S1 semantics, judgment-preserving
storage, honest-warnings discipline, and the MCP errors-as-data envelope
were checked by reviewers and held. The system's core promises survived
adversarial review; the failures above are fixable seams, not thesis
problems.
