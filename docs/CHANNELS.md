# Channels

A channel is one niche identity that gets clips from new episodes over time.
It keeps source grants, factory defaults, review history and a posting queue.
Publishing is off by default. You can upload finished kits yourself or connect
your YouTube account and enable private or scheduled uploads.
Watching can read public feeds, fetch granted podcast enclosures and read
existing Uoink media. `track` reads your public YouTube feed.

## Set up a new niche

```sh
zing channels setup streamer-lessons --niche "What small streamers can learn" \
  --candidates @creatorone @creatortwo @creatorthree --keep 15
zing channels setup streamer-lessons --niche "What small streamers can learn" \
  --candidates-file candidates.txt --no-brief
zing channels setup streamer-lessons --niche "What small streamers can learn" \
  --suggest --judge host
zing channels setup streamer-lessons --from-scan zing-workspace/scout \
  --scan-niche "Creator breakdowns"
```

Replace the example handles with channels in your niche. Supply up to 40 unique
YouTube handles, channel URLs or UC IDs. A candidates file has one per line.
Blank lines and `#` comments are ignored. Both inputs can be used together.
Duplicates ignore case. Channel URLs become handles or IDs in the watch list.

Use `--from-scan PATH` to reuse a `zing playbook niches` output folder or its
`niches.json` file. A scan with one niche selects it automatically. Otherwise,
choose a name with `--scan-niche NAME`. Names ignore case and surrounding spaces.
`--niche` defaults to the selected name, clipped to 200 characters. An explicit
`--niche` wins. Without a scan, `--niche` is required.

Candidates enter in this order.

1. `--candidates`
2. `--candidates-file`
3. Scan channels listed by median views, highest first, with ties in scan order.
   Skipped channels follow in scan order.
4. `--suggest` suggestions

The first occurrence of a duplicate wins. Extra scan candidates are left out
once 40 slots are filled. Explicit candidates and suggestions still obey the
40-channel limit. Setup checks every selected channel's current feed, including
channels the scan skipped. Fresh feed results decide the final watch list.

Use `--suggest` to ask the judge for channels in the niche. It works without
explicit candidates. Suggestions follow supplied and scan candidates, with
the same duplicate checks and 40-channel limit. They are checked against
public feeds and dropped with reasons like any candidate.

`--judge host|claude` defaults to the existing channel's judge, or `host` for a
new channel. With `host`, setup prints a prompt path and an answer path under
the channel's `setup` folder, then exits with code 0 before changing settings.
Read the prompt, write the JSON answer to the printed path and run the same
command again. The saved answer is reused. `claude` uses Claude Code's CLI.

Setup ranks candidates by median Shorts views and keeps the top 15 by default.
`--keep` accepts 3 through 40. Channels need at least three Shorts among their 15 newest uploads and a Short
from the last 60 days. Channels that mostly post long videos often drop out. Change the count with `--min-shorts N`, at least 1.
Unresolved channels, failed feeds, small samples and stale channels are dropped
with reasons. Fewer than three survivors leaves channel settings unchanged and
exits with code 1.

A new channel gets a breakdown series, a news series and an inactive podcast
clips series. It saves the chosen judge and uses manual approval and default cadence.
`--name` sets its name; otherwise the slug becomes a title-cased name.
For an existing channel, only its first breakdown watch list changes. A channel
without a breakdown series cannot use setup.

Setup saves `setup.json` and `setup.html` in the channel folder, then makes the
first brief. With `--suggest`, the JSON records the suggestions and marks which
kept and dropped channels came from them. The page marks those channels with
`(suggested)` and shows the judge's reason on hover.
With `--from-scan`, the JSON records the resolved scan path, niche, scan date,
unique scan candidate count and count left out by the cap. Kept and dropped
rows added by the scan have `from_scan` set to true. The page names the scan
under the heading.
Setup prints both page paths and the elapsed minutes. The bar is
15 minutes or less from starting setup to writing the brief page. The scorecard
adds this row when a time is recorded. With the host judge, the brief can have
pending script prompts to answer. `--no-brief` saves only the channel and setup
report. A brief failure leaves the channel saved, records `brief_error`, prints
the error and exits with code 0. Retry with `zing channels brief streamer-lessons`.

## Start a channel

```sh
zing channels new gridiron-lore --name "Gridiron Lore" \
  --niche "NFL players telling stories from podcasts" \
  --network-name "Replay Ryan Network" \
  --network-line "Part of the Replay Ryan network." \
  --network-url https://example.org --pack zing --mode context
zing channels source gridiron-lore --id club --name "Club" --kind podcast \
  --url https://example.org/show --rights permission --grant "Email from the owner"
zing factory new --channel gridiron-lore --source club --media episode.mp4 --transcript episode.vtt
zing channels show gridiron-lore
zing channels check gridiron-lore
```

