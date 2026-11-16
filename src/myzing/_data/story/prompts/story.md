# Write a cutout story

Write `story.json` for the user's topic. Aim for about eight beats that a voice
can read in under a minute. The video has paper sets, cutout puppets, props,
fact cards, a chapter pill and a generated credit card. There is no footage.

Read the sources first. Use only facts supported by a source in `sources`.
Never invent quotes. If sources disagree on a detail, leave it out or state
the uncertainty in plain words. Do not guess. Put a hook in the first line,
one idea in each beat, and a kicker in the last. Cards must carry the facts
for someone watching with sound off. Use plain words and no em dashes.

Write the story, run `zing story check <dir>`, fix every problem, and repeat
until it passes. Then make narration and review stills. A passing check tests
the file and its limits, not whether the reporting is true or the art looks good.

## JSON contract

Top-level fields:

- `schema_version`: optional `1`.
- `slug`: optional local identifier, starting with a lowercase letter and using lowercase letters, numbers, underscores and hyphens, at most 60 characters. Beat IDs and cast IDs use the same rule.
- `topic`: required string, at most 60 characters. The top-left bar says `zing · <topic>`.
- `handle`: optional string, at most 40 characters. Empty hides the right label.
- `cast`: optional object keyed by unique cast IDs. Omit it or use `{}` for no actors.
- `beats`: ordered list of 4 to 14 beats.
- `panels`: ordered list of paper sets. The first starts at the first beat.
- `sources`: at least one object with `title` (at most 100 characters) and an HTTP or HTTPS `url`.
- `outro`: end-card seconds, 1 to 30, default 3.2.

Do not add unused fields such as `title`, `credits` or a beat's `set`.
Unknown fields are errors. Colors use hex notation such as `#FFD21F`.

Each cast member has `name` (at most 60 characters), optional colors `skin`,
`jacket`, `shirt`, `legs`, and
optional `photos`. A photo has `path`, `credit`, `license`, `source_url`, and
optional `face: [x, y, width, height]`. `path` is at most 240 characters,
`credit` 120, and `license` 100. Paths are local and relative to the
story folder, and must stay inside it. List only photos the user has supplied
with cleared or attribution rights. No NC, ND or editorial-only photos.
Never invent a credit or license. A cast member with no photo gets a paper
head with initials. Do not supply `heads`; `zing story heads` makes them.

Each beat has a unique `id`, optional `chapter` (at most 40 characters),
1 to 8 `lines`, and optional
`tail` in seconds (default 0.3). Reserve the ID `outro`. Each line has `text`,
optional `say` for pronunciation, and optional `gap` in seconds (default 0.16).
Both versions of a line must be at most 22 words; both narration totals must
be at most 160 words. Each text field is also at most 300 characters.
`say` changes speech only. Gaps and tails run from 0 to 5 seconds.
The page makes a chapter pill from each nonempty `chapter` during its beat.

A panel has `from`, `set`, and optional lists `props`, `actors`, `cards`.
`from` must be an exact beat ID or `outro`. Panels begin in beat order, and
last until the next panel begins. Every beat must belong to a panel. Reuse
a set across related beats; do not move the camera for every sentence.

`set` has optional `wall` and `floor` colors, `pattern` (`tiles`, `stripes`,
`check`) and `floor_pattern` (`check`, `planks`). No pattern means plain paper.
There are no named set presets. A kitchen can combine tiles, sink, plates
and bubbles; an office can use stripes, crt and a calendar; a diner can use
a booth, table, cups and pancakes; outdoors can use a window, tree or skyline.

## Cues

Times are finite seconds or named cues: `beat`, `beat:line`,
`beat:line:fraction`, `outro`. Line numbers start at zero. Fractions run from
0 to 1 across a line's speech. Any named cue can add an offset in seconds:
`hook+0.2`, `hook:0:0.5-0.2`, `outro+0.6`. The legacy colon offset form
`hook:0:-0.2` means 0.2 seconds before line zero. Prefer the other forms
when writing new files. Panel `from` is an exact beat ID, not a general cue.

## Props and actors

Props: `blob`, `dots`, `window`, `skyline`, `lamp`, `sink`, `plates`, `bubbles`,
`crt`, `calendar`, `cube`, `chip`, `cup`, `pancakes`, `booth`, `table`,
`garage`, `tree`, `cross`, `star`.

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

## Cards

Every card has `kind`, `x`, `y`, `at` and the fields for its kind. Coordinates
use its top-left corner and must be inside 1080x1920. Optional common fields:
`until`, `rot`, `anim`, `z`, `size`, `w`, `bg`, `color`, `from` (horizontal
slide distance). `anim` is `pop`, `drop`, `stamp` or `slide`.
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
and away from the top bar.

Zing adds an outro with photo credits and licenses and the source titles.
You may supply your own `from: "outro"` panel, but Zing still adds its credits
card. Do not write a credits card yourself. Kokoro always adds
`narration is an AI voice`; that line cannot be hidden. Supplied WAV lines
use provider `lines` and do not add that line.
