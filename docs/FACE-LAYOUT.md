# Face-aware caption layout (PF v1)

To plan captions around faces, install the optional runtime, explicitly fetch
the pinned model, then supply a local video and measured caption sizes:

```powershell
uv sync --all-extras
uv run --frozen zing layout fetch-model --workspace zing-workspace/home
uv run --frozen zing layout captions --video clip.mp4 --events captions.json --platform tiktok --workspace zing-workspace/home --out zing-workspace/layout-plan.json
```

The command writes the JSON plan and `layout-plan.contact.png`. It prints both
paths, unsafe event IDs, and warnings. Exit 0 means planning completed; consumers
must inspect `overlap.safe` and warnings before rendering. Invalid input, missing
dependencies, failed decoding, or a missing/corrupt model returns exit 2.

For layout alone, run `uv sync --extra layout` from the source checkout.
Use `uv sync --all-extras` for the combined checkout environment. RapidOCR declares
the GUI `opencv-python` package, which shares files with the headless wheel. The
checkout's uv exclusion removes that duplicate; PySceneDetect and layout already
provide headless OpenCV. Pip does not honor this uv setting. A mixed pip install
can overwrite `cv2`; doctor reports conflicting packages and layout rejects an
incompatible loaded runtime. Doctor checks metadata/cache without importing native
libraries or running inference. Remove
the GUI/contrib wheels and reinstall `opencv-python-headless==4.13.0.92`, or use
the checkout's uv environment. This packaging limitation needs upstream coordination
before offering a combined pip installation with the same guarantee.

## Input and output

`captions.json` is a nonempty array of events, or this versioned envelope:

```json
{
  "version": 1,
  "events": [
    {"id": "phrase-1", "start": 0.2, "end": 1.8,
     "width": 0.55, "height": 0.12, "preferred_anchor": "lower-third"},
    {"id": "phrase-2", "start": 1.8, "end": 3.0,
     "width": 0.55, "height": 0.12, "preferred_anchor": [0.4, 0.3]}
  ]
}
```

Times are seconds from the first decoded video frame. Use the same video/crop
that the caption compiler will render. Boxes use normalized display coordinates:
`x`, `y` are the top-left corner; `width`, `height` are fractions of the frame.
An anchor is the caption center. Sizes must contain the entire visible caption,
including outline, plate, wrapping and maximum animated scale. PF does not
measure fonts, split text, or estimate a box from a string.

The named anchors are `top`, `upper-third`, `center`, `lower-third`, `bottom`,
`left`, and `right`. An event may also supply a `path` array of
`{"time": 0.2, "box": {"x": 0.1, "y": 0.2, "width": 0.55, "height": 0.12}}`
keyframes. A path has 2–16 keys, includes the exact event start and end, and
retains the event's width and height. Boxes interpolate linearly. All times,
dimensions, coordinates and schema versions are validated.

Each output event has:

- `box` or `path`, with normalized geometry and absolute video times;
- `reason`: preferred anchor, previous position, nearest free zone, explicit
  path, short motion path, or infeasible;
- `overlap`: a Boolean `safe`, colliding face IDs/mask names, method and scope;
- `scale`, `fallback`, and `warnings` describing any required adjustment.

The plan also contains padded face tracks, masks, per-sample boxes/confidences,
video hash, actual sample timestamps, detector/model versions, settings and
warnings. Track IDs only associate nearby boxes within this video. No face
embeddings, recognition, or identity inference are used or stored. Sample PNGs
are temporary; the requested debug contact sheet remains on disk.

The classes in `myzing.layout` are independent versioned dataclasses with
`to_dict()` / `from_dict()`. Version 1 is emitted at every record level; omitted
input versions default to 1; other versions fail. The [v2 ASS renderer](RENDER-V2.md)
consumes the geometry, linear paths and reduced `scale`. Unsafe layouts need
explicit acceptance; a plate does not make an overlap safe. HyperFrames layouts
require final sizes with scale 1. Caption-to-caption collisions are outside
PF; concurrent input events receive a plan warning.

## Placement and tracking

YuNet uses CPU inference on frames selected by FFmpeg. Default sampling is at
most 2 fps, configurable from 0.1 to 8 fps with `--sample-rate`; jobs are limited
to 600 samples and 640 pixels per image axis. Longer jobs fail with a remedy
instead of silently dropping the end. Selected frames retain their actual PTS,
including variable-frame-rate inputs. FFmpeg applies display rotation and sample
aspect ratio before normalization. FFmpeg 8.1.2 is the tested binary.

Tracking uses deterministic greedy IoU matching with a centroid distance gate.
It links across gaps up to `--max-gap` seconds (default 1.5), interpolates linearly,
and holds endpoints for that interval. A centered three-sample smoothing window
is expanded to include each measured box, then padded on every side by
`--face-margin` (default 0.04 of frame width/height). This avoids shrinking away
a measured face edge. Bridged occlusions and limited track lifetimes are reported.
The Python API exposes matching thresholds and smoothing radius. `choose_layout`
expects already padded tracks, such as the output of `build_tracks`.