The factory command prints the project path. Run and review that project with
the usual factory commands. Factory runs retain their existing network settings.
Use `--offline` when a factory project must work only with local media.

Channel factory settings supply defaults. Explicit factory flags win.
`--source ID` supplies the source credit and its effective rights label.
`--rights` can override that label. An expired grant counts as unknown.
Network name, line and URL supply the brand name, CTA and URL. Override them
with `--brand-name`, `--cta` and `--brand-url`.

Without a positional project path, the project goes in the channel's
`projects/<episode stem>/` folder. An explicit project path still works;
the channel queue scans only projects directly under its `projects/` folder.
Post and No ratings use the channel slug as the factory show, so later episodes
learn from the same history.

Every channel's About text should say which network it belongs to.

## Files and settings

The default root is `<workspace>/channels/`. `ZING_CHANNELS_HOME` replaces it.

```text
channels/
  PAUSE
  gridiron-lore/
    channel.json
    voice.md
    sources/
      club.jsonl
    inbox/
    projects/
      episode/
        factory.json
        clip01/
    queue.jsonl
    ticks.jsonl
    youtube.token
    outbox.jsonl
    youtube-quota.json
    youtube-analytics.json
    kits/
      index.html
    PAUSE
```

`voice.md` is optional free text, up to 4000 characters. It guides new title
and caption prompts. Existing copy stays as it is.

`channel.json` uses schema version 1. Edit it to set factory defaults, handles,
cadence, approval and seeding. `zing channels check SLUG` validates it and exits
with code 1 if it finds a problem. Setup input and channel errors also exit
with code 1. Other command errors exit with code 2.

