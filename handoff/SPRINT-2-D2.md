# Zing Sprint 2 — D-2: StyleProfile (your taste, quantified)

Opened 2026-07-18 by the orchestrator. Contract: `StyleProfile` +
`StatSummary` in schemas.py (orchestrator-owned, same rules as ever).
S1 discipline carries over verbatim: owned paths, small PRs, failing-test-
first, never merge red, process observations per finished item.

## The point

N admired references (studied + judged) → one profile that says what YOUR
taste measurably is — then (S3) footage gets directed against it. Measured
and judged halves stay strictly separated; a profile is honest about
coverage (StatSummary.n, unjudged_source_slugs) or it is slop.

## Lanes

**Lane A — profile builder.** `myzing/profile/api.py:
build_profile(name, slugs, workspace=None) -> StyleProfile`. Measured
aggregates only: robust stats (median/p25/p75) per contract field;
cuts_per_10s_curve over NORMALIZED position (10 buckets of relative
runtime, so 30s and 60s sources align); time-to-first-cut/word/caption
from breakdown fields; transition counts from opt-in observations
(excluded sources named in warnings); format-aware (long-form sources
aggregate the same fields — duration stat carries the spread). CLI
`zing profile build <name> <slug...>` + `zing profile show <name>`.
Judged collection: copy judgment sections verbatim into `judged` keyed by
section, stamp `_meta` prompt versions, fill unjudged_source_slugs. Gate:
profile from 3+ real breakdowns matches hand-computed stats; honest on
mixed judged/unjudged sets.

**Lane B — surface + judgment grounding.** Storage: `profiles/<name>/
profile.json` (validate profile names like slugs); MCP tools
`build_profile`, `get_profile`, `list_profiles`. Prompt pack v0.5: the
judgment prompt that scores a NEW breakdown AGAINST a profile + its genre
rubric (cite criterion IDs + profile stats; honest-degradation rules
carry over). Gate: MCP round-trip; a real profile-grounded judgment of
the Cleo reference against a profile built from D-Q9 candidates.

**Lane C — profile eval.** Synthetic golden profiles: N synthetic
breakdowns with constructed stats → exact expected aggregates; mutation
matrix per aggregate family; real-profile regression from the frozen set
once Lane A lands. Extend the eval report. Gate: scorer catches each
mutated aggregate; per-dimension only.

**Lane D — light work.** Profile readability QA (show output as a creator
would read it); reference-set curation upkeep (D-Q9 list refreshed as
profiles get built).

## Sprint gate (orchestrator + Ryan)

Build a real profile from 3-5 of Ryan's picks (or D-Q9 candidates until
his land), judge one fresh reference against it, and Ryan reads the
output: does the profile describe a taste he recognizes, and does the
profile-grounded judgment beat the S1 rubric-only judgment? That verdict
shapes S3 (Direct).

## Status
- [ ] Lane A builder · [ ] Lane B surface+prompts · [ ] Lane C eval ·
- [ ] Lane D QA · [ ] Sprint gate (Ryan)