For each event, the chooser tries its preferred anchor, the previous safe event's
position, then nearest candidates from a 9-by-13 grid, named zones and obstacle
edges. Callers can add normalized centers with the Python API's `anchors` argument.
Obstacle-edge search retains the 24 nearest coordinates per axis. Stable boxes
are preferred to movement. If necessary, a bounded search joins up to 32 free
candidates at the start, midpoint and end into a three-keyframe path. Every
connecting segment is checked. An explicit safe path takes precedence; a blocked
explicit path is replaced with a warning.

Collision checking solves the interval where all four rectangle-separation
inequalities are positive. It splits at every face and caption keyframe, so
collisions between detector samples are checked analytically. Merely touching
edges is allowed (floating-point tolerance: 1e-12 normalized units). Stationary
faces with unchanged caption dimensions produce a stationary caption position.

When full-size search fails, the chooser tries 85%, 70%, then 55% boxes and reports
the required resize. If those fail, it returns an unsafe plate proposal and an
explicit infeasible warning. Reframing or reserving an external top/bottom bar is
then an editorial decision. A plate drawn over a face remains unsafe. Search
exhaustion means no feasible result under these finite candidates, path lengths
and scales; it does not prove that every conceivable path is impossible.

`safe` is a geometric result against the supplied padded tracks and masks. Sparse
detection can miss a face, an abrupt entrance, a cut or nonlinear movement. Long
occlusions are unknown. This pass does not establish detector recall or every-frame
safety on arbitrary footage. Increase sampling/margins and inspect the contact
sheet and final render for the intended clip.

## Platform exclusions

These normalized vertical-video masks are approximations, not platform promises.
Tune them for device, locale, expanded descriptions and publishing-preview state.

| Platform | Top bar | Bottom description | Right rail |
|---|---|---|---|
| TikTok | y=0–0.12 | y=0.78–1 | x=0.86–1, y=0.28–0.78 |
| Reels | y=0–0.10 | y=0.80–1 | x=0.87–1, y=0.32–0.80 |
| Shorts | y=0–0.10 | y=0.80–1 | x=0.86–1, y=0.30–0.80 |
| none | no masks | no masks | no masks |

Use `--platform custom --masks masks.json` to replace presets. The file is a JSON
array such as `[{"name":"description","box":{"x":0,"y":0.8,"width":1,"height":0.2}}]`.
An explicit empty array is allowed. Passing custom masks with another platform
is rejected to avoid silently ignoring them.

The contact sheet shows up to 24 evenly distributed sampled frames. Red boxes
are raw detections, amber boxes are padded tracks, blue regions are UI masks,
green boxes are geometrically clear captions, and magenta boxes are unsafe
fallbacks. A contact sheet illustrates selected frames; the continuous collision
check is the evidence for the interval between them.

## Pinned model and offline behavior

The optional dependency is `opencv-python-headless==4.13.0.92`, using OpenCV
4.13.0's DNN CPU backend with the fixed-shape `face_detection_yunet_2023mar.onnx`.
[Upstream's compatibility notes](https://raw.githubusercontent.com/opencv/opencv_zoo/main/models/face_detection_yunet/README.md)
distinguish this OpenCV 4.x export from the 2026 dynamic export for OpenCV 5.

The model is pinned to opencv_zoo commit
`f12e12798e8314f7c074a6656816c048dcc95b7a`, size 232,589 bytes, SHA-256
`8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`.
The exact URL is the `MODEL_URL` constant in `layout/detector.py` and appears in
the fetch result and plan provenance. The cache is
`<Zing workspace>/models/yunet/face_detection_yunet_2023mar.onnx`.
Workspace resolution follows `--workspace`, `ZING_HOME`, then `~/.zing`.

Only `zing layout fetch-model` or `captions --fetch-model` may download the model.
Existing and downloaded bytes are checked against the pin; corrupt downloads
never replace a cached file. Importing layout, running doctor, and ordinary
caption planning do not fetch models. See [third-party notices](THIRD-PARTY-NOTICES.md)
for runtime, model and fixture licensing.

## Verification

```powershell
uv run --frozen pytest -q tests/test_layout.py tests/test_layout_detector.py tests/test_layout_command.py
$env:ZING_REQUIRE_FFMPEG = '1'
uv run --frozen pytest -q -m ffmpeg --expected-ffmpeg-tests 212

# Explicit, optional fixture and model provisioning:
uv run --frozen zing layout fetch-model
uv run --frozen python tools/layout_fixture.py --fetch-image
$env:ZING_REQUIRE_YUNET = '1'
uv run --frozen pytest -q tests/test_layout_detector.py
```

Detector tests skip unless `ZING_REQUIRE_YUNET=1`; that opt-in requires cached
assets and fails if they are missing. They never download. The test image defaults
to `zing-workspace/layout-fixtures/astronaut.png`, overridable with
`ZING_YUNET_TEST_IMAGE`. Its hash is checked. The positive face checks run at
320×320 and 512×512; a generated black frame is the negative case. Synthetic
track tests need no model or OpenCV and compare output to an independent dense
per-frame geometric oracle, alongside analytic mid-segment collision cases.