- `factory` accepts `pack`, `mode`, `shapes`, `moments`, `focus`, `vocab` and
  `brief`. Empty settings use factory defaults. Shapes must include `9x16`.
  The brief uses the [factory campaign rules](FACTORY.md#rights-and-campaign-briefs).
- Sources have an ID, name, kind, URL and rights record. Kinds are `youtube`,
  `podcast`, `uoink`, `folder`, `own` and `recordings`. The watcher checks these sources.
  Rights are `own`, `licensed`, `permission` or `unknown`. Known rights need
  non-empty `grant` text. `--expires YYYY-MM-DD` expires after that date;
  `--note TEXT` saves a note. Repeating a source ID replaces its record.
- `handles` stores YouTube, TikTok, Instagram and X handles. They do not connect
  accounts. The kit's link back uses the first non-empty handle in that order.
- `cadence` defaults to `per_day` 3, `times` of `12:00`, `17:00` and `20:00`,
  and `timezone` `local`. Times use `HH:MM`. `per_day` allows
  1 through 24 clips per day. The queue uses the next available times until
  that limit is reached. Fewer times mean fewer slots.
- `timezone` is `local` (this computer's clock, daylight saving included), a
  fixed offset such as `UTC-08:00`, or a name such as `America/Los_Angeles`.
  Names need time zone data; Windows Python has none until `pip install tzdata`.
- `approval` defaults to `policy` `manual`, `veto_hours` 6 and `manual_first` 30.
  `seeding.every` defaults to 8.
- `judge` is `host` by default, or `claude` to use Claude Code's CLI during ticks.
- `visuals` is `cleared` by default, or `editorial`. Editorial accepts screenshots
  of public pages used as commentary, so a person must judge whether that use is appropriate.
- `publish.youtube` is `off` by default, or `private` or `scheduled`.
  `youtube_category` is a category ID string and defaults to `"22"`.
  `youtube_daily_cap` defaults to 6. Zero prevents new upload sessions.

## What the gate checks

Each check writes `clipNN/gate.json` with `publishable` and `blockers`.
A clip waits if any of these apply.

- Project source rights or the current registered grant are unknown or expired.
- A picked visual has rights other than `cleared` or `attribution`, unless the
  channel allows `editorial`. Unknown or missing visual rights always block.
- `context.json` is missing, has an error or has flags.
- A project has `brief.json` but the clip has no `brief_check.json`, or the
  brief check has errors or flags.
- The project's `9x16` render or `post.json` is missing. Non-default packs use
  `clipNN/clip-<pack>.mp4`.
- The post copy contains a local file path (a `file:` link, a drive path or a
  network share), so nothing private ends up in a public description.
- The clip is rated No or still needs approval.
- The channel or the whole network is paused.

Manual approval needs a Post rating. Post with edits still waits. Veto approval
allows Post immediately, or an unrated clip once its render is at least
`veto_hours` old. Auto approval allows unrated clips only after `manual_first`
clips have entered the queue with a Post rating. Until then it uses manual
approval. Kits and posted rows count toward that history; skipped rows do not.
Queue rows retain whether they had manual approval when they entered.

A timestamped Post rating must be newer than both `clip.mp4` and `post.json`.
An edit after approval blocks the clip with “edited after approval” until it is
rated Post again. This applies to every approval policy. Older ratings without
timestamps keep their previous behavior.

## Watch sources

```sh
zing channels watch gridiron-lore
```

Watch checks each source once. `sources/<source id>.jsonl` keeps one row per
item with `id`, `title`, `url`, `published`, `found_at` and `state`. Later runs
update that row without adding the item again. Unknown dates stay empty.

- `folder` scans the local folder in `url` for `mp4`, `mov`, `mkv`, `webm` and
  `m4v` files. It does not scan subfolders. `own` works the same way and marks
  items as own so their clips follow the queue's seeding rule.
- `youtube` accepts an @handle, UC ID or channel URL. It uses the public upload
  feed and keeps only `/watch` entries. Shorts are skipped. Feeds contain only
  the newest uploads, so a long gap between runs can miss episodes.
  YouTube media is never downloaded. Put a video in `inbox/<video id>.<ext>`
  or keep it in Uoink first. Previously found items can become ready even after
  they leave the feed.
- `podcast` reads RSS items with a `video/*` or `audio/*` enclosure. With effective
  rights of `own`, `licensed` or `permission`, it saves the enclosure in `inbox/`.
  Downloads require HTTP or HTTPS and public hosts, including every redirect.
  The size cap is 4 GB. Attempts and byte counts go in the channel's
  `network.jsonl`. Incomplete downloads do not become ready. Audio episodes
  remain marked “audio only, needs a video” and never start projects.
- `uoink` treats `url` as a search query. It reads the existing search and
  kept-media bridge and keeps only items with a local file that still exists.
  YouTube matching uses the source URL or video ID. Search returns up to 20
  candidates. Missing media, an unavailable bridge or an unconfigured bridge
  leaves items waiting. The watcher does not ask Uoink to fetch anything.

Unknown or expired rights leave an item at `found, needs rights`. It cannot
start a project or trigger an enclosure download. Once rights are granted,
later watches can use the saved discovery.

A ready video starts one project in `projects/<safe stem>/`. The stem includes
the source and a stable item suffix. Creation uses the same channel settings
as `factory new --channel SLUG --source ID`, with the item's title, URL and date.
A matching caption file is used when present. Starting a project does not run it.

## Run one tick

```sh
zing channels tick gridiron-lore
zing channels tick gridiron-lore another-channel --max-minutes 50
zing channels tick --all
zing channels digest --all --out digest.md
```

A tick checks pause files, watches sources, makes a daily brief when due,
advances at most one unfinished episode per channel, queues clips and builds kits.
Public tracking runs next when a YouTube handle is set. It links manual posts
before uploads run. Uploads run only when `publish.youtube` is enabled.
Connected channels fetch owner analytics once per Pacific day, including when
publishing is off. Incomplete runs can retry after an hour. `youtube-analytics.json`
records the last attempt and whether it completed.
Host-judge channels stop at pending prompts until an agent answers them with
`zing factory answer` or the existing factory MCP tools. Later ticks resume them.
Projects with unknown or expired source rights do not advance.
Missing sources leave an error for that project while other projects can run.
Failed projects and projects with failed clips get at most two retries.
`tick_attempts.json` records the retries. Later ticks skip them with a note
so newer episodes can run.

`--max-minutes` defaults to 50 and limits the whole tick. Pause and time checks
run between steps, clips and enclosure chunks. A running model call or render
finishes before the next check. Saved work resumes on the next tick.

Each visited channel gets a `ticks.jsonl` summary with `at`, `found`, `started`,
`advanced`, `queued`, `kits`, `blocked`, `pending`, `errors` and `seconds`.
Counts describe this pass. Blockers and pending prompts include the affected
project or clip. A channel error leaves the next channel free to run. Tick exits
1 only when every visited channel has errors. An overlapping tick exits 0 with
“another tick is running”. The channels root holds `tick.lock` with its PID and
start time. An abandoned lock expires after three hours.

Digest writes Markdown to stdout, or to `--out FILE`. Pass a slug to read one
channel or `--all` for all channels. With neither, it reads all channels.
It counts items found, projects started, clips made and slots queued in the
last 24 hours. It also lists current kits waiting to be posted, blocked clips,
sources needing rights, pending judge prompts and recent tick errors.

## Run it every hour

Create these tasks in Windows Task Scheduler with full paths to your installed
executable and digest file. Run them under the same Windows account and with
the same `ZING_CHANNELS_HOME` as your regular commands. Quote any paths with
spaces inside the task's `/TR` value.

```text
schtasks /Create /SC HOURLY /TN "Zing channels" /TR "<full path to zing.exe> channels tick --all"
schtasks /Create /SC DAILY /ST 07:30 /TN "Zing channels digest" /TR "<full path to zing.exe> channels digest --all --out <full path to digest.md>"
```

The second task writes the digest at 7:30 AM. To pause work, create `PAUSE` in
the channels root or run `zing channels pause --all`. A channel's own `PAUSE`
file pauses just that channel. A person still handles sign-in, rights grants
and claims. Host-judge channels wait at prompts until an agent answers.

## Queue and kits

```sh
zing channels queue gridiron-lore
zing channels kit gridiron-lore
zing channels posted gridiron-lore episode/clip01 --url https://example.org/post
zing channels skip gridiron-lore episode/clip02
```

The queue scans `projects/*/clipNN`, checks the gate and assigns free slots in
the channel timezone. It never uses a past slot or queues the same clip twice.
Existing slots stay reserved, including skipped rows. Clock changes cannot
produce duplicate slots. A local time skipped by daylight saving is omitted.

At most one clip from a source of kind `own` or `recordings` fits in any `seeding.every`
consecutive cadence slots. Empty slots count, so extra own clips can wait for
a later date. No more than three consecutive queued clips can come from one
episode. Extra clips wait until another episode can break the run.

The queue command prints the added count, blockers by clip ID and the next
free slot. `show` prints settings, counts by status, the next upcoming queued
slot and whether the channel is paused. With no upcoming clips it shows the
next free slot. `list` prints all channel settings.

Each kit lives in `kits/<YYYY-MM-DD-HHMM>-<project>-<clip>/`. It contains
`video.mp4`, `youtube.txt`, `tiktok.txt`, `instagram.txt`, `x.txt`,
`first_comment.txt` and `post.json`. The JSON retains the copy fields and adds
the slot, channel, source ID, rights and gate result.

YouTube text starts with the title, a blank line and the YouTube description
if supplied, otherwise the Instagram caption. It then adds the source credit,
network line and URL, and a link back to the channel when a handle is set.
FFmpeg remuxes the video with stream copy and faststart. If FFmpeg is missing,
the original file is copied and the command reports that it was not remuxed.

`kit` rechecks the gate before making files and marks each finished row `kit`.
Repeat runs rebuild a kit when the clip's render or copy is newer. The folder
keeps its name. Uploads refuse stale kits until you run `zing channels kit SLUG`.
Kits with an upload in progress stay unchanged. `kit --out DIR` chooses another
output folder. Open its `index.html` to watch videos and copy text. Its Posted checkboxes
only change the open page. Use `posted` to save that status in the queue;
`--url` records the platform URL without opening it.

## Post to YouTube

Nothing uploads while `publish.youtube` is `off`. Connecting an account does
not change that setting. To enable uploads, first create a Google Cloud project.
Enable YouTube Data API v3 and YouTube Analytics API. Set up its OAuth consent
screen, create an OAuth client of type Desktop app and download its JSON.

```sh
zing channels connect gridiron-lore --client-secret client.json
```

The command prints a consent URL and opens your browser. Sign in yourself as
the channel owner and grant upload, YouTube read and Analytics read access.
Zing uses PKCE and a temporary loopback listener on `127.0.0.1`. It checks the
returned state before exchanging the code.

The channel ID, title and connection time go in `channel.json`. Tokens and
client credentials go only in `youtube.token`. Windows protects that file
with DPAPI for the current user. Other systems use permissions `0600`.
Access tokens refresh as needed. If refresh fails, run `connect` again.
Keep the downloaded client JSON private too.

Edit `channel.json` to choose a publish policy.

```json
"publish": {"youtube": "private"}
```

- `off` sends no uploads, including unfinished sessions.
- `private` uploads privately. You make the video public yourself.
- `scheduled` uploads privately with `publishAt` set to the queue slot or
  15 minutes from now, whichever is later, rounded up to a whole minute.

YouTube locks uploads from unaudited Cloud projects private until the project
passes Google's API audit. Setting `scheduled` does not remove that limit.
`zing channels show SLUG` also reports it.

```sh
zing channels upload gridiron-lore --dry-run --limit 3
zing channels upload gridiron-lore --limit 3
zing channels analytics gridiron-lore
zing channels disconnect gridiron-lore
```

Upload takes `kit` rows with slots from now through the next 36 hours. It checks
the gate again and reports blockers for skipped clips. `--limit` defaults to 3.
`--dry-run` shows the title, privacy, publish time, video path and byte count.
It sends no requests and needs no connection.

The upload uses the title and description from the kit's `youtube.txt` and
the category from `youtube_category`. Videos are marked as not made for kids.
Set `generated_media` to `true` in a clip's `plan.json` or `post.json` when it
contains generated media. A visual's `generated` flag also sets YouTube's
synthetic media disclosure. Otherwise that disclosure is false.

Video bytes travel in 8 MB chunks. `outbox.jsonl` saves the session before the
first chunk. Later runs resume unfinished sessions, even after their slots
pass. Keep those kits intact. A saved video ID prevents another upload and
repairs the queue if the process stopped while saving. Finished rows become
`posted` with the Shorts URL, video ID and upload time.

Zing starts at most 80 uploads per Cloud project per Pacific day across channels
in the same channels home. Each channel also has `youtube_daily_cap`, default 6.
The channel and home each keep `youtube-quota.json`. Starting a session reserves
a count. Failures before the session is saved return that count. Saved sessions
keep their count, and resuming does not reserve another. Google may impose lower
limits. A quota or upload-limit response stops the run and is recorded
until the next Pacific day. Server errors retry after 1, 4 and 16 seconds, then
leave the session for a later run.

Create `PAUSE` in the channels home or the channel folder to stop uploads before
the next request. `zing channels pause --all` pauses every channel.
`disconnect` deletes the local token and connection record. It keeps posted
videos and upload history.

Analytics merges views, engaged views, average view percentage, average view
duration and subscribers gained into `outcomes.jsonl`. Missing metrics stay null.
Total views use the `views` field; counts at 1h, 24h and 7d stay separate.
Report dates use Pacific time. Analytics data lags 48 to 72 hours. Connected ticks
request it once per Pacific day and retry incomplete runs after an hour.
The `analytics` command can retry a failed request sooner.

## Daily brief and recorded takes

Add `series` to `channel.json` to choose the kinds of stories you want each day.
A series has a unique ID, a name and a daily pick limit. This example has one
breakdown series, one news series and one clips series. Replace the example
handles and feed URL with the sources you want to follow.

```json
{
  "series": [
    {
      "id": "breakdowns",
      "name": "What got watched",
      "kind": "breakdown",
      "watch": ["@examplecreator"],
      "per_day": 2,
      "min_multiple": 3,
      "lesson": "End with one opening move a creator can try."
    },
    {
      "id": "changes",
      "name": "Platform changes",
      "kind": "news",
      "watch": ["@exampleplatform"],
      "feeds": ["https://example.org/platform.xml"],
      "per_day": 1,
      "lesson": "End with what to check before the next upload."
    },
    {
      "id": "clips",
      "name": "From the show",
      "kind": "clips",
      "per_day": 0
    }
  ]
}
```

`series` defaults to an empty list. Names allow 60 characters and optional
lessons allow 400. `per_day` accepts 0 through 10 and defaults to 2 for breakdowns,
1 for news and 0 for clips. Breakdown and news series accept up to 40 YouTube
handles or UC IDs in `watch`. A breakdown needs at least one. Only news accepts
`feeds`, with up to 10 HTTPS URLs. Only breakdowns accept `min_multiple`, from
1 through 1000, default 3. Clips series collect nothing for the brief; their
Shorts come from channel sources. `show` lists each series and its watch count.

```sh
zing channels brief creators --open
zing channels brief creators --date 2026-11-06
zing channels brief creators --date 2026-11-06 --answer script-1 answer.json
```

The brief uses the channel's local date. It saves `brief/YYYY-MM-DD/brief.json`
and `brief.html`, with a page copy at `brief/latest.html`. Repeat runs fill
missing scripts and rebuild the page. They keep the same picks. IDs saved in
`brief/seen.json` prevent repeat picks on later days.

Breakdowns normally read public YouTube RSS metadata and exact view counts for the
newest 15 uploads. They fetch no media. The baseline is the median view count
of at least five uploads that are two or more days old. Picks must be 1 through
21 days old, have at least 10,000 views and meet `min_multiple`. The largest
multiples come first. Failed channels go in `brief/errors.jsonl`.
News series collect platform updates. If the news collector is unavailable,
that series gets an error and the other series still run.

The judge drafts 70 to 110 spoken words, aiming for 30 to 40 seconds. It uses
the channel name, niche, optional `voice.md`, series lesson and prior title
guidance. Each script tells the story first and ends with a move viewers can
copy. The page shows its linked receipt, hook, script, move, title and claims
to check. Nothing in the brief is a fact unless it is in the receipt. Treat
explanations of why something worked as a read and verify extra claims before
recording. The prompt forbids invented numbers, quotes and private-life claims.

With the host judge, each item waits at `brief/YYYY-MM-DD/pending/script-N.md`.
Answer with JSON containing `hook`, `script`, `move`, `title` and a `check` list.
Use `--answer TASK FILE` to save it and refill that day's brief. A bad answer or
failed series is recorded in the brief and leaves the other items free to run.
Ticks make the brief once per local day after watching sources. Digest reports
how many scripts are ready and how many need answers, with the page path.

Create a folder for finished takes and register it as a `recordings` source.
Use an absolute folder path. Recordings require `own` rights and a grant.

```sh
zing channels source creators --id takes --name "My takes" --kind recordings \
  --url /path/to/recordings --rights own --grant "Recorded by me"
zing channels watch creators
```

Each media file is one take. The watcher transcribes it and compares its content
words with open scripts from the last 14 local dates. A match needs at least
35% of a script's distinct content words. The highest share wins; ties use the
newest brief. The match supplies the hook, receipt as the news peg, source link
and series. The brief item becomes `recorded` and points to its project.

Matched takes also save how much of the script you kept, your opening and the
spoken length. After at least three takes in the last 30 channel-local dates,
new script prompts use notes on your pace, length and wording, with examples
of hooks you changed. The brief page shows the share kept and the take's duration.
Run `zing channels brief creators --takes` to read the notes without making a brief.

The whole spoken take becomes one hand-picked clip, from its first word to its
last. That spoken span must be 3 through 180 seconds long. A failed transcription
or an invalid spoken span leaves a source error and starts no project. With no
match, the hook uses the first 12 transcript words and there is no news peg or
series. The factory reuses the transcript and skips scouting. Sentence snapping
may drop a leading "so" or "okay" but never cuts the end of a take. A matched
take's first comment links the video or post it talks about. Its usual graphics,
gate, queue and kits take over. Recordings follow the same seeding limit as own sources.
A changed file clears any cached transcript before a project is created.
Series stay in clip arms, queue rows and outcomes. `learn` adds each series's
count of unmasked rewards and median reward. The bandit does not choose series.

## Record on your phone

Use a dedicated synced folder for takes in OneDrive, iCloud Drive or Google Drive
for desktop. Do not point a recordings source at a whole camera roll. Save each
take into the dedicated folder from your phone's share sheet.

Edit the recordings source in `channel.json`. Set `require_match` to `true` and
`since` to today's date. Replace the example date and paths below. Add
`phone_folder` at the top level to copy the latest brief into a synced folder.

With `phone_folder` set, `zing channels kit SLUG` also copies approved kits and
their post copy into `<phone_folder>/<slug>-kits/`. Open its `index.html` on your
phone to play clips and copy text before uploading in the platform's app.
Posted or skipped kits leave this folder on the next kit run or tick.

```json
{
  "phone_folder": "C:/Users/ExampleUser/OneDrive/Zing/briefs",
  "sources": [
    {
      "id": "takes",
      "kind": "recordings",
      "name": "My takes",
      "url": "C:/Users/ExampleUser/OneDrive/Zing/takes",
      "rights": {"status": "own", "grant": "Recorded by me"},
      "settle_seconds": 120,
      "since": "2026-11-06",
      "max_seconds": 180,
      "require_match": true
    }
  ]
}
```

- `settle_seconds` defaults to 120. A newer modification time leaves the file
  `found, still syncing` until a later watch or tick. Set it to 0 to disable the wait.
- `since` skips files modified before that date in UTC. They do not enter the
  source log. Without it, all dates are eligible.
- `max_seconds` defaults to 180 and accepts any positive finite number. Longer
  or unreadable videos are skipped before transcription.
- `require_match` defaults to `false`. When `true`, a take must match an open
  brief item. An unmatched take leaves no project or staging folder.

These four settings apply only to recordings sources. Skipped files keep their
reason in the source log and are retried only when their size or modification
time changes. Waiting and skipped takes create no projects.

Run `zing channels check creators` after editing the settings. Run
`zing channels brief creators` to write `creators-brief.html` in `phone_folder`,
then open that file from the synced folder on your phone. The page includes its
own styles and copy button. Prompt paths appear as text; receipt links open the
original web pages. A phone-folder write failure is saved in the brief's errors
and leaves the local brief available.

## Scorecard

Check the channel against your bar with local briefs, queue rows and outcomes.
No network or judge is used.

```sh
zing channels scorecard creators --open
zing channels scorecard creators --days 14 --json
zing channels flag creators --kind claim --note "Check the source quote" --clip episode/clip01
```

Each run writes `scorecard.html` and `scorecard.json` in the channel folder.
`--open` opens the page. `--json` prints the saved result instead of the row
summary. The window defaults to 30 channel-local dates, including today.

- Days counts calendar days from the first brief through today, including both
  dates. The default target is 30. Earlier briefs still count outside the window.
- Posts counts queue rows marked `posted` within the window. It uses `posted_at`,
  or the slot when that is missing. The default target is 60.
- Recorded is the share of brief items marked `recorded`. Only items in the
  window whose brief date is at least two days old count. It needs 10 items and
  a share of at least 0.6. The detail shows recorded and total counts per series.
- Kept is the median `take.kept` share among recorded items in the window.
  It needs three numeric values and a median of at least 0.7. Older items
  without take measurements are ignored.
- Median views compares the newer half of measured posts with the older half,
  ordered by posting time. It uses `views_7d`, falling back to numeric
  `views_24h`. It needs 10 posts, and the newer median must be higher. An odd
  extra post goes in the newer half. Details include per-series medians.
- Flags counts logged flags and outcomes with `masked` set to `true` in the
  window. The default limit is zero. Details give counts by kind.
- Niche to first brief appears when `setup.json` has elapsed minutes. It passes
  at 15 minutes or less and is independent of the date window.

Rows with too little data say `not enough data`. Ready means all displayed rows pass.
Corrupt files and invalid brief folders are skipped and listed in `problems`.
The digest adds a scorecard count for channels with a brief.

Set an optional `bar` object in `channel.json` to override the following defaults.
Values must be nonnegative numbers. Missing keys keep their defaults.

```json
"bar": {"days": 30, "posts": 60, "recorded": 0.6, "kept": 0.7, "flags": 0}
```

`--days` changes the window without changing the bar. The median views row
always requires improvement over the earlier half. The setup target stays at 15 minutes.

Use `flag` to append a claim, strike, reused-content issue or other note to
`flags.jsonl`. `--kind` accepts `claim`, `strike`, `reused` or `other`.
`--note` requires non-empty text of up to 500 characters. `--clip` is optional.
Each flag uses the time it was logged. Invalid flag lines are skipped and
reported while valid lines still count.

## Pause work

```sh
zing channels pause gridiron-lore
zing channels resume gridiron-lore
zing channels pause --all
zing channels resume --all
```

Pause creates a `PAUSE` file. Watch, brief, track, queue, kit, upload and analytics
commands refuse while either the channel file or the root file exists.
A pause takes effect between steps and requests. It does not interrupt a render.
Ticks stop at their next check.
Resuming one channel leaves the root
pause in effect. Pausing does not remove existing kits or queue rows.

## How a channel learns

Set `handles.youtube` in `channel.json` to your `@handle` or `UC` channel ID.
After uploading clips, run these commands.

```sh
zing channels track gridiron-lore
zing channels metrics gridiron-lore --csv "Table data.csv"
zing channels learn gridiron-lore
```

Run `track` near one hour, one day and seven days after each upload. It saves
public view counts in `snapshots.jsonl`. It matches a posted URL by video ID,
or a queued clip or kit by title. Title matching ignores case and extra spaces
but keeps emoji. Ambiguous titles wait for `posted --url`. A match saves the
feed's publish time and marks the queue row posted.

`outcomes.jsonl` holds one row per posted clip. Counts at 1h, 24h and 7d use
playbook's nearest snapshot within 25% of the target age. The 1h count stays
empty if the first observation came after two hours. Missing windows stay empty.
The feed keeps only the newest 15 uploads, so frequent uploads can lose coverage.
During feed outages, rounded counts still allow matches but do not fill measured
view windows or teach the bandit.
No video, audio or thumbnails are fetched.

`metrics --csv FILE` reads a YouTube Studio table export. Headers ignore case.
It needs Content or Video for the video ID, Views, Average percentage viewed
and Subscribers. It reports matched and unmatched rows. Total views go in
`studio_views`; they do not replace counts at a known age. Average percentage
viewed and subscribers go in `avg_view_pct` and `subs`. Later tracking keeps them.

A clip's reward is `log2((views + 50) / (median + 50))`. The median comes from
the channel's latest 30 clips with a count at that age. Seven-day counts take
precedence over 24-hour counts. Fewer than five measured clips at the chosen
age leave the reward empty. Adding 50 softens swings at low view counts.
A positive reward means above typical views; a negative reward means below.

If the latest five posts all fall below 20% of the preceding 30 posts' median
24-hour views, `track` reports a reach drop and masks those five. All 35 need
24-hour counts for this check. Masked rows stay in the log and stop teaching
the bandit or steering the scout. Their masks persist on later runs.

Each generated clip has `arms.json`. It records its archetype, title pattern,
rendered length, graphics density and pack. Short means under 29 seconds, mid
means 29 through 45, and long means above 45. Heavy means at least six graphics
per minute in the final plan; light means fewer. The queue adds the slot's
local hour and keeps a copy of the arms on its row.

The bandit keeps a separate reward estimate for each value in each dimension.
It uses a Normal mean with variance 1 and a prior worth two clips at reward 0.
Title choices use `name_claim` as an editorial baseline 10% of the time when
offered and allowed. Another 15% chooses uniformly. The rest samples the
reward estimates. The queue samples a waiting archetype and takes its first
clip, while keeping the existing episode and seeding limits.

The variety rule excludes a value used by at least five of the last ten queued,
kit or posted clips, unless it is the only candidate. If every candidate is
excluded, the queue waits and copy keeps its original title without a logged
choice. Each sampled title and queue choice records its policy and estimated
probability. The estimate uses 400 seeded draws with the uniform share included
exactly. Offered title patterns that remain allowed are saved for comparison.

Optionally set `prior` in `channel.json` to a `PRIOR.json` from `zing playbook prior`.
Relative paths start at the channel folder. Strong title-feature lifts set a
small starting preference, capped at rewards of -1 and 1. Weak lifts are ignored.
The prior's guidance and up to five high and five low results guide the next
scout. Existing Post and No guidance stays in place.

`learn` writes `learned.json` and prints it. For each value, `n` counts unmasked
rewards, `mean_reward` is their average, and `posterior_mean` includes the prior.
`posterior_sd` shows uncertainty. `probability_best` uses 2,000 seeded draws to
estimate how often that value beats the others. The summary expresses rewards
as approximate view multiples with the same 50-view smoothing.

The `ips` comparison estimates an always-name-claim baseline by weighting each
observed name-claim reward by the inverse of its saved choice probability.
It compares that estimate with the logged policy's average reward, on rows
where name-claim was allowed. It skips with a reason below 20 usable rows or
without baseline examples. Small samples can swing sharply.

This is a small-data experiment engine. It is not deep reinforcement learning.
No model weights change. Views are noisy, the dimensions are treated separately,
and the report shows associations rather than proof that a title or edit caused
more views. Length, density, pack and hour are measured; their settings still
come from your plan, factory defaults and cadence.

## Platform news

News candidates come from RSS or Atom feeds and public YouTube upload metadata.
When both `feeds` and `watch` are empty, the sources are the YouTube Official Blog,
Meta's Instagram newsroom, Creator Insider uploads and YouTube Creators uploads.
No videos are downloaded. TikTok, Twitch and X publish no feed, so they are not read.

When YouTube's feed returns 404 or a server error, or the connection fails, Zing
asks the YouTube Data API first if you have set `YOUTUBE_API_KEY` in the process
environment. Counts and dates stay exact. Each channel uses about 3 of the 10,000
free daily quota units. Zing only reads the key you set. It sends the key in a
header, never in a URL or log, and refuses redirects. `zing doctor` reports only
whether the key is set.

Without the key, or if the API fails, Zing reads public metadata with yt-dlp.
It uses no cookies and downloads no media. Both paths read up to 15 videos and
15 Shorts. With yt-dlp, video dates and rounded counts are marked approximate,
and receipts say "about 88,000 views". Shorts use exact dates and counts from
one extra yt-dlp call. Shorts with missing metadata are skipped. YouTube watch
sources still use only long-form videos. Each attempt is saved in
`feed-fallbacks.jsonl` under the caller's output folder. API attempts add `source`
as `api` or `ytdlp`; an API failure also adds `api_error` without the key. If
yt-dlp is missing, run `zing doctor`.

Items must have an HTTPS link and a date within the last 10 days, with up to one
hour allowed for clock differences. Each matched keyword group adds points for
money, reach, format, policy or creators, while off-topic terms subtract three.
Candidates need at least four points and sort by score, then newest first.
Duplicate links keep their first entry. Failed sources are skipped and recorded
in the channel's `brief/news-errors.jsonl`.
