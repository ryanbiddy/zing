# X Native-Video Virality (V-C)

Author: Lane C. Date: 2026-07-18. V-round deliverable (doc-only).

This brief separates what X discloses from what creators infer. Evidence tiers:
**T1** = current first-party product documentation or platform code;
**T2** = transparent, large-sample secondary research; **T3** = a repeated
practitioner pattern; **T4** = a single example or unverified synthesis. The
May 2026 open-source recommendation release is a snapshot: X says its model
architecture is representative, while production is larger and continuously
trained. It reveals signal families, not stable production weights.

## 1. Measurable definition

X publishes no view count, velocity, or engagement-rate threshold that makes a
video “viral.” Zing should therefore define virality as **distribution that is
an extreme outlier for both the creator and a matched content cohort, while
qualified attention and spread remain healthy**. Absolute public views alone
do not meet that definition.

### Keep the counters separate

- **Public post views are exposure-like, not video watches.** A logged-in view
  of the post counts from Home, Search, Profiles, and other X surfaces; the
  author’s own view and repeat views can count, and the number is not unique.
  Embedded posts do not add to it. **T1.**
  [X view-count definitions](https://help.x.com/en/using-x/view-counts)
- **A Media Studio video view is narrower.** It requires at least two seconds
  of playback with at least 50% of the player in view. It counts logged-in
  views, excludes logged-out and web-embed viewing, and aggregates the same
  uploaded video across every post that reused it. **T1.**
  [X Media Studio Analytics](https://help.x.com/en/using-x/media-studio-analytics)
- **Attention is measurable after publication.** X exposes average watch time,
  completion, retention at 25/50/75/100%, total minutes viewed, and
  organic-versus-promoted views. The Video Activity Dashboard also defines
  view rate, average percentage watched, and completion. **T1.**
  [Media Studio](https://help.x.com/en/using-x/media-studio-analytics) ·
  [Post and Video Activity Dashboards](https://business.x.com/en/help/campaign-measurement-and-analytics/tweet-activity-dashboard)

### Zing’s operational tiers

These are v0.1 measurement rules, not X claims. Compare only organic posts at
the same elapsed age. Match on genre, duration band, account-size band, and
original upload versus repost. Use at least 20 comparable posts for the
creator baseline; otherwise return `insufficient_baseline`.

| Label | Required reach | Required quality | When assigned |
| --- | --- | --- | --- |
| Normal | At or below the creator’s elapsed-time P95 | No gate | Provisional at any checkpoint |
| Account breakout | Above the creator’s elapsed-time P95 | At least two of view rate, average watch time, completion, and conversation rate are at or above the creator’s P50 | Provisional at 6h; confirmed at 24h |
| Cohort viral | Above the matched-corpus P99 **and** creator P95 | At least two of those four rates are at or above creator P75; none is below creator P25 | Confirmed at 24h |
| Durable viral | Still above matched-corpus P99 at 7d | Quality gate still holds | Confirmed at 7d |

Use organic impressions as the reach unit when the creator supplies an
analytics export. Public post views are a fallback and must produce the label
`public-view provisional`, because they count repeat exposure and do not prove
that the video played. `conversation_rate` is `(replies + reposts) / organic
impressions`; keep broad engagement rate separate because X includes clicks
anywhere on the post.

Until Zing has a matched X corpus large enough to estimate P99, it can issue
**account breakout** labels only. “Cohort viral” must not be guessed from an
absolute view band or follower multiple.

A useful negative result comes from the largest transparent secondary dataset
found in this round: among Buffer-published content, 2025 X video had a 2.96%
median engagement rate versus 3.56% for text. The report covers 18.8 million X
posts in its Premium analysis but only Buffer users, and its X engagement
measure is likes + reposts + comments. It does **not** prove that video is
penalized; it does disprove “native video gets a default reach advantage” as a
safe baseline assumption. **T2.**
[Buffer 2026 report and methodology](https://buffer.com/resources/state-of-social-media-engagement-2026/)

## 2. Spread mechanism

X’s current open-source For You architecture gives the strongest available
mechanistic account:

1. **Candidate supply.** Thunder retrieves recent in-network posts from
   followed accounts. Phoenix retrieves out-of-network candidates from the
   global corpus. **T1.**
2. **Personalized ranking.** A Grok-based transformer uses the viewer’s
   engagement history and content representations to predict many actions:
   favorite, reply, repost, quote, click, profile click, video view, share,
   dwell, follow-author, and negative feedback such as not-interested, block,
   mute, and report. A weighted scorer combines the probabilities. **T1.**
3. **Eligibility and diversity.** The pipeline removes duplicates, old or
   already-seen posts, blocked or muted sources, and other ineligible
   candidates; it then applies author-diversity and out-of-network scoring.
   **T1.**

Source:
[X/xAI For You algorithm, updated 2026-05-15](https://github.com/xai-org/x-algorithm) ·
[Phoenix architecture and release caveats](https://github.com/xai-org/x-algorithm/blob/main/phoenix/README.md)

The code names both dwell and a “video quality view” action, but X does not
publish the production action weights or a creator-facing definition that
equates “video quality view” with Media Studio’s two-second view. Do not turn
the presence of a signal into a ranking hierarchy.

### Surfaces that can carry the post

- Native video autoplays in timelines, Moments, Explore, and elsewhere on X.
  **T1.** [X video help](https://help.x.com/en/using-x/x-videos)
- Full-screen vertical discovery exists through the Video tab and the
  Immersive Media Viewer. X’s ad specification recommends 9:16 there but also
  accepts 4:5, 2:3, square, 1.91:1, and 16:9. The ad page proves the surface
  and accepted shapes; its under-15-second recommendation is an ad rule, not
  an organic-video optimum. **T1.**
  [X vertical-video specifications](https://business.x.com/en/help/campaign-setup/creative-ad-specifications)
- Reposts, replies, quotes, profile clicks, follows, and shares appear among
  the action families the disclosed ranker predicts. They are plausible routes
  from an in-network seed into new viewer contexts, but X does not publish a
  fixed “reply weight” or “repost multiplier.” **T1 for signal presence;
  unknown for relative weight.**

The practical spread loop is therefore:

`in-network or retrieved exposure → qualified watch/dwell → conversation or
sharing → more personalized in-network/out-of-network candidates`

That is a feedback loop, not a staged test with published batch sizes. No
credible primary source found in this round supports “first 500 viewers,”
“links are deboosted,” “video gets 10× reach,” or a universal completion
trigger.

## 3. Leading indicators

Record snapshots at 15m, 1h, 3h, 6h, 24h, and 7d. X says post metrics usually
update within seconds but may take up to 36 hours to stabilize, so early values
are directional and the 24-hour export can still revise. **T1.**
[X dashboard timing](https://business.x.com/en/help/campaign-measurement-and-analytics/tweet-activity-dashboard)

| Signal family | Record | What a breakout looks like |
| --- | --- | --- |
| Reach | Organic impressions, public post views, incremental impressions per hour, creator and cohort percentile | Velocity rises between checkpoints instead of merely starting high |
| Play | Organic video views, view rate | Reach acceleration does not collapse the view rate |
| Attention | Average watch time, average percentage watched, 25/50/75/100% retention, completion, total minutes | At least two duration-matched measures remain above the creator median as reach broadens |
| Conversation/spread | Replies, reposts, conversation rate, broad engagement rate | Conversation rate holds while impressions move outside the normal range |
| Conversion | Profile clicks, follows, link clicks or CTA clicks per impression | Reach produces intent beyond passive exposure |

The earliest credible signature is **joint movement**: accelerating organic
impressions plus stable attention plus a healthy conversation rate. A large
public view count with weak two-second view rate is exposure, not demonstrated
video virality. A high completion rate on a six-second loop is not comparable
to a 30-minute interview. A high broad engagement rate can also be inflated by
detail expands and other low-intent clicks, because X counts clicks anywhere
in its definition.

For a machine-readable tracker, store raw numerators and denominators as well
as rates. Never reconstruct rates from rounded dashboard percentages. Separate
organic from promoted data and identify repeat uploads, because Media Studio
aggregates a reused video across posts.

## 4. Genre differences

The platform supports both short and long native video. Non-Premium accounts
may upload up to 140 seconds; Premium accounts may upload videos under four
hours, with resolution conditions above two hours. Videos of 60 seconds or
less automatically loop. Web uploads accept a wide aspect-ratio range rather
than mandating 9:16. **T1.**
[X upload, loop, and ratio limits](https://help.x.com/en/using-x/x-videos)

No first-party source publishes genre-specific winning durations or retention
bars. The patterns below come from the R3 Grok/X sweep and remain **T3**
cross-account synthesis or **T4** single-example evidence. They are editing
hypotheses to test, not algorithm facts.
[R3 Grok/X findings](../../handoff/research/R3-grok-x-findings.md)

| Genre / intent | Working shape | Primary success read | Editing implications |
| --- | --- | --- | --- |
| Comedy, memes, sports moments | Usually under 60s; often vertical or square | Completion, replay, reposts, replies | Show the gag/action immediately; tight reaction timing; captions only when they carry the setup; raw audio or deliberate SFX |
| Tech news and product demos | Roughly 30–120s; vertical, square, or landscape by source | View rate, retention, profile/link intent | Put the value screen or result first; use legible labels; let screen detail determine aspect ratio; remove feature-tour dead air |
| Business, education, interviews | Clips plus native long-form | Average watch time, total minutes, replies, follows | State the thesis early; preserve coherent arguments; use B-roll and timestamps where useful; judge absolute minutes alongside completion |
| Music, cinematic, emotional work | Often 45–60s in the sampled set; landscape remains legitimate | Watch time, replay, reposts | Rhythm and mix carry the piece; captions-off can be intentional; avoid forcing a vertical crop that damages composition |

Three platform-specific consequences follow:

- **Aspect ratio is an intent check, not a 9:16 gate.** Vertical earns the
  full-screen discovery layout; landscape and square are officially supported
  and can better preserve demonstrations, interviews, and cinematic framing.
- **Caption policy is conditional.** Information-dense, speech-led, and meme
  formats need readable text or subtitles. Music-led and cinematic work may
  intentionally omit editorial captions. X can generate speech-to-text for
  playback, but creators should not assume every viewer sees it.
- **Long-form should not be scored like a loop.** For interviews and education,
  average watch time and total minutes can show value even when completion is
  lower. For sub-60-second entertainment, completion and the loop seam are
  more informative.

## 5. Taste-engine score

Zing can score **conditional viral potential under fair distribution**. It
cannot forecast views, because the disclosed ranker depends on viewer history,
candidate supply, author context, feedback after publication, and continuously
trained production models.

### Experimental 100-point rubric

| Component | Points | File-measurable or judged evidence |
| --- | ---: | --- |
| Hook clarity and immediacy | 20 | Proposition or arresting visual in 0–3s; first visual state change by 3s; no logo pre-roll |
| Attention architecture | 20 | Duration-matched pacing, no unexplained dead air, purposeful shot/energy changes, intelligible speech, payoff before attention decays |
| Post-to-video congruence | 15 | Supplied post text, first frame, opening claim, and actual payoff describe the same promise |
| Ending and payoff | 15 | Claim resolves; CTA follows earned value; under-60s loop seam is clean when looping is intentional |
| Conversation and share worth | 15 | Specific utility, humor, identity, novelty, tension, or evidence gives a viewer a reason to reply or repost |
| Genre-native craft | 15 | Aspect ratio, caption policy, audio design, shot pace, and talking-head use match the declared genre and intent |

Scoring rules:

- Report the six component scores and **coverage**; a total alone is
  insufficient. Missing post text makes post-to-video congruence `not_scored`;
  do not silently award or reweight its 15 points.
- Use 0–49 = weak structure, 50–69 = mixed, 70–84 = strong, and 85–100 = high
  conditional potential. These are editorial routing bands, not probabilities
  and not validated view thresholds.
- Keep genre conditioning explicit. Caption absence is not a defect for a
  declared cinematic/music piece; a static talking head is not automatically
  a defect when authority is the format; 16:9 is not a platform failure.
- Treat a sub-60-second loop seam as craft evidence only. X confirms automatic
  looping, not a ranking bonus for a smooth loop.
- Do not score Premium status, posting cadence, trending demand, originality
  ownership, audience affinity, or early reactions from the video file. Those
  belong in context or post-publication analytics.
- Until the rubric is calibrated against matched X exports, emit
  `experimental: true` and the phrase **“not a view forecast.”**

The first calibration target is ranking, not numeric prediction: on a held-out
set of creator videos, does the pre-publish score order the later 24-hour
account-breakout percentile? Report Spearman correlation and top-quartile lift
with confidence intervals. Only add probability language after prospective
validation across genres and account sizes.

## Sources and limits

- **T1:** [X/xAI algorithm repository](https://github.com/xai-org/x-algorithm),
  [Phoenix release notes](https://github.com/xai-org/x-algorithm/blob/main/phoenix/README.md),
  [video upload/watch help](https://help.x.com/en/using-x/x-videos),
  [public view counts](https://help.x.com/en/using-x/view-counts),
  [Media Studio Analytics](https://help.x.com/en/using-x/media-studio-analytics),
  [activity dashboards](https://business.x.com/en/help/campaign-measurement-and-analytics/tweet-activity-dashboard),
  and [vertical-video specifications](https://business.x.com/en/help/campaign-setup/creative-ad-specifications).
- **T2:** [Buffer’s 2026 engagement report](https://buffer.com/resources/state-of-social-media-engagement-2026/).
  It is large and method-documented, but limited to Buffer-published posts and
  not a platform-wide causal study.
- **T3/T4:** [R3 Grok/X findings](../../handoff/research/R3-grok-x-findings.md).
  The source explicitly caps Grok synthesis at T3/T4. None of its approximate
  post IDs, engagement counts, payout claims, encoding claims, or
  anti-recycling claims were promoted here.

## Deeper Threads

1. **Build the matched corpus.** Pair 15m/1h/3h/6h/24h/7d organic analytics
   exports with genre, duration, account size, aspect ratio, and edit
   breakdown. Without it, P99 cohort virality and rubric calibration remain
   unavailable.
2. **Resolve analytics access in practice.** Verify which current account
   tiers can export PAD, VAD, and Media Studio metrics, and whether the CSVs
   expose the same fields described in help. Preserve raw exports because the
   dashboard can stabilize for 36 hours.
3. **Map “video quality view.”** The open-source ranker names this action, but
   public analytics defines a two-second view. Find a primary schema or
   engineering note before treating them as the same event.
4. **Measure out-of-network spread.** The recommender has explicit
   out-of-network retrieval, but creator analytics does not publish an
   in-network/out-of-network split in the sources found here. Test whether an
   accessible export or API provides one.
5. **Verify genre exemplars.** Resolve the approximate post IDs in R3, capture
   public metadata with dates, and request creator analytics where possible.
   Promote only verified examples into the taste corpus.
6. **Test post-copy congruence.** Hold the file constant and vary the post text
   prospectively. Measure view rate, retention, and conversation rate; do not
   infer a causal effect from retrospectively selected winners.
7. **Keep platform claims on a clock.** Pin the algorithm-repository commit and
   re-audit quarterly. The public Phoenix checkpoint is frozen while
   production training continues.
