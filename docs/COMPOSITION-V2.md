To read a v2 plan or upgrade a v1 EDL, use the composition API:

```python
import json
from myzing.composition import load_composition, lower_to_v1

plan = load_composition(json.loads(saved_json))
legacy = lower_to_v1(plan)  # Raises if any v2 instruction/evidence would be lost.
```

Run `zing render plan.json -o output.mp4 --keep-work render-work` for either
EDL v1 or Composition v2. R9 adds `myzing.render.render_composition(plan, output,
base_dir=plan_directory)`. V1 still uses its original compiler. V2 supports
cuts, source audio, placed voiceover/music, v1 voiceover ducking, and positioned
ASS captions. See [V2 rendering](RENDER-V2.md) for bounds, fonts and timing.

LUTs, speed maps, non-cut transitions, HyperFrames captions, other audio roles,
audio trims, other ducking scopes and loudness targets fail before media work
with a `not yet supported in this renderer: ...` list. Passing v2 JSON to
`EDL.from_dict` still fails; use `load_composition` to load v2.

All new records have `to_dict`, `from_dict`, `to_json` and `from_json`. Nested
records use `version: 1`; Composition uses `schema_version: 2`. V2 and recipe
JSON sort object keys, retain array order and numeric values, use UTF-8, and
reject non-finite numbers, including numbers inside free-form evidence.
Unknown fields and unsupported versions fail instead of disappearing.

The following fields define Composition. Times are seconds. Intervals are
half-open `[start, end)`, except a hard cut is a point. Source timestamps remain
source coordinates; words and caption paths use output coordinates. The
contract does not round timestamps to frames.

| Composition field | Contract |
|---|---|
| `schema_version` | Required integer `2`. |
| `assets` | Array of `AssetRef` records. IDs are unique within the array. |
| `clips` | Array of `CompositionClip`, extending the existing `Clip`. Stored order survives serialization; validation uses timeline order. Empty plans can be saved. |
| `captions` | Array of `CompositionCaption`, extending `CaptionSpec`. IDs are unique. |
| `audio` | Array of `CompositionAudio`, extending `AudioTrack`. IDs are unique. |
| `transitions` | Array of explicit `Transition` records between adjacent clips. Every positive clip overlap needs one. |
| `width`, `height` | Positive integer output dimensions in pixels; defaults 1080 × 1920. Encoder-specific constraints still belong to rendering. |
| `fps` | Existing inventory `Rational`: positive integer `numerator`, `denominator`, and `version: 1`. Default 30/1. |
| `loudness_target` | `LoudnessTarget` or null. Null requests no new loudness policy. |
| `warnings` | Ordered strings. Evidence gaps and planning limitations belong here. |
| `accepted_unsafe_layouts` | Optional array of unique caption IDs, default `[]`. Explicitly accepts those events' unsafe/infeasible layout warnings for rendering. Other warnings never imply acceptance. |
| `brief` | Existing `myzing.brief.models.Brief`, including its version, or null. Its answers retain the brief module's validation. |
| `legacy_fps` | Migration-only original v1 FPS number, or null. Retains integer versus float spelling and the exact decimal value. |
| `legacy_timing_order` | Migration-only map from JSON pointers to ordered key arrays inside v1 words' timing objects. `/caption-index/word-index/...` identifies an object. Values remain in `Word.timing`; this map stores only key order. Default `{}`. |

Asset references are snapshots of inventory identity. `upgrade_edl(edl,
manifest=manifest)` matches exact IDs, paths, original paths and previous paths.
It never guesses by basename. Ambiguous matches fail. It copies a matched
asset's ID, SHA-256 and probed duration. It does not read or hash media.

| AssetRef field | Contract |
|---|---|
| `id` | Nonempty stable identifier. A manifest's ID is authoritative. |
| `path` | Nonempty source path. Relative paths belong to the saved composition's directory; absolute paths remain explicit. Callers exporting from another directory must rebase paths. |
| `sha256` | Lowercase 64-digit content hash, or null when a legacy source has no inventory evidence. Null does not verify file identity. |
| `duration` | Positive source seconds from the manifest probe, or null. No media probe runs during validation. |
| `aliases` | Other exact spellings used by clips/audio, including legacy paths or inventory IDs. Default `[]`. |
| `version` | `1`. |

