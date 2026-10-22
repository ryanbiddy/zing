# HyperFrames sidecar: pass PH

P10b connects the [Composition v2 adapter and transparent overlays](HYPERFRAMES-V2.md)
to `zing render`, with rational FPS and a verified cache in the render work folder.
The historical PH measurements below describe the original opaque fixture.

PH renders local, positioned word captions from a plain JSON plan on Windows.
The three-second proof passed at 640×360 and 30 fps: all 90 decoded frames matched
the expected word and caption-box position. The recorded render took **10.91
seconds**, including the Python wrapper's render subprocess and ffprobe check.
Setup, background generation and pixel inspection are outside that measurement.
This is one run on this PC, not a throughput benchmark.

The adapter is callable from Python and the sidecar's Node entrypoint, and P10b
routes v2 HyperFrames captions through it in `zing render`; `schemas.py` is unchanged. PH's
`version: 1` input is a small adapter contract for the future composition-v2
translator, not a replacement Zing timeline.

The published npm package is pinned to `hyperframes@0.8.144`, with its full
dependency tree in `tools/hyperframes-sidecar/package-lock.json`. npm metadata
was checked on 2026-10-21. This matches the existing Windows-tested tool version.
Its registry integrity is
`sha512-MrPr9NSGkgU9N1u+M5GNWHju90vlWUMJFKBQq3rHxakg0qDo11fO3dEoiCzStxCS3TQ4cuwBDMtY/MQJ24xrfg==`.
The existing shared HyperFrames install was read only. PH installs its
own Node modules and reuses only the existing browser executable.

Run setup from the worktree in PowerShell. The npm install and font-fetch command
are explicit network operations. Neither runs during a render or test.

```powershell
# Run from your Zing checkout.
# Ensure FFmpeg, ffprobe, uv and Node are on PATH.
$env:UV_CACHE_DIR = Join-Path $env:LOCALAPPDATA 'uv\cache'
$env:TEMP = $env:TMP = "$PWD\zing-workspace\tmp"
$env:HF_HOME = "$PWD\zing-workspace\models"
$env:ZING_HOME = "$PWD\zing-workspace\home"
$env:PYTHONIOENCODING = 'utf-8'
New-Item -ItemType Directory -Force $env:TEMP | Out-Null

uv sync --frozen --all-extras
npm.cmd ci --prefix tools/hyperframes-sidecar --ignore-scripts --no-audit --no-fund --cache zing-workspace/npm-cache
npm.cmd run fetch-font --prefix tools/hyperframes-sidecar

$env:HYPERFRAMES_BROWSER_PATH = 'C:\Tools\hyperframes\.cache\browser\chrome-headless-shell\win64-152.0.7977.30\chrome-headless-shell-win64\chrome-headless-shell.exe'
```

Node 24 or newer and FFmpeg/ffprobe must be on PATH. PH was exercised with
Node **24.18.0**, Chrome Headless Shell **152.0.7977.30**, and FFmpeg/ffprobe
**8.1.2**. `HYPERFRAMES_FFMPEG_PATH` and `HYPERFRAMES_FFPROBE_PATH` can select
existing binaries explicitly. A source install is expected; a wheel user can
point `ZING_HYPERFRAMES_SIDECAR` at a separately checked-out sidecar directory.
`zing doctor` reports this adapter as optional and checks prerequisites without
launching a render or downloading anything.

If that cached browser is unavailable, explicitly download the same version
into this worktree, then set `HYPERFRAMES_BROWSER_PATH` to its executable:

```powershell
node tools/hyperframes-sidecar/node_modules/@puppeteer/browsers/lib/main-cli.js install chrome-headless-shell@152.0.7977.30 --path zing-workspace/hyperframes/browser
$env:HYPERFRAMES_BROWSER_PATH = "$PWD\zing-workspace\hyperframes\browser\chrome-headless-shell\win64-152.0.7977.30\chrome-headless-shell-win64\chrome-headless-shell.exe"
```

The fixture font is Anton Regular, OFL-1.1, fetched from Google Fonts commit
`45e3d5269e4a17d823f6d84470bc084dc5ae46f6`. Its pinned URL and SHA-256, and those
of its license, are in [font-source.json](../tools/hyperframes-sidecar/font-source.json).
The font hash is
`a4ba3a92350ebb031da0cb47630ac49eb265082ca1bc0450442f4a83ab947cab`.
The fetch command verifies both hashes, reports the cache paths, and fails on
a corrupt cache entry. Font bytes live in ignored `zing-workspace`; only the
[OFL notice](../tools/hyperframes-sidecar/ANTON-OFL.txt) is tracked. Plans may
instead name a supplied local TTF, OTF, WOFF or WOFF2. Invalid font files or
missing glyphs fail with a remedy before Chrome starts.

