# CLI recipes and dependencies

Run from the installed environment. In a checkout, use `uv run --frozen zing`
instead of bare `zing`. Paths below are examples to replace with actual local
paths; `SOURCE_SLUG` and `REFERENCE_SLUG` must come from study results. Use a
fresh output directory. JSON is UTF-8 without a BOM; on Windows, prefer files
over nested JSON in native-command arguments.

## Installation and first use

Run `zing doctor` before media work. `zing setup --ffmpeg` shows the OS package
manager command and requires a typed yes in an interactive terminal. Neither
`--yes` alone nor JSON/non-interactive mode installs FFmpeg. On macOS use
`ffmpeg-full` and its keg-only PATH step. Doctor names missing libx264, libass,
drawtext and delivery filters. Preserve model-download consent separately.

The v1 guides are [Install](https://github.com/ryanbiddy/zing/blob/main/docs/INSTALL.md),
[Troubleshooting](https://github.com/ryanbiddy/zing/blob/main/docs/TROUBLESHOOTING.md),
[Privacy](https://github.com/ryanbiddy/zing/blob/main/docs/PRIVACY.md) and
[Studio](https://github.com/ryanbiddy/zing/blob/main/docs/STUDIO.md).
Until the PyPI release, use the source checkout. The planned package command
is `pipx install "myzing[all]"` or `uv tool install "myzing[all]"`.

## Choose a command

| Command | Use and boundary |
|---|---|
| `zing record-cursor` | Local 60 Hz cursor/click and anonymous key-press timestamps; never key contents. |
| `zing studio` | Guided creative session; recommendations, confirmation, saved answers and resume. |
| `zing doctor` | Dependencies, caches and optional local Uoink health; ready can coexist with absent extras. |
| `zing setup --list` | List curated packs; interactive setup can study/download references. |
| `zing explain` | Explain a local video as a style card; `--out DIR`, optional `--against VIDEO`. Offline models; URL downloads require explicit `--allow-download`. See [Explain](explain.md). |
| `zing study` | Measure a URL/local video; `--raw` adds raw-footage evidence; `--transitions` enables v6. |
| `zing factory` | `new` a project from a local episode (+ optional SRT/VTT), `run` it (host judge writes prompts; `--judge claude` asks Claude Code's CLI and logs cost), `status`, `answer`, `redo` (including `clipNN-context` to repeat a context check), `clip` (a stretch by start and end, or a scout runner-up) and `trim` (new in and out points), `render`, `review`, `approval` (local guest approval HTML with `--out FILE`), `serve` (local review dashboard: rate, see context flags, make clips from the transcript, trim), `learn-style` (a pack from a clip you like, checked against a sample render), `fetch-depth` (optional depth model that moves photos; `--no-parallax` keeps them flat), `fetch-cutout` (`--cutout` stands the speaker in front of pictures), `fetch-upscale` (sharper small photos), `packs` (`--check NAME` checks local font and logo files and font families; exits 1 on errors), `doctor`. Nothing is posted. |
| `zing channels` | Watch sources, advance local projects, check approval, queue clips and make post kits and digests. YouTube uploads and owner analytics need a connection. Publishing defaults to off. |
| `zing playbook` | Scout niches and view growth from public metadata. List/import contrasting Shorts, measure local media, request blind Gemini notes, and distill patterns. Video fetching requires `measure --download`; `notes` sends public URLs using `GEMINI_API_KEY`. CLI only; no automatic publication. |
| `zing fonts` | List/fetch the pinned font library or rank candidates from saved caption geometry; matching stays offline. |
| `zing project` | Init, scan, status, find-reference, resolve-reference and study-reference; verified local reuse without web fallback. |
| `zing brief` | New/show; save interview answers after project init, not an automatic director. |
| `zing plan choose` | Choose A/B/C from a local artifact; durable receipt, optional reference citation with --share-choice; never publishes. |
| `zing moments` | Rank complete transcript windows from a cached clip or study; Estimated reasons and must-keep JSON, no model calls. |
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
| `zing from-uoink` | Open a saved Uoink item in a factory project. Probe support, reuse its project and serve the review page until idle. |
| `zing connect` | List agent apps or print a config with `zing connect CLIENT`. `--json` includes location, notes and sources. `--deeplink` prints a Cursor or VS Code install link. Nothing is written. |

## Episode Shorts in studio

Run `zing studio` and choose 7 (path `g`) for a local episode or `uoink:<id>`.
The file must be at least 60 seconds long. The plan recommends 3 moments,
`9x16`, and `claude` if its CLI is on PATH, otherwise `host`.
An optional transcript can be SRT, VTT or word JSON. Enter skips it.
Confirm to create the factory project, then press Run on its review page.

`zing studio --no-open` prints the dashboard link and leaves the browser
closed. The same choice is available as `"no_open": true` in `--answers` JSON.
`--json` emits `project` and `page` in the final result when the server is ready.
Use `zing studio --resume <project>` to reopen it with its settings and edits.

## Hand-off with Uoink

```sh
zing from-uoink --probe --json
zing from-uoink uoink:short-123 --json --no-open
zing from-uoink uoink:short-123 --allow-download --json --no-open
zing from-uoink uoink://item/short-123 --project ./episode --judge claude --idle-minutes 30
```

`--probe` prints the supported contract, installed version and
`features: ["allow_download"]` without network access. `REF` accepts either
Uoink item form. `--json` prints one readiness envelope with the absolute
project path, dashboard URL, item reference and
the `reused` and `downloaded` flags. Errors print a JSON envelope and exit 1.

`--allow-download` permits a source download when Uoink did not keep the
video. Without it, a known source URL returns `error="download_needed"`. Downloads
go in `<project>/source/` and time out after one hour. Failures return
`error="download_failed"`. Rights stay `unknown`, so the posting gate still applies.
Progress goes to stderr as JSON lines with `--json`, or `Downloading 42%`
in plain mode. The first stdout line arrives after the download. Kept media
and reused projects report `downloaded` as `false`.

`--project DIR` chooses the project folder. By default it goes under
`<ZING_HOME or ~/.zing>/handoff/`, with a safe title slug and a short item hash.
The same item reuses its project; another project in the folder is refused.
`--judge host` is the default. Press Run on the page, then answer its pending
prompts through the factory commands or MCP tools. `--judge claude` uses
Claude Code. `--no-open` leaves the browser closed. `--idle-minutes N` sets
the limit without HTTP requests, default 60 and minimum 1 whole minute.
Ctrl+C or the idle limit stops the server with exit 0.

See the [button contract and capture behavior](https://github.com/ryanbiddy/zing/blob/main/docs/UOINK-MEMORY.md#hand-off-with-uoink).

## Channels

```sh
zing channels setup creators --niche "How creators tell stories" --candidates @one @two @three
zing channels setup creators --niche "How creators tell stories" --name "Creators" --candidates-file candidates.txt --keep 15 --min-shorts 3 --no-brief
zing channels setup creators --niche "How creators tell stories" --suggest --judge host
zing channels setup creators --from-scan zing-workspace/scout --scan-niche "Creator stories"
zing channels new stories --name "Stories" --niche "Player stories" --pack zing --mode context
zing channels source stories --id club --name "Club" --kind podcast --url https://example.org/show --rights permission --grant "Email from the owner"
zing factory new --channel stories --source club --media episode.mp4 --transcript episode.vtt
zing channels list
zing channels show stories
zing channels check stories
zing channels watch stories
zing channels brief stories --open
zing channels brief stories --takes
zing channels brief stories --date 2026-11-06 --answer script-1 answer.json
zing channels scorecard stories --days 30 --open
zing channels scorecard stories --json
zing channels flag stories --kind claim --note "Check the quote" --clip episode/clip01
zing channels tick stories another-channel --max-minutes 50
zing channels tick --all
zing channels digest stories
zing channels digest --all --out digest.md
zing channels queue stories
zing channels kit stories
zing channels connect stories --client-secret client.json
zing channels upload stories --dry-run --limit 3
zing channels upload stories --limit 3
zing channels analytics stories
zing channels disconnect stories
zing channels posted stories episode/clip01 --url https://example.org/post
zing channels skip stories episode/clip02
zing channels track stories
zing channels metrics stories --csv "Table data.csv"
zing channels learn stories
zing channels pause stories
zing channels resume stories
zing channels pause --all
zing channels resume --all
```

`setup SLUG --niche TEXT` takes `--candidates HANDLE ...`, `--candidates-file FILE`
or both. Files have one handle, YouTube channel URL or UC ID per line, with
blank lines and `#` comments ignored. Up to 40 candidates remain after removing
duplicates without regard to case. `--keep N` keeps 3 through 40 channels by
median Shorts views, default 15. `--min-shorts N` needs at least 1, default 3.
Channels also need a Short from the last 60 days. Failed feeds and unresolved
channels are dropped. At least three survivors are needed before settings change.
`--name TEXT` defaults to the slug in title case for a new channel. Setup adds
breakdown, news and clips series with manual approval. Existing channels keep
their settings except the first breakdown watch list; that series must exist.
Setup writes `setup.json` and `setup.html`, makes a brief and prints its page
path and elapsed minutes against a 15 minute target. `--no-brief` leaves the
brief time unset. Brief failures are recorded and printed with exit code 0;
setup input and channel errors exit with code 1.

`--from-scan PATH` accepts a `playbook niches` output folder or its `niches.json`.
`--scan-niche NAME` selects a niche without regard to case or surrounding spaces.
A scan with one niche selects it automatically. Other scans need `--scan-niche`.
`--niche` defaults to the scan name, clipped to 200 characters, and an explicit
value wins. It remains required without `--from-scan`.
Candidates enter from `--candidates`, then `--candidates-file`, then the scan,
then suggestions. Listed scan channels come first by descending median views,
with ties in scan order. Skipped channels follow in scan order and get fresh
feed checks too. The first occurrence of a duplicate wins. Scan candidates
beyond the 40-channel limit are left out. The JSON records the scan path, name,
date, unique candidate count and count left out. Rows added by the scan have
`"from_scan"` set to true. The page names the scan under its heading.

`--suggest` asks the judge for candidate handles. Explicit candidates come
first, then scan candidates and suggestions, with the same duplicate checks
and 40-channel limit.
It works without `--candidates` or `--candidates-file`. Each suggestion goes
through the public feed checks and can be dropped with a reason.
`--judge host|claude` defaults to the existing channel's judge, or `host` for a
new channel. New channels save that choice. With `host`, setup prints the
prompt and answer paths and exits with code 0 before changing the channel.
Write the JSON answer to the printed path and rerun the same command.
With `claude`, Claude Code's CLI answers the prompt.

`new` also accepts `--network-name`, `--network-line` and `--network-url`.
`source` adds or replaces a source and accepts optional `--expires YYYY-MM-DD`
and `--note TEXT`. Known rights need a grant. Expired grants count as unknown.

`watch SLUG` checks every source once and deduplicates items in
`sources/<source id>.jsonl`. Folder and own sources use local videos. YouTube
feeds keep only watch entries and wait for `inbox/<video id>.<ext>` or existing
Uoink media. Uoink sources search for already kept local files. Podcast feeds
download enclosures only with known rights, from public HTTP or HTTPS hosts,
up to 4 GB. Audio-only episodes wait for a video. Ready items use the shared
factory setup and inherit channel settings.

`brief SLUG [--date YYYY-MM-DD] [--answer TASK FILE] [--open]` makes or refills
the day's scripts and prints the page path. Dates use the channel timezone.
`--date` selects another day. `--answer` saves JSON for a pending `script-N`
task and fills missing scripts. `--open` opens `brief/latest.html`. Existing
picks stay fixed. Configure breakdown, news and clips series in `channel.json`.
The page shows linked receipts and claims to check before recording.

`scorecard SLUG [--days N] [--open] [--json]` compares local briefs, posted queue
rows, take measurements, outcomes and flags with the channel's bar. `--days`
sets a positive window of channel-local dates ending today, default 30.
Each run writes `scorecard.html` and `scorecard.json` in the channel folder.
`--open` opens the page. `--json` prints the result instead of row summaries.
Set `bar` in `channel.json` to override days, posts, recorded share, kept share
or the flag limit. A timed `setup.json` adds a niche-to-brief row with a fixed
15 minute target. Ready means all displayed rows pass. No network or judge is used.

`flag SLUG --kind KIND --note TEXT [--clip ID]` appends one row to `flags.jsonl`
and prints it. Kinds are `claim`, `strike`, `reused` and `other`. Notes must be
non-empty and at most 500 characters. The clip ID is optional. Scorecards count
these flags and masked outcomes within the window.

`brief SLUG --takes [--date YYYY-MM-DD]` prints recording notes without making
a brief. Notes use matched takes from the last 30 channel-local dates and need
at least three takes. New script prompts use them to follow the owner's pace,
length and wording. `--date` sets the last day of that window.

Use `source SLUG --kind recordings` with a local folder, `--rights own` and
a grant for finished takes. Each take becomes one clip of 3 through 180 seconds
without scouting. A matching open brief item supplies the hook, news peg and
series. Unmatched takes use their first 12 words as the hook. Series reach
queue rows and outcomes; `learn` reports their counts and median rewards.

`tick [SLUG ...|--all]` watches, makes the daily brief when due, advances at most one episode per channel,
queues clips and builds kits. `--max-minutes N` defaults to 50 for the whole
tick. It stops between steps when paused or out of time and records each
channel in `ticks.jsonl`. The channel's `judge` is `host` by default or `claude`.
Host runs wait at prompts until an agent answers them. A lock prevents overlap;
an abandoned lock expires after three hours. Tick exits 1 only when every
visited channel has errors. An overlapping tick exits 0.
After kits, tick uploads only when `publish.youtube` is enabled. Connected
channels fetch owner analytics once per Pacific day. Pause and time checks
also run before YouTube requests.

`digest [--all|SLUG] [--out FILE]` writes Markdown for the last 24 hours and
lists waiting work. With no slug it includes all channels. With no `--out`
it writes to stdout. Today's brief adds ready and waiting script counts and
the page path. Channels with a brief also get a scorecard count.
Scheduling examples are in the Channels guide.

Factory `new --channel SLUG` inherits the channel's factory defaults and uses
its slug for shared Post and No history. Explicit flags win. `--source ID`
uses that source's rights and credit; `--rights` overrides the label.
Brand fields default to the network name, URL and line, with the channel name
as the fallback. `--brand-name`, `--brand-url` and `--cta` override those fields.
Without a positional project path, the episode goes in the channel's
`projects/<episode stem>/`. An explicit path still works. Optional `voice.md`
guides copy prompts and allows up to 4000 characters.

Queue and kit commands check source and visual rights, context and brief
flags, the 9x16 render, copy and approval. Manual approval is the default.
Timestamped Post ratings must be newer than both the video and copy. Channel
`visuals` defaults to `cleared`; `editorial` also accepts picked visuals labeled
editorial. Unknown or missing visual rights still block.
Slots follow the channel timezone and daily cap. Own clips are spaced by
`seeding.every`; a fourth consecutive clip from one episode waits.

`kit --out DIR` changes the kit and HTML index folder. FFmpeg remuxes with
stream copy and faststart. If missing, it copies the file and reports that.
The index uses local videos and Copy buttons. Its Posted checkbox only changes
the page; `posted` and `skip` update the queue. Pause files block watch, brief, queue, kit, upload and analytics
commands. `check` exits 1 for problems; command errors exit 2.

Settings live under `<workspace>/channels/`, or `ZING_CHANNELS_HOME` when set.
Timezones need local zoneinfo data; `PYTHONTZPATH` can point at an existing
database. Each channel's About text should
name its network. See [Channels](https://github.com/ryanbiddy/zing/blob/main/docs/CHANNELS.md).

`connect SLUG --client-secret FILE` reads a Google OAuth Desktop app JSON and
opens the owner's consent flow with PKCE. Enable YouTube Data API v3 and
YouTube Analytics API in that Cloud project first. Tokens and client credentials
stay in `youtube.token`, protected with current-user DPAPI on Windows or `0600`
permissions elsewhere. `disconnect SLUG` removes that file and the connection.

Set `publish.youtube` in `channel.json` to `private` or `scheduled` to upload.
Its default `off` sends nothing. `scheduled` adds the queue slot as the publish
time only when it is at least 15 minutes ahead. All uploads start private.
YouTube locks uploads private until the Cloud project passes Google's API audit.

`upload SLUG [--dry-run] [--limit N]` takes kits due within 36 hours and rechecks
the gate. The limit defaults to 3. Dry runs send no requests and show title,
privacy, publish time, file and size. Interrupted sessions resume from
`outbox.jsonl`. Daily caps are 80 new sessions per Cloud project across the
channels home and youtube_daily_cap per channel, default 6, on Pacific days.
The category defaults to `youtube_category="22"`. A clip's `generated_media=true`
in its plan or post enables YouTube's synthetic media disclosure.

`analytics SLUG` merges owner metrics into outcomes. Missing values stay null;
total views stay separate from counts at known ages. Analytics data lags
48 to 72 hours. Setup and pause details are in
[Post to YouTube](https://github.com/ryanbiddy/zing/blob/main/docs/CHANNELS.md#post-to-youtube).

`track SLUG` needs `handles.youtube` set to an `@handle` or UC channel ID. It reads
the public feed, matches posted URLs or unambiguous queued titles, and saves
snapshots and outcomes. Run near 1h, 24h and 7d after uploads to measure those ages.
`metrics SLUG --csv FILE` merges a Studio table by video ID and reports matched
and unmatched rows. Total Studio views stay separate from counts at known ages.
`learn SLUG` writes `learned.json` with reward estimates, uncertainty, summaries
and a comparison with always choosing name-claim titles when the data allow it.
Set `prior` in `channel.json` to a playbook prior file for initial title guidance.
Relative paths start at the channel folder. See
[How a channel learns](https://github.com/ryanbiddy/zing/blob/main/docs/CHANNELS.md#how-a-channel-learns).

## Pick a niche

```sh
zing playbook niches niches.json --out zing-workspace/scout
zing playbook niches niches.json --out zing-workspace/scout --source ytdlp --min-shorts 15
zing playbook watch --channels channels.txt --out zing-workspace/scout
zing playbook velocity zing-workspace/scout
zing playbook prior zing-workspace/scout --niche "NFL stories" --out zing-workspace/scout/prior.json
```

`niches` takes a JSON object with a niches list. Each item needs a niche name and
a channels list. Optional rights, fit, money and notes inputs stay separate from
the view statistics. Rights accepts campaign, encouraged, mixed, claims,
public_domain or unknown. Fit accepts high, medium or low. Money accepts low, mid
or high. `--out DIR` holds the reports and local metadata.

`--source feeds` is the default and reads the newest 15 uploads per channel from
RSS without a key or cookies. During RSS outages, an owner-set `YOUTUBE_API_KEY`
lets Zing try the Data API for exact counts before yt-dlp. The fallback reads up
to 15 Shorts and 15 long videos. Only Shorts qualify for niche scores.
`--source ytdlp` uses the existing
flat metadata listing and also accepts known durations of at most 180 seconds.
`--min-shorts N` defaults to 15. Channels below that usable sample size are skipped
with a reason. These commands never fetch or store video, thumbnails or audio.

`watch --channels FILE_OR_HANDLES --out DIR` accepts a UTF-8 file or space-separated
handles and channel IDs. It appends one feed observation to snapshots.jsonl and
exits. Schedule it hourly to collect views by age. `velocity DIR` writes
velocity.json from those snapshots, using the nearest views within 25% of 1h,
6h, 24h, 72h and 7d. Missing observations stay null.

NICHES.md reports channel and niche statistics, supplied human inputs, title
feature lifts and original links. It copies no competitor titles. Titles stay
in the local section of niches.json, titles.jsonl and snapshots.jsonl.
`prior DIR --niche NAME --out FILE` exports counts, lifts and guidance only.
Guidance needs at least ten hits and ten misses and a lift of at least 1.5 or at
most 0.67. Set a channel's `prior` to this file to guide titles and scouts. See
[Pick a niche](https://github.com/ryanbiddy/zing/blob/main/docs/PLAYBOOK.md#pick-a-niche)
for the formula, title heuristics and hourly Windows task example.

## Label a playbook cohort

```sh
zing playbook list --channels developer-channels.txt --scope "Developer channel Shorts" --out zing-workspace/developers
zing playbook distill zing-workspace/developers --version dev-v0
zing playbook distill zing-workspace/developers --version dev-v1 --scope "Developer tutorial Shorts"
```

`list --scope TEXT` saves the label in `library.json`, including candidate imports.
`distill --scope TEXT` overrides it for that report. Without a flag or saved label,
distill uses `YouTube Shorts`. The label appears in the JSON and WHATS-WORKING
report. It does not filter entries or verify cohort membership.

Scope accepts 1 to 120 plain text characters after whitespace is trimmed and
collapsed to single spaces. This removes newlines. Empty labels and other
nonprintable characters are rejected.

List warns on stderr after saving a library with fewer than 8 distinct selected
channels. Measure warns before starting work. Both name the actual count.
Add channels or pass `--min-channels N` to distill. The warning does not stop
the run; distill still records why patterns fail its thresholds.

## Measure a playbook library

```sh
zing playbook measure zing-workspace/playbook --media-dir local-shorts
zing playbook measure zing-workspace/playbook --download --gap 3 --max-blocks 3
zing playbook measure zing-workspace/playbook --download --retry-failed
```

Local media takes precedence. Downloads require `--download`; Zing never uses
browser cookies. `--gap SECONDS` waits between download attempts, defaults to 3
and accepts 0. The first attempt starts immediately. `--max-blocks N` pauses
downloads after N consecutive bot-check or rate-limit failures. It defaults to 3
and requires at least 1. Local media and cached measurements still process.
Paused entries get no new failure record and can be tried on a normal rerun.

Failures show download_bot_check, download_rate_limited,
download_unavailable or ytdlp_missing when recognized, with a fixed hint.
Raw stderr and exception text stay out of failure records. Wait after blocks,
then use `--retry-failed` to retry only saved failures. It also works with
`--media-dir DIR`. Successful measurement files stay unchanged. `--force`
recomputes all entries and cannot be combined with `--retry-failed`. See
[Measure and retry downloads](https://github.com/ryanbiddy/zing/blob/main/docs/PLAYBOOK.md#measure-and-retry-downloads).

## Factory framing and captions

Factory renders check detected text against each shot's actual crop and output
shape. Cards stay whole when the crop would cut text, including in solo shots.
Speaker-top packs keep captions above the graphic card when avoiding a low face.
Lists with seven or more items shrink their badges and text to fit the rows.

At 1920×1080, `--pack launch` uses 89px captions, `headline` 103px and
`documentary` 117px. The default `zing` look stays at 78px. Portrait sizes and
learned packs keep their existing scaling.

## Factory transcript sync

`factory new --transcript FILE` tries up to five speech samples inside the media
before scouting and stops when two agree.
It uses a cached model and saves the result and any shift in `factory.json`.
Speech turned off, no cached model, failed probes or too little speech skip
the check with a note. Shifts keep cues inside the media and preserve originals
so an interrupted run cannot apply the offset twice.
`--offset SECONDS` supplies a known shift and skips the check, even when zero.
`--no-sync-check` skips it without shifting captions. Both flags also work with
`factory batch` for new projects. Use `factory run "PROJECT" --no-sync-check`
or `factory run "PROJECT" --offset SECONDS` to recover an existing project
before moments have been scouted. Studio offers to skip a failed check or
transcribe instead. Only matched supplied transcripts get the per-clip word check.
See [Captions from another version](https://github.com/ryanbiddy/zing/blob/main/docs/FACTORY.md#captions-from-another-version).

## Factory rights and campaign briefs

```sh
zing factory new talk --media talk.mp4 --rights permission --brief campaign.json
```

`--rights own|licensed|permission|unknown` labels source rights and defaults to
`unknown`. It never blocks a clip or grants rights. `--brief FILE` validates and
copies a JSON campaign brief to `brief.json`. Both flags also work with `batch`.
The brief can set length bounds, tags, banned terms, a disclosure and scout notes.
Length violations and missing required disclosure stop rendering that clip.
Banned terms and missing tags are review flags. See
[Rights and campaign briefs](https://github.com/ryanbiddy/zing/blob/main/docs/FACTORY.md#rights-and-campaign-briefs)
for the JSON fields. Zing does not make a clip legal.

## Factory offline projects

```sh
zing factory new launch --media demo.mp4 --transcript demo.vtt --mode launch --offline --visuals ./launch-media
zing factory run launch
zing factory status launch
```

`new --offline` saves the embargo setting. It refuses public searches, site captures,
remote video reads, model downloads and `--judge claude`. The host judge writes
prompts locally. Your media never leaves the machine and offline mode fetches nothing.
Online Claude judge prompts go to Anthropic.

`new --visuals DIR` supplies your PNG, JPG, JPEG, WebP, MP4, MOV and WebM files.
The pick step chooses from their thumbnails and credits `Your file: <name>`.
Online runs also search public sources. Picks containing your files stay with the
host judge. `status` and the review header summarize `network.jsonl` by host and
purpose. Only an empty offline ledger shows `offline: nothing fetched`.

`fetch-depth`, `fetch-cutout` and `fetch-upscale` accept `--project DIR` to use that
project's network policy and ledger. Without it, the download is not tied to a
project and is not recorded. Downloads still need `--yes`.

## Factory batch

```sh
zing factory batch ./inbox --out ./projects --judge claude --moments 4
zing factory batch ./inbox --out ./projects --watch --every 60 --limit 2
```

`--out DIR` holds one project per episode and `batch.jsonl`. Batch scans only
the inbox's direct `.mp4`, `.mov`, `.mkv`, `.webm` and `.m4v` files, oldest first.
Files must keep the same size and modification time across checks three seconds
apart. Existing projects resume and `done` projects are skipped.

`--judge host` is the default and stops at pending judgments. `--judge claude`
uses Claude Code's CLI. `--watch` repeats until Ctrl+C. `--every SECONDS` sets
the wait between passes, with a default of 60. `--limit N` caps new episode
attempts per pass, with no limit by default. Resumes do not count toward it.
Use `--limit 0` to resume only.

All `factory new` settings apply to newly created projects. Matching `.srt`,
`.vtt` or word `.json` files supply captions, in that order. `<stem>.info.json`
supplies the title, source URL, upload date and uploader or channel tag.
Explicit flags override these defaults. Existing project settings are kept.

A single pass prints a JSON object with an `episodes` list and appends it to
`batch.jsonl` with a UTC `at` timestamp. Entries have `file`, `project`, `state`,
`clips`, `pending` and `error`. Clips count once if they have any render.
`episodes[].cost_usd` is the project's total judge cost. Watch mode prints and
logs one line per processed episode. Failed episodes do not stop the rest. See
[Clip factory](https://github.com/ryanbiddy/zing/blob/main/docs/FACTORY.md).

## Factory vocabulary

```sh
zing factory new talk --media talk.mp4 --vocab "Pompliano, Starbase" --vocab "Vermilion Parish"
```

Repeat `--vocab` or separate terms with commas. The supplied spellings are saved in
`factory.json` for transcription and caption fixes. Names from the brand, source,
tag or show are not added. Limits match study vocabulary. Up to 64 terms,
80 characters per term and 500 UTF-8 bytes including comma-space separators.
Oversized lists are rejected. Set the list when creating the project.

## Factory guest approval

```sh
zing factory approval talk
zing factory approval talk --out talk/guest.html
```

Writes `talk/approval.html` by default. `--out FILE` changes the output path.
Each rendered 9x16 clip in the project's style pack includes its hook, full
transcript and any saved before/after context. The guest chooses Yes or No, adds
comments, then uses **Copy my answers** to get plain text. The page stays local.
Keep the HTML inside the project folder and share the folder as a zip so its
relative video paths still work. No MCP tool is added.

## Factory 4K output

```sh
zing factory new talk --media talk.mp4 --4k
zing factory render talk/clip01 --4k
```

Both flags save `"uhd": true` in `factory.json` for future renders. Every shape
doubles in width and height. File names stay the same. The next factory run
replaces any remaining 1080 renders. Sources below 2160 pixels on the short side
still render with one warning per run.

## Factory export

```sh
zing factory export talk/clip01 --shape 9x16 --pack zing --out talk/clip01/editor
```

`factory export` writes `speaker.mp4`, transparent ProRes 4444 `overlay.mov`,
`captions.srt`, `words.srt`, 48 kHz `audio.wav`, `timeline.xml` and `README.txt`.
Import the XML into Premiere Pro or DaVinci Resolve. It places speaker on V1,
overlay on V2 and audio on A1 at 30 fps. Text and graphics are rendered into the
overlay. Import an SRT to style new captions.

`--shape` accepts `9x16`, `4x5`, `1x1` or `16x9` and defaults to `9x16`.
`--pack NAME` defaults to `zing`. `--out DIR` defaults to `<clipdir>/export-<shape>/`.
JSON includes three composite comparisons, file sizes in bytes and elapsed seconds.
This command has no MCP tool.

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
source-image `[x,y,width,height]` boxes. Text avoids detected faces and a
model-free subject estimate (a distinct region, not a recognized pet or object);
add `--protect x,y,w,h` boxes on `meme render` and `still` when it misses one.
Choose a font covering the requested script.
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

## Edit factory clips

```sh
zing factory edit talk clip01 --rate edits --why "Fix the name"
zing factory edit talk clip01 --hook "How we built it"
zing factory edit talk clip01 --copy x "The build, in their words."
zing factory edit talk clip01 --visual v1 1
zing factory edit talk clip01 --word 12 "Starbase"
zing factory edit talk clip01 --render 1x1 --pack swiss
```

Choose one of `--rate`, `--hook`, `--copy`, `--visual`, `--word` or `--render`.
`--rate` accepts `post`, `edits` or `no`; `--why` adds a reason. `--copy` takes
a field and text. Fields are `"x"`, `"instagram"`, `"tiktok"`, `"youtube_title"` and
`"first_comment"`. `--visual` takes a request ID and candidate index from status.
`--word` takes an index in the clip's `words.json` and replacement text. Both
indices start at 0. Word timing stays unchanged. `--render` takes `9x16`, `4x5`,
`1x1` or `16x9`; `--pack` defaults to `zing` and only applies to `--render`.

Hook, visual and word edits re-render the project's shapes and pack. Hook and
word edits refresh fact checks, context and receipts. The command waits for the
edit and render, then prints JSON with any pending context task. Answer it with
`zing factory answer`, then use `zing factory run` to finish the check.

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
| screen | Optional macOS Quartz cursor recording (PyObjC); Windows uses stdlib. |
| layout | Pinned headless OpenCV; explicit MIT YuNet model fetch still required. |
| color | NumPy for SDR look matching. |
| audio-ml | Optional CED audio tags via sherpa-onnx; weights via `zing doctor --audio-model ced-mini`. |
| audio | NumPy for audio measurements. |
| factory | Study, Pillow, pinned OpenCV and NumPy for `zing factory`; Node, the sidecar and Chrome/Edge render. |
| all | All feature extras above. |
| dev | pytest, MCP and render support for development. |

Prefer uv's combined checkout install: its exclusion prevents overlapping GUI
and headless OpenCV wheels. Plain pip does not honor that exclusion.
The default Whisper model is large-v2 (about 3.1 GB); `ZING_WHISPER_MODEL` selects
another cached model or existing local model directory. Study never downloads a
speech model. Studio recommends small.en (~486 MB, English-only, less accurate)
for a first draft, with large-v2 available. `zing doctor` and `zing setup` list
cached models; `--speech-model small.en` runs the same pinned, hash-verified
fetch after an explicit yes (`--yes` when non-interactive); `--audio-model ced-mini`
does the same for the optional `audio-ml` tag weights (about 10.5 MB). RapidOCR may acquire
missing weights too. Do not run an uncached study as an offline operation.
Kokoro runtime/assets, OpenTimelineIO, and the pinned HyperFrames Node/browser/font
sidecar require separate setup and are not installed by all-extras. The v2
renderer composites HyperFrames captions with footage and audio; standalone
sidecar output is silent. Cloud ElevenLabs is outside this local workflow.

Screen demos: `zing record-cursor --out session.jsonl` records local cursor/click and anonymous key-press timestamps (no contents). Use `zing plan screen demo.mp4 --cursor session.jsonl --out screen.json`, then `zing render screen.json --aspect all`. Without a log, UI activity supplies lower-confidence targets. `zing match screen --clips <folder> --out <folder>` and Studio screen-footage answers use this continuous zoom/pan path.

For long clips, `zing moments <clip-or-study> --target 22 --top 3 --json` ranks cached
transcript windows. Add `--project DIR` to also search a match project's
`breakdowns/` folder. An explicit `breakdown.json` path works too.

`zing match` picks the top Estimated moment when a long clip exceeds the search
limit. It names the pick in the terminal and `comparison.md` and saves it for
resume. Add `--no-auto-moment` to stop for a choice. To change a pick, replace
`brief.must_keep` in the project's `brief.json`, then use `--resume` without `--answers`.
