# Prior art & reusable OSS survey (R-B)

Researcher: Claude agent (R-B lane). Date: 2026-07-18.
Method: GitHub API metadata (license SPDX, stars, last push, archived flag)
pulled 2026-07-18 via authenticated `gh api`; license texts read directly for
every NOASSERTION; product teardowns from vendor pages + 2026 reviews.
Scope: components and comparables for Zing's pipeline — yt-dlp fetch, shot
detection, faster-whisper word timestamps, caption OCR, pacing/audio
measurement, EDL JSON -> ffmpeg renderer with word-timed .ass + ducking,
local TTS (Kokoro/Piper), MCP server.

Verdict key: **REUSE** = take as dependency. **BORROW** = study the
approach/design, reimplement. **SKIP** = not worth time. Anything not
MIT/BSD/Apache/Unlicense/ISC is **ideas only — never code** (flagged).

---

## Top 5 highest-leverage findings

1. **pysubs2 (MIT, active) — REUSE now for the C-2 renderer.** Mature Python
   library for generating/editing .ass subtitles, including karaoke `\k` tags
   and full style/positioning control. Hand-rolling the ASS format for
   word-timed captions is a classic time sink with encoding and timing-format
   gotchas; pysubs2 removes the whole category. Small, zero heavy deps.
2. **Piper TTS is a license trap; Kokoro has a quieter one.** The MIT
   `rhasspy/piper` is **archived**; its official successor is literally named
   `piper1-gpl` (**GPL-3.0**, because it links espeak-ng in-process). Kokoro
   itself is Apache-2.0, but its G2P library misaki uses **espeak-ng
   (GPL-3.0)** as an *optional* English fallback. Recommendation: ship Kokoro
   as the only default TTS (via `kokoro-onnx`, MIT — no torch needed on
   Windows), do NOT install the espeak fallback in the default extra, and
   drop Piper from S4 or support only the archived MIT version as
   user-supplied. Update ROADMAP S4 wording accordingly.
3. **auto-editor (Unlicense, active, 4.6k stars) — the closest living
   relative.** Measurement-driven editing (audio loudness / motion analysis
   -> cut list) with export to Premiere XML, Final Cut XML, ShotCut, and its
   own timeline JSON. Public domain, so we can read *and lift* anything.
   Borrow: its silence/loudness cut heuristics for pacing measurement, and
   its timeline-export formats as the model for Zing's S4 "executor export
   package."
