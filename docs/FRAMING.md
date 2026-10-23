Composition v2 supports per-clip `framing`: `fit`, `fill`, `reframe`, `zoomfill`, and
`blurfill`. Omit it to retain the existing fit-and-pad graph and JSON bytes.
EDL v1's default render path and v1/v2 compatibility fixtures are unchanged.

To discard static broadcast bars before adapting a source:

```powershell
zing render plan.json --aspect all --picture-crop auto -o delivery.mp4
```

`picture_crop` in a brief accepts `auto` (default), `on`, or `off`. Auto uses a
picture rectangle only when every used source range has consistent borders,
static outer regions and motion inside. `on` requires that evidence and fails
with a remedy if it is unavailable; it does not guess harder. `off` preserves
the full source. These choices also work in match and studio.

The local detector samples up to 12 gray frames per merged used range, with
at most 10 ranges. Two horizontal boundaries must persist across at least
80% of the central 70% of the frame width;
at least 98% of the outer region must have temporal standard deviation ≤3
gray levels, and at least 3% of the picture must vary. Confident candidates
retain 25–94% of source area. Matching side borders can remove side chrome.
The delivery analysis records sample counts, border support, variance, motion
fraction, retained area, confidence and the decision. Selected source-pixel
bounds and evidence also travel in each clip's `framing.picture`.

The crop precedes fit/fill/reframe and blurred-background generation. Caption
safety and enlargement advice use the resulting live picture. Moving lower
thirds, changing layouts, freezes, weak borders and motionless room edges may
remain ambiguous. This is sampled static-frame detection, not recognition or
reconstruction of obscured picture. NumPy (`myzing[color]`) is optional; without
it the decision is unavailable and auto retains the source.

YuNet tracking now retains raw observation times and small RGB histograms for
fragment stitching within each shot and used range. Fragments may overlap in
their held intervals. A link requires a gap ≤1.25 s, position within .45 face
width/height units, size ratio ≤1.3 and histogram similarity ≥.82. Two raw
detections at the same time are a hard conflict, so simultaneously visible
faces stay separate. Ambiguous alternatives and missing appearance also stay
separate. Every accepted link records its numbers and heuristic confidence;
histograms are appearance evidence, not biometric identification or speaker
diarization. Lighting changes and long occlusions can still require review.

Fit retains the entire picture with black padding. Fill crops around a stated
center. Reframe follows local subject evidence with bounded crop motion.
Zoomfill crops to an intermediate width around the subject, keeps every source
row, scales that sharp picture to the output width, and fills the remaining
height with blur. Its crop can move horizontally; its size stays fixed per shot.
Blurfill fits the sharp picture and fills the surroundings with a blurred,
darkened copy of the same frames. Its background is blurred at quarter delivery
resolution, converted to 8-bit 4:2:0, darkened to 55% luma above black, and
desaturated to 65%. The conversion keeps 10-bit, RGB and full-range sources
neutral. Source-baked mattes can remain; framing does not reconstruct detail.
Blurfill and zoomfill scale the sharp picture to an explicit even size (the
planned size, never rounded up) at an even origin, so caption bands, coverage
reports and rendered rows agree exactly on FFmpeg 6.1.1 and 8.1.2.

Set brief `framing` to `auto` (default), `fit`, `fill`, `reframe`, `zoomfill`, or `blurfill`:

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
`--short-side` defaults to the brief's `short_side`, else 1080: 1920×1080,
1080×1080 and 1080×1920. It accepts multiples of 18 from 18 to 4320 for
even, exact-aspect dimensions, or `auto` (see "Low-resolution sources").

Auto evaluates display-oriented, square-pixel geometry in this order:

1. Fit when source and output aspects agree within 1%.
2. Reframe to fill the output if the full crop passes the checks below.
3. Try zoomfill at a target **70% sharp height**, reducing that share as needed
   to respect enlargement and subjects. The intended vertical range is 50–70%.
   Width starts at `ceil(max(output_width / max_upscale,
   output_width * source_height / (0.70 * output_height)))`. Widen the window
   until it retains the required subjects. Source height is never cropped.
   Widths narrower than the subjects' inner 98% spans (or two thirds of the
   source when evidence has gaps) cannot pass at any position and are skipped,
   so a two-shot search assesses tens of widths, not every pixel width.
4. Use full-picture blurfill if no intermediate crop passes, or if the source
   is narrower than the output. Fit remains available as an explicit choice.

This prefers the largest admissible picture in those families: a full crop,
an intermediate picture capped at 70% height, or the full source. Enlargement
means output pixels per source pixel in the sharp foreground, not the blur.

| Check | Policy |
|---|---|
| Matching source/output aspect | Within 1%: fit the full picture |
| Crop enlargement | At most `framing_max_upscale`, default **2.5×** linear |
| Retained source area | At least 30% |
| Retained source height | At least 60%, preserving vertical context |
| Supplied face/person or object tracks | At least 98% box coverage on every output frame |
| Subject top | Keep all of the top, with headroom of 8% of box height or 2% of source height, whichever is larger; clamp headroom at the source edge |
| Gaps in subject evidence | Full reframe permits at most 10% source loss. Zoomfill keeps all source rows and at least two thirds of source width; unknown subjects can still be missed, and this is reported |

