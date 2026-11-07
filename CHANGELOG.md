# Changelog

## Unreleased

- Keep YouTube channel metadata available during feed outages with yt-dlp.
  Receipts say "about" for rounded counts. Shorts use exact metadata, and
  approximate counts never become measured learning results.
- Add channel scorecards with local progress rows, owner-set bars, flags and
  digest counts. `channels scorecard` writes HTML and JSON; `channels flag` logs issues.
- Channel scripts learn from matched takes in the last 30 local dates. The brief
  page shows how much of the script was kept. `brief --takes` prints recording notes.
- Add daily channel briefs with script drafts and claims to check. Recorded takes
  carry their hook, news peg and series into the factory, queue and learning report.
- Add channel platform news candidates from RSS, Atom and public YouTube uploads,
  with a 10-day window, topic scoring and source errors saved under `brief`.
- Channels: stricter gate and safer kits after review.
- Add opt-in YouTube connection, private or scheduled uploads and owner analytics
  for channels. Uploads resume from saved sessions, recheck approval, honor pause
  files and enforce daily channel and Cloud project caps. Publishing defaults to off.
- Channels learn from public view snapshots and Studio CSV metrics. `track`,
  `metrics --csv FILE` and `learn` record results, compare title and clip choices,
  and guide later scouts while keeping variety in titles and the queue.
- Add channel source watching, bounded ticks and daily digests. Ticks resume
  local projects and make post kits. Edited clips need fresh approval, and
  channels can choose whether to allow editorial visuals.
- Add `zing channels` for niche settings, source grants, approval gates, local
  queues and post kits. `factory new --channel SLUG --source ID` shares defaults
  and review history across episodes. Publishing stays off until enabled.
- `zing playbook niches` compares channels from public metadata. `watch` saves
  view snapshots, `velocity` compares views by age, and `prior` exports title
  guidance. Reports omit competitor titles. No video, thumbnails or audio are fetched.

## Clip factory

- Review edits read current files in the queue. MCP refuses edits during active
  factory runs. Manual word fixes update on-screen text and copy, repeated fixes
  keep the original heard text, and new cuts clear old fixes. Render errors now
  return brief stderr through MCP and the CLI.

- `factory_edit` and `zing factory edit` rate clips, change hooks and copy, swap
  visuals, fix caption words and re-render. The review page also edits caption
  words. Fixes keep their timing and refresh fact checks, context and receipts.

- Factory `--rights` labels source rights without blocking clips. `--brief FILE`
  adds campaign length checks, required tags, banned-term flags and a disclosure
  at the start of every rendered shape.

- security: Limit Claude image reads to attached files. Check video redirects before
  FFmpeg runs. Block private DNS answers and WebSockets in page captures.

- Factory review fixes correct 4K export sizes, transcript setup, batch retries,
  visual IDs, caption fixes, dashboard state and sign-in, network logs, name tags,
  and context answer validation.

- Style packs can carry local fonts and a logo. `zing factory packs --check NAME`
  checks files and font families. Renders stop when a font or logo cannot load.

- Factory embargo mode adds `new --offline`, local visual candidates with
  `--visuals DIR`, and a host-only `network.jsonl` ledger shown in status and review.

- `zing factory batch` clips stable episodes in a folder, reads caption and
  metadata files, resumes unfinished projects and logs JSON summaries. `--watch`
  checks for more episodes. `--limit` caps new episodes per pass.
- YouTube first comments link to the clip's start time. `zing factory approval`
  writes a local guest approval page with videos, transcripts, saved context and
  copyable Yes / No answers and comments.
- `zing factory new --4k`, `render --4k` and `factory_new(..., uhd=True)` save 4K
  output for the project. Every shape doubles in width and height. Smaller sources
  still render with a warning.
- `zing factory export` writes speaker and overlay layers, caption and word SRTs,
  48 kHz audio and a timeline for Premiere Pro or DaVinci Resolve. It checks three
  composited frames against the normal scene and reports the difference.
- `zing factory new --vocab` and `factory_new(..., vocab=[...])` save supplied names
  and terms for episode transcription, word timing and the planner's caption fixes.
- Factory review fixes: trims get words for the full span, redo clears old clip
  work, and dashboard hook edits and visual picks survive later runs. The dashboard
  updates while jobs run, shows errors, keeps saved ratings, and plays the selected
  style pack. Graphics keep decimals and handle zero values. Learned caption sizes,
  review pack selection, clip boundaries, and cutout retries are corrected. The
  quick scout pass can use batched speech decoding.
