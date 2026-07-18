# Research round R-3 — full-craft expansion (Ryan, 2026-07-18)

Zing's direction must cover the WHOLE creator craft in plain language:
transitions, sound mix, intros/outros, thumbnails, packaging/upload. Same
rules as R-1: every claim sourced + tier-flagged (T1–T4), Deeper Threads
section required, doc-only deliverables.

- **R3-A · Transitions + sound mix.** (1) Taxonomy of every common
  transition in CapCut / Premiere / DaVinci / Final Cut / TikTok-native
  editing (hard cut, J/L cut, whip pan, zoom punch, dissolve, wipe, match
  cut, speed ramp, glitch, mask...) — per transition: what it looks like,
  when the pros use it, and its DETECTABILITY SIGNATURE (what a frame/audio
  analyzer would see — feeds future measurement). (2) Music volume norms:
  music-under-speech vs action/no-speech vs MIXED segments — practitioner
  numbers (dB under dialogue, LUFS by segment type), how editors handle the
  mix transition. Deliverable: `docs/taste/TRANSITIONS-AND-MIX.md`.
- **R3-B · Intros/outros + thumbnails + upload craft.** (1) What makes a
  great intro/outro by format (research + exemplar practice); which TOOLS
  make genuinely high-quality intros — survey, rank, settle on a few to
  recommend. (2) THE THUMBNAIL CANON: what actually wins on YouTube
  (packaging-first evidence, known A/B practices, the craft rules of the
  top thumbnail designers), and from it a SPEC for Zing's
  thumbnail-prompt generator: pick candidate freeze-frames from the video
  → emit THREE distinct, high-quality image-LLM prompts (generic prompts
  produce bad thumbnails — the prompts must encode the craft rules +
  the video's actual content). (3) YouTube upload/packaging tips (title/
  description/chapters/schedule) with sources. Deliverable:
  `docs/taste/PACKAGING-INTROS-THUMBNAILS.md`.
- **R3-C · AI-editor user sentiment.** Mine Reddit/X/forums for what users
  say about Opus Clip, Descript, CapCut AI, Stanley, Veed, Submagic, etc —
  what they praise, what they hate, where output reads as slop, what
  converts users to paying. Real user voices with links, not marketing.
  Deliverable: `handoff/research/R3-ai-editor-sentiment.md`.
- **R3-D · Grok/X rounds (Ryan-run).** Ryan runs Grok prompts (provided in
  chat) on X-native video mechanics + creator teardowns + tool sentiment;
  results land in `handoff/research/R3-grok-x-findings.md` (paste raw, the
  orchestrator synthesizes).

## R-4 (next wave, seeded now, launch after R-3 lands)

**Creator-genre taste corpus:** identify + study the top creators per genre
— music, sports, comedy, informative/educational, tech, product/launch,
vlog — on EACH platform (YouTube/Shorts, TikTok, X, Instagram Reels).
Per creator: editing signature, hook patterns, packaging, what separates
them from imitators. Feeds genre×platform rubric matrix in docs/taste/.
This is a standing program (AG's exemplar-teardown format at 10x scale),
not one round.

## Product implications (folded into ROADMAP)

- Direction output is PLAIN LANGUAGE for creators ("Record a 2-second
  clip outside — the location jump is your hook"), never jargon-first.
- S2+ measurement candidate: transition classification (needs R3-A
  signatures first; cuts-only until then, honestly labeled).
- NEW S4 deliverable: `zing thumbs` — freeze-frame candidates + 3
  crafted image-LLM prompts per R3-B spec (Zing prompts, the user's image
  model generates; no image generation inside Zing).
- Prompt pack gains intro/outro advisory + upload/packaging checklist
  grounded in R3-B.
