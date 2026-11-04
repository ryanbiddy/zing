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

Without `--transcript`, Zing reads the whole episode with a small speech model already
on disk (`small` or `base`; an hour in about 5 minutes on a CPU) only to find the
moments, then transcribes the chosen moments with your configured model for word
timing. With a caption file, or when no small model is on disk, it works as before.

Speech models mishear names and terms. The plan lists clear mishearings it is sure of
("Buddy Shaw" for "Buddy Shah", "Middle least" for "Middle East"); Zing corrects the
captions, graphics, hook and copy, logs each fix, and keeps what was heard in
`words-heard.json`. Numbers and meaning are never changed.

## Cut from unreleased footage

```bash
zing factory new launch --media demo.mp4 --transcript demo.vtt \
  --mode launch --offline --visuals ./launch-media
zing factory run launch
zing factory status launch
```

Your media never leaves the machine and offline mode fetches nothing. `--offline`
saves `"offline": true` in `factory.json`. It blocks public visual searches, page
captures, remote video reads and model downloads. Use models already on disk or
supply a transcript. Word timing still needs a cached speech model when the
transcript lacks word times.

The host judge writes prompts and contact sheets locally for you to answer.
Offline projects refuse `--judge claude`. In an online project, that judge sends
prompts to Anthropic. Picks for a project with `--visuals` use the host judge so
your pictures and video thumbnails stay local.

`--visuals DIR` accepts PNG, JPG, JPEG, WebP, MP4, MOV and WebM files directly in
the folder. Filenames help rank candidates. The pick step sees thumbnails and
chooses a file or none. Selected files are copied into the project and credited
as `Your file: <name>`. Online projects also search the public sources. Offline
projects use only your files; without a usable file, the shot stays on the speaker.

`network.jsonl` records factory network attempts, including failures. Each row has
`at`, `host`, `purpose` and `bytes`. It never stores full URLs, query strings,
headers or prompt text. Python downloads count response bytes read. Subprocess
calls use `null` when the byte count is unavailable. Claude calls use the host
`claude CLI (Anthropic)` and the task name. Cached work adds no requests.
Browser resource requests and FFmpeg range requests or redirects are included.
The ledger records factory activity; it is not a system-wide packet capture.

Status and the review header show counts by host and purpose. They show
`offline: nothing fetched` only for an offline project with an empty ledger.
Model fetch commands accept `--project launch` to apply that project's policy
and ledger. Without it, the download is not tied to a project and is not recorded.

## Supply names and spellings

Give names and terms when creating the project.

```bash
zing factory new talk --media talk.mp4 --vocab "Pompliano, Starbase, Vermilion Parish"
```

Repeat `--vocab` or separate terms with commas. MCP accepts
`factory_new(..., vocab=["Pompliano", "Starbase", "Vermilion Parish"])`.
The list is saved as `vocab` in `factory.json`. It guides episode transcription,
word timing and the planner's caption fixes. Only supplied terms are used.
The brand name, source name, tag and people named in the show are not added.

Limits match study vocabulary. Up to 64 terms, 80 characters per term and
500 UTF-8 bytes for the list joined with a comma and space. Oversized lists are
rejected. Spaces are normalized and duplicates are removed. Set the vocabulary
when creating the project; there is no edit command.

## Render in 4K

```bash
zing factory new talk --media talk.mp4 --4k
zing factory render talk/clip01 --4k
```

`--4k` saves `"uhd": true` in `factory.json`. MCP accepts
`factory_new(..., uhd=True)`. Each shape doubles in width and height.

| Shape | 4K output |
| --- | --- |
| 9x16 | 2160x3840 |
| 16x9 | 3840x2160 |
| 1x1 | 2160x2160 |
| 4x5 | 2160x2700 |

The layout and file names stay the same. `render --4k` also enables 4K for future
renders in that project. The next factory run replaces any remaining 1080 renders.

Sources below 2160 pixels on the short side still render. Each run warns once,
for example `source is 1080p; 4K output will be upscaled`. Speaker frames, cutout
mattes and moving visuals keep their source resolution. The photo upscaler is
unchanged. Output uses H.264 High level 5.1, CRF 20 and yuv420p.

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

## Input limits

- Prompt image directives count only in the leading block. Attached files must resolve
  inside the project folder. Directive lines in the transcript stay as text.
- Visual downloads and page captures refuse local and private network addresses.
  HTTP download redirects receive the same check.
- Plans drop shots with negative or nonfinite times, or times more than three seconds
  after the last word. End cards stop within three seconds of the last word.

## Steer which moments become clips

- `--focus "the pricing argument"` (or "funny moments", "anything about hiring") tells
  the scout what you want. It fills any gap with the strongest other moments and says
  in each clip's "why" whether it is on your ask.
