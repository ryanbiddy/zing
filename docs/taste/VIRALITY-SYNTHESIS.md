# Cross-Platform Virality Synthesis (v0.1, 2026-07-18)

What the four V-round docs agree on, where they genuinely differ, and what
the taste director should score per platform. Sources: `VIRALITY-youtube.md`
(V-YT-1..16), `VIRALITY-TIKTOK.md` (V-B; no numeric IDs — cited as V-TT §n),
`VIRALITY-instagram.md` (V-IG-1..10), `VIRALITY-X.md` (V-C; cited as V-X §n),
grounded in `TASTE-FRAMEWORK.md` pillar C (completion as universal currency).

**Tiering rule:** every claim below carries the tier of the **weakest link in
its chain** (TASTE-FRAMEWORK tiers T1–T4, plus the V-B **FOLKLORE** tag). A
"universal" built from three T1s and one T3 is a T3 universal. Four docs,
**five surfaces** — YouTube long-form and Shorts diverge enough that merging
them would itself be a smoothing error.

---

## 1. The Comparison Table

| Surface | What virality measurably IS | Dominant ranking currency | First-hour leading indicators | Distinct mechanism |
| --- | --- | --- | --- | --- |
| **YouTube long-form** | Outlier multiple: views ÷ channel recent-average; 5x+ = viral (V-YT-3, T3). Signature: **CTR holds while impressions explode** — not high CTR (V-YT-2, T2). No official threshold (V-YT-1, T1). | Expected watch time per impression, topped by "valued watchtime" — satisfaction-survey-weighted, invisible to creators (V-YT-8, T1). | First-hour/24h CTR correlates with long-term performance on established channels; real-time uptick later in day = entering Suggested (V-YT-11, T3). But learning starts at publish and breakouts can come weeks later (V-YT-12, T1). | **Pull, not push**: each impression generated per-viewer at rec time; ~70% of watch time from recommendations; per-video ranking, no penalty box (V-YT-7/9, T1/T2). The only surface with a **click gate** (packaging is a separate artifact). |
| **YouTube Shorts** | 1M–10M views in ~a week = viral (~0.8% of Shorts) (V-YT-6, T3) — but public views became a **vanity metric 2025-03-31**; ranking runs on private engaged views (V-YT-5, T1). | Engaged views: viewed-vs-swiped ≥70%; APV >100% (looping) is the strongest signal (V-YT-6, T3). | Views-per-hour >10x channel average; viral Shorts peak 24–72h; **plateau-then-re-push is normal** — taper is not a verdict (V-YT-13, T3). | Choice is absent (swipe feed): seed audience → expand/taper on response; thumbnails, publish time, hashtags officially marginal (V-YT-10, T1). |
| **TikTok** | No official threshold (verified-absence). ~1M+/24–48h bands are FOLKLORE-adjacent. Zing definition: **For You share of traffic >70–80% + views decoupled from account baseline by ~10x** (V-TT §1, T3). | Predicted watch behavior: playtime/completion dominate the leaked, authenticated Algo-101 formula; finishing a *longer* video is an explicitly strong official signal (V-TT §2, T1; C1/C3). | 1–2h engagement above own average; share rate >~1% of views; watched-full >~80% (V-TT §3, T3 — **no published study validates any velocity threshold**, verified-absence). | Staged batch testing is real; **the batch sizes are folklore** (V-TT §2, T1 for staging). Watch behavior alone (linger, rewatch) profiles interest in <2h. **Sound is structural ranking metadata** (V-TT §4, T1 platform-commissioned). |
| **Instagram Reels** | View-to-follower ratio >10x within 7 days (V-IG-3, **T3 — see §4.1**); save:like >0.30 = evergreen velocity (V-IG-4, T3). No official threshold appears in the doc. | Top likelihood predictions, in order: **reshare, watch-all-the-way-through, like, go-to-audio-page** (V-IG-1, T1); shares + completion outrank comments/likes (V-IG-2, T2). | Completion <50% in initial test audience → throttled (V-IG-7, T3); shares >30/1,000 views in first 2h predicts push (V-IG-8, T3 — same genre of number V-B tags FOLKLORE). | Reels/Explore tabs are explicitly **non-follower distribution** (V-IG-5, T1); the only platform with a concrete published **demotion list** — watermarks, low-res, heavily political (V-IG-6, T1; P2). |
| **X native video** | No published threshold (T1 absence). Zing operational tiers: creator elapsed-time P95 (account breakout) → matched-corpus P99 + quality gates (cohort viral) — **Zing's own rules, not X claims** (V-X §1). | A weighted multi-action scorer (favorite, reply, repost, video view, dwell, negative feedback…) — signal families are T1 via open-sourced code; **production weights unpublished, no hierarchy may be inferred** (V-X §2, T1). | **Joint movement**: accelerating organic impressions + stable attention + healthy conversation rate. Metrics can take 36h to stabilize — early values directional (V-X §3, T1). | Two-source candidate supply (Thunder in-network / Phoenix out-of-network) feeding a Grok-based transformer: **a feedback loop, not a staged test**. Conversation (replies/quotes/reposts) is a first-class spread route; aspect-ratio pluralism is official (V-X §2/§4, T1). |

