# Research round R-1 — worker assignments (Phase 0.5)

Do this AFTER your Phase-0 plan critique, BEFORE heavy build work. Research
the ground your own lane's implementation depends on, so your build choices
are evidence-based, not defaults.

**Rules for every deliverable**
- Every claim carries a source link. Prefer primary sources (official docs,
  benchmarks, papers, named practitioners with track records) over listicles.
- Flag confidence per claim: verified-data / practitioner-consensus /
  single-opinion.
- End with a **Deeper threads** section: the 3–5 follow-up questions your
  research surfaced that deserve their own round — this feeds the recursive
  research loop (ROADMAP R-track).
- Deliverables are doc-only PRs (normal flow, auto-merge). Do not change
  code or specs from a research PR.
- Timebox: one focused session. Depth beats coverage; flag what you skipped.

## R1-A — Measurement science (Lane A)

Deliverable: `handoff/research/R1-lane-a-measurement.md`
1. Shot-boundary detection: PySceneDetect (content/adaptive) vs TransNetV2
   vs ffmpeg scdet — published accuracy (AutoShot, ClipShots, BBC datasets),
   speed, license, Windows friendliness; short-form failure modes
   (transitions, speed ramps, meme zooms).
2. Word timestamps: faster-whisper native vs whisperX forced alignment —
   accuracy on music-heavy short-form audio; practical GPU/CPU costs.
3. OCR on stylized captions: RapidOCR/PaddleOCR vs Tesseract vs EasyOCR on
   stylized/moving text; frame-sampling and caption-tracking/dedup
   strategies that actually work.
4. Audio: VAD choices (e.g. Silero), music/speech discrimination options,
   loudness via ffmpeg ebur128.
Close with: YOUR concrete implementation picks for Lane A, justified.

## R1-B — Surface & judgment design (Lane B)

Deliverable: `handoff/research/R1-lane-b-surface-judgment.md`
1. Exemplary MCP servers: tool design patterns, naming, error surfaces,
   .mcpb packaging; uoink's MCP surface (64 tools) as the house pattern —
   what to copy, what to avoid.
2. LLM-as-judge best practice: rubric-scoring reliability, known biases,
   structured output for judgments, grounding judgments in hard
   measurements; vision-LLM keyframe analysis patterns.
3. Prompt-pack design: making prompts/study.md produce CONSISTENT judgments
   across different AI models (Claude, GPT) — what techniques exist.
4. Prior art: any MCP-native media/analysis tools worth studying.
Close with: YOUR concrete design picks for Lane B, justified.

## R1-C — Render & eval engineering (Lane C)

Deliverable: `handoff/research/R1-lane-c-render-eval.md`
1. Word-timed captions: .ass karaoke (\k) via libass in ffmpeg vs drawtext;
   TikTok-style pop/bounce effects achievable in libass; emoji + font
   handling on Windows; what breaks.
2. Audio: sidechaincompress ducking configs that sound right; two-pass
   loudnorm to -14 LUFS; pitfalls.
3. Video: vertical scale/pad/crop strategies; x264 preset/CRF choices for
   1080x1920@30 quality-vs-speed on consumer hardware.
4. Eval methodology: prior art on testing media pipelines; tolerance
   selection; mutation testing in Python; ffprobe-based assertions;
   synthetic-fixture generation patterns.
Close with: YOUR concrete engineering picks for Lane C, justified.

## R1-D — Exemplar teardowns (Antigravity — fresh eyes, doc-only)

Deliverable: `handoff/research/R1-exemplar-teardowns.md`
Pick 8–12 acknowledged-great creators/videos across our three genres
(creator talking-head; tech launch/product; vlog; plus TikTok-native
editing). Per exemplar: hook construction, cut rhythm, caption style, sound
use, structure beats, and the ONE thing separating them from their
imitators. Also map the creator-education canon worth mining (respected
editing/YouTube-craft educators and essays — e.g. Every Frame a Painting
school of analysis) with links. This feeds the genre rubrics in
`docs/taste/` alongside the orchestrator's deep-research round.

## What happens next (recursive loop)

The orchestrator mines every deliverable's **Deeper threads** + surprising
findings into round R-2 assignments (worker rounds or deep-research
workflows), and folds accepted findings into lane specs and `docs/taste/`.
Rounds continue until returns diminish. Research never blocks the build —
it lands into specs between sprints.
