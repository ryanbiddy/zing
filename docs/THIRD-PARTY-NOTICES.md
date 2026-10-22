# PF layout dependencies and assets

No model, image, media binary or third-party source is vendored in this pass.
Downloaded evidence belongs under the ignored `zing-workspace/` directory.

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
