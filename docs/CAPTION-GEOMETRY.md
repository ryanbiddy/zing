# Caption geometry

For rendering active-word backgrounds and setting phone-readable caption sizes,
see [Captions](CAPTIONS.md). This page covers observation of existing pixels.

Run `zing study reference.mp4 --caption-geometry` to write
`caption-geometry.json` beside `breakdown.json`. The breakdown retains schema
version 1 and adds only counts and the sidecar filename in
`provenance.caption_geometry`. Without the flag, the existing OCR path and JSON
shape are unchanged.

Install the existing optional `myzing[study]` dependencies. In a checkout, use
`uv sync --all-extras`. Geometry inference uses verified local RapidOCR assets
and never downloads them. If they are absent, prepare them explicitly:

```powershell
$env:ZING_HOME = "E:\my-zing-workspace"
uv run --frozen python -m myzing.study.caption_models --fetch
uv run --frozen zing study reference.mp4 --workspace "$env:ZING_HOME" --caption-geometry
```

The provisioner verifies three pinned SHA-256 hashes before replacing cached
models under `$ZING_HOME/models/caption-geometry`. An existing RapidOCR package
cache is also accepted if its bytes match. `zing doctor` checks packages and
model files without starting inference. It does not certify native runtime
health.

## Read the sidecar

`version` is 2 (CG2). Version 1 sidecars remain readable. Nested record versions
remain 1, with additive evidence fields. The dataclasses in `myzing.study.caption_geometry` support
`to_dict()` and `from_dict()`; they do not modify `myzing.schemas`.

| Field | Meaning |
|---|---|
| `frames[].t`, `frame_index` | Actual decoded CFR frame time and index. The target schedule is retained separately as `scheduled_t`. |
| `frames[].detections[].polygon` | Raw OCR polygon normalized to the display frame, clipped to [0,1], including low-confidence detections. |
| `detections[].box` | Axis-aligned bounds of the OCR polygon, ordered left, top, right, bottom. |
| `detections[].validation` | Acceptance, rejection reasons, neighboring samples, face overlap and video script consistency. OCR confidence stays unchanged. |
| `frames[].face_boxes` | Same-frame YuNet bounds when the verified local layout model is available; null means unavailable, not no faces. |
| `detections[].appearance.ink_box` | Refined visible fill-ink bounds, or null when pixel segmentation is uncertain. |
| `appearance.fill`, `outline` | Component-wise CIE Lab D65 medians, estimated sRGB bytes, and heuristic confidence. Null means unknown. |
| `appearance.ink_evidence` | Component count, edge/ink density and stroke fraction supporting the text-region decision. |
| `appearance.cap_height`, `x_height` | Median component height for suitable homogeneous Latin case runs, with confidence; otherwise null. |
| `appearance.stroke_width_px`, `stroke_width_fraction` | Estimated outline thickness in decoded pixels and as a fraction of frame height. |
| `appearance.plate_present`, `plate_color` | Evidence for a uniform background plate around the glyphs; null means unknown. |
| `tracks[].samples` | Text, normalized box, line boxes/count, frame references and height at each accepted sample. `box_method` distinguishes refined ink from an OCR proposal. |
| `tracks[].median_text_height` | Median visible fill-ink height per line, divided by frame height. This is not a font point size or em height. |
| `tracks[].alignment` | Left, center or right. Multiline edge agreement supports the estimate; a single line uses a low-confidence frame-anchor estimate. |
| `tracks[].motion`, `path` | Static, moving or cumulative word-by-word popping. Paths contain least-squares keyframes or piecewise sample centers, split at missing samples. |
| `tracks[].kind` | Caption candidate or persistent overlay. Overlay tracks remain inspectable and are excluded from the opt-in breakdown's caption events. |
| `coverage` | Scheduled hook/body fps, observed frames per second, low-confidence timestamps, missing/uncertain samples and all unsampled intervals. |
| `provenance` | Media hash, OCR/model versions and hashes, coordinate/color conventions and thresholds. |

A path's interior is a fit, never an observed frame. Its keyframes occur only
at accepted sample times. Do not extrapolate beyond a segment or bridge a gap.
Empty detections are recorded as `no_text_detected` gaps because OCR cannot
distinguish absent text from missed or fully occluded text. A frame with both
confident and uncertain text retains the confident observations and names the
uncertain detections in coverage.
Missing observations inside a linked track are also reported, even when a
watermark remains readable in those frames.

## Acceptance and limits

