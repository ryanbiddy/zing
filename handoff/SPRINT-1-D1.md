# Zing Sprint 1 — D-1: the Study engine, measured and gated

Orchestrator: Claude (Ryan's chat session). Workers: two Claude Fable 5
terminals (Lanes A, B) + one Codex GPT-5.6 Sol session (Lane C).
Vision: `E:\AI\projects\uoink\handoff\VIDEO-DIRECTOR-VISION-2026-07-17.md`.
Lifecycle + sprint sequence: `handoff/ROADMAP.md`. Worker standing prompts:
`handoff/prompts/LANE-{A,B,C}.md` (Phase-0 plan critique lands BEFORE build).
Priority: WORKING > pretty. No brand/design/copy work this sprint.

## Rules for every lane

- **Never edit `src/myzing/schemas.py`.** It is the interface contract. If it
  blocks you, write the problem to `handoff/NOTES-<lane>.md`, commit, and move
  to other work in your lane; the orchestrator changes contracts.
- Own your lane's paths (below). Do not touch another lane's paths.
- Branch from `main` in YOUR worktree only. PR flow:
  `gh pr create` → `gh pr ready` → `gh pr merge --auto --squash --delete-branch`.
  CI (pytest) is the merge gate. `gh` lives at
  `C:\Program Files\GitHub CLI\gh.exe` (not on PATH).
- Tests must pass OFFLINE: no network in CI. Mock subprocess calls or use
  synthetic local fixtures.
- New dependencies: MIT/BSD/Apache only, added to `pyproject.toml` with a
  one-line license note in the PR body. When a binary tool is needed
  (ffmpeg, tesseract), detect it honestly in `zing doctor` — never assume.
- Small PRs, merged often, each leaving `main` green. Rebase on main before
  ready.
- **Shared-file discipline:** `src/myzing/cli.py` is a dispatch registry —
  implement `run(argv) -> int` in YOUR lane's module instead of editing it.
  `pyproject.toml` dependency additions: one dep per tiny PR, merged
  immediately, everyone rebases after.
- When your gate passes, write a short completion note in
  `handoff/NOTES-<lane>.md` (what shipped, what's honest-missing) and STOP —
  the orchestrator assigns the next item.

## Lane A — Study engine (Claude Fable 5, high effort)

Owns: `src/myzing/study/**`, `tests/test_study*`, fixtures it needs.
Deliver `zing study <url|file>` producing a real `Breakdown`:

1. Media in: local file directly; URL via yt-dlp (keep the file). Store under
   the workspace dir (Lane B owns storage layout — until it lands, use
   `./zing-workspace/` and read the path from one helper so it can be swapped).
2. Shot detection → `Shot[]`: ffmpeg scdet or PySceneDetect (pick one,
   justify in PR).
3. Transcription → `Word[]`: faster-whisper word timestamps. Honest skip
   (empty list + warning) when the model isn't available; doctor reports it.
4. Caption OCR → `CaptionEvent[]`: sample frames (~4/s), OCR, cluster into
   timed events with position/case/words-visible observations. OCR choice:
   **RapidOCR recommended** (Apache, pip-only ONNX — better Windows story
   and stylized-text results per `handoff/research/PRIOR-ART-OSS.md`);
   tesseract acceptable fallback. **TIMEBOX: best-effort with
   honest confidence values is the S1 bar** — stylized/animated captions
   will fool OCR; do not chase accuracy past ~1 day, iterate in S2 against
   real data.
5. Audio → `AudioLayout`: speech ratio (whisper segments or VAD), loudness
   curve via ffmpeg (1 sample/sec), `has_music` as an honest heuristic.
6. Derived: `avg_shot_duration`, `cuts_per_10s` windows.
7. `breakdown.md` renderer: human-readable edit breakdown — shot table,
   pacing summary, first-3-seconds facts (shots + words + captions in 0–3s).

**Gate:** on 3 real short videos (run locally, not CI) the JSON + markdown
survive a manual spot-check; CI tests cover each measurement with mocked
subprocess / synthetic fixtures; `Breakdown.from_json(b.to_json())` is
lossless on real output.

## Lane B — Surface: doctor, MCP server, storage, uoink bridge (Claude Fable 5, medium effort)

Owns: `src/myzing/{doctor,mcp_server,storage}*.py`, `prompts/**`,
`tests/test_doctor*`, `tests/test_mcp*`.

1. `zing doctor`: detect ffmpeg, yt-dlp, faster-whisper model, OCR backend;
   actionable per-item messages; exit nonzero when core tools missing.
2. Storage: workspace layout `~/.zing/` (overridable via env)
   `breakdowns/<slug>/{breakdown.json, breakdown.md, media.*}` + a tiny
   index function Lane A can call. Land this FIRST so Lane A can adopt it.
3. MCP stdio server (`zing serve-mcp`): tools `study_video(url_or_path)`,
   `get_breakdown(slug)`, `list_breakdowns()`, `save_judgment(slug, judgment)`
   (merges into `Breakdown.judgment`), `zing_status()`. Until Lane A merges,
   call the stub and return honest not-implemented; wire up after.
4. Prompt pack v0: `prompts/study.md` — how the user's AI should read a
   Breakdown and judge hook type, structure beats, caption style, and what
   makes it work (judgment written back via `save_judgment`).
   `prompts/direct.md` — stub with the D-3 shape (gap report + shot prompts).
5. Uoink bridge (optional, last): if the uoink helper answers on localhost,
   offer pushing `breakdown.md` back as a note; silently absent otherwise.

**Gate:** CI smoke test drives the MCP server over stdio:
initialize → tools/list → tools/call zing_status (uoink's C-01 pattern);
doctor output honest on a machine missing everything.

## Lane C — Eval harness, then renderer (Codex GPT-5.6 Sol, MAX reasoning)

Owns: `tools/eval/**`, `src/myzing/render/**`, `tests/test_render*`,
`tests/test_eval*`.

**C-1 (first): the anti-slop gate.** Synthetic golden fixtures + scorer:
1. `tools/eval/make_goldens.py`: generate 3 tiny videos with ffmpeg where
   truth is EXACT by construction — colored segments with known cut times,
   drawtext captions with known text/timing, tone/silence audio patterns.
   Emit `goldens/<case>/truth.json` alongside.
2. `tools/eval/run.py`: run Lane A's study pipeline on each golden, score
   Breakdown vs truth with explicit tolerances (cut count exact, cut times
   ±0.15s, caption text fuzzy ≥0.8, speech ratio ±0.1), print a pass/fail
   table, exit nonzero on regression. Until Lane A merges, score a checked-in
   sample Breakdown so the scorer itself is proven.
3. CI job runs the scorer when ffmpeg is present (install it in CI).

**C-2 (after C-1 gate):** `zing render <edl.json>` executing an `EDL`
exactly: trim + concat clips, scale/pad to spec, burn word-timed captions
(generate .ass from `CaptionSpec.words` — use **pysubs2** (MIT, active) for
.ass generation incl. karaoke tags rather than hand-rolling the format; see
`handoff/research/PRIOR-ART-OSS.md`), mix voiceover + music with ducking,
fail loudly on malformed EDL (missing file, overlapping clips, words
outside caption window).

**Gate C-1:** scorer catches a deliberately-broken Breakdown (mutation test).
**Gate C-2:** golden EDL renders; ffprobe asserts duration/resolution/streams;
a caption-timing probe frame contains the expected text.

## Critique resolutions — BINDING (orchestrator, 2026-07-18, from Phase-0 round)

All three critiques were high quality; nearly everything is accepted. The
contract changes are already in `schemas.py` (warnings, provenance,
Shot.keyframe, Word.confidence, music_confidence, pinned measurement
definitions, EDL S1 timeline/audio semantics, media_path relative-to-
breakdown rule). Additional binding decisions by lane:

**Lane A:** the programmatic seam is `myzing/study/api.py:
study(source: str, workspace: Path | None = None) -> Breakdown`; CLI is a
thin wrapper (A#4). VFR policy accepted as proposed: PTS-derived timestamps,
CFR-normalize on ingest, prefer avc1 mp4 (A#5). Extract keyframes per shot +
~1fps over 0–3s into the breakdown dir (A#2). OCR sampling ~8–10fps in the
0–3s hook window, ~4fps elsewhere, sampling rate recorded in
warnings/report (A#9). Heavy deps imported lazily inside functions (B#7).

**Lane B:** prompt delivery = MCP prompts capability + `get_prompt` tool
fallback + `zing prompt <name>` CLI (B#1). `study_video` — RULING REVISED
2026-07-18 on R1-B evidence (Claude Desktop's hardcoded ~60s MCP request
timeout; progress does not extend it): **job pattern IN S1**. study_video
validates cheaply (bad input / missing required tools → immediate honest
error), else starts a worker thread and returns `{ok, slug,
status:"started"}` in <1s; `zing_status()` reports per-slug job phase;
`get_breakdown(slug)` answers honestly while studying and returns the
breakdown when done; a status file in the slug dir keeps crash states
honest. The CLI `zing study` stays synchronous (same `study/api.py`
pipeline, two surfaces) (B#2, revised).
`save_judgment(slug, judgment, section="study")` = per-section REPLACE with
`_meta` stamp; prompt pack carries a version header and defines the
judgment JSON shape (B#3). Storage owns `slug_for()`; re-study overwrites
measurements but PRESERVES judgment (+ one .bak) (B#4). Doctor tiers:
required (ffmpeg) / recommended (yt-dlp, whisper, OCR — named degraded
modes) / optional (uoink); exit nonzero only on required; `--json`; MCP
`zing_status()` built on the same checks; include yt-dlp staleness check
(B#5, A-minor). Install weight: core = stdlib-only; extras `[study]` and
`[render]` (pysubs2) plus `[all]`; doctor prints the exact install command
(B#7). MCP server: port uoink's proven stdio skeleton, else official MIT
SDK — zero novel protocol code (B#8). Ship `tests/conftest.py` with the
shared `zing_workspace` fixture in the storage PR (B#10).
`prompts/study.md` v0 must degrade honestly on visual hooks ("cannot
classify from measurements") — the eval scores that honesty; named S2
fast-follow: `get_frames(slug, timestamps[])` returning MCP image content
(B#6).

**Lane C:** EDL semantics now pinned in schemas.py — build to them (C#1).
Split audio oracle: tones/silence score loudness-window timing + silence
detection; speech_ratio scored only against a real spoken fixture with
documented redistribution terms — until then mark speech-ratio scoring
unavailable, never tone-as-speech (C#2). Scoring rules live in a versioned
eval manifest: one-to-one chronological cut matching with
missing/extra/out-of-tolerance reported separately; captions matched by
temporal overlap then similarity; explicit Unicode/whitespace/case/punct
normalization; recall AND per-event similarity; extras penalized; raw
deltas beside every pass/fail; tolerances never inside truth files (C#3).
Eval adapter: media path → Breakdown; scorer stays pure
`score(truth, breakdown)` (C#4). Mutation gate = fault matrix, ≥1 targeted
mutation per scored dimension, asserting the intended metric fails and
others stay green (C#5). ffmpeg: argv lists never shell,
filter_complex_script files for path-hostile graphs, normalize every leg
before concat, fixtures with spaces/apostrophes in paths (C#6). Renderer
oracle = content probes (solid-color pixel checks, RMS windows for
timing/gain/ducking, generated-ASS inspection + caption-region frame
deltas) — no OCR in renderer tests (C#7). CI: ffmpeg explicitly installed +
version/filters printed, scorer + render golden on Ubuntu, focused Windows
job for paths/ASS/render smoke (C#8; the pytest Windows matrix job is
already added by the orchestrator). Every eval run emits a machine-readable
report (scorer version, fixture hashes, ffmpeg version, per-event deltas,
wall-clock) kept as CI artifact on failure (C#9). Eval golden segments
≥0.8s (A#3).

Real-video regression discipline (C deeper-thread, accepted): when the
3-real-videos gate runs, freeze those annotations + provenance so they
become a regression set, not a one-time demo.

## Sprint-1 exit gate (orchestrator + Ryan): the wizard-of-oz test

Before S1 closes, the riskiest assumption gets tested by hand: take ONE real
reference video Ryan admires + Ryan's raw footage, run `zing study` on both,
have an AI (Claude, using `prompts/study.md`) produce the judgment, style
read, gap report, and shot prompts manually. If the direction output is not
genuinely useful, S2 priorities change — better to learn that now than in S3.
Ryan's S1 tasks: record 2–3 min of raw talking-head footage; pick 5–10
admired shorts (uoink them) as the real reference set.

## Status

- [x] Lane A — study engine (gate passed #37; A-Q2 eval iteration continuing; A-Q4 X/long-form + A-Q5 phase_callback delivered)
- [x] Lane B — doctor/storage/MCP/prompt pack (gate passed #31; real-engine e2e verified #35)
- [x] Lane C-1 — eval harness (#24, Ubuntu+Windows CI green)
- [x] Lane C-2 — renderer (#39, content-probe oracle green) · C-Q3 perf harness (#42)
- [ ] S1 REVIEW ROUND (open as of 2026-07-18): each lane reviews the OTHER lanes → handoff/reviews/S1-REVIEW-<lane>.md → orchestrator fixlist → fix sprint
- [ ] Wizard-of-oz exit gate (orchestrator + Ryan — the last S1 box)
- Orchestrator log lives in `handoff/ORCHESTRATOR-LOG.md`.
