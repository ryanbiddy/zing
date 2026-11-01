# Clip factory

`zing factory` turns one long episode (a podcast, talk or interview) into a pack of
short social clips. Each clip is cut on sentence boundaries with the pauses removed,
framed on the speaker, and given on-screen visuals and graphics that draw what is
being said. It also gets post copy and a local review page. Nothing is posted.

```text
episode + captions -> scout moments -> cut -> plan the screen -> find visuals -> pick
                   -> fact-check -> render 9:16 / 1:1 / 16:9 -> copy -> review page
```

## Quick start

```bash
zing factory doctor
zing factory new talk --media talk.mp4 --transcript talk.vtt \
  --name "Show, Ep. 12" --url https://example.org/ep12 --date "May 2026" --moments 8
zing factory run talk --judge claude
zing factory status talk           # review page: talk/index.html
```

Without `--transcript`, Zing transcribes the whole episode locally with its speech
model, which is slow on a CPU. With a caption file, only the chosen moments are
transcribed for word timing.

## Who makes the judgment calls

Four steps need taste: the **scout** (which moments), the **plan** (what appears on
screen, second by second), the **pick** (which found visual fits best, from a contact
sheet) and the **copy**. Everything else is measured locally.

- `--judge host` (default; MCP): the run writes each prompt to `pending/` and stops.
  It asks for everything that is ready at once: the scout, then every clip's plan and
  copy, then every clip's pick. You or your agent answer with
  `zing factory answer <project> <task> <file>` (or the `factory_answer` MCP tool),
  then run again. Answers are validated; a rejected answer leaves the prompt pending.
- `--judge claude`: Claude Code's CLI answers. Calls run lean: a short system prompt,
  no MCP servers, skills or project files, and only the Read tool when an image must
  be seen. Each call's cost and tokens are logged to `answers/_usage.jsonl` and shown
  by `status`. Measured on an episode: scout about $0.18, then about $0.11 per clip
  (plan $0.055, pick $0.03, copy $0.02), so about $1 for eight clips.

Every answer is cached in `answers/`. `zing factory redo <project> clip03-plan` forgets
one judgment and what was built from it.

## What the screen shows

- **9:16** keeps the speaker in the bottom half under a visual or graphic, with the
  caption box on the seam. **4:5** (the LinkedIn and Instagram feed shape), **1:1** and
  **16:9** cut to full-screen visuals.
- Graphics (counter, list, funnel, quote) are built only from the clip's words. Every
  drawn number must be spoken (spelled-out numbers count), a quote must be word for
  word, and a hook with an unspoken number is flagged. A graphic that fails becomes a
  shot of the speaker.
- Speaker framing uses the pinned YuNet face model (`zing layout fetch-model`).
  Close-ups teach the frame what the main speaker wears; in wide shots it follows them.
  Captions already burned into the source are cropped out.
- Photos move through their own depth: near things slide and grow against the
  background, as if a camera drifted past (Depth Anything V2 Small on the CPU, about
  0.5 s per photo plus a few seconds to encode the move). The move only shifts and
  scales what is in the photo; nothing is generated. Logos, page captures and flat
  pictures such as charts stay still. It needs `zing factory fetch-depth --yes` once
  (Apache-2.0 weights, about 99 MB); without them photos keep the flat zoom. Turn it off
  per project with `new --no-parallax` or per render with `render --no-parallax`.
- `--mode fun` asks for playful, literal visuals that still match what is said.
  Clips on sensitive subjects (slavery, violence, death, war and similar) are planned
  and picked in context mode with restrained visuals, and flagged on the review page.

## Where visuals come from

Context mode searches Wikidata and Wikimedia Commons for the named thing, the named
company's own site (a screenshot and a six-second scroll recording, with cookie
banners hidden by CSS and nothing clicked), NASA, the Library of Congress and the
Internet Archive. With your own keys it also uses Pexels and Pixabay stock video and
the Exa page finder: set `PEXELS_API_KEY`, `PIXABAY_API_KEY` or `EXA_API_KEY`.
Key values are never printed, logged or passed to the browser.

Each candidate carries a rights record (`cleared`, `attribution`, `editorial` or
`unknown`) and a credit line. The review page flags anything not cleared. `--public`
keeps only cleared and attribution-licensed visuals and skips site captures.
GIPHY, KLIPY and Tenor are not used: their terms forbid baking clips into video.

## Style packs

`--pack zing | newsdesk | swiss | headline` sets colors, caption treatment and source tag
(`zing factory packs`). A pack is one JSON file in `myzing/_data/factory/themes/`.
`headline` plays the clip above a solid panel that holds your source credit and the hook
as a standing headline in condensed capitals, key words in the accent color.

## Review dashboard

`zing factory serve <project>` opens a local page (http://127.0.0.1:8765) for the part
that is yours: watch each clip in every shape, rate it Post / Post with edits / No,
swap a visual for another candidate, fix a hook or the copy, and re-render in another
style pack. Swaps and hook edits re-run the fact check and re-render in the background.
Ratings save to `ratings.json`. `--judge claude` lets the page's Run button answer
judgments with Claude Code; otherwise they wait for your agent.

The server listens on 127.0.0.1 only, answers only to localhost Host headers, refuses
writes from other sites and non-JSON posts, and serves files only from the project's
clip folders. Nothing on the page posts or publishes.

## Learn a style from a clip you like

```bash
zing factory learn-style liked.mp4 --name bold-white --sample talk/clip01
zing factory new talk2 --media ep2.mp4 --pack bold-white
```

`learn-style` measures the reference's captions: position, size, words per caption,
case, text color, background box, outline, word color (the active word, or emphasized
words such as numbers and the hook's keywords), how captions pop in, the closest bundled
font, plus the frame shape, a headline panel under the video (its size, color and
headline colors), where the speaker sits and how often it cuts. It writes those into a pack,
renders the sample clip in it, measures that render the same way and corrects size,
position, grouping, pop timing and outline, for up to `--rounds` (3). The pack is saved
to the workspace (`factory/packs/<name>.json`) beside a report: `report.md` lists each
trait as matched, not matched or not measured, and `compare.jpg` puts reference
frames above ours.

Everything is measured from pixels. The original font, project and settings stay
unknown, and the closest bundled font is reported with its similarity.

## Setup

```bash
python -m pip install "myzing[factory]"
zing layout fetch-model
zing factory fetch-depth --yes          # optional: photos move through their depth
cd tools/factory-sidecar && npm ci     # pinned playwright-core; uses your Chrome or Edge
```

The renderer captures a deterministic `seek(t)` page frame by frame in a local Chrome
or Edge (`ZING_BROWSER_PATH` overrides the lookup), then FFmpeg encodes it with the
cut's audio. Set `ZING_FACTORY_SIDECAR` when the sidecar lives outside a checkout.

## Project layout

```text
<project>/source.json  factory.json  transcript.json  words.json  moments.json
<project>/pending/<task>.md     answers/<task>.json     answers/_usage.jsonl
<project>/clipNN/  cut.mp4  words.json  cams.json  plan.json  post.json
                   visuals/ (candidates, manifest.json, run_log.json, pick_sheet.jpg)
                   clip.mp4  clip-1x1.mp4  sheet.jpg
<project>/index.html   review page with Post / Post with edits / No ratings
```
