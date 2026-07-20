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

## The candidate that SURVIVES the falsifier: temporal persistence

Position failed because it encodes a style. The next signal P-C2
named — persistence — is position-agnostic: count how many sampled
frames contain the same text. Watermarks and HUD counters sit still;
captions move with speech.

Measured per class (median frames a text persists):

| cell | captions | non-captions |
|---|---|---|
| youtube-fuxm3vz-keo (y≈0.38 captions) | 4 | 9 |
| youtube-nlgyv0bmddi | 6 | 9 |
| youtube-oyaneh0joqi | 4 | 10 |
| youtube-uc6b5owmca (HUD flood) | — | **513** |

As a rule (`persists ≤20 frames AND ≥2 words`):

| | precision | recall | F1 |
|---|---|---|---|
| aggregate | 0.484 | **1.000** | 0.652 |
| youtube-fuxm3vz-keo | 0.401 | **1.000** | 0.572 |
| youtube-nlgyv0bmddi | 0.843 | **1.000** | 0.915 |
| youtube-oyaneh0joqi | 0.502 | **1.000** | 0.669 |

Tightening to ≤8 frames raises aggregate F1 to 0.731 but drops recall
to 0.932 — it starts eating captions that are held on screen.

**Why this beats the position rule despite a lower headline F1:**
position scored 0.735 aggregate while scoring **0.000 recall** on one
caption style. Persistence scores 0.652 with **recall 1.000 on every
captioned cell measured**. A signal that fails gracefully everywhere
is worth more than one that fails totally somewhere — especially for
a warning, where a false positive costs attention and a false
negative costs the whole point.

**The caveat that keeps this honest:** my labels were assigned partly
by transcript-window matching, and persistence keys on the same
underlying phenomenon (caption text tracks speech, watermarks do
not). Persistence does not read the transcript, so it is not
circular in implementation — but it is not a fully independent
validation either. Confirming it needs labels produced without any
speech-timing input.

## Frame audit of the labels themselves (2026-07-20)

The persistence result carried a caveat: labels assigned partly by
transcript matching might be circular. I audited them the only way
that is independent — by looking at frames, with no reference to the
transcript.

`youtube-nlgyv0bmddi`, three frames inspected. One is decisive: at
t≈1s the video shows TWO texts at once — a green graphic label
**"ANTARCTICA"** at y≈0.52 and the white speech caption **"YOU'RE
NEVER ALLOWED TO"** at y≈0.79. If a narrator says "Antarctica" while
that graphic is on screen, naive transcript matching would label the
GRAPHIC as a caption.

**It did not.** All 33 graphic lines (y 0.5–0.6) are
`incidental_text`; only the 11 lines in the y≈0.79 band are
`likely_caption`. So the labels are correct here, verified by eye.

**Why it worked, and the blind spot that follows.** The labeling rule
required ≥2 tokens to call something a caption. "ANTARCTICA" is one
token, so it never matched. That safeguard is sound — but it is also
a systematic exclusion:

| | count |
|---|---|
| single-token lines labeled caption | **0** |
| single-token lines labeled non-caption | 14,022 |
| multi-token captions | 473 |

**Not one single-word caption exists in this dataset — by
construction, not by observation.** Word-by-word karaoke captioning
is a real and common style; under this labeling method its captions
would all be labeled non-caption. Any recall figure here therefore
excludes that entire style, and the ≥2-token term that appears in
BOTH candidate rules is partly fitting the labeling method rather
than the phenomenon.

Closing that needs a cell labeled without a token-count floor —
smaller than a fresh freeze, and now the highest-value next step for
this dataset.

## The token floor tested against real single-word captions (2026-07-20)

The label audit above predicted that the `≥2 words` term in both
candidate rules was partly fitting my labeling method. That was
testable, so I tested it: found a word-by-word captioned video in the
corpus (`youtube-se50vifj0aq` — frame-verified, "$100" in green as a
SINGLE-TOKEN caption), froze it, and labeled it with **no token
floor**. The dataset went from **0 single-token captions to 68**.

On that cell:

| rule | precision | recall | F1 |
|---|---|---|---|
| persistence ≤20 AND ≥2 words | 0.400 | **0.346** | 0.371 |
| persistence ≤20, no token floor | 0.374 | **1.000** | 0.545 |

**The token floor discards two thirds of this style's captions.** The
prediction held.

But dropping it globally is not the answer either:

| rule (7 cells, 15,999 lines) | precision | recall | F1 |
|---|---|---|---|
| confidence ≥0.75 (ships today) | 0.036 | 1.000 | 0.070 |
| persistence ≤20 AND ≥2 words | 0.477 | 0.882 | 0.619 |
| persistence ≤20, no token floor | **0.085** | 1.000 | 0.157 |

Without the floor, precision collapses from 0.477 to 0.085 — the
single-token world is dominated by HUD glyphs, keyboard keys, prices
and serial numbers.

**What this actually establishes:** the token floor is not a caption
property, it is a cheap proxy that trades one style away for
precision. A signal that handles both must separate single-token
CAPTIONS from single-token NOISE some other way — persistence alone
does not, because a one-word caption and a flickering HUD digit both
change fast. That is a real, named, unsolved problem, and it is more
useful than a headline F1.

Note on validity: this cell was labeled BY POSITION (frame-verified
band), so it must not be used to evaluate position rules — circular.
It is valid for the token floor and persistence, which are
position-independent.

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
