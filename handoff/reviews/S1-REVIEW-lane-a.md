# Sprint 1 cross-review — Lane A duty (Lanes B + C)

Author: Fresh-eyes review agent standing in for Lane A's review duty (2026-07-18)

Scope: MERGED code of Lane B (`src/myzing/storage.py`, `doctor.py`,
`mcp_server.py`, `prompt_pack.py`, `uoink_bridge.py`, `prompts/`, their
tests) and Lane C (`src/myzing/render/**`, `tools/eval/**`, their tests),
reviewed against the binding specs: `handoff/ROADMAP.md`,
`handoff/SPRINT-1-D1.md` §Critique resolutions, `src/myzing/schemas.py`.
Every finding below was verified by reading the merged source, not docs.
Lane A study code was read only where a seam required it (`study/api.py`,
`ingest.py`, `captions.py` import surfaces).

Where a finding overlaps `S1-REVIEW-lane-c.md` it is marked **[overlaps
C#n]** — independent rediscovery is signal for the fixlist, not noise.

Severity: **P1** = fix before S1 closes · **P2** = fix sprint · **P3** =
queue/note. Fix size: S (< 1 h), M (half day), L (day+).

---

## P1 — fix before S1 closes

### 1. CI never exercises the ffmpeg-gated suites; C#8/C#9 are unimplemented (Lane C / CI)

`.github/workflows/ci.yml:1-18` — the entire workflow is checkout →
setup-python → `pip install -e .[dev]` → `pytest -q`. There is **no ffmpeg
install step, no version/filters printout, and no failure-artifact
retention**, all three of which are binding (SPRINT-1-D1 §Critique
resolutions C#8, C#9: "ffmpeg explicitly installed + version/filters
printed, scorer + render golden on Ubuntu, focused Windows job for
paths/ASS/render smoke"; "machine-readable report … kept as CI artifact on
failure").

Concrete failure: every test in `tests/test_render_integration.py` (the
whole C-2 content-probe oracle: pixel probes, duck-depth, ASS inspection,
end-to-end `zing render`), plus `test_make_three_real_goldens_with_hostile_paths`,
is guarded by `skipif(ffmpeg missing)`. windows-latest runners ship no
ffmpeg, so the "focused Windows render smoke" has never once run in CI;
on ubuntu the suite runs only if the runner image *incidentally* contains
ffmpeg, unpinned and unprinted — exactly the ambiguity C#8 was written to
forbid. A renderer regression (e.g. a filtergraph typo in `graph.py`)
would merge green today.

Note for the orchestrator: `git log --follow .github/workflows/ci.yml`
shows the file untouched since the scaffold + Phase-0 commits, while
`handoff/NOTES-lane-c.md` (2026-07-18 orchestrator entry) records that
"#24 shipped it green on both OSes" with ffmpeg install/probes. The
workflow steps either never landed or were lost; either way the merge
gate for Lane C's paths is currently self-certification on developer
machines. **Fix: S–M** (add ffmpeg install per-OS, print
`ffmpeg -version` + `-filters`, run `tools/eval/run.py --sample` plus the
render suite, upload `eval-report.json` on failure).

### 2. Doctor's OCR verdict disagrees with the pipeline it vouches for (Lane B)

`src/myzing/doctor.py:188-217` (`check_ocr`) reports `ok=True` for any of:
module `rapidocr_onnxruntime`, module `rapidocr`, or a `tesseract` binary.
But the actual study pipeline imports exactly one backend:
`src/myzing/study/captions.py:242` — `from rapidocr import RapidOCR`.
There is no tesseract code path anywhere in `src/` and no
`rapidocr_onnxruntime` fallback.

Concrete failure: `pip install rapidocr-onnxruntime` (the older, very
widely installed package) or a machine with tesseract on PATH → `zing
doctor` prints `[ok] ocr` → every `zing study` emits "caption OCR
skipped: rapidocr/onnxruntime not installed". Doctor says healthy, the
product degrades — a direct violation of the doctor honesty contract
(B#5: "named degraded modes", "detect it honestly … never assume").
`tests/test_doctor.py:134-142` currently *enshrines* the tesseract lie
(`test_tesseract_counts_as_ok_but_recommends_rapidocr` asserts `ok is
True`). **Fix: S** — check importability of `rapidocr` only; report
tesseract/rapidocr_onnxruntime as found-but-not-wired ("Zing's OCR uses
the `rapidocr` package; install myzing[study]"), and fix the test.

### 3. Crash states are not honest: "running" survives server death forever (Lane B) [overlaps C#4]

`src/myzing/mcp_server.py:209-238` (`h_get_breakdown`) and `:296-320`
(`h_zing_status`) trust `status.json` verbatim. Job liveness lives only in
the in-process `_JOBS` dict (`:50`), which nothing consults when reporting
state. The B#2 ruling's whole point was "a status file in the slug dir
keeps crash states honest."

Concrete failure: Claude Desktop restarts (or the machine reboots) while a
study runs → the worker thread dies with `status.json` still
`state=running` → in the next session `get_breakdown(slug)` answers
"still studying — poll again shortly" **forever**, and `zing_status()`
lists a phantom running job. The AI will dutifully poll a corpse. **Fix:
S–M** — in `h_get_breakdown`/`h_zing_status`, a `running` status whose
slug has no live thread in `_JOBS` is reported as
`interrupted — call study_video again` (or auto-marked failed at server
startup).

### 4. `get_breakdown` serves stale measurements as `ready=true` during/after re-study (Lane B) [overlaps C#2]

`src/myzing/mcp_server.py:212-224` — status is only consulted in the
`except FileNotFoundError` branch. If a slug already has a
`breakdown.json` and a re-study is `running` (or has `failed`),
`load_breakdown` succeeds and the handler returns the **old** breakdown
with `ready=true` and no state annotation.

Concrete failure: re-study a video after installing whisper; poll
`get_breakdown` a second too early → the AI receives the old wordless
breakdown flagged ready, judges it, and writes a judgment against
measurements that are about to be replaced. **Fix: S** — when a status
exists with `state != done`, include `state`/`phase`/`stale: true` in the
envelope (or return `ready=false` while running).

---

## P2 — fix sprint

### 5. Doctor never checks scenedetect — "Ready." on a machine that measures zero shots (Lane B)

`src/myzing/doctor.py:245-252` (`run_checks`) covers ffmpeg, yt-dlp,
faster-whisper, OCR, uoink. Lane A's shot detection — the single most
load-bearing measurement (shots drive `avg_shot_duration`, `cuts_per_10s`,
keyframes, the eval cut score) — requires `scenedetect`
(`src/myzing/study/shots.py:72`), which doctor never mentions.

Concrete failure: `pip install myzing` + ffmpeg on PATH → `zing doctor`
prints "Ready." → `zing study` returns a breakdown with 0 shots and a
warning. The breakdown is honest; the doctor was not. **Fix: S** — add a
recommended-tier scenedetect check with its degraded mode ("no cut
detection: single-shot breakdown, pacing metrics empty").

### 6. `study_video` validates one path and dispatches another; URL preflight skips yt-dlp (Lane B)

`src/myzing/mcp_server.py:133-137` validates local files with
`Path(source).expanduser().is_file()` but passes the **raw** string to the
engine, and Lane A's `_stage_local` does not expanduser
(`src/myzing/study/ingest.py:147-149`).

Concrete failure: `study_video("~/Videos/take1.mp4")` → cheap validation
passes → `{ok: true, status: "started"}` → job fails seconds later with
"no such file: ~/Videos/take1.mp4". The tool said yes then failed on the
exact condition it claimed to have checked. Also: for URL sources the
"cheap validation" (B#2: "missing required tools → immediate honest
error") never checks yt-dlp, so a URL on a yt-dlp-less machine gets
`ok/started` followed by an async ToolMissing failure instead of the
immediate honest error the ruling requires. **Fix: S** — expanduser once
at the top and use the expanded string for validation, slug, and
dispatch; preflight `shutil.which("yt-dlp")` when `is_url`.

### 7. Doctor cannot see a live uoink helper that 404s GET / (Lane B)

`src/myzing/doctor.py:222-226` intends `200 <= resp.status < 500` to count
as reachable, but `urllib.request.urlopen` raises `HTTPError` for every
4xx, and `HTTPError` is a subclass of `URLError`, which the `except`
swallows as unreachable (verified: `issubclass(HTTPError, URLError) is
True`). The `< 500` branch is dead code — only 2xx/3xx ever reach it.

Concrete failure: a uoink helper that serves `POST /notes` but returns
404 on `GET /` (typical API-only server) → doctor reports "no uoink
helper at …" while `push_to_uoink` works fine. **Fix: S** — `except
HTTPError as e: reachable = e.code < 500` before the generic handler.

### 8. Bridge misdiagnoses a malformed 200 response as "helper not running" (Lane B)

`src/myzing/uoink_bridge.py:100-107` — `json.loads(resp.read())` raising
`ValueError` is caught by the same clause as connection refusal and
reported as "no uoink helper at … — is Uoink running?".

Concrete failure: uoink answers 200 with an HTML error page or truncated
body → the user is told the helper isn't running when it demonstrably
answered. Wrong diagnosis, wrong fix path. **Fix: S** — separate the
`ValueError` catch: "uoink answered but returned unparseable JSON — is
your uoink up to date?".

### 9. Doctor's yt-dlp verdict and fix command don't match the pipeline or the extras (Lane B) [overlaps C#3]

`src/myzing/doctor.py:126-161` accepts the `yt_dlp` *module* as healthy,
but ingest execs the `yt-dlp` *binary* (`src/myzing/study/ingest.py:121`),
and the printed fix `pip install "myzing[study]"` does not install yt-dlp
at all — the `[study]` extra (`pyproject.toml`) is scenedetect +
faster-whisper + onnxruntime + rapidocr. Module-only machines pass doctor
and fail URL ingest; users who run the printed fix stay broken. **Fix: S**
(doctor: require the binary or make the fix text truthful; pyproject: add
yt-dlp to `[study]` — orchestrator-owned file, propose via notes).

---

## P3 — queue / notes

### 10. Scorer matcher recurses per event — RecursionError on real-video density (Lane C)

`tools/eval/scoring.py:54-78` — `_best_monotonic_pairs.visit(i, j)`
recursion depth grows with `truth_count + predicted_count`, and each
cached state materializes pair tuples (O(n·m) states × O(n) tuples).
Fine for 2-cut goldens; but the frozen real-video fixture already has 34
shots, and the S2 direction is scoring caption-dense multi-minute videos
— ~500 truth + 500 predicted events exceeds Python's default 1000-frame
recursion limit and the memory profile grows cubically before that.
Concrete failure: point the scorer at a caption-per-word 3-minute video
and it dies in `visit()` instead of scoring. **Fix: M** — iterative DP
(store choice matrix, backtrack), same manifest semantics.

### 11. `_score_cuts` pairs leftovers by index — misleading "out-of-tolerance" deltas in reports (Lane C)

`tools/eval/scoring.py:102-124` — after in-tolerance matching, leftover
truth and predicted cuts are `zip`ped in index order regardless of
proximity, so a predicted cut at 25.0s can be reported as an
out-of-tolerance *match* for a truth cut at 1.0s (delta 24s) instead of
one missing + one extra. Pass/fail is unaffected (counts gate), but the
per-event deltas C#3 requires the report to carry are distorted exactly
when a human needs them. **Fix: S** — only pair leftovers whose delta is
below a sanity bound (e.g. 2× tolerance window), else report
missing/extra.

### 12. `freeze_real_videos` hardcodes `platform="youtube"` (Lane C)

`tools/eval/freeze_real_videos.py:90` — `_portable_breakdown` stamps every
frozen fixture as YouTube. Correct for both current manifest cases;
silently wrong metadata the day a TikTok case is added (the manifest
already carries `source_url` to derive it from). **Fix: S.**

### 13. Workspace override is a process-global env mutation (seam, Lane A api ↔ Lane C adapter)

`src/myzing/study/api.py:126-141` implements `workspace=` by mutating
`os.environ["ZING_HOME"]` for the duration of a study;
`tools/eval/performance.py:151-171` (StudyBenchmarkAdapter) and
`freeze_real_videos.py` depend on it. Any concurrent storage access in the
same process (a second adapter call, an MCP server thread, pytest-xdist)
reads/writes the wrong workspace mid-flight. Not reachable in today's
single-threaded eval runs — flagging before S2 makes it reachable.
**Fix: M** (thread storage root as a parameter; Lane A + storage change,
orchestrator contract call).

### 14. `write_status` read-modify-write is not atomic (Lane B)

`src/myzing/storage.py:172-194` — status merge is read → update →
`write_text` with no temp-file rename. A reader (another process running
`zing_status`) hitting the file mid-write gets partial JSON,
`read_status` returns None, and `get_breakdown` momentarily claims "no
breakdown for slug" during an active study. Transient and rare, but the
status file is the one artifact whose honesty B#2 staked out. **Fix: S**
— write to `status.json.tmp` + `os.replace`.

### 15. Cosmetics / drift (Lane B)

- `src/myzing/mcp_server.py:48` — `STUDY_PHASES` omits `keyframes`, which
  the engine actually reports; harmless today, but anything that validates
  phases against this tuple will reject a real phase. **Fix: S.**
- `src/myzing/prompt_pack.py:70-74` — `available_prompts()` serves *any*
  `*.md` in the prompts dir as an MCP prompt; a future `README.md` becomes
  a client slash-command. **Fix: S** (require frontmatter `name:`).

---

## Test gaps (what breaks that no test would catch)

1. **The renderer in CI** — nothing in the merge gate runs a single ffmpeg
   command (finding 1). The C-2 gate is green only on machines that
   already have ffmpeg.
2. **Re-study staleness** — no test creates breakdown.json + a `running`
   status and asserts what `h_get_breakdown` returns (finding 4).
   `test_get_breakdown_while_running_reports_phase` only covers the
   no-breakdown case.
3. **Crashed-server state** — no test simulates `status=running` with no
   live thread (finding 3).
4. **Doctor↔pipeline agreement** — no test asserts that a backend doctor
   calls ok is a backend `study()` can actually import (finding 2);
   the existing tesseract test asserts the opposite.
5. **Scorer at realistic scale** — no test scores > 3 events per
   dimension; the recursion ceiling (finding 10) is invisible.
6. **`~` paths over MCP** — no test passes a tilde path through
   `h_study_video` (finding 6).
7. **uoink 4xx root response** — `test_doctor` mocks only URLError and
   clean 200s; the HTTPError-on-GET-/ path (finding 7) is untested.

## What's solid (so the fixlist doesn't overcorrect)

- Lane C's renderer discipline is the best code in the repo: strict EDL
  validation matching the pinned S1 semantics (overlap/gap/word-window
  errors), argv-only ffmpeg + `filter_complex_script`, per-leg
  normalization before concat, content-probe oracle with
  frequency-isolated duck-depth assertions, hostile-path fixtures,
  atomic output publish, no OCR anywhere in render tests.
- The eval manifest honors C#3 to the letter (tolerances outside truth
  files, normalization declared, raw deltas beside pass/fail), the fault
  matrix covers every scored dimension with isolation assertions, and
  speech-ratio honesty ("tone is not speech") is exactly right.
- Lane B's errors-as-data envelope, per-section judgment replace with
  `_meta` stamping, judgment preservation + `.bak` on re-study, the
  prompt-pack contract test (the worked example must satisfy its own
  `required_keys`, evidence before verdicts), and the stdio smoke test
  reusing uoink's C-01 pattern are all faithful to the binding rulings.
- `prompts/study.md` is a genuinely strong v0: cite-or-abstain, warnings
  gate judgments, the visual-hook `cannot_judge` rule the eval will score.
