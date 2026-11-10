# Zing directory submission kit

Prepared for review. Every destination below is **NOT SUBMITTED**. Zing
1.0.0rc1 is a release candidate. These files do not publish, register or submit
anything. Recheck each directory's current requirements before submission.
Form fields and acceptance rules are unverified.

Uoink is listed in most of the same places. Each Zing listing carries one
"Works with Uoink" line in its long description, and Uoink's listings point
back the same way. Uoink's own kit is `docs/submissions/README.md` in
ryanbiddy/uoink.

| Where | Status | First step |
|---|---|---|
| [Official MCP registry](#official-mcp-registry) | Ready after a package install check | Verify the pinned release install |
| [GitHub MCP Registry](#github-mcp-registry) | **Blocked** on the official registry entry | Ask in the onboarding discussion |
| [Hermes plugin catalog](#hermes-plugin-catalog) | Ready, deadline for the hackathon Tue Nov 11, 5 PM ET | Ryan opens the catalog PR |
| [Glama](#glama) | Ready | Ryan runs the build form |
| [mcp.so](#mcpso) | Ready | Web form |
| [Cline marketplace](#cline-marketplace) | Ready after a Cline install test | Issue form |
| [Cursor Directory](#cursor-directory), [LobeHub](#lobehub), [MCP Market](#mcp-market), [Smithery](#smithery) | Ready | Web forms or CLI |
| [PulseMCP](#pulsemcp) | Follows the official registry | Nothing to submit |
| [awesome-mcp-servers](#awesome-mcp-servers) | **Blocked** on a Glama score | PR after Glama |
| [Claude directory and Goose](#claude-directory-and-goose) | Ready after a package install check | Verify the pinned release install |

Not for Zing: Raycast, Homebrew, winget, Flow Launcher, Edge Add-ons, Alfred and
Obsidian. Uoink is listed there because it ships an app or extension for each.
Zing is a Python package with no app to list.

## Text to paste

| Field | Value |
|---|---|
| Name | Zing |
| Repository | https://github.com/ryanbiddy/zing |
| Website | https://myzing.app |
| Short description | Local clipping factory. Episodes become Shorts with receipts. 44 MCP tools. Release candidate. |
| Tags | video-editing, ffmpeg, captions, shorts, local-first, python, release-candidate |
| Logo | The 400x400 PNG from the Charge Z brand handoff (not in this repository yet) |
| Install line | `pipx install "myzing[all]==1.0.0rc1"` or `uv tool install "myzing[all]==1.0.0rc1"`, then `zing serve-mcp`. |
| Install guide | https://github.com/ryanbiddy/zing/blob/main/llms-install.md |
| Transport | Local stdio |
| Connect line | `zing connect <client>` prints the config for 48 agent apps. |
| License | MIT for Zing code and docs; bundled assets retain their own notices. |

Long description

> Zing turns a long episode into a pack of Shorts on your machine. Each clip has
> a receipt listing what the clip adds, with sources and licenses. A separate
> context check asks whether the cut changes the meaning. A review page brings
> the clips and checks together. Nothing is posted.
>
> Zing 1.0.0rc1 is a release candidate with 44 MCP tools. Install with
> `pipx install "myzing[all]==1.0.0rc1"` or `uv tool install "myzing[all]==1.0.0rc1"`.
> Needs Python 3.11+, FFmpeg, Node.js 20+ and Chrome or Edge. Run
> `zing factory setup` to install the Node sidecar.
>
> Works with Uoink to reuse saved media through `zing from-uoink` and save
> breakdowns as notes. Uoink is optional.

Name Uoink only in long fields, as above, and always say it is optional. Never
name it in the short description, the PyPI summary, `zing --help`, titles or the
awesome-mcp-servers one-liner.

## Official MCP registry

Status: **NOT SUBMITTED**

- Registry name: `io.github.ryanbiddy/zing`
- Manifest: [server.json](../server.json)
- Schema: `2025-12-11`, matching the Uoink release reference.
- Package: PyPI `myzing`, version taken from `pyproject.toml`.
- Required extra: `mcp`; executable: `zing`; arguments: `serve-mcp`.
- Ownership marker: `mcp-name: io.github.ryanbiddy/zing` in README.md. Setuptools
  uses that file as the PyPI long description through `project.readme`.

The package entry describes the release candidate. The executable is named
`zing`, and the MCP dependency is optional. Clients must install the `mcp`
extra or `[all]` and use the launch command above. For an MCP-only connection,
use `uvx --from "myzing[mcp]==1.0.0rc1" zing serve-mcp`. Keep its version aligned
with `pyproject.toml`.

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
install guide. Specify local stdio and `zing serve-mcp` with the `mcp`
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

Short description

> Local clipping factory. Episodes become Shorts with receipts. 44 MCP tools.
> Release candidate.

Long description

> Zing turns a long episode into a pack of Shorts locally. Each receipt lists
> what the clip adds with sources and licenses. A separate context check asks
> whether the cut changes the meaning. Review the clips and checks on a review
> page. Nothing is posted. Version 1.0.0rc1 is a release candidate with 44 MCP tools.
> Install with `pipx install "myzing[all]==1.0.0rc1"`, then run `zing factory setup`.
> Needs Python 3.11+, FFmpeg, Node.js 20+ and Chrome or Edge.
> Works with Uoink to reuse saved media. Uoink is optional.

Use the shared name, repository, website and tags. Link the
install guide. The client command is the installed `zing` executable with
`serve-mcp`; use its absolute path or the interpreter config printed by
`zing serve-mcp --print-config`.

## LobeHub

Status: **NOT SUBMITTED**

Destination: https://lobehub.com/mcp

Repository: `https://github.com/ryanbiddy/zing`.

Short description

> Local clipping factory. Episodes become Shorts with receipts. 44 MCP tools.
> Release candidate.

Long description

> Zing turns a long episode into a pack of Shorts on your machine. Each receipt
> lists what the clip adds with sources and licenses. A separate context check
> asks whether the cut changes the meaning. The review page shows the clips
> and checks. Nothing is posted. Version 1.0.0rc1 is a release candidate with
> 44 MCP tools. Install with `pipx install "myzing[all]==1.0.0rc1"`, then run
> `zing factory setup`. Needs Python 3.11+, FFmpeg, Node.js 20+ and Chrome or Edge.
> Works with Uoink to reuse saved media. Uoink is optional.

Use the shared tags and install guide. Label the server a release candidate, local and
stdio; media capabilities require the dependencies listed in the guide. LobeHub
publishes through its market CLI from a signed-in account; the owner signs in.

## MCP Market

Status: **NOT SUBMITTED**

Destination: https://mcpmarket.com/submit

Description

> Zing turns a long episode into a pack of Shorts locally. Each receipt lists
> what the clip adds with sources and licenses. A separate context check asks
> whether the cut changes the meaning. Inspect the clips on a review page.
> Nothing is posted. Version 1.0.0rc1 is a release candidate with 44 MCP tools.
> Install with `pipx install "myzing[all]==1.0.0rc1"`, then run `zing factory setup`.
> Needs Python 3.11+, FFmpeg, Node.js 20+ and Chrome or Edge.
> Works with Uoink to reuse saved media. Uoink is optional.

Use the repository URL. An owner must supply any contact email
and choose any submission tier. No email, payment or queue selection is included
in this kit.

## Cline marketplace

Status: **NOT SUBMITTED**

Destination: https://github.com/cline/mcp-marketplace

Suggested issue title is `Add Zing local clipping factory over MCP`.

Paste-ready body

> Name: Zing
>
> Repository: https://github.com/ryanbiddy/zing
>
> Website: https://myzing.app
>
> Install guide: https://github.com/ryanbiddy/zing/blob/main/llms-install.md
>
> Give Cline a long episode and get a pack of Shorts on your machine. Each
> receipt lists what the clip adds with sources and licenses. A separate context
> check asks whether the cut changes the meaning. Inspect the clips and checks
> on a review page. Nothing is posted. Zing 1.0.0rc1 is a release candidate with
> 44 MCP tools.
>
> Install with `pipx install "myzing[all]==1.0.0rc1"` and start `zing serve-mcp`.
> Needs Python 3.11+, FFmpeg, Node.js 20+ and Chrome or Edge. Run
> `zing factory setup` to install the Node sidecar. Works with Uoink to reuse
> saved media. Uoink is optional. See the install guide for download boundaries.

The current issue form asks the submitter to confirm they tested Cline
installing the server from the README or `llms-install.md`. Run that test before
submitting; do not tick the box without it. Use the 400x400 logo above. Any
screenshots the form requires remain to be supplied.

## GitHub MCP Registry

Status: **NOT SUBMITTED**

The GitHub MCP Registry onboards servers that are already in the official MCP
registry. After `io.github.ryanbiddy/zing` is published there, ask in
[discussion #1257](https://github.com/github/github-mcp-server/discussions/1257):

> Hi! Could `io.github.ryanbiddy/zing` be onboarded to the GitHub MCP Registry?
> It's published in the official MCP Registry. Zing 1.0.0rc1 is a release candidate
> with 44 MCP tools. Its local clipping factory turns a long episode into a pack
> of Shorts. Each receipt lists what the clip adds with sources and licenses.
> A separate context check asks whether the cut changes the meaning. The clips
> come with a review page. Nothing is posted.
>
> Install with `pipx install "myzing[all]==1.0.0rc1"`, then run `zing factory setup`.
> Needs Python 3.11+, FFmpeg, Node.js 20+ and Chrome or Edge.
> Works with Uoink (`io.github.ryanbiddy/uoink`) to reuse saved media. Uoink is
> optional. The repository is https://github.com/ryanbiddy/zing.

## mcp.so

Status: **NOT SUBMITTED**

Destination: https://mcp.so (web form; find its submit page). Paste:

- **Name:** Zing
- **URL:** https://github.com/ryanbiddy/zing
- **Short description:** Local clipping factory. Episodes become Shorts with receipts. 44 MCP tools. Release candidate.
- **Description:** Use the long description above.
- **Transport:** stdio
- **Tags:** video-editing, ffmpeg, captions, shorts, local-first, python, release-candidate

## Hermes plugin catalog

Status: **NOT SUBMITTED**

The package is `plugins/hermes-zing` in this repository. It passed
`hermes plugins validate` in an isolated Hermes 0.23 home, and Hermes connected
to Zing and registered all 44 tools. The catalog entry is one file,
`plugin-catalog/zing.yaml`, in a PR to
[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent). The
repository owner opens it (catalog rule 5). Pin `sha` to the full commit that
contains the package on `main`. Drafts of the entry and the PR body are kept
outside this repository. Uoink's entry is separate, so each app has its own
chance in the hackathon.

## Claude directory and Goose

Status: **NOT SUBMITTED**

Both list one launch command that must work on every machine. Install the release
candidate with `pipx install "myzing[all]==1.0.0rc1"` or
`uv tool install "myzing[all]==1.0.0rc1"`, then use `zing serve-mcp`.
Verify the install before submitting with `command: "zing", args: ["serve-mcp"]`.

## awesome-mcp-servers

Status: **NOT SUBMITTED**

Destination: https://github.com/punkpeye/awesome-mcp-servers

Category: Multimedia Process. Proposed entry:

```markdown
- [ryanbiddy/zing](https://github.com/ryanbiddy/zing) 🐍 🏠 - Release candidate with 44 MCP tools. A long episode becomes a pack of Shorts locally. Each receipt lists what the clip adds with sources and licenses. A separate context check tests whether the cut changes meaning. Includes a review page. Nothing is posted. Install `pipx install "myzing[all]==1.0.0rc1"` and run `zing factory setup`. Needs Python, FFmpeg, Node.js 20+ and Chrome or Edge.
```

Add OS emoji only for platforms tested on release day. The maintainer asked
Uoink (October 2026) for a Glama score badge right after the repository link, in
the form `[![ryanbiddy/zing MCP server](https://glama.ai/mcp/servers/ryanbiddy/zing/badges/score.svg)](https://glama.ai/mcp/servers/ryanbiddy/zing)`.
Wait for an actual Glama listing and score; this kit contains no claimed score.
