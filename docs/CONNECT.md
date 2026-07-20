# Connecting your AI to Zing

Zing's MCP server gives any MCP client nineteen tools, plus the prompt
pack as slash commands:

- **Study:** `study_video`, `study_uoink_item`, `get_breakdown`,
  `list_breakdowns`, `get_frames`, `zing_status`
- **Judge:** `get_prompt`, `save_judgment`, `setup_taste`
- **Profile:** `build_profile`, `get_profile`, `list_profiles`,
  `list_presets`
- **Render:** `render_edl`, `get_render`, `export_otio`,
  `generate_thumbnails`
- **Suite:** `push_to_uoink`, `import_shot_list`

(This list is pinned by a test against the server's own tool registry —
if it drifts, CI fails.)

**One command prints your exact config with real paths — start there:**

```
zing serve-mcp --print-config
```

Prerequisites — install Zing from source (PyPI publication happens at
launch; until then `pip install myzing` finds nothing):

```
git clone https://github.com/ryanbiddy/zing && cd zing
python -m pip install -e ".[mcp]"
```

(At launch this becomes `python -m pip install "myzing[mcp]"`.) Then run
`zing doctor` once — `study_video` refuses to start without ffmpeg and
says why.

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
serve-mcp` and speak MCP over stdin/stdout. Gemini CLI serves Zing's
prompt pack as slash commands (same as Claude clients). Clients without
the prompts capability (e.g. Codex CLI, which speaks tools and server
instructions only) can fetch any judgment prompt through the
`get_prompt` tool instead — same content, one extra call.

## Suite integration (uoink + Writer) — all optional

Zing is fully standalone; these light up only when the sibling products
are present (INTEGRATION-CONTRACT v1):

- **Study a captured short without re-downloading:**
  `study_uoink_item("uoink://item/<id>")` asks uoink for the kept media
  file, verifies its hash, and studies it with **zero network fetch**;
  if that file is missing or fails integrity checks, Zing may refetch
  only from the handoff's HTTP(S) source URL. A missing source URL or a
  failed refetch leaves the study failed rather than guessing. The
  breakdown records whether it used kept media or refetched, with the
  reason. `UOINK_URL` defaults to `http://127.0.0.1:5179`.
- **Supply the Uoink credential explicitly:** set `UOINK_TOKEN` in the
  environment that launches Zing's MCP server. For an installed Uoink
  helper, the value is stored at
  `%LOCALAPPDATA%\Uoink\token.txt` on Windows or
  `~/Library/Application Support/Uoink/token.txt` on macOS; a source
  checkout keeps `token.txt` beside `server.py`. Copy the value into the
  process environment. Zing never reads Uoink's token file and never puts
  the token in a URL.
- **Import a Writer shot list:** `import_shot_list(path, slug)` takes
  the `.md` file you exported from Writer and attaches it to a studied
  breakdown as editorial context. Re-importing the same file is
  idempotent. Zing's own measured direction stays the authority for
  what's actually usable footage.
- **Peer health, honestly:** `zing doctor` probes uoink through the
  suite contract. No service at the default address is calm `absent`;
  a verified service without `UOINK_TOKEN` is calm `unconfigured`; a
  configured service that rejects authentication, serves the wrong
  contract, or fails health is `unhealthy` with a named code. The human
  doctor row abbreviates `unconfigured` as `unconfig`, while its peer data
  keeps the contract state. A missing Uoink does not fail Zing's
  standalone local-file study, profile, or render paths.

## Environment knobs (all optional)

| Variable | Effect |
|---|---|
| `ZING_HOME` | workspace location (default `~/.zing`) |
| `ZING_PROMPTS_DIR` | prompt pack location (default: the install's `prompts/`) |
| `UOINK_URL` / `UOINK_TOKEN` | uoink address + credential for `push_to_uoink`, `study_uoink_item`, and doctor's peer probe |

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

**What is verified** (2026-07-18, this machine, then a 12-tool
surface): the staged bundle tree is complete and CI-tested; `mcpb pack`
produces the bundle; the manifest's exact launch command (`uv run
--directory <bundle> --extra mcp python -m myzing.cli serve-mcp`) boots
the server cold from the staged tree — initialize handshake, every tool
listed, all four prompt-pack prompts (study, compare, direct, taste)
served via the `${__dirname}/prompts`
pin. The served tool list follows the package (CI pins it), so bundles
built today serve all nineteen. **What still needs a
human:** the Claude Desktop double-click dialog itself (GUI). If it
fails, the fallback is the manual config above — same server, same
behavior. Requires a Claude Desktop recent enough to support uv-type
bundles; older versions should use the manual config.
