# Local SDR color matching

Match a clip toward a reference's measured palette and tone:

```sh
uv sync --extra color  # from the source checkout
uv run --frozen zing color match --reference reference.mp4 --clip clip.mp4 --out zing-workspace/look
uv run --frozen zing color apply --lut zing-workspace/look/look.cube --in clip.mp4 --out zing-workspace/graded.mp4
```

FFmpeg and ffprobe must be on PATH. `zing doctor` reports NumPy availability.
Both commands accept `--json`. Match emits the complete recipe; apply emits
output paths, hashes, and warnings. Failures return a nonzero status and, with
`--json`, an `ok: false` error object. Existing output files are refused.
Apply writes H.264 at CRF 16 in YUV 4:4:4 to `.mp4`, `.mkv`, or `.mov` and copies
audio streams. This favors color preservation; some hardware players require
4:2:0. An audio codec incompatible with the selected container fails explicitly.

`--reference` also accepts a breakdown slug from the workspace selected by
`ZING_HOME`. Its locally stored video and shots are used; nothing is downloaded.
The Python `measure_video(..., shots=...)` interface also accepts shots for a clip.
No CUDA, model weights, cloud calls, or third-party LUT assets are used.

Each match writes `look.cube` and `recipe.json` to `--out`. The contact sheet goes
under `./zing-workspace/color/`, with its absolute path in the recipe. Columns
are BEFORE, REFERENCE, AFTER; rows include the requested sample timestamps.
Reference rows span the reference's sampled timeline. They are visual comparisons,
not aligned frames from the same scene.

## What the result means

The result is a **matched approximation**. Pixels do not identify a creator's
original LUT. Different subjects, lighting, framing, and graphics change the
statistics even when two videos use the same grade. Review the contact sheet
before using the result. A distribution score is not a pixel color error.

The standalone command grades footage. Existing burned-in captions are part
of its pixels and will be graded. The [v2 renderer](RENDER-V2.md) also accepts
per-clip LUTs and applies them before ASS and HyperFrames caption layers.

## Measurement and color assumption

The supported working domain is display RGB in [0, 1], with Rec.709/sRGB
primaries and D65 white. RGB code values use the sRGB transfer function for
CIELAB measurements. BT.709 transfer-tagged sources carry a warning about this
approximation. FFmpeg decodes YUV with a BT.709 matrix and honors input range;
output YUV is explicitly converted and tagged BT.709. Missing color tags are
reported as an assumption, never as detected SDR. Display rotation is honored.

PQ, HLG, declared LOG transfer/profile tags, non-Rec.709 primaries, and unsupported
matrix tags fail with a request for a declared input transform. A flat untagged
sample cannot prove LOG: the warning says it may also be low-contrast SDR.
An undeclared camera profile can escape detection. Apply validates the declared
color space; it does not estimate an input camera transform.

Match samples 12 frames per input by default (`--samples 1..32`). Without shots,
it seeks to the centers of equal-duration bins. With shots, it samples every shot
when the budget permits, allocates remaining samples by duration per existing
sample, and spaces samples evenly inside each shot. If there are more shots than
the budget, it selects evenly spaced shot indices and discloses missing coverage.
Invalid or overlapping shot intervals fail. Each frame is resized to at most 160
pixels on its long side, then at most 4,096 evenly spaced pixels are retained.

Per-sample and pooled measurements include encoded Rec.709 luma and CIELAB L*
percentiles (1, 5, 25, 50, 75, 95, 99), L* contrast (p95 minus p5), a*/b* means,
standard deviations and percentiles, chroma percentiles (5, 25, 50, 75, 95),
mean a*/b* in lightness quartiles, eight deterministic median-cut Lab palette
centroids and weights, and black/white clipping fractions. Clipping means **any
channel** at or beyond 1/255 or 254/255; saturated colors can trigger it.
Pooled statistics weight retained samples equally, not every source frame.

Coverage records requested/usable samples, their temporal span, and the fraction
of supplied shots sampled. Seek positions are requested seconds, not exact PTS.
A failed sample remains a warning and reduces coverage. Confidence is a heuristic:
at most 0.85, scaled by sample success, up to four usable samples, and shot
coverage; capped at 0.6 for missing color metadata and 0.2 for flat/clipped samples.
It is not a calibrated probability or a full-duration inspection.

