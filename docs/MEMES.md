# Stills and animated memes

## Photos and a topic

Make six distinct concepts from a local photo folder, then pick a concept ID
from the contact sheet:

```sh
uv sync --extra memes  # from the source checkout
uv run --frozen zing still --photos ./photos --topic "one quick bug fix" --out ./stills --n 6 --aspect 4:5
uv run --frozen zing still pick ./stills --id still-0123456789abcdef
```

Both `zing still` and `zing still pick` accept `--workspace DIR` and `--json`.
The workspace selects cached models and assets; the explicit output folder
stays independent of it. Workspace defaults to `ZING_HOME`, then `~/.zing`.

Replace the example ID with one printed by your run. `--n` is the total
number of concepts, from 1 to 8. Zing distributes them across candidate
photos, seeds the existing formula engine with the topic and photo hash,
and removes duplicate complete captions. The same photo bytes and topic
produce the same concepts and IDs with the same local detector setup.
Scores measure readability and compression; they do not predict popularity.

The output folder must be new or empty. It receives full-size candidate
PNGs, `contact-sheet.png`, `index.json`, and `meme-writer.md`. The index records
photo hashes and measurements, every candidate's text, layout, regions,
score, warnings, renderer box coordinates, and alt text. The contact sheet
labels each candidate with its ID and includes every candidate in its index.
`pick` re-renders `finished-<id>.png` and records the selection and output
hash. It refuses changed source photos or previously exported files that
have been modified. Source photos stay where they are; keep them available.

`--aspect` sets exact PNG dimensions: `1:1` = 1080×1080, `4:5` = 1080×1350,
`9:16` = 1080×1920, `16:9` = 1200×675. `--fit` frames any photo for that
aspect:

- `auto` (default): crops (`fill`) only when the local face detector ran and
  the crop keeps all of the evidence plus a 3% margin: detected prominent
  faces (head boxes, with room for hair and chin), or, when the detector found
  no face, a measured subject box and only if the crop keeps at least 75% of
  the photo (that crop carries a warning that a missed face could be cut).
  Without the detector, auto never crops. Otherwise `blur`, with a warning
  that says why.
- `fill`: a full-bleed crop positioned on the faces or subject (faces sit a
  little above center). It can cut part of a subject that does not fit; the
  concept then carries a warning.
- `blur`: the whole photo, letterboxed over a blurred, darkened copy of
  itself, so no frame area is dead.
- `contain`: the whole photo with dark bars (the previous default).
- `cover`: a centered crop that ignores faces.

The index records each concept's resolved `fit` and `focus` box, and the
contact sheet labels each cell with layout, framing, and photo filename
(wrapped onto more lines when long, never cut off).
`--layout auto` chooses a separate caption bar when sampled
edge density is high, classic top/bottom text when those bands are clear,
or labels when supplied regions/template metadata call for them. You can
also request `classic`, `caption`, or `labels` directly. Placement checks
the text boxes against protected regions and other text under the chosen
framing; blocked layouts fall back to a caption bar, with a warning. More
than three label slots require safe regions because the caption bar supports
at most three.

With `myzing[layout]` and the verified cached YuNet model, Zing detects face
boxes locally and pads them by 2.5% on each side. Faces smaller than a
quarter of the largest face (or 5% of the photo height) are background:
they never steer a crop, but text still avoids them when they stay in frame.
Without a prominent face, a local color-distinctness estimate (not
recognition) supplies the subject box; a flat or uniformly busy photo has
none. It never downloads the
model while generating concepts. To provision it explicitly, run
`zing layout fetch-model`. Without the runtime/model, or if detection
fails, Zing reports an unknown face count and keeps text off the central 60%
of the source image as a heuristic, and `auto` blur-fills instead of
cropping (a subject estimate can sit beside a face it cannot see). This can
miss faces elsewhere. Text avoids faces only; pets and objects are not
protected. Inspect placement before sharing, even when detection is available.

The photo inventory reads one folder, without recursion or links. It accepts
single-frame JPEG, PNG, WebP, BMP, TIFF, and HEIC/HEIF; other extensions are
ignored. Limits: 64 supported files, 64 MiB per photo, 256 MiB combined, and
4096 folder entries; decoding is bounded as described in "HEIC and very large
photos" below. Invalid supported files are reported as errors. Byte-identical
photos are deduplicated. Orientation follows EXIF (HEIF: its rotation and
mirror properties). No photo, description, or topic is sent anywhere.