Each clip's `assessments` records the rejected crop and final choice: sharp
height/area share, enlargement, retained source area, minimum tracked coverage,
headroom result, evidence gaps and rejection reasons. Warnings explain the
decision. Missing detections are not proof that a crop contains every subject.

A 640×360 NASA frame needs a 198×352 full portrait crop: **5.455×** at 1080×1920.
Zoomfill can use 432×360 at **2.5×**, for a 1080×900 sharp picture: **46.875%**
of screen height, up from blurfill's 31.7%. A 360-row source cannot reach 50%
at 1920 output rows under that limit. The plan reports the missed 50–70% target;
it does not raise the ceiling. A two-shot may require an even wider window.
The 2.5× ceiling is a quality heuristic:
each source pixel already covers 6.25 output pixels in area, so further
enlargement quickly softens archival detail. It is not a measured perceptual
optimum. Configure it with brief `framing_max_upscale` (1–16), or render
`--max-upscale`. Explicit fill/reframe can override quality and context checks,
but a tracked top/headroom violation falls back to zoomfill or blurfill. Unknown
dialogue must also retain the two-shot. Explicit reframe also rejects more than
10% crop loss in gaps in
subject evidence: a diagonal rocket nose can leave through a side edge, so
headroom alone is insufficient. Explicit fill remains a manual context override.
Explicit crops warn above their stated `max_upscale` (default 2.5, the same as
auto). Full-picture fit/blurfill can exceed it for very small sources;
those enlargements warn too. Background enlargement is intentionally blurred.

The contract uses square-pixel source coordinates after display rotation.
`source_width` and `source_height` are checked against ffprobe. Display-matrix
rotation takes precedence over legacy rotate tags; SAR is applied before
rotation. Odd source sizes are supported. Explicit framing normalizes display
geometry first; only absent framing retains the old graph spelling.

`bounds` states the allowed source rectangle; `width` and `height` are the fixed
integer crop size. Fill/reframe crops exactly match the output aspect; zoomfill
must fit within output height when scaled to output width. Fit and blurfill
retain the full source rectangle. Every window fits its bounds and source.
Framing, CropBounds, CropKeyframe and CropAssessment require `version: 1` in JSON.
There is no animated zoom. Explicit framing blocks lossy v1 lowering.
Absent/default brief additions remain omitted, including nested old fixtures.

Reframe and zoomfill keys contain `time`, `center_x` and `center_y`. Time is clip-local output
seconds. Keys start at zero, increase, and stay within clip duration; at most
256 keys are accepted. Endpoints hold. Smoothstep `u*u*(3-2*u)` has zero endpoint
velocity and peak speed 1.5 times distance divided by elapsed time.
Validation enforces Euclidean `max_velocity`; the planner uses half the smaller
crop dimension per second, averages neighboring targets and limits steps.
The vertical position is one value per shot: it centers the vertical span of the
shot's faces and people (objects when there are none), then moves up only as far
as the highest measured top's headroom line requires, so a low subject in a
portrait or 4:3 source stays in a 16:9 crop. With no evidence the crop is
top-aligned. Smoothing cannot average the headroom away. Zoomfill keeps the full source height,
which also preserves a rocket nose at the top edge when detection fails.
Fast subjects can outrun horizontal tracking. Acceleration is not separately limited.

Optional composition `speech_words` supplies source-clock evidence without
changing legacy `Word`. Each `SpeechWord` has `version: 1`, `asset_id`, `text`,
`start`, `end`, optional `speaker` and `face_track_id`, and `confidence`.
These fields round-trip and block lossy v1 lowering. Delivery planning consumes
them; ordinary ASR words contain no speaker identity and do not invent one.

For a named speaker, use the supplied face-track association when that track
covers the turn. Without a supplied association, the face-size heuristic chooses
the only face, or a face with at least 1.5 times the next-largest median box area
during the words, when no other face appears during the turn. Its confidence is
**0.55**, explicitly uncalibrated; size does not establish identity. The
heuristic must be one-to-one within a clip: if it would give one face to two
speaker labels (the bigger face "speaking" for everyone) or two faces to one
label, those turns retain the two-shot. An ambiguous, missing or overlapping
speaker retains all visible people. Nearby words from one speaker form a turn (gap at most 0.8s).
The window holds during that turn. It moves with smoothstep only between turns,
after the preceding word's ceiling frame and before the next word's floor frame.
Coverage is checked for the held subject during turns and during the silences
the window holds through (before the first turn, after the last, and between
turns of one subject); only a move between two different subjects is exempt.
If the held plan fails, the same window follows all subjects instead, and the
turns record "speaker hold failed subject checks".
If the silence is too short for the velocity limit, retain the two-shot for the
clip. Source-shot splits permit hard re-centering on a cut. `speaker_turns`
records clip-local times, association, method and confidence in the framing plan.
No diarization model or face identity recognition is added.

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
is not treated as probability. Faces and people are framed together unless
speaker evidence selects a face. Detector confidence does not identify the speaker.
Saliency has confidence .25; center/hold has zero.

