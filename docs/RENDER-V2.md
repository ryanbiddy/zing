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

V2 resolves media by `asset_id`; `AssetRef.path` and font paths are relative to
the JSON file's directory. Every listed asset must exist, including unused
assets. Supplied media and font SHA-256 hashes are checked before subprocesses,
work files or MCP job creation. A null legacy media hash is allowed with an
unverified-identity warning. Queued MCP jobs recheck hashes when they run.

The supported media graph is hard cuts, source audio, voiceover/music placement,
gain and music ducking under voiceover. Rational FPS is retained in FFmpeg's
filters and output rate. LUTs, speed maps, non-cut transitions, HyperFrames,
other audio roles, audio source trims, non-voiceover ducking scopes and loudness
targets produce one `not yet supported in this renderer: ...` list. V2
voiceover synthesis and OTIO export are also rejected; place an existing
voiceover asset in the composition. Evidence, brief and warning metadata are
preserved without inventing render effects.

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
