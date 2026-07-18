# Plan critique — Lane A (Study engine)

Author: Lane A (Claude Fable 5). Date: 2026-07-18. Read: vision doc, ROADMAP,
SPRINT-1-D1, schemas.py, PRIOR-ART-OSS, EXAMPLE-DATASET.

Ranked by leverage. Items 1–2 are contract gaps that undermine the product's
core promise (measurement honesty, judgment quality). Items 3–5 are
cross-lane seams that will drift silently if not pinned now. The rest are
quality and tooling. Schema recommendations are proposals for the
orchestrator — I will not touch `schemas.py`.

## 1. The schema cannot represent a skipped or degraded measurement

"Measurement honesty is the product," and my spec says transcription does an
"honest skip (empty list + warning)" — but `Breakdown` has **no field that
can hold a warning**. An empty `words` list is ambiguous between "silent
video" and "whisper not installed"; an empty `captions` list between "no
on-screen text" and "no OCR backend". The judgment AI, the eval harness, and
the human reading `breakdown.md` all need that distinction, and today the
only place it could live is the AI-owned `judgment` dict, which Zing's own
code must not write.

**Recommendation:** add to `Breakdown`:

```python
warnings: list[str] = field(default_factory=list)
# e.g. "transcription skipped: faster-whisper not installed"
```

Additive, default keeps existing JSON and tests valid, `from_dict` gains one
line. (A structured per-measurement status map is the S2 version; a warnings
list is the S1 floor and I need it in the first build PR.)

## 2. The judgment layer is blind: no keyframes anywhere in the contract

The vision doc's judgment plan is explicitly visual — "multimodal LLM on
keyframes for hook/beat classification" — and the S1 exit gate has an AI
judging hook type from a Breakdown. But a Breakdown is pure text and
numbers. An AI reading it over MCP cannot see a single frame, so the
*visual* half of the hook (the thing the first 1–3s lives or dies on) is
unjudgeable. The wizard-of-oz test will discover this the hard way.

**Recommendation:** Lane A extracts keyframes during study (first frame of
each shot, plus ~1 fps over 0–3s) into the breakdown folder — the frames are
already being decoded for OCR, so this is nearly free. Contract change: add
`keyframe: str = ""` (path relative to the breakdown dir) to `Shot`. Lane
B's MCP can return the paths now (Claude Desktop can read local files) and
serve real images in S2.

## 3. Measurement definitions aren't pinned; the eval harness will fight the pipeline over definitions, not accuracy

Lane C scores my output against exact truth, but several measured quantities
have multiple reasonable definitions, and each lane will pick independently:

- `loudness_curve` "dBFS": mean RMS per 1s bucket (astats)? EBU R128
  momentary (ebur128, LUFS)? These differ by several dB and shape.
- `speech_ratio`: VAD-speech seconds / duration, or whisper segment
  coverage? Whisper hallucinates segments on music-only audio, so these
  genuinely diverge on exactly our content.
- `cuts_per_10s`: non-overlapping windows? stride? is the trailing partial
  window scaled to 10s, or dropped?
- Minimum detectable shot: PySceneDetect's default `min_scene_len` is
  ~0.6s. A golden with a 0.4s segment would "fail" a correct pipeline.

**Recommendation:** pin one-line definitions in the contract (schemas.py
docstrings), orchestrator's choice. My proposals: loudness = per-1s mean
RMS dBFS via ffmpeg `astats` (cheap, S1-honest; ebur128 in S2 if R-D's LUFS
targets need it); `speech_ratio` = fraction of duration covered by VAD
speech; `cuts_per_10s` = non-overlapping 10s windows, count per window,
trailing partial window counted raw (not scaled) with the window list
length implying coverage; goldens use segments ≥ 0.8s.

## 4. Name the programmatic seam now: `study()` returning a `Breakdown`

Lane C's eval "runs Lane A's study pipeline" and Lane B's MCP tool
`study_video` calls it. If my deliverable is only a CLI, both lanes end up
shelling out to `zing study` and parsing stdout — fragile and slow.

**Recommendation:** the sprint spec names one function as the seam:

```python
# myzing/study/api.py
def study(source: str, workspace: Path | None = None) -> Breakdown: ...
```

