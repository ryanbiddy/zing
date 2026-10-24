# Third-party content notice

The MIT licence in `LICENSE` covers **the software in this repository** — the
code under `src/`, `tools/`, `tests/`, `packaging/`, and the documentation
written for this project.

The OpenCV Zoo-derived preprocessing, anchors and decoding in
`src/myzing/layout/vision.py` retain Apache-2.0 terms. Both upstream license
texts and Zing's modification notice ship in
`myzing/_data/docs/OPENCV-ZOO-LICENSES.md` inside the wheel.

It does **not** cover third-party material that is checked in as evaluation
evidence. That material stays under the licence of its original author. This
file aggregates the per-fixture rights records so the terms are visible at the
repository root instead of only inside sidecar JSON.

## Evaluation media (`tools/eval/real_videos/`)

Source videos are **not** redistributed. Each fixture's `provenance.json` is the
machine-readable record, and what a fixture may commit depends on whether a
redistribution basis exists for its source:

- **Licensed sources** commit measurement output plus downscaled analysis
  thumbnails (height <= 360 px).
- **Rights-unknown sources** commit measurement output only: no frames, and no
  verbatim transcript or on-screen caption text. Timings, confidences, and
  caption style flags are kept, together with SHA-256 hashes of everything that
  was removed, so the measurements remain checkable against the original by
  anyone holding it.

| Fixture | Creator | Source | Rights | Committed |
| --- | --- | --- | --- | --- |
| `landscape-big-buck-bunny` | Blender Foundation | [video.blender.org](https://video.blender.org/w/dmhvQNzwBnrWy1iYzVv5g7) | CC BY 3.0 — "Copyright 2008, Blender Foundation / www.bigbuckbunny.org" ([evidence](https://peach.blender.org/about/)) | measurements + thumbnails |
| `short-daily-dweebs` | Blender Animation Studio | [video.blender.org](https://video.blender.org/w/gdfAeNysimipmpo7AbgaTp) | Host labels the upload "Attribution"; no version exposed, so none is inferred | measurements + thumbnails |
| `raw-talking-head-korky-paul` | Wikimedia Commons (uploader Mvolz) | [Commons](https://commons.wikimedia.org/wiki/File:Korky_Paul_Introduction.webm) | CC0 1.0 | measurements + thumbnails |
| `x-nasa-artemis-backseat-drivers` | NASA Artemis | [x.com/NASAArtemis](https://x.com/NASAArtemis/status/2040619776100147411) | U.S. Government work; see [NASA media guidelines](https://www.nasa.gov/nasa-brand-center/images-and-media/) for identifiers, third-party material, and implied endorsement | measurements + thumbnails |
| `reference-cleo-antarctica` | Cleo Abram | [YouTube](https://www.youtube.com/shorts/nlGYV0bmddI) | **All rights reserved.** No licence grant located; none is claimed | measurements + hashes only |
| `raw-editing-practice` | MrDenoise | [YouTube](https://www.youtube.com/watch?v=FHMXO_VikdA) | **All rights reserved.** No licence grant located; none is claimed | measurements + hashes only |

The last two rows are all-rights-reserved uploads by named, identifiable
creators. Until the SEC1 cleanup on 2026-10-22 they also carried 63 extracted frames and
near-complete verbatim transcripts; those were removed, and
`tools/eval/real_videos/manifest.json` now sets
`media_policy.derived_frames_permitted: false`, which makes
`tools/eval/backfill_frames.py` refuse to put frames back. Each fixture's
`provenance.json` records what was removed under `redactions`, with content
hashes. Nothing here is a claim of permission.

## Speech fixtures (`tools/eval/fixtures/speech/`)

Excerpts from the LibriVox recording of Kate Chopin's *"Ripe Figs,"* read by
volunteer **Alan Davis Drake**. Dedicated to the public domain (`CC-PDDC`).
Public-domain status can vary outside the United States; this repository makes
no broader claim. Full provenance, source hashes, and the exact `ffmpeg`
extraction commands are in `tools/eval/fixtures/speech/provenance.json`.

## OCR calibration data (`tests/fixtures/research/ocr-calibration/`)

The seven cells have no recorded redistribution license. Their source URLs,
frame hashes, timings, geometry, confidence and labels remain; OCR text has
been replaced by content hashes and token counts. The freezer emits only this
content-free form. Five lexical calibration cases explicitly skip under
SEC1-OCR; generated overlay regressions and measurement-based checks continue
to run. See [the test record](tests/PRIVATE-FIXTURES.md).

## Fonts, models and other components

Bundled Anton and IBM Plex Sans fonts retain OFL-1.1 terms in
[src/myzing/_data/fonts/](src/myzing/_data/fonts/). The
[component notices](docs/THIRD-PARTY-NOTICES.md) and
[HyperFrames notices](tools/hyperframes-sidecar/NOTICES.md) record the
optional runtimes and explicitly downloaded assets. None receives a new
license from Zing's MIT grant.

The three small recognition images in `tests/fixtures/vision/` are CC0:
Christoffer G. Thomsen's cat, JasonAstros123's dog, and a frame from Mvolz's
Korky Paul video. Their [manifest](tests/fixtures/vision/manifest.json)
records source URLs, attribution, license links, hashes and derivation.

## V1 real-video evaluation

[tools/eval/real/](tools/eval/real/) contains JSON manifests, labels and
results, evaluation code and a report. It contains no media, frames, fonts or
models. The four source records and derived clips carry licenses, attribution,
source URLs and hashes in [manifest.json](tools/eval/real/manifest.json):
CC0-1.0 (Korky Paul), CC BY 3.0 (Tears of Steel), and recorded public-domain
sources (Duck and Cover and We Are NASA). The notices linked above retain
the jurisdiction and NASA identifier caveats. These are recorded rights
bases, not a claim of an individual model release.

## Reporting

If you own material referenced here and want it removed or its attribution
corrected, please open an issue on this repository.

## SCREEN1 screen-demo algorithms

OpenScreen (MIT, copyright 2025 Siddharth Vaddem), Screenize (Apache-2.0), and screenstudio-alt-skill (MIT, copyright 2026 Conner K Ward) inform the ports in `src/myzing/screen`. Upstream revisions, modifications and links: [Screen demos](docs/SCREEN-DEMO.md). Full upstream license texts: `docs/licenses/screen-openscreen.txt`, `screen-screenize.txt`, and `screen-screenstudio-alt-skill.txt`. Screenize has no upstream NOTICE file in the inspected revision. PyObjC (MIT) is an optional macOS-only dependency; no upstream application runtime or model weights are vendored.

The Screenize-derived portions of `myzing.screen.planner` retain Apache-2.0 terms. All three upstream screen-demo license texts and the modification notice also ship inside the wheel in `myzing/_data/docs/SCREEN-LICENSES.md`.
