# Stories

`zing story` turns a short script into a vertical video without source footage.
A voice reads each beat. Choose paper puppets, large words, taped photos or
a comic page. All looks carry source, photo, image and music credits on the
end card and make the narration readable with sound off.

## Make a story

Start a folder and give your agent the bundled writing prompt:

```sh
zing story new ./story --topic "the cardboard moon"
zing story prompt
```

The default `new` writes `story.json` and `README-STORY.txt`. The cast is invented and has
no photos. The draft meets the structure rules, but `check` flags its source
placeholder with `replace this source`. Replace that source and the draft
lines with reporting you have checked. `build` refuses the placeholder.
Existing story files are never overwritten. Zing does not call a model to
research or write a story; the calling agent does that work.

After writing the story, run:

```sh
zing story check ./story --json
zing story voice ./story --voice af_heart --speed 1
zing story heads ./story --sheet
zing story images ./story --sheet
zing story render ./story --stills 1,4,8
zing story render ./story --out ./story/final.mp4
```

`check` prints every problem and exits 1 if it finds any. For `cutout` without
a `--look` flag, `--json` keeps the list of `{ "path": "topic", "message":
"must be non-empty text" }` objects, or `[]` when clear. For another look or an
explicit `--look`, it returns an object with `look`, `problems`, `warnings`
and `notes`. Each of the three lists uses the same path/message objects.
Warnings and notes do not fail the check; plain output prints them too.
`voice` writes `narration.wav` and `timings.json`. `heads` writes square
portraits into `heads/`, plus transparent PNG head stickers for `cutout` and `comic`.
`images` prepares declared pictures in `images/`; its `--sheet` writes
`images/sheet.png`. For heads, `--sheet` adds `heads/sheet.png`, with portraits
and any cut heads labelled by cast ID and photo index. `render` writes a 1080x1920,
30 fps MP4 with narration, captions and sound effects. `--stills`
writes JPEGs for review instead of a video.

To run all steps and write `story-receipt.json`:

```sh
zing story build ./story
zing story build ./story --lines-dir ./recorded-lines --out ./story/final.mp4
```

`build` also accepts `--look`, `--provider`, `--voice`, `--speed`, `--synthetic-voice`
and `--no-sfx`. The default video is `story.mp4`
inside the story folder. The receipt records the look, voice provider and name,
each photo's and image's credit, license and source URL, any music rights, the sources,
output and duration.

Render uses the factory's Node sidecar and FFmpeg discovery. Install Node.js
20 or newer, FFmpeg and Chrome or Edge, then run `zing factory setup` and
`zing factory doctor`. Rendering uses bundled fonts and local files only.
The same time always produces the same frame.

## Looks

Set `"look": "headline"` in `story.json`, or choose it for one run:

```sh
zing story new ./headline-story --topic "the cardboard moon" --look headline
zing story check ./story --look headline --json
zing story render ./story --look headline --stills 1,2,3
zing story build ./story --look headline --lines-dir ./recorded-lines
```

`cutout` is the default when `look` is absent. `--look NAME` on `check`,
`heads`, `render` and `build` overrides the file for that run without rewriting it.
`new --look NAME` writes the choice into the starter. Unknown looks are errors;
the current choices are `cutout`, `headline`, `scrapbook` and `comic`.

| Look | What it needs | What it is good for |
|---|---|---|
| `cutout` | Panels; cut heads for cast photos | People doing things in places |
| `headline` | Beats; portraits for cast photos; no panels or cut heads | Claims, numbers, quick explainers, or no good photo |
| `scrapbook` | Panels; portraits for cast photos; no cut heads | Stories told through pictures and documents, or a face photo that is hard to cut |
| `comic` | Panels; cut heads for cast photos | A sequence of events with a punchline |

Photos are optional in every look. A cast member without one gets initials
and a `no photo` label. Vary looks across a series.

`cutout`, `scrapbook` and `comic` read the same directed `panels`: sets,
props, actors and cards. Switch an existing layout with `--look scrapbook`
or `--look comic`, then check it and review stills. The caption band stays
in the same screen position. All three keep the 12 frames per second stepping.
During the comic overview and both new looks' camera moves, art from the
next panel may pass behind the caption for a moment; the caption keeps its
own ink plate. Once a frame is centred, capture checks its screen boxes for
caption clearance.

When switching a portrait-only story to comic, prepare the cut heads first:

