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
behind the glyphs and above the phrase plate. Only the active interval has a
word plate; pauses show the before/after foreground states. Frame quantization
and the existing one-frame minimum still apply. A plan contains one caption per
phrase; the renderer generates the ASS states. No short-event reading warning
is added for those internal states. Existing styles retain their defaults.

Use an opaque plate and contrasting active ink on busy footage. Transparent
plates deliberately allow the background to show through. Padding is part of
layout safety, so a changed style may require `--aspect` to replan its box.
Active-word backgrounds currently require the native ASS backend; HyperFrames
rejects them with a remedy rather than silently discarding them.

The `phone` preference uses short spoken groups and a size floor based on the
visible picture and a 400-pixel-wide phone presentation. For 9:16, font em size
is at least 8% of visible picture width and 7% of output width. A full-width
720×1280 picture therefore needs at least 57.6 px, equivalent to 32 px at a
400-pixel viewing width. Square/landscape use 6.5% of the smaller of picture
width and output height: 46.8 px for a full-width 720×720 picture.

These are em sizes, not glyph ink heights or a promised phrase width. Short
phrases naturally occupy less width. The planner may wrap text but refuses a
phone layout below its floor: shorten the phrase or choose framing with more
caption space. Face avoidance still uses sampled detector evidence; inspect
the delivered video at phone size. Reference-mode typography is unchanged.
