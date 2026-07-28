# Third-party content notice

The MIT licence in `LICENSE` covers **the software in this repository** — the
code under `src/`, `tools/`, `tests/`, `packaging/`, and the documentation
written for this project.

It does **not** cover third-party material that is checked in as evaluation
evidence. That material stays under the licence of its original author. This
file aggregates the per-fixture rights records so the terms are visible at the
repository root instead of only inside sidecar JSON.

## Evaluation media (`tools/eval/real_videos/`)

Source videos are **not** redistributed. What is committed is downscaled
analysis thumbnails (height <= 360 px), measurement output, and provenance
records. Each fixture's `provenance.json` is the machine-readable record.

| Fixture | Creator | Source | Rights |
| --- | --- | --- | --- |
| `landscape-big-buck-bunny` | Blender Foundation | [video.blender.org](https://video.blender.org/w/dmhvQNzwBnrWy1iYzVv5g7) | CC BY 3.0 — "Copyright 2008, Blender Foundation / www.bigbuckbunny.org" ([evidence](https://peach.blender.org/about/)) |
| `short-daily-dweebs` | Blender Animation Studio | [video.blender.org](https://video.blender.org/w/gdfAeNysimipmpo7AbgaTp) | Host labels the upload "Attribution"; no version exposed, so none is inferred |
| `raw-talking-head-korky-paul` | Wikimedia Commons (uploader Mvolz) | [Commons](https://commons.wikimedia.org/wiki/File:Korky_Paul_Introduction.webm) | CC0 1.0 |
| `x-nasa-artemis-backseat-drivers` | NASA Artemis | [x.com/NASAArtemis](https://x.com/NASAArtemis/status/2040619776100147411) | U.S. Government work; see [NASA media guidelines](https://www.nasa.gov/nasa-brand-center/images-and-media/) for identifiers, third-party material, and implied endorsement |
| `reference-cleo-antarctica` | Cleo Abram | [YouTube](https://www.youtube.com/shorts/nlGYV0bmddI) | **Not determined.** No licence grant recorded. Retained as measurement evidence only. |
| `raw-editing-practice` | MrDenoise | [YouTube](https://www.youtube.com/watch?v=FHMXO_VikdA) | **Not determined.** No licence grant recorded. Retained as measurement evidence only. |

The last two rows are open items, not claims of permission. Their
`provenance.json` files carry no `rights` block.

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

## Reporting

If you own material referenced here and want it removed or its attribution
corrected, please open an issue on this repository.
