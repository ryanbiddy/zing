# Three draft plans

`zing plan drafts` writes three Composition v2 documents from a saved project,
brief and StyleRecipe. It reads existing studies and runs offline. It does not
study footage or render videos.

```powershell
zing study C:\clips\take-1.mp4 --raw --workspace C:\edit-project
zing study C:\clips\take-2.mp4 --raw --workspace C:\edit-project
zing plan drafts C:\edit-project --recipe C:\edit-project\recipe.json --seed 17 --out C:\edit-project\drafts
```

Create the inventory with `zing project init` and save `brief.json` with
`zing brief new` first. Study every clip you want considered. Studies are read
from `<project>/breakdowns/*/breakdown.json` and the current `ZING_HOME`.
They must match an exact original source path, resolved studied media path,
or recorded `source_sha256`; a basename is never enough. Multiple matching
studies need one authoritative copy. Missing, stale, unfinished or invalid
studies are listed in the comparison report with a `zing study` remedy.

The MCP equivalent is `plan_drafts(project, recipe, out, seed=17)`. It returns
paths and a summary. `status: "ready"` means plans were written: three, or
fewer when the footage offers no further distinct edit inside a measured
reference's timing (`missing_drafts` gives the reason; a draft is never
duplicated). `alternatives` names any draft outside the reference timing.
`status: "shortage"` means no plan was written. A shortage is a valid tool
result, while malformed inputs and filesystem errors use the usual error
envelope. The CLI exits 1 for either a shortage or an error.

## What the choices mean

A favors a speech-led opening using clean-take support and complete-word
density. B favors observed keyframes and less speech in its opening. C favors
the shortest feasible selection within two frames of the brief's target.
These are deterministic editorial heuristics. They do not establish which
line is the best hook or which image is the strongest visual.

Every pair must change the opening content with less than 50% source overlap,
or change at least the greatest of one second, the reference median shot
duration, and 20% of the target. Filename changes, alternate asset IDs for
identical bytes, and tail reordering alone do not qualify. A draft cannot reuse
overlapping source footage to pad its duration.

Must-keep moments expand outward to complete word boundaries and remain
continuous in source order, including across camera cuts. Forbidden
moments exclude whole overlapping words, including duplicate copies of the
same source. Phrase matching ignores case and punctuation. A must-keep phrase
with several occurrences needs an explicit clip/start/end. Forbidden phrases
exclude every measured occurrence. Invalid word intervals require review;
planning does not repair them or run ASR.

The search uses measured shots, words, raw keeper candidates and supplied
dead-air intervals. Older studies store only a dead-air count; that count
cannot establish where silence occurs. An optional `audio-map.json` beside a
study supplies measured silence intervals after source and duration checks.
Must-keeps take precedence over silence heuristics. Search is bounded to 2,400
candidates, 96 retained states per expansion and 120 expansion steps per
strategy. A search shortage is not proof that a human editor could not find
another solution.

## Style and evidence

The match report compares planned median shot duration (10% tolerance), first
cut (two frames), first caption (one frame), caption words visible, all-caps
rate and brief duration (two frames). It counts original visual cuts inside
trims and actual changes between trims. Adjacent entries from one continuous
source cannot manufacture a cut. Deviations name the constraint; missing
recipe observations remain unmeasured.

Caption groups follow the recipe's median words-visible count. One-word
captions use word timing; larger groups use phrase display. The all-caps
fraction is rounded to the nearest representable number of caption events.
Word timestamps retain their source timing provenance through timeline mapping.

The first ranked font substitution in `recipe.approximations.font_candidates`
is used when it has a licensed local FontAsset with a matching checksum.
Candidate evidence may come from caption geometry; it is not original-font
recovery. A family name without an asset returns `font_asset`. With no
candidate, the disclosed default is the existing renderer's Arial bold and
system fallback. Missing size, color and animation observations use renderer
defaults, not invented measurements.

