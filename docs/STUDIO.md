# Start with `zing studio`

```powershell
uv sync --all-extras
uv run --frozen zing studio
```

FFmpeg and ffprobe must be on PATH for video work. The interview itself uses
plain stdin/stdout and the Python standard library; media work uses Zing's
existing optional extras. It works in PowerShell and macOS/Linux shells.

Choose what you want to make:

1. Edit clips to look like a reference video.
2. Edit clips with a style chosen from your brief.
3. Make a meme or still from photos and a topic.
4. Break down a video's style.
5. Check music for an edit.
6. Re-deliver a video or plan in landscape, square or portrait.

Each question includes a recommended answer, its reason and available evidence.
Enter accepts it, `?` shows evidence, `b` goes back and `q` saves and quits. At the
opening menu, `b` selects the second path; use numbers if you prefer. Required
paths and topics have no invented default: an empty answer asks again.

Studio probes local inputs while asking questions. It does not start studies,
rendering or downloads until you review and confirm a plan. The plan lists
steps, shapes, downloads and the output folder. Cold-run time is explicitly
unknown; a source duration is not an encoding-speed benchmark.

## A real photo session

This excerpt is from the STUDIO1 acceptance run on October 22, 2026. It used
three frames extracted from SHA-verified V1 clips (Korky Paul, Tears of Steel
and NASA), without downloads. Answers are shown after `>`; the long project
prefix is shortened below to `zing-workspace/studio1-real`. The full terminal
capture is saved locally under that folder as `c-transcript.txt`.

```text
What are we making?
  1. a. Edit my clips to look like a reference video
  2. b. Edit my clips (no reference): pick a style from the brief
  3. c. A meme or still from photos plus a topic
  4. d. Break down a video's style
  5. e. Check music for an edit
  6. f. Re-deliver an existing edit or plan
> c

Where should I save this session and its outputs?
> zing-workspace/studio1-real/memes

Which folder holds your photos?
> zing-workspace/studio1-real/photos

What's the meme or still topic?
> when the build finally passes

Where will this go?
Recommended: square
> square

Which shapes? (16:9, 1:1, 9:16 or all)
Recommended: 1:1
This follows your destination and measured orientation where available; auto framing checks crops before delivery.
> [Enter]

Plan: A meme or still from photos plus a topic
Shapes: 1:1
  1. Measure photos and create six concepts per shape
  2. Render contact sheets
  3. Export the highest readability-scored concept per shape
Downloads: none
Output folder: zing-workspace/studio1-real/memes
Note: Readability scores do not judge the joke. Face coverage is sampled or unknown; review the contact sheet.

Run this plan? Recommended: yes.
> yes
Working: Measure photos and render six 1:1 concepts
Working: Export still-57812695cd9c8fda (highest readability score; humor needs your review)
Studio: ready
```

The run wrote `index.json`, `contact-sheet.png`, `meme-writer.md` and
`finished-still-57812695cd9c8fda.png` under `memes/stills-hhyxg5ot/1x1/`.
Six questions plus confirmation took 1.86 seconds with scripted stdin; the first
complete contact sheet was available at 1.61 seconds. These are local timings,
not a general speed promise. The result named two crops that would lose face or
subject evidence and used the existing still renderer's blurred background.

## Save, resume and automate

Answers and question history live in `<project>/studio-session.json`. It is a
version 1 `Session` record with `to_dict()` / `from_dict()`, written atomically.
The result is also saved as `studio-result.json` when production completes.

```powershell
zing studio --resume ./zing-workspace/my-project
zing studio --answers ./answers.json --json
zing studio --answers ./answers.json --yes --json
```

`--answers` reads a JSON file, never stdin. Use the question IDs as keys. The
first invocation above prints the plan without executing it; `--yes` confirms
that plan. Missing answers return the next question and exit 2. Invalid answers
produce an error. `--json` writes JSON Lines events (`question`, `plan`,
`confirmation_required`, `progress`, `result`, `paused` or `blocked`) to stdout.
It never mixes prose into those lines. A result can be partial or a shortage;
only `ok: true` means the requested production finished.

Example `answers.json` for a reference match:

```json
{
  "path": "a",
  "project": "./zing-workspace/my-project",
  "reference_kind": "file",
  "reference": "./reference.mp4",
  "clips": "./clips",
  "topic": "Introduce the workshop",
  "platform": "all",
  "aspects": ["16:9", "1:1", "9:16"],
  "length": 15,
  "tone": "natural",
  "captions": "phone",
  "music": "original"
}
```

