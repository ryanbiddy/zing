# CLI recipes and dependencies

Run from the installed environment. In a checkout, use `uv run --frozen zing`
instead of bare `zing`. Paths below are examples to replace with actual local
paths; `SOURCE_SLUG` and `REFERENCE_SLUG` must come from study results. Use a
fresh output directory. JSON is UTF-8 without a BOM; on Windows, prefer files
over nested JSON in native-command arguments.

## Choose a command

| Command | Use and boundary |
|---|---|
| `zing doctor` | Dependencies, caches and optional local Uoink health; ready can coexist with absent extras. |
| `zing setup --list` | List curated packs; interactive setup can study/download references. |
| `zing explain` | Explain a local video as a style card; `--out DIR`, optional `--against VIDEO`. Offline models; URL downloads require explicit `--allow-download`. See [Explain](explain.md). |
| `zing study` | Measure a URL/local video; `--raw` adds raw-footage evidence; `--transitions` enables v6. |
| `zing fonts` | List/fetch the pinned font library or rank candidates from saved caption geometry; matching stays offline. |
| `zing project` | Init, scan, status, find-reference, resolve-reference and study-reference; verified local reuse without web fallback. |
| `zing brief` | New/show; save interview answers after project init, not an automatic director. |
| `zing plan choose` | Choose A/B/C from a local artifact; durable receipt, optional reference citation with --share-choice; never publishes. |
| `zing match` | Reference + clip folder to three rendered, decoded, inspected drafts and measured reports; resumable, with named failures/shortages. |
| `zing prompt` | Print study, compare, direct, taste or meme-writer judgment instructions. |
| `zing profile` | Build/show measured aggregates; pack can study missing references. |
| `zing assemble` | One studied source plus chosen keepers → draft-edl.json. |
| `zing plan drafts` | Project-wide studies, saved brief and recipe → three distinct Composition v2 plans, comparison, and supported v1 derivatives; named shortage if no trio is found. |
| `zing render` | EDL → MP4 using FFmpeg/libass; optional voiceover is separate. |
| `zing layout` | Explicit model fetching or standalone caption geometry plan. |
| `zing color` | Match SDR distribution → recipe/LUT/preview; apply LUT → derived video. |
| `zing music check` | Rate supplied local music for a brief or plan. No downloads; requires the audio extra. |
| `zing audio` | Analyze local audio/video → observations; does not change the mix. |
| `zing thumbs` | Thumbnail candidates for a studied slug. |
| `zing inspect` | Timeline PNG with aligned frames/waveform/available timed text. |
| `zing meme` | Template metadata, formula ideas, text checks, still rendering and MP4/GIF animation. |
| `zing still` | Photo folder + topic to concepts, contact sheet and JSON index; `pick` exports an indexed selection. No model calls or uploads. |
| `zing serve-mcp` | Local stdio server; `--print-config` prints client setup. |

## Match a reference

```sh
zing match reference.mp4 --clips ./clips --out ./zing-workspace/match --brief brief.json --drafts 3 --seed 18
zing match reference.mp4 --clips ./clips --out ./zing-workspace/match --resume --json
zing plan choose ./zing-workspace/match --draft B
```

Use `--answers` for a JSON object of brief answers. With no supplied brief, a
terminal runs the interview; scripts must supply answers or resume a saved brief.
URLs require `--allow-download` after acquisition consent. `uoink:<id>` reuses
verified retained media without URL fallback. Models are local-only.

Review `comparison.md`/`.json`, `drafts/plan-A.json`, `drafts/draft-A.mp4`,
`drafts/draft-A.png`, and `drafts/draft-A.match.json` (likewise B/C), plus
`recipe.json`. Ready means rendered, fully decoded, inspected and reported.
Read the actual ready count, named failures/logs, director shortages, and
pass/approximate/miss dimensions. Match grades measure the rendered file;
caption sampling and unpaired color statistics cannot certify exact fidelity.

Resume reuses checksum-valid measurements and artifacts. Ctrl+C stops owned child
jobs and preserves checkpoints. Missing layout/model support uses disclosed
position defaults; missing color support leaves ungraded footage. The current
director emits cuts with warnings about unreconstructed reference effects.

## Individual study and assembly

