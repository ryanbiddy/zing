# Transitions Taxonomy & Sound-Mix Norms (R3-A, v0.1, 2026-07-18)

Fills the R3-A agenda: the full transition taxonomy across CapCut / Premiere /
DaVinci / Final Cut / TikTok-native editing with **detectability signatures**
(feeds the S2+ transition classifier), and music-mix norms by segment type
(talking-head / action-no-speech / mixed) with practitioner numbers. Criterion
IDs continue the parent scheme (Pillar E picks up at **E11**, Pillar P at
**P12**; E5–E10 and P3–P11 are in `EDITING-CRAFT-AND-SPECS.md` and are
extended, not repeated — loudness targets live in P7–P9, the "no canonical
ducking number" finding in P10). Tiers as in TASTE-FRAMEWORK.md (T1 / T2 / T3
/ T4) plus the R-2 extension **T1-R** (peer-reviewed / standards-body primary
source) and, used here for tool documentation, **T1-tool** (the tool's own
live docs, verified — authoritative for what the tool does, not for craft).

**Signature vocabulary used below** (defined once in E12): SAD = sum of
absolute frame differences; HD = histogram distance; ECR = edge change ratio;
flow = dense optical flow (per-pixel magnitude + angle); onset/beat = audio
spectral-flux novelty and beat grid.

---

## Pillar E — Transitions (continued; E1–E10 in prior docs)

### The governing norms

