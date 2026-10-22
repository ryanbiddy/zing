# Standalone Composition v2 caption adapter (P10a)

P10a converts `CompositionCaption` records into a transparent ProRes 4444 MOV.
R9 can overlay that file after grading the cut. This pass does not route through
`pipeline.py`, `graph.py` or `captions.py`.

```python
from pathlib import Path
from myzing.render.hyperframes_v2 import captions_to_plan, composite_overlay
from myzing.render.hyperframes_adapter import render_hyperframes

# composition is an already loaded Composition v2. duration is the final cut's
# output duration, including its transition overlaps and speed maps.
plan = captions_to_plan(
    composition.captions,
    width=composition.width, height=composition.height,
    fps=composition.fps, duration=duration,
    base_dir=Path("saved-plan-directory"),
)
workspace = Path("zing-workspace")
overlay = workspace / "captions.mov"
receipt = render_hyperframes(plan, overlay, workspace=workspace)
composite_overlay(
    workspace / "cut.mp4", overlay, workspace / "composite.mp4",
    plan=plan, workspace=workspace,
)
```

The converter selects only `backend="hyperframes"` events and retains their
array order. ASS events remain for the other backend. It copies the inputs,
validates the v2 records, resolves font paths against `base_dir`, and checks each
font's declared SHA-256. The sidecar checks the hash again against the exact bytes
embedded in HTML. Word confidence, timing provenance, layout safety and license
records stay in the original composition; they are not rendering instructions.

Words keep their absolute output timestamps and gaps. `all_caps` transforms their
text. The phrase must match the ordered words after whitespace normalization.
Boxes use normalized top-left coordinates; paths preserve every keyframe and
interpolate linearly. Size, fill, highlight, outline and optional plate colors
map directly to the sidecar. Position anchors yield to the explicit layout.

Supported output is even dimensions from 2 to 4096 pixels, integer FPS from
1 to 120 (including equivalent rationals such as 60/2), and durations up to
600 seconds containing a whole number of frames. Fractional FPS, untimed words,
missing or changed fonts, mismatched phrase text, unsupported templates and
`layout.scale != 1` fail with a named error. For a scaled layout, supply final
font size/effect values and geometry with scale 1. No size or timing is silently
rounded. An empty selected caption list produces a fully transparent layer.

The templates are `phrase-highlight` and `kinetic`, with the same wrapping,
clipping and 180 ms word reveal documented in [the sidecar contract](HYPERFRAMES-SIDECAR.md).
Text overflow and multilingual shaping still require visual review. The adapter
does not perform layout collision detection, recover an original font or grade
the footage.

## Alpha and compositing

`background: {"transparent": true}` selects `.mov`; ordinary color/video plans
still use `.mp4`. HyperFrames 0.8.144's existing `--format mov` path emits
ProRes 4444 with `yuva444p10le` encoding (FFmpeg reports the decoded stream as
`yuva444p12le` here). The pin and npm lockfile are unchanged. This avoids a
separate PNG capture engine or chroma-key approximation.

The wrapper and Node entrypoint probe dimensions, FPS, duration and decoded frame
count before publishing. Transparent output also requires ProRes and an alpha
pixel format. The opt-in pixel test checks actual transparency, word timing,
path positions and the final composite on all 90 frames; a pixel-format label
alone is not the acceptance test.

`composite_overlay` requires both inputs to match the full plan's size, CFR,
duration and frame count. It resets their video timestamps, uses straight alpha,
copies optional source audio, and encodes H.264/yuv420p. It performs no resize or
grade. It uses inline `-filter_complex`, compatible with FFmpeg 6–9's CLI; the
local measured run uses 8.1.2. FFmpeg 6 and 9 were not executed in this pass.

## Offline guard and artifact ownership

Each job lives under `<workspace>/hyperframes/jobs/hf-job-*`, including the
project, browser temporary files, caches, logs and intermediates. Python uses
the existing workspace resolver when `workspace` is omitted. Direct Node uses
`ZING_HOME` or this checkout's `zing-workspace`. Success removes the job. Failure
keeps it and includes the path in the error. Receipts embed the normalized plan
and probe, so they remain useful after cleanup. Optional backward-seek proof
runs before cleanup and embeds its result in the receipt.

Node blocks external TCP/TLS hosts (including `hostname` options), HTTP/HTTPS,
HTTP/2, fetch redirects, DNS resolution and UDP. Shell commands, arbitrary child
executables and Node scripts are denied through `exec`, `execSync`, `execFile`,
`execFileSync`, `spawn`, `spawnSync` and `fork`. Narrow exceptions allow the
configured browser and FFmpeg tools, the pinned setup worker with the same
preload, and fixed local process queries/termination. FFmpeg inputs allow only
`file,pipe,fd`; Chromium uses the existing loopback-only proxy configuration.
The optional upstream NVIDIA memory query is disabled. An attempted forbidden
operation records a rejection and fails the render even if upstream catches it.
These hooks protect the trusted pinned renderer; they are not an OS firewall
or a sandbox for arbitrary Node code/native addons.

Both output and receipt are reserved before rendering. An existing file requires
Python `overwrite=True` or Node `--overwrite`. Each completed file is staged on
the destination volume, flushed, and published with an exclusive hard link;
an unrelated writer winning the name cannot be overwritten. Explicit overwrite
uses atomic replacement. Filesystems without hard-link support fail rather
than use a check-then-replace fallback. A lock serializes cooperating writers.
The receipt is published first; two filenames are not one filesystem transaction.
A crash can leave a receipt or reservation lock requiring inspection before
retry. Failure before the media commit rolls back a newly created receipt.

## Reproduce the acceptance checks

Follow [local setup](HYPERFRAMES-SIDECAR.md) for the unchanged pinned dependencies
and browser. P10a uses the already bundled Anton font (OFL-1.1); it downloads no
font or media. The pixel proof uses NumPy from the existing optional `color`
extra. Core conversion and publication remain stdlib-only.

```powershell
uv run --frozen pytest -q tests/test_hyperframes_v2.py tests/test_hyperframes_adapter.py
npm.cmd test --prefix tools/hyperframes-sidecar
$env:ZING_REQUIRE_HYPERFRAMES = '1'
$env:ZING_HYPERFRAMES_FONT = "$PWD/src/myzing/_data/fonts/Anton-Regular.ttf"
uv run --frozen pytest -q tests/test_hyperframes_v2.py tests/test_hyperframes_adapter.py
Remove-Item Env:ZING_REQUIRE_HYPERFRAMES
# Use an unused proof directory; existing outputs are protected.
$env:ZING_HYPERFRAMES_PROOF_DIR = 'zing-workspace/hyperframes/p10a-proof'
uv run --frozen python tools/hyperframes-sidecar/overlay-proof.py
```

The proof saves `overlay.mov`, `composite.mp4`, their receipts, the v2 caption
events, sidecar plan, `pixel-proof.json`, and `contact-sheet.png` with sampled
frame times. The local result checks 90 frames, has zero-frame word-switch error,
and maximum path-edge error of 0.001191 of a frame dimension (0.12%). It also
checks unchanged colored footage outside the caption rectangle and retained
audio. The HyperFrames tests have their own opt-in gate; the existing 102-test
FFmpeg gate count is unchanged.
