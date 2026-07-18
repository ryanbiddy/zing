# Sprint 1 cross-review — Lane B duty

Author: Fresh-eyes review agent standing in for Lane B's review duty (2026-07-18)

Reviewed: Lane A's study engine (`src/myzing/study/**` + tests) and Lane C's
eval harness + renderer (`tools/eval/**`, `src/myzing/render/**` + tests) on
merged `main` (bc3d264). Lane B's storage/doctor/MCP code was read only as an
integration boundary. Binding specs used: `handoff/ROADMAP.md`,
`handoff/SPRINT-1-D1.md` (§Critique resolutions), `src/myzing/schemas.py`.

## Method / gate evidence

- Read every file under review (not docs-alone review).
- `python -m pytest -q` on this Windows machine: **214 passed** (ffmpeg
  present, so the render/golden integration tests executed rather than
  skipped — that distinction is Finding 1).
- Verified the pinned definitions line-by-line against implementations:
  cuts_per_10s windowing, astats 1s RMS buckets, VAD speech ratio params,
  CFR-normalize policy, EDL S1 timeline/audio semantics, eval manifest rules.

## Findings (ranked)

### 1. [P1] The anti-slop gate does not actually gate: CI never installs ffmpeg and never runs the eval scorer

`.github/workflows/ci.yml:12-18` — the only CI job is `pip install -e .[dev]`
then `pytest -q`. Binding items violated:

- SPRINT C-1.3: "CI job runs the scorer when ffmpeg is present (**install it
  in CI**)" — nothing installs ffmpeg, and no step invokes
  `tools/eval/run.py` (neither `--sample` beyond an incidental pytest
  subprocess test, nor `--study`).
- C#8 (binding): "ffmpeg explicitly installed + **version/filters printed**,
  scorer + render golden on Ubuntu, focused Windows job" — none present.
- C#9 (binding): eval report "kept as CI artifact on failure" — no artifact
  upload exists.

Concrete failure scenario: GitHub-hosted `ubuntu-latest`/`windows-latest`
images do not ship ffmpeg. Every ffmpeg-gated test
(`tests/test_render_integration.py:18-21`, the golden-generation test in
`tests/test_eval_runner.py:146-149`) then `skip`s silently, and CI is "green"
while the C-2 content-probe oracle and golden generation have never executed
on a merge. Separately, even where ffmpeg exists, nothing in CI or pytest
ever runs the study→score pipeline end-to-end (`run.py --study` is
manual-only; all pytest study tests mock every stage), so a Lane A
measurement regression (e.g., a threshold change that halves detected cuts on
the goldens) merges green. The status line "Ubuntu+Windows CI green" is
currently evidence about mocked unit tests only.

Ownership nuance: `ci.yml` was scaffolded by the orchestrator and is not in
any lane's owned paths, but C-1.3 assigned the CI wiring to Lane C and it
never landed anywhere.

Fix: S — add ffmpeg install (apt / choco or setup-ffmpeg action), print
`ffmpeg -version` + `-filters`, add a step running
`python -m tools.eval.run --sample` always and `--study` behind a label or
nightly (needs `[study]` extras), upload `eval-report.json` on failure.

### 2. [P2] VFR gate hole: mildly-VFR H.264 passes ingest untouched, silently violating the pinned PTS rule

`src/myzing/study/ingest.py:35` (`_VFR_TOLERANCE = 0.02`) and
`ingest.py:195-210` (`_needs_normalize`). The VFR test compares only
`avg_frame_rate` vs `r_frame_rate`. A phone/TikTok-style avc1 file with
dropped frames (declared 30/1, avg 29.93 — 0.23% mismatch) passes the h264 +
<2% gate, so it is NOT CFR-normalized. Downstream, shot times
(PySceneDetect: frame_index/framerate, `shots.py:68-86`) and OCR sample times
(`captions.py:247-273`, `frame_index / fps`) are frame-index-derived, while
word/VAD times decode true PTS audio. schemas.py pins "all timestamps derive
from container PTS, never frame indices" — the implementation relies on CFR
normalization to make frame-index time equal PTS time, and this gate lets
non-CFR files through with **no warning recorded**.

Concrete failure scenario: a 60s TikTok with bursty frame drops
(avg-vs-declared under 2%) — cut timestamps drift vs the transcript by up to
`duration × mismatch` (≈0.14s at 0.23%, up to ~1.2s at just-under-2%); the
eval's own cut tolerance is ±0.15s. The breakdown then asserts "word lands on
the cut" relationships that are false, with nothing in `warnings`.