```sh
zing story heads ./story --look comic --sheet
zing story render ./story --look comic --stills 1,2,3
```

`build --look comic` prepares those assets as part of the build.

### Scrapbook

The camera moves down a paper page. Each actor becomes a taped instant photo:
a 250x310 white card, a 222x222 square portrait inset 14 px, and the cast name
in 30 px Instrument Serif italic below it. The card is about the size of a
puppet head, so a layout made for `cutout` stays clear of it. The portrait keeps its background.
`heads` prepares portraits only for this look.

The card is centred on the actor's `x`, with its top at y=720 for a standing
actor. `scale` acts about the actor's feet and `y` adds the same offset, both as
in `cutout`, so the card lands where the puppet's head would be. `flip` and `head_scale` do not change the photo card. `head` and
`head_at` choose portraits from the same photo indices.

Cards have a small stable tilt and paper wobble. Pointing and presenting lean,
thinking leans the other way, shrugging rocks once, and raised arms, cheering
and waving hop. A walking entrance slides in; a timed entrance drops in.
The set's wall colour and pattern fill the sheet, with a torn strip of its
floor colour from y=1500 down. Props and text cards keep their existing art.
`check` uses picture-card bounds in place of puppet heads.

### Comic

Panels sit two across on an off-white page, with staggered rows, ink borders
and gutters. Each frame contains the full cutout set, puppets, props and cards.
Halftone dots and heavier grain give the page a printed texture.

The opening holds the whole page for 0.45 seconds, centred both ways with
at least 40 px of margin on every side, then pushes into the first frame.
This also applies to a single-panel page. Each frame settles at 0.9 scale, centred, with alternating tilts of
-1.2 and +1.2 degrees. A move to the next frame pans and changes tilt together
over 0.8 seconds. Future frames hold their starting state. The camera stays
close for the end card.

Chapters appear in a yellow caption box at the current frame's top left.
The top chips and spoken captions stay full size in screen space. `check`
uses the original panel coordinates; capture checks the visible screen boxes
against the caption band. `heads` prepares cut heads for this look.

### Headline

`headline` reads the beats, cast, images and sources. It needs no layout.
`panels` is optional and ignored, including a supplied outro panel; `check`
reports a note when panels are present. `captions` is ignored too: the big
type is the caption, so there is no caption band or caption clearance check.
Panel and overlap checks do not apply. Script, source, rights and timing
checks still do.

Write short lines with one idea each. Put the number in the line: words with
digits use the accent colour. Lines longer than 16 words get a warning;
the existing 22-word limit still applies. Words appear at evenly spaced
times across the line's audio and keep their place before they appear.
The line stays until the next one starts.

Each beat fills the frame with a flat colour. The cycle is `ink`, `yellow`,
`tomato`, `cream`, `teal`, `blue`; a beat's `"color": "teal"` overrides its
colour. The next block slides up, with motion stepped at 12 frames per
second. The beat's chapter appears above the type with a two-digit number.
The topic and handle stay at the top, and a bar tracks progress at the bottom.

A cast member's full, first or last name in a line's `text` brings in a
round portrait badge. Matches use whole words and ignore case; `say` does
not trigger a badge. The badge stays through the beat. If two people are
named, the later badge is larger and the earlier one shrinks beside it.
A member without a photo gets initials and a `no photo` label.

An image appears when a line contains one of its `keywords`, such as
`"keywords": ["elephant", "elephants"]`. If keywords are absent, Zing splits
the image ID on hyphens and underscores and uses words of at least three
letters. A simple plural also matches: `elephant` matches `elephants`.
Pictures keep their `photo` or `sticker` cut and stay through the beat.
Zing sizes them to clear the badges.

The generated end card uses the next colour, a `made with zing` sticker,
a 900 px credits card and the first cast member's badge if they have a photo.
It keeps the same source, media, music and AI voice credits as `cutout`.
Sound effects follow beat changes and badge or picture arrivals.

Every look fits long end-card credits by reducing the font size in steps to
22 px, then using two columns. If the list still does not fit, it removes
sources from the end of the list and adds `+ N more in the receipt`.
Visible lines stay whole. AI voice, photo, image and music credits stay on
screen, and the receipt keeps every source and credit. Short lists keep
their usual size and position. Credits are never stretched or squashed.

`new --look headline` writes a small fictional example with no panels that
passes `check`. Replace its sample story and source before using it for
reporting. The default `cutout` starter keeps its source placeholder, which
must be replaced before a build.

