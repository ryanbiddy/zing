# PH dependency and asset notices

This private sidecar is an optional install. It adds no Python dependency.
`package-lock.json` records exact npm versions, registry integrity values and
package license metadata, including optional binaries for other platforms.
No node_modules directory, font binary, browser, media or model is committed.

| Component | License / source |
| --- | --- |
| HyperFrames 0.8.144 | Apache-2.0; [upstream](https://github.com/heygen-com/hyperframes), [published package](https://registry.npmjs.org/hyperframes/0.8.144). Existing install provenance identifies source commit `6f3f86a9c9824c8ad5b7bf760375e243466e5ee0`. |
| Puppeteer Core 25.15.0 and @puppeteer/browsers 3.2.5 | Apache-2.0; transitive CLI dependencies locked by npm. The proof uses the installed Puppeteer to test the pinned HyperFrames browser runtime. |
| fontkit 2.0.4 | MIT; transitive CLI dependency used to reject undecodable fonts and missing glyphs. |
| Sharp 0.35.5 | Apache-2.0; Windows binary package `@img/sharp-win32-x64` also includes LGPL-3.0-or-later libvips. Preserve its bundled notices/source obligations if distributing binaries. |
| Other lockfile dependencies | MIT, Apache-2.0, ISC, BSD-3-Clause, 0BSD and CC0-1.0. Optional libvips binaries are LGPL-3.0-or-later; wasm builds list Apache-2.0, LGPL-3.0-or-later and MIT together. No package in this lockfile has an absent license field. |
| Anton Regular | OFL-1.1. Copyright 2020 The Anton Project Authors. Exact source URLs and SHA-256 values are in `font-source.json`; full notice is in `ANTON-OFL.txt`. Explicit fetch into ignored workspace only. |
| Chrome Headless Shell 152.0.7977.30 | Separately installed and reused read only; Chromium BSD-style license plus third-party notices. Not redistributed by this pass. |
| FFmpeg/ffprobe 8.1.2 Gyan build | Separately installed GPLv3 binary; not vendored or downloaded by PH. Follow the [FFmpeg distribution terms](https://ffmpeg.org/legal.html) for any future binary distribution. |

The generated background and caption text are original synthetic test material.
PH adds no model dependency. The npm license inventory from this run is
saved in `zing-workspace/hyperframes/dependency-licenses.json`; that inventory is
package metadata, not a full audit of licenses inside every upstream bundle.
