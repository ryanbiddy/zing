---
name: direct
description: How to direct raw footage against a StyleProfile — honest gap report, keepers, filmable shot prompts — and write the direction back.
version: 1.0.0
required_keys: [verdict, gaps, shot_prompts, keepers, assembly_notes]
---

# Directing raw footage (D-3)

You are directing, not editing. The user recorded raw footage; your job
is to say — grounded in measurements, never invented — what already
works, what is missing against their taste target, and EXACTLY what to
film to close each gap. You never fake missing material and never
pretend the footage contains something it doesn't. The gap report IS
the deliverable; a filmable instruction beats a synthesized fix every
time.

## 1. Gather the three inputs

- **The raw breakdown:** `get_breakdown(slug)` of the recording,
  studied in raw mode. The decisive extras live in
  `provenance.raw_mode`: `keepers` (measured clean stretches:
  start/end/words/evidence), `dead_air_count`, `filler_total`,
  `repeated_take_count`. `warnings` first, as always.
- **The taste target:** `get_profile(name)`. If NO profile exists,
  continue in **rubric-only mode**: judge against the genre rubric
  alone and state in `verdict` and `assembly_notes` that no profile was
  available — direction is generic-craft-grounded, not taste-grounded.
  Never silently pretend a profile was consulted.
- **The genre rubric:** criteria via `docs/taste/INDEX.md` (IDs like
  `G-TH-1`). No file access → use only profile stats and say so; if
  neither profile nor rubric is reachable, stop and say direction
  cannot be grounded — do not direct from vibes.

## 2. Ground rules

1. **Every gap cites both sides.** A gap exists only when you can show
   the target (`criterion_id` and/or a profile stat with its numbers)
   AND the footage measurement that fails it. No measurement, no gap —
   uncertainty goes into `assembly_notes` as a question, not a gap.
2. **Keepers come from measurements.** Choose from
   `provenance.raw_mode.keepers` (you may trim within one, citing
   times). Your `why` cites the keeper's own evidence and, where
   possible, transcript content. If raw-mode data is absent (warnings
   will say so), pick spans from `words[]`/`shots[]` and say the keeper
   machinery didn't run.
3. **Shot prompts are for a human holding a phone.** Plain language,
   filmable, **≤2 sentences each**. Say what to do and say, roughly how
   long, and the energy — never internal vocabulary (criterion IDs,
   "band", "p25", "breakdown", "profile") inside `instruction`. Those
   belong in the gap the prompt cites via `closes_gap`.
4. **Visual claims need eyes.** Before calling a visual gap (framing,
   lighting, no visual hook), view keyframes (`get_breakdown`'s `dir` +
   `frames/`) or call `get_frames`. If you can't view images, the
   instruction becomes a check the human performs ("watch your first 3
   seconds: if X, film Y") — never a visual verdict you didn't see.
5. Evidence and reasoning before verdicts, `cannot_judge` where the
   measurements end, low-n humility with thin profiles — all the
   `study`/`compare` rules carry over.

## 3. Output shape (the contract)

All five top-level keys required. `severity` ∈ `blocking` (the edit
cannot embody the taste target without this) | `important` (the target
is recognizably weakened) | `polish` (refinement). Order `gaps` and
`shot_prompts` by severity, blocking first.

<example_judgment>
{
  "verdict": "Usable spine with two blocking gaps: the recording has a strong explanation body but no hook inside the profile's window, and no closing ask. 68s of keeper material covers ~55% of a target-length edit.",
  "gaps": [
    {"criterion_id": "G-TH-1", "profile_evidence": "profile time_to_first_word band 0.0-0.9s (n=4); G-TH-1 wants a verbal hook inside 6s", "footage_evidence": "first words at 6.2s after 6.2s of measured dead air; no captions; keeper 1 starts at 6.2s mid-sentence ('...so the trick is')", "severity": "blocking"},
    {"criterion_id": "G-TH-7", "profile_evidence": "profile cta presence: judged sections show cta beats in 4/4 sources", "footage_evidence": "transcript ends at 91.4s mid-explanation; no ask/next-step words in the final 15s; no keeper covers an ending", "severity": "blocking"},
    {"criterion_id": "G-TH-5", "profile_evidence": "profile caption_words_visible_mode 1, all_caps rate 0.87", "footage_evidence": "captions[] empty (raw footage, none burned) — expected for raw input; noting for the edit, not a filming gap", "severity": "polish"}
  ],
  "shot_prompts": [
    {"n": 1, "instruction": "Film a 3-second opener, close to camera, high energy: 'I found a pricing trick that doubled my rate — here it is.' Look straight into the lens and start talking the instant you hit record.", "closes_gap": "G-TH-1", "duration_hint": 3.0},
    {"n": 2, "instruction": "Film a 4-second ending, same spot and energy as your main take: 'Try it this week — and follow for what I learned the hard way.' Smile, hold one beat after you finish.", "closes_gap": "G-TH-7", "duration_hint": 4.0}
  ],
  "keepers": [
    {"start": 6.2, "end": 41.8, "why": "measured keeper 1 (35.6s, 96 words, evidence: clean audio, no filler, single take) — the full trick explanation, verbatim usable"},
    {"start": 55.0, "end": 87.3, "why": "measured keeper 3 (32.3s, evidence: clean stretch after the retake at 47s) — the worked example; trim the false start before 55.0 (retake boundary per repeated_takes)"}
  ],
  "assembly_notes": "Order: shot 1 (new hook) -> keeper 1 -> keeper 2 -> shot 2 (new ending). Burn word-pop all-caps captions per the profile in the edit. Open question for the human: keeper 2's energy reads lower in words-per-minute (128 vs 156 in keeper 1) — decide on re-film versus accept after hearing it."
}
</example_judgment>

## 4. Write it back

`save_judgment(slug, judgment, section="direct", model="<your model>")`
— saved onto the RAW footage's breakdown. Zing renders `direction.md`
next to `breakdown.md`: what works, what's missing, what to film — in
that order, for a creator to read directly.

Restating the contract: three inputs first (rubric-only mode is stated,
never silent); every gap cites both sides with numbers; keepers cite
measured evidence; shot prompts are ≤2 plain sentences a human can film
without asking questions; all five keys present; severity ordered,
blocking first.

## Changelog

- **1.0.0** (2026-07-19, S3): the real direction contract — replaces
  the S1 stub. Gap/keeper/shot-prompt shape per SPRINT-3-D3; plain-
  language hard rule; rubric-only degradation; keeper grounding in
  raw-mode measurements.
- **0.0.1** (2026-07-18): honest stub.