### HEIC and very large photos

Every photo is decoded once into a working copy at most 4096 pixels on its
long side, in display orientation, before face/subject analysis and rendering
(outputs are at most 1920 pixels wide). A 50-megapixel phone JPEG is decoded
at a reduced JPEG scale and never needs a full-size bitmap. The decode bound
is explicit: at most 120 megapixels and 16384 pixels per side; larger photos
are refused with "resize it first". Pillow's decompression-bomb warning is
replaced by that bound, so a 90-megapixel photo no longer crashes. The still
index records each photo's `source` (`original` and `working` sizes,
megapixels, decoder, orientation source), its description names both sizes,
and `meme render` returns the same `source` object plus a warning line when a
photo was reduced.

HEIC/HEIF photos are decoded by the installed FFmpeg (extension `.heic`,
`.heif`, `.hif`, or a HEIF `ftyp` brand on a renamed file). FFmpeg 8.1.2
reads single images, phone-style tile grids and HEIF rotation; FFmpeg 6.1.1
cannot read HEIF image items. Then the command stops with the FFmpeg version
and the remedy: convert the photo to JPEG or PNG, or put FFmpeg 7.1 or newer
first on PATH. `zing doctor` reports HEIC support (`heic`) by probing a tiny
HEIF header, without an encoder or sample photo. Zing adds no HEIC library:
pillow-heif wheels bundle the GPL x265 encoder. Color profiles (for example
Display P3) are not converted; colors are read as stored.

### Better lines from your own AI

The command prints and saves the existing meme-writer prompt with your
topic and locally computed orientation, sampled dominant colors, and face
count (or unknown). JSON mode includes the prompt as a string. Copy it into
your own AI if you want editorial help. Zing makes no model calls.

Save the returned lines as a local JSON file, then render them:

```json
{"ideas": [
  {"photo": "desk.jpg", "title": "Scope creep", "texts": ["one quick fix", "the sun came up"]},
  {"photo": "desk.jpg", "title": "Wildcard", "texts": ["the bug has tenure now"]}
]}
```

```sh
uv run --frozen zing still --photos ./photos --topic "one quick bug fix" --lines ./lines.json --out ./rewritten --json
```

Use a filename or photo ID from the index. Omit `photo` to distribute ideas
across the selected photos. A top-level array is also accepted. The file's
1–8 ideas replace `--n`; the same 70-character box cap, 110-character total
cap, beat limits, and filler checks apply. Invalid or duplicate captions
fail before output publication. Optional `regions` use normalized source
coordinates `[x,y,width,height]`, one per text slot. An optional `template`
ID supplies local catalog regions only; it never replaces or downloads the
photo. `title` and `why` are optional strings. Alt text is generated from
measured photo properties and the rendered caption text. Subject details
remain explicitly unknown; this is a limited literal description, not
semantic image recognition or a claim that no undetected faces exist.

```sh
uv run --frozen zing still pick ./stills --id still-0123456789abcdef --video
uv run --frozen zing still pick ./stills --id still-0123456789abcdef --gif --json
```

These reuse the existing animated renderer: five-second MP4, with `--gif`
also producing a companion GIF. They keep the concept's framing (the same
fill crop, or the blurred background). Text remains fixed and no zoom is applied.
FFmpeg and ffprobe are required. MP4 sizes follow the animated-meme rules
below, including 1200×676 for `16:9`; GIFs are capped at 640 pixels wide and
10 fps. Each PNG, MP4, GIF, and contact-sheet entry has alt text in the index.

MCP `still_concepts(photos, topic, out, n=6, aspect="1:1", layout="auto", lines=None)`
returns the index path, summary, writer prompt, and contact-sheet path. It
always uses `fit` `auto`; use the CLI for another framing.
`still_render(out_folder, concept_id, video=False, gif=False)` renders a
selection. Both return paths and metadata, never inline media bytes.

## Individual memes

Render your photo with text written by you or your AI:

```sh
uv sync --extra memes  # from the source checkout
uv run --frozen zing meme ideas --topic "one quick bug fix" --n 6
uv run --frozen zing meme check --text "one quick fix" --text "six hours later"
uv run --frozen zing meme render --image desk.jpg --text "one quick fix" --text "six hours later" --out meme.png
```

