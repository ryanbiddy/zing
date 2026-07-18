# Connecting your AI to Zing

Zing's MCP server gives any MCP client seven tools (`study_video`,
`get_breakdown`, `list_breakdowns`, `save_judgment`, `zing_status`,
`get_prompt`, `push_to_uoink`) plus the prompt pack as slash commands.

**One command prints your exact config with real paths — start there:**

```
zing serve-mcp --print-config
```

Prerequisites: `python -m pip install "myzing[mcp]"` (the server tells
you this and exits if the SDK is missing), and run `zing doctor` once —
`study_video` refuses to start without ffmpeg and says why.

## Claude Desktop

1. Run `zing serve-mcp --print-config desktop` and merge the JSON it
   prints into `claude_desktop_config.json`:
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
2. Fully restart Claude Desktop (tray icon → Quit, not just the window).
3. Verify: ask Claude to call `zing_status` — you should see the doctor
   summary and workspace stats.

The printed config pins the absolute path of the Python that's running
Zing, so venv installs work. If `zing` is on your PATH you can use the
shorter form instead:

```json
{
  "mcpServers": {
    "zing": { "command": "zing", "args": ["serve-mcp"] }
  }
}
```

## Claude Code

Run the one-liner that `zing serve-mcp --print-config code` prints:

```
claude mcp add zing -- "<absolute path to python>" -m myzing.cli serve-mcp
```

Verify with `/mcp` (server listed, connected) — the prompt pack appears
as `/mcp__zing__study`. `study_video` returns in under a second and
studies in the background, so no timeout tuning is needed.

## Any other MCP client

Zing is a standard stdio server: launch `<python> -m myzing.cli
serve-mcp` and speak MCP over stdin/stdout. Clients without the prompts
capability (Codex CLI, Gemini CLI) can fetch the judgment prompt through
the `get_prompt` tool instead.

## Environment knobs (all optional)

| Variable | Effect |
|---|---|
| `ZING_HOME` | workspace location (default `~/.zing`) |
| `ZING_PROMPTS_DIR` | prompt pack location (default: the install's `prompts/`) |
| `UOINK_URL` / `UOINK_TOKEN` | uoink helper address + token for `push_to_uoink` |

## When it doesn't work

- **Server never connects:** run `zing serve-mcp` in a terminal — if the
  SDK is missing it prints the exact install command and exits 2.
  Anything else it prints to stderr is the real error; stdout is
  reserved for the protocol.
- **`study_video` errors immediately:** that's it being honest — the
  message names the missing tool (usually ffmpeg) and `zing doctor`
  prints the fix.
- **A study seems stuck:** `zing_status()` reports per-slug phase from
  disk (`status.json`), and survives restarts — a crashed study shows
  `failed` with its error, never a silent hang.

## One-click bundle (.mcpb) — not yet

A `.mcpb` bundle (double-click install into Claude Desktop) is queued
for the hardening sprint: Python servers need their compiled deps
bundled per-platform (the MCP SDK's pydantic doesn't bundle portably),
so it ships when we can test it on a clean machine rather than promise
it now.
