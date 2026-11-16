# Write a story

Write `story.json` for the user's topic. Aim for about eight beats that a voice
can read in under a minute. Choose a look for the video: paper puppets,
large words, taped photos or a comic page. All have generated credits.
There is no footage. Zing makes no research or writing model calls.

Start with `zing story new <dir> --topic "..." --look cutout|headline|scrapbook|comic` if the
folder does not exist. Choose one look name. The panel-look starters have an
invented cast and a source marked `Replace this source`; the placeholder
blocks build. The `headline` starter is a small fictional example with no
panels that passes `check`. Replace the sample lines and source for every
look. Never turn invented details into claims about real people.

Read the sources first. Use only facts supported by a source in `sources`.
Never invent quotes. If sources disagree on a detail, leave it out or state
the uncertainty in plain words. Do not guess. Put a hook in the first line,
one idea in each beat, and a kicker in the last. In panel looks, cards must carry
the facts for someone watching with sound off. Use plain words and no em dashes.

Write the story, run `zing story check <dir> --json`, fix every problem, and repeat
until it passes. Then make narration and review stills. A passing check tests
the file and its limits, not whether the reporting is true or the art looks good.
For `cutout` without a `--look` flag, JSON check returns a list of
`{path, message}` objects, or `[]` when clear. For another look or an explicit
`--look`, it returns `look`, `problems`, `warnings` and `notes`; each message
has `path` and `message`. Warnings and notes do not fail the check.
Use `zing story heads <dir> --sheet` to review portraits and any cut heads.
Use `zing story images <dir> --sheet` to review picture props.
Then use `zing story render <dir> --stills 1,3,5` to inspect the layout,
and `zing story build <dir>` for the video and receipt. Listen to the result
and inspect the captions before handing it over for posting.

## Choose a look

Use `headline` for a claim, numbers or a quick explainer, and when there is no
good photo. Use `cutout` for people doing things in places. Choose `scrapbook`
for stories told through pictures and documents, or when a face photo is hard
to cut. Choose `comic` for a sequence of events with a punchline. Vary looks
across a series. Set `look` in the file; `check`, `heads`, `render` and `build` also accept
`--look NAME` for a run without rewriting the file. An omitted look means
`cutout`.

`cutout`, `scrapbook` and `comic` share the same directed `panels`, with sets,
props, actors and cards. You can re-render the same story with any of them.
Keep the caption band clear and run `check --look NAME` after switching.
Before rendering comic from a portrait-only story, run
`zing story heads <dir> --look comic --sheet` to prepare its cut heads.
`build --look comic` handles that step too.

`scrapbook` turns actors into taped 340x420 photo cards with square portraits
and their names below. A standing card starts at y=640, centred on actor `x`.
Actor `scale` uses the card's bottom centre; `y` applies the usual offset.
`flip` and `head_scale` are ignored; `head` and `head_at` choose portraits.
Poses lean, rock or hop, and the camera moves down the paper. The wall colour
and pattern cover the page; a torn floor-colour strip starts at y=1500.
`heads` needs portraits only, with no background removal. `check` uses the
picture card's box instead of a puppet head.

`comic` puts cutout panels in bordered frames, two across with staggered rows.
The camera opens on the whole page for 0.45 seconds, then pushes in and travels
frame to frame at 0.9 scale with alternating small tilts. Halftone dots and
grain give it a print feel. Chapters use yellow boxes at the top left of the
current frame; chips and spoken captions stay full size on screen. Keep
directing in panel coordinates. This look needs cut heads, as `cutout` does.
The camera stays close on the end card so its credits remain readable.

If a cut warns about a leaking background, render with `--look scrapbook` or
`--look headline`, which use the photo as it is.

## Headline

This look reads `beats`, cast names in line `text`, image `keywords`, and
`sources`. It has no layout to author. Omit `panels`; any supplied panels,
including an outro, are ignored and reported as a note. `captions` is ignored:
the large type is the caption. Panel, overlap and caption-band checks do not
apply, but script, source, rights and timing checks still do.

Write short lines, one idea each. Put the number in the line so it takes the
accent colour. More than 16 words gets a warning; 22 is still the hard limit.
Words pop in as they are spoken and hold until the next line starts.