Saliency excludes components whose bounding box exceeds 35% of frame area or
whose pixels occupy less than 20% of that box, clipped bright regions
with area ≥1% and either mean luma ≥225 or at least 25% of pixels ≥235,
and regions of area ≥0.5% where over 45% of
pixels changed by more than 30 levels and the region is bright (mean >190) or
warm-colored. This suppresses generated moving exhaust/fire and large glare;
it is not a universal fire or object classifier. Small compact bright targets
remain eligible. Missing or suppressed evidence uses a centered, conservative
intermediate crop or full-picture fallback with confidence zero.
Scene boundaries reset temporal comparison. Missing dependencies and sampling
failures are disclosed. This path never downloads models.

Caption planning uses the sharp picture and generic output-frame reserves.
For vertical blurfill/zoomfill, prefer the lower blur band if the complete caption
fits there throughout its event; otherwise try the upper band, then the sharp
picture. The band must fit the estimated wrapped text with its outline and plate.
Every placed vertical caption is then measured with the positioned renderer's
own libass probe (text and outline at the layout scale plus the plate padding);
if the 0.8 em estimate was short, as with bold W, the text shrinks until the
measured ink fits the placed box, which never moves or grows. The scope records
"measured libass ink+plate fits the box"; a custom font is measured at render.
Fit's black padding is not caption content. A caption's overlap scope records
which region was used. No text crosses a sharp/blur boundary.

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

Default font size is the output short side divided by 18. Vertical captions use
at least a short-side/270 black stroke (4 px at 1080) and a dark `#111111` plate
when no plate was supplied, but only once a caption is placed: the measured
safe-default check below runs first, so a safe 9:16 default stays v1. This also strengthens thin reference fonts on busy
footage. Square and landscape retain their existing style defaults. Explicit sizes and
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
`test_aspect_delivery*.py` and `test_reframe2*.py`: all requested shapes, odd sizes, SAR, phone rotation,
blurfill edges, moving targets/exhaust, safe captions, CLI/MCP and multi-aspect
match/resume. Licensed acceptance media stays outside Git.

## Low-resolution sources

A small source cannot fill a large vertical or square frame with a sharp
picture inside `framing_max_upscale`. Every director plan and every
per-aspect delivery therefore carries a `resolution` record, and when a
source is resolution-limited its summary is the first plan warning (and the
first `zing plan drafts` summary warning; `zing render` repeats it on
stderr). It states the source pixels, the enlargement a full-frame sharp
picture would need, and the sharp height share and enlargement the plan
actually uses. Example (an 862×360 Tears of Steel clip at 9:16):

> Low-resolution source for 9:16: 862x360 source needs 5.33x to fill
> 1080x1920 with a sharp picture; within the 2.5x limit the plan shows 42.8%
> sharp height (zoomfill, 2.50x). Recommended: deliver 720x1280
> (--short-side 720, or brief short_side 720 / "auto") for up to 70% sharp
> height at 2.49x; or keep 1080x1920 with zoomfill/blurfill. Upscaling cannot
> recover detail.

A source is resolution-limited when no framing at this size reaches its
sharp target within the limit: 70% of the output height for sources wider
than the output (the zoomfill target), the full height for same-aspect and
narrower sources, and the plan's enlargement is at (or past) the limit. A
shortfall caused by subject or evidence-gap policy (a crop held wider than
the limit allows) is not flagged. The recommendation is the largest short
side (a multiple of 18, at least 360) that reaches the target without extra
upscaling; when the whole picture fitted to the width is already above the
target (4:3 in 1:1, 3:4 in 9:16), it is the size at which that fit stays
within the limit. It lists its expected share ("up to": geometry only),
enlargement, `--short-side` command and brief answer. Players enlarge
a 720×1280 upload to the screen, so on a phone it looks the same or softer
up close; the trade is a larger sharp picture instead of blur bands. When
that size would be below 360p the recommendation is to keep the size with
zoomfill/blurfill. Alternatives are listed in `alternatives`.

Brief `short_side` (default 1080, omitted from saved briefs) chooses the
delivery size for director plans and deliveries; `"auto"` re-plans an
aspect at the recommended size only when its source is resolution-limited,
keeps that size only when the planned sharp picture is larger (or an
enlargement past the limit comes back within it), and records
`auto_selected` (from, to, reason). Otherwise it keeps the size and records
`auto_declined` (the tried size and its planned numbers): subject evidence,
not resolution, held the crop. With several sources the
lowest recommendation wins. Zing has no "enhance" filter: lanczos and
sharpening change how enlargement looks, but no filter recovers detail.
