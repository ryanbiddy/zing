Enable person and pet detection with the existing layout extra:

```powershell
$env:UOINK_URL='http://127.0.0.1:1'
zing layout fetch-model --vision
zing doctor --json
```

This explicitly downloads 21,069,611 bytes of Apache-2.0 ONNX weights into
`<ZING_HOME>/models/vision`. `--all` also fetches YuNet; the existing command
without either flag still fetches only YuNet. Model URLs include an immutable
OpenCV Zoo revision. Zing checks SHA-256 and byte limits before publishing a
download, permits HTTPS on every redirect, and reuses verified cached files.
`zing doctor` reports both files without loading OpenCV or using the network.
The [notices](THIRD-PARTY-NOTICES.md) record the exact weight grants and hashes.

MediaPipe's person detector runs through OpenCV DNN at the existing frame
samples, up to 2 fps. Its rectangle is a person head region, not a measured
full-body extent. YOLOX-S int8 supplies COCO people, pets, animals and objects
at cut/range starts and about 1 fps. Tracks retain every accepted detection's
source time, raw box, class, confidence and detector. These observations
travel in director plan evidence and delivery `zing.subject_analysis` records.
Different classes and detectors use separate tracks. YuNet and DOGFOOD1's
face-fragment stitching remain in place; object tracks cannot become speakers.
If a full-body region leaves no safe caption position inside a wide picture,
the planner can use its existing upper or lower padding band. It still checks
the caption's overlap before accepting that placement.

Photo memes and `zing still` use YOLOX detections as protected regions, with
class names and model confidence in the render report and still index.
Every detected box receives a 3% margin. Faces and user boxes stay protected
too. Default text placement can move into an external caption bar. Explicit
layouts retain their existing behavior: an overlap is reported, not silently
accepted as safe. Automatic crops include detected subjects in their focus.

No analysis, study, still or render path downloads a model. Without either
vision model, video framing uses the existing HOG people and saliency
fallbacks and names that fallback in warnings. With only one model available,
that model still runs. Without YOLOX detections, stills use model-free saliency.
Without the optional OpenCV runtime, the existing center/blur behavior stays
available. No MediaPipe wheel, OpenCV contrib wheel or Ultralytics package is
required or installed.

Scores are uncalibrated model outputs, not probabilities of correctness.
Small, occluded, back-facing or unfamiliar subjects can still be missed;
false detections can make crops wider. Sampled tracks and the 98% geometric
coverage test cannot certify detector recall. Review the saved evidence and
render before publishing.

Lean CI tests mock detection and exercise decoding with known output tensors.
Synthetic shapes do not prove real recognition. Real-model tests are opt-in:

```powershell
$env:UOINK_URL='http://127.0.0.1:1'
$env:ZING_REQUIRE_VISION='1'
uv run --frozen pytest -q tests/test_vision.py
```

Prepare the two verified local models first. The test uses three small CC0
images in `tests/fixtures/vision`; their manifest records source URLs,
original and derivative hashes, licenses, and expected classes.
`ZING_VISION_FIXTURES` can name another directory with the same manifest format.
Tests never fetch files. The normal suite skips real inference with an explicit
opt-in reason. Mocked decoding and integration tests run in lean CI without
OpenCV, models or FFmpeg.
