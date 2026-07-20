# SG-4 scan: shot-boundary detection (the real-video recall gap)

Scope: transitions detector v4's own provenance admits synthetic-only
calibration — "no measurable real-video recall" — and the S5 sweep
recorded two truthful hard cases (Zach King invisible cuts; gameplay
no-cut format) where shot measurement is blind by design. This scan
asks what current OSS offers, license-first.

## The headline: AutoShot's SHOT dataset — MIT, and it IS our domain

AutoShot (CVPR-W 2023, github.com/wentaozhu/AutoShot, MIT) ships the
SHOT dataset: **853 complete short-form videos (Kuaishou/TikTok/Reels
style) with 11,606 human shot annotations**, plus weights and eval
code. Short-form social video is precisely Zing's measurement domain
— not BBC/RAI long-form like the classic SBD benchmarks.

**Highest-value use is EVALUATION BEFORE ADOPTION**: run OUR current
stack (PySceneDetect AdaptiveDetector for shots; transitions v4)
against SHOT's annotations. That converts "no measurable real-video
recall" into a measured number without touching any detector — the
cheapest possible honesty upgrade. If our numbers are good, the
provenance disclaimer shrinks to a citation; if bad, we have the
evidence an upgrade decision needs. (Fits A-Q2's accuracy-iteration
mandate; eval-harness half would be Lane C's surface.)

## TransNetV2 — MIT, PyTorch inference, ADOPT-CANDIDATE (gated)

soCzech/TransNetV2: MIT, pretrained weights, PyTorch inference path.
The standard learned SBD baseline; AutoShot reports +4.2% F1 over it
on SHOT specifically (and +~1% on ClipShots/BBC/RAI). Both are
100-frame rolling-window frame-probability models — architecturally
suited to gradual/soft transitions that frame-differencing misses.
Gate: only worth weighing AFTER the SHOT evaluation of our current
stack — a learned detector adds model-weight distribution, GPU-or-slow
inference, and a second calibration surface; the evaluation may show
AdaptiveDetector is already adequate for cut-rate/profile purposes
(our use is style measurement, not frame-exact segmentation).

## AutoShot the MODEL — WATCH only

MIT and short-form-SOTA, but single-checkpoint research code with a
NAS-derived architecture; maintenance risk is real and the +4.2%
over TransNetV2 only matters if the evaluation shows our gap is in
exactly that band. Revisit after evidence.

## Citation audit (self-initiated, 2026-07-19, prompted by CX-6)

Every load-bearing claim above re-verified against PRIMARY sources
after the trust flag on AG's dossiers — a scan is only worth its
citations:

- SHOT dataset "853 complete short videos and 11,606 shot
  annotations" — VERBATIM from AutoShot's README; platform list
  (Kuaishou/TikTok/Reels/YT Shorts) confirmed there too.
- AutoShot MIT — confirmed by fetching the LICENSE file (MIT,
  (c) 2023 Wentao Zhu), not GitHub's sidebar inference.
- TransNetV2 MIT — same method (MIT, (c) 2020 Tomas Soucek).
- surya's split license (the REJECTION basis, so verified hardest):
  README states verbatim "The Surya code is licensed under Apache
  2.0. The model weights use a modified AI Pubs Open Rail-M license
  (free for research, personal use, and startups under $5M
  funding/revenue)." Root LICENSE is indeed Apache. The rejection
  stands on the primary source.
- CORRECTION: my scan wrote the weights license as "cc-by-nc-sa /
  OpenRAIL-M". The repo's own badge and text say OpenRAIL-M only;
  cc-by-nc-sa came from a secondary summary, not the source. The
  rejection is unaffected (both carry commercial restrictions
  incompatible with MIT), but the specific string was wrong.

## Honest limits

- SHOT's annotation granularity (hard cuts vs gradual types) needs
  reading before eval design; our transitions v4 distinguishes kinds,
  SHOT may not.
- The Zach King class stays hard for ALL of these — invisible cuts
  are adversarial to frame evidence; no scanned tool claims them.
  The sweep's "warning keyed on genre" disposition stands.
