# Start with `zing studio`

## Your first draft in 10 minutes

Try this after [installation](INSTALL.md) and a successful FFmpeg check in
`zing doctor`. Ten minutes is a walkthrough budget, not a measured guarantee
for your computer. Package installation and model downloads take extra time.
This sample uses generated video with no speech, so it needs no model download
or personal media. The commands below use PowerShell from a source checkout.

Create three clips with test shapes and color bars. Separate clips give the
planner enough choices for three distinct edits:

```powershell
New-Item -ItemType Directory -Force zing-workspace/first-draft/clips | Out-Null
ffmpeg -hide_banner -loglevel error -n -f lavfi -i "testsrc2=size=640x360:rate=30:duration=12" -c:v libx264 -pix_fmt yuv420p zing-workspace/first-draft/clips/shapes.mp4
ffmpeg -hide_banner -loglevel error -n -f lavfi -i "smptebars=size=640x360:rate=30:duration=12" -c:v libx264 -pix_fmt yuv420p zing-workspace/first-draft/clips/bars.mp4
ffmpeg -hide_banner -loglevel error -n -f lavfi -i "testsrc=size=640x360:rate=30:duration=12" -c:v libx264 -pix_fmt yuv420p zing-workspace/first-draft/clips/grid.mp4
uv run --frozen zing studio
```

Use a fresh folder on reruns; `-n` refuses to overwrite the generated input.
For macOS/Linux, create the folder in your file browser and use the same FFmpeg
and uv commands in Terminal. Those shell variants were checked by docs only
for REL2; the Windows flow was run locally.

Answer the interview:

1. Choose **2**, edit clips without a reference.
2. For clips, paste `zing-workspace/first-draft/clips`.
3. Choose **general** footage.
4. For the topic, enter **A first test with moving shapes**.
5. Choose **YouTube** for landscape delivery.
6. Set the length to **6** seconds.
7. Choose **natural** for tone.
8. Choose **none** for captions and **none** for added music.
9. Read the plan, check that downloads says **none**, then type **yes**.

The finish screen lists the draft paths and a recommendation with its reason.
Open a listed MP4 in your video player. These test shapes are only a rendering
check; there is no reference style or speech to match. Use the displayed output
folder to find the saved plan, reports and `studio-result.json`. Missing
measurements and failed drafts remain visible.

Next, start a new Studio session with your own clips and choose **1** to use a
reference video. Speech clips add one model question: choose a cached model,
skip speech, or explicitly choose a download option. Enter never authorizes a
model download. Review names, caption timing and framing before sharing a draft.
For help, see [Troubleshooting](TROUBLESHOOTING.md) and [Privacy](PRIVACY.md).

```powershell
uv sync --all-extras
uv run --frozen zing studio
```

Caption and delivery preferences can be supplied before the interview:

```powershell
zing studio --caption-mode box --short-side 720 --picture-crop auto --target-mb 2
```

The confirmation plan shows these choices. Saved studio answers accept
`caption_options`, `caption_mode`, `picture_crop`, `target_mb`, and
`video_bitrate_kbps`, and `short_side` (`auto` or a multiple of 18, such as 720);
the size and bitrate fields are mutually exclusive. `zing brief new` also accepts
`--short-side`, and brief/MCP answers accept the same `short_side` field.
They apply to edited drafts and re-deliveries of existing plans. A flattened
video still needs timed caption events to add word backgrounds. Choose phone
captions for the [documented size floor](CAPTIONS.md); existing captions cannot
be extracted or resized from flattened pixels by this option.

The target applies to each delivered file. Encoding receipts beside the MP4s
report achieved size and encoder quality risk. The framing evidence records
whether static broadcast chrome was removed. These are local operations;
they require no Uoink connection, upload, or new model download.

## Use reference 0:30 to 1:20

Studio probes the reference before its preview or study. A reference over 60
seconds needs a selected range of at most 60 seconds for matching. The interview
asks which part to use for a long or unknown-duration reference (including URLs
and failed probes). A local reference of 60 seconds or less uses `all`, records
that answer, and displays a short note without asking. Explicit trim flags or
MCP fields still take precedence. When a long local reference needs a trim,
the selected interval also supplies the default edit length, rounded to whole
seconds within 1–60; an explicit `length` answer overrides it. This keeps the
reference interview within ten questions, including speech setup.

