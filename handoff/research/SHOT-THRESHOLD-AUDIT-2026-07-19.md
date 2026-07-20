# Auditing our min_scene_len against SHOT's real annotations

`shots.py` justifies `MIN_SCENE_LEN_S = 0.3` with an unsourced claim:
the 0.6s-equivalent default "silently merges real montage cuts (SHOT
avg shot length is 2.59s)". This note replaces that assertion with a
measurement against the primary annotation data.

## What was actually available (and what was not)

The SHOT **videos** live in a Google Drive folder — not fetchable
autonomously, so a true detector evaluation (precision/recall of our
AdaptiveDetector vs their ground truth) remains OPEN and still needs
the download. What IS public in the repo is
`kuaishou_v2.txt`: the frame-level transition annotations.

Honest accounting of that file, because it is messier than its
headline suggests:

- 738 header lines, **648 unique** video names (90 names repeat).
- **304 headers carry no frame count**; without a video length the
  final shot cannot be bounded, so those are EXCLUDED.
- **5 malformed annotation lines** (CORRECTED 2026-07-20: the note
  first said 1, having stopped at the first example. Writing the
  regeneration script surfaced the real count — exactly what a
  regeneration command is for). They are two double-comma typos
  (`568,,569`, `1375,,1376`) and three trailing-comma lines
  (`178,179,`, `232,233,`, `1952,1953,`). All five carry two
  unambiguous frame numbers, so they are parsed tolerantly rather
  than dropped; none of the reported figures change.
- Usable subset: **344 videos, 6,245 derived shots.**

So this measures a third of the corpus, not all 853 videos. The
README's "853 complete short videos and 11,606 shot annotations"
describes the full dataset behind the Drive link; the repo file is a
subset. Both are true — they are different things, and the earlier
citation audit's verification of the README figure stands.

Regeneration: `python handoff/research/shot_threshold_audit.py
[path/to/kuaishou_v2.txt]` (stdlib only; fetches the annotation file
if no path is given). Every figure below is reproduced by that script.

## Result (frames — assumption-free)

| Quantity | Value |
|---|---|
| Median shot | 48 frames |
| Mean shot | 72.1 frames |
| Shots < 9 frames (0.30s @30fps — **our** min_scene_len) | 292 (**4.68%**) |
| Shots < 18 frames (0.60s @30fps — default-equivalent) | 842 (**13.48%**) |

Frames are what the annotations state; no fps is given, so the second
conversion assumes 30fps (typical for the platform, and the ratio
between the two thresholds is fps-independent regardless).

## What this changes

1. **The tuning decision is now evidenced, not asserted.** The
   default-equivalent 0.6s floor would merge **13.5% of real
   short-form shots**. Lowering to 0.3s was correct, and the
   docstring's "silently merges real montage cuts" now has a number.
2. **An unstated residual cost is now stated.** Our 0.3s floor STILL
   merges **4.7%** of real annotated shots. That is the honest price
   of the setting — previously invisible. Anyone reading a
   Zing cut-rate should know it is a slight UNDER-count on
   fast-montage content, by construction.
3. **A cross-check on the docstring's own number.** It cites SHOT's
   average shot length as 2.59s; this subset yields 2.40s at 30fps
   (72.1 frames). Close, and the difference is explained by subset +
   fps assumption — not a contradiction, but the docstring's figure
   should be attributed to the paper rather than implied as measured
   by us.

## Still open

The real prize — measured precision/recall of our detector against
these annotations — needs the Drive videos. That remains the filed
evaluation-before-adoption path for any TransNetV2/AutoShot decision;
this note only audits the threshold, which needed no videos.