## Look bank and search

The eight original procedural looks are neutral, warm, cool, teal-orange,
faded-film, punchy, desaturated, and golden-hour. Their numeric parameter sets
live in `src/myzing/color/looks.py` under Zing's MIT license.

Exposure is bounded to +/-0.5 EV in linearized sRGB. Temperature/tint controls
are bounded to +/-0.06: linear RGB gains are
`2**[temperature, tint, -temperature]`. These are small corrective gains, not
estimates in kelvin. The creative look then applies code-value contrast, gamma,
channel gains, saturation, shadow/highlight tints, lift, and a strength blend
in [0, 1]. The final cube bakes in the whole transform; apply does not repeat
the strength or corrections.

Search uses at most 2,048 pooled pixels per input. For each look it tries strengths
0, 0.1, ..., 1, refines the best two starts by bounded coordinate search over
strength/exposure/temperature/tint, and halves step sizes four times. The neutral
look starts at strength zero. The best transform per look is baked into a 33^3
cube and rescored with trilinear interpolation before ranking. This is a bounded
search, not a proof of the continuous global optimum.

The distance is a sum of normalized mean squared differences:

| Component | Scale | Weight |
|---|---|---|
| L* percentiles | 100 | 3 |
| Encoded luma percentiles | 1 | 1 |
| L* contrast | 100 | 1 |
| a*/b* percentiles | 128 | 2 |
| a*/b* means | 128 | 2 |
| a*/b* standard deviations | 128 | 1 |
| Chroma percentiles | 128 | 1 |
| Lightness-quartile a*/b* means | 128 | 2 |
| Black/white clipping fractions | 1 | 0.2 |

The palette term adds 0.25 times the sum of weighted nearest-centroid squared
distances in both directions, with Lab normalized by [100, 128, 128]. The recipe
retains every weighted component, ranked candidate, chosen parameters, baseline
score, and selection reason. Similar scores cap confidence at 0.5; a residual
above 0.02 caps it at 0.35; reaching a correction bound caps it at 0.5.

Cube tables use red-fastest ordering and deterministic ten-decimal serialization.
The reader validates headers, row count, finite normalized RGB values, size 2..65,
and the supported unit domain. Standard omitted domains default to [0, 1].
1D/shaper LUTs and non-unit domains are rejected. Both the Python interpolation
and [FFmpeg lut3d](https://www.ffmpeg.org/doxygen/8.1/vf__lut3d_8c.html)
use trilinear interpolation. Hard clipping knees can soften by about three RGB8
codes in a 33^3 table; the color gate tests the exported and rendered result.

## Reproduce the color gate

```sh
uv sync --all-extras
uv run --frozen python -m tools.eval.color_fixture --out zing-workspace/color-evidence
uv run --frozen pytest -ra
```

Set `ZING_REQUIRE_FFMPEG=1`, then run:

```sh
uv run --frozen pytest -q -m ffmpeg --expected-ffmpeg-tests 204
```

The original synthetic RGB chart is graded with teal-orange at strength 0.87.
The generator saves paired FFV1 videos, the selected cube/recipe, an H.264 render,
and `metrics.json`. Acceptance requires top-one look recovery, strength within
0.08, and rendered median Delta E 2000 <=3. It also checks the ungraded baseline
exceeds 3, so an identity result cannot pass this fixture. Unit recovery tests
cover all seven non-neutral looks at strengths 0.37 or 0.67.

Delta E uses an independent implementation of the published equations, checked
against numerical pairs including zero-chroma and hue-wrap cases from
[Sharma, Wu and Dalal](https://www.ece.rochester.edu/~gsharma/ciede2000/ciede2000noteCRNA.pdf).
The identity video test allows 5 RGB8 codes at the 99th percentile and 1.5 codes
on average after H.264 encoding. A separate affine channel-permutation LUT
checks FFmpeg table ordering and interpolation. These tests do not establish
perceptual quality across unrelated real scenes; that still needs human review.

NumPy is the only new optional dependency (BSD-3-Clause; included in `color` and
`all`). The installed NumPy 2.4.6 wheel declares
`BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0` for its bundled components.
FFmpeg remains an externally installed tool with its existing build-dependent
license. No binaries or external LUTs are bundled by this pass.