## Voice setup

Story voice uses Zing's existing TTS providers, with one provider call per
line. `--provider kokoro|elevenlabs|lines` selects one explicitly. Otherwise
Zing uses `ZING_TTS_PROVIDER`, then local Kokoro. Supplying `--lines-dir`
selects `lines`; pairing it with a synthetic provider is an error.

`check`, `heads`, `images` and `render` never use the network. `find` and
`fetch` use the network for Wikimedia Commons only. `voice` and `build`
use the network only when the chosen provider is an online one. Kokoro
and supplied lines stay local.

Kokoro is optional and needs Python 3.11 to 3.13. Install kokoro-onnx in
the environment that runs Zing. It is not part of any Zing extra:

```sh
python -m pip install kokoro-onnx
```

Put `kokoro-v1.0.onnx` and `voices-v1.0.bin` in `ZING_KOKORO_HOME`, or in
`~/.cache/myzing/kokoro` when that variable is unset. `ZING_KOKORO_MODEL` and
`ZING_KOKORO_VOICES` override the individual paths, so differently named model
files still work. Zing does not download either file. The shared Kokoro
default voice is `af_sarah`; `--voice af_heart` keeps the earlier story voice.
`--speed` defaults to `1`. Kokoro runs locally.

ElevenLabs uses the existing `ELEVENLABS_API_KEY` and `ZING_ELEVENLABS_VOICE`
settings. Set those in your environment, then run:

```sh
zing story voice ./story --provider elevenlabs
```

`ZING_TTS_PROVIDER=elevenlabs` also selects it for `voice` and `build`.
`--voice` can pass an ElevenLabs voice ID. This provider sends each line's
spoken text to ElevenLabs and may use paid quota. Story commands do not
print provider keys or service response bodies. Timings are marked synthetic,
and every synthetic provider keeps the `narration is an AI voice` credit.

You can supply recordings instead, with no speech model installed. The
`lines` provider also works on Python 3.14:

```sh
zing story voice ./story --lines-dir ./recorded-lines
```

Name one WAV per line `<beat-id>-<line-index>.wav`, with line indices starting
at zero: `hook-0.wav`, `hook-1.wav`, and so on. Use mono or stereo PCM WAV files
with the same sample rate, channel count and bit depth (8, 16, 24 or 32 bit).
The `lines` provider preserves the recordings and adds the pauses
from the script. `--provider lines` requires `--lines-dir`. `--voice` and
`--speed` apply only to synthetic providers. Pass `--synthetic-voice` when
supplied clips came from a voice model.

Timing starts with 0.35 seconds of silence. Each line has a 0.16 second gap
unless `gap` sets another length. Each beat then has a 0.3 second tail unless
`tail` sets another length. The outro defaults to 3.2 seconds. Times are
recorded to the nearest millisecond. `timings.json` has `duration`,
`outro_start`, `provider`, `voice`, `synthetic`, and `beats`. Each timed beat has `id`,
`start`, `end` and `lines`; each timed line has `text`, `start` and `end`.

## Story contract

Use UTF-8 JSON. Unknown fields are errors, so misspellings cannot silently
change the film. All positions are pixels in a 1080x1920 frame. Colors are
hex colors such as `#FFD21F`, except the named palette colours on headline beats.

| Top-level field | Meaning |
|---|---|
| `schema_version` | Optional, `1`. |
| `slug` | Optional local story identifier. |
| `look` | Optional `cutout` (default), `headline`, `scrapbook` or `comic`. |
| `topic` | Required top-bar label, up to 60 characters. The bar reads `zing · <topic>`. |
| `handle` | Optional right-hand label, up to 40 characters. Empty means no label. |
| `cast` | Optional object keyed by cast ID. Omit it or use `{}` for no puppets. |
| `images` | Optional object keyed by image ID, for licensed pictures. Optional `keywords` trigger them in `headline`. |
| `beats` | Required ordered list of 4 to 14 narration beats. |
| `panels` | Required ordered paper sets for `cutout`, `scrapbook` and `comic`. The first starts at the first beat. Ignored by `headline`. |
| `sources` | Required nonempty list of `{ "title": "Source title", "url": "https://..." }`. Titles are at most 100 characters. URLs must be HTTP or HTTPS. |
| `outro` | Optional end-card duration in seconds, from 1 to 30. Default 3.2. |
| `captions` | Optional boolean, default `true`. Shows the fixed caption band in panel looks. Ignored by `headline`. |
| `sfx` | Optional boolean, default `true`. Adds synthesized paper sounds during render. |
| `music` | Optional local music object with `path`, `credit`, `license`, `source_url`. |

