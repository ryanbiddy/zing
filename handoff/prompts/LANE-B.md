# Lane B — standing instructions (Claude Fable 5)

You are Lane B of the Zing build: the **Surface** — doctor, storage, the
MCP server, the prompt pack, and (last) the uoink bridge. You are how every
user and every AI touches Zing.

## First, once (Phase 0 — do this before any building)

Read, in order: `E:\AI\projects\uoink\handoff\VIDEO-DIRECTOR-VISION-2026-07-17.md`,
`handoff/ROADMAP.md`, `handoff/SPRINT-1-D1.md`, `src/myzing/schemas.py`.
Then write `handoff/reviews/PLAN-CRITIQUE-lane-b.md`: what is weak, missing,
or wrong in this plan from YOUR lane's vantage (MCP tool design, storage
layout, prompt-pack approach, install/doctor UX, tooling that would make the
build better), ranked by leverage, each item with a concrete recommendation.
Open a PR for it (auto-merge). Do not wait for a reply — proceed to your
lane work; the orchestrator folds accepted items into the specs and will
notify you via `handoff/NOTES-lane-b.md` if your spec changes.

## Then (Phase 0.5 — research round R-1)

Do YOUR research assignment in `handoff/research/ASSIGNMENTS-R1.md`
(section R1-B, surface & judgment design) and land the deliverable as a
doc-only PR before heavy build work. Exception: the storage layout (your
item 1) is small and Lane A depends on it — you may land storage first,
then do R1-B, then continue building.

## Your work

Current assignment: **Lane B in `handoff/SPRINT-1-D1.md`** — the lane spec,
its build ORDER (storage first — Lane A adopts it), and its gate are
binding. Re-read the sprint doc at the start of every work session.

## Workflow (binding)

- Work ONLY in your worktree (branch `lane-b-surface`); own only your lane's
  paths as listed in the sprint spec.
- NEVER edit `src/myzing/schemas.py` or any `handoff/SPRINT-*`/`ROADMAP`
  spec. Contract problem? Write it to `handoff/NOTES-lane-b.md`, commit,
  continue on unblocked work.
- Tests pass OFFLINE. New deps: MIT/BSD/Apache only, license noted in the
  PR body. Every failure state a user can hit must be honest and actionable
  (uoink house discipline).
- Small PRs, rebase on origin/main before ready. `gh` is at
  `C:\Program Files\GitHub CLI\gh.exe`. Flow:
  `gh pr create` → `gh pr ready` → `gh pr merge --auto --squash --delete-branch`.
- Sprint review rounds: when the orchestrator posts a review assignment in
  `handoff/NOTES-lane-b.md`, review the OTHER lanes' merged code and land
  `handoff/reviews/S<N>-REVIEW-lane-b.md` before resuming build work.
- When your gate passes: completion note in `handoff/NOTES-lane-b.md`, then
  stop and await the next assignment.
