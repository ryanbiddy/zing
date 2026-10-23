# Install Zing from source with an AI agent

Zing is pre-alpha. Use the source checkout today. The Python distribution is
named `myzing`, its command is `zing`, and it has not been published to PyPI.
The repository's `server.json` describes a future PyPI release, not an install
that is available now.

Run these steps on the machine that holds the person's media. You need Git, uv
and Python 3.10 or newer. For video work, put FFmpeg and ffprobe on PATH, using
an FFmpeg build with libx264 and libass. Python extras do not install those
binaries. See [developer setup](docs/DEVELOPER-GUIDE.md).

## Install and check

Clone into a new folder, or use the person's existing Zing checkout:

```sh
git clone https://github.com/ryanbiddy/zing.git
cd zing
uv sync --extra mcp
```

This installs the MCP server and its Python dependencies. For local still images,
add `--extra memes`. For video study and editing, use `uv sync --all-extras`.
The [README extras table](README.md#optional-dependencies) explains `study`,
`render`, `audio`, `color`, `fonts` and `layout`. OpenTimelineIO and the
HyperFrames sidecar need separate installs. Installing all extras does not fetch
model weights.

Set an isolated workspace and keep Uoink disconnected for the first check.
In PowerShell:

```powershell
$env:ZING_HOME = Join-Path $PWD 'zing-workspace/agent'
$env:UOINK_URL = 'http://127.0.0.1:1'
uv run --frozen zing doctor
uv run --frozen zing serve-mcp --print-config
```

In a POSIX shell:

```sh
export ZING_HOME="$PWD/zing-workspace/agent"
export UOINK_URL=http://127.0.0.1:1
uv run --frozen zing doctor
uv run --frozen zing serve-mcp --print-config
```

`zing doctor` reports feature gaps and returns 1 if a required dependency is
missing. An MCP-only install without FFmpeg can still serve the tools below;
the doctor's video-readiness verdict is not an MCP connection test. Do not
start an uncached study just to check installation. Study can download speech
or OCR weights, even for a local video. Ask before downloading models or media.

## Connect over MCP

The server command is `zing serve-mcp`, with stdio transport. It requires the
`mcp` extra. Prefer the config printed above: it uses this environment's exact
Python interpreter with `-m myzing.cli serve-mcp`, which avoids client PATH
problems. Merge only Zing's entry into the client's existing settings, preserve
other servers, and give that entry the `ZING_HOME` and `UOINK_URL` values above.
Use the resolved absolute workspace path, not a shell expression in JSON.

If configuring a launcher directly, use the absolute path to `.venv/bin/zing`
on POSIX or `.venv/Scripts/zing.exe` on Windows, with arguments `["serve-mcp"]`.
There is no HTTP endpoint to configure. Restart the client's MCP connection,
confirm initialization and tool discovery, then call `zing_status` and
`get_prompt`. See [connection details](docs/CONNECT.md).

The canonical tool set is `EXPECTED_TOOLS` in
[the stdio smoke check](packaging/mcp_stdio_smoke.py). Tool discovery can succeed
while media features still need dependencies or saved inputs.

## What works without FFmpeg

These boundaries come from the handlers in
[mcp_server.py](src/myzing/mcp_server.py) and the modules they call:

| Tools | Conditions without FFmpeg or ffprobe |
|---|---|
| `get_prompt`, `brief_questions`, `list_presets` | Read bundled text and metadata. |
| `meme_templates`, `meme_ideas`, `meme_check` | Local catalog, text ideas and validation. No model or image download. |
| `get_breakdown`, `list_breakdowns`, `save_judgment`, `import_shot_list` | Read or update existing local records. They do not study new media. |
| `build_profile`, `get_profile`, `list_profiles` | Use saved breakdowns and judgments. |
| `brief_save` | Needs an existing project inventory; saves answers and reads its metadata. |
| `get_render`, `match_status` | Report an existing job's state. They do not create a rendered video. |
| `zing_status` | Reports missing dependencies; may probe configured Uoink health. |
| `meme_render`, `still_concepts`, `still_render` | Need `memes` (Pillow) and local images. Use `offline=true` for meme templates; keep `video=false` and `gif=false` for still export. Optional face detection can fall back to a stated heuristic. |
| `push_to_uoink` | Needs a saved breakdown and a configured local Uoink helper. This writes a note to Uoink; it is not part of installation verification. |

Do not promise full video work from an MCP-only install. `study_video`,
`study_uoink_item`, `zing_explain`, `match_start`, `render_edl`,
`generate_thumbnails`, `get_frames`, `inspect_timeline`, `music_check` and
`meme_render_video` need media binaries for their intended work. `setup_taste`
can start missing studies. `plan_drafts` reads saved studies but can also run
local framing, audio and ASR repair paths; it is not a guaranteed binary-free
operation. `export_otio` needs OpenTimelineIO and ffprobe to validate sources.

Zing works standalone with local files. It can also use a local Uoink library
as references, including verified retained media when available. Connecting
Uoink is optional and requires deliberate local configuration. Keep the
isolated endpoint above until that integration is wanted. Zing does not
automatically publish drafts.
