# S3 direction gate — full-fidelity rerun (closes the S3 limit)

Date: 2026-07-20. Runner: Lane B (Claude Fable 5) as the directing AI.
Closes limit #1 of `S3-GATE-lane-b.md`: that gate directed
`raw-editing-practice`, which F-16 measured as EDITED (34 shots, 49
burned captions) standing in as "raw". This rerun directs footage that
is genuinely unedited.

## Input (Lane C's C-CD1 freeze, PR #309)

`raw-talking-head-korky-paul` — "Korky Paul Introduction", CC0 1.0,
source SHA-256 pinned in `research/RAW-MODE-SOURCE.md`. Verified by
Lane C as one uninterrupted portrait talking-head take: no cuts,
cutaways, captions, overlays, or title cards, with an FFmpeg
`scene>0.25` scan returning zero candidates.

Measurements this direction stands on: 19.067s, 1080×1920, **1 shot**,
49 words, **0 captions**, speech 0.34–17.74s, `provenance.raw_mode`
one keeper 0.34–17.74s with evidence (uninterrupted take, no filler,
no interior dead air, loudness within 12 dB of speech level).

## Method — the real chain, no fakes

Seeded scratch workspace → frozen breakdown installed as a slug →
`prompts/direct.md` v1.0.0 followed as written → judgment written →
`h_save_judgment(section="direct", model="claude-fable-5")` → contract
validated, `prompt_version` 1.0.0 stamped → **`direction.md` rendered**
next to the breakdown in creator order.

Rule 4 ("visual claims need eyes") honored literally: `hook_0s.jpg` and
`hook_2s.jpg` were VIEWED before any framing claim, and the direction
says which frames were viewed.

## What the direction found

- **MUST FIX (G-TH-1):** speech starts fast (0.34s) but the first 6s is
  self-introduction — no proposition, no curiosity gap; the only
  interesting claim (Winnie and Wilbur → TV series) arrives in the
  final 5s. Cuts in 0–3s: 0. Shot prompt 1 films a 3s hook that moves
  the claim to the front.
- **MUST FIX (G-TH-7):** last word ends 17.74s on a fact mid-flow, no
  ask, then 1.33s of silence (loudness windows 18–19 at −61.1/−78.0 dB
  against a −15…−19 dB speech body). Shot prompt 2 films a 4s ending.
- **SHOULD FIX (G-TH-2):** congruence cannot be scored because there is
  no opening promise — recorded as a CONSEQUENCE of G-TH-1, not as an
  independent defect.
- **POLISH (G-TH-5):** `captions[]` empty — correct for raw footage,
  flagged for the edit, with the OCR sampling warning cited so absence
  is a measurement rather than an inference.
- **Keeper:** the measured keeper verbatim, plus a trim of the 1.33s
  silent tail, citing the loudness windows.

## What is new versus the S3 run (why the rerun mattered)

1. **Keepers now come from real raw-mode measurement.** The S3 run had
   to pick spans from `words[]` and SAY the keeper machinery hadn't
   run. This one cites the keeper's own recorded evidence.
2. **The "no captions" finding is now true of the SOURCE.** Against the
   edited stand-in, 49 burned captions made that branch untestable.
3. **Single-shot reality exercised a path the stand-in could not:**
   `cuts in 0-3s: 0` is a rubric measurement that only means something
   on footage that genuinely has no cuts.

## Honest limits of THIS run

1. **Rubric-only mode.** No StyleProfile existed in the scratch
   workspace, so the direction is generic-craft-grounded, not
   taste-grounded — stated in `verdict` and `assembly_notes` rather
   than silently assumed, per the prompt's degradation rule. A profile
   would likely change the hook style and length calls.
2. **The source is a 19s introduction, not a creator's short.** It is
   ideal for proving raw-mode direction (one clean take, nothing
   edited) and unrepresentative of the format Zing targets — the gaps
   found are real against the rubric but modest in stakes.
3. **Judgment quality remains unjudged.** As at S2/S3, no human has
   scored whether this direction is GOOD; the gate proves the chain is
   honest and grounded, not that the taste is right.

## Gate verdict

**PASS.** The S3 chain runs end to end on genuinely unedited footage
with keepers grounded in measured raw-mode evidence, every gap citing
both sides with numbers, visual claims made only after viewing frames,
and rubric-only degradation stated rather than hidden. `S3-GATE-lane-b.md`
limit #1 is closed; limit #2 (profile taste-coherence) is unchanged and
still belongs to Ryan's real reference set.
