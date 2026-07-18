# Sprint 1 cross-review — Lane C

Reviewed: Lane A’s study engine and Lane B’s storage, doctor, MCP server,
prompt pack, connection flow, and Uoink bridge on merged `main`.

## Gate evidence

- `python -m pytest -q`: **214 passed** on Windows.
- Lane A’s default `large-v2` CPU pipeline completed both canonical
  EXAMPLE-DATASET videos. The frozen results preserve source hashes,
  measurement provenance, warnings, and stage timings.
- The reference video’s measured hook transcript and front-loaded cut
  density are credible. The second upload also exposed a truth-data error:
  it contains 34 shots, including 15 cuts from 20–30s, so it is not the
  zero-cut raw clip described by D-Q2.
- MCP’s real stdio handshake, prompt enumeration, errors-as-data envelope,
  and judgment stamping are covered. Lane A keeps optional measurement
  failures visible through warnings instead of converting missing evidence
  into confident values.

## Findings

### 1. [P1] MCP slugs can escape the workspace and read or rewrite files

`h_get_breakdown`, `h_save_judgment`, and `h_push_to_uoink` accept a slug
from the MCP caller and pass it to storage without validation.
`storage.breakdown_dir(slug)` joins that value directly beneath
`breakdowns/`, so `../../escape` resolves outside `ZING_HOME`.

Reproduction in an isolated temporary workspace:

```text
h_get_breakdown("../../escape") -> ok=true
h_save_judgment("../../escape", ..., section="notes") -> ok=true
```

The second call rewrote the out-of-workspace `breakdown.json`. This matters
even for a local server: tool arguments are AI-generated and may be
influenced by untrusted video text or prompts.

Recommendation: define one canonical slug validator in storage, reject
separators, `.`/`..`, absolute paths, and values outside the slug length and
character contract, then verify the resolved directory remains under
`breakdowns_root()`. Apply it at every public slug boundary and add
read/write/push traversal tests on Windows and POSIX-style inputs.

### 2. [P1] `get_breakdown` serves stale measurements as ready during re-study

The handler consults `status.json` only when `load_breakdown` raises. If a
slug already has a Breakdown, starting a re-study sets status to `running`
but leaves the prior JSON in place. `get_breakdown` then returns the old
measurement with `ready=true` and no running state.

Reproduction:

```text
save old Breakdown
write status: state=running, phase=ocr
h_get_breakdown(slug) -> ready=true, old title, no state
```

An AI can therefore judge an older video revision while believing the new
study finished. A failed re-study has the same ambiguity because the old
Breakdown still loads.

Recommendation: evaluate `running` and `failed` status before serving the
file. While running, return `ready=false` and optionally expose that a prior
snapshot exists; after failure, return the failure plus an explicit,
separately named prior snapshot only if the caller requests it. Add
re-study tests with an existing Breakdown for both running and failed
states.

### 3. [P1] Doctor and MCP preflight do not test the tool paths Lane A uses

On this machine, `doctor.check_ytdlp()` reports healthy because the Python
module is installed, while `shutil.which("yt-dlp")` is `None`. Lane A always
executes the `yt-dlp` binary, so URL ingest immediately raises
`ToolMissing`. The recommended fix is also inaccurate:
`pip install "myzing[study]"` does not install yt-dlp.

Two adjacent mismatches have the same root:

- `study_video` checks only `ffmpeg`, although ingest also requires
  `ffprobe`, and URL inputs require an invokable yt-dlp.
- Doctor marks a Tesseract-only machine OCR-ready, but Lane A implements
  only RapidOCR; no Tesseract fallback exists.

Recommendation: centralize executable capability resolution and use it in
doctor, MCP preflight, and study. Either invoke yt-dlp through
`python -m yt_dlp` when only the module exists or require the binary
everywhere. Mark Tesseract unsupported until a fallback lands. Add
integration tests that assert every doctor “ok” route is the exact route
the engine can invoke, plus URL preflight tests for missing yt-dlp and
ffprobe.

### 4. [P2] Interrupted background jobs remain “running” forever

The worker writes `failed` only when its Python exception handler runs.
Because it is a daemon thread, process exit or client/server shutdown kills
the work without that handler; the persisted state remains `running`.
After restart, `_JOBS` is empty but `zing_status` and `get_breakdown` keep
reporting an active job. This conflicts with `docs/CONNECT.md`, which says
a crashed study shows `failed` rather than a silent hang.

Recommendation: persist a worker identity and heartbeat, and reconcile
orphaned `running` states on server startup or status reads. At minimum,
report `interrupted` when a persisted running slug has no live in-process
job. Cover restart, abrupt worker loss, and recovery by a new study call.

### 5. [P2] X/long-form support stops at ingest

Lane A correctly tags X as platform `x` and uses a 30s hook window for
videos over 180s. The consumer surfaces have not caught up:

- `storage.slug_for("https://x.com/creator/status/1234567890")` returns an
  opaque `x-com-<hash>` instead of the queued status-ID slug; there is no X
  slug test.
- `prompts/study.md` still declares “ONE short video” and hardcodes the
  hook to 1–3s, the visual review to 0–3s, and verdict fields to the first
  1500ms. MCP server instructions also describe only short videos.

For long-form inputs, the deterministic report analyzes 30s while the AI
contract judges 3s, so the two layers disagree about the hook.

Recommendation: finish the queued X status-slug contract and tests. Then
bump the study prompt version and derive its hook instructions from the
format/provenance window (3s short-form, 30s long-form), including an
honest long-form output shape and worked example. Update MCP descriptions
to state the supported formats without promising short-form timing.

## What should remain unchanged

- Keep `study(source, workspace=None, phase_callback=None)` as the shared
  programmatic seam.
- Keep measurement failures in `Breakdown.warnings`; the real-video run
  showed this works.
- Keep background MCP jobs, on-disk status, per-section judgment replace,
  and the errors-as-data envelope. The findings above are boundary fixes,
  not reasons to replace those decisions.
- Keep the pure eval scorer and synthetic renderer oracles as the merge
  gates while real-video snapshots remain provenance baselines rather than
  machine-scored truth.