For a URL, range and download consent share a question: enter `yes 0:30-1:20`,
`yes all`, or `no`. A requested interval over 60 seconds is rejected even when
the source duration is unknown. A bounded interval supplies the default edit
length; `all` with unknown duration uses a disclosed 15-second target. The
downloaded reference still has to pass the duration check before study.

Local metadata is cached by resolved path, size and modification time within
the terminal interview. Failed or timed-out probes leave duration unknown.
Going back removes an automatically recorded `all`, but preserves an explicit
CLI or MCP range, including after resume.

For screen footage, Studio uses `cursor_log: "none"` with a note when the project
contains no JSONL log. Supply a log path in answers to override it. Screen demos
keep source audio; their planner does not apply added music. Custom delivery
shapes can be entered in the destination answer, for example `16:9,1:1`.

These PowerShell examples select the same 50-second interval. Replace
`reference.mp4` and `clips` with your local paths. The Studio command continues
the interview; Match uses default brief answers. Replace `--answers '{}'` with
`--brief brief.json` to use a saved brief.

```powershell
$env:UOINK_URL='http://127.0.0.1:1'
zing studio --ref-start 0:30 --ref-end 1:20
$env:UOINK_URL='http://127.0.0.1:1'
zing match reference.mp4 --clips clips --out zing-workspace/match-range --answers '{}' --ref-start 0:30 --ref-end 1:20
$env:UOINK_URL='http://127.0.0.1:1'
zing explain reference.mp4 --out zing-workspace/explain-range --ref-start 0:30 --ref-end 1:20
$env:UOINK_URL='http://127.0.0.1:1'
zing study reference.mp4 --workspace zing-workspace/study-range --reference-range 0:30-1:20
```

All four commands accept seconds (`30`, `80`) or `mm:ss`. Use either
`--ref-start/--ref-end` or `--reference-range`, not both. MCP `study_video`, `study_uoink_item`,
`match_start`, and `zing_explain` accept `ref_start`, `ref_end`, and
`reference_range`; Studio accepts those keys in its answers.

For an HTTP reference, Match downloads the source, then probes and checks the
selected duration before normalization or study. A long untrimmed URL is refused
at that point. General-purpose Study can analyze longer footage; Explain and
its Studio fallback cap analysis at 60 seconds. Analysis budgets have separate
cache identities, so a bounded study cannot replace the full study's media.

Ranges include the start and exclude the end. CFR boundaries snap forward to
the next source frame; the breakdown's `provenance.reference_range` records
requested times, selected frame indices, effective times, frame rate and hashes.
Only the selected interval is encoded. VFR selections use source time and record
their conversion to CFR. Audio is encoded with the selected interval; source
files are unchanged.

Explain analyzes at most the first 60 seconds of the selected interval and uses
a maximum image side of 960 pixels. Its card records this budget and identifies
unmeasured footage. `--against` applies the reference range to the first video;
the comparison video has its own 60-second analysis budget. Caption geometry
keeps at most 256 sampled frames, 16 detections per frame, 128 tracks, 64 samples
per track and 512 gap examples, with total and omitted counts. Font comparison
uses at most 16 tracks, three samples per track and two lines per sample. Text
between sampled frames remains unknown. A fractional-rate selection may end
within one frame after its requested endpoint; its source frame choices are
recorded explicitly.

## One usable moment can make a draft

Studio can deliver one or two drafts when the footage cannot support three
distinct edits. It reports a **VARIETY limit**, keeps the usable drafts and names
the missing choices. Another opening or a different visual moment can add
variety; shortening a complete moment is not required just to fill three slots.
The `box` caption mode and its active-word plate apply to brief-only drafts,
reference matches and captioned plan re-deliveries.

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
`b` goes back and `q` saves. Menus use numbers. At the opening menu a and c-f
also pick their rows, but `b` always means back, so type 2 for clips without a
reference. Dragged paths may keep the quotes Windows Explorer, Windows Terminal
or GNOME Terminal add, or macOS Terminal's backslash-escaped spaces.

