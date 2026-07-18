# S2 Lane B gate record — profile-grounded judgment, run for real

Date: 2026-07-18. Runner: Lane B (Claude Fable 5) as the judging AI.

## Method

Seeded a scratch workspace with the five frozen real-video breakdowns
(`tools/eval/real_videos/`), then ran the REAL chain end to end — no
fakes anywhere:

1. `h_build_profile("gate-refs", [short-daily-dweebs,
   x-nasa-artemis-backseat-drivers, landscape-big-buck-bunny],
   genre="talking-head", platform="tiktok")` → Lane A's merged builder
   (#92) via the MCP tool's seam auto-wire (keyword-only genre/platform
   sniff worked as designed).
2. Judged `reference-cleo-antarctica` against the profile following
   `prompts/compare.md` 0.5.0 exactly (band rules, both numbers cited,
   low-n humility, honest abstentions).
3. Saved via `h_save_judgment(section="compare",
   model="claude-fable-5")` — stamped prompt_version 0.5.0, round-trip
   verified.

D-Q9 candidates are not yet studied (no media pipeline deps in this
environment), so the frozen set stood in as sources — noted honestly:
this proves the MACHINERY; the taste verdict needs Ryan's real
reference set.

## What the run showed (the system being honest with itself)

The judgment's verdict is `weak_fit`, and the reasoning says the more
important half: **this profile describes no coherent taste** — its
sources are an animation feature, an 18s short, and an X clip, all
unjudged, so bands are wide to the point of unfalsifiability
(8 of 10 curve buckets span p25=0 to p75 up to 26). Cleo diverges
exactly where a fast-cut talking-head should: pacing (median shot 1.5s
vs band 4.8–18.3s), captions (all-caps 1.0 vs 0.056; words_visible 5 vs
1), speech density (0.995 vs band 0–0.42). Hook timing was the one
inside-band dimension. 2 of 3 rubric criteria (G-TH-5, G-TH-6)
abstained honestly — visual contrast and music-bed halves are
unmeasurable from this frozen data.

Full judgment JSON lives on the breakdown copy in the gate workspace;
the same content is reproducible from this doc's numbers.

## Findings for Lane A (judgment calls, no action from me)

1. **n=2 percentile interpolation emits impossible values:**
   time_to_first_word p25 = **−1.085s** on two non-negative observations
   (0.0, 11.065 area). Suggest clamping percentiles to the observed
   min/max (or inclusive method) — a negative time-to-first-word will
   read as a bug to every consumer.
2. **Profile coherence warning:** when a stat's band width exceeds
   ~3× its median, the profile can't falsify anything on that dimension.
   A one-line warning ("duration band spans 18–635s — sources may not
   share a format") would have named this profile's problem before any
   judgment ran. Candidate for the S2 review round.

## Gate verdict

Lane B S2 gate: **both halves now run** — MCP round-trip in CI (12-tool
stdio surface) and a real profile-grounded judgment through the real
builder and real tools. Remaining for the SPRINT gate (orchestrator +
Ryan): rebuild from genre-consistent, judged references when Ryan's
picks land, and put that judgment in front of Ryan.