A cast member's full, first or last name in `text` brings in their portrait
badge for the rest of the beat. Matching ignores case and uses whole words;
`say` does not trigger it. No photo gives an honest circle with initials and
`no photo`. Two named people share the lower area, with the later one larger.
`heads` makes square portraits only for this look, without cutting a head.

An image's `keywords`, such as `["elephant", "elephants"]`, bring it in when
a line contains a match. Without keywords, its ID supplies words of at least
three letters, split on `-` and `_`. A simple plural also matches. Pictures
keep their `photo` or `sticker` cut and stay until the beat ends.

Colours cycle through `ink`, `yellow`, `tomato`, `cream`, `teal` and `blue`.
A beat can choose one with `"color": "teal"`. Each beat gets its chapter above
the type. The generated end card uses a full-width credits card, the
`made with zing` sticker and the first cast member's badge if they have a photo.

## JSON contract

Top-level fields:

- `schema_version`: optional `1`.
- `look`: optional `cutout` (default), `headline`, `scrapbook` or `comic`.
- `slug`: optional local identifier, starting with a lowercase letter and using lowercase letters, numbers, underscores and hyphens, at most 60 characters. Beat IDs and cast IDs use the same rule.
- `topic`: required string, at most 60 characters. The top-left bar says `zing · <topic>`.
- `handle`: optional string, at most 40 characters. Empty hides the right label.
- `cast`: optional object keyed by unique cast IDs. Omit it or use `{}` for no actors.
- `images`: optional object keyed by image IDs, each `{path, credit, license, source_url, cut}`. IDs follow the cast ID rule. `cut` is `photo` by default or `sticker`; optional `box: [x,y,width,height]` sets a sticker's subject rectangle in the source image. Optional `keywords` is a list of words or phrases that trigger the picture in `headline`.
- `beats`: ordered list of 4 to 14 beats.
- `panels`: required ordered list of paper sets for `cutout`, `scrapbook` and `comic`. The first starts at the first beat. Optional and ignored for `headline`.
- `sources`: at least one object with `title` (at most 100 characters) and an HTTP or HTTPS `url`.
- `outro`: end-card seconds, 1 to 30, default 3.2.
- `captions`: boolean, default true. In panel looks, reserve x=0..1080, y=1560..1720 for the caption strip. Ignored in `headline`.
- `sfx`: boolean, default true. Synthesized whooshes, pops and stamp thuds stay below the voice. `--no-sfx` on render or build also turns them off.
- `music`: optional `{path, credit, license, source_url}` for a supplied local file inside the story folder. Use the photo rights rules: no NC, ND, unknown or editorial-only licenses. Never invent music rights. Music loops or trims to length, fades at both ends and ducks under speech. Its credit goes on the end card and receipt. No music ships with Zing.

Do not add unused fields such as `title`, `credits` or a beat's `set`.
Unknown fields are errors. Set and cast colors use hex notation such as
`#FFD21F`; a headline beat's `color` uses a palette name.

Each cast member has `name` (at most 60 characters), optional colors `skin`,
`jacket`, `shirt`, `legs`, and
optional `photos`. A photo has `path`, `credit`, `license`, `source_url`, and
optional `face: [x, y, width, height]`. `path` is at most 240 characters,
`credit` 120, and `license` 100. Paths are local and relative to the
story folder, and must stay inside it. Use supplied photos with cleared or
attribution rights, or fetch a licensed Commons file. No NC, ND or editorial-only photos.
Never invent a credit or license. A cast member with no photo gets a paper
head with initials in `cutout`, or an initials badge in `headline`. Do not
supply `heads` or `portraits`; `zing story heads` makes them. Each portrait
is a 600x600 face crop. An explicit `face` lets Pillow make it without OpenCV.

Show the subject of the story. If no drawn prop fits, use a licensed image:
`zing story find "elephant" --limit 6 --json` lists Commons candidates,
including refusals and their reasons. Choose a suitable accepted file, then
`zing story fetch <dir> "File:Chosen file.jpg" --as image:elephant` downloads
it and saves its actual rights in `images.elephant`. `--as photo:<cast-id>`
adds a cast photo instead. Fetch refuses missing authors, missing licenses
and non-Commons hosts. Never fill missing metadata with a guess.
`check`, `heads`, `images` and `render` never use the network. `find` and
`fetch` use the network for Wikimedia Commons only. `voice` and `build`
use the network only when the chosen provider is an online one. Kokoro
and supplied lines stay local. Review the source and the sheet.

