# Raw-mode filler precision: measuring "like" against real speech

## Why this exists

C-CD1 froze a licensed genuinely-raw talking-head clip (#309) — the
first real-video exercise of raw mode. Its human-truth section is
honest that the raw measurements are "analyzer outputs, not
hand-labeled truth"; the fixture proves the pipeline RUNS, not that
its numbers are RIGHT. And the clip is clean (0 dead air, 0 fillers,
0 retakes), so it can only demonstrate the absence of false
positives — never detection accuracy.

This note closes part of the remaining gap using material already
measured: the sweep's 62-minute live-studied interview
(`x-1875286149788573873`, 10,088 words of real conversational
speech).

## What the clean fixture actually validated (independently checked)

Recomputing from the fixture's own word timings, without trusting the
analyzer:

- inter-word gaps ≥ 1.5s (DEAD_AIR_MIN_S): **0** — matches "0 dead air"
- leading silence 0.34s, trailing 1.33s — both under the floor, so no
  edge dead air is correct
- transcript contains no filler tokens — matches "0 fillers"
- keeper span 0.3–17.7s vs measured speech 0.34–17.74s — the keeper
  tracks the actual speech, not an invented boundary

So: no false positives on clean footage, keeper boundaries honest.
That is real, and it is all that clip can show.

## The finding: "like" is over-counted on real speech

Running raw mode over the 62-minute interview produced 105 fillers,
with `like` the largest single class at 37. Sampling 12 random `like`
contexts from the transcript showed roughly a quarter are not fillers
at all:

| Context (sampled) | Actual use |
|---|---|
| "made it sound **like** it's some big secret" | preposition |
| "no indication that he was **like** this" | comparative |
| "i don't **like** i don't trust the…" | verb |
| "i was **like** man i don't know" | quotative (genuine) |
| "happened man **like** i can't live with" | hedge (genuine) |

A creator told "you said 'like' 37 times" would find that several of
those are ordinary English. That is an over-count, and over-counting
is the same honesty failure as under-reporting.

## Fix shipped, deliberately conservative

`_like_is_not_filler` skips only unambiguous cases: a preceding word
that makes "like" a verb or preposition (don't / doesn't / sound /
looks / feels / seems / …) or a following word that makes it
comparative (this / that / it / them / …). Quotative and hedge uses —
the genuine fillers — are untouched. Anything ambiguous stays
COUNTED, so the measurement errs toward reporting rather than hiding.

Effect on the same interview: `like` 37 → 26, total fillers 105 → 94.
No other filler class changes.


- The 25% figure comes from a 12-context sample of one speaker, not a
  labeled corpus. It sizes the problem; it is not a precision metric.
- The guards are rules, not understanding: quotative "like" following
  a verb-ish word could still be skipped, and sarcastic or unusual
  phrasing is unhandled.
- Residual over-count is unmeasured. Closing that needs a labeled
  filler set — a genuinely useful future fixture, and the same shape
  as the P-C2 calibration pack.
- `you know` (34) and `i mean` (11) WERE audited in a follow-up pass
  (6 contexts each, same interview): all sampled uses are genuine
  discourse markers. Their known false-positive shapes ("do you know
  where…", "what I mean is") did not occur in this speaker's
  transcript, so no guard was added — a rule with no observed
  false positive to fix would be speculation, not measurement.

## Follow-up: `kind of` has the same over-count (audited exhaustively)

All 15 `kind of` hits were checked, not sampled. **6 are preceded by a
determiner**, marking the noun-phrase use where "kind" means TYPE:
"all that kind of stuff", "any kind of official manual", "some kind of
islamic banner", "any kind of screening device", "that kind of stuff".
Five of those six are genuine false positives; a determiner guard now
skips them (`kind of` 15 → 9, total 94 → 88).

**The sixth is a real hedge the rule wrongly skips**: "sure THAT kind
of revolutionized warfare" — that "that" is a complementizer, not a
determiner. Net effect is 5 false positives removed for 1 false
negative introduced. Separating the two needs part-of-speech tagging,
which is not worth a dependency here. The miss is PINNED by a test
(`test_known_false_negative_complementizer_that_is_documented`) so it
is a visible cost rather than an accident, and that test says to
update it if a future change fixes the case.

Cumulative effect on the interview: 105 → 94 (`like`) → 88 (`kind
of`). No filler class was ever silenced entirely.

## Honest limits (updated)