Zing makes no model calls. Ideas are seeded formula substitutions; your AI
writes and judges the joke using `zing prompt meme-writer` or MCP
`get_prompt("meme-writer")`. A topic phrased as a situation ("when the build
finally passes", "when you commit", "the deploy failed") gets situation
formulas: the photo is the reaction, so lines read "when you commit" or "pov:
the build finally passes / nobody move"; the subject after "when" is kept. A
wh-clause ("how it works", "why the build broke") is used as a noun: "me
explaining how it works". Other topics are treated as a thing; tasks and "how
to ..." become gerunds with standard spelling ("fix the flaky test" reads
"fixing the flaky test", "commit" "committing", "be on call" "being on call").
Topics longer than 40 characters are shortened at a clause break or a word,
never mid-word and never with an ellipsis. `zing doctor` reports the optional `pillow`
dependency. Templates, ideas, and checks work without Pillow.

```sh
uv run --frozen zing meme templates --search drake --json
uv run --frozen zing meme ideas --topic "release day" --template drake --json
uv run --frozen zing meme render --template drake --text "one more meeting" --text "ship it" --aspect original --out drake.png
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
pixels wide, retaining the source ratio). Photos are decoded as described in
"HEIC and very large photos"; output images are limited to 40 megapixels.
The still `render` command uses the first frame of animated inputs; use
`render-video` to keep motion.

- `--layout classic`: outlined Anton text at the top and bottom edges, in
  capitals. The outline is 8% of the font size, so it holds on bright skies.
- `--layout caption`: a white caption bar with IBM Plex Sans above the photo.
  Every beat uses one size, and the bar is only as tall as its text (at most
  26% of the height), leaving the rest to the photo. Lines are balanced and
  avoid ending on a short word like "the".
- `--layout labels`: text on normalized source-image regions. Pass
  `--regions '[[0.05,0.4,0.3,0.2],[0.65,0.4,0.3,0.2]]'` for custom placement.
  Templates default to their catalog regions; some use generic rows and
  return a placement warning.

Photos default to `--fit auto` (see "Photos and a topic": `fill`, `blur`,
`contain`, or `cover`); templates default to `contain` to retain all panels.
For `auto` and `fill`, `meme render` uses the cached YuNet model when
installed (never a download); without it `auto` blur-fills and the result
carries a warning. JSON reports the resolved
`fit`, `focus` (the kept box, margin included), and `focus_basis`. Labels follow the source through crop and scaling. `--plate`,
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
uv run --frozen zing meme render-video --video reaction.mp4 --start 2 --end 6 --text "one quick fix" --text "six hours later" --at 0 --at 1.5 --gif --out reaction-meme.mp4
```

Install `myzing[memes]` and put FFmpeg and ffprobe on PATH. Animated rendering
stays offline, including template selection: a catalog blank must already
be cached, or you can supply it as a local `--image`.

`--start` and `--end` are source seconds. The selected interval must be at
most 30 seconds; longer sources require an explicit trim. `--max-duration`
can lower that limit. Missing or invalid durations, unsupported containers,
files above 500 MiB, and videos above 8192 pixels on either axis or 40
megapixels are refused before encoding. Still images (`--image`, cached
blanks) use the photo decoder above, including HEIC and large photos.
Supported containers are MP4/MOV, Matroska/WebM, AVI, MPEG/TS, and GIF; the
installed FFmpeg must support their codecs. URLs, network shares, and playlist
inputs are refused.

The `classic`, `caption`, and `labels` layouts use the still renderer's text
caps, fonts, wrapping, plates, shadows, rotation, and framing. `--fit` is
`cover` (default), `contain`, or `blur` (the whole frame over a blurred,
darkened copy of itself, useful for vertical clips in a 16:9 frame); face
detection does not run on video. Caption mode keeps a white bar above the footage. Pillow rasterizes each
text box once to a transparent PNG; FFmpeg composites those layers over the
motion. Labels stay at their output positions; they do not track subjects.

`--at` sets when text appears; `--until` sets its inclusive end. Repeat either
option once per supplied `--text`, in the same order, including empty slots.
Times are relative to the trimmed output. Omitted starts default to zero;
omitted ends default to the output duration. Each window must satisfy
`0 <= at < until <= duration`. Changes land on the next output frame.

```sh
uv run --frozen zing meme render-video --video reaction.gif --text "setup" --text "payoff" --at 0 --at 1.5 --until 1 --until 3 --end 3 --out timed.mp4
uv run --frozen zing meme render-video --image template.png --text "still waiting" --duration 5 --zoom 0.1 --out slow-zoom.mp4
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
