Render a Composition v2 file with the same command as a v1 EDL:

```text
zing render composition.json -o draft.mp4 --keep-work render-work
```

In Python:

```python
from pathlib import Path
from myzing.composition import Composition
from myzing.render import render_composition

path = Path("composition.json").resolve()
plan = Composition.from_json(path.read_text(encoding="utf-8"))
result = render_composition(plan, path.with_suffix(".mp4"), base_dir=path.parent)
```

The existing MCP `render_edl` tool accepts both versions and returns the same
job ID, paths and status metadata. Poll `get_render` for completion and warnings.
No media bytes travel through the tool.

V2 resolves media by `asset_id`; `AssetRef.path`, font paths and LUT paths are relative to
the JSON file's directory. Every listed asset must exist, including unused
assets. Supplied media, font and LUT SHA-256 hashes are checked before subprocesses,
work files or MCP job creation. A null legacy media hash is allowed with an
unverified-identity warning. Queued MCP jobs recheck hashes when they run.

The supported media graph is hard cuts, source audio, voiceover/music placement,
gain and music ducking under voiceover. Rational FPS is retained in FFmpeg's
filters and output rate. Per-clip SDR `.cube` LUTs are supported. Speed maps, non-cut transitions, HyperFrames,
other audio roles, audio source trims, non-voiceover ducking scopes and loudness
targets produce one `not yet supported in this renderer: ...` list. V2
voiceover synthesis and OTIO export are also rejected; place an existing
voiceover asset in the composition. Evidence, brief and warning metadata are
preserved without inventing render effects.

R13 renders each clip's `ColorTransform` before output-size scaling, padding,
concat and captions. The order is:

1. Verify the LUT's SHA-256, then validate the verified text with
   `myzing.color.cube`. Check the selected FFmpeg for `lut3d` and probe source
   color metadata before creating output directories or work files.
