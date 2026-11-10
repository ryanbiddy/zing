# Factory sidecar

Two small Node scripts for `zing factory`, driven by a pinned `playwright-core`
(Apache-2.0) and your installed Chrome or Edge. No browser is downloaded.

- `render.cjs <scene.html> <data.json> <outdir>`: seeks the deterministic scene to each
  frame time and writes JPEG frames for FFmpeg.
- `shot.cjs <url> <out.png> [framesDir]`: a screenshot and a six-second scroll recording
  of a page named in a clip. Cookie banners are hidden with CSS; nothing is clicked,
  accepted or submitted.

Install with `zing factory setup`. This folder is the source of truth for
`package.json`, `package-lock.json` and `shot.cjs`. Keep the copies in
`src/myzing/_data/factory/sidecar` identical so wheel installs get the same files.
`render.cjs` ships in `src/myzing/_data/factory` and resolves Playwright from the
selected sidecar's working directory. `shot.cjs` runs from that sidecar.

Zing passes the browser path in
`ZING_BROWSER_PATH` and never passes stock-library keys to these scripts.
