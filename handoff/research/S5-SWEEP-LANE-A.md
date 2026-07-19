# S5 Lane A — real-video sweep record

Matrix: {tiktok, instagram, youtube, x} × {short ≤180s, long >180s} ×
{vertical, horizontal}, cells only where the combination exists on the
platform. Per SPRINT-5-D5: cached media is allowed where bot-gating
blocks a live fetch, but every cell is flagged **live** or **cached**,
and fetch-blocked cells get at least two retries at different times.
Sanity = spot-check of the studied Breakdown against the actual video
(duration/dims/fps exact; shots, transcript, captions, loudness
eyeballed for plausibility; warnings honest about anything skipped).

## Cell status

| Platform | Length | Orient | Status | Evidence |
|---|---|---|---|---|
| youtube | short | vertical | **cached** (22 studies) | packs-ws: S4 pack curation, live-verified at study time (2026-07-19); spot-checks below |
| youtube | short | horizontal | **cached** (3 studies) | packs-ws + baseline (`youtube-fhmxo-vikda` 55s 1920x1080 et al.) |
| youtube | long | horizontal | **cached** (7 studies) | packs-ws: 315s–1530s, incl. 25-min podcast-style |
| youtube | long | vertical | **unsourced** | rare but real (vertical VODs/podcast clips); needs live fetch — blocked, see log |
| tiktok | short | vertical | **blocked** | attempt 1 (2026-07-19): "Your IP address is blocked from accessing this post" (khaby.lame post) — retry pending |
| tiktok | short | horizontal | **blocked** | same wall; exists but rare on-platform |
| tiktok | long | vertical | **blocked** | exists (10-min uploads); same wall |
| instagram | short | vertical | **blocked** | attempt 1 (2026-07-19): "empty media response … use --cookies" — login-walled; cookies are Ryan's call |
| instagram | long | * | **blocked** | same; long-form exists (extended reels) |
| x | short | horizontal | **LIVE** ✓ | SpaceX post 1732824684683784516, 114s 1920x1080 — studied 2026-07-19, sanity below |
| x | short | vertical | **unsourced** | exists; next live candidate |
| x | long | horizontal | **unsourced** | exists (premium long uploads) |

Non-cells (combination effectively absent, so out of scope): tiktok
long horizontal, x long vertical — will add if a real counterexample
turns up during sourcing.

## Fetch-wall log (retries required by spec)

- **YouTube**: anti-bot wall ("Sign in to confirm you're not a bot")
  first hit 2026-07-19 after ~28 fetches during A-Q14; re-probed twice
  since, still up as of this record's last update. Cookies route needs
  Ryan.
- **TikTok**: IP-level block on first-ever attempt (2026-07-19). Never
  fetched from this IP before, so this is not rate-limiting from our
  usage — likely datacenter/ISP range blocking. Retry #2 pending at a
  different time.
- **Instagram**: login wall on anonymous access to a major public reel
  (2026-07-19). yt-dlp's suggested fix is cookies; deferred to Ryan.
- **X**: no wall. Fetches work anonymously.

## Live cell: x / short / horizontal — sanity record (2026-07-19)

- URL: https://x.com/SpaceX/status/1732824684683784516 (Starship
  flight-2 launch recap). Slug `x-1732824684683784516` — the `x`
  platform detect's first live exercise: correct.
- Meta: 114.368s measured vs 114.322s in extractor metadata (0.05s
  container delta — fine); 1920x1080@23.976 matches.
- 55 shots in 114s of fast cinematic cuts — plausible on eyeball of
  the shot list. Internal consistency checks (spans, monotonic words,
  in-range captions) all pass.
- Audio honesty is right: music_confidence 0.8, speech_ratio 0.1 —
  it IS a music-driven montage with sparse radio chatter, and the 54
  words are the real launch-control audio ("Attention all operators
  on countdown one, this is the final go/no-go…").
- **Finding SW-1 (measurement quality, filed in NOTES):** the 60
  caption events are largely OCR junk at HIGH confidence (0.75–1.0,
  median 0.88 — the 0.75 conf_threshold cannot filter them): texture
  misreads ('MNNT', 'WN', CJK glyphs off the engine plume) plus
  mangled real text ('4 TEXA'/'TEIA' for the on-screen "STARBASE,
  TEXAS" tag). Cinematic footage without burned-in captions is a
  blind spot: region tracking + confidence assume caption-like text.
  Needs a design decision (lexicality/script heuristic? flag-not-drop
  per measurement honesty?) — proposed as a queue item, not
  unilaterally patched.

## Cached-cell spot-checks

Checked: shot spans within duration and positive, word timestamps
monotonic and within duration, caption events within duration,
provenance present, warnings honest. Platform re-verification (does
the video still match its recorded metadata) is wall-blocked right
now — flagged, retried with the wall retries.

- **yt/short/vertical** `youtube-nlgyv0bmddi` — 43s 1080x1920@24;
  22 shots, 146 words, 64 caption events; internally consistent;
  warnings honestly name OCR sampling limits and inconclusive music
  detection (wall-to-wall speech). PASS.
- **yt/short/horizontal** `youtube-fhmxo-vikda` — 55s 1920x1080@30;
  38 shots, 178 words, 45 caption events; internally consistent. PASS.
  (Also the S1 gate video — spot-checked against the actual video
  frame-by-frame back then.)
- **yt/long/horizontal** `youtube-22wlly7hkp4` — 1530s
  1920x1080@23.976; 220 shots, 3110 words, 1023 caption events;
  internally consistent at 25-min scale. PASS.
