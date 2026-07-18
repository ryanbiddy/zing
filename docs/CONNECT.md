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

## One-click bundle (.mcpb)

Build it (needs Node for the pack step; network on first run):

```
python packaging/build_mcpb.py        # -> dist/myzing.mcpb
```

Then double-click `myzing.mcpb` (or drag it into Claude Desktop →
Settings → Extensions). The bundle is `server.type: "uv"`: Claude
Desktop's runtime resolves Python + dependencies from the bundled
`pyproject.toml` at install time, so nothing compiled is packed and one
bundle serves Windows/macOS/Linux. The install dialog offers one
optional setting — the Zing workspace directory (default `~/.zing`).

**What is verified** (2026-07-18, this machine): the staged bundle tree
is complete and CI-tested; `mcpb pack` produces the bundle; the
manifest's exact launch command (`uv run --directory <bundle> --extra
mcp python -m myzing.cli serve-mcp`) boots the server cold from the
staged tree — initialize handshake, all 9 tools listed, both prompt-pack
prompts served via the `${__dirname}/prompts` pin. **What still needs a
human:** the Claude Desktop double-click dialog itself (GUI). If it
fails, the fallback is the manual config above — same server, same
behavior. Requires a Claude Desktop recent enough to support uv-type
bundles; older versions should use the manual config.