Fix: M — either (a) spot-check packet PTS monotonic spacing via
`ffprobe -show_entries packet=pts_time` on a sample window and normalize when
spacing variance exceeds a bound, or (b) keep the cheap gate but append a
warning whenever avg≠declared at all ("timestamps assume CFR; residual VFR
risk X%"), and tighten `_VFR_TOLERANCE` toward the 0.15s eval budget.

### 3. [P2] Stale keyframe cache: re-study attaches old frames to new shot boundaries

`src/myzing/study/keyframes.py:58-60` — `_grab()` returns True if the target
file already exists, and the filename is keyed by shot **index**
(`shot_001.jpg`), not by timestamp. This reuse is even locked in by
`tests/test_study_keyframes.py:56` as intended behavior.

Concrete failure scenario: a slug is re-studied after anything shifts shot
boundaries — scenedetect version upgrade, `ADAPTIVE_THRESHOLD` retune in S2,
or first-run-without/second-run-with scenedetect. New shot 1 starts at 2.0s;
`frames/shot_001.jpg` still holds the frame grabbed at the old 4.2s start.
`Shot.keyframe` now points at an image that is not the first frame of the
shot — the judgment AI "sees" the wrong shot with no warning. Keyframes are
Lane A's answer to critique A#2 ("give the judgment AI eyes"); stale eyes are
worse than none.

Fix: S — drop the `target.exists()` short-circuit (ffmpeg is already called
with `-y`; re-extraction cost is trivial), or key filenames by timestamp.

### 4. [P2] Caption OCR fails closed to zero captions with no warning when the backend returns no scores

`src/myzing/study/captions.py:287-313` (`_ocr`). `scores` is defended with
`scores or [0.0] * len(txts)` — if a rapidocr version/API variant returns
`scores=None`, every line gets score 0.0, falls below `CONF_THRESHOLD`
(0.75), and is dropped. Same shape of failure if the output object stops
exposing `.boxes`/`.txts` (returns `[]` per frame). Either way the study
reports `captions: []` and `breakdown.md` prints "no on-screen text observed"
— a measurement that silently guessed "no captions" instead of recording
uncertainty, violating the warnings contract in schemas.py:124-127.

Concrete failure scenario: rapidocr minor release changes the result API (it
did between 1.x and 3.x); every studied video suddenly reports zero captions
while `warnings` stays clean, and the judgment AI concludes the creator uses
no on-screen text.

Fix: S — count frames where raw OCR output was non-empty but everything was
filtered (or the adapter saw no `.scores`), and append one warning; also
treat `scores=None` as "confidence unavailable" (keep lines, set a low
confidence) rather than 0.0.

### 5. [P2] Cut scorer conflates "missing" and "extra" cuts into fabricated out-of-tolerance pairs

`tools/eval/scoring.py:102` — after maximum in-tolerance matching, leftovers
are `zip`ped positionally: `out_of_tolerance = list(zip(unmatched_truth,
unmatched_predicted))`. C#3 (binding) requires "missing/extra/out-of-tolerance
reported **separately**".

Concrete failure scenario: truth cuts `[1.0, 2.0]`, predicted `[1.0, 5.0]`.
The report claims truth 2.0 was "matched" to predicted 5.0 with delta 3.0s
(within_tolerance=false), instead of reporting `missing: [2.0]`,
`extra: [5.0]`. Overall pass/fail is unaffected (both fail timing), but the
per-event diagnostics — the whole point of the machine-readable report — lie
about what happened, and A-Q2's ongoing eval iteration reads those deltas.

Fix: S — only pair leftovers when they at least fall within some sane
proximity window (e.g., nearest-neighbor within 2-3× tolerance); otherwise
report them as missing/extra.

### 6. [P3] Renderer caption geometry is hard-coded to 9:16 and mis-places captions on any other aspect

`src/myzing/render/captions.py:10-27` — `SAFE_BOX_1080X1920` and
`POSITION_Y_1080X1920` are scaled by `width/1080` and `height/1920`
regardless of actual aspect. `validate_edl` happily accepts landscape
dimensions. Concrete: an X/long-form 1920x1080 EDL puts "bottom" at y=657
(61% of frame height) and the x anchor at 43.7% of a 1920px width — captions
float high and markedly left of center. S1 is vertical-first, so this is
P3, but the renderer should be honest: warn (or error) when the EDL aspect
is not ~9:16 rather than silently applying vertical-safe-zone math. Fix: S.

### 7. [P3] Word-timed captions strobe: screen goes blank between consecutive word timings

`src/myzing/render/captions.py:94-118` — each word is an SSAEvent spanning
exactly `[word.start, word.end]`. Whisper word timings routinely leave
100-400ms gaps between words; during each gap no caption is on screen, so
real voiceover captions flicker instead of holding, which no short-form
pop-caption style does. Concrete: any EDL built from measured `Word[]` (the
D-3 path). Fix: S — extend each word event to the next word's start (or the
caption end), keeping the pop/karaoke tags.

### 8. [P3] `study()` workspace override mutates process-global env — a landmine under the threaded MCP surface

