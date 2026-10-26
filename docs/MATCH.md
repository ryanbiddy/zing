# Match a reference with your clips

Source timing uses the [confirmed source map](SOURCE-MAP.md). Public study
shots remain unchanged; extra planning cuts carry frame evidence and confidence.

```sh
zing match reference.mp4 --clips ./clips --out ./zing-workspace/match --answers '{"target_length_seconds":6,"aspect":"16:9"}'
zing match reference.mp4 --clips ./clips --out ./zing-workspace/match --resume --json
zing plan choose ./zing-workspace/match --draft B
```

Use `--brief brief.json` for a saved versioned brief, or `--answers` for the same
fields accepted by `zing brief new`. With neither, a terminal starts the existing
interview; scripts must supply answers or resume a saved brief. Defaults are
up to three drafts and seed 0. Fewer drafts are delivered when the footage cannot
support distinct edits, with a **VARIETY** warning naming the missing drafts.
The `--drafts` request remains 3; Zing never duplicates an edit to fill the slots.

References can be local files, `uoink:<id>`, or URLs. A URL needs the explicit
`--allow-download` flag before study's acquisition runs. Verified Uoink kept
media stays local; an unavailable peer or missing retained file is a named
failure, with no URL fallback. Match never downloads models. Provision needed
assets explicitly before running it.

Match checks FFmpeg/ffprobe, readable local reference and clips, brief/target,
explicit `framing=reframe` face weights, speech when any input has audio, and
output space before study. It reports one PREFLIGHT shortage with every detected
problem and its fix. Metadata probes time out after two seconds per file; large
folders take longer. URL/Uoink references get their audio check after acquisition,
still before study. Output space is estimated from the inputs (about four times
the source sizes plus 64 MB): less than the sources plus 16 MB is refused, and
less than the estimate is a warning. This is an estimate, not a quota.
OCR, color, audio tagging, font matching and automatic face analysis are optional;
missing measurements have disclosed fallbacks. `framing=fit` needs no face model.

Choose speech once with `zing doctor --speech-model small.en --yes` (English),
`large-v2` for multilingual speech, or `skip` to omit speech processing. Doctor,
setup and Studio save successful choices in `$ZING_HOME/speech.json` (default
`~/.zing/speech.json`). Study, match, Studio and MCP use `ZING_WHISPER_MODEL` first,
then the saved choice, then cached `large-v2`, then cached `small.en`. An explicit
Studio run choice replaces the saved choice for that run; the environment still
wins. Missing selected weights produce a command naming that model. No inference
path downloads weights.

Caption placement moves text and regroups words at one draft font size. Only an indivisible word can lower the size for the whole draft. The floor is 24 output
pixels for reference clauses; phone mode uses the documented picture-relative
minimum in [Studio](STUDIO.md). If subject avoidance cannot preserve readable
text, generated drafts use an inset high-contrast plate and disclose possible
subject overlap. Text still has to pass the renderer's ink-fit check. A refusal
names the caption, measured ink, available box and minimum size. Style fidelity
remains measured and reported separately from render completion.

The pipeline inventories clips, studies the reference with caption geometry,
available font candidates and experimental transitions, and studies each clip
in raw mode. It builds a reusable StyleRecipe, keeps each clip's source color by default,
measures audio, saves the brief, and asks the existing director for A/B/C.
It renders with the public v2 API, fully decodes each output, studies the rendered
file again, and writes a timeline PNG and match report.

Outputs in the project folder:

- `recipe.json`, `brief.json`, `project.json` and `match-state.json`.
- `drafts/plan-A.json`, `drafts/draft-A.mp4`, `drafts/draft-A.png` and
  `drafts/draft-A.match.json`, likewise B/C; decode receipts include SHA-256.
- `comparison.md` and `comparison.json`, with the actual ready count and failures.
- `director/comparison.json`, retaining planned values and shortages separately.
- `logs/`, reference/clip/output studies and audio maps; color recipes/LUTs only in reference color mode.

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

