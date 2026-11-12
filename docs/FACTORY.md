# Clip factory

`zing factory` turns one long episode (a podcast, talk or interview) into a pack of
short social clips. Each clip is cut on sentence boundaries with the pauses removed,
framed on the speaker, and given on-screen visuals and graphics that draw what is
being said. It also gets post copy and a local review page. Nothing is posted.

For a guided start, run `zing studio` and choose [Turn a long episode into Shorts](STUDIO.md#turn-a-long-episode-into-shorts).

Studio's reference-match projects can be moved or copied. Resume from the new
folder to reuse finished match steps. External source files still need their
original paths. See [Match](MATCH.md).

For photos, choose the meme or still path in `zing studio`. Its ideas keep the
full topic when a formula fits and warn when it must be shortened. Sign captions
require a confident OCR read clear of the image edges. See [Stills and animated
memes](MEMES.md) for the text limits and sign checks.

## Playbook cohorts

Use `zing playbook list --scope "Developer channel Shorts"` to label a comparison
library. `distill --scope TEXT` can override its saved label. The default is
`YouTube Shorts`. List and measure warn when fewer than 8 channels are available
for distill. See [Set the cohort scope](PLAYBOOK.md#set-the-cohort-scope).

## Hand-off with Uoink

`zing from-uoink uoink:short-123` starts a factory project from the item's kept
video and opens the review dashboard. Press Run to begin. The host judge is
the default; `--judge claude` uses Claude Code. The source title and link are
saved when available. The media stays in Uoink.

Local Uoink calls never use a proxy. Peer checks reject invalid JSON and replies
larger than 1 MiB. Saved breakdown Markdown is replaced atomically. A symlinked
breakdown.md or JSON backup is replaced, not written through.

If Uoink did not keep the video, add `--allow-download` to fetch its source
into the project's `source/` folder. Rights stay `unknown`, so the posting
gate still applies. Progress goes to stderr. With `--json`, stdout has one
readiness line after the download, including a `downloaded` flag. Reusing
the same project does not download again.

While a download is in progress, another launch for the same item in the
default hand-off folder returns `project_exists`. Try again when it finishes.
Kept media must use a local path. Network shares and device paths are refused
before Zing opens the file. The Windows long-path form of a local drive, such as
`\\?\C:\...`, is accepted. A library on a network share falls back to
`download_needed`.

Use `--project DIR` to choose the folder, `--no-open` to leave the browser
closed, and `--idle-minutes N` to change the 60-minute idle limit. The minimum
is 1 minute. The same item reuses its project and keeps edits. Uoink's button
uses `--probe --json` to check support and `--json` to read the dashboard URL.
See the [hand-off contract](UOINK-MEMORY.md#hand-off-with-uoink).

## Hermes Agent

The [Hermes Agent plugin](../plugins/hermes-zing/README.md) uses the installed
Zing command. Start with `factory_new`, call `factory_run` and poll
`factory_status`. Hermes answers each `factory_prompt` through `factory_answer`,
then resumes the run. Use `factory_clip` for new cuts and `factory_edit` for
caption, hook, copy or visual changes. Return the review page and receipts.

MCP hints mark `factory_status` and `factory_prompt` as read-only. The other
factory tools write files and can replace existing work. `factory_run` can
fetch visuals, so its open-world hint is true even when a project is offline.
Hosts apply their own approval rules. See [Tool hints](CONNECT.md#tool-hints).

## Connect an agent

Run `zing connect` to list agent apps, then `zing connect claude-desktop`
to print a config for one. Merge the entry into the app's settings to use the
factory MCP tools. See [One line per app](CONNECT.md#one-line-per-app).

## Channels

Use [`zing channels`](CHANNELS.md) to keep source grants, factory defaults,
review history and a posting queue for one niche. `factory new --channel SLUG`
uses those defaults; `--source ID` selects a registered source. Explicit flags
still win. Channels check clips and make local post kits for you to upload.

YouTube publishing is off by default. `zing channels connect SLUG --client-secret FILE`
connects an owner's account. Set `publish.youtube` to `private` or `scheduled`
before using `zing channels upload SLUG`; `--dry-run` previews the upload.
Uploads recheck the gate, honor pause files and resume interrupted sessions.
Scheduled uploads use the queue slot or 15 minutes from now, whichever is later,
rounded up to a whole minute. Ticks link manual YouTube posts before uploading.
The gate requires finished context and brief checks and current source grants.
After editing and approving a clip, run `zing channels kit SLUG` to refresh its
video and copy. Uploads refuse stale kits. Channel steps use the project's pack
for its `9x16` render. Caption fixes leave title patterns and rights unchanged.
For clips with saved scene shot data, the gate blocks a render older than its inputs.
Later context, brief checks and post copy do not make the render stale. Kit runs
recheck existing kits and remove newly blocked ones from the phone folder. Source size and timestamp
stamps detect replaced video and copy, including files copied with older timestamps.
`zing channels analytics SLUG` merges owner metrics into outcomes.
See [Post to YouTube](CHANNELS.md#post-to-youtube) for setup, quotas and Google's
private upload restriction before an API audit.

Channel projects choose among the copy judge's alternative title patterns and
save the choice probability and policy in `post.json`. Each clip's `arms.json`
records its archetype, title pattern, rendered length, graphics density and pack.
`zing channels track SLUG` measures posted results, and `learn SLUG` reports them.
Later scouts use those results and any channel prior alongside Post and No calls.
See [How a channel learns](CHANNELS.md#how-a-channel-learns).

`zing channels watch SLUG` finds source items and starts projects when local
video and source rights are ready. `zing channels tick --all --max-minutes 50`
advances one episode per channel, queues clips and makes kits. The channel's
`judge` defaults to `host`, which waits for answers at pending prompts.
`zing channels digest --all --out digest.md` reports the last day's work and
what needs attention. See [Channels](CHANNELS.md#run-it-every-hour) for scheduling.

`zing channels brief SLUG --open` makes a daily page of outliers and platform
updates with scripts to check and record. A `recordings` source turns an eligible local
take into one hand-picked clip with `moments=0`. A matching brief supplies its
hook, news peg and series. The factory reuses the transcript, plans graphics
from the spoken facts and sends the clip through the usual gate and queue.
See [Daily brief and recorded takes](CHANNELS.md#daily-brief-and-recorded-takes).

For phone takes, use a dedicated synced folder. Recordings wait 120 seconds
after the last file modification and skip videos over 180 seconds by default.
Set the source's `since` and `require_match` to avoid old files and unmatched
takes. Set the channel's `phone_folder` to copy the latest brief to your phone.
See [Record on your phone](CHANNELS.md#record-on-your-phone).

With `phone_folder` set, channel kit runs also copy approved kits and their text
to `<phone_folder>/<slug>-kits/`. The command prints the phone index path.
Posted or skipped kits leave the mirror on the next kit run or tick.
Phone folder errors appear as warnings and do not stop the kit run.

`zing channels scorecard SLUG --open` compares local days, posts, recorded items,
kept script shares, view medians and flags with the channel's bar. It writes a
page and JSON without network or judge calls. `zing channels flag SLUG --kind
claim --note "Check the quote"` logs an issue. See [Scorecard](CHANNELS.md#scorecard).

- Masked posts do not set the channel's reward median or count toward its five-post minimum.
- Recorded and kept shares must meet the scorecard bar before rounding for display.
- `folder`, `own` and `recordings` sources need `url` set to the folder to watch.

After three matched takes with measured words in the last 30 local dates, new brief scripts use
recording notes on pace, length and wording. `zing channels brief SLUG --takes`
prints those notes without making a brief.

- Take stats use transcript segments when word timing is missing or empty.
  Takes without measured words do not guide new scripts.
- Brief builds and answers share a channel lock. A caller waits up to 30 seconds.
  Ticks repair a missing or stale latest page for the newest brief.

Channel [platform news](CHANNELS.md#platform-news) finds candidates from public
feeds and YouTube uploads from the last 10 days. It ranks them by creator topics
and date. Source errors are saved in `brief/news-errors.jsonl` under the channel.

Set the optional `YOUTUBE_API_KEY` in the process environment to keep channel
counts exact during YouTube feed outages. Zing tries the YouTube Data API first.
Without the key, or if the API fails, it uses yt-dlp without cookies or media
downloads. Receipts mark rounded counts with "about". Those counts can match
posted clips but do not become measured learning results. `zing doctor` reports
whether the key is set without printing it or testing it online.

```text
episode + captions -> scout moments -> cut -> plan the screen -> find visuals -> pick
                   -> fact-check + context check -> render 9:16 / 1:1 / 16:9 -> copy -> review page
```

## Pick a channel niche

Use `zing channels setup SLUG --from-scan zing-workspace/scout --scan-niche "NAME"`
to reuse a niche scan's channels. Setup checks their current feeds and saves the
scan source in its report. See [Set up a new niche](CHANNELS.md#set-up-a-new-niche).

Add `--suggest` to `zing channels setup` to ask the judge for candidate handles.
Setup checks their public feeds and records why channels were dropped.
`--judge host|claude` chooses the judge. With `host`, answer the printed prompt
and rerun the same command. See [Set up a new niche](CHANNELS.md#set-up-a-new-niche).

`zing channels setup SLUG --niche "TEXT" --candidates @one @two @three` ranks
public channels by median Shorts views, saves a watch list and makes the first
brief. `setup.html` lists kept and dropped channels and the time to the brief.
The scorecard checks that time against 15 minutes. See
[Set up a new niche](CHANNELS.md#set-up-a-new-niche) for inputs and limits.

Use `zing playbook niches niches.json --out zing-workspace/scout` to compare
channels from public metadata. `watch` saves view snapshots, `velocity` compares
views at fixed ages, and `prior` exports title guidance without competitor titles.
These commands fetch no video, thumbnails or audio. Set a channel's `prior` to
the exported file to guide its titles and scout. See [Pick a niche](PLAYBOOK.md#pick-a-niche)
for inputs and formulas.

For a saved Shorts library, `zing playbook measure DIR --download` reports safe
download categories and pauses downloads after three consecutive YouTube blocks.
`--gap SECONDS` sets the wait between attempts; `--max-blocks N` sets the stop
threshold. After waiting, use `--retry-failed` to retry saved failures while
keeping good measurements. Zing never uses browser cookies. See
[Measure and retry downloads](PLAYBOOK.md#measure-and-retry-downloads).

## Quick start

```bash
zing factory doctor
zing factory new talk --media talk.mp4 --transcript talk.vtt \
  --name "Show, Ep. 12" --url https://example.org/ep12 --date "May 2026" --moments 8
zing factory run talk --judge claude
zing factory status talk           # review page: talk/index.html
```

`zing doctor` reports core readiness and names missing optional models and render
tools with their limits and fixes. `zing factory run` exits 1 when it finishes
with no rendered clips and at least one failed clip. It prints a reason on stderr
and keeps the same JSON on stdout. Runs waiting for answers, empty runs and runs
with some rendered clips still exit 0. The MCP `factory_status` result reports
`ok: false` for the same completed failure.

Without `--transcript`, Zing reads the whole episode with a small speech model already
on disk (`small` or `base`; an hour in about 5 minutes on a CPU) only to find the
moments, then transcribes the chosen moments with your configured model for word
timing. When no small model is on disk, it uses your configured speech model.

Speech models mishear names and terms. The plan lists clear mishearings it is sure of
("Buddy Shaw" for "Buddy Shah", "Middle least" for "Middle East"); Zing corrects the
captions, graphics, hook and copy, logs each fix, and keeps what was heard in
`words-heard.json`. Numbers and meaning are never changed.

## Captions from another version

Supplied captions may start after a pre-show or use a different edit. Before the
scout runs, Zing tries up to five 20-second speech samples near 10%, 30%, 50%,
70% and 90% of the media. Each window stays inside the media, so a full-episode
transcript can match a shorter excerpt. It prefers the small model already on
disk and never downloads one for this check.

If two samples match at least 45% of their words and agree within 1.5 seconds,
Zing stops probing and shifts the captions by the measured offset. Shifts under 0.75 seconds are
left alone. For a 5-minute, 23-second pre-show, it adds 323 seconds to caption
times before scouting. `factory.json` saves `transcript_offset` and the check
result so reruns do not repeat it. Shifted cues outside the media are dropped,
and cues that cross an edge are clipped to it. This applies to segments and words.
The first shift keeps `transcript.unsynced.json` and, when present,
`words.unsynced.json`. Every shift starts from those originals, so an interrupted
run cannot apply it twice. Status and the review header show the shift.

Silent samples are inconclusive. If fewer than two samples hear speech, Zing
skips the check and prints a note. It also skips with a note when speech is
turned off, no model is cached, or no speech probe can run. If at least two
samples hear speech but no two agree, the run stops before scouting.

If you have confirmed the transcript, resume the same project with either command.

```bash
zing factory run "talk" --no-sync-check
zing factory run "talk" --offset 323
```

`--offset` sets the shift from the original transcript and skips the check,
including `--offset 0`. `--no-sync-check` skips it without shifting captions.
Both flags work with `new`, `run` and `batch`. On `run`, they are refused once
moments have been scouted. On `batch`, they apply to new projects. Studio asks
whether to skip a saved failed check or transcribe the episode instead. Enter
accepts skipping after you confirm the transcript matches.

For supplied transcripts that passed the sync check, word timing checks each
chosen span. If fewer than 40% of its transcript
words are heard in order, that clip fails before cutting or rendering. The
other clips continue. This guard is skipped with `--offset`, `--no-sync-check`,
any skipped sync check, and transcripts Zing made itself.

## Rights and campaign briefs

```bash
zing factory new talk --media talk.mp4 --rights permission --brief campaign.json
```

`--rights` accepts `own`, `licensed`, `permission` or `unknown` (the default).
It saves the source label in `factory.json`, each clip's `post.json`, status and review.
The label never blocks a clip. Zing labels and checks but does not grant rights
or make a clip legal.

`--brief FILE` copies a JSON campaign brief into the project as `brief.json`.
All fields are optional. Both flags also work with `factory batch`.

```json
{
  "name": "Campaign X",
  "disclosure": "Paid partnership with X",
  "disclosure_seconds": 2.0,
  "tags": ["#ad", "@brand"],
  "banned": ["gambling", "competitor names"],
  "min_seconds": 15,
  "max_seconds": 60,
  "notes": "Keep the answer to the opening question."
}
```

The scout uses the supplied length bounds, banned topics and notes.
It leaves 1 second inside each length bound and another 3 seconds below the
maximum in launch mode for the end card. A pick outside the bounds is dropped
and the rest stand. Missing tags and mentions are
appended in brief order to the X, Instagram and TikTok captions and to the end of
the YouTube title. The first comment is left alone. A disclosure
appears over the video from the first frame in every shape. It lasts
`disclosure_seconds`, from 1 to 5 seconds, or 2 seconds when omitted.

Before rendering, Zing writes `brief_check.json` in the clip folder. Length
bounds apply to the final timeline, including an end card. A length violation
or missing required disclosure stops that clip. Banned terms in the hook,
copy or spoken text use case-insensitive whole-word matching and only flag
the clip for review. Missing tags are also flagged. Status reports `brief_flags`
and `brief_errors`; the review page shows the details. Notes guide the scout
but are not checked automatically.

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

Each picture is used once per clip, in request order. A later pick of the same
picture shows no visual for that moment. An unanswered row uses the next unused
candidate that passes the content and place checks. If none remain, it shows no
visual. The pick sheet still shows repeated pictures in every row where they appear.

`network.jsonl` records factory network attempts, including failures. Each row has
`at`, `host`, `purpose` and `bytes`. It never stores full URLs, query strings,
headers or prompt text. Python downloads count response bytes read. Subprocess
calls use `null` when the byte count is unavailable. Claude calls use the host
`claude CLI (Anthropic)` and the task name. Cached work adds no requests.
Browser resource requests and FFmpeg range requests or redirects are included.
Page captures block known ad and analytics hosts before DNS lookup and leave those requests out of the ledger.
The ledger records factory activity; it is not a system-wide packet capture.

Status keeps counts by host and purpose. Review pages show a short request and
host count, with the full list under **Details**. They show
`offline: nothing fetched` only for an offline project with an empty ledger.
Model fetch commands accept `--project launch` to apply that project's policy
and ledger. Without it, the download is not tied to a project and is not recorded.

## Clip a folder of episodes

```bash
zing factory batch ./inbox --out ./projects --judge claude --moments 4
zing factory batch ./inbox --out ./projects --watch --every 60 --limit 2
```

Batch reads `.mp4`, `.mov`, `.mkv`, `.webm` and `.m4v` files directly in the inbox,
oldest modification time first. Size and modification time must stay unchanged
across two checks at least three seconds apart. Growing files wait for a later pass.

Each episode gets a project under `--out`, named from its file stem with unsafe
characters replaced. Existing projects resume. Successful projects are skipped.
Done projects with failed clips get at most two retries on later passes.
If two files map to the same project name, the second reports an error.
`--limit N` caps new episode attempts per pass. Resumed projects do not use the limit.
There is no limit by default. `--limit 0` only resumes existing projects.

All settings from `factory new` also work here. A matching `.srt`, `.vtt` or
`.json` supplies the transcript, in that order. JSON must contain readable words
or segments. Batch and Studio skip metadata JSON beside an episode.
A matching `<stem>.info.json` supplies the title, `webpage_url`, `upload_date`
and uploader or channel as the
source name, link, date and tag. Dates become `YYYY-MM-DD`. Explicit flags override
these files. Settings apply when a project is first created.

The default `--judge host` stops at pending judgments with state `waiting`.
Answer them with `factory answer`, then run batch again. `--judge claude` uses
Claude Code's CLI. An episode error is recorded and the batch continues.

A single pass prints one JSON object with an `episodes` list. Each entry has
`file`, `project`, `state`, `clips`, `pending`, `cost_usd` and `error`.
`clips` counts clips with at least one render. `pending` lists task names.
`cost_usd` is the project's total judge cost from status usage. The same summary
is appended to `projects/batch.jsonl` with a UTC `at` timestamp.

`--watch` repeats until Ctrl+C. It prints and logs one JSON line per processed
episode. `--every` sets the seconds between passes and defaults to 60.

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
when creating the project; there is no vocabulary edit command.

## Edit from an agent

Use `factory_edit(project, clip, action, ...)` or the CLI to edit a finished clip.

```bash
zing factory edit talk clip01 --rate edits --why "Fix the name"
zing factory edit talk clip01 --hook "How we built it"
zing factory edit talk clip01 --copy x "The build, in their words."
zing factory edit talk clip01 --visual v1 1
zing factory edit talk clip01 --word 12 "Starbase"
zing factory edit talk clip01 --render 1x1 --pack swiss
```

Choose one action per call. Ratings are `post`, `edits` or `no`. Copy fields are
`x`, `instagram`, `tiktok`, `youtube_title` and `first_comment`. Hook text is
trimmed to 120 characters; copy to 2200. Status lists visual requests, candidate
counts, candidate details and current picks. Candidate and word indices start
at 0. Words are listed in the clip's `words.json`.
Status uses the current plan's hook and includes `scout_hook` when the scout's
original differs, so agents can confirm hook edits.

For MCP, `word` also accepts `at`, `old` and `new`. `at` is seconds in the edited
clip, within the word's timing; `old` must match its current text. Caption fixes
keep every timing. The original words stay in `words-heard.json`, and manual
fixes stay in `word-fixes.json` so later hook and visual edits preserve them.
On the review page, open a clip's details and click a word under Captions.

CLI and MCP edits finish synchronously. Hook, visual and word changes re-render
the project's shapes and pack. Hook and word changes repeat the fact and context checks and
refresh the receipt. Results include fact checks, context flags and pending
tasks. With the host judge, a context check may need an answer. Use
`factory_prompt`, `factory_answer`, then `factory_run` to finish it.

- The review page queues hook, visual and word edits. Each job reads the latest
  files when it starts. `factory_edit` refuses edits during a factory run for the
  same project. Wait for `factory_status` to report `running=false`.
- Manual word fixes also correct matching text in hooks, graphics, labels and
  post copy. Fixing a word again replaces its saved fix and keeps the original
  heard text. A new cut clears the old saved words and manual fixes.
- MCP and CLI edits return a short render error with the last 500 characters of
  stderr when available.

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

Five steps use a judge. The **scout** chooses moments. The **plan** sets what appears
on screen. The **pick** chooses a visual from a contact sheet. The **copy** writes
the post. The **context check** looks for cuts and hooks that change the meaning.

- `--judge host` (default; MCP): the run writes each prompt to `pending/` and stops.
  It asks for everything that is ready at once. The scout comes first, then each
  clip's plan and copy, then its visual pick. The context check follows the final plan.
  You or your agent answer with
  `zing factory answer <project> <task> <file>` (or the `factory_answer` MCP tool),
  then run again. Answers are validated. Bad context answers are logged and skipped.
  Other rejected answers leave the prompt pending.
- `--judge claude`: Claude Code's CLI answers. Calls run lean: a short system prompt,
  no MCP servers, skills or project files, and only the Read tool when an image must
  be seen. Each call's cost and tokens are logged to `answers/_usage.jsonl` and shown
  by `status`. Measured on an episode: scout about $0.18, then about $0.14 per clip
  (plan $0.055, pick $0.03, copy $0.02, context check $0.03), so about $1.30 for eight clips.

Every answer is cached in `answers/`. `zing factory redo <project> clip03-plan` forgets
one judgment and what was built from it.

## Check the context

After the plan is final, each clip gets a context check of its words and hook
against a 90-second window before and after it, clipped to the episode. Whole
transcript segments at a window edge are kept. Launch films check every span's
edges. The judge flags clear reversals, heavy qualifications, jokes,
missing questions or conditions, and hook claims the clip does not back.
Normal topic changes are left alone. Each flag must quote supplied words.

The dashboard shows **Check the context**, the flagged quotes and reasons, and
expandable text from both windows. An unrated clip suggests **No**. Nothing is
saved until you click a rating. A clean check shows **Context checked**.

Results go in `clipNN/context.json` with window times and text. Launch films also
keep windows for each span in `spans`. Status reports a `context_flags` count.
Missing nearby transcript skips the check. A bad judge answer writes an `error`
with no flags and logs the failure. Neither case is shown as a clean check.

Answers are cached as `clipNN-context`. Trims, new cuts and hook edits clear the
old check. To ask again, run `zing factory redo talk clip03-context`, then run
the project. The existing number and quote fact checks still run.

## Input limits

- Prompt image directives count only in the leading block. Attached files must resolve
  inside the project folder. Directive lines in the transcript stay as text.
- Visual downloads and page captures refuse local and private network addresses.
  HTTP download redirects receive the same check.
- Page captures reject missing navigation responses and HTTP status 400 or higher.
  Failed HTTP pages do not become screenshots or scroll videos.
- Scene captures time out after 300 seconds plus 3 seconds per captured frame.
  Sample captures count only the requested frames.
- Plans drop shots with negative or nonfinite times, or times more than three seconds
  after the last word. An end card starts at most three seconds after the last word
  and holds for three seconds.

## Match a long talking clip

For reference matching, `zing match` and Studio can pick an Estimated moment
when a clip exceeds the search limit. Sentence pauses under two seconds are
allowed. The pick and its study path appear in `comparison.md` and survive
resume. Use `--no-auto-moment` to remove earlier automatic picks and choose it
yourself. Spans you wrote stay in the brief. Find another with
`zing moments clip.mp4 --project ./project --json`.
See [long interviews](MATCH.md#long-interviews) for changing the saved brief.

Automatic 9:16 match drafts can punch in toward a measured reference face size.
The plan and report state the size reached within source-resolution limits.
See [framing](FRAMING.md) for the crop limits and unchanged explicit choices.

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
  captions on the seam. Solo shots fill the frame from the header to the bottom.
  **4:5** (the LinkedIn and Instagram feed shape), **1:1** and
  **16:9** cut to full-screen visuals.
- The solo hook shrinks to a small header after `hook_until`. Packs with
  `hook_header` set to false hide the hook when that time ends. A `hook_until`
  of zero hides it from the start.
- Pictures and video fill their panel. Black padding baked into an asset is
  cropped when matching borders are detected across sampled frames.
  Visuals marked `fit: contain` stay whole over a blurred copy of the picture.
  Picture credits keep their small type on a dark translucent background.
- Captions target 2–4 words and at most 18 characters. Punctuation and pauses of
  0.3 seconds start a new group. Articles and connecting words stay with the words
  that follow when the limits allow. Short dangling words join a neighboring group.
  A pack's `cap_words` and `cap_chars` override the limits.
- Default **9:16** captions sit near y 1340 in solo shots and full-frame cutaways.
  Captions, name tags and hooks stay within x 90–990 and y 150–1440 at 1080×1920.
  Explicit `cap_y` values set the preferred position within the safe bounds.
  Headline panels keep their pack's placement.
  Speaker captions move clear of faces and hold their position for the whole phrase, including with `cap_y`.
  Graphic cards bound caption placement in either split order.
  Whole pages also bound caption placement in 9:16 splits. Captions that overlap
  a page use a dark rounded background, including kinetic captions. Packs keep
  their own caption backgrounds. Photos and logos keep their existing look.
- Lists center the title and all items as one block. Items fade in at fixed positions.
  Badges and text shrink when seven or more items need closer rows.
- Counters start when the card appears and reach the final number by its `at`
  time. Years and small numbers appear whole.
- Funnels show dim bars at their final widths, with dim labels, from the start of the shot.
  Each row lights up and reveals its number at its `at` time. The stack stays
  centered below its title. Fewer rows get heavier bars.
- A quote is the clip's one most quotable line, and the captions take over for it: the
  speaker stays on screen, dimmed, and the line builds word by word in the pack's quote
  face with its key words highlighted, then steps away and normal captions carry on.
- Graphics (counter, list, funnel, quote) are built only from the clip's words. Every
  drawn number must be spoken (spelled-out numbers count), a quote must be word for
  word, and a hook with an unspoken number is flagged. A graphic that fails becomes a
  shot of the speaker.
- Speaker framing uses the pinned YuNet face model (`zing layout fetch-model`).
  Close-ups teach the frame what the main speaker wears; in wide shots it follows them.
  Face boxes stay within 40% of the speaker panel height, with room above the brows for hair.
  Source pixels scale up by at most 1.6 times. Cropping out burned-in captions can override these limits.
  Temporary source panels, papers and picture cards get timed boxes in `cams.json`.
  In 9:16 and 1:1, speaker crops shift to clear them, then zoom if needed, up to 2.2 times source size.
  The crop changes at the graphic's start and end. If it cannot clear the box, it keeps the original framing.
  Clear grid borders that agree across sampled frames keep each face inside its own tile.
  If filling the panel would exceed the limits, the whole tile sits over the blurred background.
  With local OCR available, text cards without faces stay whole over a blurred background if the crop would cut text.
  Each shot checks its actual panel and output shape, including solo shots that fill the frame.
  A closing group shot under half a second with no tracked face holds the previous
  tracked frame through the final tail. Longer group shots and text cards stay whole.
- Standard MP4 renders use H.264 CRF 20 with the slow preset, a 12 Mbps peak rate
  and a 24 Mb buffer. File size depends on the footage. UHD keeps its existing
  CRF 20, medium preset and 40 Mbps peak rate.
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
  It rejects unrelated places, police forces, teams and companies, including names
  on cars, signs and jerseys. This rule also applies in context and fun modes.
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
CC BY and CC BY-SA count as `attribution`. Licenses with NC or ND terms in their
name or URL count as `unknown`. Openverse searches require commercial use and
modification. NASA items with copyright or permission notices in their title,
description or creator also count as `unknown`. Long attribution credits shorten
the title and creator to keep the license whole at the end.
GIPHY, KLIPY and Tenor are not used: their terms forbid baking clips into video.

## Style packs

`--pack zing | newsdesk | swiss | headline | documentary | launch` sets colors, caption treatment and source tag
(`zing factory packs`). A pack is one JSON file in `myzing/_data/factory/themes/`.
`zing` uses 78px heavy white capitals per 1080px of the frame's short side, a dark outline and a soft shadow.
The active word turns yellow and grows slightly in place. There is no caption box.
Long groups shrink to fit 900px. Other built-in packs with an explicit caption size scale it with frame width.
At 1920×1080, `launch` uses 89px, `headline` 103px and `documentary` 117px.
Learned packs keep their height-based scaling.
`headline` plays the clip above a solid panel that holds your source credit and the hook
as a standing headline in condensed capitals, key words in the accent color.

### Brand kit

Save a user pack as `factory/packs/acme.json` in your workspace. Put its font and
logo files in `factory/packs/acme/`.

```json
{
  "name": "Acme",
  "accent": "#E83E55",
  "fonts": [
    {"family": "Brand Sans", "file": "BrandSans-Bold.woff2", "weight": 700, "style": "normal"}
  ],
  "cap_font": "Brand Sans",
  "cap_weight": 700,
  "logo": "logo.png",
  "logo_pos": "top-right",
  "logo_h": 72
}
```

Font files can be `.ttf`, `.otf`, `.woff` or `.woff2`. Use the family in
`cap_font`, `hook_font` (or `pill_font`), `gfx_font`, `quote_font` or `panel.font`.
The bundled families are Inter, Anton, IBM Plex Sans and Instrument Serif.
Font weight defaults to 400 and style to `normal`.

Logos can be `.svg` or `.png`. Choose `top-left`, `top-right` or `bottom-right`.
The default is `top-right` at 72 pixels high in a 1080-wide frame. The logo scales
with the frame and keeps one spot for the whole clip. It steps below the source tag
and above a headline panel, and hides for a moment when the hook, a caption or a quote
is drawn where it sits. Launch end cards show the logo once, centered above the brand name.

Run `zing factory packs --check acme` to check files and family names. Errors
produce exit code 1. Every render runs the same check, then verifies that the
browser loaded each font and the logo before capturing frames. A broken font
fails with its family and file name. Assets stay local and inside the pack's
folder. Absolute paths, `..` and symlinks that escape that folder are rejected.
All brand fields are optional.

## Finish in your editor

```bash
zing factory export talk/clip01 --shape 9x16 --pack zing
```

Import `talk/clip01/export-9x16/timeline.xml` into Premiere Pro or DaVinci Resolve.
The 30 fps timeline places `speaker.mp4` on V1, `overlay.mov` on V2 and
`audio.wav` on A1. The overlay uses ProRes 4444 with alpha. Audio is 48 kHz.
The speaker keeps the scene's framing and cutout. Pictures, graphics and text
stay in the overlay. These are two video layers, not native graphics or text objects.

`captions.srt` follows the scene's caption groups and display times, including
quote takeovers. `words.srt` has one cue per word. Import either to style new
captions. The overlay still contains the rendered captions.

Use `--shape 9x16|4x5|1x1|16x9` and `--pack NAME` to choose the render.
`--out DIR` changes the output folder. The defaults are `9x16`, `zing` and
`<clipdir>/export-<shape>/`. Keep the media beside the XML. Relink it if you move
the folder.

Each export compares the composited layers with three normal scene frames.
The command prints JSON with each sample's mean absolute RGB error on a 0–255
scale and PSNR in dB, plus file sizes in bytes and elapsed seconds.
Lower error and higher PSNR mean a closer match. An exact match has zero error
and a null PSNR.

## Review dashboard

Run `zing factory serve <project>` and open the printed link. It uses port 8765.
Pass `--port N` to choose a port from 0 to 65535. Use `--port 0` for any free port.
The link includes a token for this server session, such as
`http://127.0.0.1:8765/?t=TOKEN`. The page saves it
in an HttpOnly session cookie and removes it from the address bar. Open the new
printed link after restarting the server. Requests without the cookie are refused.
Studio prints the full link but saves the URL without its token in
`studio-result.json` and `studio-session.json`.

Watch each clip in every shape, rate it Post / Post with edits / No,
swap a visual for another candidate, fix a hook or the copy, and re-render in another
style pack. Swaps and hook edits re-run the fact check and re-render in the background.
Ratings save to `ratings.json`. `--judge claude` lets the page's Run button answer
judgments with Claude Code; otherwise they wait for your agent.

The header keeps Run and the decision count at the top. Network **Details** open
below the header. On screens up to 700 pixels wide, the header scrolls with the page.

The player reloads a video after a re-render. Variants older than `plan.json` or
`words.json` are labeled "older than the latest edit". They stay available to
watch and download. Re-render those shapes and packs to include the edit.
If encoding fails after capture, the next run retries when `data<tag>.json`
is newer than the MP4.

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

## Study a reference video

- Reference studies check kept copies by SHA-256 and publish staged media only
  after the copy finishes. Download timeouts and errors stop child processes too.
- Caption samples follow decoded frame times on low frame-rate videos. Music
  detection stays inconclusive when speech is present but no one-second bucket
  is mostly speech.
- Failed transition detection is reported as not measured.
- Local studies record the original file's SHA-256 before trimming or staging.
  Planning rejects studies whose source hash has changed. Older studies still load.

## Reframe clips and check music

- Auto, reframe and zoomfill deliveries split at detected cuts unless the clip
  is linked by a transition. Tracks from an adjacent shot do not set its vertical crop.
- Contact sheets support frames as thin as one pixel.
- Caption presets assign each word to the first clip containing its start time.
  Transition overlaps no longer repeat the word in two cues.
- Music advice gives silent excerpts zero energy points. An excerpt counts as
  silent when its median level is at or below -60 dBFS. Missing energy analysis
  is reported as missing, not silent.

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

Use `zing explain reference.mp4 --against draft.mp4 --out card` to compare a draft.
The terminal and both readable cards start with the measured differences and an
action for each section. See [Compare a draft](EXPLAIN.md#compare-a-draft).

## Briefs, drafts and reference profiles

- `zing brief new` checks `--short-side` before saving. A rejected value leaves
  the saved brief unchanged. Valid answers and the override are saved together.
- `zing assemble` replaces `draft-edl.json` atomically. A failed write keeps the
  previous draft. Keeper times must be numbers. Invalid word timing provenance
  asks for review before assembly continues.
- `zing profile pack` saves once, after adding provenance. The previous profile
  stays in `profile.json.bak`. Repeated source slugs count once and get a warning.
- Malformed reference packs report errors. `zing setup --list` lists broken packs
  without stopping the whole listing.
- Timeouts and OS errors while reading Uoink error replies leave delivery pending.
  `UOINK_TOKEN` and `ELEVENLABS_API_KEY` reject control characters before a request
  is built. Errors name the setting and omit its value.

## Match and studio resumes

- Match keeps step logs inside `logs/`, even when asset IDs contain path separators.
- Changing the reference range rebuilds match color grades and clears the saved
  studio result. Unchanged ranges can reuse cached work.
- Match skips generated files when `--out` is inside `--clips`.
- Studio screen runs share the production lock. A busy CLI run leaves the active
  session unchanged. The lock stays held through the final session save.
- After cancellation or a worker failure, studio removes project locks only for
  its own dead worker on this machine. Other owners' locks stay in place.

## Setup

```bash
python -m pip install "myzing[factory]==1.0.0rc1"
zing layout fetch-model
zing factory fetch-depth --yes          # optional: photos move through their depth
zing factory fetch-cutout --yes         # optional: --cutout stands the speaker in front of pictures
zing factory fetch-upscale --yes        # optional: small photos render sharp
zing factory setup                    # pinned playwright-core; uses your Chrome or Edge
```

Install Node.js 20+ with npm first. `zing factory setup` prints the folder and
`npm ci` before running it. It downloads the pinned Node dependency, not a browser.
Run it again after upgrading Zing. It skips npm when the lockfile matches and
Playwright is installed, and refreshes the shipped scripts.

The sidecar uses `ZING_FACTORY_SIDECAR` when set, otherwise
`tools/factory-sidecar` in a checkout, otherwise `factory-sidecar` under
`ZING_HOME` (default `~/.zing`). The wheel includes the setup files.
`tools/factory-sidecar` is the source of truth. Tests check that its packaged
copies are identical.

The renderer captures a deterministic `seek(t)` page frame by frame in a local Chrome
or Edge (`ZING_BROWSER_PATH` overrides the lookup), then FFmpeg encodes it with the
cut's audio.

The separate HyperFrames renderer needs a source checkout for now. See
[HyperFrames setup](HYPERFRAMES-SIDECAR.md).

## Project layout

```text
<project>/source.json  factory.json  transcript.json  words.json  moments.json
<project>/pending/<task>.md     answers/<task>.json     answers/_usage.jsonl
<project>/clipNN/  cut.mp4  words.json  cams.json  plan.json  receipt.json  context.json  post.json
                   visuals/ (candidates, manifest.json, run_log.json, pick_sheet.jpg)
                   clip.mp4  clip-1x1.mp4  sheet.jpg
<project>/index.html   review page with Post / Post with edits / No ratings
```