4. **whisperX (BSD-2, active, 23k stars) — the word-timestamp accuracy
   upgrade path.** faster-whisper's built-in word timestamps are decent but
   drift on fast speech; whisperX does phoneme-level forced alignment
   (wav2vec2) on top of faster-whisper and is the standard fix. Keep
   faster-whisper for S1 (already spec'd); if the eval harness shows caption
   word-timing misses, whisperX is the drop-in S2 upgrade — same backend,
   compatible license.
5. **OpenTimelineIO (Apache-2.0, ASWF, active) — keep the EDL schema
   OTIO-mappable.** The industry-standard interchange format for timelines
   with adapters for Premiere/Resolve/etc. Don't adopt it as the internal
   format (heavyweight for Zing's needs), but a one-way `zing export --otio`
   in S4 turns Zing's draft EDL into something a real NLE opens — that is the
   highest-credibility version of the "executor export package."

Runners-up: **RapidOCR** (Apache, ONNX, pip-installable — no tesseract binary
to detect on Windows) for caption OCR; **clipsai** (MIT) for its face-tracked
9:16 auto-crop code; **silero-vad** (MIT) for honest speech-ratio
measurement; Opus Clip's 4-signal virality score as direct input to the R-A
taste rubric.

## License landmines (never vendor code from these)

| Project | License | Note |
|---|---|---|
| Remotion | Source-available "Remotion License" (NOASSERTION) | Free only for individuals / for-profits <=3 employees / nonprofits; company license via remotion.pro above that; no derivative relicensing. **Not OSI.** Ideas only. |
| piper1-gpl | GPL-3.0 | The *active* Piper. GPL because espeak-ng is embedded in-process. |
| espeak-ng | GPL-3.0 | Transitive risk via Kokoro/misaki fallback and Piper phonemization. Keep out of default install; subprocess-only if ever used. |
| whisper-timestamped | AGPL-3.0 | The DTW-on-cross-attention idea is readable; the code is radioactive for MIT. |
| videogrep | Anti-Capitalist License | Not OSI; excludes for-profit use. Ideas only. |
| LosslessCut | GPL-2.0 | UX ideas only (keyframe-accurate cuts, smart cut). |
| AI-Youtube-Shorts-Generator | **NO LICENSE** | All rights reserved by default despite "open-source" marketing. Do not copy anything. |
| supoclip | AGPL-3.0 | Ideas only. |
| aeneas | AGPL-3.0 | High-quality forced alignment, but AGPL-3.0 is a license landmine for commercial/permissive reuse. Ideas only. |
| ffmpeg (binary) | LGPL/GPL by build | Calling the user's binary via subprocess (Zing's pattern) is fine and standard. Never *bundle* a GPL ffmpeg build in a distributed MIT package without doing the homework. |


---

## Core measurement & editing components

### auto-editor — https://github.com/WyattBlue/auto-editor
- **What:** CLI that auto-cuts video by analyzing audio loudness/motion;
  renders directly or exports timelines (Premiere XML, FCP XML, ShotCut,
  own JSON format, v1/v3 timeline spec).
- **License:** Unlicense (public domain). **Health:** 4,560 stars, pushed
  2026-07-17, single strong maintainer, years of steady releases.
- **Verdict: BORROW (heavily).** Different product goal (it edits; Zing
  directs), but its loudness-threshold cut detection informs pacing
  measurement, and its timeline export formats are the blueprint for S4
  exports. Public domain means snippets can be lifted with attribution as
  courtesy, not obligation. Not a dependency: its pipeline is monolithic and
  CLI-shaped, not library-shaped.

### PySceneDetect — https://github.com/Breakthrough/PySceneDetect
- **What:** The standard Python shot/cut detector: ContentDetector (HSV
  delta), AdaptiveDetector (rolling average — better on fast motion),
  ThresholdDetector (fades). Library + CLI, frame-accurate timecodes,
  stats CSV.
- **License:** BSD-3-Clause. **Health:** 5,024 stars, pushed 2026-07-18,
  actively maintained for a decade.
- **Verdict: REUSE.** This is the S1 Lane A shot-detection choice.
  AdaptiveDetector handles short-form's fast cuts better than plain
  content mode; ffmpeg scdet is the zero-dep fallback but gives less
  control over thresholds and no stats output for the eval harness.

### TransNetV2 — https://github.com/soCzech/TransNetV2
- **What:** Learned shot-boundary-detection network (research SOTA on
  ClipShots/BBC); catches gradual transitions and effects-heavy cuts that
  histogram methods miss. TF weights in-repo, community PyTorch port on PyPI
  (`transnetv2-pytorch`).
- **License:** MIT (code and weights). **Health:** 990 stars, last push
  2023-12 — research code, effectively frozen.
- **Verdict: BORROW (S2 fallback).** If the eval harness or real short-form
  data shows PySceneDetect missing flash/transition-heavy cuts, TransNetV2 is
  the licensed upgrade. Don't take the dependency in S1 — frozen repo, TF/
  torch weight-loading friction, and goldens are hard-cut synthetic anyway.

### AutoShot — https://github.com/wentaozhu/AutoShot
- **What:** Research model + dataset (SHOT) for shot boundaries specifically
  in *short-form* videos (Kuaishou); claims to beat TransNetV2 on that
  domain.
- **License:** MIT. **Health:** 246 stars, frozen since 2023.
- **Verdict: BORROW (bookmark).** Same story as TransNetV2 but tuned to
  exactly Zing's domain. Worth an eval-harness bake-off in S2 if shot
  detection quality becomes the bottleneck; the SHOT dataset is also useful
  ground truth for expanding the golden set.

### whisperX — https://github.com/m-bain/whisperX
- **What:** faster-whisper batching + wav2vec2 forced alignment for accurate
  word-level timestamps + optional pyannote diarization. 70x realtime on GPU.
- **License:** BSD-2-Clause (pyannote itself is MIT; its models need HF
  token acceptance — an install-friction note for doctor if ever adopted).
- **Health:** 23,128 stars, pushed 2026-07-13, active.
- **Verdict: BORROW now, REUSE if needed.** S1 stays on plain faster-whisper
  (already spec'd, lighter). The forced-alignment pass is the known fix if
  word-timed .ass captions look off against goldens. Diarization is out of
  scope until multi-speaker videos matter.

### faster-whisper — https://github.com/SYSTRAN/faster-whisper
- **What:** CTranslate2 Whisper inference; 4x faster than openai/whisper,
  word timestamps, built-in Silero VAD filter.
- **License:** MIT. **Health:** 24,353 stars, pushed 2025-11 — cadence has
  slowed post-SYSTRAN-acquisition churn, but it is the ecosystem default and
  whisperX rides on it.
- **Verdict: REUSE (already core).** Confirmed right choice. Use its
  `vad_filter=True` and segment output for speech-ratio measurement before
  reaching for a separate VAD dependency.

### silero-vad — https://github.com/snakers4/silero-vad
- **What:** Tiny (~2MB) enterprise-grade voice-activity detector, ONNX,
  <1ms per chunk on CPU.
- **License:** MIT. **Health:** 9,610 stars, pushed 2026-07-16, active.
- **Verdict: REUSE (thin).** For `AudioLayout.speech_ratio` when whisper
  isn't available/installed — doctor can report "VAD-only mode" honestly.
  Also already embedded inside faster-whisper, so it may come along free.

### librosa — https://github.com/librosa/librosa
- **What:** The standard Python audio-analysis library: onset detection,
  beat/tempo tracking, spectral features.
- **License:** ISC (BSD-equivalent). **Health:** 8,504 stars, pushed
  2026-07-17, institutionally maintained.
- **Verdict: REUSE (S2).** `has_music` as an honest heuristic and any
  cut-on-beat pacing analysis (does the editor cut on music beats?) come
  almost free from onset strength + tempogram. Heavier import than S1 needs;
  ffmpeg loudness curve suffices for S1.

### inaSpeechSegmenter — https://github.com/ina-foss/inaSpeechSegmenter
- **What:** CNN speech/music/noise segmenter from INA (French national
  archive); the credible dedicated music-detection option.
- **License:** MIT. **Health:** 902 stars, pushed 2026-03. TensorFlow
  dependency — heavy.
- **Verdict: BORROW.** Right answer if `has_music` must become a real
  classifier, but the TF dep is disproportionate. Prefer librosa heuristics
  first; revisit only if eval shows music detection failing.

### ffmpeg-normalize — https://github.com/slhck/ffmpeg-normalize
- **What:** Two-pass EBU R128 `loudnorm` wrapper targeting e.g. -14 LUFS.
- **License:** MIT (license text verified; GitHub shows NOASSERTION only
  because the file is nonstandard-formatted). **Health:** 1,517 stars,
  pushed 2026-07-10, same maintainer for a decade.
- **Verdict: BORROW.** Zing's renderer already shells to ffmpeg; lift the
  two-pass loudnorm filtergraph pattern (measure pass -> apply pass with
  measured values) rather than adding a wrapper dep. Directly serves R-D's
  ~-14 LUFS platform target.

### demucs — https://github.com/facebookresearch/demucs
- **What:** Meta's state-of-the-art hybrid transformer audio source separation tool. Splits audio into vocals, drums, bass, and other music beds.
- **License:** MIT. **Health:** 11k+ stars, active updates, backed by Meta Research.
- **Verdict: REUSE/BORROW (S2).** Excellent for isolating clean dialogue from background music before transcription (improves Whisper word accuracy on music-heavy clips) and measuring exact ducking thresholds. We should support it as an optional dependency (extra) or borrow their CLI subprocess integration pattern.

## Caption OCR

### RapidOCR — https://github.com/RapidAI/RapidOCR
- **What:** ONNX-runtime OCR (PaddleOCR PP-OCR models repackaged), pip
  install, CPU-fast, no system binary.
- **License:** Apache-2.0. **Health:** 7,192 stars, pushed 2026-07-09,
  active.
- **Verdict: REUSE.** The right S1 OCR backend for Windows-first local
  install: `pip install rapidocr-onnxruntime` beats "go install tesseract
  and put it on PATH" for doctor UX, and PP-OCR scene-text models tolerate
  stylized captions better than tesseract's document-trained engine.
  Keep tesseract as a detected-if-present alternative.

## Rendering & timeline

### pysubs2 — https://github.com/tkarabela/pysubs2
- **What:** Read/write/edit SubStation Alpha (.ass), SRT, WebVTT; styles,
  positioning, karaoke tags; CLI converter.
- **License:** MIT. **Health:** 433 stars, pushed 2026-07-13, maintained
  10+ years. Low stars because it's plumbing, not a product.
- **Verdict: REUSE (C-2, now).** Generate word-timed .ass from
  `CaptionSpec.words` with real style objects instead of string templates.
  Also useful in the eval harness to parse the .ass back and assert word
  timing.

### moviepy — https://github.com/Zulko/moviepy
- **What:** Pythonic video editing — clips, concat, compositing, text — by
  decoding frames through ffmpeg pipes and re-encoding.
- **License:** MIT. **Health:** 14,789 stars, pushed 2026-03; v2 (2024)
  revived it after years of drift.
- **Verdict: SKIP (as renderer).** Frame-by-frame Python processing is 10 to
  100x slower than a single ffmpeg filtergraph and adds a fragile dep. Zing's
  direct-ffmpeg EDL executor is the right architecture. Borrow nothing;
  its caption rendering (ImageMagick/PIL) is exactly what .ass burning
  avoids.

### editly — https://github.com/mifi/editly
- **What:** Declarative JSON edit spec -> video (Node): clips, transitions,
  Ken Burns, text layers, audio ducking (`mixVolume`-style).
- **License:** MIT. **Health:** 5,452 stars, pushed 2025-05, effectively
  unmaintained (maintainer moved on; issues stack up).
- **Verdict: BORROW.** The closest existing "EDL JSON in, video out" design.
  Study its spec shape — layer model, per-clip transitions, `audioNorm` and
  ducking options, `cutFrom/cutTo` semantics — as a checklist for what Zing's
  EDL schema will eventually need. Node runtime and dead repo rule out reuse.

### remotion — https://github.com/remotion-dev/remotion
- **What:** Videos as React components, rendered via headless Chrome;
  excellent captioning/animation ergonomics; huge ecosystem.
- **License:** **NOT open source.** Custom "Remotion License": free for
  individuals, for-profits up to 3 people, and nonprofits; paid company
  license beyond that; no reselling/relicensing derivatives. **Health:**
  53,542 stars, pushed 2026-07-17, VC-grade active.
- **Verdict: IDEAS ONLY (license).** Never vendor code or take it as a dep
  of an MIT tool. Worth studying: `@remotion/captions` word-token model
  (their TikTok-style caption pages/tokens structure is a clean data shape
  for word-timed captions) and their determinism discipline (frame-pure
  rendering) as a mindset for reproducible EDL renders.

### OpenTimelineIO — https://github.com/AcademySoftwareFoundation/OpenTimelineIO
- **What:** Academy Software Foundation interchange format + Python API for
  editorial timelines; adapters for CMX EDL, FCP XML, and (via ecosystem)
  Premiere/Resolve.
- **License:** Apache-2.0. **Health:** 1,920 stars, pushed 2026-07-14,
  foundation-backed (used by Pixar, Netflix pipelines).
- **Verdict: BORROW now, REUSE in S4.** Keep Zing's EDL JSON conceptually
  mappable (tracks, clips with source ranges, markers) and add an OTIO
  export in S4 so a human editor can open Zing's draft cut in a real NLE.
  Do not adopt as the internal format — Zing's EDL needs captions/ducking
  semantics OTIO doesn't model natively.

### ffmpeg-python — https://github.com/kkroening/ffmpeg-python
- **What:** Filtergraph-builder DSL for ffmpeg.
- **License:** Apache-2.0. **Health:** 11,001 stars, but last push 2024-08
  and maintainer absent for years; community forks fragment.
- **Verdict: SKIP.** Zing's own thin subprocess wrapper (already the CI
  mocking pattern) is more debuggable than a dead DSL. Complex filtergraphs
  are better written explicitly and unit-tested as strings.

### ffsubsync — https://github.com/smacke/ffsubsync
- **What:** CLI tool to synchronize subtitles with video by analyzing speech presence/absence in the audio track and matching it with subtitle events using Fast Fourier Transforms (FFT).
- **License:** MIT. **Health:** 5.2k+ stars, mature tool, stable releases.
- **Verdict: BORROW (C-2 / S2).** Useful for matching timing offsets. While we don't need a full alignment tool (our pipeline generates timing natively), we can borrow their VAD-to-subtitle cross-correlation alignment logic to auto-correct drift in user-supplied external subtitles.

### subaligner — https://github.com/baxtree/subaligner
- **What:** Subtitle synchronization and translation tool using deep neural networks and forced alignment. Supports timing shift detection, alignment, and translation.
- **License:** MIT. **Health:** 500+ stars, active, well-documented.
- **Verdict: SKIP (S2).** Too heavy (requires PyTorch and complex DNN model files) for a simple local editor. We should stick to lighter correlation tools like `ffsubsync` or `whisperX`.

## Similar tools (auto-edit / clip generators)

### videogrep — https://github.com/antiboredom/videogrep
- **What:** Search a transcript, supercut matching moments; n-gram tooling.
- **License:** **Anti-Capitalist License — not OSI, excludes for-profit
  use. Ideas only.** **Health:** 3,461 stars, frozen since 2024.
- **Verdict: IDEAS ONLY.** The core idea — transcript as the query surface
  for cuts — validates Zing's words-first Breakdown. Nothing else needed.

### jumpcutter — https://github.com/carykh/jumpcutter
- **What:** The 2019 original silence-speedup script (carykh).
- **License:** MIT. **Health:** 3,149 stars, abandoned; author points users
  elsewhere.
- **Verdict: SKIP.** Historically important, technically superseded by
  auto-editor in every way.

### ShortGPT — https://github.com/RayVentura/ShortGPT
- **What:** Framework for automated faceless-content shorts: LLM script,
  EdgeTTS voice, stock assets, captions.
- **License:** MIT. **Health:** 7,711 stars, last push 2025-02 — stalling.
- **Verdict: SKIP.** It is the slop machine Zing positions against. Its
  asset-sourcing abstraction is the only mildly interesting part, and Zing
  doesn't source assets.

### MoneyPrinterTurbo — https://github.com/harry0703/MoneyPrinterTurbo
- **What:** Text prompt -> finished faceless video (script, stock clips,
  TTS, burned subtitles), web UI + API. Massive adoption.
- **License:** MIT. **Health:** 97,916 stars, pushed 2026-07-18, very
  active.
- **Verdict: SKIP (with one note).** Same anti-slop reasoning as ShortGPT.
  The note: 98k stars is market proof that "one command -> finished
  vertical video" is what people want — Zing's demo path (`zing study` ->
  direct -> render) must feel that effortless. Its MIT code is legible if
  we ever want a reference for ffmpeg subtitle burn on Windows paths.