---

## 2. Universal vs Platform-Specific

### Universal — supported by all four docs

- **U1 (T3 net).** **No platform publishes a virality threshold.** Explicit
  T1-grade absence in V-YT-1, V-TT §1, V-X §1. The IG doc never states it,
  but every IG threshold it carries is T3 practitioner — the absence is only
  inferable there, which caps the universal at T3 until Lane IG says it.
- **U2a (T1).** **Watch/attention behavior is a ranking input everywhere.**
  TikTok, IG, YT name it first-order (pillar C, C1 — the framework's
  strongest finding); X's ranker predicts video view and dwell (V-X §2).
- **U2b (T1, three platforms only — not universal).** Completion/watch-through
  as **first-order** currency is documented on TikTok, IG, and YouTube (C1).
  X names the signals but publishes no weights; V-X explicitly forbids
  promoting presence into hierarchy. Do not quote C1 as four-platform.
- **U3 (T3).** **Virality is relative, not absolute.** All four lanes
  independently define it as outlier-vs-own-baseline: outlier multiple
  (V-YT-3), ~10x decoupling + For You share (V-TT §1), view-to-follower
  (V-IG-3), creator-P95/corpus-P99 (V-X §1). Convergent method choice;
  every leg is practitioner-tier or Zing-authored, so T3.
- **U4 (T1 — the strongest genuine universal).** **Spread runs through
  non-follower recommendation surfaces, earned per-item by audience
  response.** Pull-based recs, ~70% of watch time (V-YT-7); "neither
  follower count nor previous high-performing videos are direct factors"
  (V-TT §2, official); Reels recommendations focus on accounts you don't
  follow (V-IG-5); Phoenix out-of-network retrieval (V-X §2). Every leg T1.
- **U5 (T2, an absence claim).** **No primary source validates any
  first-window → outcome mapping.** Verified-absence on TikTok (V-TT §3);
  YT's only first-hour claim is T3 and T1 evidence says breakouts can come
  weeks later (V-YT-11/12); IG's first-hour claims are all T3; X says early
  values are directional and metrics stabilize over up to 36h (T1). Every
  early-velocity number in circulation is practitioner-tier at best.

### Near-universal — three of four; the gap flagged, not smoothed

- **Shares/reshares as top secondary currency (T1 on IG, official-input on
  TikTok, weight-unknown on X — absent from the YT doc).** Reshare is IG's
  #1 prediction (V-IG-1); shares/saves outweigh likes on TikTok
  (V-TT §3, T3; official input, T1); X predicts repost/share (V-X §2). The
  YouTube doc never mentions shares. Gap or platform truth — see §4.7.
- **Loop/replay reward (Shorts + TikTok + IG; explicitly craft-only on X).**
  APV >100% is the strongest Shorts signal (V-YT-6, T3); rewatches are
  verified interest signals on TikTok (V-TT §2, WSJ); IG loopability drives
  replays (V-IG-9, T3; replay-counting is an open question, V-IG DT-1). X
  confirms auto-loop under 60s but claims **no ranking bonus** (V-X §5, T1).
- **"Conditional potential, not a view forecast" as the honesty ceiling
  (TikTok §5.6, X §5, YT DT-3 — absent from the IG doc).** Three lanes
  independently cap what a file-only score can claim; the IG doc carries no
  such caveat. Methodological gap — see §4.1.

### Platform-specific — do not transfer

- **YT long-form:** the click gate. CTR-holding-under-impression-growth is
  the viral signature (V-YT-2, T2); packaging (title/thumbnail) is a
  separate scoreable artifact. No other surface has this.
- **YT:** satisfaction surveys — a top-weighted ranking term invisible to
  creators and to Zing (V-YT-8, T1). No analog documented elsewhere.
- **YT Shorts + X:** the public counter is not the ranking counter (V-YT-5;
  V-X §1 public post views vs 2s Media Studio views — both T1).
- **TikTok + IG (pair, not universal):** audio as ranking currency — sounds
  are official ranking metadata on TikTok (V-TT §4); go-to-audio-page is a
  top-four IG prediction (V-IG-1, T1). The YT doc lists Shorts metadata as
  marginal (V-YT-10) and the X doc has no audio ranking signal.
