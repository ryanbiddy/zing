# Zing V1 real-video evaluation — October 2026

## T6 transition update

Detector v6 recovers the seven cuts missed by v5 and the calibration classroom
dissolve. The held-out title dissolve still fails. No decision rule changed
after held-out inference. The current measurements are in
[transitions-v6-results.json](transitions-v6-results.json); the original
[results.json](results.json) remains a frozen v5 record marked
`matches_current_detector=false`. The historical V1 sections below describe
their original checkout and measurements, including its then-missing commands.

The [clip split](transition-split.json) was fixed before tuning. Calibration:
`korky`, `tos-lab`, `tos-credits`, `duck-classroom`, `nasa-opening` (23.75 reviewed
seconds, 16 events). Held-out: `tos-dialogue`, `tos-memory`, `duck-titles`,
`duck-street`, `nasa-montage` (22 seconds, eight events). Each partition has one
dissolve. The prior v5 failure report was supplied in advance; source works
overlap across partitions. This is a tuning holdout with provisional
single-annotator labels, not a blind benchmark or a population accuracy estimate.

The split receipt, baseline source hashes, and
[pre-evaluation decision lock](transition-v6-lock.json) are checked in.
All ten clip and four source SHA-256 hashes match the existing manifest. Media
was read from `E:\AI\projects\zing\worktrees\v1-realeval\zing-workspace\real-eval`;
no source files were changed or downloaded. Matching stays one-to-one, within
two frames for cuts and interval IoU ≥0.5 for dissolves, at confidence ≥0.8.

| Partition / class | v5 TP / FP / FN | v5 precision / recall / unknown | v6 TP / FP / FN | v6 precision / recall / unknown |
|---|---:|---|---:|---|
| Calibration hard cut | 10 / 0 / 5 | 100% / 66.7% / 5 | 15 / 0 / 0 | 100% / 100% / 0 |
| Calibration dissolve | 0 / 0 / 1 | undefined / 0% / 1 | 1 / 0 / 0 | 100% / 100% / 0 |
| **Held-out hard cut** | 5 / 0 / 2 | 100% / 71.4% / 2 | 7 / 0 / 0 | 100% / 100% / 0 |
| **Held-out dissolve** | 0 / 0 / 1 | undefined / 0% / 1 | 0 / 0 / 1 | undefined / 0% / 1 |

| Other real class | Calibration v5 → v6: precision / recall / unknown | Held-out v5 → v6: precision / recall / unknown |
|---|---|---|
| Wipe | undefined / undefined / 0 → same | undefined / undefined / 0 → same |
| Zoom punch | undefined / undefined / 0 → same | undefined / undefined / 0 → same |
| Audio-aligned cut | undefined / undefined / 0 → same | undefined / undefined / 0 → same |
| Whip pan (unsupported) | undefined / undefined / 0 → same | undefined / undefined / 0 → same |
| Flash (unsupported) | undefined / undefined / 0 → same | undefined / undefined / 0 → same |

These other classes have no labeled positives. Audio alignment has no listening
ground truth; no real accuracy claim is made for it. Per-class unknown counts
mean missed labels intersected by an explicit abstention. Missing predictions
remain false negatives. Overall abstentions intersecting reviewed windows rise
from 52 to 62 on calibration and 118 to 123 on held-out: accepted cuts split
long unknown motion runs into smaller intervals. Those totals are activity
counts, not missed-edit counts. V6 has zero confident false edits in reviewed
no-cut spans, including the title overlay fade and Korky's monologue.

Across both partitions, hard cuts improve from 15/22 to 22/22 and dissolves
from 0/2 to 1/2, with no accepted false positives. This aggregate combines
calibration and held-out data and must not be called a held-out result.
Matched-cut MAE is 2.22 ms on calibration and 9.52 ms on held-out. The classroom
dissolve is measured at 7.000–7.700 s, against 6.833–7.633 s labeled (IoU 0.731;
worst endpoint error 166.7 ms). Its detection passes the unchanged interval
gate; its endpoints are less precise than the label's ±100 ms uncertainty.

