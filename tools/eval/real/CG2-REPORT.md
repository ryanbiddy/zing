# CG2 caption geometry, 22 October 2026

CG2 rejects the Korky face hallucination and improves the two calibration title
lines. **It does not improve held-out geometry overall.** It recovers one stylized
title but introduces a cropped-line localization failure. Keep caption geometry
experimental; these results do not support a general accuracy claim.

Changes are on `feat/cg2-caption-geometry-real`, based on
`a7fcd85e558d39332908a9f6308b1c5a5ca5c661`. Neither T6 transition module nor
`schemas.py`, `captions.py`, CI gate counts or `uv.lock` changed.

## Scope and evaluation boundary

The [clip split](cg2-split.json) was written before implementation. Calibration
contains Korky and all Tears of Steel clips. Held-out contains all Duck and Cover
and NASA clips. Source works stay together. Only clips with caption labels are
scored: two calibration frames with two lines, three held-out frames with nine
lines, and the separate post-hoc Korky negative at 2.400 s. Unlabeled clips are
not treated as negatives. The task and V1 report had already disclosed Duck's
failures: this is a tuning holdout, not an unseen benchmark.

All ten local clip SHA-256 hashes match the pinned manifest. Media was read from
`E:\AI\projects\zing\worktrees\v1-realeval\zing-workspace\real-eval`; no media was
modified. `zing-workspace/cg2/media-hashes.json` retains the verification receipt.
Labels remain the V1 provisional visual annotations, with approximately four
pixels of box uncertainty and no independent second annotator.

The [freeze](cg2-freeze.json) records code, labels, split and thresholds before
held-out replay. No threshold or detector change followed the held-out result.
Three implementation files subsequently had only mixed line endings normalized
to LF; both evaluated-byte and portable hashes are retained. `.gitattributes`
keeps the hashed bytes stable on checkout.

The [machine-readable results](cg2-results.json) contain per-frame matches,
rejections, fill estimates, font rankings and PNG paths. Both versions use final
ink-box IoU >= 0.5 for one-to-one line matching. This is stricter than the V1
report's raw-OCR-box matching; baseline counts remain the same. Geometry errors
condition on matched lines. False-track counts cover labeled instants only.

## Measured results

| Set / metric | Before | CG2 |
|---|---:|---:|
| Calibration line recall | 2/2 (100%) | 2/2 (100%) |
| Calibration false caption tracks at primary frames | 0 | 0 |
| Calibration median relative height error | 35.8% | 13.0% |
| Calibration median ink-box IoU | 0.718 | 0.792 |
| Separate Korky 2.400 s false tracks | 1 | 0 |
| **Held-out line recall** | **7/9 (77.8%)** | **7/9 (77.8%)** |
| Held-out false/spatially unmatched caption tracks | 0 | 1 |
| Held-out precision under the box criterion | 100% | 87.5% |
| Held-out median relative height error | 22.5% | 22.5% |
| Held-out median ink-box IoU | 0.755 | 0.745 |
| Real fill-color error | Unavailable: no numeric labels | Unavailable: no numeric labels |

The held-out unmatched track contains real text whose refined box loses part of
the line; it is not a new no-text hallucination. Among the six held-out lines
matched by both versions, height error and IoU are unchanged (medians 22.8% and
0.750). The recovered and newly missed lines change the seven-line aggregate.

At `tos-dialogue` 0.500 s, fill estimates change from RGB 105/104/96 and
112/113/103 to 232/233/228 and 247/252/250. Their heuristic confidences are 0.651
and 0.720. These estimates fit the visible white lettering better, but there is
no color-ground-truth error claim.

The expanded synthetic acceptance rerun uses all 13 verified fonts and the
unchanged oracle thresholds. Both versions pass **23/23 tests**; ranking is
**77/78 top-three hits** for both. Per-style acceptance remains at least 90%.

| Synthetic measurement | Before | CG2 | Limit |
|---|---:|---:|---:|
| Worst of three static height errors | 3.03% | 3.03% | <=10% |
| Lowest static median IoU | 0.962 | 0.962 | >=0.8 |
| Largest static median center error per axis | 0.139% | 0.139% | <=2% |
| Largest fitted path error | 0.120% | 0.208% | <=2% |
| Median fill / outline Delta E 76 | 1.105 / 0.0001 | 1.105 / 0.0001 | <=10 |
| Median outline width for a 3 px stroke | 3.597 px | 3.597 px | +/-1.5 px |

These are synthetic measurements, not real-video guarantees. Baseline modules
were saved before edits in `zing-workspace/cg2/baseline-code`; the baseline
replay script, expanded logs, JUnit properties and individual font results are
under `zing-workspace/cg2/`.

## Remaining failures and font evidence

- `duck-titles`, **11.000 s**: temporal and pixel evidence admits `DucK` at
  confidence 0.7284. `and` still has no OCR proposal. Duck/Cover boxes remain
  loose, with height errors of 19.0% and 22.5%.
  [PNG](../../../zing-workspace/cg2/held-out/duck-titles-11-after.png).