Paths in an answers file resolve from the working directory. Saved answers use
absolute paths. Moving source media requires updating those answers. `aspects`
also accepts `all` or a comma-separated string. `music` accepts `original`,
`none`, or an array of local tracks; `none` means no added music, not removal of
embedded audio. Optional `draft: "B"` records a local choice through the existing
choice API after a completed draft is available. Nothing is shared to Uoink.

Other paths ask for these fields after `path` and `project`:

| Path | Answer fields |
|---|---|
| b | `clips`, `topic`, `platform`, `aspects`, `length`, `tone`, `captions`, `music` |
| c | `photos`, `topic`, `platform`, `aspects` |
| d | `source` (local video) |
| e | `tracks` (array), `context` (composition plan JSON or `none`); with `none`, also `length` and boolean `speech` |
| f | `source` (video, v1 EDL or v2 composition JSON), `platform`, `aspects` |

`q`, EOF and Ctrl+C save the interview. Reference matches retain the existing
hash-checked match checkpoints. Other interrupted operations retry into fresh
attempt folders, leaving earlier artifacts available for diagnosis. A finished
non-match session returns its saved result on resume after checking output hashes;
match resumes revalidate the pipeline checkpoints after confirmation. Use a new
project for a new edit.

## Evidence and limits

- Probes establish geometry, duration and audio-stream presence. They do not
  establish a talking head, safe crop, speech, rights or editorial quality.
- No-reference styles are disclosed search preferences: calm targets four-second
  shots, natural two seconds and energetic one second. Source studies, complete
  clauses and available footage still constrain the director. These are not
  measurements or recovered presets, and source color is unchanged.
- Reference matches use the existing match API. Three drafts in three shapes
  can produce nine videos. Reports keep render completion separate from style
  fidelity. Failed drafts, missing words, shortages and soft upscales are named.
- `phone` requests spoken captions in groups of up to four timed words, with
  a 60px starting size and the renderer's default font. Safe placement may
  shrink them; review the delivery at phone size. Missing or
  invalid speech can block captions or planning. `none` disables new captions
  for studio edits. Neither choice erases text already baked into source media.
- Re-delivering a plan rebuilds framing and caption placement from its sources.
  A flattened video retains its baked-in captions, cuts, color and mix; those
  elements cannot be edited separately. Each delivery is decoded for validation.
  If the existing auto crop planner rejects a motion-velocity bound, studio
  retries full-picture blurfill and records that fallback in the delivery report.
- Style breakdown lazily calls `myzing.explain.api.explain_video(source,
  out_dir, transitions=True, offline=True)`. If that module is unavailable, the
  small `studio.adapters.explain_video` seam runs existing study + inspect and
  explicitly labels the fallback. It does not claim an original font or LUT.
- Photo concepts use the existing formula engine and readability score, not
  semantic image recognition or a prediction that a joke will land.

URL references need `reference_kind: "url"` and explicit
`allow_download: true`; `--yes` cannot supply that consent. Models stay local.
Saved references appear only with a configured, reachable Uoink peer advertising
the existing search contract. `reference_query` searches through `uoink_bridge`
using `corpus.read/1` GET with `q` and `limit` only. A selected retained file is
hash-verified by match; an unavailable retained file never triggers URL fallback.

## Agents

Call `zing_studio(path, answers)` for the next question. Relay its prompt,
options, recommendation, reason and evidence; do not turn unknowns into claims.
Pass the answers back until it returns a plan. This tool is stateless: it does
not save a session or run production. It performs local read-only probes and
only the requested configured-peer search.

After confirmation, follow the plan's `execution` metadata. Paths a, c and e
reuse `match_start` / `match_status`, `still_concepts` / `still_render`, and
`music_check`. The optional `studio_options` argument to `match_start` carries
studio's caption and supplied-music choices; omit it for the previous behavior.
Paths b, d and f use `zing_studio_run(answers=..., confirmed=true)` because the
existing job tools do not cover those orchestrations. Poll with
`zing_studio_run(project=...)`; `cancel=true` stops an owned job. The runner uses
the existing process-tree supervisor. Both studio tools return paths and
metadata, never media bytes.
