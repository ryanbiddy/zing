# P-C2 baseline: what confidence alone achieves on the labeled data

P-C2 proposed calibrating caption-evidence quality and set its own
promotion bar: a named signal must separate at least one failure class
"without reducing recall on real captions". The dataset (5 frozen
cells, 15,231 frame-grounded labels) has been complete and handed over
for several cycles while the comparison harness has not run. This is
the Lane A half of that comparison — the baseline, measured, so the
proposal can be promoted or archived on evidence instead of aging.

Regenerate: `python handoff/research/pc2_baseline.py`.

## Finding 1 — confidence is not weak here, it is ANTI-correlated

| | median OCR confidence |
|---|---|
| real captions (368 lines) | 0.988 |
| everything else (14,863) | **1.000** |

Non-caption text scores *higher* than captions. That is not noise: HUD
counters, watermarks and UI labels are crisp synthetic glyphs, while
burned-in captions carry outlines, shadows and motion blur. So the
threshold that ships today cannot be tuned into usefulness — raising
it removes captions first:

| threshold | precision | recall |
|---|---|---|
| 0.75 (ships today) | 0.024 | 1.000 |
| 0.90 | 0.026 | 1.000 |
| 0.95 | 0.027 | 0.984 |
| 0.98 | 0.021 | **0.707** |

At 0.98 nearly a third of real captions are gone and precision is
still 2%. **P-C2's core premise is confirmed with numbers: confidence
alone cannot carry this job.**

## Finding 2 — two features already in the data do far better

No new dependency, no model, no schema change — just the position and
token count already recorded per OCR line:

| rule | precision | recall | F1 |
|---|---|---|---|
| confidence ≥ 0.75 (today) | 0.024 | 1.000 | 0.047 |
| lower-third (y ≥ 0.55) | 0.253 | 1.000 | 0.404 |
| **lower-third AND ≥2 words** | **0.697** | **1.000** | **0.821** |

Held out across the two captioned cells (train on one, test on the
other): P=0.701/R=1.000 and P=0.922/R=1.000. The rule does not depend
on tuning against the cell it is scored on.

## FALSIFIED — the prediction was tested and came true (2026-07-20)

The section below warned that the position rule might be fitting two
videos that happen to share one caption style, and named the test: a
top- or centre-captioned video should score recall 0. **That cell was
sourced, frozen, labeled, and it does.**

`youtube-fuxm3vz-keo` — a phone-comparison short whose burned-in
karaoke captions sit at **y ≈ 0.38** (frame-verified at t=1:
"SAMSUNG DEBATE IS" with the active word highlighted), above centre,
with pasted product images above and price text below.

| | before | after adding the cell |
|---|---|---|
| lower-third AND ≥2 words | P=0.697 R=1.000 F1=0.821 | P=0.697 **R=0.778** F1=0.735 |
| hold-out on the new cell | — | **P=0.000 R=0.000** |

The rule catches **zero of its 105 captions**. Aggregate recall falls
because 105 real captions are now invisible to it.

**Conclusion: caption position is a style, not an invariant.** Any
promoted signal must either be position-agnostic or measure the
video's own caption band before using it — which Zing already does
(`_caption_style` derives position from the source's measured
captions). Finding 1 is unaffected and still holds on the enlarged
set (captions 0.988 vs others 1.000 median confidence).

## What this does NOT establish (the part that matters)

**Every captioned cell in this dataset uses lower-third captions.**
Caption y-centres: 0.79 (all 166 lines) in one cell, 0.65–0.78 in the
other. A video with top-positioned captions — a style Zing already
measures and `draft.py` already supports — would score **recall 0**
under this rule. The perfect recall above is a property of a
two-video sample sharing one style, not evidence of generality.

Three of the five cells contain zero captions, so they only exercise
rejection. The dataset is strong for measuring FALSE POSITIVES and
weak for measuring recall.

Consequently the honest promotion recommendation is:

1. The baseline finding (confidence anti-correlated) is **solid** and
   worth acting on regardless — it is measured over all 15,231 lines
   and every cell agrees in direction.
2. The position+tokens rule is **promising but under-evidenced**. It
   must not ship as a filter until the dataset includes at least one
   top-captioned and one centre-captioned video. Until then it belongs
   in a warning, never a drop — which is what P-C2 itself specified
   ("no production filter" in this phase).
3. What would settle it is cheap: label two more cells with different
   caption placements. That is a smaller job than the original freeze.
