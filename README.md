# Zing

The video director. Zing reverse-engineers the editing anatomy of short
videos you admire (cuts, pacing, hooks, captions, audio), directs your raw
footage against that style with honest gap reports and filmable shot
prompts, and renders the edit — all locally, all open source.

Zing does the deterministic measurement and rendering. The judgment (what
makes a hook work, what your cut is missing) is done by your own AI over
MCP, guided by the prompt pack in `prompts/`. No API keys, no cloud, no
bundled model.

Works standalone (`zing study <url>`), and works hand-in-hand with
[Uoink](https://github.com/ryanbiddy/uoink) — the local context layer where
your saved references live.

Status: pre-alpha, under active build. See `handoff/SPRINT-1-D1.md`.

MIT licensed. Core is stdlib-only; optional tools (ffmpeg, yt-dlp,
faster-whisper, OCR) are detected by `zing doctor`.
