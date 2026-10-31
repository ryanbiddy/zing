# Motion graphics

A Composition v2 plan can carry templated motion graphics: a title card, a lower
third, a callout and a progress bar. Each one is a `graphics` record with a
template, an output-time interval, a normalized box, text lines, a pinned font
and colors. `zing render` draws them with the same local HyperFrames sidecar
that renders [v2 captions](HYPERFRAMES-V2.md), so a plan with graphics needs
that [sidecar setup](HYPERFRAMES-SIDECAR.md). Nothing is downloaded at render
time.

```text
zing render composition.json -o draft.mp4 --keep-work render-work
```

All graphics and HyperFrames captions render into one transparent ProRes 4444
layer, composited after footage LUTs and transitions and before ASS captions.
Graphics sit beneath HyperFrames captions, and ASS captions stay on top.

## Templates

| Template | Text lines | Motion | Colors |
|---|---|---|---|
| `title-card` | 1-2 | The block rises, scales and fades in; an accent underline grows; everything fades out at the end. | Text `color`, underline `accent`. |
| `lower-third` | 1-2 | A dark plate with an accent bar wipes in from the left, the text slides in after it, and the plate fades out. | Text `color`, bar `accent`. |
| `callout` | 1 | A tilted pill pops in with a small overshoot and shrinks out. | Text `color` on an `accent` pill. |
| `progress-bar` | 0 | The `accent` fill sweeps linearly from left to right across the whole interval. | Track is `color` at 30% opacity. |

The first line uses `style.size` output pixels; a second line is half that
size. Each text entry is one unwrapped line. Entrances take
`min(0.35 s, duration / 4)` and exits `min(0.25 s, duration / 4)`; the progress
bar has neither. Motion is finite CSS animation that HyperFrames seeks
frame by frame, so renders are deterministic.

## Record

| CompositionGraphic field | Contract |
|---|---|
| `id` | Nonempty, unique among graphics. |
| `template` | `title-card`, `lower-third`, `callout` or `progress-bar`. |
| `start`, `end` | Output seconds, `0 <= start < end`, ending within the cut. |
| `box` | Normalized top-left `Box` (`x`, `y`, `width`, `height`, `version: 1`). The template centers in it; a lower third aligns left. |
| `text` | Ordered lines, each 1-120 characters without control characters. Default `[]`. |
| `font` | `FontAsset` (TTF or OTF) when there is text; `null` for a progress bar. |
| `style` | `GraphicStyle`: `size` (1-512 px, required with text and absent without), `color` and `accent` (`#RRGGBB`, defaults `#FFFFFF` and `#FF3D00`), `version: 1`. |
| `version` | `1`. |

An empty `graphics` array is omitted from saved JSON, so existing plans keep
their exact spelling. A plan with graphics cannot be lowered to EDL v1.

```json
{
  "graphics": [
    {
      "id": "hook", "template": "title-card", "start": 0, "end": 2.4,
      "box": {"x": 0.06, "y": 0.1, "width": 0.88, "height": 0.16, "version": 1},
      "text": ["3 MISTAKES", "every new founder makes"],
      "font": {"path": "fonts/Anton-Regular.ttf", "sha256": "a4ba3a92350ebb031da0cb47630ac49eb265082ca1bc0450442f4a83ab947cab", "license": "OFL-1.1", "version": 1},
      "style": {"size": 140, "color": "#FFFFFF", "accent": "#FF3D00", "version": 1},
      "version": 1
    },
    {
      "id": "progress", "template": "progress-bar", "start": 0, "end": 6,
      "box": {"x": 0, "y": 0.992, "width": 1, "height": 0.008, "version": 1},
      "text": [], "font": null,
      "style": {"color": "#FFFFFF", "accent": "#FF3D00", "version": 1},
      "version": 1
    }
  ]
}
```

Zing bundles Anton, IBM Plex Sans and the ZingCaption faces under
`src/myzing/_data/fonts/`. As with caption presets, a missing font path whose
SHA-256 matches a bundled face resolves to that face, with a warning.

## Fit check

Before rendering, Zing measures every line in the pinned face and adds the
template's padding, bars and gaps. Text that would overflow its box fails with
the size that fits. At 1080×1920, the example title card above at size 200 fails:

```text
Graphic hook: title-card needs 1043x406px at size 200, but its box is 950x307px;
set style.size to 151 or less, or enlarge the box
```

Missing glyphs fail the same way. Zing never shrinks, wraps or clips text to
make it fit.

## Other shapes

`zing render --aspect` deliveries keep each graphic's normalized box and scale
`style.size` with the short side, as captions do. A box that suits 9:16 can
be too short in 16:9; that shape then fails the fit check by name. Give such a
plan per-shape boxes, or a box tall enough for every shape you deliver.

## Limits

- Four templates. There is no keyframed custom motion, image or logo layer,
  count-up number or per-word timing in a graphic. Use a HyperFrames caption for
  word-timed text.
- Boxes are static; graphics do not follow faces or avoid captions
  automatically. Place them clear of the [face-aware caption layout](FACE-LAYOUT.md).
- Fit checks use font advance widths without kerning, so measured lines are
  slightly conservative.
- The standalone sidecar (`node render.mjs plan.json out.mov`) accepts the same
  `graphics` array but has no fit check; `zing render` and
  `myzing.render.hyperframes_v2.captions_to_plan(..., graphics=...)` do.

## Adding a template

A template is CSS in `tools/hyperframes-sidecar/templates.mjs`, its line count in
`GRAPHIC_LINES` (both `plan.mjs` and `myzing.composition.models`), and its
padding in `GRAPHIC_CHROME` (`myzing.render.hyperframes_v2`). Keep motion to
one full-length CSS animation per part, timed by percentages on the graphic's
local clock, with no script, timer or random value.
