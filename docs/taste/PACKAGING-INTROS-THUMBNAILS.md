# Packaging: Intros/Outros, the Thumbnail Canon & Upload Craft (R3-B, v0.1, 2026-07-18)

Fills R3-B: intro/outro craft (+ tool recommendations), the thumbnail canon
with a concrete `zing thumbs` prompt-generator spec, and upload/packaging
mechanics. Builds directly on **H3** (packaging-congruence, T1) and **E4**
(packaging-first, T3) from TASTE-FRAMEWORK.md — this round grounds both
deeper and turns them into product surface. Criterion IDs continue the
parent scheme: **H6+** extends Pillar H; new pillars **O** (outros/end
screens), **K** (thumbnail & title packaging), **U** (upload mechanics).

**Tiers** as in TASTE-FRAMEWORK.md (T1 / T2 / T3 / T4) plus the R-2
extension T1-R (peer-reviewed or standards-body primary source). Method
note: three parallel research passes 2026-07-18; official pages fetched
live and quoted verbatim wherever possible; where verification degraded
(login walls, blocked archives, transcript mirrors) the claim says so. The
two highest-leverage T1 claims (K3 spec, K4 Test & Compare) were
re-fetched and re-verified independently before writing.

---

## Pillar H continued — intros (H1–H5 in TASTE-FRAMEWORK.md)

