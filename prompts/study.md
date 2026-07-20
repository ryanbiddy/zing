---
name: study
description: How to judge a Zing Breakdown — hook, beats, caption style, why it works — and write the judgment back.
version: 0.6.0
required_keys: [hook, beats, caption_style, why_it_works]
---

# Judging a Zing breakdown

You are judging the editing of ONE short video from its measurements. Zing
measured it deterministically; you supply the judgment layer. You cannot
watch the video — you can only read what was measured. That constraint is
the method: every judgment must trace to a measurement, and where the
measurements can't support a judgment you say so instead of guessing.

## 1. Get the data

Fetch the breakdown (over MCP: `get_breakdown(slug)`; or you were handed
the JSON). It contains:

- `meta` — platform, duration, resolution, fps.
- `shots[]` — cut boundaries: `start`, `end` seconds; possibly a
  `keyframe` image path relative to the breakdown's folder.
- `words[]` — the spoken transcript, word by word, with timings and
  per-word ASR `confidence`.
- `captions[]` — on-screen text seen by OCR: text, timing, position,
  case, words-visible-at-once, and OCR `confidence` (0..1 — treat low
  confidence as "maybe").
- `audio` — `speech_ratio`, `has_music` (+ `music_confidence`),
  per-second `loudness_curve` in dBFS.
- `avg_shot_duration`, `cuts_per_10s` — pacing, precomputed.
- `transitions[]` — detected edit transitions (opt-in measurement):
  `kind` ∈ `hard_cut` | `dissolve` | `wipe` | `zoom_punch`, with timing;
  hard cuts may carry `audio_aligned: true` plus a signed
  `audio_onset_delta` (cut landing on a sound onset — cutting on the
  beat, measured). **Three states, never conflate them:** entries
  present = observed; empty with a `transition*` key in `provenance` =
  detector ran, found none; empty without one = detection was not run —
  say nothing about transitions in that case. There is deliberately NO
  per-event confidence: the detector has known per-signature precision,
  not calibrated probabilities — cite kinds, counts, and timings; never
  invent certainty about any single event.
- `warnings[]` — **read this first, and sort it.** Four kinds of entry
  share this list and they carry opposite implications:
  1. **A measurement was skipped or degraded** — "transition detection
     skipped", "loudness curve skipped: ffmpeg failed". Evidence is
     MISSING here. A skipped measurement is not evidence of absence: if
     transcription was skipped, empty `words` does NOT mean nobody
     speaks.
  2. **A measurement's resolution is stated** — "caption OCR sampled at
     8 fps in 0-3s, 4 fps after; text between samples is unobserved".
     Nothing went wrong. This BOUNDS how precise a claim you may make;
     it does not weaken the measurement that was taken.
  3. **A normalization was applied** — "source codec 'av1' is not
     reliable for frame-accurate measurement here; re-encoded to H.264",
     "normalized to constant frame rate". Something was CORRECTED so
     measurement could proceed. Confidence went up, not down.
  4. **A measurement found something** — "raw: 51 dead-air span(s)
     totaling 197.2s", "raw: 105 filler word(s) — like×26...", "raw:
     repeated take (similarity 0.82) — 4.0-6.0s vs 12.0-14.0s",
     "profile coherence: source durations span 34-434s (>3x spread)",
     "draft EDL: chosen span is not a measured keeper". The measurement
     SUCCEEDED and what it found is the warning. The numbers are the
     evidence and the span references are where to look. **These are the
     entries to act on** — retake-spotting is a feature, not a fault
     report. Do not file them as "nothing went wrong", and never as
     missing evidence: the evidence is present and speaking.
  Only kind 1 is a gap in the evidence. In the frozen real-video set,
  11 of 12 warnings are kinds 2-4 — so do NOT read a long `warnings[]`
  as a broken study, and do not discount a measurement because its
  resolution was stated honestly. Kind 4 is under-represented there (1
  of 12) because that set is mostly finished videos; a raw-mode study of
  someone's unedited footage is dominated by it.

If your client can read local image files, view the shot `keyframe`
images: join each relative path against the `dir` field in the
`get_breakdown` result (the breakdown's folder — its `frames/` subdir
also holds ~1fps `hook_*.jpg` stills over the hook window). Otherwise
use the `get_frames` tool; only judge blind from text and numbers as
the last resort.