Without a manifest match, upgrade creates a deterministic `legacy-` ID from the
source path's UTF-8 SHA-256, and leaves the **content** `sha256` null. Such an ID
is stable for that spelling, not across a file rename. Use inventory IDs for
projects that move or rename assets. Neither loading nor upgrading verifies
that a stored checksum still matches bytes on disk.

| CompositionClip field | Contract |
|---|---|
| `src`, `src_in`, `src_out`, `timeline_start` | Inherited v1 fields. `src` must match the referenced asset's path or an alias. Require `0 <= src_in < src_out` and nonnegative timeline start. |
| `id`, `asset_id` | Unique clip instance ID and an existing asset ID. Repeated uses of an asset have different clip IDs. |
| `speed_map` | Ordered `SpeedSegment` array, default `[]` for rate 1. Segments must tile the complete source trim without gaps or overlaps. |
| `color` | `ColorTransform` or null. |
| `version` | `1`. |

Each `SpeedSegment` contains `src_in`, `src_out`, positive `rate` (source seconds
per output second), and `version: 1`. Rate changes are piecewise constant;
reverse and freeze are unsupported. A segment's output duration is
`(src_out - src_in) / rate`. `clip.duration`, `clip.timeline_end` and
`clip.source_at(output_seconds)` use that mapping. Ordinary clip audio follows
the clip's source mapping. This pass records that intent without compiling it.

`frame_time(index, fps)` returns an exact `fractions.Fraction` in seconds.
`frame_index(seconds, fps)` floors by default; pass `rounding="ceil"` or
`"nearest"` explicitly. Nearest ties go forward. Indices are zero-based output
CFR frames, not VFR source indices. Decimal 29.97 stays 2997/100; upgrade never
guesses 30000/1001. At 30000/1001, frame 30000 starts at exactly 1001 seconds.

| Transition field | Contract |
|---|---|
| `id` | Unique nonempty transition ID. |
| `outgoing_clip`, `incoming_clip` | IDs of adjacent clips in timeline order. A pair can have only one transition. |
| `start`, `end` | Output overlap window. Start equals the incoming clip's start; end equals the outgoing clip's end. |
| `recipe` | `TransitionRecipe`: `kind`, `duration_seconds`, `reason`, optional `direction`, optional `observation`, and `version: 1`. |
| `outgoing_handle`, `incoming_handle` | Required `SourceRange` objects for a positive overlap: `src_in`, `src_out`, `version: 1`. Null for a hard cut. |
| `version` | `1`. |

`TransitionRecipe.kind` is `hard_cut`, `dissolve`, `wipe` or `zoom_punch`.
Hard cuts require zero duration; other kinds require positive duration. Only a
wipe has a direction, which must be `left`, `right`, `up` or `down`. `reason`
records why a stand-in was chosen. `observation` reuses P14's
`TransitionEvidence`, with its signature, event interval, evidence window,
heuristic confidence, detector version, reason, legacy observation index and
wipe direction. Its signature can be `unknown`; that is an abstention, not a
render effect. The original `TransitionObservation` and v1 Breakdown bytes are
unchanged.

Trims **include** transition handles. Each handle names the portion of its
source trim consumed during the overlap, after applying the speed map. No
extra footage outside the trim is implied. A transition cannot exceed either
clip's output duration. Handles must cover the complete mapped overlap;
missing or shortened handles fail. Timeline gaps and three-way overlaps are
unsupported. Time comparisons use the legacy renderer's one-microsecond
tolerance. Known source durations use its 50-millisecond probe tolerance.

| CompositionCaption field | Contract |
|---|---|
| `text`, `start`, `end` | Inherited phrase text and output interval. Text must be nonempty; the interval must fit the composition. |
| `position`, `all_caps`, `word_timed` | Inherited v1 controls. `position` remains `top`, `center`, `lower` or `bottom`; default `lower`. An explicit layout supplies the geometry. |
| `words` | Existing `Word` records, preserving text, start, end, confidence and optional `timing` verbatim. Timings must be positive, ordered, nonoverlapping and contained in the phrase. Word-timed events need words. |
| `id` | Unique event ID, also used by its layout record. |
| `alignment` | Optional `left`, `center` (default), or `right`; horizontal text alignment within the layout box. |
| `layout` | Existing `layout.types.EventLayout`, or null for a legacy anchor. Its ID/start/end must equal the caption's. |
| `font` | `FontAsset`: nonempty `path`, lowercase content `sha256`, nonempty `license`, and `version: 1`; or null for the legacy default font. |
| `style` | `CaptionStyle`, or null for the v1 renderer defaults. |
| `backend` | Exactly one of `ass` (default) or `hyperframes`. |
| `template` | `phrase-highlight` or `kinetic` for HyperFrames; null for ASS. |
| `version` | `1`. |

