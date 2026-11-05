# Channels

A channel is one niche identity that gets clips from new episodes over time.
It keeps source grants, factory defaults, review history and a posting queue.
`zing channels` works with local files. It never posts, uploads, signs in or
makes network requests. You upload the finished kits yourself.

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
    projects/
      episode/
        factory.json
        clip01/
    queue.jsonl
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
  `podcast`, `uoink`, `folder` and `own`. These are labels; no source is fetched.
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

## What the gate checks

Each check writes `clipNN/gate.json` with `publishable` and `blockers`.
A clip waits if any of these apply.

- Project source rights are unknown, or its registered grant has expired.
- A picked visual has rights other than `cleared` or `attribution`.
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

Pause creates a `PAUSE` file. Queue and kit commands refuse while either the
channel file or the root file exists. Resuming one channel leaves the root
pause in effect. Pausing does not remove existing kits or queue rows.
