# Stills and animated memes

Render your photo with text written by you or your AI:

```sh
python -m pip install "myzing[memes]"
zing meme ideas --topic "one quick bug fix" --n 6
zing meme check --text "one quick fix" --text "six hours later"
zing meme render --image desk.jpg --text "one quick fix" --text "six hours later" --out meme.png
```

Zing makes no model calls. Ideas are seeded formula substitutions; your AI
writes and judges the joke using `zing prompt meme-writer` or MCP
`get_prompt("meme-writer")`. `zing doctor` reports the optional `pillow`
dependency. Templates, ideas, and checks work without Pillow.

```sh
zing meme templates --search drake --json
zing meme ideas --topic "release day" --template drake --json
zing meme render --template drake --text "one more meeting" --text "ship it" --aspect original --out drake.png
```

The catalog ships 101 classic templates as metadata only. Explicitly
rendering `--template <id>` fetches its blank from api.memegen.link on the
first use; the download has a 15-second socket timeout and a 20 MiB limit.
Blanks are cached under `$ZING_HOME/memes/templates/` (default `~/.zing`).
Use `--offline` to require a cached blank. Local photos and catalog searches
never use network. No third-party meme images are bundled.

Repeat `--text` in box order. Empty strings preserve unused slots. Each box
allows 70 characters and the entire image allows 110, after whitespace
normalization. Newlines count as one character and are preserved for
rendering. Counts use Unicode code points. Checks also report banned filler
and invalid beat counts: normally 1-3, or up to the selected template's box
count. `check` exits 1 for invalid copy; JSON distinguishes a successful
check (`ok`) from passing copy (`valid`).
For custom layouts with more than three regions, check with `--box-count`.

Rendering defaults to a square. `--aspect` accepts `16:9` (1200x675), `1:1`
(1080x1080), `4:5` (1080x1350), `9:16` (1080x1920), or `original` (1200-1920
pixels wide, retaining the source ratio). Source and output images are
limited to 40 megapixels. The still `render` command uses the first frame
of animated inputs; use `render-video` to keep motion.

- `--layout classic`: outlined Anton text at the top and bottom, in capitals.
- `--layout caption`: a white caption bar with IBM Plex Sans above the photo.
- `--layout labels`: text on normalized source-image regions. Pass
  `--regions '[[0.05,0.4,0.3,0.2],[0.65,0.4,0.3,0.2]]'` for custom placement.
  Templates default to their catalog regions; some use generic rows and
  return a placement warning.

Photos default to `--fit cover`; templates default to `contain` to retain
all panels. Labels follow the source through crop and scaling. `--plate`,
`--shadow`, and `--rotation 8` add a dark rounded plate, shadow, and rotation.
Text wraps and shrinks to fit; it is never silently dropped. `--font anton`
and `--font sans` use bundled OFL fonts with licenses in `_data/fonts/`.
Use a font path or installed name such as `--font Impact` for another font.
The bundled fonts do not cover every script or emoji; use a suitable system
font for those characters.

Output supports PNG, JPEG, and WebP. Without `--out`, a unique PNG goes into
`$ZING_HOME/memes/renders/`. Existing files require `--overwrite`;
the source image cannot be the output. `--workspace <dir>` overrides the
storage root. Every subcommand accepts `--json`.

MCP offers `meme_templates`, `meme_ideas`, `meme_check`, `meme_render`, and
`meme_render_video`.
Use `texts` for the ordered text array and `image`/`out` for input/output
paths. Render returns paths and box metadata, never inline image bytes.
Its `viral_lens` measures brevity, beats, contrast, and aspect; it does not
predict reach. Review the resulting image before sharing it.

## Animated memes

Use a local video or GIF to produce an H.264 MP4. Source audio is retained
as AAC. Add `--gif` to write a companion GIF beside the MP4:

```sh
zing meme render-video --video reaction.mp4 --start 2 --end 6 --text "one quick fix" --text "six hours later" --at 0 --at 1.5 --gif --out reaction-meme.mp4
```

Install `myzing[memes]` and put FFmpeg and ffprobe on PATH. Animated rendering
stays offline, including template selection: a catalog blank must already
be cached, or you can supply it as a local `--image`.

`--start` and `--end` are source seconds. The selected interval must be at
most 30 seconds; longer sources require an explicit trim. `--max-duration`
can lower that limit. Missing or invalid durations, unsupported containers,
files above 500 MiB, and sources above 8192 pixels on either axis or 40
megapixels are refused before encoding. Supported containers are MP4/MOV,
Matroska/WebM, AVI, MPEG/TS, and GIF; the installed FFmpeg must support their
codecs. URLs, network shares, and playlist inputs are refused.

The `classic`, `caption`, and `labels` layouts use the still renderer's text
caps, fonts, wrapping, plates, shadows, rotation, and cover/contain geometry.
Caption mode keeps a white bar above the footage. Pillow rasterizes each
text box once to a transparent PNG; FFmpeg composites those layers over the
motion. Labels stay at their output positions; they do not track subjects.

`--at` sets when text appears; `--until` sets its inclusive end. Repeat either
option once per supplied `--text`, in the same order, including empty slots.
Times are relative to the trimmed output. Omitted starts default to zero;
omitted ends default to the output duration. Each window must satisfy
`0 <= at < until <= duration`. Changes land on the next output frame.

```sh
zing meme render-video --video reaction.gif --text "setup" --text "payoff" --at 0 --at 1.5 --until 1 --until 3 --end 3 --out timed.mp4
zing meme render-video --image template.png --text "still waiting" --duration 5 --zoom 0.1 --out slow-zoom.mp4
```

Stills default to five seconds. `--zoom` adds a centered Ken Burns zoom of
0 to 0.25 (0.1 ends 10% closer); text stays fixed. Use `--duration` for stills
and `--start`/`--end` for video/GIF inputs.

MP4 defaults to 30 fps; `--fps` accepts integers from 1 to 60. Aspect presets
match stills, with odd dimensions rounded up to even for H.264 compatibility
(the 16:9 preset becomes 1200x676). `--width` accepts even widths from 64 to
1920 and scales the height with the aspect. Outputs above 4096 pixels high
or 8 megapixels are refused. Duration is quantized to output frames.

GIF defaults are at most 8 seconds, 10 fps, and 640 pixels wide, matching
MemeForge. `--gif-duration`, `--gif-fps`, and `--gif-width` can lower those
limits. GIFs use FFmpeg palette generation and palette application, contain
no audio, and loop indefinitely. Shorter/smaller MP4s are not extended or
upscaled. GIF timing uses centiseconds, so the last frame can last slightly
longer to fill the selected interval without exceeding the duration cap.
The CLI reports GIF dimensions, duration, fps, and bytes.

MCP `meme_render_video` accepts the same options with underscores (`video`,
`start`, `end`, `gif_fps`, etc.) and ordered `texts`, `at`, and `until` arrays.
It returns MP4 metadata, text boxes with time windows, and an optional `gif`
report with a path and byte size. Without `out`, files receive unique names
under the workspace's `memes/renders/` directory. Both destinations must
differ from the source; both require `overwrite=true` to replace existing
files. Probing and encoding have timeouts. Failed encodes leave existing
outputs intact and remove temporary layers.

The prompt rules, eight offline formulas, catalog, aspect sizes, and viral
lens arithmetic are ported from MemeForge's `app/api/generate/route.ts`,
`lib/meme-engine.ts`, `components/TemplateDock.tsx`, and `lib/render.ts`.
Zing adds complete multi-box ideas, region metadata, and bounded text fitting.
Font source URLs and SHA-256 digests are recorded in `_data/fonts/sources.json`.