- `duck-titles`, **13.500 s**: the `PRODUCED IN CO-OPERATION WITH THE` ink crop
  loses its right portion and fails IoU 0.5. Other credit lines still contain
  background pixels and OCR transcription errors.
  [PNG](../../../zing-workspace/cg2/held-out/duck-titles-13.5-after.png).
- `tos-dialogue`, **0.500 s**: the larger line's height remains 26.1% below the
  approximate label. The four-pixel labeling uncertainty matters at this size.
  [PNG](../../../zing-workspace/cg2/calibration-final/tos-dialogue-0.5-after.png).
- `korky`, **2.400 s**: the raw hallucinated character remains inspectable, marked
  rejected for full-frame extent, string/size mismatch and isolated face overlap.
  It creates no caption track or font candidate.
  [PNG](../../../zing-workspace/cg2/calibration-final/korky-2.4-after.png).

Font comparisons use the exact labeled frames and the same 13-family library:

| Frame / text | Leading substitute before | Leading substitute after |
|---|---|---|
| ToS 0.500 s, small line | Poppins, 0.394 | IBM Plex Sans 600, 0.593 |
| ToS 0.500 s, larger line | Bangers, 0.493 | Open Sans 700, 0.705 |
| Duck 11.000 s, Cover | Inter 900, 0.289 | Poppins, 0.291 |
| Duck 11.000 s, Duck | Unaccepted OCR | Anton, 0.358 |
| Duck 13.500 s, credit block | Luckiest Guy, 0.339 | Bangers, 0.200 |

All remain `best substitute`, below 0.90. Cleaner ToS crops change the ranking;
poor Duck crops degrade it. No source font identities are known. Full top-three
rankings, crop/mask hashes and per-family metrics are saved beside each PNG.

## Implementation and validation

`caption_regions.py` adds string-size bounds, stroke/edge density, temporal
corroboration, optional same-frame YuNet overlap and contextual script evidence.
Rejections stay as explained low-confidence observations and coverage gaps.
`caption_pixels.py` adds luminance-tail color seeds and glyph-component filters;
geometry includes adjacent antialias pixels while colors use solid ink/stroke
pixels. Homogeneous Latin runs can report component-based cap/x-height estimates.
`font_match.py` reuses component support. `caption_geometry.py` writes sidecar
version 2 and reads version 1. The no-flag v1 study path remains unchanged.

New tests cover rejection, texture/plate/outline segmentation, version reading,
scoring and split integrity. A registered `real_caption` test uses
`ZING_CG2_REAL_ROOT` and real OCR on the pinned Korky clip. The existing synthetic
tests retain every threshold; they now also emit numeric JUnit properties.

CI's baseline remains **204 FFmpeg tests**; this pass adds no tests to that gate.
All commands used the pass-rule environment and `uv run --frozen`. The expanded
font runs used `ZING_TEST_FETCH_FONTS=1` with all pinned assets already cached.
Full suites used `HF_HUB_OFFLINE=1`; gates used `ZING_REQUIRE_FFMPEG=1`.

| Command | FFmpeg 8.1.2 | FFmpeg 6.1.1 |
|---|---|---|
| `pytest -ra` | **2,505 passed, 7 skipped**, 620.37 s | **2,505 passed, 7 skipped**, 408.69 s |
| `pytest -q -m ffmpeg --expected-ffmpeg-tests 204` | **204 passed, 2,308 deselected**, 335.66 s | **204 passed, 2,308 deselected**, 397.81 s |

Both gates have zero skips and zero xfails. The seven full-suite skips are the
new opt-in real-caption test, Kokoro, three HyperFrames checks, the YuNet portrait
fixture and OpenTimelineIO. The new real-caption test was separately enabled:
`ZING_CG2_REAL_ROOT=<pinned real-eval root> uv run --frozen pytest -q -m real_caption`
passed **1 test**, with 2,511 deselected. The 35 focused region/pixel/evaluator/
registry checks also passed. `uv sync --all-extras` and `git diff --check` passed.

Logs and JUnit XML are `zing-workspace/cg2/{full,gate}-{8.1.2,6.1.1}.{log,xml}`.
`validation.json` records exact commands, executable paths, version output,
counts and XML hashes; the same receipts are embedded in `cg2-results.json`.
`zing-workspace/PASS-REPORT.md` is the short handoff.

After the capacity interruption, the 35 focused checks passed again. Frozen
source hashes, all four JUnit receipt hashes/counts, all ten clip hashes and every
reported PNG path were reverified. `resume-focused.log` and `.xml` retain that
test rerun. The protected-file diff and `git diff --check` remained clean.

No dependency, model or media asset was added. Existing cached assets are
RapidOCR/PaddleOCR (Apache-2.0), YuNet (MIT), OFL fonts except Luckiest Guy and
Permanent Marker (Apache-2.0), and the real corpus with the existing CC0,
CC BY 3.0 and public-domain credits in the manifest/notices. No media, models or
renders are staged for Git. Broad multilingual, rotated, occluded and archival
caption accuracy remains unestablished.