Each cast member has a required `name` (at most 60 characters), optional
`skin`, `jacket`, `shirt` and `legs`
colors, and optional `photos`. Each photo is an object with `path`, `credit`,
`license`, `source_url`, and optional `face: [x, y, width, height]`. Photo paths
are at most 240 characters, credits 120, and licenses 100. Paths are
local files relative to the story folder and must stay inside it. A member
without photos gets initials on a paper head, photo card or portrait badge. Photo indices
start at zero in the order of `photos`; generated heads and portraits are
outputs, not inputs.

A beat has `id`, optional `chapter` (at most 40 characters), 1 to 8 `lines`,
and optional `tail` in seconds. In `headline`, optional `color` chooses one
of the palette names listed above. Beat IDs, cast IDs and slugs start with a
lowercase letter and use lowercase letters, numbers, underscores and hyphens,
up to 60 characters. `outro` is
reserved. A line has required `text`, optional `say` for pronunciation, and
optional `gap` in seconds. `say` changes the spoken words, while `text` remains
the readable version in timings. Both text fields are at most 300 characters.
Line gaps and beat tails must be finite, from 0 to 5 seconds.
Panel looks show each nonempty `chapter` while that beat plays: a bottom pill
in `cutout` and `scrapbook`, or a yellow frame caption in `comic`.

A directed panel has `from`, `set`, and optional `props`, `actors` and `cards` lists.
`from` is an exact beat ID, or `outro` for a custom end panel. It cannot be an
offset or a line cue. Panels start in beat order and last until the next
panel. One panel can cover several beats; every beat must have a panel.

`set` is an object with optional `wall` and `floor` colors, `pattern`
(`tiles`, `stripes` or `check`) and `floor_pattern` (`check` or `planks`).
Omit patterns for plain paper. There are no named scene presets: combine a
set with props to make a kitchen, office, diner, street or garage.

### Cues and movement

A cue is a finite number of seconds, a beat ID, `beat:line`,
`beat:line:fraction`, or `outro`. Line indices start at zero. A fraction is
from 0 to 1 through the line's audio. Add a signed seconds offset to any
named cue: `hook+0.2`, `hook:0:0.5-0.2`, or `outro+0.6`.
The older colon form `hook:0:-0.2` also means 0.2 seconds before that line.
Unknown beats and out-of-range lines are errors.

Props have `prop`, `x`, `y`, and optional `scale`, `rot`, `at`, `until`,
`anim`, `still`, `front` and `spin`. `front: true` places the prop in front
of puppets. `still: true` stops its paper wobble. `spin` sets the rotation
step. Prop origins are their base center. Use `pop` or `drop` for a prop's
entry animation.

Available props: `blob`, `dots`, `window`, `skyline`, `lamp`, `sink`, `plates`,
`bubbles`, `crt`, `calendar`, `cube`, `chip`, `cup`, `pancakes`, `booth`,
`table`, `garage`, `tree`, `cross`, `star`, `image`.

| Prop options | Meaning |
|---|---|
| `blob`: `r`, `fill` | Radius and color. |
| `dots`: `n`, `gap`, `dot`, `round`, `opacity`, `fill` | Grid count, spacing, dot radius, circular clipping, opacity and color. |
| `window`: `night` | Defaults to a night sky; `false` gives daylight. |
| `skyline`: `fill`, `lit` | Building and window colors. |
| `lamp`: `drop`, `fill` | Cord length and shade color. |
| `plates`, `pancakes`: `n` | Number of plates or pancakes. |
| `calendar`: `text` | A short date or year. |
| `cube`: `stroke` | Line color. |
| `booth`: `seat`, `seat2` | Bench and cushion colors. |
| `table`: `leg`, `bench` | Front height and color. `front` always stays a layer flag. |
| `star`: `fill` | Color. |
| `image`: `image`, `w` | Image ID and picture width in pixels, from 80 to 1000. |

### Pictures as props

Use an image prop when the story needs a subject that the drawn props cannot
show. Declare its rights once in `images`, then refer to its ID:

