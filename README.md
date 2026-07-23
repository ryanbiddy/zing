# Zing

The video director. Zing reverse-engineers the editing anatomy of short
videos you admire (cuts, pacing, hooks, captions, audio), directs your raw
footage against that style with honest gap reports and filmable shot
prompts, and renders the edit — measurement and rendering run on your own
machine, all open source.

Zing does the deterministic measurement and rendering. The judgment (what
makes a hook work, what your cut is missing) is done by your own AI over
MCP, guided by the prompt pack in `prompts/`. Zing itself needs no API key
and opens no listening network service. Its external network calls are
limited to fetching a video URL you supply and, if you opt in, using
ElevenLabs for voiceover (`ELEVENLABS_API_KEY`; the default voice engine is
local). Suite-aware commands may also make loopback HTTP calls to a local
Uoink helper for peer health, retained media, corpus notes, and engagement;
Zing never puts the Uoink token in a URL. Your AI client is yours to choose,
cloud or local.

Works standalone (`zing study <url>`), and works hand-in-hand with
[Uoink](https://github.com/ryanbiddy/uoink) — the local context layer where
your saved references live.

Status: pre-alpha, under active build. See the [Developer Guide](docs/DEVELOPER-GUIDE.md), [CONNECT](docs/CONNECT.md) for AI clients, and [DIRECT-FLOW](docs/DIRECT-FLOW.md) for the direction workflow.

## Quick Start
```bash
# Setup virtual environment with dev/study dependencies
uv sync --all-extras

# Run system checks
uv run zing doctor

# Run tests
uv run pytest
```

MIT licensed. Core is stdlib-only; optional tools (ffmpeg, yt-dlp,
faster-whisper, OCR) are detected by `zing doctor`.

