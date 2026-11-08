# Playbook v0

Playbook compares Shorts that beat their own channel's median with Shorts that fell below it. It saves Zing measurements and blind model judgments, then keeps patterns that separate the two groups. This is a library and a statistical comparison, not model fine-tuning. v0 compares curated YouTube Shorts. Study and Clip defaults stay unchanged.

## Pick a niche

Use the niche scout to compare supplied channels from public metadata. These
commands read titles, view counts, publish times and durations. They never fetch
or store video, thumbnails or audio. They make no model calls.

Save a `niches.json` input with your channel choices and research inputs.

```json
{
  "niches": [
    {
      "niche": "NFL stories",
      "channels": ["@inmotionNFL"],
      "rights": "unknown",
      "fit": "high",
      "money": "mid",
      "notes": "Check source permissions before using clips."
    }
  ]
}
```

```powershell
zing playbook niches niches.json --out zing-workspace\scout
zing playbook niches niches.json --out zing-workspace\scout --source ytdlp --min-shorts 15
zing playbook prior zing-workspace\scout --niche "NFL stories" --out zing-workspace\scout\prior.json
```

The default `--source feeds` reads each channel's 15 newest uploads. A feed entry
counts as a Short only when its link contains `/shorts/`. Watch links are excluded,
even if the upload might be a Short. Channels with fewer than `--min-shorts 15`
usable Shorts are skipped with a reason. Lower the threshold explicitly for a
smaller sample. `--source ytdlp` uses the existing flat metadata listing of up to
160 entries. It keeps Shorts links or entries with a known duration above zero
and at most 180 seconds. Missing or invalid view counts and duplicate video IDs
are excluded. Zero views count.

Young Shorts are still collecting views, so they would pull the medians down.
Dated Shorts younger than `--fresh-days 3` are left out. Flat listings carry no
dates, so they drop their newest `--skip-newest 10` entries instead. Set either
to 0 to keep everything.

Handles and channel IDs are accepted. Feed handle resolutions are cached in
`feeds/ids.json` under the output directory. RSS requests use no cookies or
API key, have a 20-second timeout, and permit only HTTPS requests to
`www.youtube.com`, including redirects. Requests start at least 1.5 seconds apart
within a process. Each attempt adds its time, URL and HTTP status, or `error`, to
`feeds/requests.jsonl`. Raw channel pages and XML are not saved.