- Factory review fixes: the dashboard now requires the session link printed by
  `zing factory serve`. The link sets a cookie before opening the page.
- Factory news peg: `--news-peg "<what happened>" --news <article url>` turns clips into
  the backstory to today's news. The scout looks for how it came about, each clip opens on
  a headline screenshot, and the copy leads with the news. Spoken decimals ("$6.3") now
  count as said numbers. Page captures load no ads, trackers or private addresses and
  scroll only to the end of the article, and the hook moves above a page shown whole.
- Clips now check their cuts and hooks against up to 90 seconds of surrounding
  transcript at each edge. The dashboard shows supported flags and suggests No
  for unrated clips. Trims and hook edits clear the cached check.
- Each clip gets a `receipt.json` of its planned additions, with time ranges,
  sources and known licenses. Overlaps count once. The dashboard shows the receipt
  and `zing factory status` reports its share. Visual swaps and hook edits refresh
  it. The receipt makes no promise about platform outcomes.
- Hardening: keep prompt images inside their project and preserve transcript text.
  Refuse private visual URLs and unsafe redirects. Keep peer tokens off redirects.
  Bound shot times and end cards. Save breakdowns atomically. Keep FFmpeg off stdin.
  Use the available caption filter. Finish worker cleanup after wait timeouts.
  Retry JSON replacements when Windows readers hold files open.
- Factory steering: `--focus` tells the scout what to clip, and `--show` keeps every
  Post/No call (with its reason) so the next episode's scout learns from them. The scout
  also lists runners-up the review page can make with one click, and **Make a clip**
  picks any stretch from the transcript (click a start line, then an end line, nudge
  either end). **Trim** moves a clip's in and out points and re-cuts it. CLI:
  `zing factory clip` and `zing factory trim`. MCP: `factory_clip`. `--moments 0` scouts
  nothing. The upscaler's platform check no longer starts a process on Windows.
- Factory speaker cutout: `new --cutout` (or `render --cutout`) stands the speaker,
  lifted off their background by rembg's IS-Net model, in front of each picture instead
  of splitting the frame. Speakers too small or too absent to lift cleanly keep the
  split. `zing factory fetch-cutout --yes` installs the weights.
- Factory photos under 1600 px are upscaled 4x by Real-ESRGAN (Vulkan, any GPU), blended
  half and half with a plain enlargement so old photos keep their grain, and credited
  "upscaled". `zing factory fetch-upscale --yes` installs it; `--no-upscale` turns it off.
- Factory transcription keeps one language per episode: a short stretch that speech
  detection mishears as another language (an English span came back as Welsh) is redone
  in the episode's main language. `transcribe()` takes an optional `language`.
- `zing factory` turns one long episode into a pack of social clips: scouted moments
  cut on sentences with pauses removed, speaker framing, visuals found in public
  archives and on the named company's own site (stock video with your own keys),
  graphics drawn only from spoken facts, 9:16 / 1:1 / 16:9 renders, post copy and a
  local review page. See [Clip factory](docs/FACTORY.md).
- Judgments (scout, plan, pick, copy) go to the calling agent through
  `factory_new`, `factory_run`, `factory_status`, `factory_prompt` and
  `factory_answer`, or to Claude Code's CLI with `--judge claude`, which runs lean
  calls and logs each call's cost.
- Style packs: `zing`, `newsdesk`, `swiss`.
- `zing factory learn-style` learns a pack from a clip you like and checks a sample render
  against it, trait by trait. `zing factory serve` opens a local review dashboard
  (watch, rate, swap visuals, edit hook and copy, re-render).
- 4:5 renders for LinkedIn and Instagram feeds, and a `headline` pack: the clip above a
  solid panel with your source credit and the hook as a standing headline. learn-style
  detects the frame shape and a headline panel, including accent words inside a line.
- Photos move through their own depth (Depth Anything V2 Small, CPU, after
  `zing factory fetch-depth --yes`): a slow camera drift where near things slide
  against the background. Logos, page captures and flat pictures stay still; nothing
  is generated. `--no-parallax` turns it off per project or per render.
