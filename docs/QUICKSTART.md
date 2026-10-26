# Make and review a local draft

This walkthrough uses generated media: a six-second moving test pattern and a
tone, a four-second edit with one cut, a color approximation, a caption placement
plan, a review PNG, and a meme. No footage or API key is needed. The captions are
authored labels, not a measured transcript. The sample has no real faces, so it
tests layout execution and platform masks, not face-detection recall.

Run the PowerShell blocks in order from the repository root, in the same shell.
Use a fresh output folder on each run. Commands were exercised on Windows with
Python 3.11.14 and FFmpeg 8.1.2 essentials; output excerpts below omit long paths
and repeated warnings. External tool installation and a new model download were
not exercised: this run used installed tools and a hash-verified cached YuNet.

## Install and choose a workspace

Have Python 3.11+, uv, and FFmpeg/ffprobe (including libx264 and libass) on PATH.
Use the current source checkout for these features. Zing is not on PyPI; an older
release wheel may have fewer commands. See [installation](DEVELOPER-GUIDE.md).
The sync command can download Python packages. Agents should get consent before
installing packages or fetching assets that the user has not already authorized.

```powershell
uv sync --all-extras
```

```powershell
$demo = Join-Path $PWD 'zing-workspace/quickstart'
if (Test-Path $demo) { throw 'Choose a fresh $demo directory before rerunning.' }
New-Item -ItemType Directory -Force "$demo/clips", "$demo/tmp" | Out-Null
$env:TEMP = $env:TMP = "$demo/tmp"
$env:ZING_HOME = "$demo/home"
$env:HF_HOME = "$demo/models"
$env:PYTHONIOENCODING = 'utf-8'
uv run --frozen zing doctor
```

Doctor's overall verdict can be ready while optional features are absent. For
this walkthrough, check Pillow, color, audio and the layout runtime. YuNet is
prepared separately below. Missing voiceover or HyperFrames does not block it.

## Generate the source and a warmer reference

`-n` makes FFmpeg refuse existing files. Keep outputs outside `clips` so a project
rescan does not mistake them for new source footage.

```powershell
ffmpeg -hide_banner -loglevel error -n -f lavfi -i "testsrc2=size=640x360:rate=30:duration=6" -f lavfi -i "sine=frequency=440:sample_rate=48000:duration=6" -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "$demo/clips/sample.mp4"
ffmpeg -hide_banner -loglevel error -n -i "$demo/clips/sample.mp4" -vf "colorbalance=rs=0.08:bs=-0.08,eq=saturation=0.85" -c:v libx264 -pix_fmt yuv420p -c:a copy "$demo/reference.mp4"
```

Both commands exit 0 without output. This is an authored reference transform;
matching its statistics does not recover an original creator's LUT.

## Inventory and save the brief

```powershell
uv run --frozen zing project init --reference "$demo/reference.mp4" --clips "$demo/clips" --out "$demo/project"
uv run --frozen zing project scan "$demo/project"
uv run --frozen zing project status "$demo/project" --json
```

Write UTF-8 without a BOM so these JSON files also work in Windows PowerShell
5.1. Import a complete brief file to avoid native-command JSON quoting differences.

```powershell
$utf8 = New-Object System.Text.UTF8Encoding($false)
$brief = @'
{"version":1,"purpose":"Review a generated test cut","audience":"Local reviewer","platform":"YouTube","aspect":"16:9","target_length_seconds":4,"must_keep":[],"forbidden":[],"caption_language":"none","exact_spellings":[],"music":{"source":"keep original audio","files":[]},"sfx":{"source":"none","files":[]},"reference_match":"pacing only"}
'@
[IO.File]::WriteAllText("$demo/brief-input.json", $brief, $utf8)
uv run --frozen zing brief new "$demo/project" --brief "$demo/brief-input.json"
```

The brief records intent. `zing plan drafts` and `zing match` use it to plan
edits; this walkthrough instead supplies its own EDL.
For a real reference, study and judge it with the
[agent workflow](../skills/zing/SKILL.md). This generated-media exercise authors
the edit directly, avoiding speech/OCR model downloads and invented transcripts.

## Render a four-second draft

Keep source seconds 0–2, then 4–6. The cut is at **output second 2**. Source paths
in this version 1 EDL resolve relative to the EDL file. These two captions are
deliberately authored titles; `word_timed: false` does not claim speech timing.