### clipsai — https://github.com/ClipsAI/clipsai
- **What:** Python lib: transcript-based clip finding (podcast -> shorts) +
  face-tracked dynamic 9:16 reframing (mediapipe).
- **License:** MIT. **Health:** 521 stars, dead since 2024-01.
- **Verdict: BORROW.** The resize/reframe module is the useful half: scene
  segmentation + face detection -> crop keyframes. When Zing's S3 direct
  stage needs "this 16:9 source shot, reframed vertical," this is MIT
  reference code worth reading before writing our own.

### FunClip — https://github.com/modelscope/FunClip
- **What:** Alibaba's LLM-assisted clipping tool on FunASR (excellent
  Chinese ASR + accurate timestamps), Gradio UI, LLM picks segments.
- **License:** MIT. **Health:** 5,936 stars, pushed 2026-07-18, active.
- **Verdict: BORROW.** Their prompt patterns for "LLM reads transcript with
  timestamps, returns clip decisions" parallel prompts/study.md and
  prompts/direct.md. Also the reference if Chinese-language sources ever
  matter. Dependency itself is heavy (FunASR stack) — not worth it.

### captacity — https://github.com/unconv/captacity
- **What:** Small script: Whisper word timestamps -> styled burned captions
  via moviepy.
- **License:** MIT. **Health:** 139 stars, frozen 2024.
- **Verdict: SKIP.** Zing's .ass pipeline is strictly better (styling,
  positioning, performance). Nothing here that pysubs2 + ffmpeg doesn't do
  better. (Category note: most "auto caption burner" repos are this same
  200-line shape; none found worth a dependency.)

