# Channels

A channel is one niche identity that gets clips from new episodes over time.
It keeps source grants, factory defaults, review history and a posting queue.
`zing channels` keeps local files and never posts, uploads or signs in.
`track` reads your public YouTube feed. You upload the finished kits yourself.

`zing channels` saves its work in local files. Watching can read public feeds,
fetch granted podcast enclosures and read existing Uoink media. It never posts,
uploads, signs in or creates accounts. You upload the finished kits yourself.

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
    kits/
      index.html
    PAUSE
```

`voice.md` is optional free text, up to 4000 characters. It guides new title
and caption prompts. Existing copy stays as it is.

`channel.json` uses schema version 1. Edit it to set factory defaults, handles,
cadence, approval and seeding. `zing channels check SLUG` validates it and exits
with code 1 if it finds a problem. Other command errors exit with code 2.

- `factory` accepts `pack`, `mode`, `shapes`, `moments`, `focus`, `vocab` and
  `brief`. Empty settings use factory defaults. Shapes must include `9x16`.
  The brief uses the [factory campaign rules](FACTORY.md#rights-and-campaign-briefs).
- Sources have an ID, name, kind, URL and rights record. Kinds are `youtube`,
  `podcast`, `uoink`, `folder` and `own`. The watcher checks these sources.
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

## What the gate checks

Each check writes `clipNN/gate.json` with `publishable` and `blockers`.
A clip waits if any of these apply.

- Project source rights are unknown, or its registered grant has expired.
- A picked visual has rights other than `cleared` or `attribution`, unless the
  channel allows `editorial`. Unknown or missing visual rights always block.
- `context.json` has flags, or `brief_check.json` has errors or flags.
- The `9x16` render at `clipNN/clip.mp4` or `post.json` is missing.
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

A tick checks pause files, watches sources, advances at most one unfinished
episode per channel, queues clips and builds kits. If a YouTube handle and a
channel `track` command are available, tracking runs last. Otherwise it is skipped.
Host-judge channels stop at pending prompts until an agent answers them with
`zing factory answer` or the existing factory MCP tools. Later ticks resume them.
Projects with unknown or expired source rights do not advance.

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
file pauses just that channel. A person still handles accounts, rights grants,
posting and claims. Host-judge channels wait at prompts until an agent answers.

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

At most one clip from a source of kind `own` fits in any `seeding.every`
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
Repeat runs leave finished kits alone. `kit --out DIR` chooses another output
folder. Open its `index.html` to watch videos and copy text. Its Posted checkboxes
only change the open page. Use `posted` to save that status in the queue;
`--url` records the platform URL without opening it.

## Pause work

```sh
zing channels pause gridiron-lore
zing channels resume gridiron-lore
zing channels pause --all
zing channels resume --all
```

Pause creates a `PAUSE` file. Watch, queue and kit commands refuse while either
the channel file or the root file exists. Ticks stop at their next check.
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
