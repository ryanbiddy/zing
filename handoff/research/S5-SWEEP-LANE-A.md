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
| youtube | short | vertical | **LIVE** ✓ (+22 cached) | PPPMJ7xq9vM re-studied live 2026-07-19: 42.9s 720x1280, 11 shots, 159 words, sane; wall-to-wall speech honestly warned |
| youtube | short | horizontal | **LIVE** ✓ (+cached) | `_Bpwo7JlmII` re-studied live 2026-07-19 (after FHmXO-ViKdA rotted, SW-2; first fetch 403'd until SW-3 fix): 143.6s, 55 shots, 227 words, 144 captions vs cached 144s/55/228/144 — an independent live re-measurement reproducing the cached study to within 1 word |
| youtube | long | horizontal | **cached** (7 studies) | packs-ws: 315s–1530s, incl. 25-min podcast-style |
| youtube | long | vertical | **LIVE** ✓ | -UC6b5owmCA (reddit-story format), 430s 864x1920 — studied 2026-07-19, sanity below |
| tiktok | short | vertical | **LIVE** ✓ | zachking 6768504823336815877, 18.3s 1080x2044 — studied 2026-07-19 retry #2, sanity below |
| tiktok | short | horizontal | **exists-rare, unsourced** | fetches work now; sourcing round: even TV/sports accounts crop vertical (@espn probe: 1080x1920). Genuine horizontal TikToks are edge-case uploads; cell stays open with low priority |
| tiktok | long | vertical | **sourcing walled (round 2 logged)** | fetches work but candidates keep walling: @reesateesa private, GRWM post permission-locked, tag pages broken in yt-dlp. Round 2: listed big public long-form accounts — @mrballen tops out at exactly 178s (creators optimize just under the 3-min mark), @60minutes at 138s. >180s uploads live on small accounts behind per-post walls. Cell stays open; note for formats.py thinking — TikTok's own behavior clusters right at our 180s boundary, so "long tiktok" is a thin real-world class |
| instagram | short | vertical | **blocked** | attempt 1 (2026-07-19): "empty media response … use --cookies" — login-walled; cookies are Ryan's call |
| instagram | long | * | **blocked** | same; long-form exists (extended reels) |
| x | short | horizontal | **LIVE** ✓ | SpaceX post 1732824684683784516, 114s 1920x1080 — studied 2026-07-19, sanity below |
| x | short | vertical | **LIVE** ✓ | BrianMcDonaldIE 2075286280561107161, 14.9s 720x1280 — studied 2026-07-19, sanity below |
| x | long | horizontal | **LIVE** ✓ | ShawnRyanShow 1875286149788573873, 3702.8s 1280x720 — studied 2026-07-19, sanity below |

Non-cells (combination effectively absent, so out of scope): tiktok
long horizontal, x long vertical — will add if a real counterexample
turns up during sourcing.

## Fetch-wall log (retries required by spec)

- **YouTube**: anti-bot wall ("Sign in to confirm you're not a bot")
  first hit 2026-07-19 after ~28 fetches during A-Q14; re-probed 3×
  while up. **Retry #4 (2026-07-19, later session): WALL DOWN** —
  fetches work again; the wall is a rolling rate window, not a
  permanent IP flag. Sweep + parked vlog-pack retry ran in the open
  window.
- **TikTok**: "Your IP address is blocked from accessing this post"
  on attempt #1 (khaby.lame post). **Retry #2 at a different time
  with a different post (zachking): fetch OK** — the block is
  per-post or transient, not an IP flag. Cell studied live.
- **Instagram**: login wall on anonymous access, attempts #1 and #2
  (different reels, different times, both "empty media response …
  use --cookies"). Consistent policy wall, not rate limiting;
  cookies route is Ryan's call. Cells remain **blocked**.
- **X**: no wall. Fetches work anonymously.
- **SW-2 — reference rot observed live**: FHmXO-ViKdA (the S1 gate
  video) is now "Video unavailable" on YouTube. Not in any pack
  manifest; cached study stays valid as measurement of stored bytes.
  Rot within weeks is real — verified_at dating and frozen-fixture
  policies are doing load-bearing work; a pack `--reverify` pass is
  proposed in NOTES.
- **SW-3 — JS-runtime 403s (fixed on this box)**: yt-dlp ≥2026.07
  wants a JS runtime for YouTube; without one, signature-challenge
  videos 403 while others pass, masquerading as an intermittent wall.
  Fixed here via `--js-runtimes node` in the user yt-dlp config
  (node v24 present). Product gap routed to Lane B: `zing doctor`
  should check for a JS runtime.

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

## Live cell: tiktok / short / vertical — sanity record (2026-07-19)

- URL: https://www.tiktok.com/@zachking/video/6768504823336815877
  (Zach King "Hogwarts broom" — one of TikTok's most-viewed posts).
  Slug `tiktok-6768504823336815877`; platform detect correct.
- Meta: 18.3s, 1080x2044@30 (matches probe's 1080x2042 ± TikTok's odd
  crop heights). HEVC source honestly warned and re-encoded to H.264
  per the ingest contract.
- Transcript is the video's REAL dialogue ("…Longboardium Leviosa!
  Zach, my longboard!") — verified against the actual video, not
  whisper hallucination; speech_ratio 0.638 with music_confidence
  0.687 is an honest read of dialogue-over-music.
- **1 shot detected — a truthful hard case, not a defect**: Zach
  King's signature is cuts engineered to be invisible. AdaptiveDetector
  reporting a single shot IS the measurement (the deception works on
  the detector exactly as it works on humans). Recorded here so
  profile-building on magic-cut content is understood to undercount
  cuts; the honest fix, if ever needed, is a warning keyed on genre,
  not a detector tweak.
- SW-1 reinforced: caption events again include wrong-script (CJK)
  texture/watermark misreads at passing confidence.

## Live cell: x / short / vertical — sanity record (2026-07-19)

- URL: https://x.com/BrianMcDonaldIE/status/2075286280561107161
  (music-backed meme montage with Russian text overlays). Slug
  `x-2075286280561107161`; 14.9s 720x1280@30, matches probe.
- 7 shots in 14.9s — plausible montage cutting; consistency OK.
- **Honesty highlight: 0 transcript words** with speech_ratio 0.0 and
  has_voiceover False — the VAD gate correctly produced NOTHING over
  music instead of letting whisper hallucinate lyrics. This is the
  skip-vs-empty distinction doing its job on a live video.
- **SW-1 sharpened**: the overlays are Cyrillic; PP-OCR (Latin/CJK
  models) mangles them into confident Latin junk ('AAHIT', ': , - ?')
  at 0.77–0.93 confidence rather than abstaining. SW-1's scope is
  therefore "unsupported scripts + textures", not just cinematic
  footage — whatever design call resolves it must handle
  wrong-alphabet text, where the right answer is "unreadable script,
  flagged", never a fabricated Latin reading.

## Live cell: youtube / long / vertical — sanity record (2026-07-19)

- URL: https://www.youtube.com/watch?v=-UC6b5owmCA (reddit-story TTS
  over full-screen subway-surfers gameplay — the definitive
  long-vertical genre). CORRECTION (P-C2 frame verification): the
  initial record said "split-screen with story overlay" — wrong; the
  story exists ONLY as narration, with no on-screen story text.
  430.4s, 864x1920@30 (normalized from the 1728x3840 source). First
  live exercise of the **batched whisper path in the sweep**
  (pipeline: batched(batch_size=8), large-v2) — 1215 words at a
  plausible 2.82 words/s of real TTS narration; speech_ratio 0.829
  over gameplay music honestly split.
- **Truthful hard case #2**: 3 shots in 430s — one 426.6s shot plus an
  end-card. Correct: continuous gameplay footage genuinely has no
  cuts. Like the Zach King case, profile-building on this genre will
  see cut-rate ≈ 0 because that IS the measurement.
- 1882 caption events are REAL on-screen text — but ALL of it is
  gameplay HUD/watermark/CTA graphics (P-C2 labels: 13,266 of 13,313
  raw lines incidental_text, 47 unreadable, ZERO captions — the
  creator did not caption this video). Ties into the SW-1 design
  call: the measurement layer records on-screen text honestly;
  whether HUD/incidental text should be distinguishable from creator
  captions is a schema/judgment-layer question for the orchestrator,
  filed with SW-1.
- OCR sampling warning honest (2 fps after 30s on long videos).

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

Round 2 (two more slugs per cached cell, adding a word-rate
plausibility bound 0.3–5.5 w/s): `youtube-oyaneh0joqi`,
`youtube-2z0geysuxak` (short/vert); `youtube-bpwo7jlmii`,
`youtube-yvow0tao9ok` (short/horiz); `youtube-01zctt-cjw`,
`youtube-c25g53pc5qq` (long/horiz) — all six PASS. 9 of 32 cached
studies now spot-checked, ≥3 per cell.

## Live cell: x / long / horizontal — sanity record (2026-07-19)

- URL: https://x.com/ShawnRyanShow/status/1875286149788573873 (62-min
  native X podcast upload). Slug `x-1875286149788573873`. The sweep's
  longest study: 3702.8s 1280x720@23.976, batched large-v2.
- 393 shots (~9.4s median spacing — plausible two-camera interview
  cutting); 10,088 words at 2.72 w/s; speech_ratio 0.837 with a music
  bed honestly detected (intro/outro). All spans in range.
- **Finding SW-4 (fixed same cycle):** the sweep's first word-order
  violation — 2 sub-second inversions in 10,088 words (t=499s,
  t=2774s), where batched-pipeline segment seams overlap slightly.
  Fix: _collect_words now sorts by whisper's own timestamps
  (normalization, not fabrication) + regression test with synthetic
  seam overlap. At 62-min scale a 0.02% defect rate is what honest
  hardening looks like: found by sweeping, named, fixed, pinned.
