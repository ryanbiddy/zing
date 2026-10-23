# Font candidates

Run `zing study reference.mp4 --caption-geometry --fonts` to rank available
font files for each measured text track. Results live in the optional
`font_candidates` section of `caption-geometry.json`. The original font remains
unknown. A candidate is a similarity result, not a recovered editor setting.

In a source checkout, install the optional runtime with `uv sync --extra fonts`,
or use `uv sync --all-extras`. Geometry also needs the existing study
runtime and explicitly provisioned OCR models described in
[caption geometry](CAPTION-GEOMETRY.md).

```text
uv run --frozen zing fonts list
uv run --frozen zing fonts fetch bebasneue poppins bangers
uv run --frozen zing fonts fetch --all
uv run --frozen zing study reference.mp4 --caption-geometry --fonts
uv run --frozen zing fonts match <breakdown-slug>
```

Each fonts command accepts `--workspace DIR` and `--json`. Fetch is the only
font-download operation. Study and match use verified local assets and do not
search system fonts or download missing files. Match reuses the saved geometry
and media; it does not rerun OCR or change the breakdown's judgment. The media
SHA-256 must agree with the geometry's recorded hash.

## Library and provenance

Anton and IBM Plex Sans are bundled. The remaining files are cached under
`<workspace>/fonts/<font-id>/` only after an explicit fetch. A font is available
only when both its font bytes and license bytes match the manifest.

| Font ID | Family | License | Compared weights |
|---|---|---|---|
| `anton` | Anton | OFL-1.1 | File default |
| `ibmplexsans` | IBM Plex Sans | OFL-1.1 | 400, 600, 700 |
| `bebasneue` | Bebas Neue | OFL-1.1 | File default |
| `oswald` | Oswald | OFL-1.1 | 400, 600, 700 |
| `montserrat` | Montserrat | OFL-1.1 | 100, 400, 700, 900 |
| `poppins` | Poppins | OFL-1.1 | Bold file |
| `inter` | Inter | OFL-1.1 | 400, 700, 900 |
| `roboto` | Roboto | OFL-1.1 | 400, 700, 900 |
| `opensans` | Open Sans | OFL-1.1 | 400, 700, 800 |
| `archivoblack` | Archivo Black | OFL-1.1 | File default |
| `bangers` | Bangers | OFL-1.1 | File default |
| `luckiestguy` | Luckiest Guy | Apache-2.0 | File default |
| `permanentmarker` | Permanent Marker | Apache-2.0 | File default |

[`library.json`](../src/myzing/_data/fonts/library.json) pins every font and
license URL and SHA-256 to Google Fonts revision
`45e3d5269e4a17d823f6d84470bc084dc5ae46f6`. Licenses were checked against that
revision's OFL.txt or LICENSE.txt, including the two Apache fonts. No new font
binary is bundled. Variable axes other than weight use each file's defaults;
the result does not imply that all weights, widths or italic styles were tested.

## Evidence and scores

The geometry envelope is version 2 in CG2 (version 1 remains readable).
Its optional `font_candidates` section
is independently versioned at 1 and round-trips through the P7 dataclass.

| Field | Meaning |
|---|---|
| `available_fonts` | Verified files available for comparison, with hashes, licenses, local paths and weight choices; retained on failures. |
| `tracks[].status` | `plausible candidate`, `best substitute`, or `unmeasured`. |
| `tracks[].original_font` | Always `unknown`. |
| `tracks[].candidates` | Families ranked by decreasing score; stable font ID breaks ties. The best aggregate weight per family is retained. |
| `tracks[].evidence` | Frame index/time, OCR text/confidence, polygon, crop bounds, mask dimensions/hash and segmentation method. |
| `candidates[].metrics[i]` | Metrics for `evidence[i]`: line IoU, glyph-run IoU, width/height and ink-density ratios, stroke fractions, candidate cap/x heights and font size. |
| `tracks[].gaps` | Missing frames, tiny/empty masks or uncertain text excluded from comparison. |
| `tracks[].rejected_candidates` | Unsupported glyphs and font rendering failures, with the excluded weight. |
| `tracks[].warnings` | Failures affecting this track, also included in the study warnings. |
| `provenance` | Media/manifest hashes, runtime versions, score formula, threshold, unavailable/excluded font IDs and sample selection. |

