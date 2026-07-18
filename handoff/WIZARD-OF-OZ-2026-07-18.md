# Wizard-of-Oz Judgment Simulation — Sprint 1 Gate (2026-07-18)

Role: "the user's AI" running `prompts/study.md` v0.1.0 over the two frozen
breakdowns, then previewing direct mode. Every number below is quoted from
`tools/eval/real_videos/*/breakdown.json`; where the measurements could not
support a judgment, the verdict is `cannot_judge` per the prompt's ground
rules. No keyframes are committed for either fixture (manifest:
`derived_frames_committed: false`), so the visual channel was dark
throughout — this simulation is text-and-numbers only, which is itself a
finding (see section 4).

Inputs: `prompts/study.md` · `docs/taste/TASTE-FRAMEWORK.md` ·
`docs/taste/EDITING-CRAFT-AND-SPECS.md` · `docs/taste/RUBRIC-talking-head.md`
(both videos are talking-head genre; the reference is a named G-TH exemplar) ·
`handoff/research/EXAMPLE-DATASET-TRUTH.md` · both breakdowns.

---

## 1. Judgment: the reference (Cleo Abram, "Why You Can't Pee On Antarctica")

`meta`: 42.534s, 608×1080 (0.563 ≈ 9:16), 24fps, YouTube Shorts.
`warnings` read first: (1) AV1 re-encoded to H.264 — frame-accuracy caveat on
cut times; (2) OCR sampled 8fps in 0–3s / 4fps after — text between samples
unobserved, caption timing quantized to 0.125–0.25s; (3) **music detection
inconclusive** — speech is wall-to-wall, no gaps to measure a bed in. Warning
3 gates every music-dependent judgment below; `has_music: false` is NOT
evidence of no music.

### Hook: type `claim`, strength 2, hook-promise congruence high

- Spoken claim completes inside the H1 3s window: words 0.0–2.78s "In
  Antarctica, you're never allowed to pee on the ice." — a surprising rule
  stated flat, no intro, no branding (H2 cold open: first word at 0.0s).
- Three channels agree inside 1.5s: speech at 0.0s; caption at 0.0–0.875s
  "ANTARCT IN ANTARCTICA," (confidence 0.997, all_caps); first cut at 0.292s.
  That is the anchored definition of strength 2. Checklist:
  `speech_in_first_1500ms: true`, `caption_in_first_1500ms: true`,
  `cut_in_first_1500ms: true`.
- 3 cuts in 0–3s (0.292, 1.958, 2.958); `cuts_per_10s[0] = 7`, the densest
  bucket of the video — energy front-loaded exactly where H1/H5 say the
  retention risk is.
- **Hook-promise congruence (H3):** title "Why You Can't Pee On Antarctica";
  "Antarctica" is spoken at 0.2–0.64s and "pee" at 2.02–2.18s — both title
  nouns land inside 2.2s. The promise is a *why*, and the why is explicitly
  resolved: "So you can't pee because if you did..." at 26.12–28.5s, punchline
  "what's that yellow line?" at 35.98–37.32s. Promise made in 2.2s, paid off
  at 26–37s. This is the H3 packaging-congruence pattern, measured.
- Vocabulary note: the truth annotation calls this a "curiosity gap" and H2
  names "open loop"; `study.md`'s label set has neither, so `claim` is the
  closest legal label. See section 4.

### Structure beats

| span | label | evidence (verbatim measurements) |
|---|---|---|
| 0.000–5.042 | hook | claim words 0.0–2.78s + escalation "Not even when you're hiking for hours." 3.04–4.78s; 3 cuts in 0–3s; caption from 0.0s |
| 5.042–13.458 | build | mechanism: "It's because it's so cold and so dry... traps air inside." 5.1–13.38s; cut at 8.5s lands 0.1s after "snows," (ends 8.4s); pacing eases to cuts_per_10s = 5 |
| 13.458–26.083 | build | science + stakes: "scientists drill ice cores... hundreds of thousands of years" 13.76–18.64s; pivot "But if anything else hits that ice, like ash" 20.8–23.52s; cut at 26.083s lands 0.12s after "too." (25.96s) |
| 26.083–37.62 | payoff | "So you can't pee because if you did, one day some descendant of yours..." 26.12–31.02s → "what's that yellow line?" 36.62–37.32s; the punchline rides the longest shot of the video (5.5s, 32.333–37.833) and loudness lifts: mean −16.64 dBFS over seconds 28–35 vs −20.41 for seconds 0–27 |
| 37.62–42.534 | cta | "to see what's really hidden under the ice, subscribe" 37.78–40.98s; "SUBSCRIBE" caption events 39.5–42.5s; final caption ends 42.5s = last frame — no cold outro |