```text
"images": {
  "elephant": {
    "path": "images/elephant-source.jpg",
    "credit": "The actual photographer's credit",
    "license": "CC BY 4.0",
    "source_url": "https://commons.wikimedia.org/wiki/File:Your_chosen_file.jpg",
    "cut": "photo"
  }
}
```

The metadata above shows the fields, not a cleared asset. Use the downloaded
file's actual author and license. Add a prop such as
`{"prop":"image","image":"elephant","x":780,"y":1400,"w":360}`.
Its origin is the bottom center. All normal prop fields work, including
`at`, `until`, `anim`, `rot`, `scale` and `front`.

`cut: "photo"` is the default: a paper photo with a white border, a shadow
and tape. FFmpeg prepares it locally; OpenCV is not needed. `cut: "sticker"`
uses OpenCV GrabCut with a center rectangle, then adds the same faceted
white edge as heads. Optional `box: [x, y, width, height]` sets the subject
rectangle in source-image pixels. The box must leave some background around
it. Review `zing story images <dir> --sheet` after changing the cut or box.
Sticker cuts need the same OpenCV and NumPy install as heads. Every path
must stay inside the story folder; image rights follow the photo rules.

### Find and fetch Commons pictures

```sh
zing story find "elephant" --limit 6
zing story find "elephant" --limit 6 --json
zing story fetch ./story "File:Your chosen file.jpg" --as image:elephant
zing story fetch ./story "https://commons.wikimedia.org/wiki/File:Your_chosen_portrait.jpg" --as photo:mira
```

`find` lists each file's title, license, author credit, pixel dimensions,
byte size and Commons page URL. Refused files stay in the list with a reason.
`fetch` downloads just the selected file into `photos/` or `images/` and
writes its rights into `story.json`. A photo target must name an existing
cast member; an image target creates a new image ID. Downloads are limited
to Commons hosts and the factory's file-size limits. Missing author or
license metadata is a refusal, as are NC, ND and unknown licenses.
Neither command guesses a credit. `find` and `fetch` use the network for
Wikimedia Commons only.

Actors have `who` (a cast ID), `x`, optional `y`, `scale`, `flip`, `pose`,
`head`, `head_scale`, `enter`, `moves`, `poses` and `head_at`. `head_scale`
changes only the head size, from 0.1 to 3. `enter: "walk"` walks onto
the panel; a cue makes the actor appear at that time. `moves` contains
`{ "at": cue, "dur": seconds, "from": x, "to": x }`. `poses` contains
`{ "at": cue, "pose": name }`; `head_at` contains
`{ "at": cue, "head": index }`. Move durations run from 0.01 to 30 seconds;
their x positions can run from -1080 to 2160 for entrances and exits.

Poses: `idle`, `present`, `point`, `up`, `wave`, `think`, `shrug`, `cheer`,
`table`, `carry`, `hip`.

### Cards and limits

Cards have `kind`, `x`, `y`, `at`, and the text fields below. Optional common
fields are `until`, `rot`, `anim`, `z`, `size`, `w`, `bg`, `color`, `from`
and `over_head` (boolean, default false).
`from` is the horizontal slide distance. Animations are `pop`, `drop`,
`stamp` and `slide`. Card positions use the top-left corner and must be
inside the frame: `0 <= x < 1080` and `0 <= y < 1920`. Review stills after changing size,
rotation or placement.

A standing actor's head covers about y=650 to 1010; name tags go at y=560
or higher. Allow more room for a tall cut, a larger `head_scale`, a changed
actor `scale`, or a different actor `y`. Seated actors with the `table` pose
often use a different `y`, so check those heads too. `check` compares card boxes
with visible heads through each panel, including entrances, moves and cues.
An error names the actor and suggests a card y that clears the head.
The check judges where a card settles, not its trip in, and it lets a card
clip the outer fifth of a head box (hair, the sticker edge). A card that
reaches the face is an error.
Before narration exists, timing checks place beats ten seconds apart and
give each line one second as placeholders. When a valid `timings.json` is
present, they use its actual times. Run `check` again after
`voice`, especially when mixing numeric seconds with named cues.
Use `over_head: true` only for a deliberate face-covering gag. A stamp
animation gets no automatic exemption. Cards that cover more than 60 percent
of another visible card's box are also errors. These checks still apply
when captions are off. Review stills after fixing them.