Up to eight evenly spaced observations per track are decoded by exact frame
index. The decoder seeks to each selected index and reads shared frames once;
it does not scan from frame zero to the last observation. Seeking can decode
from the preceding codec keyframe. Failed or inaccurate seeks leave a gap.
Every OCR line in those observations is cropped through its polygon.
Nearest Lab color separates fill from backdrop, outline and plate. When the P7
fill estimate collapses onto the backdrop, a deterministic Otsu luminance mask
is used and named in the evidence. Solid or empty masks remain unmeasured.
Font-matching failures, including OpenCV errors, become per-track warnings so
study can save the breakdown. Available fonts and provenance remain recorded;
unreadable provenance fields are identified in `provenance.errors`.

Pillow/FreeType renders the same OCR text near its measured visible-ink height.
Font size is a comparison parameter, not a recovered point size. Shape is
compared at 48 pixels high with small translations. Separated glyph runs are
also aligned when both masks have the same run count, reducing sensitivity to
different text-layout engines' advance rounding.

The score is `0.78 * shape + 0.17 * width_similarity + 0.05 * density_similarity`.
Shape combines 75% glyph-run IoU and 25% whole-line IoU when run counts agree;
otherwise it uses line IoU. Width similarity is
`exp(-3 * abs(log(candidate_aspect / observed_aspect)))`. Density similarity
uses the same expression without the factor 3. Metrics are averaged across
observations, with a single weight chosen per family for the whole track.
Stroke and candidate x/cap-height metrics are evidence, not extra score terms.
Observed x/cap heights are not inferred from arbitrary OCR lines.

CG2 excludes rejected OCR regions and confines font masks to the measured glyph
components plus their antialiased edges. At the labeled Tears of Steel frame
(0.500 s), this changes the leading substitutes from Poppins to IBM Plex Sans
for the small line, and from Bangers to Open Sans for the larger line. All remain
below 0.90. Duck's held-out credit crops still fail, and their rankings deteriorate;
see [CG2 results](../tools/eval/real/CG2-REPORT.md). No source font identities are
labeled, so ranking changes are diagnostic evidence rather than accuracy gains.

## Calibration and acceptance

The threshold is **0.90**. It was selected conservatively against 39 generated
calibration cases: all 13 families, three separate phrases at 32/44/60 pixels,
plain fill, outline and plate. Removing the generating font from each
comparison yielded a maximum substitute score of **0.868** on the recorded
Windows FFmpeg 8.1.2 run. The three calibration tests retain the 0.90 rejection
boundary; they do not retune it at runtime.

The acceptance corpus uses six other phrases/styles at 24–68 pixels, including
upper, lower and mixed case, digits, yellow/white fills, outlines and plates.
`test_known_fonts_top_three` asserts **at least 90% top-three hits separately
for each of the six phrase/style cases**, across that case's available fonts.
That requires at least 12/13 hits per style with the expanded library, or 2/2
with the bundled library. It does not assert 77/78 overall or 90% per family.

The recorded Windows FFmpeg 8.1.2 expanded run measured **77/78 top-three hits
(98.7%)**. Montserrat Thin misses once; each other family has 6/6 hits.
Only 29/78 clear the conservative similarity threshold. These are measured
results, separate from the per-style test assertion. A correct top-three ranking
can therefore still be labeled `best substitute` when the evidence is weak.
Similarity scores are not calibrated probabilities.

Every video and oracle mask is generated by FFmpeg drawtext with an explicit
font FILE path. The ranking corpus uses independently rendered oracle bounds
and known text to isolate font comparison; two additional tests run real OCR
through the complete geometry-to-font path. This is not a claim of 98.7% OCR
accuracy on real videos.

The font FFmpeg tests also check sparse seeks against sequentially decoded
pixels across keyframes and B-frames. Without an opt-in,
tests use only the two bundled fonts. The expanded test library requires
`ZING_TEST_FETCH_FONTS=1`, which explicitly permits the fixture to fetch pinned
assets. CI also runs `zing fonts fetch --all` before testing. Required FFmpeg
mode makes dependency/model skips fail.

```powershell
$env:ZING_TEST_FETCH_FONTS = "1"
$env:ZING_FONT_TEST_REPORT = "$PWD/zing-workspace/p8-accuracy"
uv run --frozen pytest -q tests/test_font_match_ffmpeg.py
$env:ZING_REQUIRE_FFMPEG = "1"
uv run --frozen pytest -q -m ffmpeg --expected-ffmpeg-tests 330
```

Reruns are deterministic with the same files and runtime versions; different
FreeType/FFmpeg builds can change rasterization and scores. Short strings,
very thin text, OCR mistakes, custom tracking, rotation, translucent fills,
occlusion, gradients and unsupported glyphs can defeat the comparison.
An absent font that resembles an available one cannot always be distinguished
from pixels. Even above threshold, the result only names a plausible candidate.