- `--show "The Pod"` names the show. Every Post, Post with edits and No you give on the
  review page (with its reason) is kept for that show, and the next episode's scout
  sees your newest calls as examples of what you post and what you pass on. Without a
  show, a re-scouted project learns from its own calls.
- The scout lists as many runners-up as clips (up to eight). The review page shows them
  under the clips with the scout's reason; **Make this one** turns one into a clip.
- **Make a clip** on the review page: read the transcript, click the line a clip starts
  on and the line it ends on (3 s to 3 min), nudge either end a line at a time, and give
  it a hook or let the plan write one. **Trim** on a clip loads its range to move its in
  and out points; the clip is cut, planned and rendered again from the new words, so
  its old plan, copy and rating go. Every clip goes through the same fact checks.
- `--moments 0` scouts nothing: only the clips you pick.

```bash
zing factory clip talk --start 12:03 --end 12:51 --hook "The *real* price"
zing factory clip talk --bench 2       # make runner-up 2, as status lists them
zing factory trim talk clip03 --start 4:10 --end 5:02
zing factory run talk --clips 9
```

MCP: `factory_new(..., focus=, show=)` and `factory_clip(project, start=, end=, hook=)`,
`factory_clip(project, bench=)` or `factory_clip(project, clip=, start=, end=)`.

## What the screen shows

- **9:16** keeps the speaker in the bottom half under a visual or graphic, with the
  caption box on the seam. **4:5** (the LinkedIn and Instagram feed shape), **1:1** and
  **16:9** cut to full-screen visuals.
- A quote is the clip's one most quotable line, and the captions take over for it: the
  speaker stays on screen, dimmed, and the line builds word by word in the pack's quote
  face with its key words highlighted, then steps away and normal captions carry on.
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
- `new --cutout` stands the speaker in front of the pictures instead of splitting the
  frame: the picture sits sharp in a window (the top in 9:16, the left in 16:9) over its
  own blur, and the speaker, lifted off their background, overlaps its edge with a soft
  shadow. The cutout uses rembg's IS-Net model on the CPU (about 0.4 s for every second
  frame, only inside those shots; mattes are kept for re-renders). A speaker too small
  to lift cleanly, such as a conference recording's inset camera, or one who leaves the
  frame, keeps the split. It needs `zing factory fetch-cutout --yes` once (Apache-2.0
  weights, about 179 MB). Try it on one render with `render --cutout`.
- Small photos (under 1600 px on the long side) are upscaled 4x by Real-ESRGAN on the
  GPU through Vulkan (AMD and Intel included) before they render, so a full-frame photo
  stays sharp. On its own the model airbrushes old photos, so its result is blended half
  and half with a plain enlargement: sharper edges, the photo's own grain. It still
  guesses the finest texture, so an upscaled photo's credit says "upscaled". Logos and page captures are never upscaled.
  It needs `zing factory fetch-upscale --yes` once (BSD-3-Clause, about 50 MB); without
  it photos render at their own size. Turn it off with `new --no-upscale` or
  `render --no-upscale`.
- `--mode fun` asks for playful, literal visuals that still match what is said.
  Clips on sensitive subjects (slavery, violence, death, war and similar) are planned
  and picked in context mode with restrained visuals, and flagged on the review page.
- Any shot can carry a name tag for the person speaking or pictured, shown for its first
  seconds. The name and role must be said in the clip (or given as the brand).

## Documentary mode

`--mode documentary --pack documentary` cuts the episode like a Vox or Ken Burns
documentary, with the speaker as the narrator:

- Visuals come from archives only (Wikidata, Commons, NASA, the Library of Congress,
  the Internet Archive): period photographs, paintings, documents, letters, maps and
  portraits. No stock, no site captures. The picker keeps a period map or register of
  the exact subject as evidence instead of rejecting it as a scan.
- The archival image fills the frame in every shape, moving through its depth; the
  speaker comes back on camera for opinions and emotional beats.
- The `documentary` pack grades footage and photos to warm black and white with grain
  and a vignette, brings each cut into focus, and sets captions in Instrument Serif that
  build word by word with the weightiest word of each line large in italic. A quote
  moment draws a hand-drawn ring around its key words.
- Sensitive subjects stay in documentary mode: it is already archival and restrained.

### News peg

Make each clip the backstory to today's news ("Binance just lost $6.3B. Here's how it
happened."):

```
zing factory new ./hack --media interview.mp4 --mode documentary --pack documentary \
  --news-peg "Binance lost $6.3 billion in the biggest crypto hack ever" \
  --news https://example.com/binance-hack --news https://example.com/fbi-statement
```

The scout favors moments that explain how it came about. Each clip opens on a
screenshot (and short scroll recording) of one of the `--news` articles, then tells the
story with recent photos of the people named and a photo from each backstory beat's own
year. The hook and the copy may state the peg; everything drawn on screen still has to
be said in the clip. MCP: `factory_new(..., news_peg=, news_links=)`.

## Launch mode