- Quote moments no longer cut to a text card. The captions take over: the speaker stays
  on screen, dimmed, while the line builds word by word in big type with its key words
  swiped by a highlighter, then steps away. One per clip. Packs set the quote face
  (`quote_font`, `quote_weight`, `quote_upper`, `quote_ink`, `quote_hl`).
- Episodes without captions are read with a small speech model already on disk just to
  find the moments; the moments get the full model. On three trending hour-long X
  episodes this cut transcription from about 50 minutes to about 6 per episode.
- Misheard names and terms are corrected in captions, graphics and copy when the plan is
  sure (sound-alikes only, never numbers), with a log line per fix.
- Site captures and helper tools no longer fail on non-ASCII output on Windows.
- The scout prefers moments that open inside a scene, a demo or a first-person claim over
  ones that open on an abstract setup or a lead-in, and how-it-works or funny moments over
  vision talk. Post copy leads with a first sentence of about ten words. Both come from
  the openings of 600 product launch videos.
- Documentary mode (`--mode documentary --pack documentary`): archival visuals only,
  full-frame stills moving through their depth, a warm black-and-white grade with grain
  and soft-focus cuts, serif captions that build word by word with the key word large in
  italic, and hand-drawn rings around a quote's key words.
- Launch mode (`--mode launch`): launch films assembled from several spans of a long
  demo or interview, landscape first, with an "Introducing" title card, an end card from
  `--brand-name`, `--brand-url` and `--cta`, name tags, launch post copy and a `launch` pack.

## Motion graphics

- Composition v2 plans accept `graphics`: `title-card`, `lower-third`,
  `callout` and `progress-bar` templates with a normalized box, one or two
  text lines, a pinned TTF/OTF font and text/accent colors. `zing render` draws
  them in the HyperFrames overlay beneath its captions. See
  [Motion graphics](docs/MOTION-GRAPHICS.md).
- Text is measured in its pinned face before rendering. A line that would
  overflow its box, or a missing glyph, fails with the largest size that fits.
- `--aspect` deliveries scale graphic text with the short side, as captions do.
- The HyperFrames offline guard allows the renderer's local `ps` process-table
  read and its Linux `ldd` check of the configured browser, so renders complete
  on Linux and macOS. Other commands and arguments stay blocked.

## Clip quality

- Match keeps source color by default. CLI `--color reference` and MCP
  `color="reference"` opt into grading; recipes and reports record the mode.
  Recipes that omit `color_mode` also default to `source`.
- Skin checks catch lost chroma and lightness as well as hue changes, and
  reference-grade skin misses appear as top-level match warnings.
- Draft captions keep one font size across groups and shots. Long phrases
  regroup when word timings are available; untimed clauses try shorter wraps.
  A size reduction applies to every caption, including mixed preset drafts.
- Moments reject filler, back-reference, additive ("We also ...") and lowercase
  openings, and stop before questions, including unpunctuated WH inversions.
  A window never ends where the next sentence continues the thought. Ranking
  favors substantive opening statements; suggestions include their first and
  last sentences.
- Draft selection trims measured face-free gaps and text cards out of candidates
  when the source has faces elsewhere. Faceless sources remain usable. A
  must-keep stays whole unless more than half of it is face-free or a slate.
- Match recipe, director, caption-fit and skin-report checkpoints are invalidated
  for the new quality policy.

## 1.0.0rc1

Release candidate for Zing v1. These highlights cover merged PRs #401 through
#452 on main.

### Long interviews

`zing moments` and the `zing_moments` MCP tool suggest complete transcript windows
with Estimated scores, reasons and ready-to-use `must_keep` JSON. Oversized
sources require a chosen moment; match then records its focused search window as
Measured in plans and reports. Audio/video duration drift up to 250 ms is accepted
with a warning; uncovered tails remain unmeasured. Match skips optional audio maps
beyond the analyzer's ten-minute limit. The MCP registry now has 37 tools.

### Studio