A local reference match takes eight creative questions, plus speech setup for audio clips plus confirmation: reference,
clips, topic, destination, length, captions and music after the opening choice.
The reference supplies the pacing default. The output folder defaults to a fresh
`ZING_HOME/studio[-N]` (`~/.zing/studio[-N]` when unset), claimed as the session
starts so each terminal gets its own. Starting Studio does not write into the
current directory. Change it with `o` on the plan screen; a folder
that would overwrite or equal an input is refused and the old one is kept. A
style breakdown (option 4) moves the default out of the video's folder, because
Explain writes its cards outside it. Use `t` on the plan screen to change an
edit's tone. Destination determines shape; type a shape list in that question
to choose a custom set without another question.

Studio probes local inputs and reads a local reference before style questions.
Still images in a clip folder are skipped with a count; option 3 uses photos.
For speechless clips, planning uses measured shots. If pacing candidates cannot
fill the requested length, the last speechless shot can be shortened to finish
the edit. Any difference from reference timing remains in the comparison.
The preview has an eight-second deadline, samples at most the first 20 seconds
at reduced resolution, and checks three text frames with locally installed OCR.
It reuses the study cut detector and audio measurements. It reports speech,
likely music and sampled text separately; unavailable measurements stay unknown.
The full reference summary appears once; each question gives a reason specific
to its choice. The shape is the displayed one, so a rotated phone video counts
as portrait; uncommon shapes are named by their pixels. A reference with no video
stream, or one FFprobe cannot read, is refused at its question instead of after
confirmation. A reference longer than 60 seconds recommends 60, the studio maximum.
Path 4 uses Explain for the full style card after confirmation.
Remote and saved references are resolved by match after confirmation, so their
interview style evidence remains unknown.

Production studies, renders and downloads wait for plan confirmation. The plan
lists steps, shapes, downloads and output folder. Runtime is unknown until
measured on the machine; source duration is not an encoding-speed benchmark.
Clips with speech need timed words from a local speech model. Paths a/b ask
about speech before the plan when clips have audio:

- `small.en` (~486 MB): recommended for a faster first English draft. Names,
  accents and quiet speech can be less accurate; review spelling and timing.
- `large-v2` (~3.09 GB): slower, multilingual, with better speech accuracy.
  It remains the default for `zing study`.
- `skip` (0 MB): spoken captions and whole-line continuity are unavailable.
  Clips without validated words or measured silence may be excluded, so this
  choice can finish with a shortage instead of drafts.

Enter selects the recommendation, preferring your configured cached model.
An uncached model then needs an explicit **yes** to download. Enter declines;
`b` changes the choice and `q` saves. Confirming the plan is a separate step.
The download runs after plan confirmation, reports byte progress, and verifies
every file against a pinned revision and SHA-256. Files are stored under
`ZING_HOME/models/speech`; partial or corrupt files are never accepted as a model.
The finish screen and `studio-result.json` report the model, bytes downloaded,
verification and cache path. Existing complete local model directories and Hugging
Face snapshots remain usable offline; their native loading is not preflighted.
See [doctor and setup](DOCTOR.md) for the same download outside Studio.

## A real photo session

This is the terminal output of an October 23, 2026 run on Windows, unedited
except that answers are shown after `>` (an empty `>` is Enter) and the output
folder is shortened to `<cwd>`. The three photos are frames from SHA-verified V1
clips (Korky Paul, Tears of Steel and NASA), with no downloads.