`--mode launch` turns a long founder demo, interview or livestream into launch films:
landscape first (`16x9,1x1,9x16`), the `launch` pack, two films by default (a full cut and
a teaser).

```
zing factory new ./fold --media demo.mp4 --mode launch --brand-name Fold --brand-url fold.app --cta "Join the waitlist"
zing factory run ./fold --judge claude
```

- The scout assembles each film from three to seven spans of the recording in the
  order they should play: open mid-action or on a first-person claim, say what it is,
  show how it works, proof, close. The rules come from the openings of 600 launch films.
- The plan names the product with an "Introducing" title card after the opening beat
  and ends on an end card (name, url, a short line) that holds for three seconds. The
  product's own site is captured and scroll-recorded where it is named or shown.
- Titles, end cards and name tags use only what the speaker says or the brand you give.
  Post copy is written as a launch post, not a clip credit.

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

`--pack zing | newsdesk | swiss | headline | documentary | launch` sets colors, caption treatment and source tag
(`zing factory packs`). A pack is one JSON file in `myzing/_data/factory/themes/`.
`headline` plays the clip above a solid panel that holds your source credit and the hook
as a standing headline in condensed capitals, key words in the accent color.

## Review dashboard

Run `zing factory serve <project>` and open the printed link. It includes a token
for this server session, such as `http://127.0.0.1:8765/?t=TOKEN`. The page saves it
in an HttpOnly session cookie and removes it from the address bar. Open the new
printed link after restarting the server. Requests without the cookie are refused.

Watch each clip in every shape, rate it Post / Post with edits / No,
swap a visual for another candidate, fix a hook or the copy, and re-render in another
style pack. Swaps and hook edits re-run the fact check and re-render in the background.
Ratings save to `ratings.json`. `--judge claude` lets the page's Run button answer
judgments with Claude Code; otherwise they wait for your agent.

The server listens on 127.0.0.1 only, answers only to localhost Host headers, refuses
writes from other sites and non-JSON posts, and serves files only from the project's
clip folders. Nothing on the page posts or publishes.

## Full context and guest approval

First comments link YouTube watch and youtu.be sources to the clip's start time.
An existing `t` parameter is replaced. Launch films use the first span in playback
order. Links to other sites stay unchanged.

```bash
zing factory approval talk
zing factory approval talk --out talk/guest.html
```

The default file is `talk/approval.html`. It lists each rendered 9x16 clip in the
project's style pack with its hook and full transcript. If `clipNN/context.json`
has `before` and `after` text, that appears too.

Zip the project folder and send it to the guest or their PR person. They unzip it,
open the HTML file, choose Yes or No, and add comments. **Copy my answers** builds
plain text they can send back. If clipboard access is blocked, they can select and
copy the text on the page. The page uses local videos and has no network requests.
Video paths are relative to the HTML file. Keep a custom output inside the project
folder when sharing a zip.

## What each clip adds

Each finalized plan writes `clipNN/receipt.json`. It lists pictures, graphics, quote
takeovers, name tags and title or end cards, with time ranges, sources and known
licenses. It uses the clip's existing files. Ordinary hooks and captions do not count.
An empty solo shot adds zero. Overlapping additions count once in the total.

The duration follows the render, including the last word's tail and any end card
hold. Quotes follow the spoken words. Name tags count for up to 3.4 seconds.
`by_kind` lists seconds for each kind. `added` is the total seconds covered, and
`share` is that total divided by the duration, rounded to two decimal places.

`zing factory status` reports each clip's share as `added`. A clip without a receipt
has `null`. Each dashboard card shows the percentage and an expandable source list.
Visual swaps and hook edits rewrite the receipt when the plan is finalized again.
The receipt leaves `post.json` alone. It records planned additions and makes no
promise about platform reach, monetization or originality decisions.

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
zing factory fetch-cutout --yes         # optional: --cutout stands the speaker in front of pictures
zing factory fetch-upscale --yes        # optional: small photos render sharp
cd tools/factory-sidecar && npm ci     # pinned playwright-core; uses your Chrome or Edge
```

The renderer captures a deterministic `seek(t)` page frame by frame in a local Chrome
or Edge (`ZING_BROWSER_PATH` overrides the lookup), then FFmpeg encodes it with the
cut's audio. Set `ZING_FACTORY_SIDECAR` when the sidecar lives outside a checkout.

## Project layout

```text
<project>/source.json  factory.json  transcript.json  words.json  moments.json
<project>/pending/<task>.md     answers/<task>.json     answers/_usage.jsonl
<project>/clipNN/  cut.mp4  words.json  cams.json  plan.json  receipt.json  post.json
                   visuals/ (candidates, manifest.json, run_log.json, pick_sheet.jpg)
                   clip.mp4  clip-1x1.mp4  sheet.jpg
<project>/index.html   review page with Post / Post with edits / No ratings
```
