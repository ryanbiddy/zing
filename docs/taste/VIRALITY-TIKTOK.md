# What virality measurably IS on TikTok (V-B)

Author: Lane B. Date: 2026-07-18. V-round deliverable (doc-only).
Method: web-research agent sweep, 2024–2026 sources preferred; every claim
tagged **verified-data** (platform docs, major-outlet investigations,
peer-reviewed papers) / **practitioner-consensus** / **single-opinion** /
**FOLKLORE** (widely repeated, no primary source — flagged, never laundered).
The folklore tags matter as much as the facts: several numbers "everyone
knows" about TikTok have no traceable origin, and the taste engine must not
calibrate against them.

## 1. A measurable definition

- **TikTok publishes no virality threshold.** Every numeric cutoff in
  circulation is third-party. — verified-absence
  (https://www.shortimize.com/blog/how-many-views-is-viral-on-tiktok)
- Working practitioner bands: **~1M+ views in 24–48h = unambiguously
  viral; 100K–500K = "mini-viral,"** always relative to account size. —
  **FOLKLORE-adjacent**: widely repeated, no primary dataset
  (same source + https://www.bluehost.com/blog/how-many-views-is-viral/)
- "Viral = 10× your follower count in views" — **FOLKLORE**, no primary
  source found anywhere.
- Grounded baseline instead: Socialinsider's 70M-post benchmark
  (2024–2025, brand accounts) puts average TikTok engagement at **3.70%
  by followers / 4.20% by views** — sustained multiples of this marks an
  outlier. — verified-data (brands only)
  (https://www.socialinsider.io/social-media-benchmarks/tiktok)
- **The definition Zing should adopt:** a video is behaving virally when
  (a) its For You share of traffic exceeds ~70–80% (the observable
  signature of algorithmic push), and (b) views decouple from the
  account's own baseline by an order of magnitude. Both are relative
  measures, not absolute view counts. — practitioner-consensus on the
  For You signature (https://blog.hootsuite.com/tiktok-analytics/,
  https://blog.brandghost.ai/posts/tiktok-analytics-guide-creators/)
- Per-video metrics TikTok itself exposes (Creator tools): views, total
  play time, average watch time, **watched-full-video %, per-second
  retention graph**, new followers, traffic-source split (For You /
  Following / Search / Sound / Profile). — practitioner-consensus
  documenting the official UI
  (https://www.tiktok.com/creator-academy/en/article/tool-analytics-intro)

## 2. The spread mechanism

- **Official (TikTok newsroom):** For You ranking predicts interest from
  likes, shares, comments, follows, plus video metadata (captions,
  sounds, hashtags) and device/account signals. Strong signals outweigh
  weak: "whether a user finishes watching a longer video from beginning
  to end" is named as a strong signal; "neither follower count nor
  whether the account has had previous high-performing videos are
  direct factors." — verified-data
  (https://newsroom.tiktok.com/en-us/how-tiktok-recommends-videos-for-you)
- **Leaked scoring formula (NYT 2021, "TikTok Algo 101," authenticated
  by TikTok):** score ≈ predicted-likes + predicted-comments +
  predicted-playtime + predicted-plays, weighted; the system optimizes
  retention and time-spent. — verified-data
  (https://www.nytimes.com/2021/12/05/business/media/tiktok-algorithm.html)
- **Staged testing is real; the batch sizes are not.** Narayanan (Knight
  Institute, 2023): every video gets a minimum test audience; strong
  performance expands to successively larger batches — "a standard
  recommender system." — verified-data.
  The ubiquitous specifics ("first 200–500 viewers," "70% completion
  required," "1K→10K pools") appear only in marketing blogs. —
  **FOLKLORE** (https://knightcolumbia.org/blog/tiktoks-secret-sauce)
- **Watch behavior dominates (WSJ 2021 bot investigation):** lingering,
  pauses, and rewatches alone — no likes — let TikTok infer interests
  in under 2 hours. — verified-data
  (https://www.wsj.com/articles/tiktok-algorithm-video-investigation-11626877477)

## 3. Leading indicators in the first hours

- Practitioner signature of a breakout: first 1–2h engagement well above
  the account's own average; **share rate >~1% of views** and
  **watched-full >~80%** (short videos) as expansion candidates; shares
  and saves weigh more than likes. — practitioner-consensus, no public
  primary dataset
  (https://www.tokportal.com/post/tiktok-user-analytics-metrics-that-predict-your-next-viral)
- "10K views in first 30 minutes → sustained amplification" —
  single-opinion
  (https://www.socialboostdigital.com/blog/tiktok-algorithm-2026-view-velocity)
- **No published large-scale study links first-hour velocity to eventual
  views.** That mapping is TikTok-proprietary; all velocity thresholds
  are unvalidated. — verified-absence
- Peer-reviewed feature evidence (small n, 400 videos, WebSci 2022):
  **follower count was the strongest single predictor**; content
  features that mattered: close-up/medium shot scale, text overlay,
  video lifespan, point of view. — verified-data
  (https://dl.acm.org/doi/10.1145/3501247.3531551)
- Related peer-reviewed: shorter videos earn more likes; videos with
  visible humans and subtitles are shared more; second-person address
  boosts engagement. — verified-data
  (https://journals.sagepub.com/doi/10.1177/08944393231178603)

## 4. Genre differences

- Engagement bands differ by niche: entertainment/comedy ~6.9%
  (share-driven), education ~5.8% (comment/save-driven), fashion
  save-heavy — from a 150K-account analysis, methodology not
  peer-reviewed. — practitioner-consensus
  (https://sociavault.com/blog/good-engagement-rate-tiktok)
- Baseline views scale with follower tier despite the official
  "followers aren't a direct factor" line: ~8.7K average views at
  50–100K followers, ~25K at 100K–1M; the median video sits at 2–5K
  views. — practitioner data, single source
  (https://admanage.ai/blog/average-tiktok-views)
- **Sound is structural:** 88% of users say sound is essential
  (TikTok/Kantar); sounds are official ranking metadata. — verified-data
  (platform-commissioned)
  (https://ads.tiktok.com/business/en-US/blog/kantar-report-how-brands-are-making-noise-and-driving-impact-with-sound-on-tiktok)
  "Trending sound in first 24h → 3× views" — **FOLKLORE**.
- Duet/stitch chains carry sounds/formats across niches — documented
  qualitatively, no quantitative thresholds. — practitioner-consensus
  (https://theconversation.com/tiktoks-new-owner-puts-apps-algorithm-in-the-spotlight-a-social-media-expert-explains-how-the-for-you-page-works-265658)

## 5. What the taste engine should score as viral-potential

Ranked by evidence strength; each maps to something measurable from the
file (Breakdown) alone:

1. **Predicted watch-behavior beats predicted likes.** Every credible
   source makes play-time/completion the heaviest input. Score: hook
   strength 0–3s (early-retention proxy — already in prompts/study.md),
   pacing/payoff structure (full-watch and rewatch proxy),
   loop-ability (does the end feed the start?).
2. **Duration-conditional completion, not raw shortness.** Short
   maximizes completion odds, but finishing a *longer* video is an
   explicitly stronger official signal. Score expected completion GIVEN
   duration; never reward shortness per se.
3. **Peer-reviewed file-measurable features:** close-up/medium framing,
   on-screen text/subtitles, visible human faces, second-person address
   ("you"), emotional valence — all present or derivable from
   Breakdown words/captions/keyframes.
4. **Pre-publish metadata is scoreable:** sound choice and trend
   freshness, caption, hashtags — official ranking inputs (S2+: needs a
   trend-lookup source to be honest; without one, score only presence/
   absence of a music bed).
5. **Shareability/save-worthiness converts retention into expansion:**
   humor, utility, identity-signaling — judgment-layer reads, weighted
   above like-bait.
6. **The honesty ceiling (bake this into the prompt):** the strongest
   measured predictor (follower count) and every velocity signal are
   post-publish. A file-only score is **conditional viral potential —
   P(breakout | a fair test batch)** — never a view forecast. And no
   folklore constant (70% completion, 500-viewer batches, 10× follower
   ratio) may be used as a calibration number.

## Deeper threads

1. **Retention-curve ground truth:** Ryan's own Creator-tools retention
   graphs for published videos could calibrate hook-strength scoring
   against real per-second dropoff — the only first-party data we can
   legally get. Worth a standing "export analytics screenshots into the
   corpus" habit?
2. **Sound-trend freshness feed:** scoring "trending sound" honestly
   needs a data source (TikTok Creative Center trends?). Survey what's
   accessible without ToS violations before promising the feature.
3. **Loop-ability as a measurement:** first/last-shot visual similarity
   + audio continuity is deterministically measurable (Lane A seam) —
   evidence says rewatches matter; nobody measures loop design today.
4. **Cross-platform contrast:** the leaked TikTok formula optimizes
   predicted engagement; YouTube's public statements emphasize
   satisfaction surveys. When all four V-docs land, the synthesis
   should map which file-features transfer across platforms and which
   are TikTok-specific (sound, duet chains).
5. **Completion-vs-duration curve:** is there public data on completion
   rates by video length on TikTok (even coarse)? If yes, the
   duration-conditional completion score (item 2) gets a real prior
   instead of a hand wave.