- **IG:** the concrete demotion list — watermarks, low-res, heavily
  political (V-IG-6, T1; P2). The only pass/fail penalty list any platform
  publishes.
- **X:** open-sourced ranker architecture, negative-feedback predictions as
  first-class signals, conversation as the spread route, and official
  aspect-ratio pluralism — landscape is legitimate (V-X §2/§4, T1).

---

## 3. What the Taste Director Scores as Viral-Potential

Zing sees the file, not the dashboard: it scores the structural drivers of
the currencies above. All outputs inherit the honesty ceiling: **conditional
viral potential given fair distribution — never a view forecast** (V-TT
§5.6, V-X §5). No FOLKLORE constant may be used as a calibration number.

| Surface | Score | Measured by / linked to | Grounding | Tier |
| --- | --- | --- | --- | --- |
| **YT long-form** | Hook inside 0–30s + ≥60%-past-0:30 as the bar the hook fights for | Breakdown hook window; shots/words 0–30s | H1, H5, V-YT-4 | T1 spec / T3 bar |
| | Promise–payoff congruence (title/thumbnail claim paid off in-content) | Packaging artifact vs opening claim vs payoff | H3, E4, V-YT-2/11 | T1 |
| | Retention shape: front-loaded value, re-engagement beat ~min 3, no dead-air tails | Pacing curve, loudness curve (existing measures) | C1, V-YT-4 spec | T3 |
| | Genre-conditional bar: absolute minutes (podcast) vs APV% (entertainment) | Genre declaration → bar selection | V-YT-14 (T2), V-YT-15 | T3 |
| **YT Shorts** | Hook 0–3s — the first seconds ARE the packaging | Breakdown 0–3s window | H1, V-YT-10 | T1 |
| | Loop seam: last-line→first-line continuity, matched frames (drives APV >100%) | First/last-frame similarity + audio continuity (Lane A seam) | V-YT-6 | T3 |
| **TikTok** | Duration-conditional completion — never reward shortness per se (finishing a longer video is the stronger official signal) | Expected completion GIVEN duration; pacing/payoff structure | C1, C3, V-TT §5.2 | T1 |
| | Peer-reviewed file features: close/medium framing, on-screen text/subtitles, visible faces, second-person address | Breakdown keyframes, captions, words | V-TT §3/§5.3 | T2 (small n) |
| | Sound presence (trend-freshness only with a real lookup source, else presence/absence only) | Audio-bed detection | P1, V-TT §4/§5.4 | T1 presence / T3 trend |
| | Share/save-worthiness above like-bait (utility, humor, identity) | Judgment-layer read | C2, V-TT §5.5 | T3 |
| **IG Reels** | Hook speed: visual cut/reset in 1–3s | Breakdown 0–3s window | H1, V-IG spec | T1 |
| | Loop seam (J/L-cut at the loop point) | Same loop-seam measurement as Shorts | V-IG-9 + DT-1 open | T3 |
| | Save/share CTA presence where genre-appropriate | Caption/words scan | V-IG-1 (T1 currency), CTA link T3 | T3 |
| | Asset cleanliness: no third-party watermarks, resolution, borders, majority-text | Direct file checks — Zing's only pass/fail virality gate | P2, V-IG-6 | T1 |
| **X** | The V-C experimental 100-pt rubric as-is: hook clarity (20), attention architecture (20), post-to-video congruence (15), ending/payoff (15), conversation/share worth (15), genre-native craft (15) | Per V-X §5; report components + coverage, `not_scored` when post text missing | H1/H2, C1, H3 (extended to post text), C2 | Experimental |
| | Genre-native craft is conditional: 16:9 is not a failure, caption absence is not a defect for cinematic/music, loop seam is craft evidence only | Genre declaration → conditional checks | V-X §4/§5 | T1 facts / T3 shapes |
| | Emit `experimental: true` + "not a view forecast" until calibrated (rank-correlation target, not numeric prediction) | Spearman vs 24h account-breakout percentile | V-X §5 | Method rule |

Cross-platform note: hook window (H1), congruence (H3), loop seam, and
dead-air detection are **one measurement each, rewarded per-platform** —
e.g. the identical loop-seam number is a scored driver on Shorts/TikTok/IG
and evidence-only on X. Build once, weight per surface.

---

## 4. Contradictions and Tensions Between the Four Docs

