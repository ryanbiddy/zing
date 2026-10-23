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

Recommendations include their reason and evidence. Enter accepts a recommendation;
required paths and topics ask plainly and repeat on an empty answer. `?` explains,
`b` goes back and `q` saves. Menus use numbers; a-f remain opening-menu aliases.

A local reference match takes eight questions plus confirmation: reference,
clips, topic, destination, length, captions and music after the opening choice.
The reference supplies the pacing default. The output folder defaults to a fresh
`zing-workspace/studio[-N]`; change it with `o` on the plan screen. Use `t` there
to change an edit's tone. Destination determines shape; only custom asks another
shape question.

Studio probes local inputs and reads a local reference before style questions.
The preview has an eight-second deadline, samples at most the first 20 seconds
at reduced resolution, and checks three text frames with locally installed OCR.
It reuses the study cut detector and audio measurements. It reports speech,
likely music and sampled text separately; unavailable measurements stay unknown.
The optional explain adapter runs within the same deadline when installed.
Remote and saved references are resolved by match after confirmation, so their
interview style evidence remains unknown.

Production studies, renders and downloads wait for plan confirmation. The plan
lists steps, shapes, downloads and output folder. Runtime is unknown until
measured on the machine; source duration is not an encoding-speed benchmark.

## A real photo session

This excerpt is from the October 22, 2026 acceptance run. Three photos came from
SHA-verified V1 clips (Korky Paul, Tears of Steel and NASA), with no downloads.
Answers are shown after `>`; paths below are shortened relative to
`zing-workspace/studio1-refined`. The full local capture is `c-transcript.txt`.

```text
What are we making?
  1. Edit my clips to look like a reference video
  2. Edit my clips (no reference): pick a style from the brief
  3. A meme or still from photos plus a topic
  4. Break down a video's style
  5. Check music for an edit
  6. Re-deliver an existing edit or plan
> 3

Which folder holds your photos?
> photos

What's the meme or still topic?
> when the build finally passes

Where will this go?
  1. TikTok / Reels (9:16)
  2. YouTube (16:9)
  3. Feed (1:1)
  4. All three shapes
  5. Keep source / reference shape
  6. Custom shapes
Recommended: square
> square

Plan: A meme or still from photos plus a topic
Shapes: 1:1
  1. Measure photos and create six concepts per shape
  2. Render contact sheets
  3. Export the highest readability-scored concept per shape
Downloads: none
Output folder: c/zing-workspace/studio-2
> yes

Studio: ready
Finished still (1:1): stills-rpst7pnc/1x1/finished-still-57812695cd9c8fda.png
Contact sheet (1:1): stills-rpst7pnc/1x1/contact-sheet.png
Note: Some photos need a blurred background to keep faces and subjects inside the frame.
Note: Readability scores help with layout; you still need to judge the joke.
Output folder: c/zing-workspace/studio-2
Full result: c/zing-workspace/studio-2/studio-result.json
```

Four questions plus confirmation replaced six questions plus confirmation.
The scripted run took 4.156 seconds, with its first contact sheet at 3.484 seconds.
These are local timings, not a speed promise. The two similar face/subject crop
warnings now appear as one note; both source observations remain in the result.

For edits, the finish screen shows a drafts-by-shapes table with playable paths
relative to the output folder. Status distinguishes rendered output, measured
style misses and unverified matches. One recommendation ranks completed drafts
by fewest measured misses, then most passing checks; ties are stated. It does
not infer artistic quality from that ranking. At most five merged notes appear,
followed by the output folder, full result path and an exact draft-choice command.
All deliveries, warnings and the creator summary remain in `studio-result.json`.

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

Other paths use these fields after `path`. The project defaults automatically;
`aspects` is asked only for a custom destination and remains accepted in JSON:

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
  The crop planner merges sub-microsecond duplicate track times before limiting
  movement. If a motion-bound rejection still occurs, Studio retries full-picture blurfill and records that fallback in the delivery report.
- Style breakdown lazily calls `myzing.explain.api.explain_video(source,
  out_dir, transitions=True, offline=True)`. If that module is unavailable, the
  small `studio.adapters.explain_video` seam runs existing study + inspect and
  explicitly labels the fallback. It does not claim an original font or LUT.
- Photo concepts use the existing formula engine and readability score, not
  semantic image recognition or a prediction that a joke will land.

URL references are recognized from the URL and need explicit
`allow_download: true`; `--yes` cannot supply that consent. Models stay local.
Saved references appear only with a configured, reachable Uoink peer advertising
the existing search contract. `reference_query` searches through `uoink_bridge`
using `corpus.read/1` GET with `q` and `limit` only. A selected retained file is
hash-verified by match; an unavailable retained file never triggers URL fallback.

## Agents

Call `zing_studio(path, answers)` for the next question. Relay its prompt,
options, recommendation, reason and evidence; do not turn unknowns into claims.
Pass the answers back until it returns a plan. This tool is stateless: it does
not save a session or run production. It performs local read-only probes,
a bounded local reference preview and only the requested configured-peer search.

After confirmation, follow the plan's `execution` metadata. Paths a, c and e
reuse `match_start` / `match_status`, `still_concepts` / `still_render`, and
`music_check`. The optional `studio_options` argument to `match_start` carries
studio's caption and supplied-music choices; omit it for the previous behavior.
Paths b, d and f use `zing_studio_run(answers=..., confirmed=true)` because the
existing job tools do not cover those orchestrations. Poll with
`zing_studio_run(project=...)`; `cancel=true` stops an owned job. The runner uses
the existing process-tree supervisor. Both studio tools return paths and
metadata, never media bytes.