`EventLayout` is reused in full: `id`, `start`, `end`, `reason`, `overlap`,
`box`, `path`, `warnings`, `fallback`, `scale`, `version`. Exactly one of a box
or a path must exist. `Box` uses normalized top-left `x`, `y`, `width`, `height`
and `version: 1`; positive extents must fit inside `[0,1]`. Path entries are the
existing `Keyframe(time, box, version=1)`, strictly increasing and covering the
exact event start and end. Interpolation is linear with endpoint holds.

The layout's `OverlapCheck` preserves `safe`, `face_ids`, `mask_names`,
`method`, `scope` and `version`. Its safe flag must agree with its collision
lists. Unsafe layouts must carry a warning. Safety describes the supplied
tracks/masks; it does not prove face-detector recall. Composition preserves the
result and does not rerun detection or collision search.

`CaptionStyle` uses the sidecar's names and units: `size` is 1–512 output
em pixels; `color`, `highlight`, `outline_color`, and optional `box_color` use
`#RRGGBB`; `outline_width` is 0–20 pixels; `version` is 1. Defaults are white,
yellow highlight, black outline, two-pixel outline and no plate color.
HyperFrames events require layout, font, style and template. Its current PH v1
adapter also requires integer FPS and supports a narrower output shape.
Future compilation must check that capability boundary; selecting the backend
in this contract does not invoke it.

R9 adds only `CompositionCaption.alignment` and
`Composition.accepted_unsafe_layouts`, with defaults preserving existing input.
The planning contract had no horizontal alignment or explicit safety acceptance
field. These additions make those render instructions typed and serializable;
free-form warning text is not authorization. Existing v2 documents still load,
and v1 types and serialized bytes are unchanged.

| ColorTransform field | Contract |
|---|---|
| `lut_path`, `sha256` | Local `.cube` reference and lowercase content hash. Loading does not open the LUT. |
| `strength` | Blend strength in `[0,1]` applied to this cube. |
| `color_space` | Nonempty input-space assumption, such as SDR Rec.709 display-referred RGB. It is not camera-profile recovery. |
| `baked_transform` | Existing color `Transform`, including `LookParameters`, or null. Describes controls already baked into the cube. |
| `stage` | Always `before_captions`. Captions remain outside the footage grade. |
| `version` | `1`. |

`ColorTransform.from_recipe(color_recipe)` copies PC's cube path/hash,
color-space assumption and chosen transform. It sets the external LUT strength
to 1 because PC already bakes the chosen strength, exposure and white-balance
controls into that cube. Applying those controls again would double the grade.

| CompositionAudio field | Contract |
|---|---|
| `src`, `kind`, `timeline_start`, `gain_db`, `duck_under_speech` | Inherited AudioTrack fields; time is output seconds, gain is dB. Source spelling must match the asset path or alias. |
| `id`, `asset_id` | Unique track ID and existing asset ID. |
| `role` | AudioMap roles `speech`, `music`, `silence`, `uncertain`; explicit editorial roles `voiceover`, `sfx`, `ambience` are also supported. |
| `role_evidence` | Existing AudioMap `Segment` or null. Preserves `start`, `end`, `label`, `confidence`, `evidence`, `version`. Its source-coordinate label must agree with `role`. |
| `src_in`, `src_out` | Nonnegative source trim, default 0/null. A finite out-point must follow the in-point. Null retains play-once-until-output-end intent. |
| `duck_scope` | `voiceover` (v1 default), `source_speech`, or `all_speech`. Only music may request ducking. |
| `version` | `1`. |

`audio_from_map(map, segment_index, id=..., asset=...)` places an explicit
segment and copies its role/evidence. It does not label an onset as SFX or
convert speech to voiceover. `LoudnessTarget` contains `integrated_lufs`
(-70 to -5), `true_peak_dbtp` (-9 to 0), `loudness_range_lu` (1–50, default 11),
and `version: 1`. These are requested targets, not achieved measurements.

The StyleRecipe v1 builder separates observations from choices:

