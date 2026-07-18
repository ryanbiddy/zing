# R1-A — Measurement science (Lane A)

Researcher: Lane A (Claude Fable 5). Date: 2026-07-18.
Method: four parallel web-research agents (shot detection, word timestamps,
caption OCR, audio), every claim source-linked and confidence-flagged;
synthesis and picks are mine. Confidence key per assignment rules:
**[V]** verified-data (paper/benchmark/official doc), **[P]**
practitioner-consensus, **[S]** single-opinion.

TL;DR of what changed my build plan vs. the defaults:

1. The `rapidocr-onnxruntime` package everyone (including PRIOR-ART-OSS)
   recommends is frozen at PP-OCRv4-era models; the live package is
   `rapidocr` 3.9.x with PP-OCRv6 bundled — two model generations better on
   stylized text.
2. distil-whisper variants are disqualified for word timing (their
   alignment heads were never trained); and large-v3 measurably
   hallucinates more than large-v2 — so the "obvious" model choices are
   both wrong for a measurement tool.
3. faster-whisper's built-in VAD defaults (400ms pad, 2s min-silence) would
   silently inflate our pinned `speech_ratio` — must override with
   upstream-style parameters.
4. PySceneDetect's `min_scene_len` default (0.6s) silently merges
   legitimate fast cuts on exactly our content; and on the only short-form
   benchmark that exists it trails neural methods by 6–10 F1 — good enough
   for S1, but the S2 upgrade path should be planned now.

---

## 1. Shot-boundary detection

### The candidates on published data

- PySceneDetect: BSD-3, v0.7 (May 2026, overhauls timestamps for VFR
  video), actively maintained. [V]
  https://www.scenedetect.com/changelog/ ·
  https://github.com/Breakthrough/PySceneDetect
- Official PySceneDetect benchmark (frame-exact tolerance): [V]
  https://github.com/Breakthrough/PySceneDetect/blob/main/benchmark/README.md
  - **AutoShot SHOT dataset (the only short-form benchmark)**:
    AdaptiveDetector F1 **73.86** (R 70.59 / P 77.46); ContentDetector
    69.26; HashDetector 64.84.
  - BBC Planet Earth: AdaptiveDetector F1 91.59; ContentDetector 86.69.
  - ClipShots hard cuts: ContentDetector 55.84 ≈ AdaptiveDetector 55.75
    (precision collapses ~41% on this dataset for both).
  - Gradual transitions are a known blind spot: ClipShots fades —
    AdaptiveDetector F1 23.96.
- TransNetV2 (MIT, research-frozen; maintained inference port
  `transnetv2-pytorch` on PyPI, June 2025): SHOT F1 **0.799**, BBC 96.2,
  ClipShots 77.9. Note: its eval protocol allows a 2-frame miss, so
  numbers aren't exactly comparable to PySceneDetect's tolerance-0 table.
  [V] https://github.com/soCzech/TransNetV2 ·
  https://ar5iv.labs.arxiv.org/html/2008.04838 ·
  https://pypi.org/project/transnetv2-pytorch/
- AutoShot (CVPR-W 2023): SHOT F1 **0.841** — best on short-form — but the
  model is effectively unusable (weights behind Baidu Drive, inference
  questions unanswered since 2023). The dataset is the usable artifact.
  [V] https://ar5iv.labs.arxiv.org/html/2304.06116 ·
  https://github.com/wentaozhu/AutoShot/issues/7
- ffmpeg scdet: score = clip(min(mafd, diff), 0, 100), default threshold
  10; **no published accuracy on any standard dataset anywhere**; no flash
  or min-shot-length handling — post-processing is on you. [V]
  https://raw.githubusercontent.com/FFmpeg/FFmpeg/master/libavfilter/vf_scdet.c
  · [P] https://blog.gdeltproject.org/using-ffmpegs-scene-detection-to-generate-a-visual-shot-summary-of-television-news/
- Production practice: NVIDIA NeMo Curator and CineTrans both pick neural
  (TransNetV2) for shot splitting at scale; CineTrans measured PySceneDetect
  65.5% vs TransNetV2 87.0% on their 200-video set. [V]
  https://docs.nvidia.com/nemo/curator/nemo-curator/nemo_curator/models/transnetv2
  · https://arxiv.org/html/2508.11484

### Short-form-specific failure modes