```powershell
$edl = @'
{
  "schema_version": 1, "width": 640, "height": 360, "fps": 30,
  "clips": [
    {"src":"clips/sample.mp4","src_in":0,"src_out":2,"timeline_start":0},
    {"src":"clips/sample.mp4","src_in":4,"src_out":6,"timeline_start":2}
  ],
  "captions": [
    {"text":"FIRST TAKE","start":0.2,"end":1.8,"position":"lower","word_timed":false},
    {"text":"SKIP AHEAD","start":2.2,"end":3.8,"position":"lower","word_timed":false}
  ]
}
'@
[IO.File]::WriteAllText("$demo/draft-edl.json", $edl, $utf8)
uv run --frozen zing render "$demo/draft-edl.json" -o "$demo/draft.mp4" --keep-work "$demo/render-work"
ffprobe -v error -select_streams v:0 -count_frames -show_entries stream=width,height,r_frame_rate,nb_read_frames,duration -of json "$demo/draft.mp4"
```

## Match and apply the color

```powershell
uv run --frozen zing color match --reference "$demo/reference.mp4" --clip "$demo/clips/sample.mp4" --out "$demo/look"
uv run --frozen zing color apply --lut "$demo/look/look.cube" --in "$demo/clips/sample.mp4" --out "$demo/graded.mp4"
```

Open the preview path returned by match: BEFORE, REFERENCE, AFTER. The recipe
names assumptions, confidence and warnings. This grades the source separately;
the draft above is still ungraded. To grade an edit, point a new EDL at the graded
source before adding captions. Color apply also grades any text already burned
into its input. Its 4:4:4 H.264 output may not play on every hardware player.

## Plan caption placement

With user consent, this command downloads the pinned MIT YuNet model when absent.
An existing cache is hash-verified. Our run reused the existing model; the network
download path is **not tested by this walkthrough**. See [model provenance and
license](THIRD-PARTY-NOTICES.md). A missing model must be fetched or supplied before
planning; there is no pretend face-safe fallback.

```powershell
uv run --frozen zing layout fetch-model --workspace "$env:ZING_HOME"
```

Use output-video seconds and box dimensions that include all visible text,
outlines and animation. Here the dimensions are authored for the demonstration.

```powershell
$events = @'
{"version":1,"events":[{"id":"title-1","start":0.2,"end":1.8,"width":0.55,"height":0.15,"preferred_anchor":"lower-third"},{"id":"title-2","start":2.2,"end":3.8,"width":0.55,"height":0.15,"preferred_anchor":"lower-third"}]}
'@
[IO.File]::WriteAllText("$demo/events.json", $events, $utf8)
uv run --frozen zing layout captions --video "$demo/draft.mp4" --events "$demo/events.json" --platform reels --out "$demo/layout-plan.json"
```

Open `layout-plan.contact.png` and read `events[].overlap.safe` in the JSON.
Safety is relative to sampled face tracks and approximate UI masks. No detected
face is not proof of no faces. This command does not change the rendered draft.
To render its layout, attach the result to a [Composition v2 caption](RENDER-V2.md)
and render that plan; this walkthrough uses a v1 EDL.

## Inspect the cut and audio

```powershell
uv run --frozen zing inspect timeline "$demo/draft.mp4" --edl "$demo/draft-edl.json" --around 2 --radius 0.5 --out "$demo/cut.png"
uv run --frozen zing audio analyze "$demo/draft.mp4" --json
ffmpeg -hide_banner -loglevel error -i "$demo/draft.mp4" -f null -
```

Open `cut.png`: the frame samples and amber planned cut share output time. Check
the outgoing frame against source second 2 and the incoming frame against source
second 4. The waveform helps locate discontinuities; playback is still needed to
judge the sound. Markers show EDL intent, not detected cuts. Phrase captions lack
word timings here, so inspection shows phrase intervals without inventing word
timings. The tone is
not music ground truth even if the audio heuristic labels it music.

## Make a still meme and an animated meme

