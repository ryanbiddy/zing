# Zing directory submission kit

Prepared for review. Every destination below is **NOT SUBMITTED**. Zing is
pre-alpha, and `myzing` is not yet published to PyPI. These files do not publish,
register or submit anything. Recheck each directory's current requirements
before a future submission; form fields and acceptance rules are unverified.

## Text to paste

| Field | Value |
|---|---|
| Name | Zing |
| Repository | https://github.com/ryanbiddy/zing |
| Website | https://myzing.app (only once it is live; today it is a placeholder) |
| Short description | Cut your clips in the style of a video you like, with captions. Memes too. Pre-alpha; needs FFmpeg. |
| Tags | video-editing, ffmpeg, captions, memes, video-analysis, local-first, python, pre-alpha |
| Logo | The 400x400 PNG from the Charge Z brand handoff (not in this repository yet) |
| Install line | From the source checkout: `uv sync --extra mcp`, then `uv run --frozen zing serve-mcp`. |
| Install guide | https://github.com/ryanbiddy/zing/blob/main/llms-install.md |
| Transport | Local stdio |
| License | MIT for Zing code and docs; bundled assets retain their own notices. |

Long description:

> Zing studies a video you choose and cuts your clips into drafts in that style,
> with captions, in 16:9, square and 9:16, on your machine. Every style check says
> measured, estimated or unknown. It also makes memes from local photos.
> Pre-alpha; needs Python 3.10+, uv and FFmpeg.
>
> Works with Uoink: Zing can study a video you already saved in Uoink and save its
> breakdown back as a note. Uoink is optional.

Name Uoink only in long fields, as above, and always say it is optional. Never
name it in the short description, the PyPI summary, `zing --help`, titles or the
awesome-mcp-servers one-liner.

## Official MCP registry

Status: **NOT SUBMITTED**

- Registry name: `io.github.ryanbiddy/zing`
- Manifest: [server.json](../server.json)
- Schema: `2025-12-11`, matching the Uoink release reference.
- Future package: PyPI `myzing`, version taken from `pyproject.toml`.
- Required extra: `mcp`; executable: `zing`; arguments: `serve-mcp`.
- Ownership marker: `mcp-name: io.github.ryanbiddy/zing` in README.md. Setuptools
  uses that file as the PyPI long description through `project.readme`.

The package entry describes future distribution metadata. It deliberately has
no inferred `uvx myzing` launcher: the executable is named `zing`, and the MCP
dependency is optional. Clients must install the `mcp` extra and use the launch
command above. Once the matching version exists on PyPI, the explicit uv command
will be `uvx --from "myzing[mcp]==0.1.0" zing serve-mcp`. That command does not
work from PyPI today. Reconcile its version with `pyproject.toml` before release.

Run `python scripts/check_registry_server_json.py` with Python 3.11+ before
review. It checks local metadata and README markers without network access; it
does not validate the live registry schema or establish PyPI availability.
Build and inspect the distribution's long description before any future PyPI
release, then verify the published marker and package install separately.

[The registry workflow](../.github/workflows/mcp-registry.yml) accepts only
`workflow_dispatch`. It checks the checkout and requires the matching PyPI
artifact and marker before GitHub OIDC login. Its publisher version and SHA-256
come from the Uoink reference workflow. The explicit confirmation input publishes
the registry listing when run in the future. Do not run it during preparation.
It has no release, tag or push trigger and does not publish to PyPI.

## Glama

Status: **NOT SUBMITTED**

Destination: https://glama.ai/mcp/servers

Use the long description above and the repository URL. Categories: Image & Video
Processing, Multimedia Processing, Design Tools.

Glama's build page (as seen for Uoink in October 2026) is a form, not a
Dockerfile upload. It asks for a base image, Node and Python versions, a JSON
array of build steps, a start command, an environment schema and a pinned commit,
then wraps the start command in `mcp-proxy`. Translate the Dockerfile below into
those fields: the install step is the build step, and `zing serve-mcp` is the
start command. The awesome-mcp-servers entry needs the score badge this build
produces. The Dockerfile path is
[`packaging/glama/Dockerfile`](../packaging/glama/Dockerfile), with the repository
root as its build context:

```sh
docker build -f packaging/glama/Dockerfile -t zing-glama .
docker run --rm -i --network none zing-glama
```

The image installs `.[mcp]` from the checkout and runs `zing serve-mcp` as an
unprivileged user. It uses an isolated `ZING_HOME=/data/zing` and
`UOINK_URL=http://127.0.0.1:1`. Startup does not download models or contact a
service. The image has no FFmpeg, study models or still-image dependencies.
Listing the tools proves the MCP connection, not video-rendering readiness.
`--network none` enforces an offline run; it is not a Dockerfile setting.

The local fallback when Docker is unavailable is a fresh venv with only
`.[mcp]`, the same `zing serve-mcp` command, an isolated workspace, and a real
stdio `initialize` / `tools/list` exchange. Compare the returned names to
`EXPECTED_TOOLS` in [mcp_stdio_smoke.py](../packaging/mcp_stdio_smoke.py), not a
copied count. Record the actual result in the pass report. A host fallback does
not establish that the Linux image builds or passes Glama's checks.