Reports compare the reference, the selected plan and the rendered file separately.
`pass` means the measured dimension is inside its band; `approximate` remains
unverified. `miss` names a difference outside the band. Two further statuses keep
measurement limits and footage constraints visible:

- `detector_disagreement`: the source-mapped plan meets the band, but the rendered
  detector disagrees about timing or cut events. Both numbers and unmatched event
  times are saved. This is neither a style miss nor a certified pass.
- `not_applicable`: the selected footage cannot support this target while keeping
  protected speech clauses whole. The report says **not applicable for this
  footage**, retains the target and measurements, and explains the constraint.
  A different opening may still be possible; this is not proof that the entire
  clip pool is unsuitable.

Shot pace and first cut use reference-derived ranges. Their half-width is half
the reference shot-length IQR plus the larger of 0.25 seconds or 20% of the target.
Quartiles use inclusive linear interpolation; one shot supplies zero spread.
The half-width is capped at the larger of 0.25 seconds or half the target, so
for targets of 0.5 s or more a band never extends past 0.5–1.5 times the target.
Shot lengths are heavy-tailed: without the cap, a montage mixing 0.4 s cuts
with 6 s holds had a 0–2.2 s band around its 1 s median, which passed drafts
cut at a third or double the reference pace. Below a 0.5 s target the 0.25 s
floor applies and the lower edge stops at zero. This is a documented editorial policy, not a
perceptual confidence interval. Reports say how many seconds the observation is
shorter or longer than the band. A continuous reference has no first-cut timing
target; the presence of cuts is compared separately. Missing detection stays
unmeasured.

For example, the NASA audit reference has a 0.800 s median and a 0.267 s IQR:
its pace and first-cut bands are 0.4165–1.1835 s. A 0.467 s opening is inside;
a 3.057 s opening is outside. If that longer opening is a protected continuous
speech clause with no natural cut inside the band, first cut is not applicable.
Pace abstains only when a majority of the selected shots contain uninterrupted
protected clauses longer than the band's upper edge. Speech over existing
montage cuts is judged shot by shot: it remains applicable when those picture
cuts keep each speech piece inside the band, and abstains only when the pieces
between them are themselves longer than the upper edge. Speech elsewhere in a
draft cannot excuse a non-speech opening.

The director constrains both openings and pace with these same bands during
candidate generation, beam pruning and selection of the three drafts. It tries
a complete in-band trio before considering fallbacks. New trims can move through
silence around natural cuts, but cannot split protected clauses. New band-edge
trims sit one 30 fps delivery frame inside the band to allow for frame rounding.
An initial A that already honors both bands is retained when the expanded search
can complete a distinct in-band trio around it.
Caption timing and opening variety cannot outweigh timing feasibility. Music
snapping also rejects trims that move either timing dimension farther outside
its band.

