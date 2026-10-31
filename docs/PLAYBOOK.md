# Playbook v0

Playbook compares Shorts that beat their own channel's median with Shorts that fell below it. It saves Zing measurements and blind model judgments, then keeps patterns that separate the two groups. This is a library and a statistical comparison, not model fine-tuning. v0 covers curated YouTube podcast/interview Shorts; it does not change Study or Clip defaults.

## Run the four stages

Use the existing pilot listing first. This command reads a local JSON file and makes no network requests:

```powershell
zing playbook list --from-candidates pilot-candidates.json --out zing-workspace\playbook
zing playbook measure zing-workspace\playbook --media-dir path\to\local-shorts
zing playbook notes zing-workspace\playbook --dry-run
zing playbook notes zing-workspace\playbook --limit 10 --budget-hours 7.5
zing playbook distill zing-workspace\playbook --version v0
```

For a fresh metadata listing, use `zing playbook list --channels channels.txt --out zing-workspace\playbook`, or pass space-separated handles after `--channels`. The UTF-8 file accepts whitespace-separated handles and `#` comments. Listing uses Study's yt-dlp executable resolver, `--flat-playlist`, and `--skip-download`; it reads at most 160 Shorts per channel. It never downloads video.

`--skip-newest 10` drops the newest ten entries. Known upload dates under 14 days are also excluded. Flat listings often lack upload dates: those entries use the newest-ten proxy and appear in the channel summary's `age_unverified` count. The existing pilot has unverified dates. Do not describe this cohort as fully age-verified.

A channel needs at least 30 remaining Shorts, a positive median, and enough distinct entries on each side. `--k 5` selects five strictly above and five strictly below the median. Outlier is views divided by that median, without rounding. Zero-view entries count; missing view counts do not. Ties at the median belong to neither side. Candidate imports preserve the supplied selection, validate it, and recompute outliers from the supplied median. Their `listed_at` records import time, not the original observation time. Per-channel summaries include skips and failures. Curate channels for podcast/interview content before listing; the listing does not classify format.

Measurement looks for `<id>.mp4`, `.mov`, `.mkv`, `.webm`, `.m4v` or `.avi` in `--media-dir` (default: `<dir>/media`). Missing files remain in `features.json` as `unmeasured: no local media`. Only `measure --download` allows Study's existing downloader to fetch a missing video. Local files take precedence. Existing `<dir>/measured/<id>.json` files skip Study on reruns; `--force` recomputes them. Features are rebuilt from cached Breakdowns and `measured/<id>.caption-geometry.json`, so cleaning `working/` preserves caption/face evidence. Existing caches migrate their geometry from `working/` on the next measure run; run that before cleaning older workspaces.

Each Study failure, including a subprocess timeout, records `failed` with the exception type and a short fixed message; raw exception text, private paths and credentials are omitted. Later entries still run. Failure records in `measured/<id>.failed.json` are skipped on reruns until `--force`; missing-media entries remain retryable. Study's metadata ffprobe has a 60-second timeout. Study uses local models only, including caption geometry; missing model assets leave measurements unavailable rather than triggering model downloads. The normal Zing workspace (`ZING_HOME` when set) supplies provisioned models, while each video's working artifacts stay under the playbook directory. Existing Hugging Face snapshots remain available through Study's normal cache lookup.

### Gemini setup and spending

Set `GEMINI_API_KEY` in the process environment. There is no key file or command-line key option. Requests send the key only in `x-goog-api-key`; errors omit upstream bodies and credentials. `zing playbook models` lists model IDs and supported methods using paginated `GET models` requests.

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
  measured/<id>.failed.json    # safe failure record; retry with --force
  features.json                # schema_version 1; flat measured rows and statuses
  notes/<id>.json              # schema_version 1; rubric or safe failure reason
  notes/usage-<YYYY-MM-DD>.json # UTC-day video seconds reserved across runs
  notes-summary.json           # latest run accounting
  playbook-v0.json             # publishable statistics, guidance and original URLs
  WHATS-WORKING-v0.md          # compact read; top five patterns, six dropped tests
```

Keep the directory under `zing-workspace/`, which Git already ignores. Downloaded video, keyframes, geometry, transcripts and full Breakdowns are local working data. `library.json` and `features.json` carry no frame images or keyframe paths. Only `playbook-<version>.json` and `WHATS-WORKING-<version>.md` are publication candidates. The exporter constructs these from an allowlist of numeric fields and closed categories, template-written guidance, and original links. It never copies source titles, transcript/OCR text, model prose, clips or frames. v0 does not publish anything.

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

A later refresh can create a dated library, reuse cached measurements and notes for unchanged IDs, distill a new version, then compare kept patterns and sample coverage with the previous version. Review age coverage, channel balance and model/prompt versions before interpreting a change as a trend. Scheduling, X/IG ingestion, trend downloads, Study/Clip integration and website publication are outside v0. Claude runs the real pilot after local review; this implementation has only fixture-based validation.