- **H6 (T1).** YouTube's official "Intros" retention report is a
  **30-second packaging-congruence grade**: it measures "what percentage of
  your audience still watched your video after the first 30 seconds," and
  defines a strong intro as one where "the content in the first 30 seconds
  matched the viewer's expectation of the video's thumbnail and title" and
  "kept the audience interested." YouTube's own fix advice: change
  thumbnail/title to match the content, and "modify the first 30 seconds of
  your video and experiment with different styles."
  [YT retention docs](https://support.google.com/youtube/answer/9314415)
  — Evidence: live help page fetched, quotes verbatim. Upgrades H3/H5: the
  intro is officially judged as delivery-on-the-packaging-promise, and 30s
  is the only intro window YouTube itself names for long-form.
- **H7 (T3 — leaked doc, authenticity caveat).** MrBeast internal
  production doc: "The first minute of each video is the most important
  minute of each video"; "the first minute has the most loss" — concrete
  number: on a video with ~60M clicks "we lost 21 million viewers in the
  first minute" (~35% first-minute loss *at MrBeast production quality*).
  The doc also prescribes planned re-engagements at roughly the 3- and
  6-minute marks, and treats CTR + average view duration as the two
  priority metrics.
  [full doc text (archive.org)](https://archive.org/details/how-to-succeed-at-mr-beast-production_20240813_2337) ·
  [Fortune coverage](https://fortune.com/2024/09/26/youtube-mrbeast-jimmy-donaldson-leaked-business-handbook-advice/) ·
  [Tubefilter](https://www.tubefilter.com/2024/09/17/mrbeast-internal-production-guide-leaked-key-points/)
  — Evidence: full 36-page text fetched and quoted verbatim; authenticity
  widely reported by mainstream press but never company-confirmed on the
  record — keep the caveat attached.
- **H8 (T3 — unanimous cold-open consensus; the quantified version does
  not exist).** Every named practitioner source converges on
  cold-open-first, branding sting (if any) AFTER the hook, short and
  reused: vidIQ — intro "10 seconds or less" (8s safer), "Skip long
  greetings, slow montages, and generic 'like and subscribe' at the very
  start," lead by "teasing the most entertaining scene," branded clip:
  "reuse it, but keep it short"; Film Booth (Ed Lawrence) — top creators
  "in the first line of their video tell the entire story... it sets up
  what's at stake, the hero, the conflict"; Paddy Galloway — spends up to
  a week on an intro, once wrote one 12 times, and applies a portability
  test: "look at your first sort of 30 seconds... if I cut this and put it
  on TikTok or YouTube Shorts, could it do well" — and warns against
  over-reading small dips ("a two percent dip... means 98% of people still
  watched"). Consistent with H2's T1 cold-open endorsement. **But**: no
  platform study or controlled experiment quantifying branded-intro losses
  exists in public (see Refuted) — the claim stands on H6 (T1: the first
  30s is graded) plus this consensus, never on a percentage.
  [vidIQ intros](https://vidiq.com/blog/post/youtube-video-intros) ·
  [Film Booth video](https://www.youtube.com/watch?v=Nb9cQmHFLTs) ·
  [Galloway interview (Jon Youshaei)](https://www.youtube.com/watch?v=AX3dEGjBg6w)
  — Evidence: vidIQ page fetched verbatim; both videos transcribed in full
  via caption track; channel identities confirmed via oEmbed.
- **H9 (T1 for the platform voice; T3/T4 for creator numbers).** Short-form
  intro = the first FRAME. Todd Sherman (YouTube Shorts product lead, on
  YouTube's own Creator Insider channel): underperforming Shorts show that
  "the percentage of people that swiped away was just much higher. They
  didn't get them with the hook!" — "viewed versus swiped away" is "a
  great metric," and watch time is weighed "as a proxy for if the viewer
  valued it." Jenny Hoyos, same conversation: "it's literally the first
  frame. I really do think you have one second to hook someone" — her hook
  formula: shock → set the expectation of the content → set the
  expectation of the ending. Her TED talk adds: constant progression
  toward the answer, add conflict, keep the ending uncertain. Benchmark
  floating in the ecosystem: best Shorts hold "between 70% and 90%"
  viewed-vs-swiped (T4: vidIQ attributing Galloway; dataset unpublished).
  Complements H1's TikTok 3s/6s numbers.
  [Creator Insider conversation](https://www.youtube.com/watch?v=_tWy-_otnUc) ·
  [Hoyos TED talk](https://www.ted.com/talks/jenny_hoyos_the_secret_to_telling_a_great_story_in_less_than_60_seconds) ·
  [vidIQ hooks](https://vidiq.com/blog/post/viral-video-hooks-youtube-shorts)
  — Evidence: full caption transcripts of both videos; Sherman is a
  platform employee speaking on the platform's channel (T1-grade voice);
  Hoyos's practice claims are hers (T3); the 70–90% figure is secondhand.

**Zing measures:** presence of an intro graphic/sting (early shot with no
speech + logo-ish OCR text), time-to-first-content-word, first-frame
quality for short-form. **Zing judges:** first-30s congruence against
`meta.title` and the thumbnail promise (H6), cold-open vs greeting-open
classification, whether the best material appears before or after t=30s.

## Pillar O — outros & end screens (new)

- **O1 (T1).** End-screen mechanics: elements occupy "the last 5–20
  seconds of a video"; the video must be "at least 25 seconds long"; up to
  **4 elements** (16:9); element types Video / Playlist / Subscribe /
  Channel / Link (Link = YPP members only); viewers can hide them; not
  available on made-for-kids. Official best practices on the same page:
  feature relevant elements, use calls to action, "leave enough space and
  time at the end of the video," consider staggering element timing.
  Cards: up to **5 per video**, creator-set timing, made-for-kids
  excluded — and the live page as fetched states cards are visible on
  computers only, i.e. a weak mobile lever vs end screens.
  [End screens](https://support.google.com/youtube/answer/6388789) ·
  [Cards](https://support.google.com/youtube/answer/6140493)
  — Evidence: both help pages fetched verbatim (end-screen page fetched
  independently by two passes this round).
- **O2 (T1).** Why the outro should hand off, not conclude: since Oct 12,
  2012 YouTube officially optimizes for "the amount of time viewers spend
  watching videos from search and across the site" — session time, not
  single-video time. The end of your video is the start of the session's
  next decision.
  [Official 2012 blog post](https://blog.youtube/news-and-events/youtube-search-now-optimized-for-time/)
  — Evidence: dated official post, fetched.
- **O3 (T3).** Don't signal the end. MrBeast doc, verbatim: **"The video
  endings must always be abrupt to protect retention"** and "Don't ever
  signal the end of the video unless it's to build hype for the prize or
  payoff at the end." vidIQ, verbatim: "Never say 'thanks for watching'
  at the end of a video. That prompts the viewer to leave" — instead the
  spoken outro pitches ONE relevant next video while the end-screen
  element for it is on screen ("viewers are whisked away to another video
  because they clicked a call-to-action on your end screen").
  [MrBeast doc](https://archive.org/details/how-to-succeed-at-mr-beast-production_20240813_2337) ·
  [vidIQ end screens](https://vidiq.com/blog/post/youtube-end-screens)
  — Evidence: doc text + vidIQ page both fetched verbatim; two
  independent named sources, same rule.
- **O4 (T1 platform voice + T2 + T3).** Shorts outro = the loop, honestly
  sized: Todd Sherman, verbatim: "Some of the best performing very short
  videos can be very rewatchable... It's **not like we strictly optimise
  for two loops** or something like this. When you think about watch time
  I would think of it as a proxy for what viewers value" — loops pay
  through rewatch watch-time, there is NO dedicated loop signal. Since
  **2025-03-31** a Shorts "view" counts on every play **or replay**
  (public counts inflate; "engaged views" still governs monetization) —
  T2, verified via TechCrunch; official support article not located this
  round. Loop craft (T3): make the last frame flow into the first, or end
  on a question the first line answers.
  [Creator Insider conversation](https://www.youtube.com/watch?v=_tWy-_otnUc) ·
  [TechCrunch on view counting](https://techcrunch.com/2025/03/26/youtube-is-changing-how-youtube-shorts-views-are-counted/) ·
  [vidIQ loop craft](https://vidiq.com/blog/post/viral-video-hooks-youtube-shorts)
  — Evidence: transcript verbatim for the platform voice; view-count
  change from reputable tech press pending the official page.

**Zing measures:** goodbye-phrase detection in the transcript tail
("thanks for watching", "that's it for today"...), speech/loudness in the
final 20s (is there composition room for end-screen elements per O1),
short-form first/last keyframe similarity (loop seam). **Zing judges:**
abrupt-vs-signaled ending (O3), whether the outro pitches a specific next
video vs generic sign-off.

## Tool survey — intros/outros (recommendation, not criteria)

Framing first, because the evidence demands it: per H6–H8 the best intro
is mostly **not a graphic** — cold open, then at most a ~2–3s reused
sting. Tooling exists to produce (a) that sting and (b) a reusable
end-screen background with the composition room O1 requires. License
positions below were read from the primary license documents this round;
prices marked *(unverified)* were not confirmed and must be checked
before recommending to users.

| Stack | Ceiling | Cost | License posture | Lock-in |
|---|---|---|---|---|
| **Motion Array** templates (Premiere/AE/Resolve) | High (same template class as Envato) | subscription *(price unverified)* | **Best surveyed**: "the projects you finished as a paid member will remain covered forever"; explicitly lists "YouTube + Monetization" | New projects need an active sub; finished work is safe |
| **DaVinci Resolve** (free) + Fusion / MA Resolve templates | High | $0 (Studio $295 one-time *(unverified)*) | Own work, no strings; free tier is genuinely professional (official product page) | **Lowest of any pro path** |
| After Effects + **Envato Elements**/Videohive | Highest; deepest template pool | AE + Elements subs *(unverified)* | Per-project registration; license "becomes perpetual" only for projects completed **while subscribed**; no use of items in new work after cancellation | Adobe subscription |
| Premiere **.mogrt** (either marketplace) | High-mid (text/logo params) | Premiere sub | per marketplace above | Adobe |
| **CapCut** templates | Mid (trend-native) | free / Pro *(unverified)* | **Weakest surveyed**: ToS grants ByteDance JV an "unconditional... perpetual" UGC license; template commercial rights "may vary depending on the CapCut product"; Company-Content license is revocable | High (proprietary projects) |
| Canva video | Mid-low | free / Pro *(unverified)* | **Unverified** — license page blocked to all fetch paths this round | Medium (cloud) |
| Placeit | Low-mid | sub/one-off | Most permissive read (resale/merch explicitly allowed) | Cloud render only |
| Renderforest / Panzoid | Low; dated | freemium / free | Unverified / undocumented | High / browser-only |

Key license sources:
[Motion Array license](https://motionarray.com/license/) ·
[Envato Elements license terms](https://help.elements.envato.com/hc/en-us/articles/360000628966-License-Terms) ·
[CapCut ToS](https://www.capcut.com/clause/terms-of-service) ·
[CapCut's own 2025 clarification](https://www.capcut.com/resource/about-capcut-terms-of-service) ·
[lawyer analysis (DPReview)](https://www.dpreview.com/news/1239418455/capcut-video-editing-app-s-new-terms-spark-rights-concerns-we-asked-a-lawyer-for-guidance) ·
[Placeit license](https://placeit.net/license) ·
[Resolve product page](https://www.blackmagicdesign.com/products/davinciresolve)

**Recommendations (2–3, settled):**
1. **Motion Array** — the default recommendation for anyone with any NLE.
   Cleanest license for a monetized channel (finished projects covered
   forever), so one paid month can produce a permanent brand kit: sting +
   end-screen template, rendered, done.
2. **DaVinci Resolve (free) + Fusion**, fed by Motion Array's Resolve
   section — for the creator willing to learn a real tool: zero cost,
   professional ceiling, no subscription hostage-taking.
3. **After Effects + Envato Elements** — only if already inside Adobe:
   highest ceiling and the largest template universe, but you rent both
   the tool and, functionally, the license pipeline (per-project terms).

**Anti-recommendations:** don't make CapCut the *home* of brand assets
(ToS posture above — fine as a free editor); skip Panzoid/Renderforest
(dated ceiling, cloud lock-in, undocumented licensing).

## Pillar K — the thumbnail & title canon (new)

- **K1 (T1 placement / T2 the stat).** "90% of the best-performing videos
  have custom thumbnails" is live on YouTube's official Thumbnail & title
  tips page — but no methodology, sample, or date has ever been
  published. Cite the page, tier the number T2.
  [Thumbnail & title tips](https://support.google.com/youtube/answer/12340300)
  — Evidence: live page fetched verbatim; the stat migrated here from the
  retired Creator Academy.
- **K2 (T1).** CTR mechanics, official: impressions CTR = "How often
  viewers watched a video after seeing a thumbnail"; "Half of all channels
  and videos on YouTube have an impressions CTR that can range between 2%
  and 10%." Official caveats on the same FAQ: new videos (<1 week) and
  low-view videos swing wildly — don't judge CTR right after upload;
  small loyal audiences run HIGHER CTR; impressions exclude external
  sites and end screens; and **artificially high CTR with low average
  view duration won't be recommended** — the click must be validated by
  retention (ties C1 and H3/H6: packaging earns the click, the video
  keeps it).
  [Impressions & CTR FAQ](https://support.google.com/youtube/answer/7628154) ·
  [Impressions & watch time](https://support.google.com/youtube/answer/9314486)
  — Evidence: both help pages fetched verbatim.
- **K3 (T1 — corrects the universally-copied spec).** Current official
  thumbnail spec: recommended resolution **3840×2160** ("with minimum
  width of 640 pixels"), 16:9 ("most used in YouTube players and
  previews"; 1:1 for podcasts), JPG/GIF/PNG, size limits split by
  surface: **2 MB mobile** (10 MB podcasts), **50 MB desktop**. The
  internet's standard "1280×720, under 2 MB" line is a superseded spec.
  [Add custom thumbnails](https://support.google.com/youtube/answer/72431)
  — Evidence: live page fetched verbatim twice this round (two
  independent fetches, same figures).
- **K4 (T1).** Native A/B testing exists and titles ARE testable:
  "Test & compare" (Studio now labels it "A/B Testing") runs **up to 3
  titles and thumbnails** — Title only / Thumbnail only / Title and
  thumbnail — and picks the winner on **watch time, not CTR**: "the
  option with the highest watch time will be shown to all viewers,"
  optimizing "overall watch time over other metrics, like
  click-through-rate." Tests run up to 2 weeks with a small control
  group excluded from calculations. Desktop Studio + advanced features
  required; excluded: Shorts, scheduled lives, Premieres (until
  post-premiere), made-for-kids, mature, private. Outcomes reported as
  Winner / Performed Same / Inconclusive (T3: vidIQ, updated
  2026-07-10). YouTube's launch guidance: test variants with "distinct
  differences, such as variations in layout compositions, backgrounds
  and text overlays." Third-party testers (ThumbnailTest — mechanics
  verified from its own page; TubeBuddy — unverified, site 403'd) rotate
  variants **over time**, which confounds variant with day/audience —
  the native test is the only randomized instrument available.
  [Test & compare (official)](https://support.google.com/youtube/answer/13861714) ·
  [TechCrunch launch coverage](https://techcrunch.com/2024/06/12/youtube-creators-can-test-multiple-video-thumbnails/) ·
  [vidIQ status 2026-07](https://vidiq.com/blog/post/youtube-launches-new-thumbnail-testing-tool/) ·
  [ThumbnailTest mechanics](https://thumbnailtest.com/)
  — Evidence: official help page fetched verbatim and re-verified; this
  round REFUTES "title testing hasn't shipped" (one research pass missed
  the page; the fetched page settles it).
- **K5 (T1).** YouTube's own craft rules (the only first-party design
  guidance that exists): keep the design simple — "Dynamic use of color
  and composition can help catch the eye, but too much can overwhelm
  it"; use the rule of thirds; use "a font that's easy to read" if
  adding text; thumbnails render at many sizes, so build large; for
  casual viewers highlight "actions and emotions that are more
  universally relatable, like a shocked face." Title guidance, same
  page: be accurate (misrepresentation hurts retention), be succinct,
  front-load key words.
  [Thumbnail & title tips](https://support.google.com/youtube/answer/12340300)
  — Evidence: live page fetched verbatim.
- **K6 (T4 — transcript mirrors, not audio-verified).** MrBeast's craft
  canon (Lex Fridman #351): winning thumbnails "tend to be clear, tend
  to not have much clutter, tend to be pretty simple"; his face "left
  side, very big. So, brand recognition"; contrast-legibility teardowns
  (a flag and pole "the same color... harder to see the flag"; "why are
  the cops in your thumbnail wearing yellow vests?"; "why not make the
  cars cop cars?"); "The more extreme the opinion, typically the higher
  the click-through rate. If you can... pay it off in the content, then
  it just supercharges it"; "Negative click-bait's much easier than
  positive click-bait." Iteration culture: a draft is "version, like,
  one of, like, 1,000." Note: the famous numeric "3 elements max" rule
  appears in NO primary source (see Refuted) — what's sourced is
  clear / no clutter / simple.
  [transcript mirror](https://podscripts.co/podcasts/lex-fridman-podcast/351-mrbeast-future-of-youtube-twitter-tiktok-and-instagram)
  — Evidence: two independent transcript mirrors agree; original
  lexfridman.com transcript URL 404'd this round.
- **K7 (T1-R — with an honesty rail).** Faces and text attract gaze:
  free-viewing subjects look at faces and text "16.6 and 11.1 times more
  than similar regions normalized for size and position" (Cerf, Frady &
  Koch, *Journal of Vision* 2009; 419+ citations). This is static-scene
  gaze research — it is **not** evidence that faces raise YouTube CTR;
  no platform-level study of thumbnail features vs CTR exists (the
  academic literature is clickbait-*detection*-framed, e.g.
  YTClickbait21K 2026). The craft canon is essentially untested
  academically.
  [Cerf et al. 2009](https://doi.org/10.1167/9.12.10) ·
  [YTClickbait21K](https://arxiv.org/abs/2606.14780)
  — Evidence: abstract verified via Semantic Scholar API (publisher page
  403'd); arXiv abstract for the dataset paper.
- **K8 (T1 policy floor + T4 flywheel).** Title + thumbnail are one
  packaging unit that gates virality. Veritasium ("My Video Went Viral.
  Here's Why"): "the title and thumbnail are everything"; "you can have
  a great video but unless you have a great hook to get people in it's
  not going to go viral"; and relaying MrBeast's data: "as you approach
  10%, 20%, 30% click-through rate, then the number of views and the
  number of impressions that video will get just skyrockets." The
  official floor: "maliciously misleading titles, thumbnails,
  descriptions" that "trick users into clicking on a video that does not
  deliver what was promised" are policy violations — the bar is
  *malicious* mismatch, not curiosity framing; the real penalty for
  soft mismatch is K2's retention validation. Upgrades E4's sourcing:
  Paddy Galloway's track record is now verified (MrBeast on his site:
  "Paddy did consulting work with me, I hard vouch for him"; ~700M
  monthly client views claimed) but his packaging doctrine still has no
  public primary quote — E4 stays T3.
  [Veritasium video](https://www.youtube.com/watch?v=fHsa9DqmId8) ·
  [misleading-metadata policy](https://support.google.com/youtube/answer/2801973) ·
  [paddygalloway.com](https://paddygalloway.com)
  — Evidence: full caption transcript (two independent transcriptions
  this round, matching quotes — note one pass mislabeled the video's
  title; the video ID and quotes are confirmed); policy page fetched
  verbatim.
- **K9 (T1 limit + T3/T4 length craft).** Titles: hard limit **100
  characters** (official, fetched). Display truncation is
  surface-dependent and has NO official number — SEO-tool measurements
  disagree (~40–50 mobile, ~60–70 desktop). The "under 50 characters"
  canon traces to MrBeast ("this title is under 50 characters and seems
  really intriguing to me" — T4 via a creator's breakdown of his advice;
  prefers first-person "I explored" over "Exploring") and to Briggsby's
  2018 search study (top-20 results average 47–48 chars — correlational,
  search-only, 8 years old, and the likely upstream of the entire
  folklore). Practical rule: load-bearing words inside the first ~50
  chars, and it's testable natively (K4).
  [title/description limits](https://support.google.com/youtube/answer/57407) ·
  [MrBeast advice breakdown](https://pickscribe.com/v/alOV2WVWvx4) ·
  [Briggsby study](https://www.briggsby.com/reverse-engineering-youtube-search)
  — Evidence: limit verbatim from live page; length claims honestly
  tiered T4/T3-correlational.
- **K10 (T4).** Shorts thumbnails barely matter: Jenny Hoyos — "The
  thumbnail does not matter for the most part because most people
  creating shorts are creating for browse"; exception: searchable Shorts
  (tutorials), where the move is "make your first frame look like a
  thumbnail by having whatever text on screen that you want." Ties H9
  (the first frame IS the packaging).
  [Hoyos interview mirror](https://yt.aibeginner.org/harrydry-1-billion-views-is-easy-jenny-hoyos-interview-claude-sonnet-4-5-20250929/)
  — Evidence: unofficial transcript mirror of the Harry Dry interview;
  single source — platform-side confirmation is a Deeper Thread.

**Zing measures:** (via `zing thumbs`, below) candidate-frame image stats,
caption-overlap exclusion, small-size legibility proxy. **Zing judges:**
thumbnail-promise vs hook-window transcript congruence (H6/K2) — the same
machinery H3 already requires.

## SPEC — `zing thumbs` (S4): freeze-frame candidates + three crafted prompts

Zing-derived; inherits the confidence of the criteria it cites. Design
stance per ROADMAP: **Zing picks frames and writes prompts; the user's
image model renders. No image generation inside Zing.** Why exactly
three prompts: K4 — YouTube's native A/B instrument accepts up to 3
variants, so one `zing thumbs` run emits one native test's worth of
genuinely distinct packaging hypotheses (YouTube's own advice: variants
need "distinct differences"). This is the fix for "prompted thumbnails
suck": generic prompts fail because they carry neither the craft rules
nor the video's actual content — every prompt below carries both, plus
the real freeze-frame as a reference image.

### Stage 1 — pick 3–5 candidate freeze-frames from the Breakdown

Inputs that exist today (`schemas.py`): `shots[]` (+ per-shot
`keyframe`), `words[]` (timed transcript), `captions[]` (OCR),
`audio.loudness_curve` (1/s dBFS), `meta.title`, `cuts_per_10s`,
`judgment` slots, and the `get_frames(slug, timestamps)` tool.

Selectors, in priority order (each names its evidence):

1. **Emotional peak** (K5 "shocked face" T1; K7 faces attract gaze).
   Timestamps where `loudness_curve` has a local max ≥ ~6 dB above its
   rolling median AND speech is present (a reaction: laugh, shout,
   gasp). Take the nearest shot start; the S2 judgment confirms via
   `get_frames` that a visible face with a high-arousal expression is
   actually there.
2. **Payoff / object reveal** (K8 curiosity gap — promise, don't
   spoil). First timestamp where the title's key noun is spoken
   (`meta.title` tokens ∩ `words[]`), and the shot that shows the
   object. Prefer the SETUP shot just before full resolution — the
   thumbnail teases the payoff, never resolves it.
3. **Hook-window frame** (H3/H6 congruence). The best shot start inside
   0–3s is always a candidate: the thumbnail must promise what the
   opening delivers, and the opening frame trivially satisfies that.
4. **Contrast/composition peak** (K5 simplicity + legibility).
   Remaining keyframes ranked by measurable image statistics — RMS
   contrast, colorfulness, sharpness (ffmpeg `signalstats`) — keeping
   frames that survive being rendered ~120 px wide (the pixel threshold
   is lore, but "legible when small" is K5's own advice).

Hard rules: skip frames overlapping `captions[]` events (no baked-in
captions in a thumbnail); skip within ~0.2s of a cut (transition
smear); dedupe near-identical candidates (perceptual hash); extract at
source resolution (upload target is K3's spec, minimum width 640).
Output: 3–5 candidates, each labeled `{timestamp, selector,
one-line "what this frame shows"}`.

### Stage 2 — emit THREE distinct prompts (one per archetype)

Craft constants baked into every prompt (with honest tiering):
16:9 at 3840×2160 (K3, T1) · simple composition, 2–3 elements max (K5
T1 "too much can overwhelm" + K6 "no clutter"; the numeric cap is
codified lore pointing the T1 direction) · one dominant subject ≥ ⅓ of
frame, rule-of-thirds placement (K5 T1) · strong subject/background
separation in BOTH hue and luminance (K6 teardowns, T4) · legible at
~120 px wide (lore, harmless) · text: none, or ≤3 words that do NOT
repeat the title (complementarity — T3 lore, flagged) · no logos,
watermarks, borders (P2) · style matches the video's real footage
(H6 congruence: never promise a look the video doesn't have).

- **Archetype 1 — EMOTION** (K5 T1 + K6 + K7): a real human face,
  large, high-arousal expression, off-center, reacting TO the video's
  key object or moment. Uses the emotional-peak frame.
- **Archetype 2 — OBJECT/RESULT TEASE** (K8 curiosity gap): the payoff
  object or scene dominant, partially revealed or mid-transformation;
  no face required; promises the outcome without resolving it. Uses the
  reveal frame.
- **Archetype 3 — STORY CONTRAST** (K4 "distinct layout" mandate): a
  two-element juxtaposition — before/after, A-vs-B, scale mismatch,
  expectation-vs-reality — the video's core tension as one image. Uses
  whichever candidate pair expresses the tension.

Every prompt ships with its freeze-frame attached as the reference
image ("keep this real person/object recognizable; re-light and
re-compose, don't replace") — identity + scene grounding is what
generic prompting lacks.

### Stage 3 — congruence gate (H6, T1)

Before emitting, each prompt's one-line PROMISE is checked against the
hook-window transcript (0–30s). If the opening cannot cash the promise,
revise or drop the prompt. This encodes YouTube's own intro grading at
generation time and keeps Zing on the right side of K8's policy floor.

### Worked template

```text
You are generating a YouTube thumbnail. Use the attached freeze-frame
(t={TS}s from the video) as the identity and scene reference — keep the
real {person/object} recognizable; re-light and re-compose, do not
replace them.

CANVAS: 16:9, 3840x2160.
COMPOSITION ({ARCHETYPE}): {archetype composition line}. Maximum 3
elements: {element 1}; {element 2}{; element 3}. One dominant subject
filling at least a third of the frame, placed on the {left|right} third,
facing page-center.
SUBJECT: {who/what, from the breakdown} {doing/expressing what — the
moment this frame was selected for}.
BACKGROUND: simplified version of the real scene ({scene description}),
decluttered; strong hue AND luminance contrast against the subject
({subject palette} against {background palette}).
STYLE: {photographic|animated — match the video's footage}; crisp edges,
clean subject lighting, no motion blur.
TEXT: {none | "{<=3 words}" in a heavy sans-serif with a contrast box —
words must NOT appear in the title: "{TITLE}"}.
MUST READ AT 120 PIXELS WIDE: remove any detail that would not survive
that size.
DO NOT: logos, watermarks, borders, UI elements, extra faces, more than
3 elements; do not depict {the payoff spoiler} — show the setup, not
the resolution.
```

Plus one line OUTSIDE the prompt, kept by Zing for the congruence gate:
`PROMISE: "{one-line promise}" — delivered at t={X}s: "{transcript
quote from the first 30s}".`

**Filled example** (talking-head tech video, title *"I benchmarked 5
GPUs so you don't have to"*; emotional peak at t=312.4s — loudness
+8 dB over median on "no WAY it's twice as fast"; reveal shot of the
test bench at t=45.2s):

```text
You are generating a YouTube thumbnail. Use the attached freeze-frame
(t=312.4s from the video) as the identity and scene reference — keep
this real person recognizable; re-light and re-compose, do not replace
them.

CANVAS: 16:9, 3840x2160.
COMPOSITION (EMOTION): large reacting face plus one object. Maximum 3
elements: the creator's shocked face; one GPU held toward camera; a
single green bar chart spiking off the top of frame. One dominant
subject (the face) filling at least a third of the frame, placed on the
left third, facing page-center.
SUBJECT: the creator from the reference frame, eyes wide, mid-shout —
the moment he sees a result twice as fast as expected.
BACKGROUND: his real desk setup simplified to a dark, softly lit wall;
strong hue AND luminance contrast against the subject (warm skin tones
and a green chart against deep navy).
STYLE: photographic — match the video's footage; crisp edges, clean
subject lighting, no motion blur.
TEXT: "2x FASTER?" in a heavy sans-serif with a contrast box — words
must NOT appear in the title: "I benchmarked 5 GPUs so you don't have
to".
MUST READ AT 120 PIXELS WIDE: remove any detail that would not survive
that size.
DO NOT: logos, watermarks, borders, UI elements, extra faces, more than
3 elements; do not depict the winning GPU's name — show the reaction,
not the verdict.
```

`PROMISE: "one GPU result will shock you" — delivered at t=8.1s: "one
of these cards embarrassed the other four and it is not the one you
think".`

## Pillar U — upload mechanics (new)

- **U1 (T1).** Where metadata matters: title/thumbnail/description are
  "more important pieces of metadata for your video's discovery," while
  tags "play a minimal role" (useful mainly for common misspellings).
  Search relevance officially weighs "how well the title, tags,
  description, and video content match your search query" plus
  engagement and quality; **recommendations run on behavior** — clicks,
  watchtime, survey-measured "valued watchtime," shares/likes/dislikes —
  not metadata (official recommendations blog + How-YouTube-Works page
  list no metadata signal).
  [metadata help](https://support.google.com/youtube/answer/146402) ·
  [how search works](https://support.google.com/youtube/answer/16090438) ·
  [Goodrow on recommendations](https://blog.youtube/inside-youtube/on-youtubes-recommendation-system/)
  — Evidence: all three fetched; quotes verbatim from the help pages.
- **U2 (T1).** Descriptions & hashtags: description cap **5,000
  characters** (verbatim). Hashtags: more than **60 → every hashtag on
  the content is ignored** (verbatim); up to **three hashtags "that are
  considered most engaging"** appear by the title — YouTube picks them,
  so the folk rule "your first 3 hashtags show" is outdated. No official
  above-the-fold character count for descriptions exists — front-load
  the first lines as directional craft, don't quote "125 chars" numbers.
  [limits](https://support.google.com/youtube/answer/57407) ·
  [hashtag policy](https://support.google.com/youtube/answer/6390658)
  — Evidence: both pages fetched verbatim.
- **U3 (T1).** Chapters: manual chapters require a list starting at
  **00:00**, at least **3 timestamps** in ascending order, each chapter
  **≥10 seconds** — all three folklore numbers verified exact on the
  live page. Auto-chapters are on by default for new uploads; manual
  overrides automatic. Bonus surface: for YouTube-hosted videos, Google
  Search "key moments" can be driven by "the exact timestamps and labels
  in the video description" (Google's own developer docs) — chapters are
  also external-search packaging. NO official statement exists on
  whether chapters help or hurt watch time (see Not found).
  [chapters help](https://support.google.com/youtube/answer/9884579) ·
  [Google Search video docs](https://developers.google.com/search/docs/appearance/video)
  — Evidence: both fetched verbatim.
- **U4 (T1 absence + T1 Trending + T3).** Scheduling, honestly: **no
  official ranking document lists publish time, day, or upload frequency
  as a signal** — verified absence across the live search-ranking page,
  the recommendations page, and the official recommendations blog post.
  View velocity is official ONLY for Trending ("How quickly the video's
  view count... or 'temperature'... is growing," refreshed ~every 30
  min) — it does not generalize to Home/Suggested. The "algorithm
  decides in 24–48h" belief has no official source (and platform staff
  have publicly pushed back — primary quotes not pinned this round, so
  the debunk also lacks T1; both stay unproven). What IS real: the
  Studio audience heatmap ("When your viewers are on YouTube" —
  universally reported, thinly documented officially), and third-party
  timing datasets that *disagree with each other* (Buffer, 1.8M videos:
  long-form peaks Sunday ~10am, Shorts Friday 4–7pm — near-opposite;
  vidIQ claims different day deltas), which is itself evidence timing is
  audience-specific, not algorithmic. Pragmatic default: publish 2–4h
  before your audience's card peak (T3), and ignore universal
  best-time charts.
  [Trending signals](https://support.google.com/youtube/answer/7239739) ·
  [Buffer dataset](https://buffer.com/resources/best-time-to-post-on-youtube/) ·
  [vidIQ timing](https://vidiq.com/blog/post/best-time-publish-video-youtube/)
  — Evidence: Trending page fetched verbatim; absence checks on the
  fetched ranking pages; timing data honestly flagged as non-official.
- **U5 (T1).** Remaining packaging surfaces: **Premieres** are a
  shared-watch mechanic (countdown, live chat, stays as a normal upload)
  — the official page makes NO performance claims; "Premieres boost the
  algorithm" is not an official statement. **Pinned comments** as
  packaging, YouTube's own suggested uses: clarify something, ask a
  specific question, "tease a specific moment or easter egg," thank
  viewers; hearting may notify the commenter. **Playlists**: the current
  help doc is purely procedural — the famous "playlists increase session
  time" line lived in the retired Creator Academy and is currently
  unverifiable.
  [Premieres](https://support.google.com/youtube/answer/9080341) ·
  [comments/pinning](https://support.google.com/youtube/answer/11913117) ·
  [playlists](https://support.google.com/youtube/answer/57792)
  — Evidence: all three fetched; absence of performance claims verified
  on the fetched pages.

**Zing ships this as a plain-language upload checklist** (prompt-pack
advisory, per the R-3 product note): load-bearing words in the first
~50 of the title's 100 chars (K9); description front-loaded, chapters
block 00:00 / ≥3 / ≥10s (U3); ≤3 meaningful hashtags (U2); schedule by
YOUR audience heatmap, not folklore charts (U4); leave end-screen room
in the final 20s (O1); thumbnails via `zing thumbs`, validated in the
native A/B test (K4).

## Refuted / not found this round

- **"1280×720, <2 MB" as the current thumbnail spec — SUPERSEDED.** Live
  page: 3840×2160 recommended, min width 640, 2 MB mobile / 50 MB
  desktop (K3). The most-copied spec line on the creator internet is
  stale.
- **"Title A/B testing hasn't shipped" — REFUTED in-round.** The
  official Test & compare page (fetched, re-verified) covers Title only /
  Thumbnail only / Title and thumbnail (K4).
- **"Branded intros lose X% of viewers" — no such study exists.** Only
  T1 "first 30s is graded" (H6) + T3 keep-it-short consensus +
  evidence-free template-seller blogs ("3–5s", "3–7s") that sell intros.
  Any attached percentage is unsourced.
- **Visible Measures "20% leave in the first 10 seconds" — real number,
  wrong context.** 2010 study of web/ad video; company defunct, primary
  offline, pre-modern-YouTube. Never a YouTube-retention finding; do not
  cite it as one.
- **Creator Academy "you have 15 seconds to hook viewers" — retired
  doctrine.** Survives only in secondary blogs; current live guidance
  grades the first 30 seconds (H6). (H1's Playbook post remains valid as
  a dated platform statement.)
- **"90% custom thumbnails" methodology — never published** (K1: the
  page is T1, the number is T2).
- **MrBeast's "3 elements max" as a quote — not found** in any primary;
  sourced reality is "clear... not much clutter... pretty simple" (K6).
  The numeric rule is lore.
- **"≤3–4 words of text", "readable at 120px", "bright saturated colors
  lift CTR", thumbnail-title complementarity, contrast-against-UI — all
  lore.** No data located for any; YouTube's own page actively warns
  that too much color/composition "can overwhelm" (K5). The SPEC encodes
  these only where they point the same direction as T1 guidance, flagged.
- **"Faces raise YouTube CTR" as platform data — not found.** Only
  static-scene gaze research (K7) plus YouTube's "shocked face" tip
  (K5). No thumbnail-feature-vs-CTR study exists, academic or platform.
- **End-screen CTR benchmarks — none public.** Per-element clicks exist
  only inside each creator's Studio.
- **"Shorts optimize for 2+ loops" — CONTRADICTED** by the Shorts
  product lead on YouTube's own channel: "It's not like we strictly
  optimise for two loops" (O4). Loops pay via rewatch watch-time only.
- **"Your first 3 hashtags are shown" — outdated.** YouTube displays up
  to three hashtags "considered most engaging" — it picks them (U2).
- **Description above-the-fold counts ("first 100–150 chars") —
  folklore.** Uncited by every source repeating them; only the
  directional front-load advice survives.
- **"First 24–48h decide the video" — unsupported.** Velocity is
  official only for Trending (U4); no lock-in statement exists; the
  official-side debunk also lacks a pinned primary quote this round.
- **Chapters help/hurt watch time — no official statement either way**
  (U3); the practitioner debate has no named, fetchable sources at T3
  standard yet.
- **"Playlists increase session time" as an official claim —
  unverifiable.** Retired with the Creator Academy; current docs are
  procedural only (U5).
- **Upload consistency / "breaks hurt you" — no primary reached.**
  Creator Insider's breaks research (breaks don't cause lasting harm)
  reached this round only via Reddit relays; do not present as verified.
- **Official per-surface title truncation counts — do not exist**;
  SEO-tool measurements disagree (~40–70 chars). Only the 100-char input
  limit is official (K9).
- **TikTok "63% of high-CTR videos hit the key message in 3s" — not
  located**; the live TikTok best-practices page contains no percentages
  at all.
- **TubeBuddy A/B mechanics — unverified** (vendor pages 403'd);
  ThumbnailTest's rotation IS verified from its own page — both share
  the time-confound weakness vs the native test (K4).
- **Paddy Galloway's packaging doctrine in his own words — still not
  found** (site has testimonials, no doctrine). E4 remains T3 via
  interviews/secondary; his track record is now verified (K8).
- **Attribution correction made in-round:** the Veritasium quotes in K8
  come from "My Video Went Viral. Here's Why" (fHsa9DqmId8; two
  independent transcriptions agree) — one research pass had labeled them
  with the title of his other video, "Clickbait is Unreasonably
  Effective" (S2xHZPH5Sng), which is located but untranscribed.

## Deeper Threads (R-4 candidates)

1. **Transcript-mine the canon at scale.** The caption-track pipeline
   proved out (~40K chars/hour-episode, verbatim): point it at Colin &
   Samir's MrBeast and Galloway episodes, "The New Rules of YouTube
   (2025)" (L9CO1FcRHCM), Creator Insider's retention/breaks/upload-time
   videos, Veritasium's "Clickbait is Unreasonably Effective"
   (S2xHZPH5Sng), and audio-verify the Lex #351 quotes — converts a
   dozen T4s into timestamped T3s, and could close the 24–48h-debunk and
   breaks-research gaps in one pass.
2. **MrBeast doc systematic pass.** The full 36-page archived text
   (H7/O3 source) has more: re-engagement cadence, "wow moments," CTR
   targets — map it against the rubric pillars as a structured retention
   playbook.
3. **Test & Compare field data.** Creator-published watch-time-share
   deltas from native tests + YouTube's published lift numbers — the
   first honest effect sizes for packaging changes, from the only
   randomized instrument. Directly calibrates how much `zing thumbs`
   variants can matter.
4. **Owned-channel branded-intro A/B.** Since no public study exists:
   same video, sting vs cold open, compare official 30s intro retention
   (H6) — turns the biggest intro Not-Found into owned data (same
   pattern as R-2's loudness-measurement thread).
5. **Shorts surfaces audit.** Which surfaces actually show a Short's
   thumbnail (search, channel tab, suggested-as-video), platform-side
   confirmation of K10, and the official Shorts view-count article to
   lift O4 from T2 to T1.
6. **DIY truncation measurement.** Browser-automation pass over ~50
   videos at desktop/mobile widths measuring rendered title characters —
   would beat every published source (none are rigorous) and pin K9's
   display numbers.
7. **AI motion-tool license pass (2025–26).** Runway/Pika as sting
   generators, CapCut Dreamina, Canva Magic Media, AE's AI features —
   quality ceiling AND license posture (where AI tools hide the catch);
   also fetch the Canva/Artlist license pages that blocked this round.

**Recheck-before-launch:** every surface here is a living page — the
thumbnail spec already changed once (K3), Test & Compare is actively
evolving (Studio relabeled it "A/B Testing" mid-2026), hashtag display
behavior changed silently (U2), and the Shorts view definition changed
2025-03 (O4). Re-verify K3/K4/U2/U3 and the tool licenses before
anything user-visible ships.
