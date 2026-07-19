# P-C2 calibration pack — frozen raw-OCR evidence (Lane A half)

Warning-only, offline calibration per P-C2's guardrails: no production
filter, no schema change, no text rewrite. This directory freezes the
RAW per-frame OCR evidence (pre-clustering) so candidate signals
(persistence, region stability, script, lexicality) can be compared
against the confidence-only baseline with per-class precision/recall
by Lane C's harness.

## Contents

- `freeze.py` — deterministic extractor: re-runs the exact study-time
  sampling (`_iter_frames`) and OCR (`_ocr`, same engine/threshold)
  over a stored study's media and dumps one JSONL row per sampled
  frame: `{slug, t, step, frame_sha256, lines:[{text, score,
  y_center, x_center}]}`. Rerunning it on the same media + model is
  the regeneration command.
- `frozen/<slug>.jsonl` — the frozen evidence, one file per cell.
- `labels/<slug>.jsonl` — manual labels (added in a later pass): one
  row per (t, line-index) with a class from P-C2's four:
  `likely_caption | incidental_text | unsupported_script | unreadable`.

## Frozen cells and why

| Slug | Why it's in the pack |
|---|---|
| `x-1732824684683784516` | SW-1 origin: texture junk at median 0.88 conf (SpaceX plume) + mangled real location tags |
| `x-2075286280561107161` | Cyrillic overlays fabricated into Latin at 0.77–0.93 — the unsupported_script class |
| `youtube-uc6b5owmca` | 1,882-event HUD flood: incidental_text vs story-overlay separation at scale |
| `youtube-nlgyv0bmddi` | known-good: real burned-in creator captions (word-timed style) |
| `youtube-oyaneh0joqi` | known-good: real creator captions, denser text |

## Known limitations (honest scope)

- `Line` exposes center coordinates only, not box extents; if extent
  features prove necessary, that is a captions.py debug-output change
  (Lane A) and a pack v2.
- Frames themselves stay local (media redistribution unavailable);
  `frame_sha256` anchors labels to exact frames for anyone holding
  the media.
- The OCR model version is pinned in each row's provenance header
  (first JSONL line): comparisons are only valid within one model.
- Promotion bar (from P-C2 verbatim): a held-out result showing a
  named warning separates at least one failure class without reducing
  recall on real captions; otherwise archive as negative evidence.
