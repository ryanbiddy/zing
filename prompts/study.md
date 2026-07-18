---
name: study
description: How to judge a Zing Breakdown — hook, beats, caption style, why it works — and write the judgment back.
version: 0.1.0
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
- `warnings[]` — **read this first.** Every measurement that was skipped
  or degraded is named here. A skipped measurement is not evidence of
  absence: if transcription was skipped, empty `words` does NOT mean
  nobody speaks.

If your client can read local image files, view the shot `keyframe`
images (they live next to `breakdown.json` in the Zing workspace —
`zing_status()` shows the workspace root) before judging the hook.
Otherwise judge from text and numbers only.

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
   from text measurements. Unless you actually viewed the 0–3s
   keyframes, set `hook.type` to `cannot_judge` and say in `evidence`
   what a human should check (e.g. "3 cuts in the first 1.4s but no
   speech or captions — watch 0–3s: likely a visual spectacle or
   pattern-interrupt open").
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
`payoff` | `cta` | `other`. Evidence per beat: what in the transcript,
captions, pacing, or loudness marks the span (e.g. "cuts_per_10s jumps
4→9 at 20s and the transcript pivots to the reveal"). Spans should cover
the video without overlaps; leave a span out rather than invent one. If
structure is genuinely unreadable from measurements, return a single
span labeled `other` whose `evidence` says why.

### caption_style

`style` ∈ `word_pop` (one word at a time, `words_visible` ≈ 1) |
`phrase` (2–6 words) | `sentence` (full lines) | `none` (no captions) |
`cannot_judge` (OCR skipped or all-low confidence). Report `position`
and `all_caps` from the observed majority; note timing sync (do caption
events land within ~150ms of their spoken words?). Weight evidence by
OCR `confidence` and say when you're reading low-confidence tea leaves.

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
    {"label": "payoff", "start": 21.5, "end": 33.0, "evidence": "'here's the exact number I use' at 21.7s; cuts_per_10s rises to 8"},
    {"label": "cta", "start": 33.0, "end": 36.2, "evidence": "words 33.1–35.9s: 'follow for part two'; final caption event 33.2–36.0s"}
  ],
  "caption_style": {
    "evidence": [
      "41 caption events, median words_visible = 1, median confidence 0.84",
      "38/41 events all_caps at position 'lower'",
      "caption starts track word starts within ~120ms through 0–20s"
    ],
    "reasoning": "Word-timed pop captions, uppercase, lower-third, tightly synced to speech.",
    "present": true,
    "style": "word_pop",
    "position": "lower",
    "all_caps": true,
    "notes": "sync drifts to ~400ms after 30s — either burned-in drift or OCR timing noise"
  },
  "why_it_works": "The open stacks claim, caption, cut, and level inside 1.1s (evidence above), so every channel says 'stay'. Pacing is the real device: a calm build (cuts_per_10s ≈ 4) makes the payoff acceleration (≈ 8 at 21.5s) feel like an arrival rather than noise. Word-pop captions at words_visible = 1 keep silent viewers parsing one beat at a time, and the sub-150ms sync means the captions read as the voice, not subtitles of it. The CTA stays inside the energy envelope instead of tacking on a cold outro (final caption event ends 0.2s before the video does)."
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
`cannot_judge` unless you saw keyframes.
