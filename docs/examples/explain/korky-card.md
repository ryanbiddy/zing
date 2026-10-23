# Style card: korky.mp4

19.0s, 360 x 640. Measured from the exported video; the original project settings are unknown.

## What a viewer notices

- One continuous vertical 9:16 talking-head shot, 19.0s with no cuts, full frame.
- No on-screen text read in the sampled frames.
- Speech-led audio (talking 77% of the time); music not confirmed.
- Natural color leaning strongly cool (blue); strong contrast.

## Get this look

```sh
# Three drafts in this style from your clips (measures the reference again):
zing match './clips/korky.mp4' --clips ./my-clips --out ./my-edit --answers '{}'
# Already have a Zing project? Plan drafts from this card's recipe:
zing plan drafts ./my-edit --recipe './style-card/style-recipe.json' --out ./my-edit/drafts
# Approximate this color on one of your clips:
zing color match --reference './clips/korky.mp4' --clip ./my-clips/clip1.mp4 --out ./my-look
# Apply that look:
zing color apply --lut ./my-look/look.cube --in ./my-clips/clip1.mp4 --out ./clip1-graded.mp4
```

Replace `./my-clips`, `./my-edit` and `clip1.mp4` with your own folder, project and clip. The reusable StyleRecipe is `./style-card/style-recipe.json`. Drafts approximate the look; they do not copy the original edit.

## Cuts and pacing

One continuous shot: no cuts detected in 19.0s.

Confidence: shot boundaries from scenedetect-0.7 AdaptiveDetector; no detector is ground truth
Not knowable from pixels: the editor's timeline and any cut hidden inside fast motion.

## Transitions

No dissolves, wipes or other transition effects detected.
65 other image changes could not be classified as an edit; motion or lighting can cause these.

Confidence: heuristic; not probability
Not knowable from pixels: which effect, preset or plugin made a transition.

## Captions and on-screen text

No on-screen text was read in the sampled frames.

Confidence: no accepted text tracks; absence unproven
Not knowable from pixels: the original font, shadow settings and word-highlight timing.

## Color look

Strong contrast (L* spread 84); natural color (median chroma 13).
Sampled colors are strongly cool, toward blue (Lab a* +7.0, b* -10.8).

Confidence: 0.60 heuristic score; assumes SDR video; scene objects and lighting count
Not knowable from pixels: the original LUT, preset or skin-specific grade.

## Framing

360 x 640, vertical 9:16.
Full frame used: no letterbox or pillarbox bars in 7 sampled frames.
A face appears in 100% of sampled frames, about 39% of the frame height, its top 19% below the top edge.

Confidence: probed display size (rotation and pixel aspect applied); sampled YuNet boxes; no identity; solid-bar check on sampled frames
Not knowable from pixels: whether a zoom was a punch-in or a camera move, and the app safe-zone intent.

## Audio and music

Speech for about 77% of the clip (voice activity detection).
Sound continues between spoken phrases (room tone, ambience or a music bed); music not confirmed.
No steady beat found.
Loudness -13.5 LUFS integrated; true peak -3.0 dBTP.
Mix level shifts at 5.0s, 10.5s, 17.2s (loudness changes, not identified song sections).

Confidence: music evidence weak; loudness is EBU R128; other audio values are heuristics
Not knowable from pixels: the music level under speech (that needs separate stems) and what the track is.

---

Scores are heuristic evidence, not probabilities. card.json keeps every measurement, sample and limitation.
