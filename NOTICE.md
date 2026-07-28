# Third-party content notice

The MIT licence in `LICENSE` covers **the software in this repository** — the
code under `src/`, `tools/`, `tests/`, `packaging/`, and the documentation
written for this project.

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
creators. Until 2026-07-28 they also carried 63 extracted frames and
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

## OCR calibration data (`handoff/research/ocr-calibration/`)

Per-frame OCR output derived from seven third-party videos. **No frames or
images are committed** — only recognized text, geometry, and frame hashes. The
source URL for each cell is recorded in the header row of the corresponding
`frozen/*.jsonl` file. No licence grant is recorded for these sources; the data
is retained as internal calibration evidence.

**Open item.** Because several of those creators burn word-timed captions into
frame, the recognized text is close to a timestamped transcript for those
videos — including `youtube-nlgyv0bmddi`, the same Cleo Abram short whose
transcript was removed from `tools/eval/real_videos/`. The corpus is
load-bearing for three tests that compare *text-derived* OCR signals, so it
cannot be redacted the same way without destroying what it measures. It is
recorded here as unresolved rather than quietly kept.

## Reporting

If you own material referenced here and want it removed or its attribution
corrected, please open an issue on this repository.