During RSS outages, an optional `YOUTUBE_API_KEY` lets Zing fetch exact counts
from the YouTube Data API before trying yt-dlp. The fallback reads up to 15 Shorts
and 15 long videos. See [feed outages](CHANNELS.md#platform-news) for setup,
quota use and the fallback ledger.

Rights, fit, money and notes remain separate human inputs. They are optional and
are carried through as supplied. Rights accepts `campaign`, `encouraged`, `mixed`,
`claims`, `public_domain` or `unknown`. Fit accepts `high`, `medium` or `low`.
Money accepts `low`, `mid` or `high`. These labels do not establish permission or
predict revenue.

### Read the scorecard

`NICHES.md` contains a table for each niche and its channels, the five largest
available title-feature lift ratios, and links to the niche's three biggest
Shorts. It never copies competitor titles from the listing. Keep quoted titles
out of your human notes too. Nothing is published automatically.

| Number | Meaning |
| --- | --- |
| Channel n | Unique Shorts with usable view counts in the listing |
| Median and mean views | The middle value and arithmetic average for that channel |
| P90 views | The 90th percentile, with linear interpolation between sorted counts |
| Outlier | A Short's views divided by its channel median |
| Outlier share | Share of that channel's Shorts with at least 3x its median views |
| Shorts per day | Number of dated Shorts divided by the days between the oldest and newest known publish times |
| Newest upload | Latest known publish time among the usable Shorts |
| Niche median views | Median of the listed channels' median views, with each channel counted once |
| Niche outlier share | Median of the listed channels' outlier shares |
| Niche posting rate | Median of the available channel posting rates |
| Active channels | Listed channels whose newest Short was published in the last 14 days |
| Demand | `min(10, 2 * log10(max(1, niche median views)))`, rounded to two decimals |
| Crowding | Count of active supplied channels, not an estimate of the whole market |

A niche median of 100, 1,000 or 10,000 views gives demand of 4, 6 or 8. No eligible
channels means demand is unavailable. A zero channel median leaves outlier ratios
and shares unavailable. Fewer than two distinct publish times leaves posting
rate unavailable. Missing values are excluded from niche medians. The outlier
share describes how often a channel has a large spike. It is not a separate
quality score. The human inputs never enter the demand formula.

Title comparisons use hits with at least 2x their own channel median and misses
strictly below it. Other Shorts do not enter either group. Counts are pooled
across eligible channels in a niche. For each boolean feature, lift is its share
among hits divided by its share among misses. A lift of 2 means the feature was
twice as common among hits. A missing group or zero miss share leaves the ratio
null. A comparison is marked weak when either group has fewer than 10 Shorts.
These are associations from the supplied sample, without a significance test.

Title features are deterministic heuristics. They count words, Unicode characters
and emoji sequences, then flag lowercase openings, trailing emoji, numbers,
questions, quote marks, names, past story verbs, phrases about current news,
superlatives, conflict words, how/why/what/when openings and I/I'm/my wording.
Names use adjacent capitalized words or an optional known-name list. Past story
rules include common verbs, words ending in `ed` with a small stoplist, and cues
such as almost, never and nearly. They do not reliably identify names, grammar
or quoted speech. Edit the word lists in `src/myzing/playbook/titles.py`.

`niches.json` saves the full scorecard, with titles only in its `local` section.
`titles.jsonl` holds one local row per usable Short per niche, including features,
outlier and whether the channel qualified. Skipped channels' rows stay local.
Keep both files private. `prior.json` contains counts, lift statistics and template
sentences only. Guidance requires a non-weak lift of at least 1.5 or at most 0.67.
It contains no competitor titles. Set `prior` in a channel's `channel.json` to
this file to guide title choices and scouts. See [How a channel learns](CHANNELS.md#how-a-channel-learns).

### Watch views by age

```powershell
zing playbook watch --channels channels.txt --out zing-workspace\scout
zing playbook watch --channels @inmotionNFL --out zing-workspace\scout
zing playbook velocity zing-workspace\scout
```

`watch` fetches each feed once and appends all its entries to `snapshots.jsonl`.
The UTF-8 channel file accepts whitespace-separated handles or IDs and `#`
comments. Repeated handles and aliases for the same channel are fetched once per
run. Snapshots include local titles and the Short flag. This command does not
stay running.

For an hourly Windows task, replace these absolute paths with your installed
executable, channel file and output directory. Run the command once to create
the task.

```powershell
schtasks /Create /TN "Zing niche watch" /SC HOURLY /MO 1 /TR "C:\zing\.venv\Scripts\zing.exe playbook watch --channels C:\zing\channels.txt --out C:\zing\scout"
```

`velocity` reads saved snapshots without fetching anything and writes
`velocity.json`. Each video's `views` map has `1h`, `6h`, `24h`, `72h` and `7d`
keys. Each uses the snapshot nearest that age within 25% of the target age,
including the boundary. Ties use the earlier snapshot. Otherwise the value is
null. Videos first seen more than two hours after publication have a null 1h
value. Views per hour uses the first two distinct snapshot times. One snapshot
leaves that rate null. Counts can fall when a platform revises views.

Channel summaries report median available 24h views and how many videos supplied
them. Velocity includes every feed entry, including watch links. It does not
estimate missing ages or fill gaps. The feed drops uploads beyond the newest 15,
so busy channels can lose coverage before the 7d target. All times use UTC.

## Run the four stages

Use the existing pilot listing first. This command reads a local JSON file and makes no network requests.

```powershell
zing playbook list --from-candidates pilot-candidates.json --out zing-workspace\playbook
zing playbook measure zing-workspace\playbook --media-dir path\to\local-shorts
zing playbook notes zing-workspace\playbook --dry-run
zing playbook notes zing-workspace\playbook --limit 10 --budget-hours 7.5
zing playbook distill zing-workspace\playbook --version v0
```

For a fresh metadata listing, use `zing playbook list --channels channels.txt --out zing-workspace\playbook`, or pass space-separated handles after `--channels`. The UTF-8 file accepts whitespace-separated handles and `#` comments. Listing uses Study's yt-dlp executable resolver, `--flat-playlist`, and `--skip-download`; it reads at most 160 Shorts per channel. It never downloads video.

`--skip-newest 10` drops the newest ten entries. Known upload dates under 14 days are also excluded. Flat listings often lack upload dates: those entries use the newest-ten proxy and appear in the channel summary's `age_unverified` count. The existing pilot has unverified dates. Do not describe this cohort as fully age-verified.

A channel needs at least 30 remaining Shorts, a positive median, and enough distinct entries on each side. `--k 5` selects five strictly above and five strictly below the median. Outlier is views divided by that median, without rounding. Zero-view entries count; missing view counts do not. Ties at the median belong to neither side. Candidate imports preserve the supplied selection, validate it, and recompute outliers from the supplied median. Their `listed_at` records import time, not the original observation time. Per-channel summaries include skips and failures. Choose channels that fit your cohort before listing. The listing does not classify format.

### Set the cohort scope

`list --scope TEXT` saves a cohort label as `scope` in `library.json`. It also
works with `--from-candidates`. `distill --scope TEXT` overrides that label for
one report without changing the library. Distill uses the flag, then the saved
label, then `YouTube Shorts` if neither is set. The JSON and WHATS-WORKING report
carry the effective scope and its cohort caveat.

Scope is plain text of 1 to 120 characters. Whitespace, including newlines, is
trimmed and collapsed to single spaces before the length check. Empty labels
and other nonprintable characters are rejected. The label does not filter
entries or verify cohort membership.

For developer channels, put your chosen handles in `developer-channels.txt`.

```powershell
zing playbook list --channels developer-channels.txt --scope "Developer channel Shorts" --out zing-workspace\developers
zing playbook measure zing-workspace\developers --media-dir path\to\local-shorts
zing playbook distill zing-workspace\developers --version dev-v0
zing playbook distill zing-workspace\developers --version dev-v1 --scope "Developer tutorial Shorts"
```

`list` warns on stderr after saving the library if it has fewer than 8 distinct
channels in its selected entries. `measure` prints the same warning before it
starts work, including downloads. Skipped and failed channels do not count.
The warning names the actual count. A seven-channel library prints this message.

```text
distill needs at least 8 channels to keep a pattern; this library has 7. Add channels, or pass --min-channels N to distill.
```

The warning does not stop either command. Distill still applies its thresholds
and records why patterns fail. Eight channels is the default minimum; each
pattern also needs enough usable measurements on both sides within each channel.

### Measure and retry downloads

Measurement looks for `<id>.mp4`, `.mov`, `.mkv`, `.webm`, `.m4v` or `.avi` in
`--media-dir`, which defaults to `<dir>/media`. Missing files stay `unmeasured`
with reason `no local media`. Only `measure --download` allows Study to fetch a
missing video. Local files take precedence. Zing never uses browser cookies.

`--gap SECONDS` waits between download attempts. It defaults to 3 and accepts 0.
The first download starts immediately. Local files, cached measurements and
skipped entries cause no wait. After `--max-blocks N` consecutive bot-check or
rate-limit failures, downloads pause for the rest of the run. The default is 3;
the minimum is 1. A success resets the count before that limit is reached.
Local media and cached entries still process after the pause. Remaining entries
that need downloads stay `unmeasured` with reason
`download paused after YouTube blocks`. They get no new failure record.
The summary reports the stop category in `stopped` and the paused count in `paused`.

Each failure saves the exception type and a fixed reason in
`measured/<id>.failed.json`. Known download errors also save a fixed `hint`.
Raw stderr, exception text, private paths and credentials are never saved there.
The CLI prints a count and hint for each category after the summary.

| Category | Meaning |
| --- | --- |
| `download_bot_check` | YouTube asked for sign-in or a bot check. Wait before retrying. |
| `download_rate_limited` | YouTube limited requests. Wait before retrying. |
| `download_unavailable` | The video is unavailable, private, removed, members-only or age-restricted. |
| `ytdlp_missing` | yt-dlp is not installed. Run `zing doctor`. |

Saved failures are skipped on normal reruns. After waiting, retry only those
entries with `--retry-failed`. It works with `--download` and `--media-dir`.

```powershell
zing playbook measure zing-workspace\playbook --download --retry-failed
zing playbook measure zing-workspace\playbook --retry-failed --media-dir path\to\local-shorts
```

The failure record is deleted when its retry starts. Failed retries write a new
record. Entries that cannot start keep their saved failure record. Successful
measurement files stay unchanged. Entries without a failure record are not
retried; run again without `--retry-failed` to try entries left unmeasured by a
pause. `--force` recomputes all entries and cannot be combined with `--retry-failed`.

Normal reruns rebuild features from cached Breakdowns and
`measured/<id>.caption-geometry.json`, so cleaning `working/` preserves
caption/face evidence. Older caches copy geometry from `working/` on a normal
measure run; run that before cleaning older workspaces.

Study's metadata ffprobe has a 60-second timeout. Study uses local models only,
including caption geometry. Missing model assets leave measurements unavailable
without triggering model downloads. The normal Zing workspace (`ZING_HOME` when
set) supplies provisioned models. Each video's working artifacts stay under the
playbook directory. Existing Hugging Face snapshots use Study's normal cache lookup.

### Gemini setup and spending

Set `GEMINI_API_KEY` in the process environment. There is no key file or command-line key option. Requests send the key only in `x-goog-api-key`; errors omit upstream bodies and credentials. `zing playbook models` lists model IDs and supported methods using paginated `GET models` requests.

The optional `YOUTUBE_API_KEY` keeps public channel counts exact when YouTube RSS
is down. Set it yourself in the process environment. Zing tries the YouTube Data
API before yt-dlp and sends the key only in a header. `zing doctor` reports its
presence without printing it or making an API request. See
[feed outages](CHANNELS.md#platform-news) for quota use and fallback behavior.

Model precedence is `--model`, then `ZING_GEMINI_MODEL`, then **`gemini-3.8-flash`**. This stable model supports video input and structured output, and Google's current guidance directs new projects toward it or 3.5 Flash-Lite. The default is an implementation choice, not a claim that this key has access or a free allowance. Run `models` with the pilot key and select an available video-capable model before the pilot. See Google's [model page](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash), [2.5 access note](https://ai.google.dev/gemini-api/docs/models/gemini-2.5-flash), and [model discovery API](https://ai.google.dev/api/models).

Notes send a public YouTube URL as `file_data.file_uri` plus a fixed blind rubric. They send no title, channel median, view count, outlier, cohort label, transcript or local media. Google's [video guide](https://ai.google.dev/gemini-api/docs/video-understanding) documents public YouTube URL input. `responseMimeType: application/json` and `responseSchema` request structured output; local validation rejects missing/extra fields, invalid enums, wrong types, out-of-range confidence, and overlong prose. No invalid value is coerced. The prompt requires original paraphrases; length and type checks cannot prove that a paraphrase is nonverbatim, so all model prose stays local.

Before spending quota, run `zing playbook notes <dir> --dry-run [--model ID]`. It prints the first library entry's exact request body, endpoint and headers, with `x-goog-api-key` redacted. It uses the live request builder, requires no key, writes no files and sends nothing, even if that entry is cached. Claude can inspect the `file_data.file_uri` shape here; this offline preview does not establish that Gemini accepts a particular Shorts URL or model.

The rubric contains hook type, first-two-seconds visual, opening paraphrase (20 words maximum), payoff position, caption style, energy, cut feel, speaker count, topic (20 words maximum), attention explanation (60 words maximum), and confidence (0–1). Only closed categories and speaker count enter distillation. Topic, opening paraphrase, explanation and confidence do not become published patterns.

Successful notes are cached by Short ID and prompt version, even when `--model` changes. To compare models, use separate playbook directories. Failed or invalid notes are retried on the next run. `--limit` caps new entries attempted, excluding cache hits. Requests start at least six seconds apart; HTTP 429 and 5xx responses get up to three retries. A valid `Retry-After` on 429/503 supplies the delay in seconds or as an HTTP-date, capped at 120 seconds and floored at zero. Otherwise retries use 1/2/4-second exponential backoff. The rate limiter still applies. Other HTTP errors fail immediately.

`--budget-hours` defaults to 7.5 (27,000 seconds), leaving a margin against the pilot's assumed eight-hour daily free-tier allowance. It caps the UTC day's total across runs in the same playbook directory, using `notes/usage-<YYYY-MM-DD>.json`. Every request attempt, including failures and retries, reserves its video's duration in the ledger before sending. Midnight starts a new ledger, including between retries. Cached entries cost zero. An interruption after reservation can overcount but cannot erase spend. A short exclusive `.usage.lock` prevents concurrent ledger updates; if a process dies while holding it, confirm no writer is running before removing the stale lock. Keep the ledgers when cleaning working data. Separate playbook directories and other API clients do not share this ledger; this is not an account-wide billing limit.

Duration comes from measured features, then a saved Breakdown, then the library. The 60-second unknown-duration fallback is conservative for Shorts up to one minute: it charges the full minute even for a shorter clip. It can undercount longer Shorts, so measure those before requesting notes. The run reports done, cached, failures with reasons, entries skipped for budget or limit, and seconds reserved this run. Check the account's actual quotas before scheduling repeated runs.

## Data layout and rights

```text
<dir>/
  library.json                 # schema_version 1; one entry per selected Short
  channels/<handle>.json       # selection counts, median, age caveats, failures
  media/<id>.<ext>              # optional local source files
  working/<id>/                # local Study workspace, frames and geometry
  measured/<id>.json           # full local Breakdown; may contain transcript text
  measured/<id>.caption-geometry.json # local geometry preserved across resume
  measured/<id>.failed.json    # safe failure record; retry with --retry-failed
  features.json                # schema_version 1; flat measured rows and statuses
  notes/<id>.json              # schema_version 1; rubric or safe failure reason
  notes/usage-<YYYY-MM-DD>.json # UTC-day video seconds reserved across runs
  notes-summary.json           # latest run accounting
  playbook-v0.json             # publishable statistics, guidance and original URLs
  WHATS-WORKING-v0.md          # compact read; top five patterns, six dropped tests
```

Keep the directory under `zing-workspace/`, which Git already ignores. Downloaded video, keyframes, geometry, transcripts and full Breakdowns are local working data. `library.json` and `features.json` carry no frame images or keyframe paths. Only `playbook-<version>.json` and `WHATS-WORKING-<version>.md` are publication candidates. The exporter constructs these from an allowlist of numeric fields and closed categories, the cohort label, template-written guidance, and original links. It never copies source titles, transcript/OCR text, model prose, clips or frames. v0 does not publish anything.

The published JSON includes SHA-256 hashes of `library.json`, `features.json` when present, and every note file considered, including failures. Full Breakdowns are not distillation inputs. Missing measurements stay null and are excluded per feature; each claim reports its actual n per side. A cached measurement can be rebuilt after interruption without fetching video again.

## Measured features

Fields below refer to `Breakdown` unless a caption-geometry sidecar is named. Existing `myzing.profile.api` helpers and single-source StyleProfile aggregation supply first-event times, average shot duration, caption style and speech-ratio semantics.

| Feature | Source field or calculation | Unit |
| --- | --- | --- |
| `duration` | `meta.duration` | seconds |
| `avg_shot_duration` | `avg_shot_duration`, via StyleProfile `shot_duration` | seconds |
| `time_to_first_cut` | `shots[1].start`, profile `_first_cut` | seconds |
| `time_to_first_word` | minimum `words[].start`, profile `_first_word` | seconds |
| `time_to_first_caption` | minimum `captions[].start`, profile `_first_caption` | seconds |
| `speech_ratio` | `audio.speech_ratio`, profile `_speech_ratio` | fraction of runtime covered by VAD speech |
| `music_present` | measured `provenance.audio_tags`: music-under-speech spans or any window music score >= CED `WEAK_THRESHOLD` (0.1); fallback to `audio.has_music` when `audio.music_confidence > 0` | boolean |
| `caption_presence` | `captions`, OCR provenance or successful geometry samples | boolean; null when unavailable |
| `caption_words_visible_mode` | `captions[].words_visible`, StyleProfile `caption_words_visible_mode` | words per event |
| `caption_all_caps_share` | `captions[].all_caps`, StyleProfile `caption_all_caps_rate` | fraction of caption events |
| `caption_position_mode` | mode of `captions[].position`; first observed wins ties | top / center / lower / bottom |
| `words_per_second_first_3s` | count of `words[].start` in `[0, min(3, duration))`, divided by that window | words per second |
| `source_aspect` | `meta.width / meta.height` | width/height ratio |
| `face_presence_share` | fraction of geometry `frames[]` with nonempty `face_boxes`, among samples with known boxes | fraction of samples |
| `largest_face_area_share` | mean maximum `(right-left)*(bottom-top)` from normalized geometry `frames[].face_boxes`; known empty samples contribute zero | fraction of frame area |

`avg_shot_duration` is the only shot-pace feature: the near-inverse `shots_per_10s` was removed. `time_to_first_word` is the only first-word latency feature; its duplicate `silence_before_first_word` was removed. Old feature files may retain those columns, but distillation ignores them. No second shot means first-cut time is unknown, not zero. No recognized words means first-word time is unknown; a successfully completed transcription with no words has zero opening word rate. First-word latency does not prove acoustic silence: music, laughter or unrecognized speech may precede it.

Study writes CED evidence to `provenance.audio_tags`. A completed (`status: measured`) check with no music evidence reports `music_present: false`, including wall-to-wall speech where the gap heuristic has zero confidence. CED takes precedence over that heuristic. Without completed CED or a confident heuristic result, the value is null. Music tags remain detector evidence, not proof of separate audio stems.

Caption style describes detected caption events, not every frame. A completed OCR run with no caption events can report absence; skipped/failed OCR cannot. The first caption time is the first detected event, not a frame-exact onset. Geometry face detection runs only on sampled frames with text detections and a verified local YuNet model. Face statistics therefore describe that subset, not the whole video; unknown samples are excluded. No additional framing classifier is invented. `source_aspect` describes Study's ingested display dimensions.

## Evidence thresholds

All keep gates must pass, using only rows from eligible channels:

| Flag | Default | Gate |
| --- | --- | --- |
| `--min-n` | 20 | At least this many usable values per side |
| `--min-delta` | 0.33 | Numeric absolute Cliff's delta |
| `--min-rate-diff` | 0.15 | Categorical absolute worked-minus-didnt rate difference |
| `--min-consistency` | 0.6 | Fraction of eligible channels agreeing with the effect's direction |
| `--min-channel-n` | 3 | Minimum usable rows per side for a channel to enter any statistics for that feature/category |
| `--min-channels` | 8 | Minimum eligible channels required to keep a pattern |
| `--multiple-testing` | bonferroni | Adjust the cluster CI to `1 - 0.05 / tests_run`; `none` uses 95% |
| `--bootstrap-samples` | 2000 | Channel resamples for the percentile interval; minimum 100. Raised to at least 10 per tail at the adjusted level (19,600 at 49 tests); each result records `bootstrap_samples_used` |
| `--seed` | 42 | Deterministic bootstrap seed |

The adjusted cluster interval must exclude zero. Positive numeric delta means a randomly chosen worked value is more often larger than a didnt value; ties contribute zero. Numeric output includes both medians. Each closed categorical value gets a one-versus-rest comparison, with matching counts, total n and rates. Boolean features test and publish only the `true` pole; a negative rate difference means that feature was less common in worked Shorts.

Consistency counts the eligible channels whose own Cliff's delta (numeric) or rate difference (categories) has the same sign as the effect, the same per-channel statistic the effect averages. Tied channels do not agree with either direction. Channels with fewer than three usable observations per side are excluded from n, medians/rates, effect and CI, as well as consistency. Each result lists eligible and excluded channel names and counts. Fewer than eight eligible channels adds the reason `too few eligible channels`. Every feature/category appears in either `patterns` or `no_separation`, including all-missing features, with its numbers and rejection reasons. “No separation” means the gates did not pass, not proof that the groups are identical.

The effect is within-channel: Cliff's delta (or the rate difference) is computed inside each eligible channel, then averaged with each channel counted once. Worked and didnt are contrasted inside a channel by design, so differences between channels (one show's Shorts all run longer) never enter the effect, and one channel with many rows cannot dominate it. Bootstrap resamples eligible channels with replacement, keeping each channel's worked and didnt rows together, and recomputes that mean; it uses at least enough resamples for 10 in each Bonferroni tail. Shorts within a channel share a host, an editor and an audience; treating them as independent understates uncertainty. Both JSON and the one-pager report the tests actually run: every feature/category with at least one eligible channel gets an effect and CI and counts, even when another keep gate fails. Comparisons with no eligible channels have `test_run: false` and do not count. With zero tests, nothing can be kept.

The default Bonferroni correction uses a two-sided cluster-bootstrap CI at `1 - 0.05 / tests_run`. At the full 49-comparison family, that is 99.897959%, with tails at `0.05 / (2 * 49)`. JSON uses `ci`, `ci_level` and `ci_method` rather than mislabeling the adjusted interval `ci95`. The seed defaults to 42. Finite percentile-bootstrap tails are approximate, especially with 2,000 resamples at this confidence level; increasing `--bootstrap-samples` improves tail resolution. Bonferroni does not make bootstrap coverage exact. `--multiple-testing none` explicitly disables the correction and is recorded in both outputs.

The offline pilot-size fixture has 20 channels × 5 worked + 5 didnt Shorts. Under all defaults and 49 tests, its duration separation is kept (n=100/100, delta=-1, adjusted CI [-1, -1], 20/20 channels agree); music presence is kept (rate difference=1, CI [1, 1]). Matched noise has effect=0 and CI [0, 0] and is dropped. These fixtures establish expected behavior for complete separation. A seeded simulation at pilot size (20 channels × 5+5, channel offsets of 1 SD) kept a 0.8 SD within-channel shift in 17 of 20 runs, a 0.5 SD shift in 6 of 20, and pure noise in 0 of 200; pooling across channels instead kept the 0.8 SD shift in only 7 of 20. Confirm kept patterns on a fresh cohort. Views are a noisy proxy for attention. Estimated features are model judgment; measured features still inherit detector limitations.

## Weekly reuse

A later refresh can create a dated library, reuse cached measurements and notes for unchanged IDs, distill a new version, then compare kept patterns and sample coverage with the previous version. Review age coverage, channel balance and model/prompt versions before interpreting a change as a trend. The measurement and notes stages have no built-in scheduler. The niche watch command can run on an external schedule as shown above. X/IG ingestion, trend downloads, Study/Clip integration and website publication remain outside v0. Claude runs the real pilot after local review; this implementation has only fixture-based validation.
