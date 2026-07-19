# Zing Sprint 3 — D-3: Direct (the anti-slop core)

Opened 2026-07-19. The product's signature move: raw footage + a
StyleProfile → an honest gap report + filmable shot prompts + a draft
assembly plan. NO new schemas.py types in v1 — direction output lives in
`Breakdown.judgment["direct"]` (per-section-replace rules apply) and
renders to `direction.md`. S1/S2 discipline verbatim.

## The loop being built

1. Study the raw recording (A-Q12 raw-mode: dead-air, fillers, repeated
   takes — already in flight).
2. The judging AI reads: raw breakdown + a StyleProfile + the genre
   rubric, guided by `prompts/direct.md`.
3. Output (the contract, enforced by prompt + format checks, not schema):
   `judgment["direct"]` = { verdict, gaps: [{criterion_id, profile_evidence,
   footage_evidence, severity}], shot_prompts: [{n, instruction (plain
   language, filmable, ≤2 sentences), closes_gap, duration_hint}],
   keepers: [{start, end, why}], assembly_notes }.
4. `direction.md` renders it for a creator: what works, what's missing
   (cited), exactly what to film, in that order. PLAIN LANGUAGE is a
   hard rule — jargon fails review.

## Lanes

**Lane A:** finish A-Q12 raw-mode; add `keepers` support evidence — the
measured segments most likely usable (clean audio, no filler, inside a
take) surfaced as derived data the AI can cite. Gate: raw-mode breakdown
of a real unedited recording flags its dead air/fillers/takes accurately
on manual check.

**Lane B:** `prompts/direct.md` v1 (profile+rubric-grounded, honest
degradation: no profile → rubric-only mode with a stated caveat; visual
gaps need keyframes via get_frames); `direction.md` renderer;
`save_judgment` section validation for "direct"; MCP flow doc (study raw →
build/get profile → judge → direction.md). Gate: end-to-end direction of
the gate-pack raw clip against the gate-test profile reads as genuinely
filmable direction.

**Lane C:** C-Q15 raw-footage goldens (in flight) + direction FORMAT
conformance checks (the judgment["direct"] shape above — machine-checkable
parts only: required keys, criterion_id validity vs INDEX.md, shot_prompt
plain-language heuristics like sentence length/jargon-list); eval report
extension. Gate: conformance catches each mutated direction output.

**Lane D:** plain-language review of direction.md outputs (creator's eye);
jargon list maintenance for C's checks.

## Sprint gate (Ryan + orchestrator)

Ryan's real raw footage (2-3 min talking head) through the full loop
against a profile built from HIS picks: does the gap report tell him
something true he didn't articulate, and would he actually film the shot
prompts? That's the product promise, tested on its first real user.