(`source` = URL or local path.) The CLI becomes a thin wrapper. Lanes B/C
can stub against this signature today; I will ship exactly it either way,
so this is a doc line, not new work.

## 5. Variable frame rate will silently corrupt every timestamp

TikTok/IG media is frequently VFR. Any frame-index/fps arithmetic (the
OpenCV default) drifts — by whole seconds over a 60s clip — and every field
in the contract is float seconds. This is the classic short-form measurement
bug, and it's invisible until someone spot-checks against a stopwatch.

**Recommendation (Lane A policy, stated here for review):** all timestamps
derive from container PTS, never frame counts; ingest normalizes to CFR
H.264 mp4 via ffmpeg remux/re-encode when the source is VFR or an
OpenCV-hostile codec; `VideoMeta.fps` records the normalized rate;
yt-dlp format selection prefers avc1 mp4. Cost: one extra ffmpeg pass on
ingest for a subset of videos. If the orchestrator disagrees, I need the
alternative policy stated, because the eval tolerances (±0.15s cut times)
assume *somebody* solved this.

## 6. CI is Ubuntu-only; every gate in this project runs on Windows

Ryan's machine is the actual acceptance environment (performance budget,
wizard-of-oz, the 3-real-videos gate). Path separators, subprocess quoting,
console encoding (cp1252 vs UTF-8), and codec availability are the classic
Windows breakages, and our offline test suite is exactly the kind that
catches them cheaply.

**Recommendation:** add `windows-latest` to the CI matrix (same pytest, no
network). One-line workflow change, orchestrator- or any-lane-ownable.

## 7. `has_music: bool` cannot be honest

The contract's own docstring says "we say what we measured, not what we
guessed," but a bare bool forces a guess. S1 music detection is a weak
heuristic by design (spec says so), and the schema already models this
correctly elsewhere (`CaptionEvent.confidence`).

**Recommendation:** add `music_confidence: float = 0.0` to `AudioLayout`
(0 = no evidence). Keep the bool for coarse consumers.

## 8. Word-level confidence is free — capture it

faster-whisper emits per-word probability at no extra cost. Downstream,
word-timed caption rendering (C-2) and gap analysis (S3) lean on word
timing precisely where ASR is least sure (mumbles, music overlap). Dropping
the number now means re-transcribing later to get it back.

**Recommendation:** add `confidence: float = 1.0` to `Word` (default
preserves existing JSON/tests).

## 9. OCR at ~4 fps undersamples word-pop captions — the dominant style we're studying

Word-by-word pop captions (the TikTok default, and `words_visible=1` in our
own schema) show each word for ~150–300ms. Sampling at 4 fps (250ms) will
miss or single-sample many words, so caption *text completeness* will be
systematically weakest on the most important style. The S1 timebox is
right; the fix is honesty plus targeted effort where the report looks.

**Recommendation (Lane A implementation note):** sample ~8–10 fps over
0–3s (the hook window `breakdown.md` reports on) and ~4 fps elsewhere;
record the sampling rate in `warnings`/report so downstream knows the
resolution floor. Eval note for Lane C: caption *fuzzy-match* tolerance is
the right call — don't score caption recall as if sampling were continuous.

## 10. No provenance: eval scores won't be comparable across runs

When the S2 harness shows a caption score moved, we need to know whether
code, model, or threshold moved it. The Breakdown records nothing about how
it was produced.

**Recommendation:** add `provenance: dict[str, Any] =
field(default_factory=dict)` to `Breakdown` (zing version, detector +
threshold, whisper model + compute type, OCR backend, measured_at ISO).
Free-form dict keeps the contract stable while S1 learns what belongs there.

## Minor notes (no contract change requested)

- `VideoMeta.media_path` should be written relative to the breakdown dir so
  a breakdown folder survives being moved; I'll write it that way.
- Eval's "cut count exact" is correct for synthetic hard-cut goldens. On
  real videos, gradual transitions merge shots — the S2 real-data metric
  should be boundary F1 within a tolerance, not exact count. (Lane C note.)
- `zing doctor` should check yt-dlp version staleness — extractor rot is a
  when-not-if failure (R5 already implies this; making it explicit).
- PRIOR-ART-OSS already converges with my read: PySceneDetect
  (AdaptiveDetector) + rapidocr for S1. My R1-A research round will verify
  against published accuracy data before I take the dependencies.