- AutoShot's error analysis names the mechanisms: multi-stage gradual
  transitions; **"vertically ternary structured" videos** (static
  branding/caption bands top+bottom dilute whole-frame difference signals —
  this hurts every whole-frame method, PySceneDetect and ffmpeg included);
  rapid intra-shot change (game/VFX content). ~54% of missed boundaries are
  gradual transitions. [V] https://ar5iv.labs.arxiv.org/html/2304.06116
- SHOT average shot length is **2.59s** and fast montages go well under
  0.6s — PySceneDetect's defaults (`min_scene_len` 15 frames API / 0.6s
  CLI, a documented inconsistency) will silently merge real cuts. [V]
  https://github.com/Breakthrough/PySceneDetect/issues/477
- Flash/strobe false positives: still an open issue (#35, open for years);
  the 0.6.4 flash-suppression filter helps ContentDetector only. [V]
  https://github.com/Breakthrough/PySceneDetect/issues/35

## 2. Word timestamps

### Accuracy: the collar hides the truth

- WhisperX paper (200ms collar): native Whisper 85.4% P on Switchboard vs
  WhisperX 93.2% — looks close. [V] https://arxiv.org/html/2303.00747v2
- At **50ms tolerance** the picture inverts: native Whisper DTW alignment
  **41.2% F1** vs WhisperX 79.9% vs MFA 91.0% (TIMIT). Native timestamps
  are fine at ±0.1–0.2s, not at frame accuracy. [V]
  https://arxiv.org/html/2509.09987v1
- WhisperX measured word-boundary error on clean speech: **~24ms median /
  ~34ms mean**. [V] https://arxiv.org/pdf/2406.19363
- **But WhisperX is fragile under noise**: with added noise its F1 falls
  76.7 → **59.0**, below whisper-timestamped (68.3); its English alignment
  model is trained on clean audiobooks. [V]
  https://arxiv.org/html/2408.16589v1 (CrisperWhisper, INTERSPEECH 2024)
- **Nobody has published word-timestamp accuracy on music-bed short-form
  content for any tool**; even purpose-built lyrics aligners only reach
  ~0.2s MAE. [V] https://arxiv.org/abs/2306.07744
- Known native failure modes: first word after long silence up to ~10s off
  ([V] https://github.com/SYSTRAN/faster-whisper/issues/125); pauses
  absorbed into neighboring words due to space tokenization ([V]
  CrisperWhisper above); jingle music causes total desync periods ([P]
  https://github.com/linto-ai/whisper-timestamped).

### Model choice

- **distil variants are disqualified for word timing**: distillation only
  included segment-level timestamps; word-level rides on alignment heads
  with no additional training. [V]
  https://huggingface.co/distil-whisper/distil-large-v3.5/discussions/6
- **large-v3 hallucinates more than large-v2**: Deepgram measured ~4x on
  their real-world suite ([V, vendor]
  https://deepgram.com/learn/whisper-v3-results); corroborated by
  community repros ([P] https://github.com/SYSTRAN/faster-whisper/issues/777
  · https://github.com/openai/whisper/discussions/2280).
- Hallucination on non-speech audio is systematic: 40.3% of non-speech
  inferences hallucinate ("thank you", "thanks for watching"); **Silero VAD
  preprocessing cuts hallucination-driven WER from >100% to 8–11%** — the
  single biggest mitigation lever. [V] https://arxiv.org/html/2501.11378v1
- faster-whisper practicals: v1.2.1 (Oct 2025) ships Silero VAD v6; int8
  halves VRAM at negligible accuracy cost; 13min/large-v2 in ~1min on GPU,
  CPU small-int8 ~7.6x realtime — a 60s short transcribes in seconds either
  way, well inside the performance budget. [V]
  https://github.com/SYSTRAN/faster-whisper
- Word probability = mean token softmax per word; faster-whisper itself
  uses probability <0.15 + duration anomalies as its internal hallucination
  score — precedent for using it as our confidence field. Calibration
  degrades under noise (overconfident at low SNR). [V]
  https://raw.githubusercontent.com/SYSTRAN/faster-whisper/master/faster_whisper/transcribe.py
  · https://arxiv.org/html/2509.07195v1
- Mitigation set with evidence: `vad_filter=True`,
  `condition_on_previous_text=False` (whisperX's default; stops error
  propagation), thresholds at defaults, optional
  `hallucination_silence_threshold`. [V/P]
  https://github.com/openai/whisper/discussions/679

### VAD parameters matter for OUR metric

- faster-whisper's `VadOptions` defaults are tuned for transcription
  chunking, not measurement: **min_silence_duration_ms=2000,
  speech_pad_ms=400** (upstream Silero: 100/30). Using them would merge
  every pause <2s into "speech" and pad 0.8s per segment — materially
  inflating the pinned `speech_ratio`. It exposes a standalone
  `get_speech_timestamps()` (Silero v6 ONNX bundled) we can call with
  honest parameters. [V]
  https://github.com/SYSTRAN/faster-whisper/issues/477 ·
  https://raw.githubusercontent.com/SYSTRAN/faster-whisper/master/faster_whisper/vad.py
- Silero v6 known limitation, straight from the release notes: "music with
  voice-like instruments" — speech_ratio will over-count on melodic beds;
  corroborate near decision boundaries. [V]
  https://github.com/snakers4/silero-vad/releases

## 3. Caption OCR

### Engine choice

- **Package landmine**: `rapidocr-onnxruntime` is the legacy name, frozen
  at 1.4.4 (PP-OCRv4-era). The live package is **`rapidocr` 3.9.1 (July 2,
  2026)**, Apache-2.0, which since 3.9.0 bundles **PP-OCRv6-small** det+rec
  in the wheel (~29MB) and needs `onnxruntime` installed alongside. [V]
  https://pypi.org/project/rapidocr/ ·
  https://github.com/RapidAI/RapidOCR/releases
- PP-OCRv5→v6 is a big deal for stylized text: recognition accuracy 53.0%
  (v4) → 80.1% (v5) → +5.1% more (v6), with explicit gains on street view,
  web images, digital displays. [V, vendor]
  https://paddlepaddle.github.io/PaddleOCR/main/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5.html
  · https://huggingface.co/blog/PaddlePaddle/pp-ocrv6
- Tesseract is document-trained and weak on scene text (52% vs EasyOCR 82%
  on curved/meme text [S] https://gigagpu.com/paddleocr-vs-tesseract-vs-easyocr/;
  academic assessment [V]
  https://link.springer.com/chapter/10.1007/978-981-19-1324-2_13), and its
  confidence is documented un-calibratable (no universal threshold yields
  clean output). [V] https://arxiv.org/pdf/0907.0418
- EasyOCR: Apache-2.0 but ~500MB torch install, 1.8GB RAM, **no release
  since Sept 2024**. Better than Tesseract on stylized text but the
  weight/maintenance trade kills it as default. [V]
  https://github.com/JaidedAI/EasyOCR
- **Known RapidOCR weakness to engineer around**: PP-OCR English models
  have a long-standing word-spacing failure ("Thispaper" concatenations,
  including a 3.x regression) — captions are short multi-word phrases, so
  this needs a repair pass (word-box gap heuristics or wordsplit). [V]
  https://github.com/PaddlePaddle/PaddleOCR/issues/15877
- **Emoji is a hard no for every classic engine** (dictionary-constrained
  CTC recognizers physically cannot emit emoji — dropped or garbled). VLM
  OCR would be needed; not S1. Record honestly. [V]
  https://github.com/PaddlePaddle/PaddleOCR/discussions/12302
- **No published benchmark covers TikTok-style burned-in captions at
  all** — every comparison is a proxy. [V-absence]

### Strategies from shipping subtitle-extraction tools

- The videocr family (MIT/Apache, several generations) converges on:
  crop to caption region; sample 3–5 fps; **cheap pixel-diff gate before
  OCR** (videocr-PaddleOCR: >100 differing pixels with per-pixel delta >25
  → OCR, else reuse previous result); cluster consecutive hits into events
  by Levenshtein ratio ≥0.8 with a temporal merge gap; conf_threshold 0.75
  for PaddleOCR-family scores. [V]
  https://github.com/devmaxxing/videocr-PaddleOCR ·
  https://github.com/timminator/VideOCR (active, Apr 2026, SSIM gating)
- For **word-by-word pop captions** (our `words_visible=1` style), plain
  Levenshtein clustering under-merges once the phrase grows; the one
  purpose-built solution found is CaptiOCR's incremental scheme (suffix
  alignment via difflib, novelty scoring); the pragmatic variant is
  **cluster by prefix-containment and keep the maximum-length string per
  event**. [V] https://github.com/carlosacchi/captiocr
- Confidence thresholds are NOT transferable between engines (EasyOCR
  scores run systematically lower than PaddleOCR's). [S/P]
  https://deepwiki.com/sslastnikov/ai_center_gpb/4.3-paddleocr-and-easyocr

## 4. Audio

### VAD

- Silero VAD v6 line (6.2.1, Feb 2026), MIT, <1ms/chunk CPU; self-reported
  ROC-AUC 0.97 vs WebRTC 0.73 on a multi-domain set; WebRTC VAD scores
  0.00 accuracy on noise-only audio and py-webrtcvad is effectively
  discontinued. [V] https://github.com/snakers4/silero-vad/wiki/Quality-Metrics
  · https://snyk.io/advisor/python/webrtcvad
- Batch API defaults worth keeping: threshold 0.5, min_speech 250ms,
  min_silence 100ms, pad 30ms. [V]
  https://raw.githubusercontent.com/snakers4/silero-vad/master/src/silero_vad/utils_vad.py

### Music/speech discrimination

- **inaSpeechSegmenter is structurally wrong for "music under speech"**:
  its label scheme tags speech-over-music as speech; independent
  AVASpeech-SMAD eval shows music recall 48.8% on co-occurring content.
  Also drags TensorFlow. [V] https://ar5iv.labs.arxiv.org/html/2111.01320
- CED (the attractive small modern tagger) is **GPL-3.0** — off the table.
  [V] https://github.com/RicherMans/CED
- Clean-licensed taggers: YAMNet (Apache repo, 3.7M params, AudioSet mAP
  0.306) and PANNs (MIT, mAP 0.431, heavier); practitioners threshold the
  Music class at ~0.15–0.3 on ~1s hops. [V/P]
  https://github.com/tensorflow/models/blob/master/research/audioset/yamnet/README.md
  · https://github.com/qiuqiangkong/panns_inference ·
  https://arxiv.org/pdf/2603.25750
- Microsoft's MusicNet paper proves background-music detection under
  speech+noise is tractable with a tiny CNN (81.3% TPR at 0.1% FPR) — no
  released weights, cited as feasibility evidence. [V]
  https://arxiv.org/abs/2110.04331
- Pure-DSP heuristics (spectral flatness, 4Hz modulation energy) have a
  sound feature basis but **no published validated thresholds** — don't
  ship as the only signal. [V-absence]
  https://librosa.org/doc/latest/generated/librosa.feature.spectral_flatness.html
  · https://engineering.purdue.edu/~malcolm/interval/1996-085/

### Loudness

- The pinned per-1s RMS dBFS curve needs `asetnsamples` to make "per
  second" mean anything: `-af asetnsamples=<sr>,astats=metadata=1:reset=1,
  ametadata=print:key=lavfi.astats.Overall.RMS_level` — without it,
  "per frame" is whatever the decoder emits. [V]
  https://github.com/mateors/ffmpeg/blob/master/statistics.md ·
  https://ayosec.github.io/ffmpeg-filters-docs/8.0/Filters/Audio/astats.html
- ffmpeg also gives a free 10Hz K-weighted LUFS curve
  (`ebur128=metadata=1` → `lavfi.r128.M` every 100ms; first ~400ms is
  window warm-up) — the S2 path if platform LUFS targets matter. [V]
  https://ayosec.github.io/ffmpeg-filters-docs/8.0/Filters/Multimedia/ebur128.html
- Platform targets: only Spotify documents -14 LUFS officially; YouTube
  ~-14 is measured-not-documented; **TikTok/Reels have no primary source**
  (third parties report ≈-16). [V/P]
  https://support.spotify.com/us/artists/article/loudness-normalization/ ·
  https://productionadvice.co.uk/stats-for-nerds/

---

## Lane A implementation picks (justified)

1. **Shot detection: PySceneDetect v0.7, AdaptiveDetector, min_scene_len
   lowered to ~0.3s, flash filter on; detector + threshold recorded in
   `provenance`.** AdaptiveDetector wins the short-form benchmark among
   PySceneDetect options (SHOT F1 73.86 vs 69.26) and BBC, ties ClipShots;
   the min_scene_len override is mandatory because 0.6s merges real
   montage cuts (SHOT avg shot 2.59s). Dep: `scenedetect-headless`
   (BSD-3; opencv-python-headless avoids GUI baggage). ffmpeg scdet
   rejected: unbenchmarked anywhere + no flash/min-length handling.
   **S2 upgrade path, pre-planned**: `transnetv2-pytorch` (MIT) behind the
   same internal interface, bake-off on the eval harness; center-crop
   experiment for vertically-ternary layouts.
2. **Transcription: faster-whisper (MIT), default model `large-v2`
   int8_float16 on GPU / `small` int8 CPU fallback (warned), configurable;
   `word_timestamps=True`, `vad_filter=True`,
   `condition_on_previous_text=False`; per-word probability →
   `Word.confidence`; model + compute recorded in provenance.**
   large-v2 over large-v3 because hallucination is the worst failure mode
   for a measurement tool and v3's regression is multiply attested;
   distil-* disqualified (untrained alignment heads); turbo unmeasured for
   word timing (deeper thread). Native timestamps (±0.1–0.2s typical) meet
   the S1 bar; whisperX (BSD-2) is the S2 upgrade if the eval harness
   shows word-timing misses — knowing its noise fragility means the eval
   must include music-bed clips.
3. **speech_ratio: Silero v6 via faster-whisper's bundled
   `get_speech_timestamps` with upstream-style parameters (threshold 0.5,
   min_silence 100ms, pad 30ms, min_speech 250ms)** — NOT the
   transcription defaults (2s merge + 400ms pad would inflate the pinned
   metric). No extra dependency. Honest skip + warning when faster-whisper
   absent.
4. **Caption OCR: `rapidocr` 3.9.x (Apache-2.0, PP-OCRv6-small bundled) +
   `onnxruntime`** — explicitly NOT `rapidocr-onnxruntime` (frozen,
   PP-OCRv4-era; supersedes the PRIOR-ART-OSS recommendation). Pipeline
   per the shipping-tool consensus: sample 8–10fps in 0–3s / 4fps after
   (binding), cheap pixel-diff gate before OCR, event clustering by
   prefix-containment + Levenshtein ≥0.8 with max-length-string-wins for
   pop captions, drop below confidence 0.75, word-spacing repair via
   word-box gaps. Emoji recorded as a known blind spot in warnings.
   Tesseract rejected (scene-text accuracy + un-calibratable confidence);
   EasyOCR rejected as default (500MB torch, unmaintained since 2024) but
   noted as the A/B candidate on real caption frames.
5. **has_music (S1): VAD-gap heuristic with honest confidence.** Loudness
   floor in non-speech gaps within ~15–20dB of speech-segment level ⇒ bed
   present; `music_confidence` scaled by margin and gap coverage;
   wall-to-wall speech ⇒ has_music=False with low confidence + warning
   ("insufficient non-speech evidence"). Pure-DSP-only detection has no
   validated thresholds, so S2 adds a YAMNet/PANNs anchor for calibrated
   confidence. inaSpeechSegmenter rejected (structurally wrong labels for
   speech-over-music, TF dep); CED rejected (GPL).
6. **Loudness curve: exactly the pinned astats definition**, implemented
   with `asetnsamples=<sample_rate>` so 1-per-second is real; ebur128 M
   curve reserved for S2 LUFS work.

Dependency PRs to come (one per PR, `[study]` extra, licenses in bodies):
`scenedetect-headless` (BSD-3), `faster-whisper` (MIT), `rapidocr`
(Apache-2.0) + `onnxruntime` (MIT).

## Deeper threads

1. **Word-timestamp accuracy on music-bed short-form audio is unmeasured
   anywhere** — for any tool. Proposal: hand-label word onsets on ~20 real
   short clips (mix of clean VO, music bed, on-camera + music) and score
   faster-whisper native vs whisperX on the eval harness; this decides the
   S2 alignment upgrade with our own data instead of clean-audiobook
   benchmarks.
2. **Does center-cropping vertical ternary layouts improve shot
   detection?** AutoShot names static top/bottom bands as a failure
   mechanism for all whole-frame methods; a crop-to-center-band
   preprocessing step is an obvious, cheap, completely unbenchmarked
   mitigation. Golden-set experiment in S2.
3. **PP-OCRv6 on animated caption fonts is untested** (bounce/scale
   styles, motion blur at 4–10fps sampling). A/B `rapidocr` vs EasyOCR on
   ~50 labeled frames from real TikToks, and evaluate word-box-gap spacing
   repair — feeds the S2 OCR hardening the sprint spec already timeboxes.
4. **`large-v3-turbo` word-timestamp quality is unknown** (4 decoder
   layers → fewer alignment heads; nobody has measured it). If it holds
   up, it's a 3–4x speed win for the same honesty budget. Small eval once
   thread 1's label set exists.
5. **No primary-source loudness target exists for TikTok/Reels** — S4
   render normalization currently aims at folklore. Zing can answer this
   empirically: measure integrated LUFS across every studied reference
   video and report the distribution — a taste-corpus datum nobody
   publishes, essentially free once breakdowns accumulate.

Skipped (flagged per rules): PaddleOCR-direct install-weight comparison on
Windows beyond issue reports; TransNetV2 CPU throughput benchmarking
(needed only if the S2 bake-off happens); diarization (out of scope until
multi-speaker matters).