```powershell
ffmpeg -hide_banner -loglevel error -n -ss 1 -i "$demo/clips/sample.mp4" -frames:v 1 "$demo/frame.png"
uv run --frozen zing meme check --text "ONE QUICK TEST" --text "TWELVE OUTPUT FILES"
uv run --frozen zing meme render --image "$demo/frame.png" --text "ONE QUICK TEST" --text "TWELVE OUTPUT FILES" --aspect 16:9 --out "$demo/meme.png" --offline
uv run --frozen zing meme render-video --image "$demo/frame.png" --text "ONE QUICK TEST" --text "TWELVE OUTPUT FILES" --at 0 --at 1 --zoom 0.09 --duration 3 --aspect 16:9 --out "$demo/meme-motion.mp4"
ffprobe -v error -select_streams v:0 -count_frames -show_entries stream=width,height,nb_read_frames,duration -of json "$demo/meme-motion.mp4"
```

`zing meme render-video` makes the three-second zooming MP4, with the punchline
appearing at 1 s. Inspect the still and
play the MP4 before sharing. Nothing in this walkthrough uploads either file.

## Recorded output

All 11 command blocks above exited 0 on 2026-10-21. The model-fetch command hit
the verified cache. These are trimmed excerpts from that run; `…` replaces the
absolute checkout prefix or omitted fields. Timings/IDs can differ on your run.
The cut PNG, layout contact sheet, color preview and still meme were opened for
visual review. The cut sheet showed source 1.8 s before the boundary and source
4.0 s at output 2.0 s. Both meme captions were legible. Audio playback was not
reviewed; decoding and loudness measurement are the audio checks recorded here.

Install and doctor:

```text
Resolved 87 packages in 1ms
Checked 73 packages in 147ms
Verdict: fully ready
  [ absent] tts (optional)
  [ absent] layout (optional)
  [ absent] hyperframes (optional)
```

Doctor ran before the cached model was placed in this demonstration workspace.
Project init and scan each returned:

```text
  1 ready, 0 missing, 0 changed, 0 unsupported
  reference: …\quickstart\reference.mp4 (recorded; study pending)
```

Brief:

```text
I'd start here: Start with a 4 s, 16:9 rough cut. Review the must-keep moments before choosing the opening.
  - No studied reference breakdown is attached; shot pace and caption style are unknown.
```

Render printed `…\quickstart\draft.mp4`; ffprobe reported:

```json
{"width":640,"height":360,"r_frame_rate":"30/1","duration":"4.000000","nb_read_frames":"120"}
```

Color match:

```text
Matched approximation: desaturated, strength 0.1625, confidence 0.20 (heuristic).
zing color: warning: Color metadata is incomplete; SDR Rec.709/sRGB is assumed. Untagged LOG cannot be ruled out.
zing color: warning: A correction reached its bound; review the input color space and lighting.
```

The test pattern also produced clipping warnings at all 12 sampled times. These
warnings are a reason to inspect the preview, not a failed command to hide.
Color apply printed `…\quickstart\graded.mp4`.

Model verification and layout (fields excerpted):

```json
{"sha256":"8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4","license":"MIT","verified":true}
```

```json
{"events":2,"tracks":0,"unsafe_events":[]}
```

```text
no_faces_detected: this is not evidence that the footage contains no faces
approximate_platform_masks: tune against the target device and publishing preview
```

Inspection:

```text
…\quickstart\cut.png (1600x562)
  Untimed caption text is shown as one phrase interval; no word timing was inferred.
```

Audio reported tempo `unknown`, null BPM, no beats, integrated loudness
**−21.8 LUFS**, and true peak **−19.1 dBTP**. Its role label was `music` at
confidence 0.6, with evidence “stable tonal energy; heuristic music candidate,
sustained voice also possible”. This generated tone demonstrates that limitation.
Full FFmpeg decoding of the draft exited 0 without errors.

Meme validation and render:

```text
valid: 2 beats, 33 characters
…\quickstart\meme.png (1200x675)
```

Animated meme probe (re-run on 2026-10-21 after `zing meme render-video` landed):

```text
meme-motion.mp4 (1200x676)
{"width": 1200, "height": 676, "duration": "3.000000", "nb_read_frames": "90"}
```

The sample does not exercise ASR/OCR study, automatic assembly, real-face recall,
URL acquisition, cloud calls or HyperFrames. It does exercise native still-to-MP4
animation. See the skill for the study/assemble workflow;
no transcript or face-detection accuracy claim follows from this synthetic demo.