```sh
zing study reference.mp4 --workspace /absolute/workspace --transitions
zing project init --reference reference.mp4 --clips ./clips --out ./project
zing project scan ./project
zing project status ./project --json
zing brief new ./project
zing brief show ./project --json
zing study clips/take.mp4 --workspace /absolute/workspace --raw
zing profile build reference-style REFERENCE_SLUG --workspace /absolute/workspace
zing prompt direct
zing assemble SOURCE_SLUG --direction direction.json --workspace /absolute/workspace
zing render /absolute/workspace/breakdowns/SOURCE_SLUG/draft-edl.json -o ./draft-01.mp4 --keep-work ./render-work-01
zing thumbs SOURCE_SLUG --workspace /absolute/workspace
```

For noninteractive brief import use `zing brief new ./project --brief brief.json`.
It accepts the complete version 1 brief; `--answers` instead takes a JSON object
of answers and fills omitted defaults. Neither selects footage. Init already
scans; another scan updates changed files. To attach a reference study explicitly,
run `zing project resolve-reference ./project`, then
`zing project study-reference ./project`. For an offline peer, supply
`zing project resolve-reference ./project --file reference.mp4`.

`zing project find-reference "soft cuts"` lists candidates only when the peer
advertises `uoink.corpus.read/1`. Choose an existing draft with
`zing plan choose ./project --draft A --draft-file draft-edl.json`.
Without an explicit file, the command reads `./project/drafts/A.json`, falling
back to `plan-A.json` (likewise B/C), as written by plan drafts and match.
Add --share-choice only when the user asks to share the reference citation;
retrying with that flag preserves the event identity. Choice details stay local.

The smallest direction consumed by assembly is a keepers object:

```json
{"keepers":[{"start":0,"end":2,"why":"Chosen opening"},{"start":4,"end":6,"why":"Chosen payoff"}]}
```

For project-wide alternatives, study clips into the project workspace (or
the current ZING_HOME), then run:

```sh
zing plan drafts ./project --recipe ./recipe.json --seed 17 --out ./draft-plans
```

The output includes plan-A/B/C.json and comparison.json. It also includes v1 EDL
derivatives when rendering instructions can be represented without loss. Read
the comparison before rendering; a shortage removes the earlier owned trio.

These are chosen **source seconds**; replace them with valid spans in measured
footage. This minimal object is for assembly only, not the full direct-judgment
contract required by MCP `save_judgment`. Read the `direct` prompt for that.
Assembly retains source audio and derives captions from available timed words.
The brief's caption preferences are not automatically applied. Do not invent
words when transcription is absent. Authored titles must be labeled as authored.

## Treatment artifacts

```sh
zing color match --reference reference.mp4 --clip take.mp4 --out ./look-01
zing color apply --lut ./look-01/look.cube --in take.mp4 --out ./graded-01.mp4
zing audio analyze take.mp4 --json
zing layout captions --video draft-01.mp4 --events events.json --platform reels --out layout-01.json
```

Layout requires the verified cached YuNet model. After download consent only,
`zing layout fetch-model --workspace /absolute/workspace` fetches it. Set
`ZING_HOME` consistently or pass the same `--workspace` to captions.
An events file can be:

```json
{"version":1,"events":[{"id":"title","start":0.2,"end":1.8,"width":0.55,"height":0.15,"preferred_anchor":"lower-third"}]}
```

Times refer to the supplied video's first frame. Box fractions include all visible
caption extents. Review `layout-01.contact.png` and `events[].overlap.safe`.
This plan does not alter the EDL. Color apply preserves/copies audio but encodes
4:4:4 H.264; test playback compatibility. Grade sources before new caption layers.

## Review

```sh
zing inspect timeline draft-01.mp4 --edl draft-edl.json --out cuts-01.png
zing inspect timeline draft-01.mp4 --edl draft-edl.json --around 2 --radius 0.5 --out cut-2.png
zing inspect timeline draft-01.mp4 --start 0 --end 3 --out opening.png
ffprobe -v error -show_streams -show_format draft-01.mp4
ffmpeg -hide_banner -loglevel error -i draft-01.mp4 -f null -
```

The EDL must match the rendered video. Mapping for a unity-speed v1 clip:
`source_time = src_in + output_time - timeline_start`. At a cut, the boundary
belongs to the incoming clip. A no-range EDL inspection centers rows on internal
cuts; range options use output seconds. Word bars need EDL words or a matching
breakdown. Phrase-only captions are shown as phrase intervals; they do not
establish word timestamps.

## Stills

For photo-folder concepts and a saved selection:

```sh
zing still --photos ./photos --topic "release day" --out ./stills --workspace /absolute/workspace
zing still pick ./stills --id CONCEPT_ID --workspace /absolute/workspace
```

