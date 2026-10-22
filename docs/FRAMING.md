Composition v2 supports per-clip `framing`: `fit`, `fill`, `reframe`, and
`blurfill`. Omit it to retain the existing fit-and-pad graph and JSON bytes.
EDL v1's default render path and v1/v2 compatibility fixtures are unchanged.

Fit retains the entire picture with black padding. Fill crops around a stated
center. Reframe follows local subject evidence with bounded crop motion.
Blurfill fits the sharp picture and fills the surroundings with a blurred,
darkened copy of the same frames. Its background is blurred at quarter delivery
resolution, converted to 8-bit 4:2:0, darkened to 55% luma above black, and
desaturated to 65%. The conversion keeps 10-bit, RGB and full-range sources
neutral. Source-baked mattes can remain; framing does not reconstruct detail.

Set brief `framing` to `auto` (default), `fit`, `fill`, `reframe`, or `blurfill`:

```shell
zing brief new project --answers '{"aspect":"9:16","framing":"auto","framing_max_upscale":2.5,"aspects":["16:9","1:1","9:16"]}'
zing render plan-A.json --aspect all -o draft-A.mp4
zing render plan-A.json --aspect 16:9,1:1 --framing blurfill -o draft-A.mp4
```

One composition produces `draft-A.16x9.mp4`, `draft-A.1x1.mp4`, and
`draft-A.9x16.mp4`, separate composition JSON files and a
`draft-A.deliveries.json` report. Each delivery preserves source choices, trims,
audio, grade and timeline, and rebuilds source framing and caption layout.
It never rescales an already rendered draft. Source-cut splits preserve timing.
Music plans travel unchanged: every delivery carries the same MUSIC1 evidence,
music trim, gain and known-speech ducking, and writes its own
`draft-A.<aspect>.music.json` measurement sidecar. Split pieces still match
the timeline the speech spans were planned for (see [Music](MUSIC.md)).
Transition-linked clips retain their handles and are not split; auto can choose
blurfill when their crops lose subjects. Forced reframe across internal cuts
in a transition leg needs editorial review.

No delivery file may replace something the render reads. The source plan,
assets, LUTs and fonts are checked before any analysis, and a collision (for
example `draft-A.9x16.json` rendered with `-o draft-A.mp4`) is refused with both
paths. Analysis and render work lives in a temporary folder next to the output
and is removed afterwards; `--keep-work DIR` keeps it in `DIR`.

`--aspect` accepts `all` or a comma-separated list. Without it, a v2 brief's
optional `aspects` list requests deliveries; an empty list renders the composition
unchanged. Scalar `aspect` remains the director's primary plan aspect.
`zing match` also honors `aspects`: three edits become up to nine separately
decoded/inspected deliveries named `draft-A.9x16.mp4`, etc. To record a local
draft choice, retain A/B/C and supply the aspect's plan with `--draft-file`.
No peer sharing is implied.

MCP `render_edl(edl_path, output_path)` honors a v2 brief's `aspects` list;
`get_render` returns every output and the report. Its wire schema is unchanged.
Explicit aspect rendering
upgrades v1 EDL input in memory; ordinary v1 rendering is unchanged.
`--short-side` defaults to 1080: 1920×1080, 1080×1080 and 1080×1920.
It accepts multiples of 18 from 18 to 4320 for even, exact-aspect dimensions.

Auto evaluates the maximal integer crop after display rotation and sample
aspect ratio normalization, with these deterministic thresholds:

| Check | Policy |
|---|---|
| Matching source/output aspect | Within 1%: fit the full picture |
| Crop enlargement | At most `framing_max_upscale`, default **2.5×** linear |
| Retained source area | At least 30% |
| Retained source height | At least 60%, preserving vertical context |
| Supplied face/person or object tracks | At least 90% box coverage on every output frame |
| Gaps in subject evidence | Permit at most 10% crop loss during unmeasured intervals |

A failing crop check selects blurfill, with reasons saved on the clip.
Portrait-to-landscape usually fails the height rule. A 640×360 NASA frame needs
a 198×352 crop for full-HD 9:16: **5.455×**, so auto selects blurfill; its sharp
foreground instead scales by 1.688×. The 2.5× ceiling is a quality heuristic:
each source pixel already covers 6.25 output pixels in area, so further
enlargement quickly softens archival detail. It is not a measured perceptual
optimum. Configure it with brief `framing_max_upscale` (1–16), or render
`--max-upscale`. Explicit fill/reframe override auto but still warn above their
stated `max_upscale` (default 2.5, the same as auto). Full-picture fit/blurfill can exceed it for very small sources;
those enlargements warn too. Background enlargement is intentionally blurred.

The contract uses square-pixel source coordinates after display rotation.
`source_width` and `source_height` are checked against ffprobe. Display-matrix
rotation takes precedence over legacy rotate tags; SAR is applied before
rotation. Odd source sizes are supported. Explicit framing normalizes display
geometry first; only absent framing retains the old graph spelling.

