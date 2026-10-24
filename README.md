# Zing

<!-- mcp-name: io.github.ryanbiddy/zing -->

**“Make my clips look like that video.”** Zing is a terminal-first creative studio
that gives your agent the tools to study a reference, choose a cut, match its
color, plan captions, render a draft and inspect the result. It also makes memes
from local images. Measurement and rendering run on your machine; your AI supplies
the creative judgment through the CLI or **36 MCP tools**. No Zing API key needed.

## Start here: zing studio

Run `uv sync --all-extras` once in this checkout, put FFmpeg on PATH, then:

```console
uv run --frozen zing studio
```

Start with “What are we making?” Choose a reference edit, an edit from your
clips, a photo meme, a style breakdown, music advice, or another delivery shape.
Studio reads a local reference for up to eight seconds, then recommends length,
pacing, captions, audio and shape from what it measured. A local reference edit
adds a speech-setup question when clips have audio. Enter accepts a recommendation; paths
and topics need your answer. `?` explains, `b` goes back and `q` saves.
The plan shows the default output folder, with an option to change it. The
finish screen compares playable drafts by shape and recommends where to start.
Continue with `zing studio --resume <project>`.

On a first install, choose **small.en (~486 MB)** for a faster English draft,
**large-v2 (~3.09 GB)** for multilingual speech and better accuracy, or **skip
speech (0 MB)**. Enter recommends small.en for the shorter first download;
you must then type **yes** to authorize it. Small.en can miss names, accents and
quiet words, so review its captions. Large-v2 remains the `zing study` default.
Studio verifies the download's SHA-256 and caches it under `ZING_HOME`.
Skipping disables spoken captions and whole-line continuity; clips without safe
speech timing may be excluded. The finish screen reports the model and download.

`zing doctor` and `zing setup` list cached speech models. To prepare one before
editing, run `zing doctor --speech-model small.en` and confirm the download.
See [speech setup](docs/DOCTOR.md) for unattended use and cache details.

See [Studio](docs/STUDIO.md) for a real transcript, JSON answers and agent use.
Downloads are off by default. Missing evidence, failed drafts and blocked
captions remain visible. Status: pre-alpha. MIT licensed for this project's
software and documentation; third-party terms are in [NOTICE.md](NOTICE.md).

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

For agent setup, see [install from source](llms-install.md). The
[directory submission kit](docs/DIRECTORY-SUBMISSIONS.md) is preparation only;
its future PyPI registry entry is not an available package or a submitted listing.

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
| Guided creative session | [Studio](docs/STUDIO.md): questions, measured recommendations, confirmation and resume. |
| First local edit | [Quickstart](docs/QUICKSTART.md): generated clip, explicit EDL, rendered draft and review artifacts. |
| Explain how a video was made | [Explain](docs/EXPLAIN.md): `zing explain reference.mp4 --out ./style-card`; measured JSON, plain English, phone-readable PNG and a reusable recipe. Add `--against draft.mp4` to compare. |
| Match a reference with your clips | [Match](docs/MATCH.md): `zing match reference.mp4 --clips ./clips --out ./project --brief brief.json`; resumable A/B/C rendering, full decode, PNGs and measured reports. |
| Find short cuts inside source clips | [Source map](docs/SOURCE-MAP.md): confirmed extra boundaries for planning, with frame evidence and unchanged public study shots. |
| Study and direct footage | [Direct flow](docs/DIRECT-FLOW.md): measured cuts, words, OCR, raw keeper candidates and agent judgment; `--transitions` opts into transition detector v6. |
| Inventory a project | [Project inventory](docs/PROJECT-INVENTORY.md): stable asset IDs, hashes, probes, provenance and rescans. |
| Reuse saved references and remember a choice | [Uoink memory](docs/UOINK-MEMORY.md): verified local media, optional peer search, and durable draft-choice receipts. |
| Save creative intent | [Briefs](docs/BRIEFS.md): terminal interview, saved answers and evidence-based recommendations. |
| Match a color look | [Color](docs/color.md): SDR LUT approximation, recipe and before/reference/after preview; separate apply step. |
| Measure a reference's captions | [Caption geometry](docs/CAPTION-GEOMETRY.md): `zing study --caption-geometry` saves sampled polygons, text size, colors, motion tracks and coverage. |
| Choose a caption preset | [Punch, Box and Clean](docs/CAPTION-PRESETS.md): fixed word slots, measured widths, and readable dialogue. |
| Style captions for delivery | [Captions](docs/CAPTIONS.md): active-word boxes, before/after colors, and minimum phone-readable sizing. |
| Find the caption font | [Font candidates](docs/FONT-CANDIDATES.md): `zing fonts match` ranks a pinned OFL/Apache library against measured caption glyphs; low scores are labeled substitutes. |
| Plan captions around faces | [Face-aware layout](docs/FACE-LAYOUT.md): sampled face tracks, UI masks, JSON geometry and debug sheet; attach the resulting layout to a v2 caption for rendering. |
| Fill portrait and square frames | [Framing](docs/FRAMING.md): fit, static fill, or bounded subject-following crops with captions placed inside the visible picture. |
| Detect people and pets | [Vision models](docs/VIS1.md): optional OpenCV DNN models, explicit downloads, class evidence and fallback limits. |
| Understand audio | [Audio](docs/AUDIO.md): beats where supported, attacks, role candidates and loudness; no automatic mix changes. |
| Verify a cut in one image | [Timeline inspection](docs/INSPECT.md): frames, waveform, planned cuts and available timed text. |
| Make memes | [Memes](docs/MEMES.md): photo folder + topic to concepts, a contact sheet, and selected stills (`zing still`); template metadata, text checks, and animated memes (`zing meme render-video`). |
| Render richer captions separately | [HyperFrames sidecar](docs/HYPERFRAMES-SIDECAR.md): local caption proof/adapter; standalone output is silent, and v2 rendering composites its captions with footage and audio. |
| Render v2 caption overlays | [HyperFrames v2 adapter](docs/HYPERFRAMES-V2.md): verified fonts, transparent ProRes captions, an FFmpeg composite helper and integration with `zing render`. |
| Describe a full edit as data | [Composition v2](docs/COMPOSITION-V2.md): the versioned plan contract (assets, clips, transitions, positioned captions, LUTs, audio roles) and StyleRecipe. |
| Render positioned word captions | [V2 rendering](docs/RENDER-V2.md): verified assets and fonts, ASS positions/paths, word highlights and layout safety acceptance; unsupported v2 effects fail before rendering. V1 rendering stays compatible. |
| Plan three edits from a project | [Three draft plans](docs/PLAN-DRAFTS.md): `zing plan drafts` uses a recipe, saved brief and clip studies; writes distinct Composition v2 plans (similar ones or a labeled out-of-timing alternative, never a duplicate, when few fit the reference timing) or a named shortage, with v1 EDL derivatives where supported. |
| Keep speech complete | [Continuity and ASR repair](docs/CONTINUITY.md): clause boundaries, source order, bounded timing estimates, text roles and separate render/style status. |
| Choose and place music | [Music advice and editing](docs/MUSIC.md): local track checks, beat-aware cuts, drop alignment and measured speech ducking. |
| Connect an AI or Uoink | [Connect](docs/CONNECT.md): 36 MCP tools, prompt pack, local stdio and optional suite integration. |
| Check MCP compatibility | [MCP SDK 2](docs/MCP-SDK2.md): legacy and modern stdio, wire fixtures and regeneration. |
| Check installed capabilities | [Doctor](docs/DOCTOR.md): optional runtimes, verified models and remedies. |
| Install, develop and test | [Developer guide](docs/DEVELOPER-GUIDE.md): setup, rendering paths and tests. |
| Check evaluation thresholds | [Evaluation contracts](docs/EVAL.md): the study performance budget. |
| Diagnose URL acquisition | [Fetch troubleshooting](docs/FETCH-TROUBLESHOOTING.md): downloader and platform-access failures. |
| Check cross-product behavior | [Suite smoke CI](docs/SUITE-SMOKE-CI.md): deterministic Uoink/Writer/Zing checks and their limits. |
| Check asset provenance | [Third-party notices](docs/THIRD-PARTY-NOTICES.md): model pins, hashes and licenses. |