When `recipe.approximations.layout` supplies events, their boxes or paths are
retimed and reused in order. Platform-mask checks are rerun; reference-face
safety does not transfer to new footage. Each plan states that output face
safety needs a fresh layout check. A selected LUT approximation is retained;
transition approximations are currently reported as unapplied. Output uses
30 fps CFR and the brief's aspect at its `short_side` (1080 by default, so
full HD). Each plan's comparison entry has a `resolution` record; a
low-resolution source puts its numbers and recommendation first in the
plan warnings and the summary (see [FRAMING.md](FRAMING.md), "Low-resolution
sources"). Brief `short_side: "auto"` plans at the recommended size when
that plan shows more sharp picture, and otherwise keeps the size and says why.

Source audio follows the clips. `none` adds no music or SFX; it cannot separate
embedded sounds from source speech. Supplied audio files must be inventoried.
Music is placed sequentially from zero with a disclosed -12 dB gain and
source-speech ducking intent; SFX start at the first cut with a disclosed
-6 dB gain. These choices are planning defaults. No onset is labeled as SFX.
Caption language requests and names needing ASR correction remain review
warnings; planning does not translate or guess a spelling correction.

## Files and v1 rendering

The output folder contains `plan-A.json`, `plan-B.json`, `plan-C.json`, and
`comparison.json`. Each plan is an ordinary Composition v2 document: the brief
is in `brief`, and its versioned planning evidence is a JSON string prefixed
`P17 planning evidence: ` in `warnings`. The comparison repeats that evidence
in structured form, including source/output mappings, why drafts differ,
honored facts, deviations, unknowns and lowering blockers. Planning adds only
optional, versioned Composition fields (clip `framing`, caption `layout` and
`style`); see [FRAMING.md](FRAMING.md).

Planning measures subjects in the used source trims, then writes as little new
geometry as safety needs. A square-pixel source that fits the brief aspect keeps
absent framing (the same default fit graph). An unstyled caption keeps no
layout or style when its default box, measured with libass at the 118% word-pop
size plus a small margin, clears measured subjects, the visible picture and the
output reserves. Any other caption, or any caption that cannot be measured
(no FFmpeg/libass), receives a placed layout and an output-scaled style, and
other aspects receive explicit framing.

For v1-representable edits, the command also writes `plan-A.edl.json` and its
B/C counterparts. The full v2 documents retain their evidence. The derivative
explicitly separates only `brief` and `warnings`, then calls the existing strict
`lower_to_v1`; it never discards fonts, layouts, framing, color, transitions or
audio policy to force a renderable result. Those features are listed as blockers.

Plans with a music bed are the one exception, because EDL v1 cannot carry a
trimmed, speech-ducked track: when music is the only thing that blocks
lowering, the derivative keeps the picture, captions and source audio
(dialogue) and drops only the music tracks. `plan-A.edl.music.json` (version
1, `kind: "zing.music_sidecar"`) then holds what an editor needs to rebuild
the bed: track path and SHA-256, `timeline_start`/`timeline_end`, `source_in`
and `source_out`, `gain_db`, the fade-in/out seconds the v2 renderer applies,
and the duck: scope, depth, attack, release, hold, plateau and the release
gap, the speech-over-music target, the known speech spans, the passages the
renderer ducks under (the same `duck_passages` rule, so short gaps and close
edit edges stay ducked), the per-clip `bed_gain_points`, and `envelope_db`
keyframes (timeline seconds, dB relative to the track gain, bed gain points
included) at every ramp start and end. Zing renders raised-cosine ramps
between those keyframes. `dialogue` lists, per clip, what the v2 renderer
does to the clip's own audio and EDL v1 cannot: the dialogue-matching gain,
its peak compressor (threshold dBFS, ratio, attack and release ms, knee dB)
and the speech-free fades at source changes. `cannot_carry` lists what the
EDL cannot represent (source trim, ducking under source speech, fades and
envelope with bed gain points, dialogue gain, compressor and edge fades,
MUSIC1 alignment evidence, the v2 measurement sidecar and peak limiter). The
comparison's `v1` entry records `scope`, `music_removed`, `music_sidecar` and
the full-plan `blockers`; `plan_drafts` returns `music_sidecars`. Any other
blocker (framing, layout, fonts, color, SFX, transitions) still blocks the
derivative, and no sidecar is written. Render `plan-A.json` for the complete
mix.

```powershell
zing render C:\edit-project\drafts\plan-A.edl.json -o C:\edit-project\draft-A.mp4
```

The same inputs and seed produce identical JSON bytes, even with a different
output folder. Input locations remain explicit absolute paths. A rerun replaces
only P17-owned outputs; a shortage removes an earlier owned trio so stale plans
cannot be mistaken for success. Unrelated existing output files are refused.

Generate an offline example with `uv run python -m tools.plan_examples --out
zing-workspace/p17-sample`. Its colored clips and authored word intervals test
planning and render mappings. They do not measure transcription accuracy or
establish the release gate for human-labeled speech timing.
