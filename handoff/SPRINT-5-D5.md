# Zing Sprint 5 — Hardening (LAUNCH-PLAN step 4)

Opened 2026-07-19 on S4's green rerun. Purpose: kill "works on my
machine." Everything internal, evidence-first, same discipline.

## Lanes

**Lane B — fresh-host installs.** Scripted clean-host verification:
brand-new venv + `pip install` from a built wheel (build it), on Windows
locally AND via a CI clean-install job on windows/macos/ubuntu runners
(no repo checkout in the test path — install the wheel, run `zing
doctor`, `zing setup`, a cached-media `zing study`). Every rough edge in
first-run output is a defect. Deliverable: install gate records per OS.

**Lane A — real-video sweep.** The matrix: {tiktok, instagram, youtube,
x} × {short, long} × {vertical, horizontal} where combinations exist —
study each, verify measurement sanity vs spot-checks, file per-cell
results. Use cached media where bot-gating blocks (flag honestly which
cells ran live vs cached; retry fetch-blocked cells at least twice at
different times). Includes closing CD-Q1 (genuinely-raw clip refreeze
with Lane C/D) and the S4 leftovers D-10 (trim-edge caption words) fix.

**Lane C — perf + failure honesty.** Perf harness runs across the sweep
matrix vs the ROADMAP budget (tracked→now gated: flag cells >2x budget as
defects); failure-honesty sweep — kill switches mid-study, missing
binaries, corrupt media, full disk (simulated), every failure must name
itself actionably; O-2 cleanup fix; VO gate half: install the Kokoro
model locally, render real VO, extend probes to it (the honest-skip debt
comes due here).

**Lane D — docs truth pass.** Every user-facing doc (README, CONNECT,
developer guide, prompts) checked against actual current behavior;
stale claims are defects.

## Gate

All lanes' records green + a full end-to-end on a NEVER-BEFORE-SEEN
video (Lane A picks fresh, live-verified): setup → study → profile →
direct → render → export, each stage's honesty checks intact, wall-clock
within budget. Then S6 integration opens.