### stable-ts — https://github.com/jianfch/stable-ts
- **What:** Whisper timestamp stabilization: word regrouping, silence
  suppression, gap adjustment — years of accumulated heuristics.
- **License:** MIT. **Health:** 2,278 stars, **archived 2026** — read-only.
- **Verdict: BORROW.** Archived means no dependency, but its regrouping
  heuristics (merge stray words, snap boundaries to silence) are documented,
  MIT, and directly applicable when polishing caption word windows in S2.

### whisper-timestamped — https://github.com/linto-ai/whisper-timestamped
- **License:** **AGPL-3.0 — ideas only.** DTW on cross-attention weights for
  word timing. whisperX covers the same need under BSD. **Verdict: SKIP.**

### LosslessCut — https://github.com/mifi/lossless-cut
- **License:** **GPL-2.0 — ideas only.** 42k stars, active. Keyframe-aware
  lossless cutting and "smart cut" (re-encode only around the cut point) is
  a genuinely good idea if Zing ever offers no-reencode exports.
  **Verdict: IDEAS ONLY.**

### Newer "Opus Clip alternative" wave (2025-2026)
- `SamurAIGPT/AI-Youtube-Shorts-Generator` (4.3k stars): **NO LICENSE — all
  rights reserved. Do not copy.** `FujiwaraChoki/supoclip` (965 stars):
  **AGPL-3.0.** Various ComfyUI clipping nodes: API-tethered.
- **Verdict: SKIP as code.** Useful only as market evidence that
  LLM-highlight + auto-reframe + word captions is the expected feature
  bundle.

### pyVideoTrans — https://github.com/jianchang512/pyvideotrans
- **What:** A comprehensive GUI and CLI video translation, dubbing, and subtitling toolbox translating video from one language to another using whisper, translate engines, and local TTS.
- **License:** GPL-3.0. **Health:** 11.2k+ stars, extremely active, rapid updates.
- **Verdict: SKIP / IDEAS ONLY (GPL-3.0 License).** While highly functional, the GPL-3.0 license makes the code radioactive for direct incorporation. Furthermore, its monolithic GUI focus is too heavy for Zing's lightweight developer-focused MCP/CLI tool.

## Fetch & TTS

### yt-dlp — https://github.com/yt-dlp/yt-dlp
- **License:** Unlicense. **Health:** 178,589 stars, pushed 2026-07-14, the
  most maintained project in this survey. **Verdict: REUSE (already core).**
  Call as subprocess/binary and have doctor check version freshness —
  extractors rot fast, and TikTok/IG breakage is a when-not-if support
  issue (R5 disclaimer inherits from uoink).

### youtube-transcript-api — https://github.com/jdepoix/youtube-transcript-api
- **What:** Python API to retrieve official and auto-generated transcripts from YouTube without requiring browser automation.
- **License:** MIT. **Health:** 2.5k+ stars, active maintenance, widely used.
- **Verdict: REUSE (S2 / Eval).** Highly useful for our evaluation and regression testing framework. It allows the pipeline to fetch YouTube's native human-written transcriptions to act as the golden truth dataset without requiring manual transcription.

### Kokoro — https://github.com/hexgrad/kokoro
- **What:** 82M-param TTS, near-SOTA quality-per-watt, CPU-viable, voices on
  HF under Apache.
- **License:** Apache-2.0 (code, weights, and misaki G2P all Apache).
  **Landmine adjacent:** misaki's English G2P is dictionary-based, but its
  documented OOV *fallback* is espeak-ng (**GPL-3.0**, in-process binding).
  **Health:** 8,025 stars; main repo quiet since 2025-08 but ecosystem
  active.
- **Verdict: REUSE (default S4 TTS)** — via **kokoro-onnx
  (thewh1teagle/kokoro-onnx, MIT, 2.6k stars, pushed 2026-07)**: ONNX
  runtime, no torch install on Windows, ships with misaki dictionary G2P.
  Ship without the espeak fallback; unknown words degrade gracefully and
  doctor can say so. (remsky/Kokoro-FastAPI, Apache, is the server-shaped
  alternative — SKIP, Zing wants in-process.)

### Piper — https://github.com/rhasspy/piper (archived) / OHF-Voice/piper1-gpl
- **What:** Fast local neural TTS for low-end hardware, big voice catalog.
- **License:** Original rhasspy/piper is MIT but **archived 2025**. The
  active successor **piper1-gpl is GPL-3.0** (espeak-ng embedded). Voice
  models additionally carry **per-voice dataset licenses** — several are
  non-commercial.
- **Verdict: DROP from the S4 default (was "Kokoro/Piper").** Kokoro beats
  it on quality anyway. If a second engine is wanted: support "point Zing
  at any local TTS CLI" as a config hook instead of depending on a GPL
  package. Never wrap piper1-gpl as a Python dep of MIT Zing.

## Closed products — feature teardowns (ideas only)

### Stanley (getstanley.ai)
Prompt-driven "AI editor you hire": send raw footage, get back a finished
captioned edit — silence/umm removal, follow-the-speaker captions,
punch-in zooms *where you ask for them*, auto music bed ducked under
dialog, and crucially an **editable timeline after the prompt** so users
nudge cuts instead of re-running. ~$149/mo positioning. Takeaways for Zing:
(1) the editable artifact is the product — Zing's EDL JSON is exactly that,
lean into "every decision is inspectable and re-renderable"; (2) zoom
punch-ins as an EDL primitive (crop-scale on a clip span) is cheap in
ffmpeg and high perceived value; (3) music-under-dialog with ducking as the
*default* deliverable, not an option.

### Opus Clip (opus.pro)
Long video in -> ranked shorts out. Its **virality score (0-99) built from
four named signals: hook strength, emotional flow, perceived value, trend
alignment** is the commercial cousin of Zing's R-A taste rubric — proof
that scored, criteria-based judgment sells; Zing's edge is *citing* the
rubric instead of a black-box number. ReframeAnything (object-tracked
16:9 -> 9:16), AI b-roll gap-filling, 97%-claim captions, direct-to-platform
scheduling. Takeaway: gap reports that say "hook 2/5 — no pattern interrupt
in 1.5s" beat "virality 62" on trust, which is Zing's whole thesis.