`zing studio` is the guided starting point. Choose a reference match, an edit
from clips, a photo meme, a style breakdown, music advice or new delivery
shapes. Save answers, resume work and review the resulting files. The
interview asks at most 10 questions on any path, offers a trim for references
over 60 s, and skips still images in a clip folder with a note. New sessions
start in the Zing workspace, never the current folder. (#429, #432, #445,
#446, #451)

### Explain

`zing explain` makes a style card from a video: cuts, transitions, captions,
color, framing and music. Use `--against` to compare with another video.
A hook and loop section reports time to first word, cut and caption, the
opening cut rate against the rest, and pixel checks for a clean loop and a
flash-forward cold open; anything not measured says unknown. Long references
take `--ref-start`/`--ref-end`, and analysis is capped at 60 s. (#424, #445,
#452)

### Screen demos

`zing plan screen` and `zing match screen` edit screen recordings with
cursor-aware auto-zoom, idle speed-up and action-timed cuts. Portrait framing
zooms until UI text is readable on a phone, without clipping the focus or
cutting text mid-word. (#443)

### Match and honest checks

Match takes a reference and your clips through planning, rendering and checks.
The director respects measured timing ranges, keeps source-cut mappings and
reports shortages when it cannot make distinct drafts. Color checks account
for scene differences and skin preservation. Missing evidence stays unknown;
a rendered file alone does not prove a style match. A moment too short for
three distinct drafts is labeled a variety limit, and short silent clips can
reach the target length by trimming the final shot, which is disclosed.
(#411, #417, #418, #431, #435, #437, #445, #451)

### Caption presets

Choose punch, box or clean captions. Word groups fit the available width,
baselines use font metrics, and highlight boxes can follow spoken words while
the surrounding phrase holds still. Positioned captions and optional
HyperFrames overlays share the composition plan. Box captions avoid
lower-thirds, numbers such as "$3,000" stay one unit with one plate per line,
and plate tops follow real glyph tops. (#404, #407, #408, #409, #412, #413,
#434, #438, #445, #450)

### Framing and aspects

Deliver 16:9, 1:1 and 9:16 from one edit. Framing options include zoomfill,
speaker-aware crops, headroom and picture-in-frame layouts. Delivery size
checks disclose low-resolution sources. Broadcast composites crop to the live
picture instead of the show graphics, a single talking head fills a 9:16
frame, and small background faces are disclosed as bystanders instead of
widening the shot. (#419, #423, #425, #434, #445, #450)

### Music

Place music around the edit, duck it under dialogue and inspect track advice.
Later mixing fixes reduce pumping and even out dialogue. Optional local audio
tagging separates vocals and instruments; speech timing repair stays bounded
by measured voice activity. (#405, #422, #427, #436)

### Memes and stills

Turn photos and a topic into concepts, contact sheets and exported stills.
Offline ideas, face-aware framing and subject-safe text support larger photos
and HEIC inputs where the decoder is available. Person and object detectors
also help protect pets from text placement. Animated meme rendering is
available for video inputs. (#402, #407, #409, #420, #425, #439)

### Setup and onboarding

Studio, doctor and setup explain missing speech models and ask before fetching
them. Downloads require HTTPS and verified hashes. Portable asset paths and
FFmpeg 9 compatibility improve setup across machines. `zing doctor` names the
missing FFmpeg capability and prints the install command for your system;
`zing setup --ffmpeg` runs it only after an explicit yes. Install,
troubleshooting and privacy guides cover Windows, macOS and Linux. (#401,
#403, #432, #440)

### Uoink

Use saved references, verified kept media and local search through Uoink's
existing service. Zing records choices and receipts, preserves real item
titles, and keeps a local workflow when the peer is absent. (#408, #415,
#421, #425)

### Agents and MCP

The agent skill, brief interview and composition tools expose local editing
workflows. The server uses the official MCP SDK 2.3 and offers 37 tools,
including studio and explain. Registry metadata and a separate manual registry
workflow prepare the listing for publication. The listing copy, registry line
and PyPI summary match across the README, MCP instructions, bundle manifest
and skill. (#407, #416, #424, #426, #429, #433, #442)

### Safety and privacy

Private handoff material is outside the public tree. Evaluation records retain
rights information, and unlicensed creator text and frames are not
redistributed. Model downloads require an explicit request; local editing does
not automatically publish media. (#414, #430, #432)

### Packaging and release

The release candidate includes runtime data and license notices in the wheel.
Fresh-install checks install common extras and all extras, list all 37 MCP
tools, call `zing_status`, and render an offline studio still on Windows,
macOS and Linux in CI. A manual release workflow builds and checks artifacts
before an environment approval gate, then uses PyPI Trusted Publishing.
GitHub releases start as drafts. No package or release was published as part
of this packaging pass. (#441)