The caption-geometry FFmpeg tests generate all media using the bundled OFL Anton
and IBM Plex Sans files. They run real RapidOCR and compare against independently rendered
fill-only masks: median center error at most 2% per axis, median height error
at most 10%, median box IoU at least 0.8, and fitted path keyframe error at most
2% of frame dimensions. Color tolerance is Delta E 76 at most 10 in Lab D65;
outline width tolerance is 1.5 pixels on a three-pixel stroke. The low-confidence
test deliberately lowers two real inference scores to exercise the gap contract.

```text
ZING_REQUIRE_OCR=1 ZING_REQUIRE_FFMPEG=1 uv run --frozen pytest -q -m ffmpeg --expected-ffmpeg-tests 422
```

The tests establish those limits for the generated cases. Real footage, gradients,
translucency, rotated text and occlusion need further calibration. Confidence
values describe heuristic evidence quality, not calibrated probabilities.
Pixel colors assume decoded SDR/sRGB-like content; HDR and original color-space
recovery are unsupported. Add `--fonts` to compare measured text against the
local font library. The optional `font_candidates` section has its own version
and records ranked candidates, substitutions and frame evidence; see
[font candidates](FONT-CANDIDATES.md). Geometry without `--fonts` omits the
optional font section.

Overlay classification requires at least three observations, coverage of both
ends of the clip within one sampling step, at least 90% of expected samples, low text change and less than
1.5% center displacement. A full-clip static title can satisfy the same rule as
a watermark; its classification reason and evidence remain available for review.
Non-text logos are outside OCR coverage. Word replacement and scale-only animation
are retained in samples but are not labeled as cumulative word popping.

## CG2 region evidence and real replay

CG2 requires glyph components, edges and plausible ink/stroke density in addition
to recognition confidence. Bounds are checked against the recognized string's
length and the frame dimensions. Near-full-frame regions are rejected. Two
distinct neighboring samples within 0.5 seconds can corroborate recognition
scores from 0.65 to 0.75; they cannot rescue a region without text-like pixels.
Strong, brief text can survive without temporal support. Face overlap and a
script inconsistent with the video's dominant script only reject isolated,
short or visually weak regions. They do not ban subtitles over faces or stable
multilingual text. YuNet runs on the same decoded samples only when its pinned
local model is available; missing face evidence is recorded as unknown.

Rejected proposals remain in `frames[].detections` with their original text,
score and polygon, `validation.accepted=false`, reasons, and a detection-level
coverage gap. They never become tracks, font candidates or breakdown captions.
Consumers of version 2 must use `validation.accepted`, not the raw OCR score.

Segmentation uses deterministic Lab color modes, including luminance tails,
then filters connected components for glyph support. A one-pixel neighborhood
can include antialiased edges in geometry; fill colors use solid core pixels.
Outline estimates use neighboring stroke pixels and keep confidence. Font crops
reuse component support to avoid reintroducing distant scenery of the same color.
This is an SDR pixel estimate. It does not establish original typography.

The [frozen clip split](../tools/eval/real/cg2-split.json) keeps Korky and Tears of
Steel in calibration, and Duck and Cover and NASA in held-out evaluation.
The [implementation freeze](../tools/eval/real/cg2-freeze.json) was written before
CG2 held-out replay. The earlier V1 report had already disclosed title failures,
so this is a tuning holdout, not an unseen benchmark. See the
[CG2 measured report](../tools/eval/real/CG2-REPORT.md), including its held-out
regression and remaining failures. Numeric real fill-color error is unknown:
the existing labels have no measured color targets.

With the pass-rule environment and pinned OCR/font assets already cached:

```powershell
uv run --frozen python -m tools.eval.real.cg2_eval --root E:\AI\projects\zing\worktrees\v1-realeval\zing-workspace\real-eval --split calibration --output zing-workspace/cg2/calibration --workspace zing-workspace/home
uv run --frozen python -m tools.eval.real.cg2_eval --root E:\AI\projects\zing\worktrees\v1-realeval\zing-workspace\real-eval --split held_out --output zing-workspace/cg2/held-out --workspace zing-workspace/home
$env:ZING_CG2_REAL_ROOT = 'E:\AI\projects\zing\worktrees\v1-realeval\zing-workspace\real-eval'
uv run --frozen pytest -q -m real_caption
```

The replay verifies media/label/baseline hashes and refuses changed frozen code
for held-out runs. It writes sidecars, exact-frame PNG overlays and per-frame font
evidence. The opt-in test reads 2.6 seconds of Korky without seams or downloads;
its skip is registered. It is separate from the 422-test FFmpeg gate.