The older profile, assemble, render and thumbnail commands remain available.
The [skill command reference](skills/zing/references/commands.md) maps the
top-level commands. Match attaches per-clip LUTs and available face-layout plans
to v2 compositions; standalone treatment artifacts still need explicit planning.

## Optional dependencies

Core Zing is stdlib-only. FFmpeg/ffprobe are external binaries; install a build
with libx264 and libass. In a checkout, `uv sync --all-extras` installs all Python
extras below. To select features, use e.g. `uv sync --extra memes --extra render`.

| Extra | Enables |
|---|---|
| `study` | yt-dlp, scene detection, faster-whisper transcription and RapidOCR. Models and remote media may require separate downloads. |
| `mcp` | MCP SDK server for connected agents. |
| `render` | pysubs2 for ASS captions. |
| `memes` | Pillow for still rendering and timeline inspection. |
| `fonts` | Pillow and pinned headless OpenCV for font comparison; expanded font assets require an explicit fetch. |
| `screen` | Optional macOS Quartz cursor recording (PyObjC); Windows uses stdlib. |
| `layout` | Pinned headless OpenCV; YuNet still needs an explicit model fetch. |
| `color` | NumPy for SDR matching and LUT work. |
| `audio-ml` | Optional CED audio tags via sherpa-onnx; weights via `zing doctor --audio-model ced-mini`. |
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
a video URL only when you supply one. Speech models come from Hugging Face
only through the consented, SHA-256-pinned setup: choose one in `zing studio`,
or run `zing doctor --speech-model small.en` (or `large-v2`) and confirm. Even
the first `zing study` never downloads one; without a cached model it leaves the
transcript empty and names that command (the default `large-v2` model uses about
3.1 GB; select another cached model or a local folder with `ZING_WHISPER_MODEL`).
RapidOCR may fetch missing weights too. Ask before an uncached study; a local
input alone does not guarantee an offline run.

`zing match` uses local models only and requires `--allow-download` before
acquiring a reference URL. Missing models remain warnings or planning shortages.

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

Match reports separate playable output from style fidelity. Current director
plans use cuts; sparse OCR, font substitutions, sampled face detection and color
distribution comparisons remain approximations that need review.

Screen recordings: [Screen-demo planning and cursor privacy](docs/SCREEN-DEMO.md).