- **E11 (T3, convergent).** The cut is the default; everything else is
  punctuation. Multiple independent editing guides converge on plain cuts
  carrying ~90%+ of professional transitions, and on preset/flashy transition
  overuse as THE amateur marker. Named voice: Alex Cooke (Fstoppers, 2026) —
  "A transition signals change; use one on every cut and the viewer's brain
  never settles into the story," and "a 1-second cross dissolve or a default
  audio fade isn't a solution, it's a starting point that most editors never
  question." Coheres with E2 (top-tier editing hides its cuts) and E5–E6
  (Murch: the cut serves emotion/story first). The "90%" figure itself is
  folklore — repeated everywhere, measured nowhere (see Not Found; Zing can
  measure it, see Deeper Threads).
  [Fstoppers (Cooke)](https://fstoppers.com/education/7-premiere-pro-habits-are-making-your-edits-look-amateur-902662) ·
  [convergent example](https://activids.com/common-video-editing-mistakes/)
  — Evidence: one named practitioner quoted verbatim + multiple independent
  guides agreeing; consistent with verified E2/E5. The claim is directional
  (cuts dominate), not the unmeasured percentage.
- **E12 (T1-tool + T1-R + T3 — the detection primitives).** What a classifier
  can actually see, per the shot-boundary-detection (SBD) field:
  **(a) Frame metrics:** SAD ("compared pixel by pixel, summing up the
  absolute values of the differences" — reliable on hard cuts, false-positives
  on "fast movements of the camera, explosions or the simple switching on of
  a light"); histogram distance (robust to small motion, misses some cuts);
  ECR ("transforms both frames to edge pictures", among "the best performing"
  classic scores). Consensus: "most algorithms achieve good results with hard
  cuts, many fail with recognizing soft cuts." TRECVid (2001–2007, 57
  algorithms) topped out around F≈0.897.
  **(b) Tool tier:** PySceneDetect's live docs give working detectors with
  defaults — ContentDetector (HSV frame-difference, threshold 27.0, "detects
  fast cuts"), ThresholdDetector (average pixel intensity vs threshold 12,
  "slow fades" in/out of black), AdaptiveDetector (rolling-average two-pass,
  threshold 3.0, "can improve handling of fast motion"), HistogramDetector
  (Y-channel YUV, 0.05), HashDetector (perceptual hash, 0.395).
  **(c) Learned SOTA:** TransNet V2 (Souček & Lokoč; ACM MM 2024) — dilated
  3D-CNN emitting per-frame transition probabilities with separate
  single-frame (hard cut) and all-frame (gradual) heads, trained largely on
  synthetically rendered transitions, SOTA on ClipShots/BBC at ~250 fps —
  i.e. cut-vs-gradual is solved-ish; NAMING the transition type is not (gap
  Zing's signature table below addresses).
  **(d) Motion:** dense optical flow (OpenCV Farnebäck) yields per-pixel
  displacement magnitude + angle — "the pattern of apparent motion of image
  objects between two consecutive frames."
  **(e) Audio:** librosa's onset module computes "a spectral flux onset
  strength envelope" with peak-picked onsets (and beat tracking in
  `librosa.beat`) — the audio grid that cuts do or don't land on.
  [Wikipedia SBD overview](https://en.wikipedia.org/wiki/Shot_transition_detection) ·
  [PySceneDetect detectors](https://www.scenedetect.com/docs/latest/api/detectors.html) ·
  [TransNet V2](https://arxiv.org/abs/2008.04838) ·
  [OpenCV optical flow](https://docs.opencv.org/4.x/d4/dee/tutorial_optical_flow.html) ·
  [librosa onset](https://librosa.org/doc/main/onset.html)
  — Evidence: tool docs fetched and quoted; TransNet V2 paper located;
  Wikipedia used as field summary (its named claims match the fetched tool
  behavior). Peer-reviewed survey PDFs were not parseable this round (see
  Not Found).

### The taxonomy (E13–E24) — per entry: aliases · what it is · pro vs amateur · detectability signature

- **E13 (T3). Hard cut** — aliases: cut, straight cut; variants smash cut
  (abrupt tonal/loudness contrast), cutaway, cut-in/insert (wide→detail).
  One shot replaces the next "without any effect" (StudioBinder). PRO: the
  invisible workhorse — motivated by emotion/story per E5, placed at the
  viewer-blink point per E7. AMATEUR: cutting "when clips end rather than
  when energy shifts" (Cooke), metronome regularity (E8: natural attention is
  1/f, not constant). SIGNATURE: single-frame SAD/HD spike with clean
  content on both sides; ContentDetector ≥27 HSV delta at one frame;
  TransNetV2 single-frame head fires. Smash cut adds a coincident audio
  discontinuity (RMS/onset jump at the same frame). Cut-in keeps histogram
  roughly similar (same scene) while SAD spikes — histogram-vs-SAD
  disagreement is the "same scene, new framing" tell.
  [StudioBinder taxonomy](https://www.studiobinder.com/blog/types-of-editing-transitions-in-film/)
  — Evidence: definitions from fetched guide; craft judgments cross-ref E5–E8.
- **E14 (T3). J-cut / L-cut** — aliases: split edit, audio lead (J) /
  audio trail (L); umbrella: sound bridge. J: next scene's audio starts
  before its picture; L: outgoing audio continues over the new picture
  (timeline shapes give the names — StudioBinder). PRO: the default grammar
  for conversation and scene hand-offs; smooths what would otherwise read as
  an abrupt cut; core of E3's vlog grammar. AMATEUR: absence — hard-cutting
  audio and video at the same frame everywhere is a leading "edited by a
  template/AI tool" tell (every boundary perfectly aligned). SIGNATURE:
  **temporal offset between the visual boundary and the audio scene
  boundary** — visual cut frame (E13 signature) vs audio novelty/onset event
  or speech-source change; offset 0 everywhere = suspicious alignment;
  offsets of roughly 0.2–2 s = split-edit craft. Measurable with SBD
  timestamps × librosa onset envelope (+ VAD/speaker change).
  [StudioBinder](https://www.studiobinder.com/blog/types-of-editing-transitions-in-film/) ·
  [librosa onset](https://librosa.org/doc/main/onset.html)
  — Evidence: definition sourced; the alignment-tell is Zing-derived logic
  from the definition (flagged as inference, not a sourced stat).
- **E15 (T3). Jump cut** — aliases: jump, punch-through; concealer: Premiere
  **Morph Cut**. Same framing, discontinuous subject/time ("can't help but
  call attention to themselves" — StudioBinder; Godard canon). PRO:
  deliberate time compression in vlogs/talking-head (E3 Neistat cut-offs);
  montage rhythm. AMATEUR: unintentional jump cuts from deleting breaths
  without a plan; or hiding every one behind Morph Cut, whose
  frame-interpolation produces smeared/warped in-between frames when it
  fails (widely documented in tutorials; Adobe positions it "to polish
  interviews by smoothing out jump cuts between sound bites"). SIGNATURE:
  moderate SAD spike with **high global feature similarity** (same scene:
  histogram nearly unchanged, matched keypoints persist but displaced) —
  SAD-up + HD-flat is the jump-cut fingerprint. Morph Cut leaves 2–10
  interpolated frames: anomalously smooth flow bridging the jump + local
  warping artifacts (inconsistent flow around face/edges).
  [StudioBinder](https://www.studiobinder.com/blog/types-of-editing-transitions-in-film/) ·
  [Adobe Morph Cut page (title/desc verified via search)](https://helpx.adobe.com/premiere/desktop/add-video-effects/apply-video-transitions/apply-morph-cut-to-smoothen-jump-cuts.html)
  — Evidence: taxonomy sourced; Adobe page itself timed out this round —
  purpose quoted from its indexed description (see Not Found).
- **E16 (T3). Zoom punch / punch-in** — aliases: punch-in, zoom cut, crash
  zoom (in-camera), CapCut "Pull in/Zoom" presets. Instant or 2–8-frame
  scale change on the same framing, often on a beat or emphasis word. PRO:
  emphasis and rhythm in talking-head/commentary without B-roll; a
  digital-native descendant of the cut-in (StudioBinder). AMATEUR: punching
  on every sentence (loses meaning), or scale changes so small (<10%) they
  read as a mistake rather than a choice. SIGNATURE: **radially divergent
  flow field centered near frame center** (all vectors point outward for
  punch-in, inward for punch-out); instant version = E15-like SAD blip whose
  keypoint matches solve to a similarity transform with scale ≠ 1; animated
  version spreads the same scale ramp over consecutive frames. Distinguish
  from dolly/physical zoom by duration and co-occurrence with a cut
  boundary.
  [StudioBinder (cut-in)](https://www.studiobinder.com/blog/types-of-editing-transitions-in-film/) ·
  [CapCut trending styles](https://www.capcut.com/help/capcut-transitions)
  — Evidence: craft description convergent across guides; signature is
  Zing-derived from flow geometry (flagged).
- **E17 (T3). Dissolve family** — aliases: cross dissolve, crossfade, mix;
  variants film dissolve, dip-to-black/white (= fade out/in), **wash** (fade
  through any solid color), ripple dissolve (dated flashback marker, "mostly
  gone out of style"). Gradual blend, "typically ... 24–48 frames (~1–2
  seconds)" (StudioBinder). PRO: passage of time, act boundaries, softness —
  a MEANING, not a garnish; fades close acts ("audiences may think story
  ends"). AMATEUR: the default-transition glue — Cooke's "1-second cross
  dissolve ... isn't a solution"; dissolving between two shots of the same
  scene to hide a bad cut is the classic tell. SIGNATURE: by construction a
  dissolve renders I_t = (1−α)·A + α·B, so per-frame SAD stays LOW while
  cumulative drift is large over ~24–48 frames; frame intensity variance
  dips toward the middle when A,B are uncorrelated (property of averaging);
  ECR shows old edges exiting while new edges enter across many frames.
  Fades: ThresholdDetector's exact target — mean intensity ramps to/from
  black (or a wash color: ramps toward a single hue with collapsing
  variance). TransNetV2's all-frame head fires across the span.
  [StudioBinder](https://www.studiobinder.com/blog/types-of-editing-transitions-in-film/) ·
  [PySceneDetect ThresholdDetector](https://www.scenedetect.com/docs/latest/api/detectors.html) ·
  [Fstoppers (Cooke)](https://fstoppers.com/education/7-premiere-pro-habits-are-making-your-edits-look-amateur-902662)
  — Evidence: duration + variants sourced; alpha-blend signature is
  arithmetic from the transition's definition; the classic "variance
  parabola" literature claim could not be verbatim-verified (see Not Found).
- **E18 (T3). Wipe family** — aliases: directional wipe (up/down/left/
  right), iris wipe, clock wipe, shape/heart/matrix wipe, barn door; plus
  **natural/invisible wipe** (a real object crosses and covers the cut —
  bridges to E21). One shot spatially replaces another along a moving
  boundary (StudioBinder; Star Wars is the canonical stylized user). PRO:
  only as deliberate style/homage or UI-like sectioning; the natural wipe is
  the respectable modern form. AMATEUR: geometric preset wipes (heart/clock/
  star) are the strongest single "template" marker in 2020s grammar — E11's
  overuse warning applies doubled. SIGNATURE: a **spatial frontier** — at
  each transition frame the picture is old shot on one side, new shot on the
  other, with the boundary sweeping monotonically; per-region SAD lights up
  only along/behind the moving edge (block-wise frame difference shows an
  ordered spatial progression rather than global change); total transition
  4–20 frames. Classic SBD treats wipes as their own gradual class for
  exactly this reason.
  [StudioBinder](https://www.studiobinder.com/blog/types-of-editing-transitions-in-film/) ·
  [Wikipedia SBD](https://en.wikipedia.org/wiki/Shot_transition_detection)
  — Evidence: taxonomy + spatial-effect classification sourced; block-wise
  detection framing is standard SBD practice per E12 sources.
- **E19 (T3). Whip pan** — aliases: whip, swish pan, whip transition. Camera
  (or post-move) whips so fast the frame becomes directional motion blur;
  the cut hides inside the blur ("whip-pan hiding cut in blur" —
  StudioBinder's invisible-cut technique; also its own energy/location-change
  device). PRO: energy, cause→effect, location jumps; the signature move of
  travel-vlog grammar; requires matched whip direction/speed on both sides
  to read as one move. AMATEUR: mismatched whip directions, or the CapCut
  preset version (post-only spin/slide) pasted between static tripod shots —
  motion that the camera never made reads as sticker, not movement.
  SIGNATURE: 3–10 frames of **near-uniform high-magnitude flow in one
  dominant direction** + edge-energy collapse (motion blur kills high
  frequencies) with a hard cut buried mid-blur; real whips show handheld
  jitter and exposure consistency, preset whips show perfectly linear flow
  ramps and often wrap-around/duplicated edge pixels.
  [StudioBinder](https://www.studiobinder.com/blog/types-of-editing-transitions-in-film/) ·
  [OpenCV flow](https://docs.opencv.org/4.x/d4/dee/tutorial_optical_flow.html)
  — Evidence: craft sourced; real-vs-preset discrimination is Zing-derived
  (flagged) — calibrate on exemplars (Deeper Threads).
- **E20 (T3). Match cut** — subtypes (StudioBinder): graphic match (visual
  composition matches across the cut), match on action (movement continues),
  sound bridge (audio matches across scenes). PRO: the prestige transition —
  compresses meaning, rewards attention; scarce by nature (one or two per
  video). AMATEUR: rare enough that failure mode is absence, not overuse;
  forced "match" with nothing actually matching reads as random cut.
  SIGNATURE: a hard cut (E13) where **structural similarity is anomalously
  high across the boundary** — matched composition (SSIM/keypoint geometry
  above cut-population baseline) or continued motion vector direction across
  the cut (match on action), or audio continuity across a visual boundary
  (sound bridge = an E14 measurement special case). This is a
  score-the-exception classifier: find cuts that are "too similar."
  [StudioBinder](https://www.studiobinder.com/blog/types-of-editing-transitions-in-film/)
  — Evidence: subtypes sourced; detection framing Zing-derived (flagged).
- **E21 (T3). Invisible / masked cut** — aliases: mask transition, seamless
  cut, "oner" stitch; CapCut "Masks"/before-after masking presets. Hide the
  cut behind an occluder: frame passes a single-color object/wall/body, cut
  inside the covered frames (Birdman, Rope, 1917 canon — StudioBinder).
  TikTok's hand-cover transition (E24) is this technique folk-form. PRO:
  continuity illusion, transformation reveals; premium craft when the
  occluder is motivated. AMATEUR: obvious luma-mask edges from preset masks;
  occluder moves at a different speed than the "camera." SIGNATURE: 1–5
  frames of **low-entropy / single-dominant-color, low-texture frames**
  (histogram collapses to few bins) sandwiched between two different scenes
  — i.e. SBD sees cut→black-ish/flat frames→cut in quick succession; flow
  shows a large foreground object sweeping through immediately before
  content changes. The dark/flat-frame sandwich is exactly the pattern
  cut-detectors mis-handle (E12's flash/darkness false-positive class,
  inverted into a feature).
  [StudioBinder](https://www.studiobinder.com/blog/types-of-editing-transitions-in-film/) ·
  [PySceneDetect](https://www.scenedetect.com/docs/latest/api/detectors.html)
  — Evidence: technique + film canon sourced; signature derived from
  detector behavior on flat frames (flagged).
- **E22 (T3 craft + T2 vendor). Speed ramp / velocity edit** — aliases: time
  remap, ramp, velocity (CapCut's #1 trending style: "combine slow motion
  and sudden speed changes to create dramatic, beat-synced effects").
  Mechanics per Frame.io (Chris Salters): keyframed time-remapping — speed
  band dragged per-section, duration re-flows. PRO: beat-locked energy in
  action/sports/travel; the ramp lands ON a musical hit; slow section
  showcases the money frame. AMATEUR: ramping footage shot at delivery
  frame rate (stutter or fake frame-blend mush instead of true slow-mo);
  ramps not anchored to any audio event. SIGNATURE: **optical-flow
  magnitude per output frame ramps smoothly up/down while scene content is
  continuous** (no boundary) — motion speed changes without a cut;
  true-slow-mo sections show clean flow, fake ones show interpolation
  artifacts (ghosting = double-exposure edges) or duplicated frames
  (zero-flow frames at regular intervals); ramp apex/valley typically
  coincides with a librosa beat/onset. Audio corollary: music continues
  un-retimed while visual motion rate changes.
  [CapCut trending (vendor)](https://www.capcut.com/help/capcut-transitions) ·
  [Frame.io (Salters)](https://blog.frame.io/2023/03/29/insider-tips-premiere-pro-adjust-time-rate-stretch-ramp-speed/) ·
  [librosa onset](https://librosa.org/doc/main/onset.html)
  — Evidence: vendor claim + named practitioner mechanics; artifact
  signatures are standard interpolation forensics (Zing-derived, flagged).
- **E23 (T2 vendor + T3). Glitch / flash / shake preset family** — aliases:
  glitch, RGB split, chromatic aberration split, flicker, luma flash, shake,
  distortion/zoom-blur presets ("Glitch & Digital Distortion — RGB split and
  flicker effects" — CapCut trending). PRO: sparingly, as genre marker
  (gaming, hype edits, horror stingers) and beat-locked; one per section,
  not per cut. AMATEUR: the single most template-flagged family after
  geometric wipes — E11 overuse rule at maximum; A1's "template-driven"
  penalty adjacency. SIGNATURE: 1–4 frame bursts of **channel-decorrelated
  content** — R/G/B planes spatially offset (cross-channel correlation
  drops while per-channel content matches), blockiness/high-frequency noise
  injection, or full-frame white/color flash (mean intensity spike —
  detectors' flash false-positive class, again inverted into a feature);
  frequently paired with a broadband noise/riser SFX onset at the same
  timestamp.
  [CapCut trending (vendor)](https://www.capcut.com/help/capcut-transitions) ·
  [Wikipedia SBD (flash false-positives)](https://en.wikipedia.org/wiki/Shot_transition_detection)
  — Evidence: family + look from vendor page; RGB-decorrelation test is
  Zing-derived (flagged) but directly implementable.
- **E24 (T3/T4). TikTok-native in-camera transitions** — the platform-folk
  set, executed in-camera + hard cut, not in post: **hand-cover reveal**
  ("place your hand over the camera, change ... then remove the hand to
  reveal the new outfit"), **matched-pose outfit change** ("match the end
  position of one clip with the start position of the next"), **snap/clap
  transition** ("Snap on the downbeat. Cut: on the snap frame, cut to the
  next outfit/scene already mid-snap"), plus in-camera whip (E19). PRO
  (platform-native, not amateur despite zero post sophistication): these ARE
  the craft on TikTok — precision of the match and beat placement is the
  skill; they're invisible-cut (E21) and match-cut (E20) folk equivalents.
  AMATEUR: sloppy pose match (limb jumps), cut off-beat, cover object
  entering at the wrong speed. SIGNATURE: hand-cover = E21's flat-frame
  sandwich with skin-tone dominant frames; matched-pose = E15 jump-cut
  signature where pose keypoints align but clothing/color histograms jump;
  snap = visual cut within ±2 frames of a percussive audio onset (librosa
  transient) with matched hand position across the cut. All are hard cuts
  to SBD — the classification lives in what matches vs jumps across the
  boundary plus audio alignment.
  [wikiHow overview](https://www.wikihow.com/Do-TikTok-Transitions) ·
  [creator tutorials (quotes)](https://www.nemovideo.com/blog/tiktok-transitions-tutorial)
  — Evidence: technique descriptions from how-to/creator sources (T4 each,
  convergent to T3 for the set's existence and mechanics); no official
  TikTok documentation exists (see Not Found).
- **E25 (Zing-derived; classifier plan).** Staged transition classification
  from E12–E24, honest about difficulty: **Stage 1 (S2, now):** cuts-only —
  SBD boundaries + cut density + shot-length variance (already in
  EDITING-CRAFT "Zing measures"), plus the two cheap high-value overlays:
  cut-vs-audio-boundary offset (E14 split-edit craft / suspicious perfect
  alignment) and cut-vs-beat-grid alignment (E24/E22). **Stage 2:** gradual
  vs abrupt via TransNetV2 all-frame head + ThresholdDetector fades =
  detects that a dissolve/fade/wipe happened. **Stage 3:** type
  classification via the signature table (radial flow = zoom, directional
  uniform flow = whip, spatial frontier = wipe, channel decorrelation =
  glitch, flat-frame sandwich = mask/hand-cover, SAD-up/HD-flat = jump
  cut, smooth flow-magnitude ramp = speed ramp) — each is a hand-checkable
  feature detector before any learned model. Judgment layer scores E11:
  preset-family frequency (E18 geometric wipes, E23 glitch bursts) high =
  template smell; split-edit offsets and beat-aligned cuts present = craft.
  — Evidence: derived; inherits E12's tool tiers and the per-entry flags.

**Zing measures (new this round):** transition-type histogram per video,
preset-family rate, cut↔audio-boundary offset distribution, cut↔beat offset
distribution, gradual-transition duration stats. **Zing judges:** was each
non-cut transition MOTIVATED (meaning per E17/E18/E20) or decoration (E11)?

## Pillar P — Sound mix by segment type (continued; P7–P10 hold the targets)

- **P12 (T1; the pro anchor concept).** Dialogue-gated loudness is how the
  top of the industry mixes: Netflix's live spec — "Set average loudness at
  -27 LKFS with a tolerance of ±2 LU, **dialog-gated**"; "Peaks must not
  exceed -2dB True Peak"; "Dialog LRA of 10 LU or less"; program LRA
  (5.1) 4–18 LU; and the craft sentence: "dialogue remains clear and
  intelligible within the mix ... except in cases where a lack of clarity is
  purposefully crafted." The transferable principle for Zing (short-form
  platforms normalize full-program instead, P7): **speech, when present, is
  the anchor everything else is set against** — measure loudness gated to
  speech, then fit music around it. The -27 number itself is long-form
  delivery, NOT a short-form target (P9's -14/-1 dBTP master stands).
  [Netflix Sound Mix Specifications & Best Practices](https://partnerhelp.netflixstudios.com/hc/en-us/articles/360001794307)
  — Evidence: page fetched, quoted verbatim; scope boundary stated.
- **P13 (T3 range; talking-head / speech-dominant segments).** Continuous
  music bed under near-continuous speech sits DEEP: convergent practitioner
  ranges put voice 15–25 dB above the bed (production-library guidance),
  community rule-of-thumb 10–20 dB under the spoken word, with P10's
  steady-bed figures (-20 to -30 dB re: full mix) at the conservative end.
  Vendor-side single number: Epidemic Sound/Ben Hess — dialogue averaging
  around -12 dB with the whole project under -6 dB, music set AFTER dialogue
  ("set the volume of your dialogue and then adjust your music
  accordingly"). Synthesis: **bed ≈ 15–25 dB below concurrent speech;
  deeper than the duck-style range (P14/P15) because it never gets to come
  up.** No canonical single number exists (P10's finding, unchanged).
  [DL-Sounds guidance](https://www.dl-sounds.com/how-to-mix-voice-and-music-in-videos/) ·
  [r/VideoEditing rule-of-thumb](https://www.reddit.com/r/VideoEditing/comments/10h6drk/what_is_the_rule_of_thumb_on_audio_levels_for/) ·
  [Epidemic Sound (Hess)](https://www.epidemicsound.com/blog/how-to-get-the-volume-right-in-your-videos/)
  — Evidence: three independent source classes converge on the range; each
  alone is T4, the convergence is the T3.
- **P14 (T3 + standards inheritance; action / no-speech segments).** When
  there is no speech, music IS the foreground: it runs at the master target
  itself — i.e. the P9 -14 LUFS integrated / ≤ -1 dBTP master applies to the
  music-dominant program, with AES TD1008's -16 LUFS (P8) as the
  distribution floor. There is no "under" to sit; SFX are layered against
  the music, and the loudness meter reads the music. The craft variable is
  DYNAMICS, not level: hype sections ride near the target, breathers drop
  several LU (E8's 1/f attention logic applied to loudness). No published
  per-genre no-speech LUFS norms exist for short-form (see Not Found) — the
  encode is the P9 master plus contrast, not a new number.
  — Evidence: inheritance from P8/P9 (their tiers carry); dynamics-contrast
  framing is practitioner-general (Netflix LRA guidance in P12 is its
  long-form analog).
- **P15 (T3; mixed segments — the duck numbers and time constants).** Where
  speech and music alternate, practice converges on **duck depth 6–15 dB**
  (P10's 6–12 dB Premiere-workflow cluster; third-party Premiere guidance:
  -12 dB "works well for most dialogue-heavy content," -6 to -8 dB for
  already-quiet beds, "-15 dB or more" for prominent beds) and — the new
  finding this round — on TIME CONSTANTS: keyframed fades of **500–800 ms**
  sound natural while "very short fades (under 200 ms) tend to sound abrupt
  and mechanical"; the sidechain version from a named engineer (Larry the O,
  Sound On Sound): ratio ~2:1, "medium fast attack (maybe 15 or 20 ms)," and
  a deliberately slow release — "sometimes as much as 600 or 700 ms ... to
  avoid hearing the gain come back up during short pauses between phrases."
  Also his calibration point: even "1–2 dB of ducking can make [a
  difference] in the clarity of the mix's lead element" — depth is
  perceptible long before it's dramatic. **Asymmetry rule: get out of the
  way fast (tens of ms attack / short down-fade), come back slow (600+ ms
  release / longer up-fade) so the bed doesn't pump in phrase gaps.**
  [Sound On Sound, "Duck Tales" (Larry the O)](https://www.soundonsound.com/techniques/duck-tales) ·
  [Premiere ducking guidance (third-party)](https://store.hollyland.com/en-ca/blogs/creator-hub/use-audio-ducking-in-adobe-premiere-pro) ·
  [Adobe auto-duck docs (P10)](https://helpx.adobe.com/premiere/desktop/add-audio-effects/adjust-volume-and-levels/automatically-duck-audio.html)
  — Evidence: named engineer in a reputable outlet + convergent tool-workflow
  guidance; Adobe's own default values could not be verified this round
  (page timeouts — see Not Found), so tool defaults stay uncited.
- **P16 (T3; mix craft at segment transitions).** How pros move between
  speech-anchored and music-anchored states: (1) **music swells in speech
  gaps** — "slightly raise the music level during pauses in the voiceover"
  (the radio/doc "post" move; P10's Byers mixes exactly this way, by ear
  against dialogue); (2) **audio leads the picture** — segment changes
  arrive as J/L cuts (E14): incoming music/atmos starts under the last line
  of the outgoing segment; (3) **musical grid alignment** — segment
  boundaries land on beats/phrase starts; beat-sync is a first-class
  short-form norm (CapCut trending: transitions "synced with music"; E24
  snap-on-downbeat); (4) **treat audio as structure, not garnish** —
  Cooke's amateur marker #4 ("neglecting audio as a structural element").
  Anti-pattern: music hard-cutting mid-phrase at a visual boundary — the
  audio equivalent of a default cross dissolve.
  [recordmixandmaster (swell)](https://recordmixandmaster.com/2024-05-how-to-mix-voiceovers-and-background-music) ·
  [CapCut trending (vendor)](https://www.capcut.com/help/capcut-transitions) ·
  [Fstoppers (Cooke)](https://fstoppers.com/education/7-premiere-pro-habits-are-making-your-edits-look-amateur-902662) ·
  [Byers via Sound Radix (P10)](https://www.soundradix.com/articles/mixing-dialogue-in-audio-storytelling/)
  — Evidence: each practice individually T3/T4; the four together are the
  documented craft cluster, each item independently sourced.
- **P17 (Zing-derived; encode + measure).** The eval-harness numbers, from
  P9 + P12–P16 (mixed tiers — inherit): **(a) master:** -14 LUFS integrated
  / ≤ -1 dBTP unchanged (P9). **(b) speech-active regions:** speech is the
  anchor; concurrent music short-term level target **9–15 LU below speech**
  for duck-style content, **15–25 LU below** for continuous talking-head
  beds; FLAG music within ~6 LU of concurrent speech (intelligibility risk —
  P12's craft sentence, quantified conservatively). **(c) no-speech
  regions:** music short-term should approach the master (flag if it stays
  >6 LU under program level — dead-air smell), with audible dynamic contrast
  across sections. **(d) transitions:** duck-down ≤ ~200 ms, recovery
  ≥ ~500 ms (P15 asymmetry); flag instant (≤1 frame) music level jumps and
  mid-phrase music hard cuts at segment boundaries; credit beat-aligned
  boundaries (|cut − nearest beat| small) and audio-lead offsets (E14).
  Measurement path: VAD + music/speech source separation → per-stem
  short-term LUFS timelines → duck depth, attack/release, and alignment
  extracted from the music-stem envelope. All thresholds are defaults to
  calibrate against exemplars, not gospel (Deeper Threads 4).
  — Evidence: derived; every input criterion cited above carries its tier.

**Zing measures (new this round):** per-stem short-term LUFS by segment
type, duck depth/attack/release from music-stem envelope, music↔speech gap
(LU) in speech-active regions, boundary↔beat offset, mid-phrase music-cut
flags. **Zing judges:** does the mix change state WITH the content
(speech-anchored ↔ music-anchored) and does music behave like structure
(P16) or wallpaper?

## Refuted / not found this round

- **Adobe's official auto-duck defaults — unverifiable this round.** The
  Premiere help page (P10's citation) timed out on every fetch (WebFetch and
  direct curl); no Adobe page stating default Duck Amount / Sensitivity /
  Fade values was reachable. Third-party starting points (P15) are explicit
  recommendations, NOT confirmed defaults. Do not cite "Premiere defaults
  to X dB" anywhere.
- **A canonical per-segment LUFS table for short-form — does not exist.**
  No platform (TikTok/IG/YT) documents anything about music-vs-speech
  balance; every number in P13–P15 is practitioner-range. Consistent with
  P10's R-2 finding; the spread is still the finding.
- **The "90% of transitions are cuts" statistic — folklore.** Repeated
  across editing guides with no measured corpus behind it anywhere. Use
  directionally (E11), never as a number. Zing can produce the real number
  (Deeper Threads 2).
- **Dissolve "variance parabola" from the SBD literature — not
  verbatim-verified.** The classic reviews were unreachable (MDPI Entropy
  2018 review 403'd; CEUR-WS survey PDF unparseable without poppler). E17's
  signature is re-derived from the alpha-blend definition instead —
  mathematically safe, but the literature citation upgrade is pending.
- **CapCut's full transition-category tree — not on any fetchable official
  page.** The official help page lists eight trending STYLES (T2, used in
  E22/E23); the in-app category taxonomy (Basic/Camera/Effect/Masks/…) is
  only documented by third-party guides. In-app verification would make it
  T1-tool.
- **TikTok official documentation of native transitions — none exists.**
  E24 rests on creator/how-to sources; the platform documents hooks and
  specs, not transition technique.
- **DaVinci Fairlight / Final Cut ducking defaults — not sourced this
  round.** No primary documentation fetched; deliberately omitted rather
  than repeated from blogs. (Both tools' transition GALLERIES also
  uncited — the taxonomy above is tool-independent by design.)
- **Groh-style perception data for transitions — nothing found** on whether
  audiences consciously register preset transitions as amateur (parallel to
  A7's gap). E11 rests on practitioner consensus, not audience studies.

## Deeper Threads (R-4+ candidates)

1. **Transition gold set:** hand-label ~200 transitions across studied
   exemplars into E13–E24 classes; validate each signature detector's
   precision before any of them ships in S2+ scoring. TransNetV2 gives
   boundaries; the type layer is ours alone (nobody publishes this).
2. **Measure the cut-share folklore:** run the Stage-1 classifier over the
   exemplar corpus → publish real per-genre transition-type distributions
   (turns E11's "~90%" folklore into owned data; same move as the R-2
   loudness thread).
3. **Beat-alignment tolerance:** shot boundaries vs librosa beat grid over
   trending short-form — establish the empirical window (±1 frame? ±50 ms?)
   that reads "on beat" (calibrates E25/P17's alignment credit).
4. **Per-stem mix corpus:** source-separate 20 pro exemplars per genre →
   per-stem LUFS timelines → replace P13/P15/P17 practitioner ranges with
   measured genre norms (talking-head vs hype-edit will differ; nobody has
   published this either).
5. **Adobe/Resolve defaults from live installs:** open Essential Sound and
   Fairlight on a real machine, record actual defaults — upgrades the P15
   tool anchors to T1-tool in an hour.
6. **Whip/velocity exemplar calibration:** extract flow signatures from
   known in-camera whips (travel-vlog canon) vs CapCut preset whips —
   validates E19's real-vs-preset discriminator before it judges anyone.
7. **SBD literature verbatim pass:** obtain the Entropy 2018 review or
   Lienhart/Hanjalic surveys through a non-blocked route; upgrade E17's
   derived dissolve signature to cited.

**Recheck-before-launch:** CapCut trending styles are a living marketing
page (T2, dated 2026); Netflix spec is versioned (v1.6 now — recheck on
use); preset-transition fashion moves fast — E23's "template smell" list
should be re-derived from current trending content each round, not frozen.
