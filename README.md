# Zing

**“Make my clips look like that video.”** Zing is a terminal-first creative studio
that gives your agent the tools to study a reference, choose a cut, match its
color, plan captions, render a draft and inspect the result. It also makes memes
from local images. Measurement and rendering run on your machine; your AI supplies
the creative judgment through the CLI or **28 MCP tools**. No Zing API key needed.

Today these are explicit steps you and your agent can run and review. A saved
brief and project inventory keep the work organized; automatic style-match
orchestration is still coming. Status: pre-alpha. MIT licensed.

## Five commands to a first result

From this source checkout in **PowerShell**, with Python 3.10+, uv and FFmpeg on
PATH, make a local meme without downloading media or model weights. The first
command installs Python dependencies. Use a fresh output folder on reruns.

```powershell
uv sync --all-extras
New-Item -ItemType Directory -Force zing-workspace/readme-demo | Out-Null
ffmpeg -hide_banner -loglevel error -n -f lavfi -i "testsrc2=size=640x360:rate=30:duration=1" -frames:v 1 zing-workspace/readme-demo/frame.png
uv run --frozen zing meme check --text "ONE QUICK TEST" --text "TWELVE OUTPUT FILES"
uv run --frozen zing meme render --image zing-workspace/readme-demo/frame.png --text "ONE QUICK TEST" --text "TWELVE OUTPUT FILES" --aspect 16:9 --out zing-workspace/readme-demo/meme.png --offline
```

Open `zing-workspace/readme-demo/meme.png`. For a generated sample clip → rendered
draft → color match → face-aware layout plan → cut-review PNG → animated meme,
follow the [tested PowerShell walkthrough](docs/QUICKSTART.md).
Run `uv run --frozen zing doctor` to diagnose missing prerequisites.

Use the current source checkout for these features. Zing is not on PyPI; the
[connection guide](docs/CONNECT.md) also covers the published prerelease wheel.
See [developer setup](docs/DEVELOPER-GUIDE.md) for environment details.

## Give your agent the skill

