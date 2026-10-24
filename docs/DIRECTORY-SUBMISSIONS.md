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
| Website | https://myzing.app |
| Short description | Pre-alpha video study, captioned draft editing and memes for AI agents. Runs locally over stdio. |
| Tags | video, editing, captions, memes, creative-tools, local-first, python, stdio |
| Install line | From the source checkout: `uv sync --extra mcp`, then `uv run --frozen zing serve-mcp`. |
| Install guide | https://github.com/ryanbiddy/zing/blob/main/llms-install.md |
| Transport | Local stdio |
| License | MIT for Zing code and docs; bundled assets retain their own notices. |

Long description:

> Zing gives AI agents local tools to study reference videos, save editing
> judgments, build style profiles, plan edits, render captioned drafts and make
> memes. It runs as a Python CLI or an MCP server over stdio. Video work needs
> FFmpeg and feature extras; prompts, saved records and meme text tools work
> without FFmpeg. Zing works with Uoink, using a local Uoink library as references
> and reusing verified retained media when available. Uoink is optional.
> Zing is pre-alpha and currently installs from source. Style matches are
> approximations that need review, and drafts are not automatically published.

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
will be `uvx --from "myzing[mcp]==1.0.0rc1" zing serve-mcp`. That command does not
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

Use the shared text and repository URL. The Dockerfile path is
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

## Cursor Directory

Status: **NOT SUBMITTED**

Destination: https://cursor.directory

Use the shared name, repository, website, tags and descriptions. Link the source
install guide. The client command is the installed `zing` executable with
`serve-mcp`; use its absolute path or the interpreter config printed by
`zing serve-mcp --print-config`.

## LobeHub

Status: **NOT SUBMITTED**

Destination: https://lobehub.com/mcp

Repository: `https://github.com/ryanbiddy/zing`. Use the shared copy and install
guide. Label the server pre-alpha, local and stdio; media capabilities require
the dependencies listed in the guide.

## MCP Market

Status: **NOT SUBMITTED**

Destination: https://mcpmarket.com/submit

Use the repository URL and shared copy. An owner must supply any contact email
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
> Zing lets Cline study reference videos, plan and render local edits, and make
> memes through a stdio MCP server. It is pre-alpha and installs from source
> with `uv sync --extra mcp`; start it with `uv run --frozen zing serve-mcp`.
> Video work also needs FFmpeg and feature extras. Uoink can supply saved local
> references but is optional. See the install guide for the tools that work
> without FFmpeg and for download boundaries.

An approved square PNG logo and any screenshots required by the current issue
template remain to be supplied. Do not claim this kit includes those assets.

## awesome-mcp-servers

Status: **NOT SUBMITTED**

Destination: https://github.com/punkpeye/awesome-mcp-servers

Proposed entry:

```markdown
- [ryanbiddy/zing](https://github.com/ryanbiddy/zing) - Pre-alpha local video study, captioned draft editing and memes for AI agents. Python, stdio, source install; video work needs FFmpeg. Optional Uoink reference library integration.
```

Check the repository's current contribution rules and category before preparing
a PR. If a Glama listing or badge is required, wait for an actual accepted
listing; this kit contains no claimed score or badge.
