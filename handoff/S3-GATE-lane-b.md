# S3 Lane B gate record — direction run end to end

Date: 2026-07-19. Runner: Lane B (Claude Fable 5) as the directing AI.

## Method

Real chain, no fakes, in the seeded gate workspace: the frozen
`raw-editing-practice` breakdown directed against the `gate-refs-v2`
profile (built by Lane A's real builder) following `prompts/direct.md`
v1.0.0, saved via `save_judgment(section="direct",
model="claude-fable-5")` → contract validated (prompt_version 1.0.0
stamped) → **`direction.md` rendered** next to the breakdown in creator
order.

## What the direction found (and honestly didn't)

- **Blocking gap (O2):** speech ends at 48.3s of a 55.1s video — a 6.7s
  silent tail; the final words conclude ("it would be this") with no
  handoff. Shot prompt 1 gives the 4-second replacement ending in the
  creator's own voice.
- **Polish (O4):** the opening ("I don't go anywhere without a watch")
  and closing thought ("one watch for the rest of my life") already
  rhyme — a near-loop the silent tail breaks. Shot prompt 2 closes it
  in 2 seconds.
- **Keepers:** chosen from `words[]` with the caveat STATED — this
  frozen breakdown predates raw-mode, so the keeper machinery didn't
  run and the direction says so instead of pretending.
- The gate profile's looseness (coherence warning) was respected: gaps
  cite rubric criteria (O2/O4, T1 tier), not unfalsifiable bands.

Spot-check verdict: the two shot prompts are filmable as written by a
person holding a phone — no interpretation needed, no internal
vocabulary. The prompt's plain-language rule held under real use.

## Honest limits of this run

1. Per F-16, `raw-editing-practice` is measurably EDITED (34 shots, 49
   burned captions) — it stood in as "raw" to exercise the chain. The
   full-fidelity gate (keepers from real raw-mode measurements of a
   genuinely unedited clip) needs the re-frozen replacement with
   `raw_mode` provenance — Lane C/D dependency, flagged here.

   **CLOSED 2026-07-20** by `S3-GATE-FULL-FIDELITY-2026-07-20.md`: the
   rerun directs `raw-talking-head-korky-paul` (CC0, verified unedited,
   Lane C's C-CD1 freeze #309) with keepers grounded in real raw-mode
   evidence. PASS.
2. The gate profile remains taste-incoherent (S2 gate record) — fine
   for chain-proving, wrong for judging direction QUALITY. Ryan's real
   reference set remains the input for that.

## Gate verdict

Lane B S3 items complete: `direct.md` v1.0.0 (#127), `direction.md`
renderer wired into save_judgment (#129), section validation via the
existing frontmatter mechanism, this flow-proven run, and
`docs/DIRECT-FLOW.md`. The end-to-end output reads as genuinely
filmable direction within the stated limits.
