# Screen demos

Record cursor telemetry beside your screen recorder, then make a continuous edit:

```powershell
$env:UOINK_URL='http://127.0.0.1:1'
zing record-cursor --out session.jsonl --duration 30
zing plan screen demo.mp4 --cursor session.jsonl --out screen.json
zing render screen.json --aspect all --short-side 720 -o demo-edited.mp4
```

Start the video on the printed **GO**. If GO appears 1.2 seconds into the video,
pass `--cursor-offset 1.2`. Negative offsets work when the log starts first.
`--sync-creation-time` instead compares the log's UTC start with video
`creation_time`. Some recorders write finalization time there: check the visible
action before trusting that alignment. There is no flash overlay in the recorder.

Windows uses stdlib `ctypes`, physical desktop coordinates and 60 Hz polling.
For a window or monitor recording, supply `--region x,y,width,height` in desktop
coordinates. The default covers the virtual desktop. Positions outside the
region are omitted. Match the region to the video; Zing cannot infer its origin.
On macOS, install `myzing[screen]` and allow Input Monitoring for the terminal.
The default is the main display; Quartz coordinates are display points, which
normalize independently of Retina scaling. Linux/Wayland recording is unsupported.
Planning and rendering existing recordings work on all supported FFmpeg platforms.

Ctrl+C or `--duration` closes the log with a stop marker. An interrupted file
without that marker remains usable, with a warning. Polling can miss presses
shorter than 1/60 second and does not reconstruct keyboard auto-repeat.

## Privacy and format

The recorder writes only the local file you name. It makes no network requests.
It stores cursor positions, mouse buttons, and **only that a key was pressed**.
It never stores key codes, key names, typed text, clipboard contents, active app
names or window titles. The platform sampler briefly keeps key state in memory
to detect a new press; only a boolean crosses into the logger. Input timing and
cursor coordinates can still reveal interaction patterns. Delete the log when
you no longer need it. Recording does not modify the video or your screen recorder.

The UTF-8 JSONL contract is version 1, seconds from GO, normalized coordinates:

```jsonl
{"type":"start","version":1,"t":0,"wall_time":"2026-10-24T12:00:00+00:00","hz":60,"bounds":[0,0,1920,1080],"coordinates":"normalized-capture-region","sync":"GO is t=0"}
{"type":"cursor","t":0.016667,"x":0.4,"y":0.5}
{"type":"click","t":0.1,"x":0.4,"y":0.5,"button":"left"}
{"type":"key","t":0.2}
{"type":"stop","t":30,"samples":1800}
```

Only `left`, `right` and `middle` mouse buttons are accepted. The reader rejects
extra fields, including key contents. It does not silently import another
recorder's potentially sensitive format. External logs need an explicit conversion.

## Planning and captions

Omit `--cursor` to use frame-difference UI activity. This is lower-confidence
evidence (0.45), not recovered cursor positions or recognized text. Telemetry
dwells score 0.75; clicks score 0.95. These are editorial weights, not calibrated
probabilities. Each zoom stores its evidence and confidence in the plan.

Each zoom also stores a normalized `box` and `box_evidence`. A small local pixel
probe looks for the enclosing flat-color panel or control at the focus position,
sampling the start, action and end of the scene. The union protects a widget
that expands after a click. If no enclosing region is found, activity scenes
use their changed-area rectangle; otherwise the camera shows the whole source.
These are visual bounds, not recovered DOM elements. Gradients, overlays and
unbordered controls can defeat this heuristic; inspect the saved boxes.

The camera fits the whole region with a 6% margin on each side. It zooms out
when necessary and pads outside the source at frame edges. Nearby regions share
a containing view. A move over 40% of the normalized frame, or one estimated
to take over 0.6 seconds under the motion limits, becomes a cut at a click,
activity event or nearby idle end. The previous view holds until that frame,
so no frames travel through the empty space between targets. Each shot has
a gentle, contained 0.6-second push-in with a smooth start and stop.

