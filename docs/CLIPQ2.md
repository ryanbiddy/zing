CLIPQ2 filters vertical edits before selection, measures caption backgrounds after cropping, and removes immediate ASR repeats from displayed captions.

For 9:16 and 4:5, candidate scoring prefers time dominated by close shots. Existing face/head tracks are interpolated at the output's 30 Hz clock. A speaker-held track takes priority; otherwise the crop planner's dominant-face rule applies, with identity explicitly unverified. Equal competing faces must all qualify. Face height excludes the padding used for caption collision checks.

A shot with a face below 10% of output height, or needing more than `framing_max_upscale` to reach 10%, cannot continue for over one second. The first two seconds require 15%, including across candidate joins. Wide ranges are removed at clause boundaries; incomplete speech is dropped rather than cut mid-word. Required spans survive, with a top-level `Vertical must_keep retained` warning. The final crop is checked again after music and picture framing; a failed non-required gate returns a planning shortage. Sources with no face/head geometry remain explicitly unmeasured, so this does not certify faceless footage.

Required enlargement is target face pixels divided by measured source face pixels. It differs from delivery enlargement: NASA's explicit 1080x1920 reframe still scales the 720p source by 2.667x. That existing warning remains. The new gate prevents a small face from being rescued by an additional soft punch-in.

The draft report's `vertical_quality` records shot spans, minimum face heights, required enlargement, opening checks, and candidate trims/demotions. Explicit 4:5 delivery uses even dimensions and a short side divisible by 72; the existing `all` shorthand retains its three delivery formats.

Caption backgrounds use three source-frame samples per selected shot, at 10%, 50%, and 90%, passed through the renderer's crop/blur/pad filter. No video render or detector is needed. Candidate bands stay inside delivery reserves and supplied reference masks. Face/head tracks are mapped through the crop and checked over their full observed intervals. Static captions use one band per draft; styles with moving paths retain their motion.

Clutter is `0.6 * edge_density + 0.4 * texture`. Edge density is the fraction of pixels with a normalized luma gradient above 0.08. Texture is mean absolute luma residual from a 5x5 blur, divided by 0.10 and capped at one. The worst sampled frame sets the band score; 0.18 or less is considered clean. A clean reference position stays. Otherwise reference mode picks the nearest clean face-safe band in a two-percentage-point search grid. Other modes pick the least cluttered safe band. With no clean band, the least cluttered safe option is disclosed; with no safe band, planning returns a shortage.

Readability uses linear sRGB relative luminance and the tenth-percentile fill/background contrast ratio, taking the worst sampled frame. Below 4.5:1, an opposing outline is strengthened. Reference outlines are capped at 14% of em (approximately 20% of fill-ink height), punch at 7%, and clean/box at 5%, all within the 20px schema ceiling. Explicit outline overrides win. No new background plate is invented. `caption_band` reports the box, clutter components, contrast, samples, candidates, movement, and outline decision as Estimated. Sparse samples cannot establish safety on every decoded frame.

Caption cleanup runs on copied, selected words before grouping: merge an immediate case-insensitive repeat when the second word starts zero to 0.35 seconds after the first ends. Keep the first start and spelling, the second end, and any punctuation after the second word. Punctuation between tokens blocks the merge, including sentence endings and standalone punctuation. Always preserve `that that` and `had had`. Timing provenance records the display transformation. Transcript and study words stay unchanged.

Reproduce the NASA acceptance check from the saved planner inputs:

```powershell
$env:PYTHONPATH="$PWD\src"
$env:UOINK_URL='http://127.0.0.1:1'
$env:HF_HOME="$PWD\zing-workspace\hf"
$env:PATH="E:\AI\tools\ffmpeg-8.1.2\bin;$env:PATH"
..\hookcard\.venv\Scripts\python.exe tools/clipq2_acceptance.py E:\AI\zing-demo-media\interview\full\project-clipq zing-workspace/nasa-clipq2
```

This reads the saved inventory, recipe, framing tracks, exclusions, and picture evidence, runs the current planner and same-aspect delivery rebuild, and samples caption backgrounds. It writes director plans, final `plan-*-9x16.json` delivery plans, comparison data, and `acceptance.json` under the requested output directory. It does not run match, ASR, a detector, or a video render, and does not modify the source project.
