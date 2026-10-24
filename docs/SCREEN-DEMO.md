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

Ctrl+C after GO or `--duration` closes the log with a stop marker. Cancelling
the countdown removes the empty log and prints a cancellation message. An interrupted file
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

Each zoom stores a normalized `box` and `box_evidence`. A local pixel probe
finds the smallest clicked control with its label, or the changed area and the
complete text lines it touches. It samples action frames and once per second
through a hold. Flat-color components locate controls; contrast components
group glyphs into word and line bounds without recognizing their contents.
A large parent panel may extend beyond the crop. The focus content may not.
If bounds are unknown, the camera shows the whole source.

The camera fits the focus with a 6% margin. Crop edges sit in detected whitespace
so visible words stay complete. A small push-in is used only when every frame
keeps the focus and word bounds intact; otherwise the view holds still.
Nearby targets share a view only when the union remains legible. A move over
40% of the frame, or one estimated to take over 0.6 seconds, becomes a cut at
a click, dwell start, activity event or nearby idle end. The old view holds
until the cut, with no travel through empty space.

Portrait uses a tall picture area: up to 90% of delivery height without
captions, or 58% with CAPTION2 captions in the lower band. Magnification targets
the shared phone text floor and at least 60% of output width for the focus.
It can crop non-focus panel space. `--max-zoom` (default 1.8) is the preferred
context zoom; the phone floor can require greater enlargement.
`--ui-text-px` supplies the source text em-size estimate (default 24).
Enlargement cannot restore missing source detail. If a complete focus line
cannot fit at the floor, the camera preserves it and reports the conflict;
record larger UI text or choose a wider delivery.

These bounds are heuristics, not DOM or OCR results. Gradients, low contrast,
unusual typography and changes between sampled frames can defeat detection.
Inspect the phone sheets and saved boxes. Oversampled 4:4:4 crop and `zoompan`
reduce source-pixel rounding. The work directory saves focus/word boxes,
picture rectangles, camera keys, cuts, the time map and FFmpeg graph.
Balanced expressions and `filter_script_args` support FFmpeg 6, 8 and 9.
Older version-1 plans without boxes get a region probe at render time.

`freezedetect` supplies possible idle spans. A cursor rest of at least 450 ms
is attention, including long hovers: its entire span remains at normal speed
and keeps a zoom hold. Runs must stay within 1.2% of their starting position
and below 2.5% of a screen per second over the measured window. Slow pans
therefore do not become dwells. Every valid rest survives; there is no
duration ranking or 1.8-second exclusion zone.

Only inactivity without dwell, cursor travel, clicks, keys, local image changes
or supplied words is compressed. Even travel too small for the image tiles
protects timing. Safe idle interiors default to 4x, with reading handles.
Use `--idle-speed 1` to retain all timing. Audio without supplied word timings
stays at normal speed because a still screen can contain narration.

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
  MIT, copyright 2025 Siddharth Vaddem. Adapted its 450 ms dwell concept.
  Zing retains long holds, checks window velocity and excursion, breaks gaps
  over 100 ms, and keeps every valid run. Its original maximum duration,
  per-sample movement threshold, duration ranking and spacing are not used.
- [Screenize](https://github.com/syi0808/screenize/blob/027be96bbf2d855698bc67f1536ac8cef48cc3e4/Screenize/Generators/SegmentCamera/SegmentPlanner.swift),
  Apache-2.0. Adapted scene merging (distance <0.05, gap <0.5 s), transition/hold
  structure and minimum holds. Its ContinuousCamera informed the original
  spring/dead-zone design. The revised focus-content camera uses stable containing
  views, eased push-ins and action-timed cuts for distant targets. This is not
  the full Swift planner.
- [screenstudio-alt-skill](https://github.com/connerkward/screenstudio-alt-skill/blob/61a0b303ce3a73d103398fee7ecb5fa31f8a0994/src/polish.py),
  MIT, copyright 2026 Conner K Ward. Adapted the local event-log and FFmpeg
  `freezedetect` idle-compression approach. The privacy-filtered JSONL schema is
  Zing's own, not a drop-in import of that tool's key-bearing events.

Full licenses are in `docs/licenses/screen-*.txt`. PyObjC is MIT, optional and
macOS-only; core Zing remains stdlib-only. No model or external media is downloaded.

The full license texts and modification notice also ship in the installed package at `myzing/_data/docs/SCREEN-LICENSES.md`. Plans accept recordings up to one hour.