### Descript
Text-based editing (delete words -> deletes video) plus **Underlord**, an
agentic co-editor you instruct in natural language ("remove filler words,
tighten pacing, clip the ending for social"); real-world reviews put a
31-min interview edit at ~4 min with it. Zing's MCP server + prompts/study.md
is structurally the same pattern with the user's own AI as the agent —
Descript validates the architecture. Borrow-idea: expressing edit operations
*as transcript operations* (cut = word-range deletion) is the most human
way to render a gap report or draft-EDL diff.

### CapCut (ByteDance)
The default free-tier editor for short-form creators: template-driven
styled auto-captions (trend-keyed animation presets), auto-cut, script-to-
video, beat-synced templates; 2025 ToS changes (broad content rights) and
paywalling pushed some creators to look for local alternatives — a real
wedge for a local-first MIT tool. Takeaway: **caption style presets** are a
solved UX pattern creators expect — Zing's .ass generator should ship a
handful of named, genre-appropriate caption styles (measured from studied
videos, per the taste rubric) rather than one hardcoded look.

---

## Consolidated verdict table

| Component | License | Verdict |
|---|---|---|
| yt-dlp | Unlicense | REUSE (core) |
| youtube-transcript-api | MIT | REUSE (eval/regression golden fetch) |
| PySceneDetect | BSD-3 | REUSE (S1 shot detection) |
| faster-whisper | MIT | REUSE (core) |
| RapidOCR | Apache-2.0 | REUSE (S1 caption OCR) |
| pysubs2 | MIT | REUSE (C-2 .ass generation) |
| kokoro-onnx (+ Kokoro/misaki) | MIT/Apache | REUSE (S4 default TTS, no espeak fallback) |
| silero-vad | MIT | REUSE (thin, honest speech ratio) |
| librosa | ISC | REUSE (S2 music/beat analysis) |
| demucs | MIT | REUSE / BORROW (S2 vocal/music isolation) |
| OpenTimelineIO | Apache-2.0 | BORROW now, REUSE for S4 export |
| auto-editor | Unlicense | BORROW (cut heuristics, timeline exports) |
| whisperX | BSD-2 | BORROW (S2 word-timing upgrade path) |
| TransNetV2 / AutoShot | MIT | BORROW (S2 shot-detection fallback) |
| editly | MIT | BORROW (EDL spec design) |
| clipsai | MIT | BORROW (face-tracked 9:16 reframe) |
| stable-ts | MIT (archived) | BORROW (timestamp heuristics) |
| ffsubsync | MIT | BORROW (timing alignment/drift correction) |
| FunClip | MIT | BORROW (LLM-clipping prompts) |
| ffmpeg-normalize | MIT | BORROW (two-pass loudnorm pattern) |
| inaSpeechSegmenter | MIT | BORROW (only if has_music needs ML) |
| moviepy | MIT | SKIP (wrong renderer architecture) |
| ffmpeg-python | Apache-2.0 | SKIP (unmaintained DSL) |
| subaligner | MIT | SKIP (S2 heavy DNN sync) |
| jumpcutter, captacity, auto-subtitle | MIT | SKIP (superseded) |
| ShortGPT, MoneyPrinterTurbo | MIT | SKIP (slop generators; market signal only) |
| pyVideoTrans | GPL-3.0 | SKIP / IDEAS ONLY (translation GUI, GPL-3.0) |
| Remotion | Source-available | IDEAS ONLY |
| videogrep | Anti-Capitalist | IDEAS ONLY |
| LosslessCut | GPL-2.0 | IDEAS ONLY |
| whisper-timestamped, supoclip | AGPL-3.0 | IDEAS ONLY |
| piper1-gpl | GPL-3.0 | AVOID (drop Piper from S4 default) |
| AI-Youtube-Shorts-Generator | NONE | AVOID (unlicensed) |

## Spec-change recommendations for the orchestrator

1. **S4 spec:** change "Kokoro/Piper" to "Kokoro (kokoro-onnx) default;
   arbitrary local TTS via CLI hook" — Piper's active line is GPL-3.0 and
   its voices carry per-voice licenses.
2. **S1 Lane A:** OCR backend recommendation = rapidocr-onnxruntime
   (Apache, pip-only) with tesseract as detected-alternative; shot
   detection = PySceneDetect AdaptiveDetector.
3. **C-2 renderer:** add pysubs2 (MIT) as the .ass dependency; adopt the
   two-pass loudnorm pattern targeting -14 LUFS integrated.
4. **S4 export package:** include `.otio` export via OpenTimelineIO;
   study auto-editor's Premiere/FCP XML exports as the compatibility bar.
5. **Dependency policy footnote:** espeak-ng (GPL-3.0) must never enter
   the default install graph; CI could grep the lockfile for
   GPL/AGPL SPDX ids as a cheap guard.

---

## SG-4 trending scan · 2026-07-18 · Lane B (standing generator)

Method: GitHub trending + topic searches (video-editing, creator-tools,
subtitles, media-ml, video-understanding, MCP media) via research agent;
licenses verified against GitHub API SPDX per repo. Five repos not in the
original R-B survey.

### pyloudnorm — https://github.com/csteinmetz1/pyloudnorm
- **What:** Python ITU-R BS.1770-4 integrated loudness (LUFS) metering.
- **License:** MIT (API SPDX verified). **Health:** 775 stars, pushed
  2026-01-04; single academic maintainer — small finished algorithm lib,
  not abandonware.
- **Verdict: REUSE (audio measurement).** Numeric LUFS per clip/segment
  as plain Python floats (block-gated, custom block sizes for short
  windows) — far easier to aggregate into style profiles and ducking
  targets than parsing ffmpeg ebur128 stderr; pure numpy/scipy. Directly
  serves the S2 LUFS candidate named in schemas' AudioLayout docstring
  and the wizard-of-oz P9 gap (−14 LUFS unverifiable from RMS).

### pyannote-audio — https://github.com/pyannote/pyannote-audio
- **What:** Neural speaker diarization (VAD, speaker change, overlap,
  embeddings).
- **License:** MIT (verified); pretrained pipelines MIT but HF-gated
  (token + terms) with a commercial pyannoteAI tier — install-friction
  note for doctor if adopted. **Health:** 10.3k stars, pushed
  2026-07-17, commercially backed.
- **Verdict: REUSE (optional extra, S2+).** Speaker-count/talk-time/
  overlap stats are exactly the talking-head vs dialogue vs voiceover
  signal style profiles need (silero-vad only says speech/non-speech).
  Heavy torch dep — extras-gated only.

### Qwen3-VL — https://github.com/QwenLM/Qwen3-VL
- **What:** Open-weight multimodal LLM series with first-class video
  understanding (timestamped video QA, dense captioning).
- **License:** Apache-2.0 incl. weights (verified — unlike Qwen's
  earlier research-licensed VL checkpoints). **Health:** 19.6k stars,
  pushed 2026-01-30, large funded team.
- **Verdict: REUSE (D-3 directing, local-judgment option).** 2B–8B
  variants run locally (vLLM/llama.cpp/Ollama) and can caption shots or
  answer "what's missing between shot 4 and 5" — semantic shot
  understanding is the one pipeline piece current deps don't cover.
  NOTE: adopting it as a bundled judge would cross the "no bundled
  model" architecture line — the honest fit is an OPTIONAL local
  judgment backend the user's AI can call, or a documented recipe;
  orchestrator call before any S3 use.

### VideoLingo — https://github.com/Huanshere/VideoLingo
- **What:** End-to-end subtitle pipeline (transcribe, NLP+LLM sentence
  split, align, translate, dub).
- **License:** Apache-2.0 (verified). **Health:** 17.8k stars, pushed
  2026-07-02; active, Streamlit-app-shaped, cloud-LLM-dependent.
- **Verdict: BORROW (caption rendering).** Its two-stage subtitle
  line-splitting (syntactic spaCy split, then LLM semantic split against
  CPS/length limits) is the best documented answer to where-to-break-
  lines — the hardest part of word-timed .ass rendering. Monolithic app,
  not a library: lift the approach, not the dependency.

### FireRed-OpenStoryline — https://github.com/FireRedTeam/FireRed-OpenStoryline
- **What:** Xiaohongshu's AI video-editing agent: NL intent → LLM plan →
  ffmpeg-tool orchestration, reusable "Style Skills."
- **License:** Apache-2.0 (verified). **Health:** 3.1k stars, created
  2026-02, pushed 2026-05; young, corporate-backed.
- **Verdict: BORROW (directing/render architecture).** The closest
  published system to Zing's thesis (measure → plan → render,
  human-in-the-loop, style as reusable artifact); its Style Skills
  validate the aggregated-style-profile design. FastAPI + cloud-LLM
  shape rules out dependency; study the planner/tool-schema layering.