The synthetic rerun uses the same 48 generated cases for both versions:

| Synthetic class | Labeled events | v5 precision / recall / unknown | v6 precision / recall / unknown |
|---|---:|---|---|
| Hard cut | 6 | 100% / 100% / 0 | 100% / 100% / 0 |
| Dissolve | 6 | 100% / 100% / 0 | 100% / 100% / 0 |
| Wipe | 8 | 100% / 100% / 0 | 100% / 100% / 0 |
| Zoom punch | 4 | 100% / 100% / 0 | 100% / 100% / 0 |
| Audio-aligned cut | 2 | 100% / 100% / 0 | 100% / 100% / 0 |
| Whip pan (unsupported) | 4 | undefined / 0% / 4 | undefined / 0% / 4 |
| Flash (unsupported) | 4 | undefined / 0% / 4 | undefined / 0% / 4 |

Both synthetic partitions independently pass precision ≥0.95, recall ≥0.85
for each supported class, and zero confident effects on the 16 motion/lighting
negatives. Total synthetic unknown activity is 82 → 83; all eight unsupported
events retain abstention coverage. The detailed split counts are in the JSON.

One real miss remains, all on held-out data:

| Clip / class | Clip-local labeled interval | Evidence in this T6 worktree |
|---|---|---|
| `duck-titles` / dissolve | **12.233333–12.766667 s** | [Midpoint PNG](../../../zing-workspace/t6/v6-held-out/duck-titles-dissolve-0-12.233.png), [seven-frame context](../../../zing-workspace/t6/v6-held-out/duck-titles-miss-strip.png) |

The PNGs show the title cards superimposed; v6 leaves this region unknown.
No remaining hard-cut miss exists in the reviewed windows. Further optical
tuning needs another frozen holdout rather than repeated tuning on this clip.

V6 adds area-averaged grayscale features, local motion baselines, block
structure and edge-change tests, short-blend peak suppression, and persistent
black detection. A separate optical-window test permits limited endpoint
motion while requiring spatial replacement and blend reconstruction. Rapid
translation, lighting changes and unsupported effects retain abstentions.
Evidence includes tested anchors, heuristic confidence, detector version and
reason. No dependency, renderer, shared schema or lockfile change was needed.

Reproduction commands and the opt-in local test are in
[TRANSITIONS.md](../TRANSITIONS.md). Full observations, per-miss PNGs, generated
media and test logs are under `zing-workspace/t6/`. The final command counts
are recorded in `zing-workspace/PASS-REPORT.md`. Replaying the frozen detector
on FFmpeg 6.1.1 reproduces the 8.1.2 real per-class counts, unknown counts and
matched boundary errors on both partitions. The opt-in classroom test passes
on both versions, and both mandatory FFmpeg gates pass **204/204** tests.

| T6 final check | FFmpeg 8.1.2 | FFmpeg 6.1.1 |
|---|---|---|
| `uv run --frozen pytest -ra` | 2,509 passed, 7 skipped; 345.02 s | 2,509 passed, 7 skipped; 363.66 s |
| `ZING_REQUIRE_FFMPEG=1 ... pytest -q -m ffmpeg --expected-ffmpeg-tests 204` | 204 passed; 371.98 s | 204 passed; 253.21 s |
| `ZING_REAL_TRANSITIONS=1 ... pytest -q tests/test_transition_v6.py -m real_media` | 1 passed; 6.40 s | 1 passed; 5.38 s |

The seven full-suite skips are six existing optional runtime checks (Kokoro,
three HyperFrames checks, YuNet and OpenTimelineIO) plus the separately executed
local-media test. Initial full runs found the new skip reasons missing from
the authored-skip registry; those entries were added before these final runs.
No required FFmpeg test skipped. Timings include concurrent checks and are not
a performance benchmark. No new dependency or license was introduced.

## Frozen V1 audit (detector v5)