Portrait pictures follow the target's aspect: tall elements use up to 90% of
the delivery height without captions, or 58% with a reserved lower caption band.
Wide elements retain their full width and proportions; they cannot fill a tall
frame without clipping or stretching. Oversampled 4:4:4 crop plus `zoompan`
smooths source-pixel rounding. The work directory contains the region boxes,
picture rectangles, camera keys, action-timed cuts, time map and FFmpeg graph.
Balanced expressions and `filter_script_args` support FFmpeg 6, 8 and 9 syntax.
Older version-1 plans without boxes get a region probe at render time.

`freezedetect` supplies idle evidence. The default speeds safe idle interiors
to 4x, with reading handles and protection around clicks, key presses and supplied
speech. Use `--idle-speed 1` to retain timing. Audio recordings without word
timings stay at normal speed because a still screen can contain narration.
Static UI is not proof the viewer has finished reading; review the shortened edit.

`--max-zoom` defaults to 1.8; source enlargement stays below 2.5x. Whole-region
coverage takes priority over magnification. If the element cannot fit at the
phone text floor, the view zooms out and reports the legibility tradeoff.
`--ui-text-px` is the source UI's estimated em size (default 24), not an OCR
measurement. The planner compares it to DOGFOOD1/CAPTION2's phone floor. A floor
sets a *minimum* readable text size; a zoom cap limits enlargement and loss of
context. When both cannot be met, the plan says to record larger UI text. It
does not claim unreadable source text has been repaired.

Supply `--words words.json` for captions, using source-time
`[{"text":"Build","start":1,"end":1.5}]`. Words come from an explicit transcript,
never the key log. `--caption-preset clean|punch|box|none` uses the CAPTION2 fonts,
grouping and renderer. Captions use the lower band, with the entire picture
protected from overlap. If no rail fits, rendering stops with an instruction to shorten the
phrases. `--click-highlights` adds short yellow outlines at recorded clicks.

`zing match screen --clips <folder> --out <folder> --cursor session.jsonl --aspect all`
uses the same planner and renderer. One log requires one recording; without a
log, each video gets its own activity plan. Studio paths a/b ask whether the
footage is screen recordings, then ask for an optional log and recommend this
route. Saved briefs already past the topic question retain their general-footage
route unless `footage_kind` is explicitly set to `screen`. Screen mode preserves
each demo's continuity instead of producing three hard-cut drafts. Reference pace,
requested duration and added music beds are not imposed; source audio is retained.

## Sources and adaptations

- [OpenScreen](https://github.com/siddharthvaddem/openscreen/blob/ca8104c279da0d4b4481ec992ff103949e22c772/src/components/video-editor/timeline/zoomSuggestionUtils.ts),
  MIT, copyright 2025 Siddharth Vaddem. Ported 450–2600 ms dwell runs, 0.02 movement
  threshold, duration ranking and 1800 ms spacing. Zing also breaks telemetry
  gaps over 100 ms and filters candidates against idle evidence.
- [Screenize](https://github.com/syi0808/screenize/blob/027be96bbf2d855698bc67f1536ac8cef48cc3e4/Screenize/Generators/SegmentCamera/SegmentPlanner.swift),
  Apache-2.0. Adapted scene merging (distance <0.05, gap <0.5 s), transition/hold
  structure and minimum holds. Its ContinuousCamera informed the original
  spring/dead-zone design. The revised whole-region camera uses stable containing
  views, eased push-ins and action-timed cuts for distant targets. This is not
  the full Swift planner.
- [screenstudio-alt-skill](https://github.com/connerkward/screenstudio-alt-skill/blob/61a0b303ce3a73d103398fee7ecb5fa31f8a0994/src/polish.py),
  MIT, copyright 2026 Conner K Ward. Adapted the local event-log and FFmpeg
  `freezedetect` idle-compression approach. The privacy-filtered JSONL schema is
  Zing's own, not a drop-in import of that tool's key-bearing events.

Full licenses are in `docs/licenses/screen-*.txt`. PyObjC is MIT, optional and
macOS-only; core Zing remains stdlib-only. No model or external media is downloaded.

The full license texts and modification notice also ship in the installed package at `myzing/_data/docs/SCREEN-LICENSES.md`. Plans accept recordings up to one hour.
