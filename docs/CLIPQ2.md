CLIPQ2 filters vertical edits before selection, measures caption backgrounds after cropping, and removes immediate ASR repeats from displayed captions.

For 9:16 and 4:5, candidate scoring prefers time dominated by close shots. Existing face/head tracks are interpolated at the output's 30 Hz clock. A speaker-held track takes priority; otherwise the crop planner's dominant-face rule applies, with identity explicitly unverified. Equal competing faces must all qualify. Face height excludes the padding used for caption collision checks.

A shot with a face below 10% of output height, or needing more than `framing_max_upscale` to reach 10%, cannot continue for over one second. The first two seconds require 15%, including across candidate joins. Wide ranges are removed at clause boundaries; incomplete speech is dropped rather than cut mid-word. A required interval protects its entire containing clause from both exclusion and the gate. A top-level `Vertical must_keep retained` warning is emitted only when the required span remains in the pool. Protected clauses carry through the delivery recheck. An all-wide pool returns an `edit_constraints` shortage naming the vertical face-size gate. Sources with no face/head geometry remain explicitly unmeasured, so this does not certify faceless footage.

Selection uses `brief.aspect`, the plan aspect. Listing 9:16 in `brief.aspects` does not filter a shared 16:9 or 1:1 edit. Each vertical delivery checks the final crop independently; a failing adaptation rejects that shape with a vertical-quality reason.

Required enlargement is target face pixels divided by measured source face pixels. It differs from delivery enlargement. NASA's explicit 1080x1920 reframe exceeds the 2.5x delivery limit; that warning remains. The gate prevents a small face from being rescued by an additional soft punch-in.

Crop origins are clamped on both axes after interpolation, within the source/live-picture bounds. Full crops never pad to keep a face in view. Sources too small for the integer aspect crop produce an explicit size error. The NASA top strip was already present in the source: four nearly black rows and a dark transition row. For full `reframe`/`fill` crops with picture cropping enabled, three source samples now check for thin black borders. A border must occupy at most 2% of the axis, be below gray level 24 across at least 95% of each row/column, have a brighter inner boundary, and agree within one pixel across samples. Cropping steps inward to even pixels and replans the face position. Dark frames, inconsistent edges, and larger mattes stay unchanged. The removed bounds and sampling evidence are recorded in framing; the slightly higher enlargement is still disclosed.

The draft report's `vertical_quality` records shot spans, minimum face heights, required enlargement, opening checks, and candidate trims/demotions. Explicit 4:5 delivery uses even dimensions and a short side divisible by 72; the existing `all` shorthand retains its three delivery formats.

Caption backgrounds use three source-frame samples per selected shot, at 10%, 50%, and 90%, passed through the renderer's crop/blur/pad filter. No video render or detector is needed. Candidate bands stay inside delivery reserves and supplied reference masks. Face/head tracks are mapped through the crop and checked over their full observed intervals. Precise faces replace spatially matching coarse person-head proxies only over intervals with matching face evidence at both endpoints and the midpoint (at least 50% of the smaller box overlaps). Every precise face and every unmatched head interval remains an obstacle. Static captions use one band per draft; styles with moving paths retain their motion.

Clutter is the larger of `0.6 * edge_density + 0.4 * texture` and dilated strong-edge coverage. Strong edges have normalized luma gradient above 0.08. Dilation uses a radius of 2.5% of sampled frame height, across the full frame before extracting the caption band, so nearby silhouettes count even when an object's interior is smooth. Texture is mean absolute luma residual from a 5x5 blur, divided by 0.10 and capped at one. The worst sampled frame sets each score; 0.18 or less is considered clean.

A clean reference position stays. Vertical talking heads then try a band below the lowest observed chin, with 0.5% frame clearance beyond face padding. The box reserves the actual line count and the permitted strengthened outline. If that band is not clean, reference mode tries the nearest clean safe alternative. When every band is busy, the below-face band gets preference only within 0.15 of the lowest clutter score; otherwise the least cluttered safe band wins. The report discloses this preference and all candidate scores. With no safe band, planning returns a shortage.

Readability uses linear sRGB relative luminance and the tenth-percentile fill/background contrast ratio, taking the worst sampled frame. Below 4.5:1, an opposing outline is strengthened. Reference outlines are capped at 14% of em (approximately 20% of fill-ink height), punch at 7%, and clean/box at 5%, all within the 20px schema ceiling. Explicit outline overrides win. No new background plate is invented. `caption_band` reports the box, clutter components, contrast, samples, candidates, movement, and outline decision as Estimated. Sparse samples cannot establish safety on every decoded frame.

Caption cleanup runs on copied, selected words before grouping: merge an immediate case-insensitive repeat when the second word starts zero to 0.35 seconds after the first ends. Keep the first start and spelling, the second end, and any punctuation after the second word. Punctuation between tokens blocks the merge, including sentence endings and standalone punctuation. Always preserve `that that` and `had had`. Timing provenance records the display transformation. Transcript and study words stay unchanged.

Reproduce the NASA acceptance check from the saved planner inputs:

```powershell
$env:PYTHONPATH="$PWD\src"
$env:UOINK_URL='http://127.0.0.1:1'
$env:HF_HOME="$PWD\zing-workspace\hf"
$env:PATH="E:\AI\tools\ffmpeg-8.1.2\bin;$env:PATH"
..\hookcard\.venv\Scripts\python.exe tools/eval/clipq2_acceptance.py E:\AI\zing-demo-media\interview\full\project-clipq2 zing-workspace/clipq2-r1/nasa
```

This reads the saved inventory, recipe, framing tracks, exclusions, and picture evidence, runs the current planner and same-aspect delivery rebuild, and samples caption backgrounds. It writes director plans, final `plan-*-9x16.json` delivery plans, comparison data, and `acceptance.json` under the requested output directory. It does not run match, ASR, a detector, or a video render, and does not modify the source project.