To render the included solid-background plan:

```powershell
node tools/hyperframes-sidecar/render.mjs tools/hyperframes-sidecar/example-plan.json zing-workspace/hyperframes/example.mp4
```

Choose an unused output path on reruns, or explicitly pass `--overwrite` (Node)
or `overwrite=True` (Python). Both entrypoints protect existing output and
receipt files. The [example plan](../tools/hyperframes-sidecar/example-plan.json)
contains both templates and is also a readable contract example.

From Python:

```python
import json
from pathlib import Path
from myzing.render.hyperframes_adapter import HyperframesPlan, render_hyperframes

source = Path("tools/hyperframes-sidecar/example-plan.json").resolve()
plan = HyperframesPlan.from_dict(json.loads(source.read_text(encoding="utf-8")))
receipt = render_hyperframes(
    plan,
    Path("zing-workspace/hyperframes/from-python.mp4"),
    base_dir=source.parent,
    timeout=180,
)
print(receipt["output"], receipt["wrapper_seconds"])
```

The Python writer resolves assets relative to `base_dir` (the current directory
when omitted), writes UTF-8 JSON with absolute paths, and preserves the caller's
data. The Node entrypoint resolves paths relative to the input JSON file.
No asset URL, UNC share or playlist is accepted. Video backgrounds must be
decodable local MP4/MOV/MKV/WebM files at least as long as the plan. PH rejects
PQ/HLG video and uses a centered `object-fit: cover` crop. **The output is silent**;
source-audio preservation and mixing belong to pass 10's composition integration.

The input fields have these meanings:

| Field | PH behavior |
| --- | --- |
| `version` | Exactly `1`; unknown fields fail rather than silently losing effects. |
| `width`, `height` | Even dimensions, 2–4096 pixels. |
| `fps`, `duration` | Rate from 1–120, as an integer or exact rational string such as `"30000/1001"`; finite duration up to 600 seconds and an exact whole number of frames. These are validation bounds, not tested performance claims. |
| `background` | Exactly one `color: "#RRGGBB"`, `video: "local path"`, or `transparent: true` (ProRes MOV). |
| `captions[].start/end` | Absolute output seconds, half-open intervals `[start, end)`. |
| `words[].text/start/end` | Text and absolute output times. Positive, ordered, nonoverlapping intervals inside the event; gaps are allowed. |
| `box` | Normalized top-left `x`, `y`, `width`, `height`; the entire box must fit in the frame. |
| `path` | An alternative to `box`: ordered `{time, box}` keyframes covering the event's start/end. Position and dimensions interpolate linearly. |
| `style` | Local `font`, pixel `size`, `color`, `highlight`, `outline_color`, pixel `outline_width`, and optional `box_color`. All colors use `#RRGGBB`. |
| `template` | `phrase-highlight` holds the phrase and changes the active word's fill. `kinetic` reveals words in order, scaling from 0.65 to 1 and translating upward 12 px over 180 ms. Words remain visible until the event ends. Both support box paths. |

Captions center and wrap between supplied word entries, with eight pixels of
box padding. They clip to the planned rectangle. PH does not auto-shrink text,
detect overflow, break a long word, or validate complex-script shaping. Select
a suitable size and inspect the output. Path movement can change wrapping if
the box dimensions change. Events may overlap; array order sets the paint order.