If the bounded search finds in-band edits but fewer than three meaningfully
distinct ones, it keeps every distinct in-band edit, most different first, even
when two are similar ("B and C are similar because the footage allows few
in-band openings"). Each remaining draft is the most different edit left, even
outside the bands, and is labeled `C: alternative outside the reference timing:
<reason>` in the plan notes, the director's and match's `comparison.json`
(`alternatives`, and `alternative` on each delivery row), `comparison.md`, the
MCP results and studio's finish table. An alternative never counts as a style
pass, and studio's pick prefers in-band drafts. A draft is never a duplicate:
edits that land on the same 30 fps frames are one edit, and when no further
distinct edit exists fewer drafts are delivered with the reason
(`missing_drafts`). Without a measured reference band nothing is relaxed, so
unmeasured timing still requires three distinct drafts or a named shortage.

Outside-band drafts are ranked by the number of timing violations, then total
seconds outside the bands. Selection evidence records the distances, completed
choices examined, and the number of distinct jointly in-band choices found. A
fallback says **outside band because** and identifies its natural cut or
whole-clause/duration constraint. It says whether the draft is the closest
completed edit found, or whether closer edits existed but could not form three
meaningfully distinct drafts. Planned
values and reasons describe the final edit after music snapping; when snapping
moved a timing value, the reason gives both numbers.
This is a search result, not proof that no human edit of the footage could work.
The reason appears in the match JSON and `comparison.md`, including when the
dimension is not applicable for the selected footage.

Frame accuracy remains a separate renderer check. Match's rendered-video study uses a two-frame minimum
shot length, keeping the adaptive detector's content and ratio thresholds.
The generic study default remains 0.3 s for unknown media. That default can
suppress legitimate 5–7-frame shots when verifying an assembled edit; it caused
the audit's 0.800 s plan to measure 0.967 s. A lower floor can also expose false
events, so matching medians alone never establish detector agreement. The
two-frame event-alignment allowance is solely a detector comparison precision,
not the old first-cut style window.

Color sampling crops the sharp picture **before downsampling**, using each
clip's framing geometry and output frame interval. It excludes blurfill and
zoomfill bands, fit letterboxing/pillarboxing, and source mattes recorded in
the framing bounds. Cropped pictures fill their own measurement area. Overlaps
use the common sharp rectangle; an empty intersection is a disclosed sample gap.
Edges next to a recorded matte step two pixels inside it, because scaling and
4:2:0 chroma blend the matte into the neighboring rows. If every sample is a
gap, color is unmeasured (`approximate`, with that reason); the delivery is not
failed and nothing passes.
Reports record each region and sample rectangle. Unrecorded baked-in bars cannot
be inferred from a plan that declares the whole source as picture.

`--color source` is the default: each clip keeps its own color, no color fit runs,
and no LUT is applied. Use `--color reference` to fit each source to the reference
grade. The recipe, match result and comparison report record `color_mode`;
source mode marks color matching not applicable. Changing modes with `--resume`
invalidates the recipe and downstream plans and reports.

Sparse OCR cannot certify one-frame switches or ASR accuracy. In reference color mode, color compares
CIELAB lightness, mean a*/b* cast, chroma, contrast and tonal cast on the sharp
picture. Each component has an inner pass band and an outer miss band; values
between them stay approximate. A miss in any component makes color miss. A pass
requires all measured components inside their inner bands, at least four usable
samples per input, complete requested/shot coverage and confidence at least 0.5.
Legacy luma-only, missing, sparse or low-confidence matching evidence cannot pass.
The report retains the luma delta for audits, but it does not determine status.

Scene content is not the grade. Each report measures how much each video's own
sampled shots differ; a component that exceeds its miss limit by less than two
standard errors of that shot-to-shot variation is approximate ("Scene content
differs"), not a miss. That allowance never turns a difference into a pass. A
one-shot reference and a one-shot draft of different scenes can still miss, so
inspect the crops before attributing a difference to grading. Per-component
deltas explain the direction and size of each difference. See
[color calibration](color.md#color2-match-report-bands) for thresholds and fixtures.
These are unpaired scene statistics, not paired Delta E or original-LUT recovery.

Skin is never compared with the reference. The reference's people and the
draft's people are different people under different light, so their skin says
who is on screen, not how the draft was graded, and judging one person's skin
tone against another's is wrong. Instead, `skin_preservation` is a separate
dimension: for each graded clip, faces found in the ungraded source frames are
measured on the same pixels before and after that clip's own LUT. Pass requires
hue shift <=2.5, retained chroma >=0.80 and lightness drop <=6 L*. Hue shift >5,
chroma ratio <0.65 or lightness drop >12 makes a miss; other cases are approximate.
The report lists all three components and which decided. A skin miss is also a
top-level match warning and appears in the comparison report. It does not change
the separate reference-color dimension. No detector, no faces, or no grade leaves it
unmeasured or absent, never passed. See [skin preservation](color.md#skin-preservation).
“Ready” means playable and reported; it does not mean every style dimension passed.

`comparison.md` includes abstentions, disagreements and their reasons. JSON has
`not_applicable_style_dimensions`, `detector_disagreements` and `style_notes` for
finish-screen consumers; only `miss` enters `failed_style_dimensions`.
`zing studio` ranks drafts by measured misses, then measured passes. Not
applicable, detector disagreement, approximate and unmeasured color count as
neither. Its finish screen prints one line per draft naming them (for example
`Draft B (16:9, 1:1): shot pace detector disagreement.`), and when the
recommended draft has any, the "Start with draft X because ..." line lists them
as not passes. A studio run without a reference uses its pace choice as a search
preference, never as a reference band.

Over MCP, call `match_start(reference, clips, out, answers=..., resume=..., color="source")` and
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

## Long interviews

For a 30-90 minute interview, let match study it once. Its
`long_source_needs_moment` shortage preserves those checkpoints:

```sh
zing match reference.mp4 --clips ./clips --out ./project --answers '{"target_length_seconds":22}'
zing moments ./clips/interview.mp4 --workspace ./project --target 22 --top 3 --json
```

Review the suggestions, copy one `must_keep` array into `project/brief.json`,
then rerun the same match command with `--resume` instead of `--answers`.
`zing moments` also accepts a study slug or `breakdown.json` from an earlier
`zing study <clip> --raw` run. It never transcribes or calls a model.

Suggestions include start/end, text, score and reasons, labeled **Estimated**.
Windows start on complete clauses and last 65-100% of the target. Scores weight
speech density (50%), length fit (30%), question/number/contrast cues in the first
clause (10%), keeper coverage (5%) and shot coverage (5%). Measured dead air,
word gaps of at least 600 ms, incomplete clauses and repaired timings are excluded.
Every window must be fully covered by observed shots; even sub-second shot gaps
are excluded, while abutting shots can form one window. Clips without transcript
words, including silent title slates, have no suggestions. In a project, copied
`must_keep` entries use the inventory ID for both relative and external media paths.
Results do not overlap; sparse evidence may yield fewer than requested. Semantic
quality and ASR accuracy remain unverified.

Above 2,400 candidate trims, a must-keep focuses search from its first start minus
1.5 times the target to its last end plus 1.5 times the target, snapped outward to
clause/shot boundaries. Forbidden ranges still apply; short clips keep their
existing search. Search uses one window spanning all must-keeps, including the
time between them. Plans and reports label the interval **Measured** and say
"Search focused on ... in one window around your must-keep moment; the whole
interview was not searched." For several keeps, the wording says "all your
must-keep moments, including the time between them." If snapping reaches both
clip edges, it instead says "Search window spans the full clip (...) to include
...; snapping did not narrow the search." A window that still exceeds 2,400
candidates returns `planner_capacity`: move or drop a must-keep, or split the job
into separate briefs. No moment is automatically selected. A planned span with
no transcribed speech and one observed shot carries a warning to review for a
possible static title slate.

Audio/video drift up to 250 ms is accepted and disclosed. Excess audio is clipped;
an uncovered video tail stays unmeasured. Above ten minutes, match skips its
optional audio map and reports that limit; the raw study still supplies transcript
and dead-air evidence.

Draft selection checks candidate spans for visible faces/heads before choosing
an edit. When faces occur elsewhere in the analyzed source, a measured absence
lasting at least one second excludes overlapping candidates. Text-heavy graphics
or large scene text without a face also exclude candidates. The director records
`visual_selection` with rejected spans and candidate count. The same spans
constrain later music adjustments. Analysis covers the candidate union and eight
short source anchors; sparse samples and missing detectors remain unmeasured.

`zing moments` starts at an answer sentence after a question, or drops the question
candidate. It also drops obvious question openings when ASR omitted the question
mark. Suggestions end at sentence punctuation, keep the existing timing and
exclusion checks, and include `first_sentence` in JSON. A punctuation-based
boundary is an editing aid, not a semantic-quality guarantee.