```python
from myzing.style_recipe import build_style_recipe

recipe = build_style_recipe(
    breakdown,
    reference_sha256=known_reference_content_hash,
    color=color_recipe, audio=audio_map, layout=layout_plan,
    transitions=transition_result,
    font_candidates=chosen_font_candidates,
    transition_recipes=chosen_transition_recipes,
)
```

Every argument after Breakdown is optional. Construction copies its inputs,
runs no detector, accesses no files or network, and adds no wall-clock data.
Breakdown judgment slots are excluded. Optional outputs retain their own
source identity; a clip's color target or layout is never relabeled as a
measurement of the reference.

| StyleRecipe field/record | Contract |
|---|---|
| `reference` | `ObservationProvenance` identifying the studied URL/file and any known hash. |
| `measured` | Ordered `MeasuredFact` array: `name`, JSON `value`, explicit `unit`, `coverage`, nullable `confidence`, `provenance`, `confidence_kind`, `version: 1`. |
| `approximations` | `Approximations`: `font_candidates`, `looks`, `transitions`, nullable `layout`, and `version: 1`. Empty arrays mean no choice supplied. |
| `unknowns` | `Unknown` records: `subject`, `reason`, `status` (`unsupported`, `unmeasured`, `unreported`), nullable `provenance`, JSON `evidence`, `version: 1`. |
| `warnings` | Ordered, deduplicated producer warnings. |
| `version` | Required integer `1`. |
| `ObservationProvenance` | `reference`, nullable `sha256`, `sample_timestamps`, nullable `detector`/`detector_version`/`model`/`model_version`, `timestamp_basis`, `crop_evidence`, JSON `details`, `version: 1`. Missing historical provenance stays null. |
| `CropEvidence` | Source `timestamp`, normalized `box`, optional crop file `path`/`sha256`, `note`, `version: 1`. A supplied crop is evidence; none is manufactured. |
| `Coverage` | Nonnegative `samples`, nullable `[0,1]` `fraction`, nonempty `basis`, producer `details`, `version: 1`. The basis distinguishes sample fraction from temporal coverage. |
| `FontCandidate` | `family`, nonempty `substitution_evidence` list, optional `FontAsset` as `asset`, `version: 1`. No original-font claim. |
| `LookApproximation` | A `ColorTransform` as `color`, selection `evidence` strings, `version: 1`. Existing look parameters remain in `color.baked_transform`. |

Confidence is either `unreported` with null, `producer-reported`, or
`heuristic`. P14 and audio/color scores are heuristic evidence quality, not
calibrated probabilities. Word confidence 1 can mean unreported, so the builder
does not infer an aggregate ASR confidence. Corrected `Word.timing` records
remain visible inside the observed words.

Pacing and OCR facts retain source timestamps. Color facts carry individual
units for luma, CIELAB statistics, pixel counts and coverage. Color sampling
times are requested seeks, not exact decoded PTS. Audio tempo `none` and
`unknown` remain explicit unknown entries; no beat grid is invented. P14
unknown events retain their complete sidecars. A linked supported sidecar must
agree with its unique legacy observation. Chosen transitions require an
explicit recipe argument; detections alone never select an effect.

Use the builder's `provenance` mapping to supply observation evidence by scope:
`meta`, `shots`, `words`, `captions`, `audio`, `color`, `layout`, `transitions`.
Each value is an `ObservationProvenance`. This is how a caller adds a pinned
model revision or crop evidence that an older Breakdown lacks. The builder
also recognizes the historical embedded SceneDetect/RapidOCR version stamps.
Original font, LUT, preset and project identity always remain unsupported.

V1 compatibility is checked against the base serializer, not the input file's
arbitrary whitespace. `EDL`, `Clip`, `CaptionSpec`, `Word`, `AudioTrack`,
`Breakdown`, `StyleProfile` and `TransitionObservation` retain their field order
and v1 serialization behavior. No absent `Word.timing` key is inserted. The only
change to `schemas.py` is the version guard and migration guidance in
`EDL.from_dict`.

Upgrade retains every v1 field, numeric spelling, source spelling, and word
timing object. Saving canonical v2 and then lowering restores the v1 timing
object's key order from migration metadata. Editing a timing value still
changes that value; metadata never substitutes an old measurement.

Lowering projects structural asset references/IDs/checksums back to the
preserved v1 `src` paths; v1 has no inventory-metadata slot. It carries the
legacy Clip, CaptionSpec and AudioTrack fields, and does not resolve aliases or
rewrite paths. If a caller used an inventory ID as `src`, that spelling must be
resolved to a usable path before rendering, just as for any v1 EDL.

