# Saved briefs

After `zing project init`, start the interview:

```bash
zing brief new ./project
zing brief show ./project
```

Zing asks six topics: purpose and audience; platform, aspect and length; moments
to keep or avoid; caption language and spellings; music and SFX; reference match.
Each topic has short follow-up prompts. Press Enter to accept the default printed
beside a prompt. Invalid answers get a specific correction and another attempt.
The interview uses plain stdin/stdout, including piped input. EOF or Ctrl+C before
completion leaves the previous brief unchanged.

Defaults are a starting brief, not conclusions about your footage:

| Answer key | Default |
|---|---|
| `purpose` | `Explore the footage` |
| `audience` | `Not specified` |
| `platform` | `Not specified` |
| `aspect` | `9:16` (also accepts `1:1`, `16:9`) |
| `target_length_seconds` | `30` (more than 0, at most 60 for v0.1) |
| `must_keep`, `forbidden` | Empty lists |
| `caption_language` | `original` (spoken language; `none` disables captions) |
| `exact_spellings` | Empty list |
| `music` | Keep original audio; no added music |
| `sfx` | None added |
| `reference_match` | `recommend` (also accepts `exact`, `pacing only`) |

For moments, type `intro.mp4 @ 0-2.5; "the exact words"`. Times are source seconds,
`mm:ss`, or `hh:mm:ss`. A quoted phrase may contain semicolons. A clip selector
can be an inventory ID, exact stored path, or unique filename. It is saved as a
stable asset ID. Ambiguous names, reversed intervals, ranges beyond the measured
clip duration, and directly conflicting keep/avoid constraints are rejected.
Quoted phrases remain requests; their locations need timed transcripts and
review. The interview does not run speech recognition.

Enter exact names and terms separated by semicolons, such as `Zoë; Zing; ACME`.
Case, accents, and internal spacing are preserved. For names containing semicolons,
use a JSON list. The JSON moment form also supports a phrase scoped to a clip:
`[{"clip":"intro.mp4","phrase":"the exact words"}]`.

Music and SFX are separate choices. Enter `none`, `keep original audio`, or
`supplied files: audio/bed.wav; audio/hit.wav`. These choices govern added music
and effects; they do not strip speech or separate tracks in the original audio.
File paths resolve against the project folder, regardless of the current working
directory. Files outside it stay absolute. Inventory IDs are also accepted.
Missing files remain in the brief and are named in the recommendation. Files
outside the inventory are reported as having unknown audio compatibility.

## Run without prompts

```bash
zing brief new ./project --answers '{"purpose":"Introduce the maker","audience":"New customers","platform":"Instagram","aspect":"9:16","target_length_seconds":20,"must_keep":[{"clip":"intro.mp4","start":0,"end":2}],"exact_spellings":["Zoë","Zing"],"music":{"source":"supplied files","files":["audio/bed.wav"]},"sfx":{"source":"none"},"reference_match":"pacing only"}'
zing brief new ./project --brief ./project/brief.json
zing brief show ./project --json
```

`--answers` accepts an unversioned JSON object. Omitted keys use the defaults
above; unknown keys, nulls, wrong types, and invalid choices fail without writing.
`--brief` accepts a complete version 1 brief. The two flags are mutually exclusive.
Both replace the entire saved brief after validation. `--json` emits the brief,
its path, and recommendation as one JSON object; it requires non-interactive input
or an existing saved brief on `new`.

The answers live in `project/brief.json`, using the `Brief` dataclass in
`myzing.brief.models`. Writes flush a temporary sibling file and atomically replace
the destination under the existing project lock. A failed write leaves the last
complete brief intact. Repeating `zing brief new ./project` reuses it without
reading stdin or rewriting the file. Use `--restart` to answer again. Inventory
rescans leave the brief untouched, including when the project and clips folders
are the same. Moving a project with its internal media preserves relative paths.

## Read the recommendation

Recommendations use current inventory status and saved probe data. Changed files
awaiting a scan are excluded from usable-duration and orientation totals. The
output separates a suggested rough cut from its basis and missing evidence.
Duration totals do not prove the footage contains usable or distinct moments.
Orientation alone does not prove a safe crop. Nothing calls a model or downloads
media, and this pass does not select or render an edit.

A later study/match pass can attach `reference.study` to `project.json` as
`{"breakdown_path":"reference/breakdown.json"}` (relative to the project), or
`{"breakdown": <Breakdown.to_dict()>}`. A direct version 1 Breakdown object is
also accepted. If a wrapper has `state`, it must be `done`. The brief flow reads
this attachment; it never starts a study or searches unrelated workspace studies.
Missing, invalid or unfinished studies are reported as gaps. Valid studies supply
median shot duration and coarse OCR caption observations with reported confidence
and study warnings. They cannot establish an exact font, animation, or preset.

Over MCP, call `brief_questions` for the same prompts, defaults, and JSON examples.
Call `brief_save(project="/local/project", answers={...})` to validate and save a
complete replacement brief. Both follow the `{ok, ...}` / `{ok: false, error}`
envelope. `brief_save` returns the saved answers, local path, and recommendation.
Your AI can reason over those facts; Zing does not invent that judgment.