Each beat has a unique `id`, optional `chapter` (at most 40 characters),
1 to 8 `lines`, optional headline `color`, and optional
`tail` in seconds (default 0.3). Reserve the ID `outro`. Each line has `text`,
optional `say` for pronunciation, and optional `gap` in seconds (default 0.16).
Both versions of a line must be at most 22 words; both narration totals must
be at most 160 words. Each text field is also at most 300 characters.
`say` reaches every synthetic voice provider and changes speech only. Use it
to spell out an awkward name or date; keep `text` readable for captions.
In `cutout`, captions show up to four words at a time, in the bundled ZingCaption font,
with the current word in yellow. Words divide each line's audio time evenly,
so inspect and listen rather than assuming forced alignment.
Gaps and tails run from 0 to 5 seconds.
The page makes a chapter pill from each nonempty `chapter` during its beat.

A `cutout` panel has `from`, `set`, and optional lists `props`, `actors`, `cards`.
`from` must be an exact beat ID or `outro`. Panels begin in beat order, and
last until the next panel begins. Every beat must belong to a panel. Reuse
a set across related beats; do not move the camera for every sentence.

`set` has optional `wall` and `floor` colors, `pattern` (`tiles`, `stripes`,
`check`) and `floor_pattern` (`check`, `planks`). No pattern means plain paper.
There are no named set presets. A kitchen can combine tiles, sink, plates
and bubbles; an office can use stripes, crt and a calendar; a diner can use
a booth, table, cups and pancakes; outdoors can use a window, tree or skyline.

## Cutout cues

Times are finite seconds or named cues: `beat`, `beat:line`,
`beat:line:fraction`, `outro`. Line numbers start at zero. Fractions run from
0 to 1 across a line's speech. Any named cue can add an offset in seconds:
`hook+0.2`, `hook:0:0.5-0.2`, `outro+0.6`. The legacy colon offset form
`hook:0:-0.2` means 0.2 seconds before line zero. Prefer the other forms
when writing new files. Panel `from` is an exact beat ID, not a general cue.

## Cutout props and actors

Props: `blob`, `dots`, `window`, `skyline`, `lamp`, `sink`, `plates`, `bubbles`,
`crt`, `calendar`, `cube`, `chip`, `cup`, `pancakes`, `booth`, `table`,
`garage`, `tree`, `cross`, `star`, `image`.

Every prop has `prop`, `x`, `y`. Optional fields are `scale`, `rot`, `at`,
`until`, `anim`, `still`, `front`, `spin`. Coordinates use its base center.
`front` is a boolean layer flag. `still` stops the wobble. `spin` is the
rotation step. Prop entry animations are `pop` and `drop`.

Prop-specific fields:

- `blob`: radius `r`, color `fill`.
- `dots`: grid count `n`, spacing `gap`, radius `dot`, boolean `round`, `opacity`, `fill`.
- `window`: boolean `night`, default true.
- `skyline`: building color `fill`, window color `lit`.
- `lamp`: cord length `drop`, color `fill`.
- `plates`, `pancakes`: count `n`.
- `calendar`: short `text`.
- `cube`: color `stroke`.
- `booth`: colors `seat`, `seat2`.
- `table`: front height `leg`, front color `bench`. Do not put a color in `front`.
- `star`: color `fill`.
- `image`: an `image` ID from the top-level object and `w` in pixels, from 80 to 1000. Example: `{"prop":"image","image":"elephant","x":780,"y":1400,"w":360}`. `cut: "photo"` adds white paper, shadow and tape and needs only FFmpeg. `cut: "sticker"` uses OpenCV GrabCut, a center rectangle or the supplied box, and a faceted white edge. It needs the same OpenCV and NumPy install as heads. All normal prop timing, layer and transform fields work.

Actors have `who` (a cast ID), `x`, optional `y`, `scale`, `flip`, `pose`,
`head`, `head_scale`, `enter`, `moves`, `poses`, `head_at`. `head` is a zero-based photo
index. `enter` is `walk` or a cue. Movement is
`{ "at": cue, "dur": seconds, "from": x, "to": x }` in `moves`.
Pose changes are `{ "at": cue, "pose": name }` in `poses`. Head changes
are `{ "at": cue, "head": index }` in `head_at`. `head_scale` runs from 0.1
to 3. Movement durations run from 0.01 to 30 seconds and their x positions
from -1080 to 2160.