Lowering rejects any speed map, color transform, explicit transition, caption
layout/font/style/template, HyperFrames backend, changed audio role, role
evidence, audio trim, nonlegacy duck scope, loudness target, warnings or brief.
It lists all blockers in stable order. An FPS change conflicting with
`legacy_fps` also blocks; without that migration value, the rational rate must
be exactly representable by a v1 decimal number. The conversion does not
silently round NTSC rates. These checks preserve instructions and evidence;
they do not assert that the old renderer can find the media on disk.

The first worked example is an eight-second, three-clip talking-head plan.
The complete input is [talking-head.json](examples/composition-v2/talking-head.json).
The [layout plan](examples/composition-v2/layout-plan.json) contains a synthetic
padded face track and the actual chooser result. Its first requested center
anchor collides with the face, so the chooser selects a safe box. The second
caption follows a safe path and selects HyperFrames; the other two select ASS.
Every word retains its synthetic source timing and timeline-map adjustment.

| Clip | Source trim | Output interval | Color |
|---|---|---|---|
| `clip-1` | 1–4 s | 0–3 s | Teal-orange `.cube`, strength 0.7, before captions |
| `clip-2` | 2–5 s | 2.5–5.5 s | Same transform |
| `clip-3` | 0–2.5 s | 5.5–8 s | Same transform |

The dissolve is `[2.5,3)` seconds, frames 75–90 at 30/1 FPS. Its outgoing
source handle is `[3.5,4)`; the incoming handle is `[2,2.5)`. Their half-second
overlap makes the result eight seconds rather than the trims' 8.5-second sum.
Music starts at zero, has -14 dB gain, and requests ducking under all speech.
The mix target is -16 LUFS integrated, -1 dBTP and 11 LU range.

This is a contract example, not a rendered demonstration. Repeated-digit
media/LUT hashes are declared placeholders. Replace them with inventory and
LUT checksums before compiling. The Anton hash is real and refers to the
already-bundled OFL-1.1 font. No footage, music, font or LUT was downloaded.
The [recipe example](examples/composition-v2/style-recipe.json) uses the existing
synthetic Breakdown fixture and labels the selected font/dissolve as choices.

The second worked example lowers that same plan:

```python
from pathlib import Path
from myzing.composition import Composition, lower_to_v1

plan = Composition.from_json(
    Path("docs/examples/composition-v2/talking-head.json").read_text(encoding="utf-8")
)
lower_to_v1(plan)
```

The exact failure is also saved in
[lowering-failure.json](examples/composition-v2/lowering-failure.json):

```text
Cannot lower Composition v2 to EDL v1; blocking features: clips[0].color; clips[1].color; clips[2].color; transitions; captions[0].layout; captions[0].font; captions[0].style; captions[1].layout; captions[1].font; captions[1].style; captions[1].template; captions[1].backend=hyperframes; captions[2].layout; captions[2].font; captions[2].style; audio[0].duck_scope=all_speech; loudness_target; warnings
```

JSON Schema exports are packaged as
`myzing/_data/schemas/composition-v2.schema.json` and
`myzing/_data/schemas/style-recipe-v1.schema.json`. Both have a top-level object
shape and no top-level `oneOf`. All references are local `$defs`; validation
requires no schema download. MCP/Uoink clients can load them with
`importlib.resources.files("myzing").joinpath("_data/schemas", filename)`.

Schema validates types, versions, required fields, enums, many numeric bounds,
hash spelling and required overlap handles. Cross-field checks such as
`x + width <= 1`, increasing keyframe times, ID references, source mapping and
matching overlap windows require the Python loader as well. JSON parsers must
reject NaN/Infinity; the Python contract rejects them recursively.

Regenerate and check the committed artifacts with:

```console
uv run --frozen python tools/export_schemas.py
uv run --frozen python tools/export_schemas.py --check
uv run --frozen python -m tools.composition_examples
uv run --frozen python -m tools.composition_examples --check
```

Tests validate the complete composition and recipe examples with the existing
dev environment's transitive `jsonschema` dependency (through MCP), compare the
failure message, and check packaged schema bytes. Fourteen persisted v1
documents have snapshots from the base serializer. A suite-wide frozen field
oracle also checks every v1 serialization and EDL constructed by the existing
fixtures and render goldens.
