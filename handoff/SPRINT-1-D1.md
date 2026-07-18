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
   timed events with position/case/words-visible observations. License-clean
   OCR choice (tesseract binary or rapidocr).
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
(generate .ass from `CaptionSpec.words`), mix voiceover + music with
ducking, fail loudly on malformed EDL (missing file, overlapping clips,
words outside caption window).

**Gate C-1:** scorer catches a deliberately-broken Breakdown (mutation test).
**Gate C-2:** golden EDL renders; ffprobe asserts duration/resolution/streams;
a caption-timing probe frame contains the expected text.

## Status

- [ ] Lane A — study engine
- [ ] Lane B — doctor/storage/MCP/prompt pack
- [ ] Lane C-1 — eval harness
- [ ] Lane C-2 — renderer
- Orchestrator log lives in `handoff/ORCHESTRATOR-LOG.md`.