```text
What are we making?
  1. Edit my clips to look like a reference video
  2. Edit my clips (no reference): pick a style from the brief
  3. A meme or still from photos plus a topic
  4. Break down a video's style
  5. Check music for an edit
  6. Re-deliver an existing edit or plan
Recommended: 1 (Edit my clips to look like a reference video)
Choose a reference match if you have a video to aim for; your intent is still unknown.
Enter accepts | ? explains | q saves and quits
> 3

Which folder holds your photos?
? explains | b goes back | q saves and quits
> photos

What's the meme or still topic?
? explains | b goes back | q saves and quits
> when the build finally passes

Where will this go?
  1. TikTok / Reels (9:16)
  2. YouTube (16:9)
  3. Feed (1:1)
  4. All three shapes
  5. Keep source / reference shape
  6. Custom shapes
Recommended: 3 (Feed (1:1))
3 photos measured; square is a starting layout choice. Your publishing destination is unknown.
Enter accepts | ? explains | b goes back | q saves and quits
>

Plan: A meme or still from photos plus a topic
Shapes: 1:1
  1. Measure photos and create six concepts per shape
  2. Render contact sheets
  3. Export the highest readability-scored concept per shape
Estimated steps: 3. Time: Runtime is unknown on this machine; studies and renders depend on source duration, models and hardware.
Downloads: none
Output folder: <ZING_HOME>\studio
Note: Readability scores do not judge the joke. Face coverage is sampled or unknown; review the contact sheet.

Run this plan? Recommended: yes.
Enter=yes | o changes output folder | ? explains | b goes back | q saves and quits
>
Working: Starting A meme or still from photos plus a topic
Working: Measure photos and render six 1:1 concepts
Working: Export the selected 1:1 still (highest readability score; humor needs your review)

Studio: ready
Finished still (1:1): stills-vj2psxlg\1x1\finished-still-57812695cd9c8fda.png
Contact sheet (1:1): stills-vj2psxlg\1x1\contact-sheet.png
Note: Some photos need a blurred background to keep faces and subjects inside the frame.
Note: Readability scores help with layout; you still need to judge the joke.
Output folder: <ZING_HOME>\studio
Full result: <ZING_HOME>\studio\studio-result.json
Next: Open the contact sheet and check the joke and text placement.
Next: Pick another concept with zing still pick <folder> --id <id>.
Next: Try a more specific topic in a fresh studio session.
```

Four questions plus confirmation. The scripted run took 2.172 seconds; that is
a local timing, not a speed promise. The two similar face/subject crop warnings
appear as one note; both source observations remain in the result.

