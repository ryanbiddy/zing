# Style card: korky.mp4

Shot detector: 0 cuts; 0.0 per minute. Typical shot: 19.00s.
Detector ran; no supported transition signature found.
Text style is unknown.
Contrast 84.1 L*; median chroma 13.2.
360 x 640; aspect 0.562:1.
Speech activity covers 77% of the clip (VAD).

Confidence scores are heuristic evidence, not probabilities. Full samples and gaps: card.json.

## Cuts and pacing

Shot detector: 0 cuts; 0.0 per minute. Typical shot: 19.00s.
Pace: 0-10s 0.0/min (steady); 10-19s 0.0/min (steady).
Shot lengths span 19.00-19.00s.

Confidence: scenedetect-0.7 AdaptiveDetector

Unknown: Shot detection can miss gradual changes and very short shots. No supported beat grid; cuts on beats are unknown.
1 further limitations in card.json.

## Transitions

Detector ran; no supported transition signature found.

Confidence: heuristic; not probability

Unknown: Signatures describe pixels, not the original effect or editor. Whip/flash reconstruction is unsupported. Unclassified change at 0.07-0.47s: continuous motion or missing quiet handles; edit type unknown
64 further limitations in card.json.

## Captions and on-screen text

Text style is unknown.

Confidence: no accepted text tracks; absence unproven

Unknown: Original font, drop shadow and highlight timing/color are unknown. Sparse OCR cannot prove word-by-word switching or distinguish every title from a caption.
3 further limitations in card.json.

## Color look

Contrast 84.1 L*; median chroma 13.2.
Sampled colors lean blue/cool, red (Lab a* +7.0, b* -10.8).

Confidence: 0.60; heuristic; SDR assumption

Unknown: Original LUT/preset and skin-specific treatment are unknown. Scene colors include lighting, objects and text. A clip-specific LUT approximation can be fitted with zing color match.
4 further limitations in card.json.

## Framing

360 x 640; aspect 0.562:1.
Sampled face height 38.9% of frame; top-of-face gap 19.3%.

Confidence: Probed dimensions; sampled face evidence where available.

Unknown: Punch-ins cannot be distinguished reliably from camera/subject movement. Top-of-face gap is not hair/head clearance. Unsampled subjects and app UI safety remain unknown.

## Audio and music

Speech activity covers 77% of the clip (VAD).
Music presence: candidate detected (gap-floor heuristic).
Tempo none; no global beat grid.
Loudness -13.5 LUFS; true peak -3.0 dBTP.
Detected moments: section_change at 5.00s, section_change at 10.50s, section_change at 17.25s.

Confidence: heuristics; loudness is EBU R128

Unknown: Ducking is unknown from a mixed source; separate stems are needed to establish music gain under speech. Music labels can also describe steady voices or machinery.
5 further limitations in card.json.

## Get this look

Reusable StyleRecipe: `style-recipe.json`.
Use local clips you have permission to edit. Match makes a new project; color fits a clip-specific approximation.

```sh
zing match ./clips/korky.mp4 --clips ./clips --out ./project --answers '{}'
zing color match --reference ./clips/korky.mp4 --clip ./clips/input.mp4 --out ./look
zing color apply --lut ./look/look.cube --in ./clips/input.mp4 --out ./graded.mp4
```

The original font, LUT, preset, editor project, hidden source layers and exact caption animation cannot be recovered from this export.