The reusable [host smoke check](../packaging/glama/smoke.py) runs that exchange
with media binaries off PATH and a child-process network guard. For example,
from PowerShell in a checkout:

```powershell
$env:UOINK_URL = 'http://127.0.0.1:1'
uv venv zing-workspace/glama
uv pip install -p zing-workspace/glama '.[mcp]'
zing-workspace/glama/Scripts/python.exe packaging/glama/smoke.py --workspace zing-workspace/glama-proof
```

Use a new proof folder for each run. On POSIX, the venv interpreter is
`zing-workspace/glama/bin/python`. The JSON result compares tool names directly
to the canonical set. The guard permits only Python's internal Windows
socket-pair setup, while rejecting service connections and DNS lookups.

## Smithery

Status: **NOT SUBMITTED**

Destination: https://smithery.ai/new

Repository: `https://github.com/ryanbiddy/zing`. Use the shared descriptions and
source install guide. Specify local stdio and `zing serve-mcp` with the `mcp`
extra. No hosted endpoint or Smithery-specific deployment is supplied here.
Smithery announced that its hosted proxy shuts down on October 31, 2026, so
recheck what a listing there offers before submitting.

## PulseMCP

Status: **NOT SUBMITTED**

PulseMCP paused direct submissions in October 2026 and lists servers from the
official MCP registry. Publishing the registry entry is the route in.

## Cursor Directory

Status: **NOT SUBMITTED**

Destination: https://cursor.directory

Short description:

> Pre-alpha. Match your clips to a reference video and make memes, on your
> machine. Needs Python, uv and FFmpeg.

Long description:

> Zing gives your agent local tools to study a reference video, plan an edit,
> render captioned drafts in 16:9, square and 9:16, and make memes from local
> photos. Each draft comes with a report of which style checks it passed or
> failed; style matches are approximations and need your review. Pre-alpha:
> install from source with Python 3.10+, uv and FFmpeg. A local Uoink library can
> supply references, but Uoink is optional.

Use the shared name, repository, website and tags. Link the source
install guide. The client command is the installed `zing` executable with
`serve-mcp`; use its absolute path or the interpreter config printed by
`zing serve-mcp --print-config`.

## LobeHub

Status: **NOT SUBMITTED**

Destination: https://lobehub.com/mcp

Repository: `https://github.com/ryanbiddy/zing`. Short description:

> Pre-alpha. Match clips to a reference video, render captioned drafts and make
> memes locally. Needs Python and FFmpeg.

Use the shared tags and install guide. Label the server pre-alpha, local and
stdio; media capabilities require the dependencies listed in the guide. LobeHub
publishes through its market CLI from a signed-in account; the owner signs in.

## MCP Market

Status: **NOT SUBMITTED**

Destination: https://mcpmarket.com/submit

Description:

> Pre-alpha local video tools for agents: study a reference video, cut captioned
> drafts from your clips in 16:9, square and 9:16, and make memes from local
> photos. Your media stays on your machine. Needs Python, uv and FFmpeg.

Use the repository URL. An owner must supply any contact email
and choose any submission tier. No email, payment or queue selection is included
in this kit.

## Cline marketplace

Status: **NOT SUBMITTED**

Destination: https://github.com/cline/mcp-marketplace

Suggested issue title: `Add Zing: local video editing and memes over MCP`

Paste-ready body:

> Name: Zing
>
> Repository: https://github.com/ryanbiddy/zing
>
> Website: https://myzing.app
>
> Install guide: https://github.com/ryanbiddy/zing/blob/main/llms-install.md
>
> Give Cline local captioned drafts that follow a reference video, plus memes
> from local photos, each with a style check report. Pre-alpha; needs Python and
> FFmpeg.
>
> It installs from source with `uv sync --extra mcp`; start it with
> `uv run --frozen zing serve-mcp`. Video work also needs FFmpeg and feature
> extras. Uoink can supply saved local references but is optional. See the
> install guide for the tools that work without FFmpeg and for download
> boundaries.

The current issue form asks the submitter to confirm they tested Cline
installing the server from the README or `llms-install.md`. Run that test before
submitting; do not tick the box without it. Use the 400x400 logo above. Any
screenshots the form requires remain to be supplied.

## awesome-mcp-servers

Status: **NOT SUBMITTED**

Destination: https://github.com/punkpeye/awesome-mcp-servers

Category: Multimedia Process. Proposed entry:

```markdown
- [ryanbiddy/zing](https://github.com/ryanbiddy/zing) 🐍 🏠 - Pre-alpha. Study a reference video and cut your clips in that style, with captions, in 16:9, square and 9:16, on your machine. Also makes memes from local photos. Needs Python and FFmpeg.
```

Add OS emoji only for platforms tested on release day. The maintainer asked
Uoink (October 2026) for a Glama score badge right after the repository link, in
the form `[![ryanbiddy/zing MCP server](https://glama.ai/mcp/servers/ryanbiddy/zing/badges/score.svg)](https://glama.ai/mcp/servers/ryanbiddy/zing)`.
Wait for an actual Glama listing and score; this kit contains no claimed score.