Zing's synthetic transition scores overstate what this small real-video audit found. In 45.75 seconds reviewed frame by frame, detector v5 found 15 of 22 cuts and neither of two dissolves. Its accepted cut predictions were precise, but recall was 68.2%. Caption measurements missed two of eleven labeled title lines and overestimated visible text height. These results support keeping both capabilities experimental.

This pass changes evaluation tooling, labels, tests and documentation only. No detector, renderer, schema, dependency or lockfile changed. Evaluation started October 21 and finished October 22 on `feat/v1-real-eval`, HEAD `46a93c1646e6b5f5b8f9b44e8b86309a39019555`. Changes are uncommitted, as required by the pass rules.

Two requested outcomes remain unavailable: this checkout has no `zing match` command, and this session could not reliably audition audio. The real-input match attempt is recorded as a failure. Music/beat labels remain unknown pending listening review; no audio accuracy number is invented. No model test seams were used.

The checked-in [manifest](manifest.json), [labels](labels.json), [measured results](results.json), [runner](run_real_eval.py), and [scorer](scoring.py) are the review package. Full observations, downloaded media, models, renders, PNGs, command receipts and test logs are under `zing-workspace/real-eval/`; none are added to Git. Evidence paths below are relative to the worktree root unless linked.

Supporting changes are ten evaluator tests in `tests/test_real_eval.py`, asset credits in `docs/THIRD-PARTY-NOTICES.md`, and LF rules in `.gitattributes` for hashed evaluation text. `run-01/scoring-provenance.json` records the final normalized input hashes; the original run receipt remains intact.

## Corpus and provenance

Ten contiguous excerpts total **194 seconds**, from **four source works**. These are existing edited productions, including live action, animation, CGI, titles and archival footage. They are not ten independent creators or a representative TikTok/Reels sample. Eight excerpts are 20 seconds, one is 19 seconds and one is 15 seconds.

| Clip ID | Source interval | Content used |
|---|---:|---|
| `korky` | 0–19 s | Portrait monologue, camera/subject movement; negative transition control |
| `tos-dialogue` | 20–40 s | City view, small support-credit text, cut to two people |
| `tos-lab` | 230–250 s | Three-person conversation; close/wide shot changes |
| `tos-memory` | 360–380 s | Rapid dialogue edits, pink in-scene text, tilted console lettering |
| `tos-credits` | 570–590 s | Moving VFX scene, cut to black, animated closing credit |
| `duck-titles` | 37–52 s | Turtle animation, hand-lettered title, optical title-card dissolve |
| `duck-classroom` | 75–95 s | Animation-to-classroom dissolve, teacher and children |
| `duck-street` | 265–285 s | People walking, close/wide cuts, pan to sign |
| `nasa-opening` | 0–20 s | Space imagery and fast archival montage |
| `nasa-montage` | 100–120 s | Faces, laboratory scenes, mission control, CGI |

The sources and required credits are:

| Source | License and attribution | Verification |
|---|---|---|
| [Korky Paul Introduction](https://commons.wikimedia.org/wiki/File:Korky_Paul_Introduction.webm) | CC0-1.0; Mvolz | File page saved as `korky-license.txt`; downloaded hash also matches the earlier handoff's original-file hash |
| [Tears of Steel](https://archive.org/details/Tears-of-Steel) | CC BY 3.0; **(CC) Blender Foundation \| mango.blender.org**; directed by Ian Hubert | [Blender's sharing terms](https://mango.blender.org/sharing/) saved as `tos-license.txt`; Archive metadata saved as `tos-meta.txt` |
| [Duck and Cover](https://archive.org/details/DuckandC1951) | Public domain, as marked by the archive; Archer Productions, Inc. (1951), Prelinger Archives / Internet Archive | `duck-meta.txt` records the public-domain declaration and original derivative metadata |
| [We Are NASA](https://commons.wikimedia.org/wiki/File:We_Are_NASA.webm) | Public domain in the United States; NASA (2018), narration by Mike Rowe | File page saved as `nasa-license.txt`; its agency-logo restrictions still apply |

The manifest gives each clip its source URL, license URL, attribution, source start, duration, dimensions, frame rate, derivation arguments and SHA-256. It also pins the full downloaded source files. Archive downloads were checked against the publisher's MD5 metadata during initial acquisition; SHA-256 pins were then recorded. These are reproducibility pins, not signatures establishing authenticity. License evidence is under `zing-workspace/real-eval/`.

Excerpts were resized and converted to H.264/AAC at constant frame rate, preserving the file's declared display aspect ratio. No cuts, captions, music or grades were added. The Archive file named `tears_of_steel_720p.mp4` actually decodes to **862×360**. The Duck derivative decodes to **368×480** with square pixels and visibly elongated subjects; the audit retains that source distortion and resizes it to 490×640. Korky is 360×640; NASA is 640×360. Normalization and resizing limit conclusions about original-resolution and variable-frame-rate input. Re-deriving `tos-dialogue` with the recorded FFmpeg command reproduced its clip hash exactly.

## Labels and scoring

Labels were made by **Codex visual inspection**, without a second human annotator. They are provisional review evidence, not a human-certified benchmark. Full-clip one-second overviews located candidate windows. Every decoded frame in the declared windows was then inspected in timestamped FFmpeg contact sheets; `zing inspect timeline` PNGs supplied broader context and boundary views. Cut labels were placed before reading detector predictions. The frames and explicit uncertainties are retained in `labels.json`.

The scored windows cover 45.75 of 194 seconds. Within those windows, 22 cuts and two dissolves are exhaustively labeled for those classes. The first fully new shot defines a cut. One/two-frame blends in the archive copy carry two-frame timing uncertainty; modern clips carry one-frame uncertainty. Dissolve endpoints have approximately ±0.10 s visual uncertainty. The title fading onto the unchanged turtle background at 9.73–10.10 s is recorded as an overlay fade, not a shot dissolve. No wipe was found in the reviewed windows, so wipe recall is **undefined**.

Cuts match one-to-one within two frames; dissolves require interval IoU ≥0.5. Only v5 events with confidence ≥0.8 count as accepted predictions. Unknown events are abstentions, and missing labels remain false negatives. Predictions outside reviewed windows or crossing their edges are unscored. The same cut labels also score the separate shot-boundary detector. Neither metric describes all 194 seconds.

Five caption frames contain eleven manually transcribed title lines and two no-text controls. Boxes approximate visible ink with ±4-pixel uncertainty. They are axis-aligned, normalized frame coordinates. The caption score uses the shipped OCR confidence gate of 0.75 and one-to-one box IoU ≥0.5. Geometry errors use the refined ink box when present, otherwise the OCR box. Text is lowercased and punctuation removed; spaces remain significant. Character error rate conditions on matched lines and therefore excludes missed lines. Manual bounds are less exact than synthetic oracle masks, especially on small text.

Face labels concern **any visible human face at one instant**, not every face. Twenty-six clear frames are scored; two ambiguous small/occluded-face frames are excluded explicitly. Covered faces, backs of heads, the cartoon turtle and opaque helmet visors are negatives. Layout sampling is the default 2 fps. The supplied 0–10 s caption event, width 0.65 and height 0.12, is an evaluation probe, not a caption claimed to exist in the source. Face boxes and between-sample motion were not independently labeled, so there is no layout-safety accuracy claim.

## Measured results and synthetic comparison

| Capability | Real-video measurement | Synthetic comparison and limits |
|---|---|---|
| Transition v5: hard cuts | **15 TP / 0 FP / 7 FN**; precision **100%**, recall **68.2%**; matched-boundary MAE **2.22 ms** | Reran the 48-case generator: **6/6** hard cuts, zero FP, zero timing error. Good timing on detected cuts does not compensate for missing cuts. |
| Transition v5: dissolves | **0 TP / 0 FP / 2 FN**; precision undefined, recall **0%** | Synthetic **6/6**, zero FP. One real example is title-to-title; the other changes from animation to a live classroom. |
| Wipes | No labeled positives or accepted predictions in reviewed windows; P/R undefined | Synthetic **8/8**, zero FP. Real wipe accuracy remains unknown. |
| Separate shot boundaries | **16 TP / 4 FP / 6 FN**; precision **80%**, recall **72.7%** | This is not the v5 transition classifier and must not be presented as its score. Gradual-change regions can create extra shot boundaries. |
| Caption line detection | **9 TP / 0 FP / 2 FN** across five selected frames; precision **100%**, recall **81.8%** | A small title-focused sample. A separate post-hoc face hallucination below shows why this 100% precision must not be generalized. |
| Caption geometry/text | Median ink-box IoU **0.753**; median relative height error **23.1%**; median center error **0.31% x / 0.63% y**; exact normalized text **7/9** matched lines; matched-line CER **5.35%** | [Synthetic acceptance](../../../docs/CAPTION-GEOMETRY.md): IoU ≥0.8, height error ≤10%, center errors ≤2%. IoU and height miss those nominal bounds here; hand labels add uncertainty. |
| Font candidates | **100 “best substitute,” 15 unmeasured**, no high-confidence family claim; 13 pinned families available | [Earlier synthetic result](../../../docs/FONT-CANDIDATES.md): 77/78 top-three hits (98.7%), 29/78 above the similarity gate. Real font identities are unknown: no top-k accuracy can be scored. Track counts include OCR noise. |
| Face presence | **14 TP / 12 TN / 0 FP / 0 FN** on 26 clear frames; two unknown labels excluded | Existing tests exercise supplied tracks and limited detector fixtures; they do not establish broad real-face recall. This audit also does not establish recall for every person in a crowd. |
| Audio/beat analysis | Ten real analyses completed with ASR word evidence; **zero beat timestamps**, nine `none` tempo statuses, one `unknown` | Existing click-track tests require 120 BPM ±1 and beat timing within 1/30 s. No independent listening labels or tapped beat times exist here. Music is not equivalent to a steady beat; real precision/recall is unscored. |
| Color identity | Same-file match selected neutral, strength 0, score 0. After `zing color apply`, the frame at 6 s had mean absolute RGB8 error **2.021**, p99 **8**, max **28** | [Synthetic identity allowance](../../../docs/color.md): mean ≤1.5, p99 ≤5. This real textured frame exceeds those bounds after lossy export; it does not show that the neutral LUT itself is wrong. |
| Color between scenes | Distribution scores improved **0.065531 → 0.019989** and **0.105600 → 0.014074** | These are optimizer distances on its own sampled data, not independent perceptual error or pixel Delta E. Original grades/LUTs and corresponding target pixels are unknown. |
| End-to-end `zing match` | Real reference and two real clip paths supplied; command returned **2**, “unknown command 'match'” | Command is absent from this checkout. No successful match/render or substituted pipeline is claimed. |

The synthetic rerun passed its supported-class acceptance gate, with **zero confident effects on negatives**. Whip pan and flash remained unsupported, with zero recall and explicit abstentions. This report compares the same v5 detector on that generator and the real labels; it does not reuse historical v4 measurements.

Per-clip cut counts make the small denominators visible:

| Clip | Correct / labeled cuts | Missed clip-local times |
|---|---:|---|
| `korky` | 0/0 | None; no accepted cuts on this negative window |
| `tos-dialogue` | 1/1 | — |
| `tos-lab` | 2/2 | — |
| `tos-memory` | 2/2 | — |
| `tos-credits` | 0/1 | 18.000 |
| `duck-titles` | 0/0 | Dissolve is scored separately |
| `duck-classroom` | 1/2 | 9.933 |
| `duck-street` | 0/2 | 5.600, 6.867 |
| `nasa-opening` | 7/10 | 6.833, 7.167, 7.533 |
| `nasa-montage` | 2/2 | — |

## Concrete failures and minimal reproductions

All study examples use the real local `tiny.en` model and the pinned assets described below. Set the environment from the reproduction block first.

1. **Missed montage cuts.** Run `uv run --frozen zing study zing-workspace/real-eval/clips/nasa-opening.mp4 --transitions --caption-geometry --fonts --workspace zing-workspace/home`. The real cut at **6.833 s** switches from the curved horizon to launch flames; v5 emits no accepted hard cut there. It also misses 7.167 and 7.533 s. See [boundary timeline](../../../zing-workspace/real-eval/review/nasa-opening-boundary-0.png) and [every-frame sheet](../../../zing-workspace/real-eval/review/nasa-opening-frames-0.png). No threshold or detector change was made.

2. **Missed dissolves.** Run the same study command with `duck-classroom.mp4`. The **6.833–7.633 s** interval visibly superimposes turtle and classroom. V5 supplies no accepted dissolve. [Timeline PNG](../../../zing-workspace/real-eval/review/duck-classroom-boundary-2.png). With `duck-titles.mp4`, the **12.233–12.767 s** title-card dissolve is also missed. [Timeline PNG](../../../zing-workspace/real-eval/review/duck-titles-boundary-0.png). Both stay false negatives despite nearby unknown-motion evidence.

3. **OCR on a face.** Study `korky.mp4` with caption geometry and fonts. At **2.400 s**, the geometry sidecar recognizes `福` at **0.75289** confidence and places its OCR box over nearly the whole frame, despite no visible text. [Native frame](../../../zing-workspace/real-eval/review/korky-at-2.4.png), [box overlay](../../../zing-workspace/real-eval/run-01/korky-captions-2.4.png). This diagnostic was selected after examining outputs and is **excluded from the five-frame primary caption score**. It is a verified counterexample to treating that score as general precision. Font matching abstains because the fetched fonts do not contain the hallucinated character, but the spurious caption track already exists.

4. **Stylized title loss and inflated bounds.** Study `duck-titles.mp4`. At **11.000 s**, `Duck` is recognized at **0.7284**, below the gate; `and` is absent; only `Cover` survives. Its OCR box extends almost across the full frame. At **13.500 s**, all six title lines are located, but two strings lose letters/spaces. [Title overlay](../../../zing-workspace/real-eval/run-01/duck-titles-captions-11.png), [credit overlay](../../../zing-workspace/real-eval/run-01/duck-titles-captions-13.5.png). Green boxes are labels, magenta accepted OCR, yellow below-gate evidence. At `tos-dialogue` **0.500 s**, white title lettering also receives dark gray fill estimates around RGB 105/104/96 and 112/113/103; this is a visual diagnostic, not a scored color-ground-truth result. [Overlay](../../../zing-workspace/real-eval/run-01/tos-dialogue-captions-0.5.png).

5. **Color scoring and export boundaries.** `zing color match --reference tos-dialogue.mp4 --clip tos-lab.mp4` lowers its distribution score but reaches +0.5 EV and white-balance search limits. The matched lab frame is visibly brighter; no independent label establishes whether that is desirable. [Comparison](../../../zing-workspace/real-eval/run-01/color-tos-dialogue-tos-lab/comparison.png). The black-and-white reference produces a desaturated approximation, not complete monochrome. [Comparison](../../../zing-workspace/real-eval/run-01/color-duck-classroom-tos-dialogue/comparison.png). The identity export error above is reproducible using the same-file pair and its saved `look.cube`; [identity comparison](../../../zing-workspace/real-eval/run-01/color-tos-dialogue-tos-dialogue/comparison.png). A decode/encode control is needed before attributing that error to LUT application.

The end-to-end blocker has an even smaller reproduction:

```text
uv run --frozen zing match --reference zing-workspace/real-eval/clips/tos-dialogue.mp4 --clips zing-workspace/real-eval/clips/korky.mp4 zing-workspace/real-eval/clips/tos-lab.mp4
```

It fails before parsing the real paths. The attempted argument shape is an evaluation probe, not documentation of a supported interface. The exact receipt and error are `run-01/match.command.json` and `run-01/match.stdout.txt`.

## Five fixes worth prioritizing

1. **Provide the requested end-to-end match entry point.** The absence of `zing match` prevents the intended real-reference workflow outright. Implement and test it in its own product pass, then rerun this corpus without seams.
2. **Recover real hard cuts without sacrificing precision.** Start with NASA's first three montage cuts, the archival close/wide cuts and the cut to black. Current acceptance reaches 100% on six synthetic cuts but misses seven of twenty-two reviewed real cuts.
3. **Recalibrate gradual-transition detection on optical footage.** Both reviewed dissolves fail, including the clear animation-to-classroom transition. Keep grain, low contrast, overlapping motion and uncertain endpoint labels in the calibration set.
4. **Reject OCR regions that are actually people/scenery.** Korky's nearly full-frame false character passes the current confidence gate and creates a caption track. Add real no-text negatives and region/temporal evidence before relying on OCR confidence alone.
5. **Separate ink from background and preserve uncertainty in typography.** The 23.1% median height error, excessive title bounds and gray fill estimates on white lettering are more actionable than adding font families. Retest geometry and fill segmentation before interpreting substitute rankings as style fidelity.

Audio needs listening labels before a detector fix is ranked. Identity color export needs a codec-only control. The sampled face results do not justify changing the face detector.

## Reproduce and inspect

Use the pass-rule environment on this Windows host. No downloads occur without the relevant flag; missing/corrupt assets fail with a hint. The script refuses changed media hashes instead of silently rewriting labels. Model and font downloads use the existing explicit provisioners. All thirteen expected font families must be verified to reproduce the ranking experiment.

```powershell
# Run from your Zing checkout.
# Ensure FFmpeg, ffprobe and uv are on PATH.
$env:UV_CACHE_DIR = Join-Path $env:LOCALAPPDATA 'uv\cache'
$env:TEMP = $env:TMP = "$PWD\zing-workspace\tmp"
$env:HF_HOME = "$PWD\zing-workspace\models"
$env:ZING_HOME = "$PWD\zing-workspace\home"
$env:PYTHONIOENCODING = 'utf-8'
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
uv sync --all-extras

# First use only: explicitly permit source/model/font acquisition.
uv run --frozen python tools/eval/real/run_real_eval.py --download --fetch-models --fetch-fonts
# Later: fresh, offline evaluation with a new timestamped output directory.
uv run --frozen python tools/eval/real/run_real_eval.py
# Hash check only; regenerate missing derivatives from pinned local sources.
uv run --frozen python tools/eval/real/run_real_eval.py --prepare-only
# Recreate the native frame grabs, every-frame grids and boundary timelines.
uv run --frozen python tools/eval/real/run_real_eval.py --review-only
# Rescore this run, or reuse its successful commands explicitly.
uv run --frozen python tools/eval/real/run_real_eval.py --out zing-workspace/real-eval/run-01 --score-only
uv run --frozen python tools/eval/real/run_real_eval.py --out zing-workspace/real-eval/run-01 --resume
```

Exit 0 means all requested commands completed; exit 1 retains a failed-command outcome, including the currently missing `match`; exit 2 means invalid input/setup. The completed run has **46 successful command receipts out of 47**, with only `match` failing. This is a diagnostic run, not an accuracy acceptance gate. A low accuracy result does not disappear behind a green process status. Use a new output directory for changed production code; `--resume` deliberately reuses successful command receipts. Initial media acquisition and review preparation are separate from those 47 commands.

Pinned source and clip hashes are checked on every run. `--download` also permits the pinned Whisper download; `--fetch-models` explicitly provisions OCR and YuNet; `--fetch-fonts` invokes `zing fonts fetch --all`. Generated clip hashes depend on the recorded FFmpeg 8.1.2 encoding pipeline. A different encoder build may fail the derivative hash check and needs a separately reviewed corpus version, not an automatic hash update.

The local ASR model is **Systran/faster-whisper-tiny.en**, MIT, revision `0d3d19a32d3338f10357c0889762bd8d64bbdeba`, from its [publisher repository](https://huggingface.co/Systran/faster-whisper-tiny.en). Four revision-specific URLs and SHA-256 hashes are in the manifest; `model.bin` was checked against the publisher's LFS SHA-256. Study receives the local directory with `HF_HUB_OFFLINE=1`, uses CPU/int8 and produces real word timings. This is not a test of the default large-v2 model or ASR word accuracy. The full suite separately reused/downloaded its existing tiny-model fixture under `zing-workspace/models`; that fixture's license is already recorded in the notices.

No new package dependency was added. Existing assets used here are RapidOCR/PaddleOCR models (Apache-2.0), YuNet (MIT), eleven fetched font families plus two bundled families (OFL-1.1, except Luckiest Guy and Permanent Marker under Apache-2.0). The manifest records the model URLs/hashes and font-library pin. Package versions are in `results.json`; principal versions are faster-whisper 1.2.1, CTranslate2 4.8.1, RapidOCR 3.9.1, ONNX Runtime 1.27.0, OpenCV headless 4.13.0.92, Pillow 12.3.0 and NumPy 2.4.6. Existing FFmpeg is an external executable, not vendored. The cached Ruff 0.16.0 formatter was used locally; no formatter dependency was installed.

## Validation and remaining coverage

| Command/check | Observed result | Evidence under `zing-workspace/real-eval/` |
|---|---|---|
| `uv sync --all-extras` | Passed; existing extras only; lockfile unchanged | Installed versions in `results.json` |
| Initial `uv run --frozen pytest -ra` | **2,393 passed, 5 skipped**, 311.65 s | `pytest.log`, `pytest.xml` |
| Final `uv run --frozen pytest -ra` | **2,403 passed, 5 skipped**, 300.27 s | `pytest-final.log`, `pytest-final.xml` |
| New evaluator tests | **10 passed** | `tests/test_real_eval.py`: duplicate matching, two-frame tolerance, abstentions, review-window exclusion, unknown labels, hash binding, explicit download boundary and path containment |
| `ZING_REQUIRE_FFMPEG=1 uv run --frozen pytest -q -m ffmpeg --expected-ffmpeg-tests 169` | **169 passed**, 2,229 deselected, 190.13 s | `ffmpeg-gate.log`; run before adding the ten evaluator unit tests |
| `python -m tools.eval.transitions ... --generate --report ...` | **48 cases**, supported-class acceptance passed | `synthetic-transitions.log`, `synthetic-transitions.json` |
| Offline real replay | **46/47 commands passed**; evaluator exit 1 because `match` is absent | `run-01/commands.json`, `final-replay.log` |
| Strict asset verification and one derivative rebuild | Passed; `tos-dialogue` SHA-256 reproduced | Manifest and `derive-check.mp4` |
| Ruff on the three new Python files; `git diff --check` | Passed | No product files reformatted |

The handoff's 1,237-test / 22-FFmpeg-test baseline predates this checkout. Collection here found 2,398 existing tests, including 169 FFmpeg tests. The five existing optional skips are Kokoro, two HyperFrames checks, the opt-in YuNet portrait fixture and OpenTimelineIO. The real corpus did run YuNet successfully on all ten videos despite that separate fixture skip. No existing test was edited, weakened or newly skipped. FFmpeg 6.x was not run: no render, color, study or media implementation changed.

This corpus does not establish platform-scale accuracy, multilingual captions, modern animated word captions, reliable font identity, perceptual grading quality, music classification, beat timing or end-to-end style matching. Four source works and one annotator leave correlated samples and annotation error. The next evidence to add is an independent label review, listening labels with music/no-music examples, a real wipe, more native portrait creator footage, and an implemented match command. The raw observations and known misses are retained for that work.