For edits, the finish screen shows a drafts-by-shapes table with playable paths
relative to the output folder. Status distinguishes rendered output, measured
style misses and unverified matches. One recommendation ranks completed drafts
by fewest measured misses, then most passing checks; ties are stated. Drafts
inside the reference timing come first: an alternative outside it is labeled
`C: alternative outside the reference timing: <reason>`, never counts as a pass,
and is recommended only when nothing else rendered. It does not infer artistic
quality from that ranking. At most five merged notes appear,
followed by the output folder, full result path and an exact draft-choice command.
Notes never show producer IDs or field names. A shortage names its blocker: clips
excluded for missing speech timing are not reported as too little footage. A
finished edit whose remaining warnings are measurement disclaimers shows their
count instead. Cancelled, failed and shortage results point at
`zing studio --resume`; Ctrl+C during a reference match saves and prints it.
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
  "music": "original",
  "speech_model": "small.en",
  "speech_download": true
}
```

For audio clips, `--answers` and `--json` require a speech choice. The combined
`speech_setup` question accepts `skip`, a cached model name, or an explicit
`download small.en` / `download large-v2` choice. It expands into `speech_model`
and, for downloads, `speech_download: true`. Existing separate fields also work.
Use `speech_download: true` only after approving that model's download; it must
be a JSON boolean. `--yes` confirms the plan and grants no download consent.
For `speech_model: "skip"` or a cached model, omit `speech_download`. A supplied
uncached model needs the same consent even when no clip has audio: Studio still
uses it for the run's studies, such as the reference's speech.

Paths in an answers file resolve from the working directory. Saved answers use
absolute paths. Moving source media requires updating those answers. `aspects`
also accepts `all` or a comma-separated string. `music` accepts `original`,
`none`, or an array of local tracks; `none` means no added music, not removal of
embedded audio. Optional `draft: "B"` records a local choice through the existing
choice API after a completed draft is available. Nothing is shared to Uoink.

Other paths use these fields after `path`. The project defaults automatically;
custom shapes are entered in the destination question, and `aspects` remains
accepted in JSON:

| Path | Answer fields |
|---|---|
| b | `clips`, `topic`, `platform`, `aspects`, `length`, `tone`, `captions`, `music`; with audio, `speech_model` and consent if uncached |
| c | `photos`, `topic`, `platform`, `aspects` |
| d | `source` (local video) |
| e | `tracks` (array), `context` (composition plan JSON or `none`); with `none`, also `length` and boolean `speech` |
| f | `source` (video, v1 EDL or v2 composition JSON), `platform`, `aspects` |

A URL containing a username or password is refused with a credential-specific
message. Download it yourself or remove the credentials.

`q`, EOF and Ctrl+C save the interview. An orphaned MCP job updates both its job
record and saved session to `interrupted` on status, cancel or resume, with a
resume command. Cancellation reports "Studio run cancelled." Reference matches retain the existing
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
  the renderer's default font and a [picture-relative size floor](CAPTIONS.md).
  Safe placement may shrink them only to that floor; otherwise shorten the
  phrase or change framing. Review the delivery at phone size. Missing or
  invalid speech can block captions or planning. `none` disables new captions
  for studio edits. Neither choice erases text already baked into source media.
- Re-delivering a plan rebuilds framing and caption placement from its sources.
  A flattened video retains its baked-in captions, cuts, color and mix; those
  elements cannot be edited separately. Each delivery is decoded for validation.
  The crop planner merges sub-microsecond duplicate track times before limiting
  movement, keeps a zero-length shot's single keyframe, and shrinks a clamped
  step only when rounding would break the speed bound, so motion that already
  validated is unchanged. If a motion-bound rejection still occurs, Studio
  retries full-picture blurfill and records that fallback in the delivery report.
- Style breakdown lazily calls `myzing.explain.api.explain_video(source,
  out_dir, transitions=True, offline=True)` and displays its summary and three
  card paths. Missing optional measurements remain unknown. If the module cannot
  load, the small `studio.adapters.explain_video` seam runs existing study + inspect and
  explicitly labels the fallback. It does not claim an original font or LUT.
- Photo concepts use the existing formula engine and readability score, not
  semantic image recognition or a prediction that a joke will land.

URL references are recognized from the URL and need explicit
`allow_download: true`; `--yes` cannot supply that consent. Speech-model consent
is separate; media studies remain offline after setup.
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
Without a `project` answer, agent sessions default to `studio[-N]` inside the
Zing workspace (`ZING_HOME`, else `~/.zing`), never the MCP server's working
directory, which clients often set to a system folder.

After confirmation, follow the plan's `execution` metadata. Paths a, b, d and f
use `zing_studio_run(answers=..., confirmed=true)`. `confirmed` must be a real JSON
boolean: strings and numbers are refused. Model downloads also need the explicit
`speech_model` answer and `speech_download: true`, or an explicit combined
`speech_setup` download choice; plan confirmation alone never authorizes them.
The worker delegates reference edits to the existing match API.
Paths c/e reuse `still_concepts` / `still_render` and `music_check`.

Poll with `zing_studio_run(project=...)`; `cancel=true` stops an owned job. The
runner uses the existing process-tree supervisor. Both studio tools return paths
and metadata, never media bytes.

Studio keeps every successful shape when another shape fails. Its final status
is `partial`, with each failed shape's `error` and `next_step` beside the saved
plans and successful videos. The CLI exits 2 for a partial delivery (0 for ready,
1 for failed); inspect the JSON status to distinguish it from an unfinished
interview. MCP polling retains the same status, paths and remedies, with
`ok: false` for partial or failed runs. Full decode must pass before a Studio
delivery counts as ready. Failed MP4s are renamed with a `.failed` suffix;
their diagnostic paths appear as `failed_artifact`, outside the playable outputs.
Screen deliveries preserve their actual status in the creator summary.

Type a shape list such as `16:9,1:1` in the publishing question to customize
the delivery set. The legacy answer `custom` by itself uses the default shape
without asking another question. Explicit saved `aspects` remain honored.

On the reference route, accepting the default length uses the footage available
after silence and exclusion trims. An explicit number remains a fixed target
and can produce a length shortage. Answers files and agents can request the
default with `length_mode: "usable"`; `length` then remains the provisional
pre-study value. The saved plans and result report the measured usable target.
A shortage of distinct drafts is reported as VARIETY, separately from length.
Silence inside a protected clause stays when it falls wholly between words;
trimming that pause would make the complete clause unavailable. Silence that
conflicts with word timings is still excluded. The default length and the
candidate search use the same exclusions.

For local footage that must stay in place, set `ZING_LOCAL_MEDIA_IN_PLACE=1`
before the CLI command. Study reads the original path, records that it made no
copy, and saves analysis artifacts in the chosen workspace. It refuses trim
extraction and sources requiring normalization. The default staging behavior is
unchanged when this variable is absent. Keep the original available when using
the saved plan or breakdown.