`bounds` states the allowed source rectangle; `width` and `height` are the fixed
integer crop size. Fill/reframe crops exactly match the output aspect; fit and
blurfill retain the full source rectangle. Every window fits its bounds and
source. Framing, CropBounds and CropKeyframe require `version: 1` in JSON.
There is no animated zoom. Explicit framing blocks lossy v1 lowering.
Absent/default brief additions remain omitted, including nested old fixtures.

Reframe keys contain `time`, `center_x` and `center_y`. Time is clip-local output
seconds. Keys start at zero, increase, and stay within clip duration; at most
256 keys are accepted. Endpoints hold. Smoothstep `u*u*(3-2*u)` has zero endpoint
velocity and peak speed 1.5 times distance divided by elapsed time.
Validation enforces Euclidean `max_velocity`; the planner uses half the smaller
crop dimension per second, averages neighboring targets and limits steps.
Fast subjects can outrun it. Acceleration is not separately limited.

FFmpeg evaluates crop x/y from `n/(fps numerator/fps denominator)` after CFR
sampling and E2E1's rounded absolute frame allocations. Each axis is one
smoothstep piece per key segment, selected by a balanced binary `if()` tree, so
expression depth grows with log2 of the key count. A flat sum of segments fails
on FFmpeg 8 beyond about 93 moving segments; the 256-key maximum is gated. LUTs precede framing;
captions follow framing and joins. `crop:exact=1` avoids chroma-grid rounding;
raster origins remain integer pixels. Local gates cover FFmpeg 6.1.1 and 8.1.2;
FFmpeg 9 remains a CI check.

Subjects are sampled only over the source trims an edit uses, each widened by
0.5 s, at 2 fps plus the first frame of every used source shot, within a
600-frame budget per source. A longer used span lowers the regular rate to fit
(with a warning) instead of failing, so source length never removes evidence.
More separate ranges than the budget keep one frame from evenly spaced ranges.
Tracks are built per source shot and per used range: no linking, smoothing,
endpoint hold or interpolation crosses a cut or an unused gap, at any rate.
Director drafts and `zing match` deliveries analyze each source once over the
union of the A/B/C trims. Priority is YuNet faces, OpenCV's bundled HOG pedestrian detector,
then stable contrast components. HOG needs no download, has limited recall for
seated/occluded people and receives conservative .5 confidence; its SVM score
is not treated as probability. Faces are ranked by area and center preference
with a sticky track choice. Confidence does not identify the speaker.
Saliency has confidence .25; center/hold has zero.

Saliency excludes components whose bounding box exceeds 35% of frame area or
whose pixels occupy less than 20% of that box, clipped bright regions
with area ≥1% and either mean luma ≥225 or at least 25% of pixels ≥235,
and regions of area ≥0.5% where over 45% of
pixels changed by more than 30 levels and the region is bright (mean >190) or
warm-colored. This suppresses generated moving exhaust/fire and large glare;
it is not a universal fire or object classifier. Small compact bright targets
remain eligible. Missing or suppressed evidence leads to hold or auto blurfill.
Scene boundaries reset temporal comparison. Missing dependencies and sampling
failures are disclosed. This path never downloads models.

Caption planning intersects the sharp picture's visible bounds with generic
output-frame reserves. The blurred background is not caption content.

| Delivery | Left | Top | Right | Bottom |
|---|---:|---:|---:|---:|
| 9:16 | 6% | 8% | 16% | 20% |
| 1:1 | 5% | 5% | 5% | 10% |
| 16:9 | 5% | 5% | 5% | 10% |

These are conservative Zing defaults, not guarantees for every app's overlays.
Swept subject envelopes cover each caption's quantized render interval, with a
two-source-pixel rounding allowance. Reference placement survives only if it
passes the new checks. Deliveries discard old layout geometry and prior unsafe
acceptance. Captions remain static during an event. The chooser finds free space
or shrinks the box, and reflows long lines into narrower side gaps when needed;
infeasible results stay unsafe.

Default font size is the output short side divided by 18. Explicit sizes and
outlines scale by the short-side ratio during adaptation, clamped to the
caption contract (1–512 px size, 0–20 px outline). Preliminary wrapping
and bounded shrink fit the available content; actual glyph/outline ink is still
measured before publishing. Word timing is unchanged. Crowded frames can need
manual editing when no safe legible caption position exists.

Director plans keep v1 export where it changes nothing: a square-pixel
full-picture fit is written as absent framing (the same default graph), and an
unstyled default-font caption keeps no layout or style when its default box
clears measured subjects, content and output reserves. That box is libass ink
measured by the positioned renderer's probe (Arial Bold, short side/12, outline
short side/270) at 118% size and outline, the v1 word-pop peak, plus
max(4 px, short side/180) on every side. Neither renderer re-checks an unplaced
caption, so no estimate is trusted: without FFmpeg/libass, or when the probe
fails, the caption is placed. Placed captions block v1 lowering and are listed
in the report.

Director and delivery reports retain tracks and warnings. Per-aspect
compositions retain crop keys, bounds, modes, limits and caption geometry.
Generated-media coverage is in `test_framing*.py` and
`test_aspect_delivery*.py`: all requested shapes, odd sizes, SAR, phone rotation,
blurfill edges, moving targets/exhaust, safe captions, CLI/MCP and multi-aspect
match/resume. Licensed acceptance media stays outside Git.
