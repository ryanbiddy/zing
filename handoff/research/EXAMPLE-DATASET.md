# R-C — Example dataset: reference short + raw talking-head

Zing's standing demo pair (ROADMAP R-track): one exemplary edited short-form
video and one genuinely unedited talking-head clip. Both are captured into
the local Uoink corpus (helper v3.6.0, `127.0.0.1:5179`) and verified via
`/recent`. Captured 2026-07-18.

## 1. REFERENCE — the edit Zing should aspire to

- **URL:** https://www.youtube.com/shorts/nlGYV0bmddI
- **Title:** "Why You Can't Pee On Antarctica"
- **Creator:** Cleo Abram (Huge If True), 8.4M subscribers
- **Stats at capture:** 43s · 11.79M views · 382K likes · uploaded 2026-07-08

**Why this one.** Cleo Abram is the current benchmark for short-form
explainer editing — her style is imitated widely enough that "Why Everyone's
Copying Cleo Abram's Editing" is itself a YouTube genre. This short packs
the full craft checklist into 43 seconds:

- **Hook:** cold-open curiosity gap in the first sentence ("you're never
  allowed to pee on the ice"). Uoink's hook classifier independently tagged
  it `curiosity_gap` at confidence 5/5.
- **Word-timed captions** throughout, synced to speech.
- **Fast cuts + motion graphics:** location b-roll, animated ice-core
  diagrams, punch-ins on beats — no shot outstays its welcome.
- **Payoff + CTA:** setup/payoff structure (the "yellow line" ice core) that
  resolves the hook, then a subscribe CTA tied to the content.

This is the target: when Zing scores or generates an edit, this is what
"good" looks like for the explainer-short genre.

## 2. RAW — no-edit proxy for user footage

- **URL:** https://www.youtube.com/watch?v=FHMXO_VikdA
- **Title:** "Raw Footage for Editing Practice with Download Link | Raw
  footage for Video Editing Practice"
- **Creator:** MrDenoise, 4.1K subscribers
- **Stats at capture:** 55s · 110K views · uploaded 2024-01-03

**Why this one.** It is *published as* raw footage: a single-take,
single-camera talking-head monologue (a man talking about his watch
collection) uploaded explicitly for editors to practice on — the
description calls it "Raw and Unedited," and the channel provides a
download link plus a separate "reference edit." That makes it an unusually
honest stand-in for what a Zing user will actually upload: no cuts, no
captions, no music, natural filler ("literally," restarts), continuous
speech. It even contains editable raw material (brand mentions: Rolex,
Patek Philippe Nautilus 5711R, Argos/London anecdote) that a hook-first
edit could reorder. Verified single-subject talking-head via thumbnail and
transcript before capture.

Rejected alternatives: lecture-hall recordings (multi-cam, not
talking-head framing) and "example interview footage" from production
companies (graded/scored, so not genuinely unedited).

## 3. Uoink capture status

Both POSTed to the helper's `POST /extract` (X-Uoink-Token auth) and
confirmed present in `GET /recent`:

| | Reference | Raw |
|---|---|---|
| Result | ok | ok |
| Slug | `Why_You_Can_t_Pee_On_Antarctica` | `Raw_Footage_for_Editing_Practice_with_Download_Link_Raw_footage_for_Video_Editin` |
| Folder | `E:\Uoink\Social Media Research\Why_You_Can_t_Pee_On_Antarctica` | `E:\Uoink\Uncategorized\Raw_Footage_for_Editing_Practice_with_Download_Link_Raw_footage_for_Video_Editin` |
| video_id | `nlGYV0bmddI` | `FHMXO_VikdA` |
| source_type | `short_video` | `video` |
| hook_type | `curiosity_gap` (5/5) | `story_open` (4/5) |
| On disk | transcript, SRT (en + en-orig), screenshots, thumbnail, comments JSON, md + JSON sidecar | same |

Note: the Short was submitted with its `/shorts/` URL on purpose — Uoink's
short detection runs on the pasted URL before normalization, which is what
earned it `source_type=short_video` (filterable via
`/memory/search?source_type=short_video`).

## 4. Honest limitation — no media files in the corpus

**Uoink deletes the downloaded video file after extraction** (verified: both
capture folders contain transcripts/screenshots/sidecars but no `.mp4`). A
`keep_media` flag is pending on the Uoink side but does not exist today.

Consequence for Zing: the corpus gives us transcripts, word-level timing
(SRT), screenshots-on-interval, and metadata — but **any pipeline stage
that needs actual video/audio frames must refetch by URL** (yt-dlp against
the URLs above) until `keep_media` ships. Treat the URLs in this doc as the
canonical media source; treat the Uoink folders as the analysis layer.
