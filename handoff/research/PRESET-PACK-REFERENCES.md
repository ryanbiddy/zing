# Preset-pack reference sets (A-Q14, curated + live-verified 2026-07-19)

Curator: Lane A (reassigned from Lane D per Ryan — verification fit).
**Machine truth lives in `presets/<pack-id>.json`** (stable IDs, URLs,
verification dates — the builder's input); this doc records the method
and the rejection evidence.

## Verification method (every accepted entry, no exceptions)

Two independent live checks per URL on 2026-07-19, by two research
agents: (1) WebFetch of the actual video page — resolves live, page
`<title>` matches the reported title; (2) YouTube oEmbed for the same ID
— exact title, uploader (`author_name`), and orientation
(portrait/landscape dimensions) match. Anything failing either check was
rejected, not guessed. This is the direct response to the D-Q9/D-Q12
staleness lesson that moved curation to this lane.

## The packs (32 references)

| pack | refs | orientation mix | genre rubric |
|------|------|-----------------|--------------|
| ai-tech-talking-head | 7 | 5 vertical + 2 horizontal (Fireship) | talking-head |
| informative-explainer | 5 | 4 vertical + 1 horizontal (Vox) | talking-head |
| product-launch | 6 | 5 horizontal + 1 vertical (Insta360) | tech-launch |
| viral-tiktok-reels | 7 | vertical | talking-head |
| vlog | 7 | 4 vertical + 3 horizontal (Neistat canon) | vlog |

Per-reference one-line rubric-cited "why" lives in each manifest entry.
Anchors worth naming: Cleo Abram's Antarctica short (the project's
original reference exemplar — re-verified live), Zach King's graffiti
illusion (most-viewed Short ever), MrBeast's baguette (most-liked video),
Neistat's "Make It Count" (the vlog-school canon).

## Rejection evidence (the verification working)

- **Misattribution catches:** a "Zach King" short actually uploaded by a
  fan channel; a "Drew Binsky" clip uploaded by a third-party news
  channel; a "Veritasium" clip from a fan compilation account — all
  fetched, all rejected on oEmbed uploader mismatch.
- **Unverifiable-by-pipeline:** Apple's official launch films (embed
  disabled → oEmbed 403, JS-walled pages) — real but unprovable through
  this pipeline, so excluded; Samsung global-channel films likewise
  (replaced with the verifiable Samsung South Africa upload).
- **Suspected-fabricated IDs** appearing only in search summaries (never
  as actual result links) were never used.
- Creators with no verifiable original uploads in the format (Matt
  Wolfe shorts, Nick DiGiovanni, Alan Chikin Chow, Ryan Trahan vertical)
  were dropped rather than represented by re-uploads.

## Known limits

- Durations are approximate (video pages don't expose them to fetch);
  ingest measures the real duration at study time anyway.
- TikTok-native works are represented via the creators' own YouTube
  uploads (TikTok pages block fetches); noted per entry.
- viral-tiktok-reels and informative-explainer map to the talking-head
  rubric until dedicated rubrics exist (rubric-key field is per-manifest
  and trivially updatable).

## Regeneration

`zing profile pack presets/<pack-id>.json` — batch-studies unstudied
references, builds `pack-<pack-id>` StyleProfile, records manifest
sha256 + per-reference outcomes in provenance. Dead references at build
time are excluded WITH named warnings; the profile never silently
pretends. Link-rot upkeep after packs exist stays with Lane D.
