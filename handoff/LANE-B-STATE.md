# Lane B state of the world — 2026-07-19, at the Decision Week freeze

One page for whoever picks this lane up next (post-decision sprint, or
a fresh context). Chronology lives in NOTES-lane-b.md; this is the
STATE. Written at main `d6976e1`, suite 916 passed / 2 skipped (both
skips are documented gates: isolated kokoro Python gate, optional OTIO
runtime).

## Surfaces owned and their condition

| Surface | Condition |
|---|---|
| MCP server (19 tools, 4 prompts) | serverInfo reports myzing's version; stdio smoke green; tool list + prompt count CI-pinned to CONNECT.md |
| doctor | tiered checks, evidence-carrying verdicts; yt-dlp resolver shared with ingest (D-11); node-config detection (D-13); §8 contract peer probe with 60s cadence cache |
| suite_peer (§8 probe) | ryan.suite.peer v1 envelopes + evidence receipts; fixture parity with Lane C validators both directions; 95% covered |
| uoink_bridge (push + §6.1 resolver) | exact-key handoff validation, FF-8 source_url rule; 100% covered |
| shot_list (§6.2 import) | exact wire validation, content-addressed idempotent persistence, path-free receipts; 100% covered |
| setup/onboarding, prompt pack, storage | stable since S5; drift gates on packaged data mirrors |
| .mcpb bundle | manifest_version 0.3 (spec-current, pinned); uv-type; cross-client |
| CLI | registry-rendered help; UTF-8 on redirect; user-facing errors |

## Standing invariants (test-enforced, do not quietly relax)

- Doctor never says "fully ready" over a failing promised capability
  (audit #201 lineage; consumer-boundary regressions carry the audit id).
- Peer drift is never flattened into absence; unhealthy names its code;
  verdicts carry probe-evidence receipts (final review P2-5).
- Kept-media/shot-list surfaces validate exact-key envelopes; drift is
  a named state ("version drift, not absence").
- CONNECT.md's tool count/list and prompt count are CI-pinned; the
  DEVELOPER-GUIDE doctor checklist is pinned to run_checks().
- source_url at the bridge boundary: null-or-HTTP(S), nothing else.

## Shelf: gated proposals (QUEUE §PROPOSED, each with refutation)

| Proposal | Trigger |
|---|---|
| Official MCP registry publication (+ `uv tool install`) | RYAN-GATED, post-naming, launch checklist |
| Corpus-seeded onboarding (setup from uoink library) | post-Decision-Week; FIRST ask uoink: does corpus.read expose keep_media per item? |
| Drift-direction messages | first contract-v2 bump (tripwire, zero code until then) |
| Unmocked-seam rule for SG-2 (process) | orchestrator disposition; Lane A endorsed with sharpened evidence |

## Watch-items (explicit triggers, no action before them)

- `scenedetect-core` new distribution: act only on a STABLE release
  (one-line extras rename) — research/SG4-STACK-CURRENCY-2026-07-19.md.
- D-9 tail (PO-token provider detection in doctor) — still proposed,
  never queued; revisit if YouTube fetch pain returns post-launch.
- Installed uoink predates suite routes (review P1-1): doctor shows
  honest [unhealthy] until uoink's rebuilt installer ships. Not zing's.

## Working rules this lane bled for (short list)

- Paste the number, never predict it; count catches like test results.
- No Windows-path literals through any heredoc; patch scripts live in
  the scratchpad and assert-and-parse BEFORE writing the target.
- Local runs: PYTHONPATH pinned to THIS worktree's src (the shared
  venv's editable install points wherever it was last installed).
- Coverage data via COVERAGE_FILE to the scratchpad; check git status
  before staging.
- A surface enumerated twice is one drift bug from now: generate or
  pin, never hand-copy.
- An API-compatibility claim requires one unmocked pass through the
  seam; CI-green is not deprecation-clean.
