# Editing Craft & Technical Specs (R-2, v0.1, 2026-07-18)

Fills the TASTE-FRAMEWORK.md R-2 agenda gaps: editing-craft verification
(Murch primary text, pacing research, caption conventions), audio/loudness
targets, per-platform safe zones, and independent research on AI-video
perception. Criterion IDs continue the parent scheme (E5+, P3+, A4+).
Every claim carries a tier, a source link, and a one-line evidence note.

**Tiers** as in TASTE-FRAMEWORK.md (T1 verified-platform / T2
platform-statement / T3 practitioner-consensus, named / T4 single-opinion),
plus one extension this round needs:
- **T1-R research** — peer-reviewed academic paper or standards-body
  technical document, primary source located. Strongest available tier for
  non-platform claims.

---

## Pillar E — Editing craft (continued; E1–E4 are in TASTE-FRAMEWORK.md)

- **E5 (T3, primary text verified via convergent quotation).** Murch's Rule
  of Six weights CONFIRMED as E1 stated: Emotion 51%, Story 23%, Rhythm 10%,
  Eye-trace 7%, 2D plane of screen 5%, 3D space of action 4% — from *In the
  Blink of an Eye* pp. 17–20. "An ideal cut (for me) is the one that
  satisfies all the following six criteria at once." Weights quoted
  identically, with page numbers, by a UC Berkeley course text and
  StudioBinder; no source disputes them.
  [Berkeley iSchool (quotes pp.17–20)](https://blogs.ischool.berkeley.edu/i290-viznarr-s12/the-rule-of-six-walter-murch/) ·
  [StudioBinder](https://www.studiobinder.com/blog/walter-murch-rule-of-six/)
  — Evidence: two independent sources reproduce the list verbatim with
  matching numbers and page citations; physical-copy check still open.
- **E6 (T3, primary text verified).** Murch's degradation rule — when a cut
  can't satisfy everything, sacrifice from the BOTTOM of the list, verbatim:
  "If you have to give up something, don't ever give up emotion before
  story. Don't give up story before rhythm, don't give up rhythm before
  eye-trace, don't give up eye-trace before planarity, and don't give up
  planarity before spatial continuity." Emotion is "the thing that you
  should try to preserve at all costs."
  [No Film School (quotes the book)](https://nofilmschool.com/2016/11/6-rules-good-cutting-according-oscar-winning-editor-walter-murch)
  — Evidence: verbatim book quotation; matches E5 sources' paraphrase.
- **E7 (T3, primary text — the "when to cut" thesis).** The book's central
  claim: blinks punctuate thought — we blink "to separate and punctuate
  ideas" — and a cut belongs where the viewer would blink: where one idea
  completes and the next begins, driven by the emotional state of the
  audience, not by continuity. Each shot has multiple potential cut points;
  the right one depends on "what the audience has been thinking up to that
  moment and what you want them to think next." Direct support for the E3
  "cut when the viewer can complete the thought" heuristic.
  [Wikipedia book page](https://en.wikipedia.org/wiki/In_the_Blink_of_an_Eye_(Murch_book))
  — Evidence: consistent across the book page, Goodreads summary, and
  practitioner writeups; paraphrase, not verbatim.
- **E8 (T1-R).** Cut-rhythm research exists and is peer-reviewed: Cutting,
  DeLong & Nothelfer (Psychological Science, 2010; 150 top films 1935–2005,
  every shot measured) — shot-length sequences in modern film increasingly
  follow a 1/f ("pink noise") pattern matching the natural fluctuation of
  human attention; films made after 1980 approach it most closely.
  Companion study ("Quicker, faster, darker", i-Perception 2011, 160 films
  1935–2010): average shot length fell from ~10s (1930s–40s) to under 4s
  (post-2000), alongside more motion and darker frames.
  [Cutting et al. 2010](https://journals.sagepub.com/doi/10.1177/0956797610361679) ·
  [Quicker, faster, darker (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC3485803/)
  — Evidence: primary journal pages located; note this is descriptive
  correlation with attention structure, NOT a causal engagement result, and
  no verified short-form-specific ASL norm exists (see Not Found).
- **E9 (T1 for Netflix's spec; scope: long-form subtitle craft).** The
  strongest published caption readability numbers, verified verbatim from
  Netflix's live Timed Text Style Guide (English USA): max **42 characters
  per line**, max **2 lines**, reading speed up to **20 characters/second**
  (adult), **17 cps** (children). BBC's guideline (via secondaries; official
  page unreachable this round, so T2): 160–180 words per minute, 37 chars
  per Teletext line.
  [Netflix TTSG](https://partnerhelp.netflixstudios.com/hc/en-us/articles/217350977-English-USA-Timed-Text-Style-Guide) ·
  [BBC guide summary](https://www.clevercast.com/bbc-subtitling-guidelines/)
  — Evidence: Netflix page fetched and quoted; BBC figures corroborated by
  multiple independent subtitling references.
- **E10 (T3 style norm + T4 performance claims — keep them separate).**
  Word-timed "karaoke" pop captions (1–3 words highlighted per beat) are
  the documented dominant short-form caption style in 2025–26 tooling and
  practice. BUT every "karaoke captions increase retention/completion X%"
  claim found traces to caption-tool vendors — treat as unverified
  marketing (T4 at best). Independent accessibility analysis argues the
  style actively harms readers: hides sentence structure, outpaces slower
  readers, drops non-speech information, defeats reduced-motion settings,
  and burned-in words are invisible to screen readers.
  [Disabled World analysis](https://www.disabled-world.com/disability/accessibility/karaoke-captions.php)
  — Evidence: style dominance is cross-confirmed by many tool ecosystems;
  no independent retention data located (see Not Found). Zing implication:
  offer word-timed style as genre default but keep phrase-grouped captions
  as the accessibility-clean option, and never exceed E9 reading speeds.

**Zing measures:** cut density vs genre, shot-length variance (metronome
cutting = suspicious regularity; E8 says natural attention is 1/f, not
constant), caption chars/line + cps against E9 caps. **Zing judges:** each
cut against the E5 hierarchy — was it motivated by emotion/story, or only
by rhythm/continuity?

## Pillar P — Production floor (continued)

### Safe zones (R-2 item from P1 — resolved to the extent the platforms allow)

- **P3 (T1 for the mechanism, T3 for the pixels).** TikTok: the official
  in-feed ad spec page confirms safe-zone files exist and — key finding —
  that the safe zone is **not fixed**: "The safe zone size is determined by
  the dimension (vertical, horizontal, or square), ad caption length, and
  any additional formats used. Downloadable safe zone files are available
  below." Exact margins live only in downloadable .zip files, not on any
  live page. The consensus figures replicated across independent
  measurement tools for 1080×1920: **top 130px, bottom 484px, left 44px,
  right 140px** (usable center ≈ 896×1306) — consistent everywhere but not
  officially verifiable on a live page, so T3-measured.
  [TikTok in-feed spec (official)](https://ads.tiktok.com/help/article/tiktok-auction-in-feed-ads?lang=en) ·
  [measured consensus example](https://getkoro.app/blog/tiktok-safe-zone-guide)
  — Evidence: official page fetched (also verified there: 9:16 ≥540×960,
  ≤10 min, ≤500MB, ≥516 kbps); px figures match across ≥5 independent
  tools/guides.
- **P4 (T2).** Meta Reels/Stories: an official Meta Business Help article
  exists ("About text overlays and the Safe Zone for ads in Stories and
  Reels") but is login-walled to automated fetch, so its numbers could not
  be verified verbatim this round. Figures consistently attributed to it:
  keep critical content out of the top **14%**, bottom **35%**, and **6%**
  each side (≈ top 269px / bottom 672px / sides 65px at 1080×1920). Multiple
  sources report Meta unified the Stories + Reels 9:16 safe zone in March
  2026, with an Ads Manager "safe zone guardrail" preview to validate.
  [Meta official article (login-walled)](https://www.facebook.com/business/help/980593475366490) ·
  [corroboration](https://blog.adnabu.com/meta-ads/meta-safe-zones/)
  — Evidence: platform-attributed numbers, cross-consistent across
  independent guides; verbatim confirmation blocked (upgrade path: fetch
  logged-in via browser).
- **P5 (T3-measured; no official numbers exist).** YouTube Shorts: Google's
  live Shorts-ads spec page (fetched) gives **no** safe-zone pixels — only
  that vertical 9:16 is recommended, the right-hand side carries
  like/dislike/comment/share, a CTA appears 3s in, and only the first 60s
  play in the Shorts feed. Google's vertical-video help refers to a "safe
  area reference image" for ads generally. Independent overlay measurements
  cluster at: top ~180–240px, bottom ~350–480px, right ~120–200px, left
  ~40–60px on 1080×1920.
  [Google Shorts ads specs (official, fetched)](https://support.google.com/google-ads/answer/16041697?hl=en-GB) ·
  [Google vertical video help](https://support.google.com/google-ads/answer/9128498?hl=en) ·
  [measured example](https://www.poster.ly/tools/youtube-shorts-safe-zone-checker)
  — Evidence: official pages verified to lack numbers; community figures
  agree in range but vary in exact px — treat as an envelope, not a spec.
- **P6 (Zing-derived; renderer rule).** Universal safe box for one
  9:16 master across all three platforms (union of the worst margins in
  P3–P5, conservative ends): on 1080×1920 keep text/logos/CTAs inside
  **x ∈ [65, 880], y ∈ [270, 1248]** — i.e. top 270 (Meta 14%), bottom 672
  (Meta 35%, dominates TikTok's 484), left 65 (Meta 6%), right 200 (Shorts
  action rail). Derived from mixed tiers (T2/T3 inputs) — encode as default,
  expose per-platform override.
  — Evidence: arithmetic over P3–P5; inherits their confidence.

### Loudness & mix

- **P7 (T1 for Spotify; T3-measured for YouTube — the "-14 official" meme
  is overstated).** Loudness normalization targets: **Spotify officially
  documents -14 LUFS** (ITU-R BS.1770; premium settings Normal -14 / Loud
  -11 / Quiet -19; quiet tracks get positive gain only up to -1 dBTP
  headroom). **YouTube normalizes to ≈ -14 LUFS but publishes no number**
  in any help doc found — the value is practitioner-measured (mastering
  engineer Ian Shepherd: "-14 has recently been adopted by YouTube") and
  replicated by many engineers via the player's "Stats for nerds" →
  content-loudness readout; normalization is **down-only** (quiet videos
  are not turned up). YouTube's documented feature is "stable volume"
  (dynamic-range balancing, a different mechanism).
  [Spotify official](https://support.spotify.com/us/artists/article/loudness-normalization/) ·
  [Production Advice (Shepherd)](https://productionadvice.co.uk/how-loud/) ·
  [YouTube stable-volume help](https://support.google.com/youtube/answer/14106294)
  — Evidence: Spotify page is the platform's own doc; YouTube figure is
  convergent measurement, never platform-published — tier it honestly.
- **P8 (T1-R standards-body).** AES TD1008 ("Recommendations for Loudness of
  Internet Audio Streaming and On-Demand Distribution"): distribute
  track-normalized music at **-16 LUFS**; album-normalized: loudest track
  -14. A sane floor for Zing masters given platform down-only behavior.
  [AES TD1008 PDF](https://aes2.org/wp-content/uploads/2024/01/20210924_TD1008_v3.13.pdf)
  — Evidence: primary technical document located.
- **P9 (Zing-derived; encode).** Master target from P7+P8: **-14 LUFS
  integrated, true peak ≤ -1 dBTP** — matches YouTube/Spotify behavior
  exactly (no down-normalization surprise, no lost loudness), safe on
  TikTok/IG whose normalization is undocumented (see Not Found). Eval
  harness flags: integrated outside [-18, -10], TP > -1 dBTP.
  — Evidence: derived; inherits P7/P8 confidence.
- **P10 (T3 — honest finding: there is NO canonical ducking number).**
  Music-under-voice practice: everyone ducks, nobody agrees on one figure.
  Named anchor: Rob Byers (broadcast mix engineer; NPR Training / Vox
  Media) mixes dialogue-anchored at -24 LUFS US-broadcast style and
  explicitly balances music "by ear, constantly checked against the
  dialogue" rather than to a meter number. Workflow guidance around
  Premiere's auto-duck clusters at **duck 6–12 dB** (≈ -12 dB typical for
  dialogue-heavy content); production blogs put steady background beds
  anywhere from ~-20 dB relative to full mix down to -30 dB.
  [Byers, Sound Radix](https://www.soundradix.com/articles/mixing-dialogue-in-audio-storytelling/) ·
  [Adobe auto-duck docs](https://helpx.adobe.com/premiere/desktop/add-audio-effects/adjust-volume-and-levels/automatically-duck-audio.html) ·
  [range example](https://www.epidemicsound.com/blog/audio-mixing-for-video/)
  — Evidence: named practitioner + tool-default range; the spread IS the
  finding. Zing: score speech intelligibility over music (voice clearly
  dominant whenever present), default duck depth ~9 dB, don't pretend
  false precision.

### Caption accessibility

- **P11 (T1-R standard + T1 platform).** WCAG 2.1: captions for prerecorded
  audio are **Level A** (SC 1.2.2 — the baseline accessibility bar), and
  text contrast **4.5:1** minimum (3:1 for large text) is Level AA (SC
  1.4.3) — applies to burned-in caption text over video; boxed/outlined
  caption styles exist to guarantee it. Platform side: TikTok ships
  auto-captions (official 2021 accessibility launch, creator-editable) —
  captioning is a platform-endorsed default, not an optional flourish; IG
  and YouTube auto-caption too.
  [WCAG SC 1.2.2](https://www.w3.org/WAI/WCAG21/Understanding/captions-prerecorded.html) ·
  [WCAG SC 1.4.3](https://www.w3.org/WAI/WCAG21/Understanding/contrast-minimum.html) ·
  [TikTok newsroom](https://newsroom.tiktok.com/en-us/introducing-auto-captions)
  — Evidence: W3C normative text + platform's own announcement. Zing
  renderer: caption text must clear 4.5:1 against sampled background (use
  a backing box/stroke), stay inside P6 safe box, respect E9 speed caps.

**Zing measures:** safe-box violations (P6), integrated LUFS + true peak
(P9), voice-over-music dominance (P10), caption contrast ratio + cps (P11,
E9). All are pure numbers — renderer and eval harness can enforce every one.

## Pillar A — Anti-slop (continued; A3's refuted vendor claim now replaced with real data)

- **A4 (T1-R, the honest replacement for refuted A3).** Humans CANNOT
  reliably detect AI-generated media. Meta-analysis of 56 papers /
  86,155 participants (Diel et al., Computers in Human Behavior Reports,
  2024): overall detection accuracy **55.54%** (95% CI 48.87–62.10 —
  crosses the coin-flip line); by modality: audio 62.08%, **video 57.31%**,
  images 53.16%, text 52.00%; training/feedback interventions lift it only
  to ~65%. Independent confirmation: 1,276-participant study (CACM 2025)
  found mean performance "close to a chance level performance of 50%",
  and prior knowledge about synthetic media did NOT improve accuracy.
  [Diel et al. 2024](https://www.sciencedirect.com/science/article/pii/S2451958824001714) ·
  [CACM coin-toss study](https://arxiv.org/abs/2403.16760)
  — Evidence: peer-reviewed meta-analysis + independent large-N study,
  primary sources located. The Animoto "83% can spot AI video" claim (A3)
  is not just unverified — the peer-reviewed direction is the opposite.
- **A5 (T1-R).** Video is the modality where HUMANS still beat machines:
  Groh et al. (PNAS 2022) — ordinary crowds matched the leading DFDC
  detection model on deepfake videos; Cahill/Pehlivanoglu/Zhu/Ebner
  (Cognitive Research: Principles & Implications, Jan 2026) — humans
  ~two-thirds correct on deepfake video while detection algorithms
  performed at chance on video (machines hit 97% on still images, where
  humans are at chance). Detection skill correlates with analytical
  thinking; even "good" human video detection is far below reliability.
  [Groh PNAS 2022](https://www.pnas.org/doi/10.1073/pnas.2110013119) ·
  [UF study writeup](https://news.ufl.edu/2026/02/deepfake-detection/)
  — Evidence: two peer-reviewed studies; PNAS page blocked robots so exact
  percentages quoted from the 2026 study's coverage — flagged.
- **A6 (T1-R systematic review, qualitative).** Somoray et al. (Human
  Behavior and Emerging Technologies, 2025; 40 studies): human deepfake
  detection is "inconsistent and often insufficient for practical
  reliance." Converges with A4.
  [Somoray 2025](https://onlinelibrary.wiley.com/doi/10.1155/hbe2/1833228)
  — Evidence: abstract-level verification only (full text 403).
- **A7 (finding-by-absence — design-relevant).** ALL located perception
  research is deepfake/detection-framed. **No peer-reviewed study was found
  on whether audiences penalize (enjoy less, share less, trust less)
  short-form content they merely SUSPECT is AI-generated**, nor on
  engagement effects of text-to-video content in real feeds. Implication
  for Zing: the anti-slop line cannot be justified by "viewers can tell" —
  they can't (A4). It stands on platform policy (A1/A2: mass-production
  penalties) and on quality signals that correlate with completion (C1).
  That is exactly the framework's existing thesis; now correctly grounded.

## Refuted / not found this round

- **"YouTube's official -14 LUFS standard" — overstated everywhere.** No
  YouTube help page publishes any LUFS target; dozens of blogs call -14
  "official." Behavior is real (measured, down-only) but tier is
  T3-measured, not T1. Do not cite it as platform documentation.
- **TikTok / Instagram loudness normalization targets — not documented.**
  No official statement found for either; secondary claims conflict (-14
  vs -16 LUFS). Unresolved; P9's -14/-1dBTP master is safe under any of
  the claimed behaviors. Empirically measurable (see Deeper Threads).
- **TikTok exact safe-zone pixels on a live official page — not found.**
  Official spec confirms only downloadable per-format files + the
  caption-length dependency. The 130/484/44/140 consensus is T3.
- **Meta 14%/35%/6% verbatim — verification blocked** by the Business Help
  Center login wall. T2 until fetched logged-in.
- **YouTube Shorts official safe-zone numbers — do not exist** in Google
  Ads/YouTube help (spec page fetched and checked). Community envelope only.
- **Karaoke-caption retention uplift — vendor claims only.** No independent
  or academic data located; all figures trace to caption-tool marketing.
  Same failure mode as the refuted Animoto claim — do not cite.
- **Canonical music-ducking number — does not exist.** Named practitioners
  explicitly mix by ear against dialogue; only ranges are defensible.
- **Short-form average-shot-length norms — no verified data.** Film ASL
  research (E8) stops at feature film; no peer-reviewed shot-length study
  of TikTok/Reels/Shorts content was found.
- **Groh PNAS 2022 exact accuracy figures — not verbatim-verified** (403);
  cited qualitatively via the 2026 study's press coverage.
- **Netflix reading speed "17 cps adult" claims** (seen in several subtitle
  blogs) — contradicted by the live Netflix English-USA guide: 20 cps
  adult / 17 children. Language-specific guides differ; cite per-language.

## Deeper Threads (R-3 candidates)

1. **Upgrade P3/P4 to T1:** download TikTok's official safe-zone .zips from
   the in-feed spec page (needs ads login) and fetch the Meta help article
   in a logged-in browser session; diff against the consensus pixels.
2. **Measure platform loudness empirically:** upload calibrated test-tone +
   speech clips to TikTok/IG/YT via a burner account, re-download, measure
   applied gain. Turns the biggest Not-Found into owned T1-grade data the
   eval harness can cite. (~1 day of work, high leverage.)
3. **Murch physical-copy check:** confirm pp.17–20 weights against the 2nd
   edition (2001) — closes the last gap on E5/E6.
4. **Short-form ASL corpus:** Zing's own Breakdown already extracts shot
   boundaries — compute ASL/variance distributions per genre from studied
   exemplars and publish our own norms (nobody else has this).
5. **Subtitle cognition literature:** d'Ydewalle's eye-tracking work
   (subtitle reading is automatic) and BBC R&D dynamic-subtitle studies —
   would give word-timed captions (E10) a real evidence base or a real
   refutation.
6. **AI-labeling effects:** platforms now auto-label AI content; find
   research on how the LABEL (not the content) shifts trust/engagement —
   the A7 gap's nearest measurable neighbor.
7. **Long-form delivery specs** if Zing ever renders >10min: Netflix
   dialogue-gated -27 LUFS delivery spec, EBU R128 S1/S2.

**Recheck-before-launch:** safe zones move with UI redesigns (Meta unified
its 9:16 zones as recently as 2026-03); loudness behavior changes silently.
Re-verify P3–P7 before hardcoding anything user-visible.
