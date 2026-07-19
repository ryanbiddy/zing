# Zing Sprint 4 — Assemble + Taste Onboarding

Opened 2026-07-19 under LAUNCH MODE (see uoink handoff\suite-split\
LAUNCH-PLAN.md): no Ryan gates until launch Decision Week — all gates
internal (eval + truth docs + orchestrator review). S1-S3 discipline
verbatim. S3's remaining item (Lane B direct.md) completes first.

## Track 1 — Assemble (ROADMAP S4 as amended by OSS survey)

- **Lane C:** TTS provider interface + local default via kokoro-onnx
  (MIT; espeak-ng stays OUT of default install) rendering VO tracks from
  scripts; `.otio` export (OpenTimelineIO) + the NLE export bar
  (auto-editor's Premiere/FCP exports as reference); render-quality pass
  with content probes extended to VO tracks.
- **Lane B:** provider plugin surface (ElevenLabs as optional plugin,
  key-gated, never required); MCP tools for render/export flows; honest
  degraded states when no TTS present.
- **Lane A:** EDL-production support — from direction output + keepers to
  a draft EDL (the measured half: keeper trims mapped onto a timeline
  skeleton the AI's assembly_notes can adjust).

## Track 2 — Taste Onboarding (new requirement, Ryan)

- **Lane D (curation):** vetted reference sets per preset pack —
  ai-tech-talking-head, viral-tiktok-reels, informative-explainer, vlog,
  product-launch; vertical + horizontal variants where the genre supports
  it; 5-8 live-verified references each with one-line rubric-cited "why";
  D-Q9 discipline (the re-verification lesson applies).
- **Lane A:** preset-pack builder — batch-study reference sets + build
  the preset StyleProfiles with full provenance; regeneration command per
  pack (truth-hash lesson).
- **Lane B:** `zing setup` onboarding flow (CLI) + MCP onboarding tools:
  list/pick presets, paste-your-own-links path building a personal
  profile alongside; prompt pack section for "this taste in words"
  generation; multiple named tastes first-class.
- **Lane C:** preset-pack eval — packs rebuild reproducibly from their
  reference lists; profile drift detection when references restudy;
  setup-flow smoke in CI (mocked studies).

## Internal gates

Track 1: a direction output for the raw-practice clip renders end-to-end
to a watchable draft with VO + captions + exports that open in an NLE.
Track 2: fresh workspace → `zing setup` → pick ai-tech-talking-head →
paste 2 extra links → both preset and personal profiles exist, honest
provenance, compare-judgment runs against each. Cross-review + fix
rounds per house process before S5.
