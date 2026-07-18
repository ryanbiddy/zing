# YouTube + Shorts Virality (v0.1, 2026-07-18)

How Zing defines and measures virality on YouTube long-form and YouTube
Shorts — two surfaces, one recommendation philosophy, different metrics.
Tiers: T1 official/primary · T2 documented secondary · T3
practitioner-consensus. Compiled by Lane A (V-A) from two sourced research
sweeps; every claim linked.

---

## 1. Measurable Virality Definition (Thresholds)

- **V-YT-1 (T1).** YouTube publishes almost no thresholds. The only
  official number: "Half of all channels and videos on YouTube have an
  impressions CTR that can range between 2% and 10%" — and CTR *naturally
  falls* as impressions scale. Every other numeric bar in circulation is
  practitioner folklore. [Impressions & CTR FAQ](https://support.google.com/youtube/answer/7628154?hl=en)
- **V-YT-2 (T2).** The inversion that defines long-form virality: YouTube
  PMs state your most-viewed videos "are actually the most likely to have
  the LOWEST click-through rate" (broad distribution reaches unfamiliar
  audiences). **The viral signature is CTR holding steady while
  impressions explode — not a high CTR.** [Creator Insider via SocialMediaToday](https://www.socialmediatoday.com/news/youtube-explains-some-common-algorithm-and-video-distribution-queries/581002/)
- **V-YT-3 (T3).** The de facto industry viral metric for long-form is the
  **outlier multiple**: video views ÷ channel's recent-video average
  (ViewStats/vidIQ/1of10 all use it). 2x = noteworthy, 3x = significant,
  **5x+ = viral hit**. [ViewStats Outliers](https://viewstats.zendesk.com/hc/en-us/articles/22966946776091-Outliers-Tool) · [outlier scores](https://outlierkit.com/resources/outlier-scores/)
- **V-YT-4 (T3).** Long-form retention bars (conditional on length):
  <5min → 65–75% average-percentage-viewed; 10–15min → 40–50%; keep ≥60%
  of viewers past 0:30. Platform-wide APV is only ~24%, so these "good"
  bars are well above typical. [benchmarks](https://humbleandbrag.com/blog/youtube-audience-retention-benchmarks) · [2025 report](https://www.retentionrabbit.com/blog/2025-youtube-audience-retention-benchmark-report)
- **V-YT-5 (T1).** **Shorts public view counts became a vanity metric on
  2025-03-31**: a "view" now counts on any play or replay with no minimum
  watch time (TikTok-comparable). Ranking, YPP eligibility, and revenue
  still run on **engaged views** (the old chose-to-keep-watching
  definition, in Analytics Advanced Mode). Viral-by-views and
  viral-to-the-algorithm have formally diverged. [TeamYouTube announcement](https://support.google.com/youtube/thread/333869549/a-change-to-how-we-count-views-on-shorts?hl=en)
- **V-YT-6 (T3).** Shorts thresholds: **"viewed vs swiped away" ≥70%** is
  the commonly cited distribution trigger (a 3.3B-view dataset puts
  70–90% as "good"); average-percentage-viewed **>100% (looping) is among
  the strongest signals**; top Shorts practitioners target 90%+ retention.
  View tiers: 1M–10M in ~a week = "viral" (~0.8% of Shorts). [3.3B-view study](https://medium.com/@antoinelacombled/cracking-the-youtube-shorts-algorithm-a-study-of-3-3-billion-views-4711fdf7931b) · [benchmarks](https://humbleandbrag.com/blog/youtube-shorts-benchmarks) · [Jenny Hoyos](https://podcast.creatorscience.com/jenny-hoyos/)

---

## 2. The Spread Mechanism (Surfaces)

- **V-YT-7 (T1/T2).** ~70% of all watch time comes from recommendations
  (Neal Mohan, 2018). The system is **pull, not push**: "It's actually
  more the reverse" — each impression is generated per-viewer at
  recommendation time; there is no distribution plan (Todd Beaupré,
  Growth & Discovery). [Tubefilter](https://www.tubefilter.com/2018/01/11/youtube-most-watch-time-driven-by-recommendations/) · [SEJ myth-debunk](https://www.searchenginejournal.com/youtube-algorithm-myths-debunked-insights-from-the-growth-team/510091/)
- **V-YT-8 (T1).** Mechanistic root: ranking optimizes **expected watch
  time per impression** — "ranking by click-through rate often promotes
  deceptive videos" (RecSys 2016 paper) — later split into engagement
  (clicks, watch time) AND satisfaction (likes, survey ratings,
  dismissals) objectives (RecSys 2019). The top-line target is "valued
  watchtime": watch time rated 4–5 stars in viewer surveys, ML-extrapolated —
  a signal creators cannot see. [2016 paper](https://research.google/pubs/deep-neural-networks-for-youtube-recommendations/) · [2019 paper](https://research.google/pubs/recommending-what-video-to-watch-next-a-multitask-ranking-system/) · [Goodrow blog](https://blog.youtube/inside-youtube/on-youtubes-recommendation-system/)
- **V-YT-9 (T2).** Ranking is **per-video, not channel-average** ("no
  penalty box" — a flop doesn't doom the next upload), and Home vs
  Suggested run separate models. External traffic doesn't hurt discovery. [SEJ](https://www.searchenginejournal.com/youtube-algorithm-myths-debunked-insights-from-the-growth-team/510091/) · [SocialMediaToday](https://www.socialmediatoday.com/news/youtube-explains-some-common-algorithm-and-video-distribution-queries/581002/)
- **V-YT-10 (T1).** Shorts differ because **choice is absent** (swipe feed,
  not click): the system finds a **seed audience** and expands or tapers on
  its response; the feed weights diversity heavily; thumbnails, publish
  time, hashtags, and video length are officially marginal for Shorts.
  (Todd Sherman, Shorts product lead.) [Creator Insider interview](https://www.youtube.com/watch?v=n3jsYK_-aRU) · [TechCrunch](https://techcrunch.com/2023/08/25/youtube-demystifies-the-shorts-algorithm-views-and-answers-other-creator-questions/)

---

## 3. Leading Indicators in the First Hours

- **V-YT-11 (T3).** Long-form: **first-hour/first-24h CTR correlates
  strongly with long-term performance on established channels** (Paddy
  Galloway). The breakout tell is an impressions ramp with CTR holding;
  "a sharp uptick later in the day [on real-time] — you're entering
  suggested territory." [Galloway thread](https://twitter.com/PaddyG96/status/1605985305735077888) · [1of10 guide](https://1of10.com/blog/youtube-studio-the-ultimate-2025-guide-for-creators-what-to-focus-on-and-what-to-ignore-2/)
- **V-YT-12 (T1).** Learning starts "the moment you make a video public"
  (no wait-to-publish advantage), and recommendations are not
  recency-limited — videos can break out weeks or months later when
  audience interest renews. [Creator Insider on X](https://x.com/YouTubeInsider/status/1964034935326724329) · [SEJ](https://www.searchenginejournal.com/youtube-algorithm-myths-debunked-insights-from-the-growth-team/510091/)
- **V-YT-13 (T3).** Shorts velocity: views-per-hour >10x channel average =
  viral velocity; normal Shorts peak in 4–12h, viral ones 24–72h;
  **plateau-then-re-push is normal** (the feed happily resurfaces
  weeks-old Shorts to fresh seed batches), so a taper is not a verdict. [VPH explained](https://alanspicer.com/vidiq-outlier-score-vph-explained/) · [Shortimize](https://www.shortimize.com/blog/how-does-youtube-shorts-algorithm-work)

---

## 4. Genre Differences

- **V-YT-14 (T2).** Genre-conditional weighting is **officially confirmed
  but unquantified**: "different factors can have different importance in
  different contexts" — watch time weighs differently for podcasts vs
  music, TV vs mobile (Beaupré). "Viral" is genre-relative at the
  model level, not just the benchmark level. [Beaupré interview](https://adoutreach.beehiiv.com/p/how-youtube-s-algorithm-really-works-in-2025-straight-from-youtube-s-director-of-growth)
- **V-YT-15 (T3).** Winning shapes differ: podcasts run 25–35% APV but win
  on absolute watch time (15–21 min of a 60-min interview); education
  lives with 2–5% CTR (passive browse traffic); entertainment needs 60%+
  retention; tech/reviews sit at 4–7% CTR. Same engine, different winning
  geometry. [retention norms](https://humbleandbrag.com/blog/youtube-audience-retention-benchmarks) · [CTR by niche](https://www.hooksnap.io/blog/youtube-average-ctr-by-niche-2026)
- **V-YT-16 (T1/T3).** Shorts monetization is a pooled 45% revenue share on
  **engaged views**, with RPM ~10–100x below long-form ($0.01–$0.45/1k by
  niche) — so practitioners optimize Shorts as an **audience-acquisition
  funnel**, not revenue; virality goals differ accordingly. [official pool policy](https://support.google.com/youtube/answer/12504220?hl=en) · [RPM by niche](https://miraflow.ai/blog/youtube-shorts-rpm-2026-real-ranges-by-niche)

---

## 5. Taste Engine Score Spec

What Zing should score as viral-potential — structural cues measurable
from the video itself (Zing cannot see CTR, impressions, or satisfaction
surveys; it scores the things that *drive* them):

- **Hook window strength, per format** (0–3s Shorts / 0–30s long-form —
  already Zing's measured hook windows): a pattern interrupt or claim
  inside the swipe-or-stay moment; ≥60%-past-0:30 is the long-form bar
  the hook is fighting for.
- **Promise-payoff congruence**: the packaging claim (long-form
  title/thumbnail; for Shorts the first seconds ARE the packaging) must
  be paid off in-content — "the more extreme the opinion, the higher the
  CTR… if you pay it off, it supercharges it" (MrBeast); unpaid promises
  show up as retention collapse.
- **Loop construction (Shorts)**: ending that flows seamlessly back into
  the opening (last-line→first-line continuity, matched frames) — the
  measurable driver of >100% APV, the strongest Shorts signal.
- **Retention shape**: front-loaded value, a planned re-engagement beat
  around minute 3 on long-form (leaked MrBeast production doc), no dead
  air / speech-free decays at the tail (Zing's loudness curve already
  catches these).
- **Absolute-vs-relative watch time by genre**: judge podcast-style
  content on absolute minutes held, short entertainment on percentage —
  per V-YT-15, one bar per genre, not one bar for all.

---

## Deeper Threads

1. **The engaged-view threshold is deliberately secret** (Sherman: tweaked
   to prevent gaming). Every "X seconds counts" claim is unverifiable —
   could Zing calibrate its own proxy from creator-shared analytics
   exports paired with breakdowns?
2. **Which view count should the taste corpus record post-2025-03?**
   Public Shorts views (vanity, loop-inflated) vs engaged views
   (ranking-real, private). Exemplar "viral" labels sourced from public
   counts now overstate; corpus entries should note which metric backed
   the label.
3. **Satisfaction surveys are the top-weighted signal and are invisible**
   to creators and to Zing — any viral-potential predictor is built on
   proxies YouTube itself calls only "a portion" of ranking. What is the
   honest confidence ceiling for a taste-engine virality score?
4. **Genre-conditional weights are officially real but unquantified** —
   outlier-multiple distributions per genre could be measured directly
   from public data (channel recent-average vs video views at scale) to
   put numbers where YouTube won't.
5. **Do loop/APV benchmarks survive 3-minute Shorts?** (Oct 2024 length
   extension; the 3.3B-view dataset's ">50s Shorts average 4.1M views"
   predates it.) Also unresolved: whether Shorts seed audiences include
   subscribers preferentially — practitioner sources directly contradict
   each other.
