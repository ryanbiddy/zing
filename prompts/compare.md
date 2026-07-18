---
name: compare
description: How to judge a NEW breakdown AGAINST a StyleProfile + its genre rubric — band-by-band, criterion by criterion — and write the comparison back.
version: 0.5.0
required_keys: [fit, rubric_scores, deviations, overall]
---

# Judging a breakdown against a StyleProfile

You are scoring ONE new video against a taste target: a StyleProfile
aggregated from references the user admires. The question is never "is
this video good?" — it is "how close is this video to what THIS profile
says the user's taste measurably is, and where exactly does it differ?"
Every verdict traces to a profile stat or a rubric criterion, cited.

## 1. Get both sides

- `get_profile(name)` — the target. Read `warnings`,
  `unjudged_source_slugs`, and each stat's `n` FIRST: a stat built from
  n=2 sources supports weaker claims than n=8, and you must say so.
- `get_breakdown(slug)` — the new video (rules of the `study` prompt
  apply: warnings first, cite or abstain, visual material via keyframes
  or `get_frames`).

## 2. Band rules (measured fit)

For each measured dimension, compare the breakdown's value to the
profile's `[p25, p75]` band:

- `inside_band` — the value sits within p25–p75.
- `near_band` — outside but within one band-width (p75−p25) of the edge.
- `outside_band` — beyond that.
- `cannot_judge` — the breakdown lacks the measurement (warnings say
  why), or the profile stat has n=0.

Rules: cite BOTH numbers verbatim ("shot_duration median 1.8s vs
profile band 0.9–1.4s, n=5"). A `curve` comparison
(`cuts_per_10s_curve`) is judged bucket-by-bucket over normalized
position — name the buckets that diverge, not "the pacing differs".
Low-n humility: when a stat's n < 3, prefix the verdict's reasoning
with "thin evidence (n=…)". Never average away a bimodal profile —
if p25–p75 is wide, say the profile itself is loose on that dimension.

## 3. Rubric criteria (judged fit)

If your client can read repo files, open `docs/taste/INDEX.md`, find the
profile's `genre` rubric, and score the criteria that apply — citing
**criterion IDs** verbatim, with breakdown evidence per score (0–1–2
anchored, as each criterion defines). If you cannot access the rubric
docs, set `rubric_scores` to `"cannot_judge"` and say why — never score
criteria from memory of what a rubric probably says.

## 4. Output shape (the contract)

All four top-level keys required; evidence and reasoning before
verdicts, everywhere.

<example_judgment>
{
  "fit": {
    "pacing": {
      "evidence": ["avg_shot_duration 1.1s vs profile shot_duration band 0.9-1.4s (median 1.1s, n=4)", "cuts_per_10s_curve: buckets 1-8 inside band; bucket 9 at 2 cuts vs band 6-9 (n=4)"],
      "reasoning": "Cut rhythm matches the profile through the body; the ending decelerates where the references accelerate.",
      "verdict": "near_band"
    },
    "hook": {
      "evidence": ["time_to_first_word 0.4s vs band 0.0-0.9s (n=4)", "time_to_first_caption 0.6s vs band 0.2-0.8s (n=3)"],
      "reasoning": "Verbal and caption hook timing both inside band.",
      "verdict": "inside_band"
    },
    "captions": {
      "evidence": ["words_visible mode 1 vs profile mode 1", "all_caps rate 0.92 vs profile 0.87"],
      "reasoning": "Same word-pop, same case convention.",
      "verdict": "inside_band"
    },
    "audio": {
      "evidence": ["speech_ratio 0.71 vs band 0.78-0.94 (n=4)", "has_music true vs music_present_rate 1.0"],
      "reasoning": "Slightly more silence than the references; music present as expected.",
      "verdict": "near_band"
    }
  },
  "rubric_scores": [
    {"criterion_id": "TH-H2", "evidence": "spoken claim + caption inside 1.1s", "reasoning": "multi-channel open per the anchor", "score": 2},
    {"criterion_id": "TH-P1", "evidence": "cuts_per_10s falls to 2 in the final bucket", "reasoning": "ending drags vs the anchor's 'no dead tail'", "score": 1}
  ],
  "deviations": [
    {"dimension": "ending pacing", "profile_stat": "curve bucket 9 band 6-9 cuts", "observed": "2 cuts", "direction": "slower", "meaningful": true, "note": "references end hot; this trails off — the single biggest taste gap"},
    {"dimension": "speech_ratio", "profile_stat": "band 0.78-0.94", "observed": "0.71", "direction": "more silence", "meaningful": false, "note": "close to band edge; thin difference"}
  ],
  "overall": {
    "evidence_summary": "2 of 4 fit dimensions inside band, 2 near; one meaningful deviation (ending pacing) backed by both the curve stat and criterion TH-P1",
    "reasoning": "The video is recognizably in the profile's style; the ending is where it leaves the taste target.",
    "verdict": "partial_fit"
  }
}
</example_judgment>

`overall.verdict` ∈ `strong_fit` | `partial_fit` | `weak_fit` |
`cannot_judge`. Every entry in `deviations` needs both numbers and a
`meaningful` call — a deviation inside measurement noise is honest to
report as not meaningful.

## 5. Write it back

`save_judgment(slug, judgment, section="compare", model="<your model>")`
— the comparison lives on the NEW video's breakdown, alongside its
`study` judgment. Send the complete object; the section is replaced
wholesale.

Restating the contract: read both `warnings` and every stat's `n`
first; cite both numbers in every band verdict; criterion IDs verbatim
or `rubric_scores: "cannot_judge"`; all four keys present; low-n claims
stay humble.
