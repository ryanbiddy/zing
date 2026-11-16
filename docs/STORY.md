# Cutout stories

`zing story` turns a short script into a vertical video without source footage.
A voice reads each beat while paper puppets, props and fact cards move across
drawn sets. The camera slides between sets. The end card carries source and
photo, image and music credits. Word captions make the narration readable with sound off.

## Make a story

Start a folder and give your agent the bundled writing prompt:

```sh
zing story new ./story --topic "the cardboard moon"
zing story prompt
```

`new` writes `story.json` and `README-STORY.txt`. The cast is invented and has
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

`check` prints every problem and exits 1 if it finds any. With `--json`, stdout
is a list of `{ "path": "topic", "message": "must be non-empty text" }`
objects, or `[]` when the story passes. This includes missing or invalid JSON
files, so an agent can use the same loop for every draft. `voice` writes
`narration.wav` and `timings.json`. `heads` writes transparent PNG stickers into
`heads/`. `images` prepares declared pictures in `images/`; its `--sheet`
writes `images/sheet.png`. For heads, `--sheet` adds `heads/sheet.png`, with each cut head on a checker
background and its cast ID and photo index. `render` writes a 1080x1920,
30 fps MP4 with narration, captions and sound effects. `--stills`
writes JPEGs for review instead of a video.

To run all steps and write `story-receipt.json`:

```sh
zing story build ./story
zing story build ./story --lines-dir ./recorded-lines --out ./story/final.mp4
```

`build` also accepts `--provider`, `--voice`, `--speed`, `--synthetic-voice`
and `--no-sfx`. The default video is `story.mp4`
inside the story folder. The receipt records the voice provider and name,
each photo's and image's credit, license and source URL, any music rights, the sources,
output and duration.

Render uses the factory's Node sidecar and FFmpeg discovery. Install Node.js
20 or newer, FFmpeg and Chrome or Edge, then run `zing factory setup` and
`zing factory doctor`. Rendering uses bundled fonts and local files only.
The same time always produces the same frame.

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
hex colors such as `#FFD21F`.

| Top-level field | Meaning |
|---|---|
| `schema_version` | Optional, `1`. |
| `slug` | Optional local story identifier. |
| `topic` | Required top-bar label, up to 60 characters. The bar reads `zing · <topic>`. |
| `handle` | Optional right-hand label, up to 40 characters. Empty means no label. |
| `cast` | Optional object keyed by cast ID. Omit it or use `{}` for no puppets. |
| `images` | Optional object keyed by image ID, for licensed pictures used by image props. |
| `beats` | Required ordered list of 4 to 14 narration beats. |
| `panels` | Required ordered paper sets. The first starts at the first beat. |
| `sources` | Required nonempty list of `{ "title": "Source title", "url": "https://..." }`. Titles are at most 100 characters. URLs must be HTTP or HTTPS. |
| `outro` | Optional end-card duration in seconds, from 1 to 30. Default 3.2. |
| `captions` | Optional boolean, default `true`. Shows timed spoken-word captions. |
| `sfx` | Optional boolean, default `true`. Adds synthesized paper sounds during render. |
| `music` | Optional local music object with `path`, `credit`, `license`, `source_url`. |

Each cast member has a required `name` (at most 60 characters), optional
`skin`, `jacket`, `shirt` and `legs`
colors, and optional `photos`. Each photo is an object with `path`, `credit`,
`license`, `source_url`, and optional `face: [x, y, width, height]`. Photo paths
are at most 240 characters, credits 120, and licenses 100. Paths are
local files relative to the story folder and must stay inside it. A member
without photos gets a blank paper head with initials. Head indices start at
zero in the order of `photos`; the generated PNGs are outputs, not inputs.

A beat has `id`, optional `chapter` (at most 40 characters), 1 to 8 `lines`,
and optional `tail` in seconds. Beat IDs, cast IDs and slugs start with a
lowercase letter and use lowercase letters, numbers, underscores and hyphens,
up to 60 characters. `outro` is
reserved. A line has required `text`, optional `say` for pronunciation, and
optional `gap` in seconds. `say` changes the spoken words, while `text` remains
the readable version in timings. Both text fields are at most 300 characters.
Line gaps and beat tails must be finite, from 0 to 5 seconds.
The page shows each nonempty `chapter` as a pill while that beat plays.

A panel has `from`, `set`, and optional `props`, `actors` and `cards` lists.
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
spoken `say` text. Keep one idea per beat and put the main fact on a card
so the story makes sense with sound off.

### Caption band

Captions use the bundled ZingCaption font, cream words on ink, with the
current word in yellow. Up to four words appear at a time. Word time is
spread evenly across each line's `start` and `end` in `timings.json`; this
is an estimate, not forced alignment. Captions use `text`, while voice
providers receive `say` when present. Pauses and the outro have no captions.

Reserve the full-width band **x=0..1080, y=1560..1720** in the 1080x1920
frame. The visible phrase has 48 pixels of horizontal inset. The chapter
pill stays below it. Keep cards and puppet heads above the band. `check`
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

`heads` needs the factory image dependencies. Install
`myzing[factory]==1.0.0rc1` in Zing's environment if they are missing.
Every photo needs a credit, a license and a source URL. The rights check uses
the factory's license rules and accepts only cleared or attribution licenses.
NC (noncommercial), ND (no derivatives), unknown and editorial-only licenses
are refused. A local file is not automatically cleared for reuse.
The cutter tries the frontal detector, then the profile detector on both
the image and its mirror. If a detector finds several faces, the largest
box wins and the command reports that choice. An explicit `face` box
overrides detection. It helps with drawings, profiles and small faces that
the cascades miss. Use `--sheet` to review all cuts before rendering.

When a wall or shirt has the same colour as the hair, it can leak into the cut.
The cutter notices a cut that presses against the edge of its allowed area and
tries again with less room around the face. If it still leaks, the command
prints a warning and records it in the head's result, and the sheet shows it.
Set a tighter `face` box or pick another photo.

Zing generates the credits from photo and image credits and licenses and the
source titles. Matching photo and image credits appear once. It adds an
outro panel if none exists, with the first cast member who has a photo waving.
Credits use 34 px type when they fit in five or fewer lines, otherwise 27 px,
and smaller type if needed to fit. On an empty stage the card is 900 px wide.
With an actor on stage it is 560 px wide and takes the side the actor is not
standing on, clear of heads. The default waving actor stands on the right.
Your `from: "outro"` panel keeps its authored art; Zing finds a clear place
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
narration or stickers. A passing check verifies structure, declared rights
and estimated card/head clearance. The agent still needs to verify facts,
listen and inspect the art.

## MCP tools

| Tool | Result |
|---|---|
| `story_new(directory, topic)` | Starter story and README paths; existing files are kept. |
| `story_check(directory)` | `valid` plus JSON `problems`, each with `path` and `message`. |
| `story_build(directory, ...)` | Starts a background build after validation; returns `started` or `already_running`. Accepts provider, voice, speed, lines_dir, out, synthetic_voice and no_sfx. |
| `story_status(directory)` | Reports draft, running, done, failed or interrupted, with finished video and receipt paths or an error. |

Poll `story_status` after a build. State is saved in `story-status.json`.
If the MCP process stops during a build, the next process reports it as
interrupted; call `story_build` again. These tools never publish a video.
