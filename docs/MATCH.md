# Match a reference with your clips

```sh
zing match reference.mp4 --clips ./clips --out ./zing-workspace/match --answers '{"target_length_seconds":6,"aspect":"16:9"}'
zing match reference.mp4 --clips ./clips --out ./zing-workspace/match --resume --json
zing plan choose ./zing-workspace/match --draft B
```

Use `--brief brief.json` for a saved versioned brief, or `--answers` for the same
fields accepted by `zing brief new`. With neither, a terminal starts the existing
interview; scripts must supply answers or resume a saved brief. Defaults are
three drafts and seed 0. This director supports exactly three alternatives.

References can be local files, `uoink:<id>`, or URLs. A URL needs the explicit
`--allow-download` flag before study's acquisition runs. Verified Uoink kept
media stays local; an unavailable peer or missing retained file is a named
failure, with no URL fallback. Match never downloads models. Provision needed
assets explicitly before running it; missing transcription can prevent planning.

The pipeline inventories clips, studies the reference with caption geometry,
available font candidates and experimental transitions, and studies each clip
in raw mode. It builds a reusable StyleRecipe, fits per-clip SDR color recipes,
measures audio, saves the brief, and asks the existing director for A/B/C.
It renders with the public v2 API, fully decodes each output, studies the rendered
file again, and writes a timeline PNG and match report.

Outputs in the project folder:

- `recipe.json`, `brief.json`, `project.json` and `match-state.json`.
- `drafts/plan-A.json`, `drafts/draft-A.mp4`, `drafts/draft-A.png` and
  `drafts/draft-A.match.json`, likewise B/C; decode receipts include SHA-256.
- `comparison.md` and `comparison.json`, with the actual ready count and failures.
- `director/comparison.json`, retaining planned values and shortages separately.
- `logs/`, reference/clip/output studies, color recipes/LUTs and audio maps.

Only a rendered, fully decoded, inspected draft with a report is ready. A failed
B render reports **2 of 3 ready**, names `render-B`, and links its log. Director
shortages are returned as produced; the command does not invent alternatives.
Exit codes: 0 for three ready, 1 for failure/shortage/partial results, 130 for
cancellation. `--json` writes only the final JSON to stdout; progress uses stderr.

`--resume` verifies checkpoint inputs and output hashes. Valid studies, grades,
plans, renders, decode receipts and reports are reused. Changed footage or
corrupt outputs invalidate affected work. The live inventory is rescanned using
its existing probe cache. Ctrl+C terminates the worker and its children (Windows
Job Object or POSIX process group); completed checkpoints remain resumable.
Each output folder admits one supervised job at a time.

Install the existing optional extras with `uv sync --all-extras` in a checkout.
Color/audio need NumPy; inspection needs Pillow. Face planning needs the layout
extra and the verified model from `zing layout fetch-model`. When available,
match measures faces on caption-free assembled footage, so boxes use output
coordinates. Otherwise it discloses default placement and unmeasured face safety.
Unsafe layouts still require review; match does not auto-accept them.

The current director emits cuts. Reference effects that cannot be reconstructed
are disclosed. Unsupported audio instructions remain named render/plan failures;
match does not silently remove supplied music or SFX. Font candidates are pinned
substitutes. Missing font candidates use disclosed system defaults.

Reports grade shot pace, first cut, caption timing/placement and color from the
rendered file as `pass`, `approximate`, or `miss`. Sparse OCR cannot certify
one-frame switches or ASR accuracy. Color compares unpaired scene distributions,
so it requires human review and makes no paired Delta E or original-LUT claim.
“Ready” means playable and reported; it does not mean every style dimension passed.

Over MCP, call `match_start(reference, clips, out, answers=..., resume=...)` and
poll `match_status(project)`. URL consent is `allow_download=true`. Results contain
paths and metadata, never media bytes. `match_status(project, cancel=true)` cancels
that server's owned job. Dead/stale workers are reported as failed.

The offline generated acceptance example is:

```sh
uv run --frozen python -m tools.match_examples --out zing-workspace/p18-sample
```

Its fixture provenance explicitly labels synthetic harmonic audio, authored ASR
words and stubbed OCR recognition. Real decoded pixels supply caption boxes;
the remaining pipeline runs normally. This example is a wiring/verification
test, not evidence of human speech recognition or subjective style quality.