Use an ID returned by the first command. Both forms accept `--json`; workspace
selection controls cached models and assets, while `--out` names the output folder.
`--aspect` is 1:1, 4:5, 9:16 or 16:9. `--fit auto` (default) crops to fill the
frame only when the face detector ran and detected faces (or, with none, a
measured subject in a crop keeping 75% of the photo) fit with margin; else it
blur-fills and warns why. Without `zing layout fetch-model` it never crops; `fill`, `blur`, `contain`
(letterbox) and `cover` (centered crop) force one framing. `meme render` takes
the same `--fit` values; `meme render-video` takes `cover`, `contain` or `blur`.

For individual memes:

```sh
zing meme templates --search drake --json
zing meme ideas --topic "release day" --template drake --json
zing prompt meme-writer
zing meme check --text "ONE QUICK TEST" --text "TWELVE OUTPUT FILES"
zing meme render --image frame.png --text "ONE QUICK TEST" --text "TWELVE OUTPUT FILES" --aspect 16:9 --out meme.png --offline
```

Each box allows 70 characters; all boxes together allow 110. Repeat `--text` in
box order; an empty string preserves a slot. `check` returns exit 1 for invalid
copy; JSON `ok` means the check ran, while `valid` says whether copy passed.
Layouts are classic, caption and labels. `--regions` for labels uses normalized
source-image `[x,y,width,height]` boxes. Choose a font covering the requested script.
`--template` fetches a blank on cache miss unless `--offline` is set. Catalog
lookup itself stays offline. Existing still outputs require `--overwrite`;
prefer a new filename instead of enabling it.

## Animated memes

`zing meme render-video` puts the same layouts on a short video or GIF, or on a
still with a slow zoom. Text is rendered once and composited by FFmpeg; source
audio is kept as AAC. Timed captions appear at `--at` seconds (and optionally end
at `--until`).

```sh
zing meme render-video --video clip.mp4 --text "when the build passes" --at 0 --text "on the first try" --at 1.5 --aspect 9:16 --out meme.mp4 --gif
zing meme render-video --image photo.jpg --text "one quick fix" --zoom 0.09 --duration 4 --out meme-zoom.mp4
```

Inputs are trimmed with `--start`/`--end` and capped by `--max-duration`
(default 30 s); `--gif` adds a bounded GIF (10 fps, 640 px, 8 s by default).
Existing outputs need `--overwrite`. MCP: `meme_render_video` (paths out, never
bytes). Only the first audio stream is kept.

## Caption geometry and font candidates

```sh
zing study reference.mp4 --caption-geometry --fonts
zing fonts list
zing fonts fetch --all   # explicit download of the pinned OFL/Apache library; ask first
zing fonts match <slug>
```

Geometry writes caption-geometry.json beside the breakdown. Font matching ranks
library fonts per caption track; results below the calibrated threshold are
labeled substitutes. Failures become warnings and never abort the study.

## Installation and offline limits

From a source checkout, `uv sync --all-extras` installs the Python extras, not
FFmpeg, speech/face models, Kokoro or HyperFrames. Core is stdlib-only. To install
only selected extras use uv's `--extra` with the names below. Package installation
itself may use the network; ask first when not already authorized.

| Extra | Enables |
|---|---|
| study | yt-dlp, scene detection, faster-whisper and RapidOCR; model/URL fetching is separate. |
| mcp | MCP SDK stdio server. |
| render | pysubs2 for ASS captions. |
| memes | Pillow for stills and timeline inspection. |
| fonts | Pillow and pinned headless OpenCV for font comparison; expanded font assets need an explicit fetch. |
| layout | Pinned headless OpenCV; explicit MIT YuNet model fetch still required. |
| color | NumPy for SDR look matching. |
| audio | NumPy for audio measurements. |
| all | All feature extras above. |
| dev | pytest, MCP and render support for development. |

Prefer uv's combined checkout install: its exclusion prevents overlapping GUI
and headless OpenCV wheels. Plain pip does not honor that exclusion.
The default Whisper model is large-v2 (about 3.1 GB); `ZING_WHISPER_MODEL` selects
another model or existing local model directory. RapidOCR may acquire missing
weights too. Do not run an uncached study as an offline operation.
Kokoro runtime/assets, OpenTimelineIO, and the pinned HyperFrames Node/browser/font
sidecar require separate setup and are not installed by all-extras. The v2
renderer composites HyperFrames captions with footage and audio; standalone
sidecar output is silent. Cloud ElevenLabs is outside this local workflow.