**Scan summary (2026-07-18):** the 2025–2026 trend is agentic wrappers converging on
Zing's territory from both sides — thin ffmpeg-MCP servers below, full
editing agents (OpenStoryline, OpenCut-style) above — while the middle
layer Zing occupies (local measurement, style aggregation, deterministic
rendering) remains unclaimed. Licensing has swung our way: the strongest
new models are Apache/MIT, so the local-first permissive stack no longer
forces quality compromises. Differentiation should lean on
measurement-derived style profiles: nobody in the trending set grounds
edit decisions in quantitative analysis of reference footage.

---

## SG-4 trending scan · 2026-07-19 · Lane D (standing generator)

Method: Topic searches on video understanding, forced alignment, and agentic editing libraries on GitHub; licenses verified. Three new repositories analyzed.

### aeneas — https://github.com/readbeyond/aeneas
- **What:** Command-line tool and Python library to automatically synchronize audio and text (forced alignment) at sentence/word level using DTW (Dynamic Time Warping) and MFCC features.
- **License:** AGPL-3.0 (verified). **Health:** 1.5k stars, archived/mature.
- **Verdict: SKIP/IDEAS ONLY (licensing risk).** The AGPL-3.0 license is too restrictive for direct dependency in an MIT-licensed tool. Furthermore, the repository is archived. However, its DTW-based forced alignment algorithm and text-audio synchronization mapping structure are valuable reference designs. S2/S3 should stick with permissive options like `faster-whisper` and `whisperX`.

### Videopython — https://github.com/BartWojtowicz/videopython
- **What:** Programmatic, agent-driven video editing library. Allows defining video editing plans (cuts, transitions, subtitles) via JSON files and utilizes local/cloud LLMs to compile editing plans.
- **License:** MIT (verified). **Health:** Young, actively updated.
- **Verdict: BORROW (agent plan compilation).** The concept of decoupling the editing intent (expressed as a JSON edit plan) from the actual FFmpeg rendering engine aligns perfectly with Zing's S3/S4 architecture (Breakdown -> edit plan -> rendering). We should borrow its design for representing edit plans as structured objects.

### ClipForge — https://github.com/DarkPancakes/clipforge
- **What:** Automated vertical video shorts generator. Automates script generation, image/video asset generation, text-to-speech rendering, and FFmpeg layout assembly.
- **License:** MIT (verified). **Health:** Active, recently pushed in 2026.
- **Verdict: BORROW (pipeline layout & FFmpeg wrappers).** Excellent practical reference for building Python wrappers around complex FFmpeg filters (e.g. centering visual focus, styling vertical subtitles). Not a direct dependency as its pipeline is monolithic and coupled to specific cloud LLM/TTS services.

---

## Measurement-tooling scan (Lane A, SG-4, 2026-07-19)

Scoped to the study engine's ground: word timing, audio tagging, caption
OCR, and one 2026 arrival. Facts verified against LICENSE files and repo
APIs on 2026-07-19; all claims sourced in-line.

### CrisperWhisper — https://github.com/nyrahealth/CrisperWhisper
- **What:** Verbatim Whisper-variant with the best published word-level
  timestamps + filler/disfluency detection (INTERSPEECH 2024; cited in
  R1-lane-a-measurement.md).
- **License: CC-BY-NC-4.0** — GitHub shows "Other"; the LICENSE file is
  NonCommercial. The HF `faster_CrisperWhisper` CT2 conversion is also
  CC-BY-NC, and its card disclaims the timestamp accuracy of the
  original. **Health:** 971 stars, main dormant since 2025-06.
