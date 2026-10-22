# Explain an editing style

To turn a reference into a readable style card:

```sh
zing explain ./clips/reference.mp4 --out ./style-card
zing explain ./clips/reference.mp4 --against ./project/draft-A.mp4 --out ./comparison-card
```

Open `card.md` for the explanation and commands, `card.png` for a single
phone-readable page, or `card.json` for the measured values and coverage.
`style-recipe.json` is the reusable StyleRecipe contract. Evidence files retain
the full study, OCR geometry, audio map and sampled color statistics.

The default output is a new folder under the current project's
`zing-workspace/explain`. If that is inside an input folder, explain chooses a
sibling of the configured workspace or current project. Outputs must be outside
the input video folders; `--out` selects another location. Existing
nonempty output folders are refused. No source media is modified.

Local files and `uoink:<id>` use the existing resolver. A Uoink reference resolves
only that item's verified kept media, with no URL fallback. HTTP(S) URLs need
`--allow-download`. Models always stay local, even when media download is allowed.
`--no-transitions` skips v6. `--json` prints the result paths and six summary lines.

Install FFmpeg/ffprobe and `myzing[study,fonts,color,audio,memes]`, or run
`uv sync --all-extras` in a checkout. Missing OCR, OpenCV, NumPy or ASR models
produce stated unknowns. The PNG needs Pillow from the existing `memes` extra;
without it, the command returns an install hint. Prepare OCR/font assets explicitly
as described in [caption geometry](CAPTION-GEOMETRY.md) and
[font candidates](FONT-CANDIDATES.md). Explain never fetches model weights.

## Reading the evidence

Every section has separate `facts`, `confidence`, `unknowns` and readable `lines`.
Confidence scores are heuristics, not calibrated probabilities. Missing values
are null or absent; they never become zero measurements.

- Pacing uses detected shot boundaries. It gives a shot-length distribution,
  cut rates in ten-second windows (including a duration-normalized final window),
  and nearest supported beats/drops. Alignment means within 80 ms. When v6 finds
  an additional hard cut, the card discloses the disagreement and comparison
  pacing becomes unknown. No detector is treated as ground truth.
- Transitions retain v6 types, times, scores and abstentions. An unknown effect
  stays unknown; flash/whip motion does not become a chosen render effect.
- Text includes accepted OCR tracks and sampled appearances. Visible ink height
  is a percentage of the short side, not font size. Captions, titles, credits and
  uncertain scene text retain the existing text-role evidence. Only
  speech-supported caption tracks enter caption-placement comparisons.
  Low font scores are substitutes; the original font is always unknown.
- Color reports sampled Lab palette, contrast, chroma and a*/b* values, with SDR
  assumptions and coverage. These include objects, lighting and graphics.
  Original LUT, camera settings and skin-specific treatment remain unknown.
- Framing reports aspect and sampled face placement, face height and top-of-face
  gap. That gap is not clearance above the hair. Vertical-safe reserves are Zing
  recommendations, not proof that the source clears every app's UI.
- Audio reports VAD speech share, music candidates, supported tempo, loudness,
  mix energy and detected moments. Mixed audio cannot establish ducking gain.
  Missing tempo does not mean the music has no beat.

The PNG is 800 pixels wide, with text at least 13 pixels high when displayed at
400 pixels. It shows three key frames, a shot strip, sampled text boxes, swatches
and a mix-energy/moment strip. It is a summary: the Markdown and JSON retain
details that cannot fit legibly on the page.

## Compare a draft

`--against` produces a second complete card under `against/` and a per-section
`close`, `differs` or `unknown` comparison in the reference card. Each metric
retains target, observation, tolerance and basis. Close describes only the listed
numbers; it does not certify the edit or establish an original font/LUT match.

Pacing reuses the match report's 10% median-shot envelope. Caption placement
reuses median sampled boxes and an IoU threshold of 0.8. Color reuses the maximum
encoded-luma percentile difference of 0.15. Framing compares aspect within 0.02
and face height within five percentage points; audio compares speech share within
ten percentage points, tempo within 5 BPM and integrated level within 3 LU.
Transition comparison counts detected types. Missing required measurements make
a section unknown; any measured difference outside its tolerance makes it differ.

## Python and MCP

```python
from myzing.explain.api import explain_video

result = explain_video("./clips/reference.mp4", "./style-card",
                       transitions=True, offline=True)
```

The signature is `explain_video(source, out_dir, *, transitions=True, offline=True)
-> dict`. Success returns `ok`, `card_json`, `card_md`, `card_png`, and `summary`
(three to six one-line strings). Failure returns `{"ok": false, "error": "..."}`.
`offline=False` is explicit consent to acquire a URL; models still remain local.
MCP `zing_explain` accepts those arguments plus optional `against`, and returns
paths and metadata only. The versioned dataclasses live in `myzing.explain.models`;
`to_dict()` and `from_dict()` reject unsupported versions and nonfinite numbers.

## Real example

The licensed V1 replay uses `korky.mp4` (Mvolz, *Korky Paul Introduction*, CC0;
SHA-256 `f11726ac7085f55a9d4f2a8a4c5ecb07c237a9639505ea0caae0802f4189a8d7`).
No media is committed. This is an excerpt from an actual local card:

The [complete example card](examples/explain/korky-card.md) preserves the real
measurements; command paths are rebased to `./clips` for readability.

```text
Shot detector: 0 cuts; 0.0 per minute. Typical shot: 19.00s.
Detector ran; no supported transition signature found.
Text style is unknown.
Contrast 84.1 L*; median chroma 13.2.
360 x 640; aspect 0.562:1.
Speech activity covers 77% of the clip (VAD).
```

The frozen labels cover no cuts in 0–6 seconds, no text at 1 second, and visible
faces at 1, 5 and 10 seconds. They contain no independent audio, font identity or
original-grade truth. The full local acceptance and those limits are recorded in
`zing-workspace/CARD1-REPORT.md`.