Poses: `idle`, `present`, `point`, `up`, `wave`, `think`, `shrug`, `cheer`,
`table`, `carry`, `hip`. Make gestures support the words; leave room to pause.

## Panel cards

Every card has `kind`, `x`, `y`, `at` and the fields for its kind. Coordinates
use its top-left corner and must be inside 1080x1920. Optional common fields:
`until`, `rot`, `anim`, `z`, `size`, `w`, `bg`, `color`, `from` (horizontal
slide distance), `over_head` (boolean, default false).
`anim` is `pop`, `drop`, `stamp` or `slide`.
Scale runs from 0.1 to 5, rotation from -360 to 360 degrees, card size from
16 to 300, width from 80 to 1000, and layer `z` from 0 to 10. Prop opacity
runs from 0 to 1. Dot and stack counts run from 1 to 20; calendar text is
at most 8 characters. Check numeric ranges with `zing story check`.

Character limits include spaces:

| Kind | Fields and maximum characters |
|---|---|
| `sticker` | `text` 32 |
| `pill` | `text` 32 |
| `tag` | `text` 32, `sub` 48 |
| `note` | `text` 90, small heading `k` 40 |
| `sign` | `text` 32, `sub` 40 |
| `doc` | `text` 32, `k` 48, `sub` 40 |
| `stamp` | `text` 24 |
| `plaque` | `text` 48, `sub` 120 |
| `list` | `k` 40; 1 to 5 `rows`, each `{ "text": string up to 32, "at": cue }` |
| `credits` | Generated only, maximum 160 characters per line |

Use short cards. Increasing type size or putting a card near an edge can
still crop it, so inspect the JPEGs. Keep important facts above the puppets
and away from the top bar. A standing actor's head covers about y=650 to
1010; name tags go at y=560 or higher. Allow more room for tall cutouts,
changed `scale` or `head_scale`, and actors at a different `y`, including
seated `table` poses. `check` tests card/head overlap through visible time
windows and moves, and suggests a y that clears the head. Fix every such
error. Before voice exists, checks use placeholders: ten seconds per beat
and one second per line. Run `check` again after `voice` so it uses the real
`timings.json`, especially for numeric cues.
Use `over_head: true` only for a deliberate gag. A stamp gets no
automatic exemption. The check judges where a card settles and allows it to
clip the outer fifth of a head box. More than 60 percent coverage of another visible
card's box is also an error, even with captions off.
Keep all card boxes, actor photo cards and puppet heads above the
caption safe band, x=0..1080 and y=1560..1720. `check` reserves room for
wrapping, rotation and entry overshoot; capture also checks actual bounds.
`captions: false` removes the strip and its clearance rules. The outro has
no spoken captions, so its art can use that band.

Zing adds an outro with photo and image credits and licenses and source titles.
Matching photo and image credits appear once. The default panel-look outro brings the
first cast member with a photo on stage waving. Credits use larger type for
five or fewer lines and sit beside any actor on the outro, clear of heads.
In panel looks, you may supply your own `from: "outro"` panel, but Zing still adds its credits
card. Do not write a credits card yourself. Kokoro and ElevenLabs always add
`narration is an AI voice`; that line cannot be hidden. Supplied WAV lines
use provider `lines`; pass `--synthetic-voice` if those recordings came from
a voice model so the credit remains.

`zing story voice <dir> --provider kokoro|elevenlabs|lines` selects a voice
provider. Otherwise Zing uses `ZING_TTS_PROVIDER`, then Kokoro; `--lines-dir`
selects supplied recordings. Kokoro uses the existing model discovery and
path overrides. ElevenLabs needs the user's configured key and voice ID,
sends spoken text to its service, and can use paid quota. Zing marks its
timings synthetic and keeps the AI voice credit. `ZING_TTS_PROVIDER=elevenlabs`
also selects it for `voice` and `build`. Never ask the user to paste a key
into chat. One clip per line keeps cues tied to the audio.

MCP clients can call `story_new`, `story_check`, `story_build` and
`story_status`. `story_new` accepts optional `look`; `story_build` accepts a
`look` override without rewriting the file. `story_check` reports the look,
problems, warnings and notes. Build runs in the background; poll status for completion or
errors. None of these commands or tools posts the video.