`src/myzing/study/api.py:126-141` — `_workspace_override` sets/restores
`ZING_HOME` in `os.environ`. Today no threaded caller passes `workspace`
(Lane B's `study_video` worker thread calls `study(source)` bare; the eval
adapter is single-threaded), so this is latent. But the API invites
`study(source, workspace=...)` from anywhere; two concurrent calls with
different workspaces (or one against a concurrent `zing_status` reading
storage paths) cross-contaminate workspace roots mid-study. Fix: M — thread
the workspace through storage calls explicitly (parameter or contextvar)
instead of env mutation; at minimum document the constraint on the seam.

### 9. [P3] Eval matcher recursion will blow the stack on real-video-scale event lists

`tools/eval/scoring.py:69-78` — `visit(i, j)` recurses with depth up to
`len(truth) + len(predicted)`. Fine for 2-cut goldens; the moment scored
fixtures approach ~500+ events combined (a few minutes of fast-cut long-form,
which A-Q4 explicitly targets), scoring dies with RecursionError. The frozen
`raw-editing-practice` fixture already has 34 shots. Fix: S — iterative DP
table.

### 10. [P3] Smaller items, one line each

- `src/myzing/study/ingest.py:146-153`: `_stage_local` reuses staged media on
  a size-only match — same-size-different-content edits at the same path
  (with identical first-1MB slug hash) study stale media. Very low
  probability; note only.
- `src/myzing/study/captions.py:259-272`: `_iter_frames` returns silently
  when frames run out before the schedule ends (container duration
  overstated) — the unobserved tail is not warned, unlike every other
  degradation in the module.
- `src/myzing/render/pipeline.py:184-188`: `os.replace` publish fails on
  Windows when `--keep-work` is on a different drive than the output — the
  full render completes, then errors. Honest (RenderError) but wasteful;
  `shutil.move` fallback is a one-liner.
- `src/myzing/render/validation.py:149-153`: words must be strictly
  non-overlapping — faster-whisper occasionally emits overlapping word
  timestamps, so D-3 EDLs built from measured `Word[]` will hard-fail
  validation until the producer sanitizes. Correct S1 behavior (fail loudly),
  but flag it now for the D-2/D-3 spec: sanitization belongs upstream.
- `tools/eval/run.py:195-228`: bare `python -m tools.eval.run` silently means
  `--sample`; worth an explicit line in `--help`/output so a human doesn't
  mistake a sample pass for a live-study pass.

## Contract-compliance spot-checks that PASSED (verified in code, not docs)

- cuts_per_10s: non-overlapping windows from t=0, boundary cut counts in the
  later window, trailing partial raw, skip vs zero-cut distinguishable
  (`shots.py:97-113`, boundary test at `test_study_shots.py:105`).
- Loudness: astats mean RMS dBFS in exact 1s buckets via
  `aresample=48000,asetnsamples=48000` with -inf floored to a JSON-safe -99,
  AAC padding bucket trimmed, partial final second kept (`audio.py:101-143`).
- Speech ratio: VAD spans / video duration, upstream-style Silero params (not
  transcription defaults), clamped, honest None-vs-empty distinction
  (`audio.py:146-177`).
- has_music: never a bare guess — every branch carries `music_confidence`
  and inconclusive branches warn (`audio.py:183-219`).
- EDL S1 semantics in the renderer: overlap error, gap error, clip audio at
  unity, tracks play once / silence-padded / never looped / trimmed at output
  end, ducking only music-under-voiceover, 48kHz stereo, silent track when no
  audio inputs, no loudnorm (`validation.py`, `graph.py`; content-probe
  integration test measures actual duck depth 6-12dB).
- Eval manifest: normalization exactly as declared, one-to-one chronological
  matching, recall + per-event similarity + extras penalized, raw deltas
  beside every verdict, tolerances absent from truth files, speech-ratio
  scoring honestly disabled ("tone is not speech"), fault matrix with ≥1
  targeted mutation per scored dimension asserting isolation.
- ffmpeg discipline: argv lists everywhere, `-filter_complex_script` files,
  every leg normalized before concat, fixtures with spaces and apostrophes in
  paths on both lanes.
- Freeze/provenance work (`freeze_real_videos.py`) is exemplary: hashes,
  environment, normalizations, refusal to overwrite frozen fixtures, and the
  truth-caveat honesty about the not-actually-raw second video.

## Top 5 summary

1. P1 — CI never installs ffmpeg or runs the scorer; the C-1 anti-slop gate
   and C-2 render oracle do not gate merges (ci.yml:12-18).
2. P2 — 2% avg-vs-declared VFR gate misses locally-VFR H.264; frame-index
   timestamps then silently violate the pinned PTS rule beyond the eval's own
   ±0.15s (ingest.py:35,195-210).
3. P2 — keyframe cache serves stale frames after shot boundaries shift on
   re-study; the judgment AI sees the wrong image (keyframes.py:58-60).
4. P2 — OCR adapter drops all text with no warning when the backend omits
   scores; "no captions" becomes a silent guess (captions.py:287-313).
5. P2 — cut scorer zips leftover missing/extra cuts into fake
   out-of-tolerance pairs, corrupting the per-event report the fix loop
   depends on (scoring.py:102).
