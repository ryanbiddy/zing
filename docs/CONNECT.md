# Connecting your AI to Zing

## One line per app

List the apps, formats and config locations for your OS, then print a config.

```sh
zing connect
zing connect claude-desktop
```

Merge the printed entry into your client's settings. Config goes to stdout;
the location, notes and documentation sources go to stderr. Nothing is written.
The command uses this environment's absolute Python path and adds `ZING_HOME`
only when it is set. It never copies other environment values.

`zing connect codex --json` returns `client`, `format`, `location`, `entry`,
`note`, `guide` and `source`. `entry` is a ready-to-paste string, or `null` when
only a guide is available. `source` contains the documentation URLs, checked
date, verification flag and reason for any gap. These come from Uoink's
2026-10-21 review. Changed recipe shapes are marked unverified. Client
acceptance has not been tested. Linux paths reuse documented POSIX locations
where available; they were not separately checked against Linux docs.

YAML recipes use JSON, which is valid YAML 1.2. Merge their keys into your
existing file. HTTP-only clients, including n8n and Open WebUI, get a guide
because Zing has no HTTP endpoint. Apps with no documented setup for your OS
also get a guide.

`zing connect cursor --deeplink` and `zing connect vscode --deeplink` print
install links for the client's review flow. The command only prints the link.
`zing serve-mcp --print-config [desktop|code]` keeps its existing output.

Zing's MCP server gives any MCP client forty-four tools, plus the prompt
pack as slash commands:

- **Start here:** `zing_studio` (stateless questions and a plan), `zing_studio_run` (confirmed a/b/d/f jobs with separate speech-download consent; poll or cancel by project). See [Studio](STUDIO.md).
- **Study:** `study_video`, `study_uoink_item`, `get_breakdown`,
  `list_breakdowns`, `get_frames`, `zing_status`