- **Verdict: SKIP as dependency (license trap — flagged so the R1 "S2
  word-timing upgrade path" never reaches for it).** whisperX (BSD-2)
  remains the licensed upgrade path. At most a user-installed optional
  backend, never bundled.

### panns_inference — https://github.com/qiuqiangkong/panns_inference
- **What:** pip wrapper for PANNs CNN14 AudioSet tagging (the R1 pick 5
  S2 anchor candidate for calibrated has_music confidence).
- **License:** MIT. **Health:** dormant (last push 2024-03) but frozen-
  good; underlying audioset_tagging_cnn also MIT.
- **Verdict: REUSE (S2 music-tagger anchor).** Dormancy acceptable for
  frozen weights + thin wrapper. YAMNet is now effectively SKIP: the
  official repo is Keras-2-locked (incompatible with TF>=2.16 defaults);
  torch ports are tiny/low-bus-factor.

### CED via sherpa-onnx — https://github.com/k2-fsa/sherpa-onnx
- **What:** Apache-2.0 inference runtime (13.6k stars, very active)
  shipping prebuilt **CED audio-tagging ONNX models**; the HF
  `mispeech/ced-*` weights are tagged Apache-2.0 (Xiaomi team) even
  though the CED training repo is GPL-3.0.
- **Verdict: BORROW/watch.** The modern small-tagger slot R1 wanted —
  but the code-GPL vs weights-Apache conflict is unresolved upstream;
  if adopted, depend only on sherpa-onnx + HF weights, never the
  training repo. PANNs stays the safe first choice.

### OnnxTR — https://github.com/felixdittrich92/OnnxTR
- **What:** docTR OCR on onnxruntime — no torch/TF, 8-bit CPU models.
- **License:** Apache-2.0. **Health:** active (v0.8.1 2026-02, pushed
  2026-07); single maintainer.
- **Verdict: BORROW (document-OCR fallback).** Same inference-engine
  profile as our rapidocr pick; document-trained so not a caption
  replacement, but the right shape if Zing ever reads slides/screenshots.

### VideOCR — https://github.com/timminator/VideOCR
- **What:** Burned-in subtitle extraction (PaddleOCR), GUI + standalone
  CLI binaries; the actively maintained successor of videocr-PaddleOCR
  (which is now ~11 months dormant).
- **License:** MIT. **Health:** 704 stars, v1.5.1 2026-04, active.
- **Verdict: BORROW (already informed the S1 caption pipeline; upgrade
  reference for S2 OCR hardening).** Pin to the local Paddle engine —
  v1.5 added a cloud Google Lens hybrid path we must not inherit.

### claude-video — https://github.com/bradautomates/claude-video
- **What:** 2026 arrival (created 2026-04, already 9.1k stars): gives
  coding agents video comprehension — yt-dlp fetch, ffmpeg keyframe/
  scene-change extraction with dedup, caption extraction, cloud Whisper
  fallback; packaged as agent skills.
- **License:** MIT. **Health:** very active.
- **Verdict: BORROW (recipes, not dependency), plus market signal.** Its
  frame-dedup trick for slow fades is worth reading against our
  dissolve gate; transcription falls back to cloud APIs (against our
  local-first stance) and it's an agent skill, not a library. Signal:
  agent-consumable video analysis is now a recognized category — Zing's
  MCP surface is well positioned.

---

## SG-4 video-creation scan · 2026-07-19 · Lane C (standing generator)

Method: searched GitHub's video-editing, video-processing, creator-tools,
subtitle, and media topics, then checked each repository's README, license,
release history, and GitHub API metadata on 2026-07-19. These five repositories
were not present in this file before the scan. Star counts are discovery signals,
not quality scores.

### OpenCut-app/OpenCut — https://github.com/OpenCut-app/OpenCut

- **What:** A local-first, web-based video editor. Its in-progress rewrite
  separates a Rust editor core from an Editor API, plugins, scripting, a
  headless automation surface, and MCP.
- **License:** MIT. **Health:** 75,463 stars and 7,593 forks; pushed
  2026-07-17. The latest release is v0.3.0 (2026-04-15), but the maintainers say
  the rewrite is still being designed and is not ready for outside
  contributions.
- **Verdict: BORROW/WATCH, not a dependency.** The useful reference is the
  product boundary: one editing model exposed through interactive, headless,
  script, plugin, and MCP surfaces. Zing should compare that separation with its
  CLI/MCP parity as long-form and landscape output expands. The rewrite is too
  unsettled, and its Rust/web stack is too distant from Zing's Python/FFmpeg
  renderer, to justify reuse now.

### tmoroney/auto-subs — https://github.com/tmoroney/auto-subs

- **What:** A local-first subtitle application for DaVinci Resolve, Premiere
  Pro, and After Effects. It combines local transcription, diarization,
  translation, styled caption presets, per-word highlighting, and native
  caption-track import.
- **License:** MIT. **Health:** 3,846 stars and 250 forks; pushed
  2026-07-19. It has 39 releases, with v3.6.2 published 2026-06-09.
- **Verdict: BORROW.** Study its NLE-facing caption export, preset model,
  word-timing markers, and overlap/conflict handling for Zing's landscape and
  long-form caption output. Do not reuse the application wholesale: its
  Rust/TypeScript/C++/Lua integration stack overlaps functionality Zing already
  gets from faster-whisper, pysubs2, and FFmpeg.

### Kemerd/premiere-agent — https://github.com/Kemerd/premiere-agent

- **What:** A local conversational editing prototype for Premiere. It merges
  speech, one-frame-per-second visual captions, and audio tags into a
  chronological evidence stream, pins edit boundaries to words, runs a boundary
  preflight, and exports FCPXML, XMEML, and SRT.
- **License:** none detected; the repository has no LICENSE file and GitHub
  reports no license. **Health:** 13 stars and 3 forks; created 2026-04-26 and
  pushed 2026-07-08.
- **Verdict: SKIP as code; BORROW concepts only.** With no license, its source
  is not reusable. Independently implement only the high-level ideas that fit
  Zing: cache expensive perception once, merge evidence on one timeline, and
  validate word-pinned boundaries before rendering. Do not copy code or data
  structures.

### PyAV-Org/PyAV — https://github.com/PyAV-Org/PyAV

- **What:** Python bindings over FFmpeg's container, stream, packet, codec, and
  frame libraries. It offers frame-accurate in-process access where an FFmpeg
  subprocess or raw pipe becomes awkward.
- **License:** BSD-3-Clause. **Health:** 3,244 stars and 439 forks; pushed
  2026-07-16. v18.0.0 was released 2026-07-02.
- **Verdict: SKIP for the renderer.** Zing intentionally relies on the user's
  FFmpeg executable, which keeps the dependency and codec boundary simple.
  PyAV's own guidance favors the CLI when it already solves the job. Revisit it
  only if a measured detector bottleneck requires packet timestamps or random
  frame access that the current subprocess boundary cannot provide cleanly.

### Vanilagy/mediabunny — https://github.com/Vanilagy/mediabunny

- **What:** A zero-dependency TypeScript media toolkit for browser-side
  reading, writing, conversion, and streaming of formats including MP4, WebM,
  MP3, and HLS. Its pipeline is lazy and built around WebCodecs, muxers, and
  demuxers.
- **License:** MPL-2.0. **Health:** 6,731 stars and 274 forks; pushed
  2026-07-18. It has 161 releases, with v1.50.9 published 2026-07-18.
- **Verdict: BORROW design only; SKIP the dependency.** Its incremental,
  browser-native preview/export architecture is a useful reference for a future
  web surface. MPL-2.0 falls outside Zing's current MIT/BSD/Apache dependency
  policy, and its TypeScript/WebCodecs runtime does not serve the Python/FFmpeg
  renderer.

**Scan conclusion:** no direct dependency cleared both the architectural and
licensing bars. The most actionable borrow is a combined pattern: AutoSubs'
native caption-track ergonomics plus premiere-agent's cached chronological
evidence and boundary preflight. OpenCut is the product-surface watch item for
keeping interactive, headless, scripted, and MCP editing behavior aligned.

---

## SG-4 targeted scan · 2026-07-19 · Lane B (bot-gating priority + assemble)

Trigger: gate-pack defect D-9 — YouTube bot-gating blocks all fresh
fetches. Licenses verified per repo.

### Ground truth (verified-data)
Since yt-dlp 2025.11.12 an external JS runtime is REQUIRED for full
YouTube support (deno default-enabled; yt-dlp/yt-dlp#15012); GVS PO
tokens are required for the mainstream clients (PO Token Guide), manual
token extraction is officially "no longer recommended" (tokens bind
per-video-ID), and flagged IPs get LOGIN_REQUIRED across all clients
(yt-dlp#15865) — matching our gate failures exactly.

### bgutil-ytdlp-pot-provider — https://github.com/Brainicism/bgutil-ytdlp-pot-provider
- **What:** the community-standard PO-token provider plugin (BotGuard
  via BgUtils); HTTP sidecar on :4416 (Docker/Node≥20/Deno≥2) or slow
  per-invocation script; pip-installable; listed first in the official
  PO Token Guide; TubeArchivist integrates it by name.
- **License: GPL-3.0** (verified). Health: 618 stars, v1.3.1 (2026-03),
  author is a yt-dlp maintainer.
- **Verdict: REUSE as optional USER-INSTALLED plugin — never vendored
  or bundled.** GPL-3.0 cannot enter Zing's dependency graph; a
  user-installed yt-dlp plugin running inside yt-dlp's own plugin
  system keeps Zing MIT-clean (TubeArchivist takes the same posture).
  Caveat per its own README: a PO token improves legitimacy, it does
  not defeat hard IP flags.

### yt-dlp-getpot-wpc — https://github.com/coletdjnz/yt-dlp-getpot-wpc
- MIT (verified), core-maintainer-authored, but requires a live Chrome
  window during fetches. **Verdict: SKIP as primary / document as
  fallback** — wrong shape for a headless CLI/MCP pipeline.

### Peer practice (verified-data)
cookies.txt / --cookies-from-browser is yt-dlp's first-line suggestion
but ties fetches to a Google account (flag risk, more ToS exposure than
anonymous use); TubeArchivist ships an opt-in bgutil sidecar URL
setting; Pinchflat/MeTube issue trackers show cookies alone are flaky.

### Recommendation for Zing (filed to NOTES for queueing)
1. Doctor: detect yt-dlp ≥2025.11.12 + deno (shipped in D-9 fix) PLUS
   PO-token-provider registration; map "Sign in to confirm"/
   LOGIN_REQUIRED fetch failures to a distinct actionable diagnostic.
2. Optional plugin support: document `pip install
   bgutil-ytdlp-pot-provider` + deno as the recommended setup; config
   knob for provider base_url + cookies file as LAST resort (account-
   flag warning). Do not vendor (GPL).
3. Docs troubleshooting order: update yt-dlp → deno → bgutil → cookies,
   under the inherited personal-use disclaimer (R5). ToS exposure ≈
   standard yt-dlp personal use.

### Secondary: VMAF — https://github.com/Netflix/vmaf
- Netflix perceptual video-quality metric; ffmpeg `libvmaf` filter;
  BSD-3-Clause-Patent (verified); 5.4k stars, v3.2.0 + new model gen
  2026-06 — very alive.
- **Verdict: REUSE (render-QA sprint).** Zing already shells to ffmpeg;
  ssim/psnr filters are zero-dep today and libvmaf where available —
  perceptual scoring of rendered output vs reference frames nearly
  free. Natural extension of Lane C's content-probe oracle.

### Secondary: captacity — IDEAS ONLY (re-confirmed)
MoviePy-based word-highlight captions; nothing found displaces
pysubs2 + \k/\t karaoke tags for word-timed animation.

**Scan summary:** bot-gating is solved-but-operational — ecosystem
consensus is deno + bgutil sidecar + cookies fallback; Zing should
DETECT and DOCUMENT, never bundle (GPL). VMAF's 2026-06 refresh makes
ffmpeg-native perceptual render QA the clear secondary win.

---

## SG-4 creator-pipeline scan · 2026-07-19 · Lane C

Method: checked GitHub's [daily trending page](https://github.com/trending?since=daily)
and the video-editor, automatic-video-editing, subtitles, video-processing, and
creator-tools topic results on 2026-07-19. The four candidates below were absent
from this survey. Repository metadata, default-branch source, release history,
and license files were checked directly; stars helped discovery but did not
decide the verdicts.

### remyxai/FFMPerative — https://github.com/remyxai/FFMPerative

- **What:** A Python experiment that turns text instructions into calls from a
  fixed catalog of FFmpeg tools. Generated code goes through an AST interpreter
  that accepts only registered functions and a small set of expression types.
- **License:** MIT. **Health:** 204 stars and 14 forks; pushed 2026-06-07.
  There is no GitHub release, and GitHub's contributor list attributes 156 of
  159 contributions to one maintainer.
- **Verdict: BORROW the bounded-tool pattern; SKIP the dependency.** The
  allowlisted interpreter is a useful reference if Zing ever lets a model
  propose renderer operations. Zing would still need a dry-run plan, path
  confinement, media preflight, and explicit overwrite approval before
  execution. The package has no release line, pins none of its seven Python
  dependencies, and wraps `ffmpeg-python`, which this survey already rejected
  as an unnecessary renderer abstraction.

### YaoFANGUK/video-subtitle-extractor — https://github.com/YaoFANGUK/video-subtitle-extractor

- **What:** A local hard-subtitle extractor that finds text regions, runs
  PaddleOCR, removes duplicate lines, and emits SRT or text. It offers fast,
  automatic, and frame-by-frame modes across CPU, CUDA, DirectML, and ONNX
  runtimes.
- **License:** Apache-2.0. **Health:** 9,186 stars and 927 forks; pushed
  2026-04-09. Release 2.2.0 shipped 2026-04-04, and five contributors are
  visible in GitHub's first contributor page.
- **Verdict: BORROW its fixture taxonomy; SKIP the application dependency.**
  Zing's existing caption-region and OCR work should be tested against VSE's
  useful failure classes: persistent logos, bilingual lines, duplicate text,
  sparse subtitles, and fast-mode misses. The PySide/Paddle application stack
  is much larger than Zing's evaluator needs, and the bundled OCR model files
  require a separate provenance audit before any weights are reused.

### zhouxiaoka/autoclip — https://github.com/zhouxiaoka/autoclip

- **What:** A self-hosted highlight generator. It chunks transcript-derived
  topics, asks an LLM for time ranges and scores, persists intermediate JSON and
  failed responses, then cuts the selected clips through a FastAPI/Celery/Redis
  pipeline.
- **License:** MIT. **Health:** 6,133 stars and 1,207 forks; pushed
  2026-06-03, with release v1.2.0 published the same day. GitHub lists one code
  contributor, so maintenance is active but concentrated.
- **Verdict: BORROW the inspectable intermediate artifacts; SKIP the scoring
  code and service stack.** Saving each chunk's raw response and parsed timeline
  makes an LLM failure debuggable. Its uncalibrated single-model “exciting”
  score, silent chunk skipping, remote Qwen default, and Redis/Celery/web
  footprint do not fit Zing's measured-facts-first evaluator.

### walterlow/freecut — https://github.com/walterlow/freecut

- **What:** A local browser editor with multi-track timelines, caption tracks,
  scene search, proxy and waveform caches, and worker-backed WebCodecs export.
  Subtitles can be burned in, written as a sidecar, or embedded as a soft track.
- **License:** MIT. **Health:** 1,800 stars and 273 forks; pushed 2026-07-18.
  The repository has no tagged release; GitHub's contributor list shows one
  maintainer accounting for 2,188 contributions and three small contributors.
- **Verdict: BORROW the export contract; SKIP the dependency.** Its explicit
  container/codec capability checks, subtitle delivery modes, render queue,
  and project-schema validation are strong references for Zing's landscape and
  long-form renderer. The TypeScript/WebGPU/WebCodecs runtime cannot simplify
  Zing's Python/FFmpeg implementation, and the lack of a release line makes it
  a moving design reference rather than a component to pin.

**Scan conclusion:** none of the four should enter Zing's dependency graph.
FreeCut supplies the clearest renderer contract to borrow; VSE supplies the
best missing caption-OCR fixtures. FFMPerative and AutoClip reinforce one
boundary Zing should keep: model output must remain inspectable and constrained
before it can mutate media.