Scale runs from 0.1 to 5, rotation from -360 to 360 degrees, card size from
16 to 300, width from 80 to 1000, and layer `z` from 0 to 10. Prop opacity
is from 0 to 1. Dot and stack counts run from 1 to 20; calendar text is at
most 8 characters. `check` reports the range for every invalid numeric field.

Limits count characters, including spaces. `k` is a small heading and `sub`
is a second line. Keep cards shorter than the limits when possible.

| Kind | Text limits |
|---|---|
| `sticker` | `text`: 32 |
| `pill` | `text`: 32 |
| `tag` | `text`: 32, `sub`: 48 |
| `note` | `text`: 90, `k`: 40 |
| `sign` | `text`: 32, `sub`: 40 |
| `doc` | `text`: 32, `k`: 48, `sub`: 40 |
| `stamp` | `text`: 24 |
| `plaque` | `text`: 48, `sub`: 120 |
| `list` | `k`: 40; 1 to 5 `rows`, each with `text` up to 32 and an `at` cue |
| `credits` | Generated only; each credit line is at most 160 |

The script must have 4 to 14 beats, at most 22 words per line, and at most
160 narration words in total. The limits apply to both readable text and
spoken `say` text. Keep one idea per beat and, in panel looks, put the main fact on a card
so the story makes sense with sound off.

### Caption band

The panel looks' caption band uses the bundled ZingCaption font, cream words on ink, with the
current word in yellow. Up to four words appear at a time. Word time is
spread evenly across each line's `start` and `end` in `timings.json`; this
is an estimate, not forced alignment. Captions use `text`, while voice
providers receive `say` when present. Pauses and the outro have no captions.

Reserve the full-width band **x=0..1080, y=1560..1720** in the 1080x1920
frame. The visible phrase has 48 pixels of horizontal inset. The chapter
pill stays below it in `cutout` and `scrapbook`. Keep cards, photo cards and puppet heads above the band. `check`
reports overlapping card boxes and low puppet heads. It reserves extra
room for wrapping, rotation and entry animations, so it can reject a box
that a browser would fit more tightly. Capture also checks measured card
and head bounds, including motion, and stops if they enter the band while
captions are visible. Review stills after layout edits. `captions: false`
removes the strip and its clearance checks. Outro art is exempt because
captions have ended.

### Effects and music

Render synthesizes a soft paper whoosh for each camera slide, a small pop
for arriving cards and props, and a thud for cards with `anim: "stamp"`.
In `headline`, whooshes follow beat changes and pops follow badge and picture
arrivals.
The generator uses Python's standard library and a fixed seed. Effects sit
about 18 dB below the narration's spoken-line RMS level; crowded entrances
are capped to keep the combined hit quiet. `sfx: false` or `--no-sfx` on
`render` or `build` turns effects off. Without music, that uses narration
alone. No effect assets or music ship with Zing.

To add your own music, put a file inside the story folder and declare:

```text
"music": {
  "path": "music/bed.wav",
  "credit": "Artist and track title",
  "license": "CC BY 4.0",
  "source_url": "https://example.org/track"
}
```

Music follows the same local-path and rights rules as photos. NC, ND,
editorial-only and unknown licenses are refused. Use the real license and
credit, not the sample values above. FFmpeg loops or trims the file to the
story length. A volume envelope fades the first and last 0.6 seconds and
ducks beneath each spoken line, with a short attack and release. The music
credit and license appear on the generated end card; the receipt also
records its path and source URL. `--no-sfx` leaves declared music enabled.
The mix is temporary: `narration.wav` and `timings.json` stay unchanged.

### Credits and photo rights

Head cuts and automatic face detection need the factory image dependencies. Install
`myzing[factory]==1.0.0rc1` in Zing's environment if they are missing.
Every photo needs a credit, a license and a source URL. The rights check uses
the factory's license rules and accepts only cleared or attribution licenses.
NC (noncommercial), ND (no derivatives), unknown and editorial-only licenses
are refused. A local file is not automatically cleared for reuse.
The cutter tries the frontal detector, then the profile detector on both
the image and its mirror. If a detector finds several faces, the largest
box wins and the command reports that choice. An explicit `face` box
overrides detection. It helps with drawings, profiles and small faces that
the cascades miss. Use `--sheet` to review all cuts and portraits before rendering.

