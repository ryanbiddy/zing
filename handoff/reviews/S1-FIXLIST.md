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
- [ ] **F-03 · Lane B (agent dispatched) · crash states never become
  honest.** status.json stays `running` after the server dies →
  `get_breakdown` says "still studying" forever, `zing_status` lists
  phantom jobs. Stamp pid + heartbeat; readers reclassify dead-runner
  states as failed with an actionable message.
- [ ] **F-04 · Lane B (agent dispatched) · stale breakdown served as ready
  during re-study.** Check status FIRST; expose `state` on every
  get_breakdown response.
- [ ] **F-05 · Lane B (agent dispatched) · doctor's OCR verdict checks the
  wrong packages.** Align doctor with the pipeline's actual import
  (`rapidocr`); fix the test that enshrines the lie.

## P2 — correctness / honesty

- [ ] **F-06 · Lane A (agent dispatched) · VFR gate hole.** Locally-VFR
  H.264 passes the 2% avg-fps check; timestamps drift past ±0.15s with no
  warning. Per-frame PTS delta detection; warn on skipped normalization.
- [ ] **F-07 · Lane A (agent dispatched) · stale keyframe cache.**
  Re-study attaches old-timestamp frames to new boundaries. Invalidate on
  re-study.
- [ ] **F-08 · Lane A (agent dispatched) · OCR fails closed silently.**
  No-scores condition → recorded warning, not silent drop.
- [ ] **F-09 · Lane C (agent dispatched) · cut scorer fabricates pairs.**
  Report missing/extra/out-of-tolerance strictly separately (C#3).
- [ ] **F-10 · Lane B (agent dispatched) · doctor omits scenedetect.**
  Recommended tier + pip fix.
- [ ] **F-11 · Lane B (agent dispatched) · study_video path mismatch.**
  Dispatch the validated path, not the raw one.
- [ ] **F-12 · Lane C (agent dispatched) · eval matcher recursion.**
  Iterative rewrite, tested at 5000+ events; scorer version bumped.

## P3 — quality (fix after P1/P2 or bundle where trivial)

- [ ] **F-13 · Lane C ·** 9:16-hardcoded caption geometry mis-places
  captions on landscape EDLs (matters once long-form output exists).
- [ ] **F-14 · Lane C ·** word-timed captions strobe during inter-word
  gaps.
- [ ] **F-15 · Lane B (+A) ·** env-var workspace override is thread-unsafe
  under the MCP job pattern — pass workspace explicitly through study().
- [ ] **F-16 · Lane D/orchestrator ·** truth-data error: the "raw,
  no-edit" example video measured 34 shots (15 cuts in 20–30s) — either
  D-Q2's truth is wrong or the clip genuinely has cuts. Re-verify by eye;
  replace the clip if it's actually edited; correct
  EXAMPLE-DATASET(-TRUTH).md.
- [ ] **F-17 · all ·** remaining P3s as listed in the three review files
  (review each file's tail section during the fix sprint).

## Passed with credit

The pinned measurement definitions, EDL S1 semantics, judgment-preserving
storage, honest-warnings discipline, and the MCP errors-as-data envelope
were checked by reviewers and held. The system's core promises survived
adversarial review; the failures above are fixable seams, not thesis
problems.
