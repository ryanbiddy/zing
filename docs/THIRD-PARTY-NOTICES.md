# Third-party dependencies and assets

## AUD1 audio tagging and ASR hygiene

The optional `audio-ml` extra adds `sherpa-onnx>=1.13,<3`; the lock resolves
`sherpa-onnx` and its native `sherpa-onnx-core` distribution to 2.0.0.
Both use Apache-2.0. No third-party training or inference code is vendored.
The runtime's [Apache license](https://github.com/k2-fsa/sherpa-onnx/blob/88204440c2ad19158fe77dbf470bb1fe7fdee613/LICENSE)
is pinned at revision `88204440c2ad19158fe77dbf470bb1fe7fdee613`, with SHA-256
`cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`.
Installed wheel notices cover native components, including ONNX Runtime.

CED-mini weights are Apache-2.0 according to the [original model card](https://huggingface.co/mispeech/ced-mini/blob/26c3ebcae85d4330f4fc26763f029539a3afcda0/README.md),
pinned at `26c3ebcae85d4330f4fc26763f029539a3afcda0`; card SHA-256:
`0fbd9dd64fffc22211d63b22689e38a81446d5e37db6148e3ac42667d3c22882`.
The [sherpa conversion repository](https://huggingface.co/k2-fsa/sherpa-onnx-ced-mini-audio-tagging-2024-04-19/tree/4da6df50dc47b25f91074b5ef7df4c1cc0dd7d4d)
is pinned at `4da6df50dc47b25f91074b5ef7df4c1cc0dd7d4d`. Its README identifies
the CED origin; the original weight card supplies the weight license. The GPL
CED training repository is not imported, vendored, or downloaded.

| Explicitly fetched asset | Bytes | SHA-256 |
|---|---:|---|
| `model.int8.onnx` | 10,451,715 | `ff29f39f9fbe637f72535160e9d006d61d872fdab0fce838672265b9b38cf946` |
| `class_labels_indices.csv` | 14,675 | `cdd1049833c4b86127c2773ac0d14a2754b6a6d0d1798002ed5c66e699708429` |

Immutable URLs are constructed in `src/myzing/audio/tag_models.py`. These
assets remain in the user's ignored workspace, with no implicit model fetch.
The label vocabulary is the AudioSet class index distributed with the conversion.
No AudioSet recordings are included.

The VAD edge algorithm is an independent stdlib implementation of stable-ts's
silence-suppression idea, using faster-whisper's existing bundled Silero VAD.
It introduces no package dependency. [stable-ts's MIT license](https://github.com/jianfch/stable-ts/blob/e312072cc024ae9fceb25b057d7d18524873a02b/LICENSE)
is pinned at `e312072cc024ae9fceb25b057d7d18524873a02b`, SHA-256
`69ac6d54d38598c96443b5314597568bb8fa21726c46168fcec98764de33dc23`.
No stable-ts source is copied. Its archived status does not affect the runtime.

Acceptance reuses V1 media from the manifest above and MUSIC1 CC0 tracks:
Electric (Sudocolon), Calm Piano / Vaporware (The Cynic Project), and The Charm
68 (The Cynic Project; vocals by Julie). Hashes and license URLs are retained
with the acceptance copies. The existing cached MIT faster-whisper-tiny model
at `d90ca5fe260221311c53c58e660288d3deb8d356` was copied locally, not downloaded.

## PF layout dependencies and assets

No model, image, media binary or third-party source is vendored in this pass.
Downloaded evidence belongs under the ignored `zing-workspace/` directory.

## MCP SDK 2 (October 2026)

The SDK migration changes only the optional MCP/development dependency graph.
Every added or upgraded package/version in `uv.lock` was checked against its
PyPI release metadata and the license text inside its wheel. Each inspected
wheel's SHA-256 matched the lockfile. All nine changed package/version records
have MIT, BSD-3-Clause or Apache-2.0 licenses; none is AGPL, non-commercial or
unlicensed. No dependency source or wheel is vendored.

| Package | Locked version(s) | License | Copyright / role |
|---|---|---|---|
| [mcp](https://pypi.org/project/mcp/2.3.0/) | 1.28.1 → 2.3.0 | MIT | Anthropic, PBC (2024); official SDK. |
| [mcp-types](https://pypi.org/project/mcp-types/2.3.0/) | 2.3.0 (new) | MIT | Anthropic, PBC (2024); protocol models. |
| httpx2 | [2.14.0](https://pypi.org/project/httpx2/2.14.0/), [2.16.0](https://pypi.org/project/httpx2/2.16.0/) (new) | BSD-3-Clause | Pydantic Services Inc. and contributors (2026–present); Encode OSS Ltd (2019). SDK HTTP client dependency. |
| httpcore2 | [2.14.0](https://pypi.org/project/httpcore2/2.14.0/), [2.16.0](https://pypi.org/project/httpcore2/2.16.0/) (new) | BSD-3-Clause | Pydantic Services Inc. and contributors (2026–present); Encode OSS Ltd (2020). HTTP transport dependency. |
| [httpx2-jsfetch](https://pypi.org/project/httpx2-jsfetch/1.0/) | 1.0 (new) | BSD-3-Clause | Pydantic Services Inc. and contributors (2026–present); Encode OSS Ltd (2019). Conditional Emscripten fetch adapter. |
| [opentelemetry-api](https://pypi.org/project/opentelemetry-api/1.45.1/) | 1.45.1 (new) | Apache-2.0 | OpenTelemetry Authors; SDK instrumentation API, no exporter configured by Zing. |
| [truststore](https://pypi.org/project/truststore/0.10.5/) | 0.10.5 (new) | MIT | Seth Michael Larson (2022); system certificate trust dependency. |

The 2.14.0 HTTP packages serve Python 3.10; 2.16.0 serves Python 3.11+.
`httpx2-jsfetch` is conditional on Emscripten and Python 3.12+. Its license was
checked even though it is not installed on this Windows host. The migration
removes `httpx-sse`, `pydantic-settings` and `python-dotenv` from the lockfile.
Unrelated existing package versions are unchanged. License metadata, wheel
hashes and extracted license texts for this audit are saved under
`zing-workspace/license-audit/` in the build-pass workspace.

## PF layout assets

| Component | Version/source | License and use |
|---|---|---|
| OpenCV headless | `opencv-python-headless==4.13.0.92` (OpenCV 4.13.0) | OpenCV: Apache-2.0; Python packaging scripts: MIT. Optional CPU face detection and debug drawing. Wheel-bundled components retain their own notices. [Publisher licensing](https://pypi.org/project/opencv-python-headless/4.13.0.92/#licensing). |
| NumPy | Transitive dependency of the OpenCV wheel; version resolved in `uv.lock` | BSD-3-Clause. Image-array bridge for inference/debug images. Already present through study dependencies. [NumPy license](https://github.com/numpy/numpy/blob/main/LICENSE.txt). |
| YuNet model | `face_detection_yunet_2023mar.onnx`, opencv_zoo commit `f12e12798e8314f7c074a6656816c048dcc95b7a` | MIT; copyright 2020 Shiqi Yu. [License at pin](https://github.com/opencv/opencv_zoo/blob/f12e12798e8314f7c074a6656816c048dcc95b7a/models/face_detection_yunet/LICENSE). Download only on explicit request. |
| Detector test portrait | NASA Eileen Collins portrait, scikit-image commit `c1af2bf80d2c8845bbbf06222f87e8b58a8e5c1e` | Public domain, no known copyright restrictions, per [scikit-image's asset documentation](https://scikit-image.org/docs/0.25.x/api/skimage.data.html#skimage.data.astronaut). Explicit developer fixture download only. |
| Generated test frames and tracks | This repository's Python tests and FFmpeg lavfi patterns | Test code is covered by Zing's MIT license; no external media asset. |
| Audit demonstration clip | Eight-second excerpt of Korky Paul Introduction, reused from the Oct 21 revival evidence | CC0-1.0, recorded/uploaded by Mvolz per that handoff's source verification. [Source file page](https://commons.wikimedia.org/wiki/File:Korky_Paul_Introduction.webm). The local excerpt's hash and provenance are saved beside it; no media is tracked. |

YuNet SHA-256:
`8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`.
Portrait SHA-256:
`88431cd9653ccd539741b555fb0a46b61558b301d4110412b5bc28b5e3ea6cb5`.
The portrait downloader also writes source/license/hash metadata alongside the
cached image. No scikit-image package is required.

FFmpeg and ffprobe remain external binaries. The tested Gyan FFmpeg 8.1.2 build
is GPLv3; this pass invokes the installed executable and does not vendor its
code or binaries. See [FFmpeg's legal page](https://ffmpeg.org/legal.html) and
[the build distributor](https://www.gyan.dev/ffmpeg/builds/) before redistribution.

MR1 macOS CI installs Homebrew's external `ffmpeg-full` bottle (9.0.2 when
verified on October 21, 2026), licensed GPL-3.0-or-later by its
[formula](https://formulae.brew.sh/formula/ffmpeg-full). Its libass dependency
uses the [ISC license](https://github.com/libass/libass/blob/master/COPYING).
These remain external tools; no source or binaries are vendored and no Python
dependency was added. The documented MacPorts alternative enables libass and
defaults to GPL-2+; see its [port details](https://ports.macports.org/port/ffmpeg/details/).

## P7 caption geometry

No new Python dependency or font is added. Geometry reuses the optional study
runtime: RapidOCR (Apache-2.0), ONNX Runtime (MIT), OpenCV (Apache-2.0), and NumPy
(BSD-3-Clause). Acceptance videos use the already bundled Anton and IBM Plex
Sans fonts under OFL-1.1; their files, licenses and hashes are in
`src/myzing/_data/fonts/` and its `sources.json`.

The explicit model provisioner pins RapidAI's v3.9.1 ONNX exports of
`PP-OCRv6_det_small.onnx`, `PP-OCRv6_rec_small.onnx`, and
`ch_ppocr_mobile_v2.0_cls_mobile.onnx`. URLs and SHA-256 hashes are recorded in
`src/myzing/study/caption_models.py`; downloads are stored in the workspace and
are never triggered by study. These are the same model families used by the
existing caption reader. Licensing: [RapidOCR Apache-2.0 license at v3.9.1](https://github.com/RapidAI/RapidOCR/blob/v3.9.1/LICENSE)
and [PaddleOCR Apache-2.0 license](https://github.com/PaddlePaddle/PaddleOCR/blob/main/LICENSE).

## P8 font candidates

The `fonts` optional extra reuses Pillow (HPND), OpenCV headless
(Apache-2.0; Python packaging MIT) and its NumPy dependency (BSD-3-Clause).
Core installation stays stdlib-only. No new third-party package or binary is
vendored. Pillow's FreeType rasterizer is supplied by the optional Pillow
installation; see [Pillow's license](https://github.com/python-pillow/Pillow/blob/main/LICENSE).

The font library pins Google Fonts revision
`45e3d5269e4a17d823f6d84470bc084dc5ae46f6` in
[`library.json`](../src/myzing/_data/fonts/library.json), with URLs and SHA-256
hashes for each font and license. Anton, IBM Plex Sans, Bebas Neue, Oswald,
Montserrat, Poppins, Inter, Roboto, Open Sans, Archivo Black and Bangers are
OFL-1.1. Luckiest Guy and Permanent Marker are Apache-2.0; see their pinned
[Luckiest Guy license](https://github.com/google/fonts/blob/45e3d5269e4a17d823f6d84470bc084dc5ae46f6/apache/luckiestguy/LICENSE.txt)
and [Permanent Marker license](https://github.com/google/fonts/blob/45e3d5269e4a17d823f6d84470bc084dc5ae46f6/apache/permanentmarker/LICENSE.txt).
Only the existing Anton and IBM Plex Sans files remain bundled. Other fonts
and their license texts are downloaded together on explicit `zing fonts fetch`.

## R9 rendering and full-suite validation

R9 adds no dependency or downloaded render asset. Its generated-media tests and
sample reuse the bundled OFL-1.1 Anton and IBM Plex Sans fonts. Temporary font
copies have private family names; glyph and license tables retain their bytes.

The existing `tests/test_study_transcribe_real.py` populated the configured
workspace cache with `Systran/faster-whisper-tiny` while running the full suite.
The publisher identifies this converted Whisper model as
[MIT licensed](https://huggingface.co/Systran/faster-whisper-tiny).
The resolved revision was `d90ca5fe260221311c53c58e660288d3deb8d356`; `model.bin`
SHA-256 was `dcb76c6586fc06cbdac6dd21f14cfd129cc4cdd9dce19bf4ffa62e59cbe6e6d1`.
All four cached files, revision-specific URLs and hashes are recorded in
`zing-workspace/r9-model-cache-receipt.json`. These were recorded after the
existing test downloaded the model, not verified against a pin beforehand.
The model is neither vendored nor used by the R9 renderer.

## V1 real-video evaluation (October 2026)

Only manifests, labels, evaluation code and reports are tracked. All source
videos, excerpts, PNGs, models, downloaded fonts and renders remain under the
ignored `zing-workspace/` directory. Excerpts are resized/re-encoded and trimmed;
no new edits or captions are added to the source corpus.

| Asset | License and credit | Source |
|---|---|---|
| Korky Paul Introduction | CC0-1.0; Mvolz | [Wikimedia file page](https://commons.wikimedia.org/wiki/File:Korky_Paul_Introduction.webm) |
| Tears of Steel (2012) | CC BY 3.0; (CC) Blender Foundation \| mango.blender.org; directed by Ian Hubert | [Sharing terms](https://mango.blender.org/sharing/), [download source](https://archive.org/details/Tears-of-Steel) |
| Duck and Cover (1951) | Public domain per archive declaration; Archer Productions, Inc.; Prelinger Archives / Internet Archive | [Archive item](https://archive.org/details/DuckandC1951) |
| We Are NASA (2018) | Public domain in the United States; NASA; narration by Mike Rowe. Agency logos retain their separate restrictions. | [Wikimedia file page](https://commons.wikimedia.org/wiki/File:We_Are_NASA.webm) |
| faster-whisper-tiny.en | MIT; Systran conversion of OpenAI Whisper; revision `0d3d19a32d3338f10357c0889762bd8d64bbdeba` | [Publisher repository](https://huggingface.co/Systran/faster-whisper-tiny.en) |

URLs, SHA-256 pins, attribution and derivation commands are in
[`tools/eval/real/manifest.json`](../tools/eval/real/manifest.json).
The model binary was checked against publisher LFS metadata; the remaining
small model files were fetched at the immutable revision and pinned locally.
The audit reuses the OCR, YuNet and OFL/Apache font assets documented above.
It adds no package dependency. See the
[evaluation report](../tools/eval/real/REAL-EVAL-2026-10.md) for measured results
and unvalidated capabilities.