The generated HTML embeds font bytes and uses local video files. Timed elements
control visibility and highlighting; finite CSS animations control movement.
HyperFrames seeks each animation against its element's local clock, so animation
delays inside timed elements are zero. The templates have no wall-clock timers,
randomness, external scripts or fetch calls. This follows the official
[determinism contract](https://hyperframes.heygen.com/concepts/determinism) and
[frame-adapter model](https://hyperframes.heygen.com/concepts/frame-adapters).

Render-time controls disable telemetry, updates and automatic installation;
strip credential-like environment variables from the CLI child; and isolate
HyperFrames' home-directory state beneath the render project. A preload rejects
external Node fetches, DNS lookups and sockets. Chrome routes external traffic
through an unavailable loopback proxy, with localhost exceptions for the renderer
and DevTools. A content security policy limits composition assets to local/data
sources. The receipt records zero attempted external Node requests; any such
attempt rejects the render. Loopback traffic is required. This is a guarded local
render path, not an operating-system network sandbox or a packet-capture audit.

The wrapper enforces a timeout and terminates the render's process tree on expiry.
Failed jobs keep the plan, HTML, logs and intermediate output for diagnosis;
successful jobs are cleaned. Before publishing
the MP4 to the requested path, ffprobe must confirm the dimensions, exact fps,
decoded frame count and duration within one microsecond of probe text rounding.
The Python verifier also checks exact rational duration ticks. The receipt records the
measured time and probe result. There is no cloud account or API-key requirement.

To reproduce the evidence, use a new proof directory:

```powershell
$env:ZING_HYPERFRAMES_PROOF_DIR = 'zing-workspace/hyperframes/my-proof'
uv run --frozen python tools/hyperframes-sidecar/proof.py

npm.cmd test --prefix tools/hyperframes-sidecar
uv run --frozen pytest -q tests/test_hyperframes_adapter.py
$env:ZING_REQUIRE_HYPERFRAMES = '1'
uv run --frozen pytest -q tests/test_hyperframes_adapter.py -k real_hyperframes_render
Remove-Item Env:ZING_REQUIRE_HYPERFRAMES
```

`ZING_HYPERFRAMES_FONT` can name another local copy of the fixture's Anton font.
The pixel acceptance bands assume that font and the authored fixture. Without
`ZING_REQUIRE_HYPERFRAMES=1`, only the real-render test skips. All plan, writer,
validation and failure-boundary tests run. When opted in, missing prerequisites
fail; they do not turn into skips. The real HyperFrames test has its own gate and
stays outside the FFmpeg marker gate. P10b's seven generated-media tests raise
that gate from 196 to 203 without requiring Node in CI.

HyperFrames lint reports zero errors and 12 Studio-editing warnings for the
fixture: timed elements lack `.clip` classes and highlight spans lack editable
IDs. The local render checks pass; Studio editing is outside PH's tested scope.

The saved proof is under `zing-workspace/hyperframes/verified/`:

- `fixture.mp4`: 73,219 bytes, H.264, yuv420p, 640×360, 30/1 fps, 90 frames,
  exactly 3.000000 seconds, one video stream and no audio.
- `fixture.mp4.receipt.json`: 10.744 seconds in the sidecar; 10.908 seconds in
  the wrapper's measured render-and-probe interval.
- `pixel-proof.json`: all 90 frames checked. Yellow word pixels switch on the
  planned frames, with zero-frame error in this fixture. The blue caption box
  follows the path within three pixels, allowing for H.264 edge artifacts.
  A magenta marker in the source video changes at frame 45, verifying that the
  supplied video is present and synchronized.
- `contact-sheet.png`, `contact-sheet-times.json`, and `frames/frame-*.png`:
  samples at frames 6, 17, 18, 29, 30, 41, 48, 59, 60, 71, 72 and 84. Read the
  sheet left to right, then down.
- `hf-run-*/hf-project-*/seek-proof.json`: eight caption frames requested again
  in a different order; all repeated PNG hashes match, both fonts loaded, and
  sampled DOM boxes match the plan within one pixel. This test removes the video
  to isolate caption determinism and sets the browser offline. It flushes two
  paint frames before capture; the authored animations remain paused.

A separate current-code solid-background render is saved at
`zing-workspace/hyperframes/solid.mp4`. Its sidecar time was 8.62 seconds.

The Windows proof uses one worker, screenshot capture, software rendering,
`--no-browser-gpu`, and `--experimental-fast-capture=false`. A bare Puppeteer
launch with only `--disable-gpu` timed out on this host; the proof harness works
with the pinned CLI's Chrome arguments. Under those arguments, the capability
probe could create WebGL and WebGL2 contexts through software rendering. That
does **not** establish shader-transition support: no shader was rendered in PH.
The render log reports no shader transitions and no page-side compositing.
The official [shader-transition documentation](https://hyperframes.heygen.com/packages/shader-transitions)
warns that its no-WebGL fallback omits shader compositing. PH rejects unrecognized
effect fields instead of promising an effect it did not render. Hardware GPU,
HDR/WebGPU and long-video performance remain untested. P10a tests transparent
ProRes output separately, as documented in the v2 adapter guide.

P10a supplies the composition-v2 caption translator with verified font hashes,
backend selection and transparent overlays. P10b adds rational FPS and routes
overlays through the graded, transitioned footage graph with its existing audio.
Packaging/install discovery beyond a source checkout, overflow, wrapping,
multilingual acceptance cases and shader effects remain outside these passes.
Cross-machine pixel
identity requires pinned browser, fonts and encoder behavior beyond this one-PC
proof. The proof harness imports one bundled 0.8.144 Chrome-argument export, so
an upgrade must review that import and rerun both the pixel and seek tests.

Primary references read for PH: [developer integration](https://hyperframes.heygen.com/developers/overview),
[CLI reference](https://hyperframes.heygen.com/packages/cli),
[caption typography and named styles](https://hyperframes.heygen.com/prompting/captions-catalog),
and [captions over footage](https://hyperframes.heygen.com/guides/captions-and-recuts).
The [dependency notices](../tools/hyperframes-sidecar/NOTICES.md) cover npm,
the fixture font and the separately installed tools.