Copy the entire [skills/zing](skills/zing/SKILL.md) folder, including `references/`,
into your agent's configured skill directory. For Claude Code, use
`~/.claude/skills/zing/`; the folder follows the
[Agent Skills format](https://code.claude.com/docs/en/skills). Codex and other
Agent Skills clients can use the same folder. The agent needs shell access to
Zing on the media's machine, or a connected Zing MCP server. Copying the skill
does not install Zing or expose local media to a remote agent.

To print MCP connection settings with this environment's real interpreter path:

```powershell
uv run --frozen zing serve-mcp --print-config
```

Merge the applicable settings into your client and check `zing_status`.
The skill covers command choice, source/output time mapping, job polling, cut
verification, download consent and honest capability limits. It is a standalone
folder; no Zing plugin marketplace or skill-install command is shipped here.

## What you can do now

| Task | Current capability and documentation |
|---|---|
| First local edit | [Quickstart](docs/QUICKSTART.md): generated clip, explicit EDL, rendered draft and review artifacts. |
| Study and direct footage | [Direct flow](docs/DIRECT-FLOW.md): measured cuts, words, OCR, raw keeper candidates and agent judgment; `--transitions` opts into transition detector v5. |
| Inventory a project | [Project inventory](docs/PROJECT-INVENTORY.md): stable asset IDs, hashes, probes, provenance and rescans. |
| Reuse saved references and remember a choice | [Uoink memory](docs/UOINK-MEMORY.md): verified local media, optional peer search, and durable draft-choice receipts. |
| Save creative intent | [Briefs](docs/BRIEFS.md): terminal interview, saved answers and evidence-based recommendations. |
| Match a color look | [Color](docs/color.md): SDR LUT approximation, recipe and before/reference/after preview; separate apply step. |
| Measure a reference's captions | [Caption geometry](docs/CAPTION-GEOMETRY.md): `zing study --caption-geometry` saves sampled polygons, text size, colors, motion tracks and coverage. |
| Find the caption font | [Font candidates](docs/FONT-CANDIDATES.md): `zing fonts match` ranks a pinned OFL/Apache library against measured caption glyphs; low scores are labeled substitutes. |
| Plan captions around faces | [Face-aware layout](docs/FACE-LAYOUT.md): sampled face tracks, UI masks, JSON geometry and debug sheet; attach the resulting layout to a v2 caption for rendering. |
| Understand audio | [Audio](docs/AUDIO.md): beats where supported, attacks, role candidates and loudness; no automatic mix changes. |
| Verify a cut in one image | [Timeline inspection](docs/INSPECT.md): frames, waveform, planned cuts and available timed text. |
| Make memes | [Memes](docs/MEMES.md): local stills, template metadata, ideas and text checks; animated memes on a video, GIF or zooming still with timed captions (`zing meme render-video`). |
| Render richer captions separately | [HyperFrames sidecar](docs/HYPERFRAMES-SIDECAR.md): local caption proof/adapter; silent output, not integrated with `zing render`. |
| Render v2 caption overlays | [HyperFrames v2 adapter](docs/HYPERFRAMES-V2.md): verified fonts, transparent ProRes captions and an FFmpeg composite helper. |
| Describe a full edit as data | [Composition v2](docs/COMPOSITION-V2.md): the versioned plan contract (assets, clips, transitions, positioned captions, LUTs, audio roles) and StyleRecipe. |
| Render positioned word captions | [V2 rendering](docs/RENDER-V2.md): verified assets and fonts, ASS positions/paths, word highlights and layout safety acceptance; unsupported v2 effects fail before rendering. V1 rendering stays compatible. |
| Plan three edits from a project | [Three draft plans](docs/PLAN-DRAFTS.md): `zing plan drafts` uses a recipe, saved brief and clip studies; writes distinct Composition v2 plans or a named shortage, with v1 EDL derivatives where supported. |
| Connect an AI or Uoink | [Connect](docs/CONNECT.md): 28 MCP tools, prompt pack, local stdio and optional suite integration. |
| Install, develop and test | [Developer guide](docs/DEVELOPER-GUIDE.md): setup, rendering paths and tests. |
| Diagnose URL acquisition | [Fetch troubleshooting](docs/FETCH-TROUBLESHOOTING.md): downloader and platform-access failures. |
| Check cross-product behavior | [Suite smoke CI](docs/SUITE-SMOKE-CI.md): deterministic Uoink/Writer/Zing checks and their limits. |
| Check asset provenance | [Third-party notices](docs/THIRD-PARTY-NOTICES.md): model pins, hashes and licenses. |

The older profile, assemble, render and thumbnail commands remain available.
The [skill command reference](skills/zing/references/commands.md) maps all 16
top-level commands. Attach layout results explicitly to Composition v2 captions.
Color/audio analysis and saved briefs remain separate planning inputs.

## Optional dependencies

Core Zing is stdlib-only. FFmpeg/ffprobe are external binaries; install a build
with libx264 and libass. In a checkout, `uv sync --all-extras` installs all Python
extras below. To select features, use e.g. `uv sync --extra memes --extra render`.

| Extra | Enables |
|---|---|
| `study` | yt-dlp, scene detection, faster-whisper transcription and RapidOCR. Models and remote media may require separate downloads. |
| `mcp` | MCP SDK v1 server for connected agents. |
| `render` | pysubs2 for ASS captions. |
| `memes` | Pillow for still rendering and timeline inspection. |
| `layout` | Pinned headless OpenCV; YuNet still needs an explicit model fetch. |
| `color` | NumPy for SDR matching and LUT work. |
| `audio` | NumPy for audio analysis. |
| `all` | All feature extras above. |
| `dev` | pytest, MCP and render dependencies for development. |

Use uv for the combined checkout environment: its exclusion avoids installing
overlapping GUI and headless OpenCV wheels. Plain pip does not honor that setting.
Kokoro runtime/model assets, OpenTimelineIO, and HyperFrames' Node/browser/font
installation are separate; `--all-extras` does not supply them. Doctor reports
feature-specific gaps. The HyperFrames page documents its own pinned setup.

## Local work and network boundaries

Zing itself needs no API key and opens no listening network service. It fetches
a video URL only when you supply one. On the first `zing study`, faster-whisper
downloads the selected speech model from Hugging Face if it is not already
cached (the default `large-v2` model uses about 3.1 GB; select another with
`ZING_WHISPER_MODEL`). RapidOCR may fetch missing weights too. Ask before an
uncached study; a local input alone does not guarantee an offline run.

Layout model downloads are explicit and hash-verified. Meme catalog searches and
local-photo renders stay offline; requesting a template may fetch its blank on
cache miss unless `--offline` is set. If you opt in to ElevenLabs voiceover, Zing
sends the voiceover request there (`ELEVENLABS_API_KEY`; the default voice engine
is local). Your AI client is yours to choose, cloud or local. MCP frame extraction
returns image content to that client; timeline inspection returns a local path.

Keep source media unchanged and outputs under ignored `zing-workspace/`. The
skill requires download consent and no uploads. Approximate color matches,
sampled face safety and heuristic audio labels need review; Zing cannot recover
the original font, LUT, transition preset or editor project from pixels.

## The Uoink connection

[Uoink](https://github.com/ryanbiddy/uoink) holds saved references and context;
Zing studies and edits media. Its agent kit uses the same portable skill-folder
approach. Zing works standalone with local files.

Suite-aware commands may make loopback HTTP calls to a local Uoink helper for
peer health, retained media, corpus notes and engagement. Zing never puts the
Uoink token in a URL. A verified kept-media handoff can avoid a new download;
if it is unusable, a study may refetch the handoff's source URL. The skill asks
for download consent before that path. No draft is automatically published.

For inventory only, `zing project init --reference uoink:123 --clips ./clips
--out ./my-project` records the reference; it does not resolve or study it.
See [Connect](docs/CONNECT.md) for the actual MCP handoff and explicit credentials.

## Coming next

`zing match` is planned, **not implemented**. `zing plan drafts` produces three
style-constrained plans and match reports from existing studies. Automatic study,
rendering and output verification for the complete reference-plus-folder flow
remain future work. Use the explicit planning and rendering steps above today.

