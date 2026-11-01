# Factory sidecar

Two small Node scripts for `zing factory`, driven by a pinned `playwright-core`
(Apache-2.0) and your installed Chrome or Edge. No browser is downloaded.

- `render.cjs <scene.html> <data.json> <outdir>`: seeks the deterministic scene to each
  frame time and writes JPEG frames for FFmpeg.
- `shot.cjs <url> <out.png> [framesDir]`: a screenshot and a six-second scroll recording
  of a page named in a clip. Cookie banners are hidden with CSS; nothing is clicked,
  accepted or submitted.

Install once with `npm ci` in this folder. Zing passes the browser path in
`ZING_BROWSER_PATH` and never passes stock-library keys to these scripts.