The measured pacing shape is the opposite of study.md's example judgment:
this edit *decelerates* into the payoff (`cuts_per_10s` = [7, 5, 6, 3, 1])
and gives the punchline the longest-held frame instead of a cut flurry.
Density where the swipe risk is (0–10s), stillness where the story lands.

### Caption craft

- 47 events, 47/47 all_caps, median OCR confidence 0.982. Position majority
  bottom/lower (21 + 16 of 47). Median `words_visible` = 5 → **style:
  `phrase`** (2–6 words) by the study.md taxonomy.
- Continuous coverage 0.0–42.5s with exactly one gap: 35.75–37.75s — which is
  precisely the "what's that yellow line?" punchline (35.98–37.32s). At 4fps
  OCR, a ≥1.3s caption spans ~8 samples, so this is more likely a deliberate
  caption drop for a visual punchline than a sampling miss — but that is an
  inference; a human should confirm from the video.
- Timing: caption starts track word starts within the OCR sampling quantum
  (e.g. "IT'S BECAUSE IT'S SO COLD" at 5.75s vs spoken "It's" at 5.1s). The
  prompt's ~150ms sync test is **below instrument resolution** at 4fps —
  reported as unmeasurable, not as a fail.
- Reading speed vs E9: "HUGE ICE CORES TO STUDY THAT AIR" shows ~32 chars for
  1.5s ≈ 21 cps — at/just over the Netflix 20 cps adult cap. Events like
  "HUGE* 5,552ft 1,692m HUNDREDS OF THOUSANDS OF YEARS" (0.75s) are OCR
  merging a *second text layer* — location/altitude graphics ("WHITE DESERT
  ANTARCTICA", "HUGE* DRILLING CO.", "SMITH") — into the caption stream. Two
  deliberate text layers is craft evidence; one merged OCR stream is a
  measurement limit.
- The truth annotation says word-timed keyword highlighting; `words_visible`
  median 5 says phrase-level *display*. OCR cannot see highlight animation —
  the honest classification from measurements is `phrase`, with the
  word-timed question flagged for a human eye.

### Rubric scores (RUBRIC-talking-head.md, 1–5, evidence per score)

| criterion | score | evidence |
|---|---|---|
| G-TH-1 Cold-open hook & pacing (H1, H2) | **5** | claim complete 2.78s < 3s (H1); speech at 0.0s, zero branding window (H2); 3 cuts 0–3s; caption at 0.0s |
| G-TH-2 Hook-promise congruence (H3, E4) | **5** | both title nouns spoken ≤2.2s; premise explicitly resolved 26.12–37.32s ("So you can't pee because...") |
| G-TH-3 Cut motivation & rhythm (E1/E5, E8) | **4** | 18/22 cuts within 150ms of a word end — cuts ride the language, not a metronome; shot lengths 0.292–5.5s, stdev 1.108s (E8: varied, not constant); longest shot reserved for the emotional peak (E6: emotion preserved first). Capped at 4: emotion/eye-trace (E5's 51%+7%) are unmeasurable without frames |
| G-TH-4 Visual organization (P1) | **partial** | measurable: aspect 608/1080 = 0.563 ≈ 9:16 pass (P1). Width 608 < 720p bar is a yt-dlp fetch-format artifact (manifest caps at ≤1080 height), not creator evidence. Composition/lighting: `cannot_judge` — no keyframes committed |
| G-TH-5 Caption craft (P2, E9, P11) | **4** | full-runtime coverage, high contrast implied by all-caps style but contrast unmeasured; phrase style at median 5 words; ~21 cps touches the E9 cap; one 2s gap at the punchline (see above) |
| G-TH-6 Sound (P1, P10) | **cannot_judge** | warning: "music detection inconclusive: speech is wall-to-wall". Speech side is strong — speech_ratio 0.995, levels −15.4..−22.7 dBFS, no dead air — but the criterion scores the music mix, and that measurement is gated. Human should check bed level and ducking |
| G-TH-7 Human vision / anti-slop (A1, A2) | **4** | transcript channel only: the pee-ban → ice-core → "descendant of yours... yellow line" chain is an original narrative device no template produces (A2 "demonstrable creative vision"); 146 words in 42.5s (~206 wpm) with zero filler tokens = written, rehearsed script. Visual originality unverifiable without frames |

### study.md contract JSON (save_judgment unavailable — fenced per §5)

```json
{
  "hook": {
    "evidence": [
      "words 0.0–2.78s: 'In Antarctica, you're never allowed to pee on the ice.'",
      "captions 0.0–0.875s: 'ANTARCT IN ANTARCTICA,' (confidence 0.997, all_caps, words_visible 2)",
      "shots: first cut at 0.292s; 3 cuts inside 0–3s; cuts_per_10s[0] = 7",
      "meta.title 'Why You Can't Pee On Antarctica' — 'Antarctica' spoken 0.2–0.64s, 'pee' 2.02–2.18s"
    ],
    "reasoning": "A surprising rule stated as fact inside 2.8s with speech, caption, and cut all present before 1.5s — a multi-channel cold open whose wording repeats the title's promise. The label set has no curiosity-gap/open-loop option; claim is the closest fit for a statement engineered to demand a 'why'.",
    "type": "claim",
    "strength": 2,
    "speech_in_first_1500ms": true,
    "caption_in_first_1500ms": true,
    "cut_in_first_1500ms": true
  },
  "beats": [
    {"label": "hook", "start": 0.0, "end": 5.042, "evidence": "claim 0.0–2.78s + 'Not even when you're hiking for hours.' 3.04–4.78s; 3 cuts in 0–3s"},
    {"label": "build", "start": 5.042, "end": 13.458, "evidence": "mechanism 'so cold and so dry... traps air inside' 5.1–13.38s; cut 8.5s lands 0.1s after 'snows,' (8.4s)"},
    {"label": "build", "start": 13.458, "end": 26.083, "evidence": "'scientists drill ice cores' 13.76s; stakes pivot 'But if anything else hits that ice' 20.8s; cut 26.083s lands 0.12s after 'too.' (25.96s)"},
    {"label": "payoff", "start": 26.083, "end": 37.62, "evidence": "'So you can't pee because if you did' 26.12s; punchline 'what's that yellow line?' 36.62–37.32s on the video's longest shot (5.5s, 32.333–37.833); loudness mean −16.64 dBFS (s28–35) vs −20.41 (s0–27)"},
    {"label": "cta", "start": 37.62, "end": 42.534, "evidence": "'subscribe' 40.66–40.98s; SUBSCRIBE caption events 39.5–42.5s; final caption ends at the final frame"}
  ],
  "caption_style": {
    "evidence": [
      "47 events, 47/47 all_caps, median confidence 0.982",
      "median words_visible = 5 (mean 5.3)",
      "position: bottom 21 + lower 16 of 47",
      "coverage 0.0–42.5s with one 2.0s gap at 35.75–37.75s (the punchline window)",
      "caption starts track word starts within OCR sampling quantum (0.125–0.25s); 150ms sync unverifiable at 4fps"
    ],
    "reasoning": "All-caps lower-third phrase captions with near-total coverage. OCR merges a second on-screen layer (location/altitude labels: 'WHITE DESERT ANTARCTICA', '5,552ft 1,692m') into the stream, and cannot see per-word highlight animation, so 'phrase' is the display-level truth; word-timed highlighting is untestable here.",
    "present": true,
    "style": "phrase",
    "position": "lower",
    "all_caps": true,
    "notes": "the 2s caption gap coincides exactly with the spoken punchline — likely deliberate; confirm by eye"
  },
  "why_it_works": "The open makes a promise in the title's own words within 2.2s (title nouns spoken 0.2s and 2.02s) and stacks speech, caption, and cut before 1.5s, so every channel votes 'stay' at the moment swipe risk peaks (cuts_per_10s[0] = 7). The real device is the pacing inversion: density decays 7→5→6→3→1 across the runtime while the punchline gets the longest shot of the video (5.5s at 32.333s) and a ~3.8 dB loudness lift (−16.64 vs −20.41 dBFS), so the payoff reads as arrival, not noise. Cuts ride the language — 18/22 land within 150ms of a word end — which is Murch's story-motivated cutting visible in pure telemetry. Wall-to-wall speech (ratio 0.995, ~206 wpm, zero filler tokens) leaves no dead air to swipe on, and the CTA is inside the energy envelope: 'subscribe' at 40.66s in a 42.5s video, final caption ending on the final frame."
}
```

---

## 2. Judgment: the raw clip (MrDenoise, "Raw Footage for Editing Practice")

`meta`: 55.074s, 1920×1080 **landscape**, 30fps. `warnings`: AV1 re-encode;
OCR sampling (same gates as above). Transcription and music detection ran:
`has_music: true` (confidence 0.676), `speech_ratio 0.84`.

### F-16 first: what the measurements actually support

The truth annotation claims "zero cuts... single, continuous, static camera
shot" and "captions: none." The breakdown says otherwise, decisively:

- **34 shots / 33 cuts**, `avg_shot_duration` 1.619s, `cuts_per_10s` =
  [1, 6, 15, 3, 7, 1] — including 15 cuts in the 20–30s bucket.
- **49 caption events**, including burned-in mixed-case subtitles ("I don't
  go anywhere" 17.5–18.75s bottom, conf 0.994) and an end card "RAW VIDEO
  LINK PINNED IN COMMENTS" 52.25–55.25s (conf 0.97).
- The transcript contains a **verbatim repeat**: the 59 words spoken at
  0–16.16s are word-for-word identical to the first 59 words of the run
  starting at 17.06s (verified token-by-token against `words[]`).
- Structure markers in the OCR: persistent top label "Raw Video Preview"
  0.0–16.75s, a "GO!" sting at 16.75–17.25s, watch-dial text (ROLEX 19.0s,
  TIMEX INDIGLO 29.25–30.0s, PATEK PHILIPPE NAUTILUS 5711R 44.0–46.0s) and
  even prop-money microprint ("...FOR MOTION PICTURE PURPOSES. IT IS NOT
  LEGAL TENDER..." 37.0–37.5s) — i.e. b-roll inserts.
- Loudness corroborates a two-part construction: seconds 0–15 mean
  −24.12 dBFS vs seconds 16–47 mean −18.09 dBFS (a ~6 dB jump at the
  "GO!" boundary), then a decay to −70 dBFS in the final second.

**Verdict on F-16:** the published upload genuinely has cuts. It is not raw
footage; it is an *editing-practice showcase*: [0–16.6s: preview of the raw
take, 2 cuts] → [GO! sting] → [17.1–48.3s: the same monologue re-delivered
as a finished edit with subtitles, b-roll and music] → [48.4–55s: music-only
outro with a link card]. The manifest's `truth_caveat` (Lane A) is correct;
`EXAMPLE-DATASET-TRUTH.md` §2 is wrong about the published file on cuts,
captions, and its Take-1/Take-2 reading (the "second take" is the edited
version, not a retake — 15 cuts/10s and dial-text OCR don't happen in a
static single shot). The genuinely raw asset is behind the video's download
link and should replace this fixture, or the truth doc should be
re-annotated. Judgment below treats the upload as what it measurably is.

### Hook: type `story_open`, strength 1

- Speech from 0.0s: "I don't go anywhere without a watch." (0.0–2.12s) —
  personal-habit statement opening an anecdote; `story_open` fits best.
- Single-channel: first cut at 2.367s (`cut_in_first_1500ms: false`); the
  only text on screen in 0–3s is "Raw Video Preview: AGMEDI" (0.0–16.75s,
  top) — technically `caption_in_first_1500ms: true`, but it is a frame
  label, and it *anti-hooks*: it tells the viewer the content is unfinished.
- No loudness event: second 0 is −23.0 dBFS against a −21.62 mean.
- Strength 1: a device exists (immediate speech, mild curiosity in "watch
  roll") but it is single-channel, and the video's actual grail — the Patek
  5711R — is not even hinted until 43.4s.

### Structure beats

| span | label | evidence |
|---|---|---|
| 0.000–16.567 | other | raw-take preview: "Raw Video Preview" label 0.0–16.75s; only 2 cuts; loudness mean −24.12 dBFS; monologue ends "London." 16.16s |
| 16.567–17.06 | other | transition sting: "GO!" caption 16.75–17.25s; cuts at 16.567/17.267s; loudness jumps −23.2 → −18.6 dBFS (s16→17) |
| 17.06–23.7 | hook | verbatim re-delivery with subtitles: "I don't go anywhere without a watch" 17.06–19.4s; subtitle events from 17.5s; ROLEX dial OCR 19.0–19.75s |
| 23.7–42.92 | build | infatuated since 8 (24.72s) → first Timex ["Hymex", ASR conf 0.692] £15 from Argos (28.76–33.28s) → first Rolex at 18 (35.28–36.8s) → "50 plus watches" (39.12–40.5s); the 15-cuts-in-10s montage burst sits at 20–30s |
| 42.92–48.4 | payoff | "my favorite piece ever, the Patek Philippe Nautilus 5711R" 41.98–45.88s with matching dial OCR 44.0–46.0s; "it would be this" ends 48.32s |
| 48.4–55.074 | cta | speech ends 48.32s; music-only tail decaying −22.2 → −70 dBFS; "RAW VIDEO LINK PINNED IN COMMENTS" card 52.25–55.25s |

### Caption craft

Two text populations share one OCR stream: (a) real burned-in subtitles —
mixed-case, bottom/lower, phrase-length ("If I had to have one watch"
46.25–47.25s); (b) set text — watch-dial print, AGMEDIA/MrDenoise
watermarks, the prop-money microprint. Aggregates are polluted accordingly:
median `words_visible` 3, all_caps only 23/49, positions scattered (center
15 / bottom 13 / lower 11 / top 10). Judging the subtitle layer where it is
identifiable: **style `phrase`**, position bottom, mixed case, coverage only
17.5–48.5s (the preview section is uncaptioned — a real absence, since OCR
was running and caught the top label), sync ~0.4s lag ("I don't go anywhere"
caption 17.5s vs word 17.06s) though quantization blurs this.

### Rubric scores (RUBRIC-talking-head.md)

| criterion | score | evidence |
|---|---|---|
| G-TH-1 Cold-open hook (H1, H2) | **2** | speech at 0.0s (cold open, H2) but single-channel: no cut until 2.367s, no hook caption — only the "Raw Video Preview" label; no stated proposition inside 6s; strongest material (Patek) at 43.4s violates H1 front-loading |
| G-TH-2 Hook-promise congruence (H3) | **1** | title promises "Raw Footage"; the upload is an edited showcase (33 cuts, subtitles, music conf 0.676). As a talking-head video, the open makes no promise the payoff resolves — the Patek reveal answers a question that was never asked |
| G-TH-3 Cut motivation (E1/E5, E8) | **3** | the edited section shows real motivated cutting: 24/33 cuts within 150ms of a word end; noun-to-image matching measured (PATEK dial OCR 44.0s vs speech 43.4s; TIMEX INDIGLO OCR 29.25s vs "Hymex" 28.76s; prop-money OCR 37.0s under the spending talk at 37.4–40.5s). But the 15-cuts/10s burst at 20–30s has no transcript escalation motivating it, and the container structure (preview + verbatim repeat) breaks rhythm at the video level |
| G-TH-4 Visual organization (P1) | **fail on measurables** | 1920×1080 landscape — fails P1's vertical 9:16 for short-form distribution. Composition/lighting: `cannot_judge`, no keyframes |
| G-TH-5 Caption craft (P2, E9, P11) | **2** | coverage only 17.5–48.5s; first 16.6s of speech uncaptioned (P11 SC 1.2.2 is Level A); mixed case, scattered positions; watermark/dial pollution in the text channel; sync ~0.4s |
| G-TH-6 Sound (P1, P10) | **3** | music present (conf 0.676) and speech dominant while speaking (ratio 0.84); but a ~6 dB section jump (−24.12 → −18.09 dBFS at s16) and a 6.7s speech-free outro decaying to −70 dBFS — measurable dead air, the exact C1 swipe risk |
| G-TH-7 Anti-slop (A1, A2) | **3** | the story is genuinely human and specific (£15 Argos Timex at 8 → Rolex at 18 → 50+ watches → 5711R grail — A2 creative vision, no template). Against it: AGMEDIA + MrDenoise watermarks in-frame (P2 third-party watermark penalty) and a demo-reel container rather than an authored video |

### study.md contract JSON

```json
{
  "hook": {
    "evidence": [
      "words 0.0–2.12s: 'I don't go anywhere without a watch.'",
      "shots: first cut at 2.367s — none inside 1.5s",
      "captions 0.0–16.75s: 'Raw Video Preview: AGMEDI' (confidence 0.994, position top) — a frame label, not a hook caption",
      "loudness_curve[0] = -23.0 dBFS vs video mean -21.62 — no opening level event",
      "the video's strongest object, 'the patek philippe nautilus 5711r', is first spoken at 43.4–45.88s"
    ],
    "reasoning": "Immediate speech opening a personal anecdote, but single-channel: no early cut, no supporting caption, no loudness event, and the on-screen label actively signals unfinished content. A hook device exists; nothing reinforces it.",
    "type": "story_open",
    "strength": 1,
    "speech_in_first_1500ms": true,
    "caption_in_first_1500ms": true,
    "cut_in_first_1500ms": false
  },
  "beats": [
    {"label": "other", "start": 0.0, "end": 16.567, "evidence": "raw-take preview: 'Raw Video Preview' label 0.0–16.75s; 2 cuts total; loudness mean -24.12 dBFS; take ends 'London.' at 16.16s"},
    {"label": "other", "start": 16.567, "end": 17.06, "evidence": "'GO!' caption 16.75–17.25s; loudness jumps -23.2 to -18.6 dBFS across s16–17"},
    {"label": "hook", "start": 17.06, "end": 23.7, "evidence": "verbatim re-delivery of the 0–16s monologue (first 59 words identical token-for-token) now with bottom subtitles from 17.5s and ROLEX dial OCR at 19.0s"},
    {"label": "build", "start": 23.7, "end": 42.92, "evidence": "collecting arc: 'infatuated... eight years old' 24.72–27.72s, 'first hymex from 15 pounds' 28.76–30.62s, 'first rolex' 36.42s, '50 plus watches' 39.12–40.5s; cuts_per_10s peaks at 15 in the 20–30s bucket"},
    {"label": "payoff", "start": 42.92, "end": 48.4, "evidence": "'my favorite piece ever the patek philippe nautilus 5711r' 41.98–45.88s; matching dial OCR 'PATEK PHILIPPE NAUTILUS 5711R' 44.0–46.0s; 'it would be this' ends 48.32s"},
    {"label": "cta", "start": 48.4, "end": 55.074, "evidence": "speech ends 48.32s; music-only tail -22.2 to -70.0 dBFS; 'RAW VIDEO LINK PINNED IN COMMENTS' 52.25–55.25s"}
  ],
  "caption_style": {
    "evidence": [
      "49 events but two populations: burned-in subtitles (e.g. 'I don't go anywhere' 17.5–18.75s, bottom, conf 0.994) vs set text (dial print 'ROLEX 13' 19.5s, watermarks 'MrDenoise' 26.5s, prop-money microprint 37.0s)",
      "subtitle layer: mixed case (all_caps 23/49 overall), bottom/lower, phrase length (overall median words_visible 3)",
      "coverage gap: no subtitles 0–17.5s despite continuous speech from 0.0s — OCR was live (top label captured), so the absence is real",
      "sync: subtitle start 17.5s vs word start 17.06s (~0.4s lag; 0.25s OCR quantization applies)"
    ],
    "reasoning": "Phrase subtitles exist only in the edited section; the raw preview is uncaptioned. Aggregate stats are polluted by non-caption screen text, so per-layer numbers are approximations.",
    "present": true,
    "style": "phrase",
    "position": "bottom",
    "all_caps": false,
    "notes": "watermark text (AGMEDIA, MrDenoise) rides the caption channel — flag for P2 watermark penalty and for OCR layer-separation work"
  },
  "why_it_works": "As a published short it doesn't, and the measurements say exactly why: the first 16.6s is a labeled preview of unfinished footage (label 0.0–16.75s, 2 cuts, -24.12 dBFS), after which the viewer hears the identical 59 words again (verbatim repeat, 17.06s) — roughly 60% of the runtime elapses before any new information, the inverse of C1's completion logic. The craft inside the edited section is real: 24/33 cuts land within 150ms of a word end, and nouns get their objects on screen within ~0.6s (PATEK OCR 44.0s vs speech 43.4s). But the structure buries the payoff at 43s behind a weak single-channel open (strength 1), the frame is landscape 1920x1080 against P1's vertical spec, and the video exits on 6.7s of speechless music decaying to -70 dBFS. It functions as an editing-practice demo — before/after in one file — not as a retention-shaped short."
}
```

---

## 3. Direct-mode preview: Ryan's footage → Cleo-style target

Premise: the raw clip is Ryan's captured footage; the reference is the style
target. Below is the gap report the product would hand back, then the shot
prompts that close the gaps. Everything cites a measurement from one of the
two breakdowns or a rubric criterion — no invented footage qualities.

### Gap report

1. **Hook deficit (G-TH-1; H1, H2).** Target lands speech + caption + cut
   inside 1.5s and completes its claim by 2.78s. Your footage opens
   single-channel (first cut 2.367s, no hook caption) with a habit statement,
   and your best asset — the Patek 5711R, spoken at 43.4s — never touches the
   hook window. The strongest 5 seconds of material is in the last 12 seconds
   of the file.
2. **Wasted runtime / retention shape (C1).** 0–16.6s is a preview take whose
   59 words repeat verbatim at 17.06s. Target wastes zero seconds:
   speech_ratio 0.995, premise done at 2.78s. Cutting the preview and the
   repeat recovers ~17s of a 55s file.
3. **No promise → no payoff arc (G-TH-2; H3).** Target speaks its title nouns
   at 0.2s and 2.02s and resolves them at 26–37s. Your footage answers "what's
   your favorite watch?" — but nothing in the first 6s asks the question. The
   payoff exists (5711R reveal, 41.98–45.88s, dial on screen 44.0s); it needs
   a debt to repay.
4. **Format (P1).** 1920×1080 landscape vs the 9:16 vertical target (reference
   is 0.563 aspect). Reframe or reshoot; captions must then live inside the
   P6 safe box (x ∈ [65, 880], y ∈ [270, 1248] at 1080×1920).
5. **Caption coverage and hygiene (G-TH-5; P2, P11, E9).** Subtitles cover
   only 17.5–48.5s, mixed case, ~0.4s lag; watermarks (AGMEDIA, MrDenoise)
   ride the frame — P2 names third-party watermarks as a downrank. Target:
   full-coverage all-caps lower-third phrase captions, ≤20 cps (E9).
6. **Audio envelope (G-TH-6; P10, C1).** A 6 dB level jump between sections
   (−24.12 → −18.09 dBFS) and a 6.7s speech-free outro decaying to −70 dBFS.
   Target holds −15..−22 dBFS throughout, lifts ~3.8 dB into the payoff, and
   ends 0.03s after the last caption. Dead air is measurable swipe risk.

### Shot prompts (filmable direction)

1. **The grail cold-open (closes gaps 1 & 3).** Vertical 9:16. Macro on the
   5711R dial filling the upper two-thirds of frame, wrist turning once.
   Deliver a claim over it in the first breath — "I've owned fifty watches.
   I'd sell every one of them before this." — with one cut at ~1.2s from dial
   to your face mid-sentence, and an all-caps phrase caption burned from
   frame 0. Targets, from the reference: speech 0.0s + caption 0.0s + cut
   ≤1.5s (its cut is at 0.292s) = strength-2 hook; claim complete ≤3s (H1;
   reference finishes at 2.78s). This also converts the 43s buried payoff
   into the promise the rest of the video repays (H3).
2. **The £15 origin insert (closes gap 2's salvage).** Re-use the measured
   reflex your own edit already proves — TIMEX INDIGLO on screen 29.25–30.0s
   against "Timex" spoken 28.76–29.5s, Patek dial at 44.0s against speech at
   43.4s. Film one steady 2s close-up of the Timex in-hand and cut it in
   within 0.5s of the word, keeping the build at the reference's mid-video
   cadence (5–6 cuts/10s), not the unmotivated 15-cuts/10s burst.
3. **The ladder montage (closes gaps 1 & 6 pacing).** Three wrist shots,
   oldest to newest — Timex, first Rolex, the watch roll — 0.8–1.2s each, cut
   exactly on the clause ends of a rewritten three-beat line. The reference's
   cuts sit within 150ms of word ends 18 times out of 22 (e.g. cut 8.5s /
   "snows," 8.4s; cut 26.083s / "too." 25.96s): cut where the sentence
   breathes, per E5/E7 — the cut belongs where the thought completes.
4. **The held reveal (closes gap 6's shape).** The "one watch for the rest of
   my life" line in a single static 5–6s take, no b-roll, no cutaway. The
   reference reserves its longest shot (5.5s at 32.333s, triple its 1.848s
   average) for the punchline and lifts loudness ~3.8 dB into it — stillness
   is the payoff signal. Kill the current 6.7s music-only tail.
5. **CTA inside the energy (closes gaps 5 & 6).** Final 4s: wrist drops out
   of frame, spoken CTA landing ~1.5s before the end — the reference speaks
   "subscribe" at 40.66s in a 42.5s video and its last caption ends on the
   final frame. Caption the CTA all-caps, inside the P6 safe box, and end the
   video on the last word, not on a fade.

That is the product's promise in miniature: every one of these five prompts
is derived from a number in the two breakdowns, and any competent phone
camera can execute all five in an afternoon.

---

## 4. Honest limits

**Where the breakdown data constrained this judgment**

- **No keyframes committed** (manifest: derived frames not committed). Every
  visual criterion — G-TH-4 composition/lighting, E5's emotion/eye-trace
  weights (58% of Murch's rubric), hook visual channel — was `cannot_judge`.
  Both videos happened to open with speech at 0.0s, so the visual-hook rule
  never forced a `cannot_judge` on hook *type*; a b-roll-first video would
  have been unjudgeable.
- **One OCR stream, many text layers.** Subtitles, location labels, dial
  print, watermarks, and prop-money microprint all share `captions[]`.
  Aggregates (words_visible, position, all_caps) are polluted; I judged the
  subtitle layer by manually reading events, which does not scale.
- **Caption sync test vs instrument resolution.** study.md asks whether
  captions land within ~150ms of spoken words; body OCR samples at 4fps
  (250ms). The question is unanswerable as posed after the 3s hook window.
- **Highlight animation invisible.** The truth doc says word-timed keyword
  highlighting; `words_visible` says phrase display. OCR cannot distinguish
  them — the measured classification (`phrase`) may understate the craft.
- **`has_music: false` + confidence 0.0 on the reference is a trap.** The
  warning saved it ("detection inconclusive"), but a boolean false stated
  alongside a warning is easy to misread. Inconclusive should surface as
  null, not false. Loudness is mean RMS dBFS per second, not LUFS — the
  P9 target (−14 LUFS / −1 dBTP) cannot be checked from this data.
- **F-16 adjudicated:** the measurements settle it — the published upload has
  33 cuts, 49 caption events, and a verbatim monologue repeat; the truth
  doc's §2 is wrong about the file it claims to describe. Replace the fixture
  with the genuinely raw file behind the download link, or re-annotate.

**What a better measurement would unlock**

- Committed (or licensable) keyframes → hook visual channel, composition
  scoring, and E5's dominant weights come online. This is the single highest-
  leverage gap.
- OCR layer separation (position + persistence clustering: an event spanning
  16.75s at "top" is a label, not a caption) → clean caption metrics and a
  free watermark detector for the P2 check.
- Integrated LUFS + true peak → P9 enforcement; word-level caption timing at
  hook fps throughout → the 150ms sync test becomes real.
- Duplicate-take detection (the verbatim-repeat check I ran by hand is ~5
  lines over `words[]`) → direct mode will need it on every real raw input,
  because retakes are what raw footage *is*.

**Verdict on prompts/study.md**

It guided well — the warnings-first rule caught the music trap, cite-or-
abstain kept every verdict traceable, the anchored 0–1–2 strength scale made
the two hooks cleanly comparable (2 vs 1), and "evidence before verdicts"
genuinely changed the order I worked in. Four fixes for v0.2: (1) the hook
vocabulary lacks `curiosity_gap`/`open_loop` even though H2 names open loop
by name and the reference is a textbook case — `claim` was the nearest legal
label and it loses information; (2) the ~150ms sync test should be stated
relative to OCR sampling resolution or it invites false precision; (3) add
one line on multi-layer OCR text ("captions[] may contain non-caption screen
text; judge the subtitle layer"); (4) beats has no vocabulary for raw-footage
structures (retakes, slates, preview labels) — `other` absorbed it here, but
direct mode's whole input class is footage like this, and the prompt should
say what a retake looks like in measurements. One quiet strength worth
keeping: the example judgment shows an *accelerating* payoff while the real
reference *decelerates* into its punchline — the prompt's "its structure is
the contract, not its prose" warning is what kept the example from biasing
the read.
