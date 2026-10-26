With `caption_mode=reference`, captions use the reference's median words per
event and its interquartile word-count band. Groups follow source word timings,
case rate, position and measured alignment. Persistent title lines are separated
from changing caption lines before those measurements are calculated.

Measured caption ink supplies color and outline when available. Missing values
are disclosed once per plan as **Estimated**, with the affected caption count: white text, a black legibility outline,
centered alignment, and an em size of the short side divided by 18 (at least
24px). Reference mode adds a plate only when one was measured, or when explicitly
requested in `caption_options`. The default active-word color matches the text.
Exact font identity and size remain estimates.
Stroke samples wider than 20% of measured glyph height are excluded as possible
background contamination; one plan-level note gives the excluded sample count
and affected caption count. Structured reference evidence retains the measurements.

Every draft uses one font size. Reference captions use a fixed glyph sample to
estimate em size, so the letters in each phrase do not change the font size.
If a group is too wide, fitting splits it into fewer words before reducing size;
word-count band deviations are disclosed. Numeric display units remain joined.
Only a word that cannot fit alone lowers the size for the entire draft. The
readability floor still applies, and a word that cannot fit at that floor stops
reference rendering with a remedy.

Punch and Box regroup onto one line; Clean can use two lines. Presets choose the
draft size from the widest word before grouping shots, and can split an oversized
word at the floor with timing provenance. Caption rails move to avoid faces and
never shrink individual cues. Existing face-overlap warnings remain visible.
The match report's caption section includes `size_spread_px` (zero for a uniform
draft), measured from planned font sizes including layout scale.

For source shots with measured text-card geometry, `reframe` preserves all
observed text. If the proposed crop cuts it, that shot uses full-source blurfill.
The plan records the decision, sample times and text bounds; aspect conversion
rechecks those bounds. Unsampled text remains unmeasured.

To add an active-word background to timed captions:

```powershell
zing render plan.json --aspect all --caption-mode phone --caption-options '{"highlight_box_color":"#FFD23F","highlight":"#0A0A0A","highlight_box_padding":6,"highlight_box_radius":4,"highlight_box_opacity":1}' -o delivery.mp4
```

The same `--caption-options` JSON works with `zing match` and `zing studio`.
Saved briefs use `caption_options`; Composition v2 stores these fields in each
caption's `style`. Captions need ordered word timings. Render does not transcribe
an existing video or create missing captions.

| Style field | Meaning and default |
|---|---|
| `highlight_box_color` | Active-word plate, `#RRGGBB`; null disables it. |
| `highlight_box_padding` | Pixels on each side of the word's measured ink and outline; 6. |
| `highlight_box_radius` | Corner radius in pixels; 0. Libass draws cubic vector corners, clamped to half the plate size. |
| `highlight_box_opacity` | 0–1; 1 is opaque. |
| `highlight` | Active foreground color; existing default yellow. Choose dark ink for a yellow plate. |
| `before_color`, `after_color` | Foreground before/after each word's interval; null uses `color`. |
| `box_color` | Existing full-phrase opaque plate; independent of the active-word plate. |

The renderer measures each word inside the complete shaped phrase with libass,
including explicit line breaks and the supplied font. It draws the word plate
behind the glyphs and above the phrase plate; word states only recolor glyphs,
so line breaks and glyph positions never change while words highlight. The
plate and active color appear when a word starts and hold through any pause
until the next word starts (the last word holds to the phrase end), so the
plate never blinks off mid-phrase; earlier words take the after color and later
words the before color. Frame quantization
and the existing one-frame minimum still apply. A plan contains one caption per
phrase; the renderer generates the ASS states. No short-event reading warning
is added for those internal states. Existing styles retain their defaults.

Use an opaque plate and contrasting active ink on busy footage. Transparent
plates deliberately allow the background to show through. Padding is part of
layout safety, so a changed style may require `--aspect` to replan its box.
Active-word backgrounds currently require the native ASS backend; HyperFrames
rejects them with a remedy rather than silently discarding them.

The `phone` preference uses short spoken groups and a size floor based on the
visible picture and a 400-pixel-wide phone presentation. A clause splits into
balanced groups of at most four words (five words make 3+2, never 4+1), and a
group shown for less than 0.5 s joins its shorter neighbour while the result
keeps at most six words. Each event is then held for at least 0.5 s and
20 characters/second, using only the silence before the next event; the
renderer still warns about faster events it could not hold. Phone captions
wrap on measured libass ink, so lines are fuller and balanced. For 9:16, font em size
is at least 8% of visible picture width and 7% of output width. A full-width
720×1280 picture therefore needs at least 57.6 px, equivalent to 32 px at a
400-pixel viewing width. Square/landscape use 6.5% of the smaller of picture
width and output height: 46.8 px for a full-width 720×720 picture.

These are em sizes, not glyph ink heights or a promised phrase width. Short
phrases naturally occupy less width. The planner may wrap text but refuses a
phone layout below its floor: shorten the phrase or choose framing with more
caption space. Render, match's caption fit and studio's report use the same
floor, from the narrowest picture shown during the event. Face avoidance still uses sampled detector evidence; inspect
the delivered video at phone size. Reference-mode typography is unchanged.