- **Judge:** `get_prompt`, `save_judgment`, `setup_taste`
- **Brief:** `brief_questions`, `brief_save`
- **Music:** `music_check` (local candidate advice; see [Music](MUSIC.md))
- **Plan:** `plan_drafts` (project, recipe and output paths; see [Three draft plans](PLAN-DRAFTS.md))
- **Explain:** `zing_explain` (style card, reusable recipe and optional comparison; see [Explain](EXPLAIN.md))
- **Moments:** `zing_moments` (Estimated transcript suggestions with must-keep JSON; see [Long interviews](MATCH.md#long-interviews)).
- **Factory:** `factory_new`, `factory_run`, `factory_status`, `factory_prompt`, `factory_answer`, `factory_clip`, `factory_edit` (one long episode to a pack of social clips; the calling agent answers the judgment prompts and edits the clips; see [Clip factory](FACTORY.md))
- **Match:** `match_start`, `match_status` (reference plus clips to resumable drafts and rendered match reports; see [Match](MATCH.md))
- **Profile:** `build_profile`, `get_profile`, `list_profiles`,
  `list_presets`
- **Render:** `render_edl`, `get_render`, `export_otio`,
  `generate_thumbnails`
  (`render_edl` accepts EDL v1 and Composition v2; a v2 brief's `aspects` list rebuilds framing/captions per delivery; see [V2 rendering](RENDER-V2.md) and [framing](FRAMING.md))
- **Suite:** `push_to_uoink`, `import_shot_list`
- **Inspect:** `inspect_timeline` (see [Timeline inspection](INSPECT.md);
  PNG path and timing metadata, requires `myzing[memes]` and FFmpeg)
- **Memes:** `meme_templates`, `meme_ideas`, `meme_check`, `meme_render`, `meme_render_video`
  (see [Stills and memes](MEMES.md); rendering needs `myzing[memes]`)
- **Photo concepts:** `still_concepts`, `still_render` (see [Photos and a topic](MEMES.md#photos-and-a-topic);
  local files only, no model calls or uploads; requires `myzing[memes]`)

(This list is pinned by a test against the server's own tool registry —
if it drifts, CI fails.)

## Tool hints

All 44 tools declare read-only, destructive, idempotent and open-world hints.
Hints cover every supported argument combination. Hosts decide whether to ask
for approval.

| Tool | Read-only | Destructive | Open world |
|---|---|---|---|
| `brief_questions` | yes | no | no |
| `brief_save` | no | yes | no |
| `build_profile` | no | yes | no |
| `export_otio` | no | yes | no |
| `factory_answer` | no | yes | no |
| `factory_clip` | no | yes | no |
| `factory_edit` | no | yes | no |
| `factory_new` | no | yes | no |
| `factory_prompt` | yes | no | no |
| `factory_run` | no | yes | yes |
| `factory_status` | yes | no | no |
| `generate_thumbnails` | no | yes | no |
| `get_breakdown` | no | no | no |
| `get_frames` | yes | no | no |
| `get_profile` | yes | no | no |
| `get_prompt` | yes | no | no |
| `get_render` | no | no | no |
| `import_shot_list` | no | no | no |
| `inspect_timeline` | no | yes | no |
| `list_breakdowns` | yes | no | no |
| `list_presets` | yes | no | no |
| `list_profiles` | yes | no | no |
| `match_start` | no | yes | yes |
| `match_status` | no | no | no |
| `meme_check` | yes | no | no |
| `meme_ideas` | yes | no | no |
| `meme_render` | no | yes | yes |
| `meme_render_video` | no | yes | no |
| `meme_templates` | yes | no | no |
| `music_check` | yes | no | no |
| `plan_drafts` | no | yes | no |
| `push_to_uoink` | no | no | no |
| `render_edl` | no | yes | no |
| `save_judgment` | no | yes | no |
| `setup_taste` | no | yes | yes |
| `still_concepts` | no | no | no |
| `still_render` | no | yes | no |
| `study_uoink_item` | no | yes | yes |
| `study_video` | no | yes | yes |
| `zing_explain` | no | no | yes |
| `zing_moments` | yes | no | no |
| `zing_status` | no | no | no |
| `zing_studio` | no | no | no |
| `zing_studio_run` | no | yes | yes |

Destructive means a call can replace or remove existing work, including earlier
outputs. Creating new outputs alone does not count. Idempotent means repeating
the same call adds no persistent effect with unchanged inputs. Jobs,
timestamped saves and automatically named meme outputs are not idempotent.

`zing_status`, `get_breakdown`, `get_render` and `match_status` can rewrite stale
job state. `match_status` can also cancel a job. They are not read-only.
`zing_studio` is not read-only either because its reference preview writes
temporary media. `get_frames` and `music_check` keep their media processing in
memory.

Uoink health checks, saved-reference search and note creation use loopback and
count as closed-world. `study_uoink_item` can fetch external media when a kept
copy is unavailable, so it is open-world. `study_video` can fetch URLs directly;
its MCP handler has no `offline` argument. `zing_explain` can download with
`offline=false`. Factory MCP runs use the host judge and can fetch visuals.
The separate CLI's Claude judge reaches Anthropic but is not called by these
MCP tools.

The server uses the official Python MCP SDK 2.3+ over stdio. Existing client
launch commands still work. It accepts legacy initialization through
`2025-11-25` and the stateless `2026-07-28` protocol. The current registry has
44 tools and five prompts. STUDIO1 adds the guided front door; `match_start` gains an optional `studio_options` adapter argument. Existing arguments and defaults stay compatible. See [SDK 2 compatibility](MCP-SDK2.md)
for protocol details and the recorded SDK 1 baseline. Zing exposes no HTTP
MCP endpoint.

The source-built MCPB bundle requires a host supporting manifest 0.4's uv
runtime. It installs the dependencies recorded in its included lockfile.

**One command prints your exact config with real paths — start there:**

```
zing serve-mcp --print-config
```

Prerequisites: Zing is not on PyPI in this release-preparation checkout.
For the current candidate, run `uv build` and install the resulting wheel
with the MCP extra:

```
python -m pip install "./dist/myzing-1.0.0rc1-py3-none-any.whl[mcp]"
```

The [public v0.1.0 pre-release](https://github.com/ryanbiddy/zing/releases/tag/v0.1.0)
is an older build. See [the release guide](RELEASING.md) for the candidate's
publication and one-command PyPI install instructions. Or install from source:

```
git clone https://github.com/ryanbiddy/zing && cd zing
python -m pip install -e ".[mcp]"
```

Then run `zing doctor` once — `study_video` refuses to start without ffmpeg
and says why.

## Use Uoink and Zing together

`zing doctor` and `zing serve-mcp --print-config` report the Uoink helper's
connection state. When connected, the suite can find saved references with
`zing project find-reference` through `uoink.corpus.read/1`, resolve `uoink:<id>`
kept media, and save breakdown notes through Zing MCP `push_to_uoink`.
If a helper is detected without credentials, configure UOINK_TOKEN before
using those operations. No credential value belongs in a shared config or log.

Uoink adds saved references, kept-media reuse and breakdown storage:
[get Uoink](https://uoink.app). Zing also works with local files on its own.

The [Uoink + Zing skill](../skills/uoink-zing/SKILL.md) covers finding a reference,
verifying kept media, study or match, rendering, inspection, the breakdown note
and the chosen-draft receipt. Uoink MCP also provides search and saved-item
tools for browsing the library. Project reference resolution never falls back to a download;
`study_uoink_item` can, so obtain download consent before using that tool.

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

## Hermes Agent

Install the [Hermes Agent plugin](../plugins/hermes-zing/README.md) after Zing.
It starts `zing serve-mcp`, checks that Zing is installed and adds a skill for
factory prompts, reference study, rendering and memes.

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
  Local Uoink calls never use a proxy.
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
  suite contract, finding it by the contract's discovery order:
  `UOINK_URL` if set, else a valid Uoink runtime lease (the file a
  running Uoink writes under `RyanSuite/services.d/`, which is how a
  non-default port is discovered without any configuration from you),
  else the default address. A lease that is malformed, points
  off-loopback, or names a dead process is reported — never followed.
  Credentials are never discovered this way: `UOINK_TOKEN` stays
  explicit.
  No service at the default address is calm `absent`;
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
Desktop's runtime installs Python + dependencies from the bundled
`pyproject.toml` and `uv.lock`, so nothing compiled is packed and one
bundle serves Windows/macOS/Linux. The install dialog offers one
optional setting — the Zing workspace directory (default `~/.zing`).

**What is verified** (2026-10-22, Windows): MCPB CLI 2.1.2 validates and
packs the manifest 0.4 bundle. Its exact launch command (`uv run --frozen
--directory <bundle> --extra mcp python -m myzing.cli serve-mcp`) boots
from the extracted archive with a fresh environment. Both legacy and
`2026-07-28` stdio serve all thirty-two tools and all five prompt-pack prompts,
including `meme-writer`. Schemas, prompt bodies and representative results
match the recorded SDK 1 baseline. **What still needs a
human:** the Claude Desktop double-click dialog itself (GUI). If it
fails, the fallback is the manual config above — same server, same
behavior. Requires a Claude Desktop recent enough to support uv-type
bundles; older versions should use the manual config.