1. **Evidence-hygiene asymmetry — the sharpest conflict.** V-IG-3's "viral
   = 10x view-to-follower ratio" is materially the same claim V-B tags
   **"FOLKLORE, no primary source found anywhere"** ("viral = 10× your
   follower count in views"). V-IG-7's "completion <50% in the test
   audience → throttled" is the same genre as V-B's folklore-tagged "70%
   completion required," and V-X finds **no credible primary source** for
   any universal completion trigger, banning cohort-viral labels "guessed
   from an absolute view band or follower multiple." Two lanes explicitly
   refuse to launder the number class the IG lane states as T3 fact. Until
   re-sourced, treat V-IG-3/4/7/8 as FOLKLORE-adjacent, not calibration.
2. **Staged testing vs feedback loop.** Seed-audience expand/taper is T1 on
   Shorts (V-YT-10); staged batches are verified-real on TikTok with
   **folklore batch sizes** (V-TT §2); V-X states X is "a feedback loop,
   not a staged test with published batch sizes"; V-IG-7 asserts a test
   audience with a numeric gate at T3. The mechanism family does not
   transfer 1:1, and every specific batch/gate number found anywhere is
   unverified.
3. **The follower paradox (inside V-TT, echoed cross-doc).** Official:
   followers are "not a direct factor" (T1). Peer-reviewed: follower count
   was the **strongest single predictor** (small n); baseline views scale
   with follower tier. Meanwhile IG virality is *defined* by follower
   ratio and YT is per-video with no penalty box. The docs do not resolve
   whether followers gate exposure without being a ranking weight — flag,
   don't harmonize.
4. **What the ranker optimizes diverges.** TikTok's authenticated formula
   optimizes predicted engagement/playtime (V-TT §2); YouTube's top-line
   is survey-backed "valued watchtime" (V-YT-8) — an invisible quality
   term. Content tuned purely for raw retention could win TikTok's ranker
   and lose YouTube's satisfaction weighting. A single cross-platform
   "retention score" silently assumes these are the same objective; they
   are not.
5. **First-window fatalism is contradicted on YouTube and unvalidated
   everywhere.** V-YT-12/13 (T1/T3): learning starts at publish, no
   recency limit, plateau-then-re-push normal, breakouts weeks later. The
   practitioner frame under V-TT §3 and V-IG-7/8 — first hours decide the
   video's fate — has no published validation (U5) and T1 counter-evidence
   on at least one platform.
6. **Loop-seam reward is not portable.** Strongest-signal on Shorts (T3),
   verified-relevant on TikTok, assumed on IG (its replay accounting is an
   open question, V-IG DT-1), explicitly no-claimed-bonus on X (T1). One
   measurement, four different reward weights — a synthesis that scores
   "loops = viral" flat across platforms would be wrong on at least one.
7. **Shares are missing from the YouTube doc.** Reshare is the #1 IG
   prediction and a top TikTok signal, yet V-YT never mentions sharing —
   V-YT-8's satisfaction objective lists likes, surveys, dismissals only.
   Unresolved: does YouTube genuinely not rank on shares, or did Lane A
   not cover it? Either answer changes whether "shares are the universal
   secondary currency" survives; today it does not (see §2).

---

## 5. Deeper Threads

1. **Which counter backed each "viral" label?** Public and ranking counters
   have formally diverged on two surfaces (V-YT-5; V-X public views vs 2s
   views — both T1), and nobody has audited the TikTok and IG view
   definitions in our docs. Corpus rule to adopt now: every exemplar's
   viral label records the metric that backed it, or gets
   `public-view provisional`.
2. **One calibration corpus, four platforms.** V-TT DT-1 (creator-tools
   retention exports) and V-X DT-1 (matched snapshot corpus) are the same
   habit. Standing pipeline: first-party analytics exports + Breakdown per
   published video, all platforms; calibration target is **rank ordering**
   (Spearman vs later breakout percentile, per V-X §5), generalized to
   every surface. Until then, every §3 score is uncalibrated.
3. **Build the shared measurements once.** Loop seam (first/last-frame
   similarity + audio continuity), hook window, congruence, dead-air — one
   implementation, a per-(platform × genre) weight table. §4.6 is the
   proof this must be a weight table, not a constant.
4. **Bring VIRALITY-instagram.md to the folklore-tagging standard.**
   Re-source or explicitly retag V-IG-3/4/7/8, and add the honesty-ceiling
   clause the other three lanes carry. Until then the synthesis treats IG
   thresholds as directional only.
5. **The invisible-quality layer.** YouTube's satisfaction surveys and X's
   negative-feedback predictions both put an unobservable quality term in
   ranking; TikTok and IG docs show no analog. Platform difference or doc
   gap? The answer sets the honest confidence ceiling for any
   cross-platform viral-potential score (V-YT DT-3 generalized).
6. **A unified genre taxonomy.** All four docs condition on genre
   independently (V-YT-14/15, V-TT §4, V-IG-9/10, V-X §4) with
   incompatible category names. Rubric weights need a shared taxonomy so
   criteria resolve per-(platform × genre) — and per-genre outlier-multiple
   distributions are measurable from public data where platforms won't
   publish (V-YT DT-4).
