# Explain an editing style

To turn a reference into a readable style card:

```sh
zing explain ./clips/reference.mp4 --out ./style-card
zing explain ./clips/reference.mp4 --against ./project/draft-A.mp4 --out ./comparison-card
```

Open `card.md` for the explanation and commands, `card.png` for a single
phone-readable page, or `card.json` for the measured values and coverage.
Both readable forms lead with **What a viewer notices**: three to five lines in
editor language ("One continuous vertical 9:16 talking-head shot, 19.0s with no
cuts, full frame"), each built only from measured facts, with weak evidence kept
hedged. **Get this look** follows with the real commands and this card's paths:
`zing match` for three drafts from your clips, `zing plan drafts --recipe
<card>/style-recipe.json` for an existing project, and `zing color match` /
`zing color apply` for a clip-specific color approximation.
`style-recipe.json` is the reusable StyleRecipe contract. Evidence files retain
the full study, OCR geometry, audio map and sampled color statistics.

The default output is a new folder under the current project's
`zing-workspace/explain`. If that is inside an input folder, explain chooses a
sibling of the configured workspace or current project. Outputs must be outside
the input video folders; `--out` selects another location. Existing
nonempty output folders are refused. A failed run removes what it wrote. An
interrupted run (a crash or power loss) leaves `.zing-explain-incomplete`; a
folder holding only that marker and Zing's own card files can be reused with the
same `--out`. No source media is modified.

Local files and `uoink:<id>` use the existing resolver. A Uoink reference resolves
only that item's verified kept media, with no URL fallback. HTTP(S) URLs need
`--allow-download`. Models always stay local, even when media download is allowed.
`--no-transitions` skips v6. `--json` prints the result paths and the summary lines.
Empty, damaged and audio-only files are refused before any output is created.

Install FFmpeg/ffprobe and `myzing[study,fonts,color,audio,memes]`, or run
`uv sync --all-extras` in a checkout. Missing OCR, OpenCV, NumPy or ASR models
produce stated unknowns. The PNG needs Pillow from the existing `memes` extra;
without it, `card.json` and `card.md` are still written, `card_png` is null and
the warning carries the install hint. Prepare OCR/font assets explicitly
as described in [caption geometry](CAPTION-GEOMETRY.md) and
[font candidates](FONT-CANDIDATES.md). Explain never fetches model weights.

## Reading the evidence

Every section has separate `facts`, `confidence`, `unknowns` and readable `lines`,
plus one `not_knowable` sentence (what no export can reveal). The readable card
shows that sentence; the full, itemized `unknowns` stay in `card.json`.
Confidence scores are heuristics, not calibrated probabilities. Missing values
are null or absent; they never become zero measurements. `card.json` is the
readable record, not a second copy of the evidence: long text lists keep their
first 200 entries (eight samples per track) with totals under `truncated`, and
the evidence files keep everything. Audio maps stop at 600 seconds; the card
then says which span tempo, loudness and moments describe.

- Pacing uses detected shot boundaries. It gives a shot-length distribution,
  cut rates in ten-second windows (a final window under two seconds joins the
  previous one), and nearest supported beats/drops. A zero-length timeline has
  unknown pacing, never a rate. Beat/drop alignment means within 80 ms. When v6
  finds an additional hard cut, the card discloses the disagreement and
  comparison pacing becomes unknown. No detector is treated as ground truth.
- Transitions retain v6 types, times, scores and abstentions. An instantaneous
  event reads "hard cut at 0.80s". An unknown effect stays unknown; flash/whip
  motion does not become a chosen render effect.
- Text includes accepted OCR tracks and sampled appearances. Visible ink height
  is a percentage of the short side, not font size. Captions, titles, credits and
  uncertain scene text retain the existing text-role evidence. Only
  speech-supported caption tracks enter caption-placement comparisons.
  Low font scores are substitutes; the original font is always unknown. The
  readable card quotes text only when its median OCR confidence is at least 0.85,
  it was read in two samples (or at 0.95 or higher), and it reads as words (no
  digits inside words, mid-word case changes, missing vowels or arrows). Every OCR
  string, with its `ocr_confidence` and `quotable` flag, stays in `card.json`.
- Color reports sampled Lab palette, contrast, chroma and a*/b* values, with SDR
  assumptions and coverage. These include objects, lighting and graphics. The
  plain wording names the mean a*/b* hue angle (pure sRGB blue has a* +79, so a
  positive a* alone never means "red"): warm for red/orange/yellow, cool for
  cyan/blue, tint for green/magenta, with slight/noticeable/strong from the chroma.
  Original LUT, camera settings and skin-specific treatment remain unknown.
- Framing reports the displayed size (rotation flags and pixel aspect applied;
  the stored size is kept), sampled face presence, placement, face height and
  top-of-face gap. That gap is not clearance above the hair. A matte check
  decodes seven display-oriented frames and reports solid letterbox, pillarbox
  or windowbox bars present in every informative sample, with the active picture
  size. Blurred or textured fills are not detected.
- Audio reports VAD speech share, music evidence, supported tempo, loudness,
  mix energy and detected moments. The study's gap-floor music candidate alone is
  weak evidence (it also fires on room tone), so the card says "music not
  confirmed" unless a steady beat supports it. Mixed audio cannot establish
  ducking gain. Missing tempo does not mean the music has no beat.

The PNG is 800 pixels wide, with text at least 13 pixels high when displayed at
400 pixels. It shows three key frames at the displayed aspect (outlined, never
padded with bars), what a viewer notices, a shot strip, caption/title boxes,
swatches, a mix-level strip and the get-this-look commands. It is a summary: the Markdown and JSON retain
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
Transition comparison uses detected signatures per minute, within 25% of the
reference rate or one event in the shorter clip, so different durations compare
fairly; when neither video has a detected signature the section is close. Missing required measurements make
a section unknown; any measured difference outside its tolerance makes it differ.

## Python and MCP

```python
from myzing.explain.api import explain_video

result = explain_video("./clips/reference.mp4", "./style-card",
                       transitions=True, offline=True)
```

The signature is `explain_video(source, out_dir, *, transitions=True, offline=True)
-> dict`. Success returns `ok`, `card_json`, `card_md`, `card_png`, and `summary`
(the three to five "what a viewer notices" lines). `card_png` is null when
Pillow is missing. Failure returns `{"ok": false, "error": "..."}`.
`offline=False` is explicit consent to acquire a URL; models still remain local.
MCP `zing_explain` accepts those arguments plus optional `against`, and returns
paths and metadata only. The versioned dataclasses live in `myzing.explain.models`;
`to_dict()` and `from_dict()` reject unsupported versions and nonfinite numbers.

## Real example

The licensed V1 replay uses `korky.mp4` (Mvolz, *Korky Paul Introduction*, CC0;
SHA-256 `f11726ac7085f55a9d4f2a8a4c5ecb07c237a9639505ea0caae0802f4189a8d7`).
No media is committed. This is the lead of an actual local card:

The [complete example card](examples/explain/korky-card.md) preserves the real
measurements; command paths are rebased to `./clips` for readability.

```text
- One continuous vertical 9:16 talking-head shot, 19.0s with no cuts, full frame.
- No on-screen text read in the sampled frames.
- Speech-led audio (talking 77% of the time); music not confirmed.
- Natural color leaning strongly cool (blue); strong contrast.
```

The frozen labels cover no cuts in 0–6 seconds, no text at 1 second, and visible
faces at 1, 5 and 10 seconds. They contain no independent audio, font identity or
original-grade truth. The full local acceptance and those limits are recorded in
`zing-workspace/CARD1-REPORT.md`.