`heads` also makes `heads/<cast-id>-<index>-portrait.jpg`, a 600x600 square
crop centred on the face and lifted a little to leave room for hair. The crop
shifts or shrinks to stay inside the photo. It uses no mask or background
removal. An explicit `photo.face` needs only Pillow for the portrait;
automatic face detection needs OpenCV. Rights checks run before pixel work.
For `headline` and `scrapbook`, `heads` makes only these portraits and never cuts a head.
`cutout` and `comic` also need the transparent head stickers.

When the face detector finds a tilted head, the cutter reads the tilt from the
eye line and levels the photo before it cuts, so the head sits upright on the
puppet. The head's result records the angle as `leveled`. A `face` box you
supply is used as given, with no levelling.

When a wall or shirt has the same colour as the hair, it can leak into the cut.
The cutter notices a cut that presses against the edge of its allowed area and
tries again with less room around the face. If it still leaks, the command
prints a warning and records it in the head's result, and the sheet shows it.
Set a tighter `face` box or pick another photo. You can also render with
`--look scrapbook` or `--look headline`, which use the photo as it is.

Zing generates the credits from photo and image credits and licenses and the
source titles. Matching photo and image credits appear once. It adds an
outro panel in each panel look if none exists, with the first cast member who has a photo waving.
Credits use 34 px type when they fit in five or fewer lines, otherwise 27 px,
and smaller type if needed to fit. On an empty stage the card is 900 px wide.
With an actor on stage it is 560 px wide and takes the side the actor is not
standing on, clear of heads. The default waving actor stands on the right.
In panel looks, your `from: "outro"` panel keeps its authored art; Zing finds a clear place
for its generated credits, or reports that the panel needs more room.
Handwritten `credits` fields and credits cards
are not accepted. Kokoro and ElevenLabs always add
`narration is an AI voice`; there is no switch to hide it. Supplied line recordings use provider `lines` and do not
add that disclosure unless you pass `--synthetic-voice`. Pass it whenever the
recordings came from any voice model.

## Small example

This is a fictional layout example with invented people and no photos.
Replace its source entry and story with facts from your own sources.

```json
{
  "schema_version": 1,
  "slug": "cardboard-moon",
  "topic": "the cardboard moon",
  "handle": "",
  "cast": {"mira": {"name": "Mira Vale", "jacket": "#1F8A8A"}},
  "sources": [{"title": "Fictional layout example", "url": "https://example.org/story"}],
  "beats": [
    {"id": "hook", "chapter": "THE MOON", "lines": [{"text": "Mira's moon would not fit through the door."}]},
    {"id": "try", "chapter": "THE PROBLEM", "lines": [{"text": "The cardboard prop was wider than the stage entrance."}]},
    {"id": "fix", "chapter": "THE FOLD", "lines": [{"text": "A paper hinge let the moon fold in half."}]},
    {"id": "kicker", "chapter": "OPENING NIGHT", "lines": [{"text": "Even the moon needed a little stage direction."}]}
  ],
  "panels": [{
    "from": "hook",
    "set": {"wall": "#FFD21F", "floor": "#17161C"},
    "actors": [{"who": "mira", "x": 320, "pose": "present"}],
    "props": [{"prop": "star", "x": 850, "y": 800, "still": true}],
    "cards": [{"kind": "note", "text": "A folding moon", "x": 80, "y": 220, "at": "fix"}]
  }]
}
```

The agent writing prompt ships at `_data/story/prompts/story.md` in the
Python package and is printed by `zing story prompt`. Write the JSON, run
`zing story check --json <dir>`, fix every problem, and repeat before making
narration or stickers. A passing check verifies structure and declared rights,
plus estimated card/head or picture clearance for panel looks. The agent still needs to verify facts,
listen and inspect the art.

## MCP tools

| Tool | Result |
|---|---|
| `story_new(directory, topic, look="cutout")` | Starter story and README paths; existing files are kept. Optional `look` selects the starter. |
| `story_check(directory)` | `valid`, `look`, `problems`, `warnings` and `notes`. Each message has `path` and `message`. |
| `story_build(directory, ...)` | Starts a background build after validation; returns `started` or `already_running`. Accepts provider, voice, speed, lines_dir, out, synthetic_voice, no_sfx and an optional look override. The override does not rewrite the file. |
| `story_status(directory)` | Reports draft, running, done, failed or interrupted, with finished video and receipt paths or an error. |

Poll `story_status` after a build. State is saved in `story-status.json`.
If the MCP process stops during a build, the next process reports it as
interrupted; call `story_build` again. These tools never publish a video.