**Your Zing tools** (over MCP; skip any your client lacks):
`get_breakdown(slug)` the measurements + `dir` for local files ·
`get_frames(slug, timestamps)` labeled stills, ≤6 per call, sample at
`shots[].start` · `save_judgment(slug, judgment)` write your verdict
back · `generate_thumbnails(slug)` deterministic freeze-frame
candidates + grounded image prompts (use when asked for thumbnails —
it measures, you and the user judge the art) · `zing_status()` what
works on this machine.

## 2. Ground rules (these outrank everything below)

1. **Cite or abstain.** Every verdict needs at least one verbatim
   measurement in its `evidence` (a timestamp, a quote from `words` or
   `captions`, a count, a dBFS value). No measurement → verdict is
   `cannot_judge`, and `evidence` says what's missing and what a human
   should look at.
2. **Warnings gate judgments.** If a warning says a measurement was
   skipped, do not judge anything that depends on it.
3. **The visual-hook rule.** If there are no `words` and no `captions`
   in the first 3 seconds, the hook is visual — you cannot classify it
   from text measurements. **Look before you abstain:** call
   `get_frames(slug, timestamps)` with the start time of every shot in
   0–3s (up to 6) and judge from the returned frames, citing them as
   evidence ("Frame 2 @ t=0.90s: ..."). Only if you cannot view images
   (tool unavailable or your client can't render them), set `hook.type`
   to `cannot_judge` and say in `evidence` what a human should check
   (e.g. "3 cuts in the first 1.4s but no speech or captions — watch
   0–3s: likely a visual spectacle or pattern-interrupt open").
4. **Fill `evidence` and `reasoning` before the verdict fields** in
   every object — the order in the shape below is deliberate. Judge each
   criterion independently; don't let one strong score bleed into the
   others.
5. Run at temperature 0 if your settings allow it. Don't copy the
   example's wording; its structure is the contract, not its prose.

## 3. Judge these four things

### hook (the first 1–3 seconds)

Label vocabulary for `type` — pick exactly one:

- `question` — opens by asking the viewer something.
- `claim` — a bold/surprising statement ("this changed everything").
- `curiosity_gap` — an open loop: names or teases a payoff and withholds
  it ("the third one broke me", "wait for the end"). Distinguish from
  `claim`: a claim asserts; a curiosity gap promises. If the opening
  words point forward to something not yet said, prefer this label.
- `pattern_interrupt` — abrupt visual/audio jolt engineered to stop the
  scroll (hard cut rhythm, loudness spike, jarring image).
- `demonstration` — the payoff shown immediately, explained after.
- `story_open` — in-medias-res narrative ("so I'm standing in line…").
- `direct_address` — plain "here's what this video is" framing.
- `cannot_judge` — measurements can't support a classification (rule 3).

`strength` is an anchored 0–1–2:

- `0` — no discernible hook device inside 3s (speech starts slow, no
  captions, no cut or loudness event in the window).
- `1` — a hook device is present but single-channel or late (e.g. spoken
  question at 2.5s, static frame until then).
- `2` — multiple channels agree inside ~1.5s (e.g. spoken claim + caption
  pop + cut or loudness spike all before 1.5s).

Also answer the checklist booleans from measurements alone:
`speech_in_first_1500ms`, `caption_in_first_1500ms`,
`cut_in_first_1500ms` (null when the needed measurement was skipped).

### beats (structure)

Segment the runtime into labeled spans using `label` ∈ `hook` | `build` |
`payoff` | `cta` | `retake` | `other`. Evidence per beat: what in the
transcript, captions, pacing, loudness, or transitions marks the span
(e.g. "cuts_per_10s jumps 4→9 at 20s and the transcript pivots to the
reveal"; audio-aligned cuts clustering in a span are strong evidence of
a deliberately edited beat — cite their timings and onset deltas).
Spans should cover the video without overlaps; leave a span out rather
than invent one. If structure is genuinely unreadable from measurements,
return a single span labeled `other` whose `evidence` says why.

**Raw footage reads differently — expect it.** Unedited recordings (the
input to direct mode) are made of retakes, not beats. In measurements a
`retake` looks like: a near-verbatim repeated word run in `words[]`
(same n-gram sequence twice, often with a false start or a "no, again"
between), typically inside one long static shot, sometimes separated by
a loudness spike + silence (a clap/slate). Label each attempt span
`retake` and say in `evidence` which words repeat and where. Do not
force hook/build/payoff onto footage that is structurally a take reel —
"this is raw footage: N takes of the same line" is the honest, useful
read.

### caption_style

`style` ∈ `word_pop` (one word at a time, `words_visible` ≈ 1) |
`phrase` (2–6 words) | `sentence` (full lines) | `none` (no captions) |
`cannot_judge` (OCR skipped or all-low confidence). Report `position`
and `all_caps` from the observed majority. Weight evidence by OCR
`confidence` and say when you're reading low-confidence tea leaves.

**`captions[]` is one stream, the screen is many layers.** OCR captures
everything: subtitles, UI labels, location tags, watermarks, on-screen
props. Zing pre-excludes the worst of it: text regions persisting
≥ max(15s, 25% of runtime) are diverted out of `captions[]` and named in
`warnings` ("persistent on-screen text … excluded") — read those notes
so you know what was on screen without counting it as caption craft.
Shorter non-caption text (a 10-second location tag, scene text) can
still appear in `captions[]`: an event whose position or content doesn't
behave like the subtitle stream is a layer, not a caption — judge
caption style from the subtitle layer only, and say which events you
excluded and why. Layer pollution skews the aggregates
(`words_visible`, `position`, `all_caps`) — recompute your read from the
subtitle events, don't trust the majority blindly.

**Sync claims are bounded by sampling resolution.** OCR samples frames
at a rate recorded in `provenance` (hook window is sampled faster than
the body). Caption timing can never be known more precisely than that
interval — at 4fps sampling, "within 150ms of the spoken word" is
unknowable. State sync at the resolution you actually have ("caption
starts track word starts within one sample (~250ms) after 3s") and
never claim tighter sync than the sampling interval supports.

### why_it_works

3–6 sentences on what the edit is doing and why it holds attention —
the transferable craft, not a summary. Every claim cites a measurement
inline in parentheses. If the honest read is "it doesn't obviously
work," write that.

## 4. Output shape (the contract)

Top-level keys `hook`, `beats`, `caption_style`, `why_it_works` are all
required — `save_judgment` rejects the write otherwise.

<example_judgment>
{
  "hook": {
    "evidence": [
      "words 0.0–1.1s: 'you are charging way too little'",
      "captions 0.2–1.0s: 'CHARGING TOO LITTLE' (confidence 0.91, all_caps, words_visible 3)",
      "shots: cut at 0.9s; cuts_per_10s[0] = 7",
      "loudness_curve[0] = -9.8 dBFS vs video mean ≈ -14 dBFS"
    ],
    "reasoning": "Spoken claim, caption echo, an early cut, and a hot opening level all land inside 1.1s — a multi-channel open aimed straight at the scroll.",
    "type": "claim",
    "strength": 2,
    "speech_in_first_1500ms": true,
    "caption_in_first_1500ms": true,
    "cut_in_first_1500ms": true
  },
  "beats": [
    {"label": "hook", "start": 0.0, "end": 2.8, "evidence": "claim + caption pop; 3 cuts in first 2.8s"},
    {"label": "build", "start": 2.8, "end": 21.5, "evidence": "transcript lists three pricing mistakes; pacing steady at cuts_per_10s ≈ 4"},
    {"label": "payoff", "start": 21.5, "end": 33.0, "evidence": "'here's the exact number I use' at 21.7s; cuts_per_10s rises to 8; transitions: 3 audio-aligned hard cuts in 21.5-24.0s (onset deltas +0.02/-0.03/+0.01s) — cut on the beat"},
    {"label": "cta", "start": 33.0, "end": 36.2, "evidence": "words 33.1–35.9s: 'follow for part two'; final caption event 33.2–36.0s"}
  ],
  "caption_style": {
    "evidence": [
      "41 caption events, median words_visible = 1, median confidence 0.84",
      "38/41 events all_caps at position 'lower'; warnings name 1 pre-excluded persistent overlay (channel watermark, 0.0-34.1s at top)",
      "caption starts track word starts within one sample in the hook window (~125ms at 8fps per provenance), within ~250ms (4fps) after 3s"
    ],
    "reasoning": "Word-timed pop captions, uppercase, lower-third, synced to speech at the resolution OCR can see.",
    "present": true,
    "style": "word_pop",
    "position": "lower",
    "all_caps": true,
    "notes": "sync drifts to ~400ms after 30s — either burned-in drift or OCR timing noise"
  },
  "why_it_works": "The open stacks claim, caption, cut, and level inside 1.1s (evidence above), so every channel says 'stay'. Pacing is the real device: a calm build (cuts_per_10s ≈ 4) makes the payoff acceleration (≈ 8 at 21.5s) feel like an arrival rather than noise. Word-pop captions at words_visible = 1 keep silent viewers parsing one beat at a time, and sync tight to the sampling limit means the captions read as the voice, not subtitles of it. The CTA stays inside the energy envelope instead of tacking on a cold outro (final caption event ends 0.2s before the video does)."
}
</example_judgment>

## 5. Write it back

Over MCP: `save_judgment(slug, judgment, model="<your model name>")`.
Zing stamps prompt version and timestamp; your judgment replaces the
`study` section wholesale, so send the complete object every time. If
`save_judgment` isn't available, hand the JSON to the user in a fenced
block.

Restating the contract: read `warnings` first; cite verbatim
measurements or abstain with `cannot_judge`; evidence and reasoning
before verdicts; all four top-level keys present; visual hooks are
`cannot_judge` unless you saw keyframes; never claim caption sync
tighter than the OCR sampling interval.

## Changelog

- **0.6.0** (2026-07-20): a FOURTH warning kind — a measurement that
  RAN and found something (dead-air spans, filler counts, repeated
  takes, profile-coherence spread, an EDL span that is not a measured
  keeper). 0.5.0's three kinds were accurate but incomplete, and the
  missing one is the costliest to misfile: kind 1 would tell a reader
  the evidence is MISSING when it is present and speaking, and kind 3
  would say confidence went UP, which is not what a repeated take
  means. These are the entries to act on — retake-spotting is the
  feature, not a fault report. Routed to Lane B by Lane A's SG-1 review
  of #360 with the enumeration; verified against the emitting source
  before adopting. Guidance only; contract keys unchanged.
- **0.5.0** (2026-07-20): `warnings[]` is described as what it actually
  contains. It said "every measurement that was skipped or degraded is
  named here" — measured against the frozen real-video set, 11 of 12
  entries are NOT skips or degradations but stated measurement
  resolutions and applied normalizations. Telling a judging AI to read
  the list first and treat all of it as damage either over-discounts
  good measurements or teaches it to ignore the list. Now sorted into
  three kinds, with "skipped is not absence" scoped to the one kind it
  applies to. Guidance only; contract keys unchanged.
- **0.4.0** (2026-07-18, B-Q11): transitions vocabulary — the three
  honest states (observed / ran-none / not-run), the no-per-event-
  confidence rule, audio-aligned cuts as beat evidence; tools overview
  including `generate_thumbnails`; example models a transitions
  citation.
- **0.3.1** (2026-07-18, aligned with measurement A-Q8): persistent
  overlays are now pre-excluded from `captions[]` at measurement time
  and named in `warnings` — the layer-separation rule reflects that;
  keyframe access now goes through `get_breakdown`'s `dir` field
  (includes the `frames/hook_*.jpg` stills).
- **0.3.0** (2026-07-18): the visual-hook rule now says look before you
  abstain — `get_frames(slug, timestamps)` serves labeled stills at shot
  boundaries; `cannot_judge` remains the honest fallback for clients
  that cannot render images.
- **0.2.0** (2026-07-18, from the wizard-of-oz round): added
  `curiosity_gap` hook label; sync judgments now bounded by OCR sampling
  resolution; multi-layer OCR separation guidance (labels/watermarks vs
  subtitles); `retake` beat label + raw-footage reading rules.
- **0.1.0** (2026-07-18): initial contract.
