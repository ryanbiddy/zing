# NOTES — Lane B ↔ orchestrator

- **2026-07-18 (orchestrator):** Your Phase-0 critique: all 10 items
  ACCEPTED — full binding resolutions in SPRINT-1-D1.md §Critique
  resolutions (prompt delivery via MCP prompts capability + get_prompt +
  CLI; sync study_video with cheap validation + progress notifications;
  per-section-REPLACE judgment merges with _meta stamps; storage owns
  slug_for + judgment-preserving re-study; doctor tiers + --json + yt-dlp
  staleness check; core-install stdlib-only with [study]/[render]/[all]
  extras; port uoink's stdio skeleton; conftest workspace fixture;
  honest-degradation rule for visual hooks in prompts/study.md;
  get_frames() named as S2 fast-follow). media_path relative semantics now
  documented in schemas.py. Saw PR #5 land storage early — good. Rebase on
  main to pick up the schema changes (warnings/provenance/keyframe fields
  affect what get_breakdown returns).
- **2026-07-18 (orchestrator, post-merge review of #5):** storage PASSES gate review — clean module. One reminder: your critique #3's `_meta` stamp (model?, prompt_version, written_at) is not in storage.save_judgment — stamp it in the MCP save_judgment tool layer as planned, and validate the prompt-pack's required keys there too.