2. Trim the source and set its timestamps/FPS. Convert footage to RGB using
   the Rec.709 matrix, apply
   [FFmpeg `lut3d` with `interp=trilinear`](https://ffmpeg.org/ffmpeg-filters.html#lut3d),
   and convert back to limited-range Rec.709 `yuv420p`.
3. Scale/pad each clip to the output size, then concatenate the clips.
4. Composite captions on the graded cut. Encode the result with the existing
   H.264/AAC settings. Caption fill, highlights, outlines and plates never pass
   through the footage LUT.

`strength` blends the cube with identity in display RGB code values. The
renderer bakes that blend into a work-folder cube; trilinear interpolation
then gives `rgb + strength * (apply_cube(rgb) - rgb)`. A zero strength still
requires a valid hash, cube and input color space, but bypasses RGB conversion
and grading, preserving the ungraded graph and decoded pixels. Recipe controls
in `baked_transform` describe the original cube; they are never applied again.

The accepted input assumption is the color package's `COLOR_SPACE` string,
or the short names `SDR Rec.709/sRGB`, `SDR Rec.709 display-referred RGB`,
`SDR Rec.709`, `Rec.709`, `bt709` and `sRGB` (case-insensitive). Other declared
spaces fail. Source transfer, primaries, matrix and color/profile tags are
checked for every v2 video clip, including clips without a LUT. HDR, LOG and
non-Rec.709 metadata fail with a request to convert the source using an explicit
camera/display transform first. A creative LUT does not declare that conversion.
Missing metadata produces an SDR-assumption warning; untagged LOG cannot be
identified reliably. The color package's sRGB display-value approximation is
retained; this renderer does not perform scene-linear grading or tone mapping.

For pass 10b, HyperFrames must receive the same graded, scaled, concatenated
footage from step 3. Render its transparent caption overlays separately and
composite them at step 4. Do not grade the overlay or the footage again in the
sidecar. Timing and dimensions come from the same composition. This is the
integration boundary; the HyperFrames backend remains unwired in R13.

`--keep-work` retains `luts/clip-NNNN.cube` and `color-transforms.json` (version 1)
with clip IDs, original paths/hashes, strengths, color-space assumptions,
stage, interpolation, applied flags and baked cube hashes. The files use
controlled relative names so Windows drives, spaces, apostrophes and filter
punctuation in source paths never enter the filter expression. Input LUTs stay
unchanged. LUT validation uses the existing optional `myzing[color]` extra;
ungraded rendering does not import NumPy.

The generated-media R13 tests require median Delta E 2000 <= 2 against
`apply_cube` on evenly spaced native-resolution samples. Identity allows mean
RGB error <= 2 and 99th-percentile error <= 8 code values (8-bit), including
H.264 and YUV/RGB conversion. Half strength is checked against both the expected
blend and the midpoint of rendered endpoints. Caption interior colors allow
two code values of median difference; antialias and chroma boundaries are
excluded. Clipping is checked against the expected eight-code endpoint envelope.
These render checks are separate from the plan's broader color-selection
release gate (median Delta E 2000 <= 3 plus review of unrelated real scenes).

Frozen FFmpeg 6/9 command and graph fixtures cover v1 and v2 without LUTs.
Generate a before/after pair and measured parity report locally with:

```text
python -m tools.eval.render_lut_fixture --out zing-workspace/r13-lut-sample
```

ASS captions need libass. The renderer preflights the selected FFmpeg through
`myzing.ffmpeg_capabilities` before probing media or writing work files.
[FFmpeg documents `fontsdir` for its ASS/subtitles filters](https://www.ffmpeg.org/ffmpeg-filters.html#ass).
Both FFmpeg 6's script argument and FFmpeg 9's replacement use the existing
`filter_script_args` compatibility helper.

Each ASS event supports these controls:

- `font`: SHA-256-pinned single-face TTF/OTF with a license record. A private
  render-time family name prevents installed or same-family fonts from winning
  selection. Glyphs, shaping/variation tables and license records keep their
  bytes; only naming/checksum metadata changes in the temporary copy. The
  source file stays unchanged. A glyph requiring fallback fails with the event
  ID. A null font keeps the legacy bold Arial default and system fallback behavior.
- `style`: size in output em pixels, fill and active-word highlight colors,
  outline color/width, and optional opaque `box_color`. The compiler converts
  em pixels to libass font-size units using the supplied font's metrics, following
  [libass's REAL_DIM sizing](https://github.com/libass/libass/blob/master/libass/ass_font.c).
  A null style uses the legacy size and outline heuristics and white/yellow/black
  colors. Layout `scale` resizes the font and outline together.
- `alignment`: `left`, `center` or `right`, default `center`. With a layout,
  the visible ink plus outline aligns to that box's edge or center; vertical
  placement is centered. Without a layout, the legacy named anchor applies.
- `layout`: normalized static box or piecewise linear keyframed path. Text
  keeps its chosen size; changing path box extents changes its available region
  and alignment anchor. An optional plate fills that region and moves/resizes
  with it. Static placement uses `\pos`; timed path segments use `\move`, with
  plate size changes expressed by `\t`.
- `words`: when `word_timed` is true, the phrase remains visible and only the
  active word highlights during its half-open interval. Gaps return to fill
  color. Words must match spans of the phrase in order; punctuation and
  whitespace remain in the phrase. Measured and corrected timings render
  alike; pending/invalid provenance fails review, and originals are retained.

Explicit newlines determine wrapping. Text, braces and backslashes are escaped
for libass; a literal `\N` stays literal. A local libass pixel probe measures
the actual ink and outline before encoding. Text that exceeds any layout box
or the frame fails with the event ID and a request to add line breaks, reduce
size or replan. It is never clipped to make a safety result appear valid.
Captioned output above 100 fps is rejected because ASS event timestamps have
centisecond precision. At supported rates, boundaries target an output frame
and account for libass's millisecond truncation. No ASR timing is repaired or
claimed accurate by rendering.

Unsafe or infeasible layouts fail unless their event IDs appear in
`Composition.accepted_unsafe_layouts`. Acceptance preserves the warnings in
the render result; it does not mark the layout safe. Layout safety covers the
supplied tracks and masks, not detector recall.

`--keep-work` retains `captions.ass`, the filtergraph, font copies and
`caption-fonts.json` with source hashes and registered names. Temporary
geometry probes are also inspectable. Source assets must live outside the
renderer-owned work filenames and font directory.

The generated-media tests use bundled OFL Anton and IBM Plex Sans. They measure
highlight switches, normalized ink position, multi-keyframe motion, literal
ASS-special text, outline/plate colors and font differences. Independent
`drawtext` probes check size within 10% and box IoU of at least 0.8. These are
render fidelity checks; the release gate for human-annotated ASR timing remains
separate.
