# Timeline inspection

`zing inspect timeline` puts video frames, audio and timed text in one PNG.
Use it to check a cut or caption without playing the edit. It runs locally with
FFmpeg/ffprobe and Pillow from the existing `myzing[memes]` extra:

```sh
pip install "myzing[memes]"
zing inspect timeline edit.mp4 --start 1 --end 4 --out review.png
zing inspect timeline edit.mp4 --around 2 --radius 0.5 --out cut.png
zing inspect timeline edit.mp4 --edl draft-edl.json --out cuts.png --json
zing inspect timeline source.mp4 --breakdown my-source --workspace ./zing-workspace/home --out words.png
```

With an EDL, supply its **rendered output video**. Without a time range, each
internal EDL cut gets a separate row centered on the cut. `--start`/`--end`
select one range instead; `--around` centers one row on an output timestamp.
The default radius is one second. Near a video edge, both sides shrink equally
to keep the selected time centered. To inspect time zero, use `--start 0`.
Without an EDL or range, the whole video is selected, up to 120 seconds.

Each row has five frames by default. Frame **centers**, waveform bins, word
interval bars and amber cut markers share one linear time axis. Frames are
sampled at bin midpoints, avoiding an empty frame at the exact video end.
Centered rows require an odd `--frames` count of at least three. FFmpeg seeks
select the first decoded frame at or after the label; allow one video frame
for sampling and render rounding. The waveform shows mono, 8 kHz linear RMS
relative to full scale, without per-row normalization. A missing audio stream
is labeled; a decode error fails the inspection.

Cut markers describe the supplied plan. They are not detected cuts. The images
come from the supplied video, so a reviewer can compare the planned boundary
with its pixels. Duration is checked against the EDL within one video frame
or 50 ms, whichever is larger. A matching duration does not prove that the video
belongs to the EDL. Only v1 contiguous, unity-speed clips are supported; gaps,
overlaps and other schema versions fail explicitly.

## Time coordinates and transcript

For a v1 clip, the mapping is:

```text
source_time = src_in + output_time - timeline_start
output_time = timeline_start + source_time - src_in
```

Clip intervals are half-open: a cut timestamp belongs to the incoming clip.
Every cut includes the outgoing source endpoint and incoming source start,
their paths and original EDL clip indexes. Relative source paths resolve from
the EDL directory. Source assets need not remain online; inspection decodes
only the rendered video. The PNG labels both source endpoints below its rows.

EDL word-timed captions already use output seconds. Captions without word
timings appear as phrase intervals; inspection does not invent word offsets.
An explicit `--breakdown` takes precedence over EDL captions. Without an EDL,
the breakdown must describe the supplied video's timeline. With an EDL, its
stored media path or local source URL must identify either the rendered video
or one EDL source. Source transcript intervals are intersected with each kept
clip and translated to output time. Reused footage repeats its words. Invalid
word intervals produce an error with the word index.

Text sits beneath its interval, centered at the visible interval midpoint.
Labels can use four vertical lanes. At image edges, the label stays inside
the image while its bar and midpoint tick retain the exact time coordinate.
If labels cannot fit, the command asks for a shorter range or wider image;
words are never silently omitted. Missing transcript text is labeled. There
is no ASR, download or model call during inspection.

## Metadata and limits

`--json` returns the same path and metadata as MCP's `inspect_timeline` tool:
`ok`, `version`, `path`, `width`, `height`, `video`, `duration`, `rows`,
`mapping`, `cuts`, `warnings` and `transcript_origin`. Each row contains its
range, axis endpoints, frame rectangles/times, waveform rectangle, cut x
positions and word bars/text boxes. Image bytes are never returned. CLI and
MCP errors use `{"ok": false, "error": "..."}`; CLI also exits nonzero.

The x projection is `x0 + (time - start) / (end - start) * (x1 - x0)`, rounded
to the nearest pixel. The synthetic acceptance tests check both metadata and
drawn transcript bars within **one pixel**, and verify red/green/blue frames
before, at and after two cuts in an actual Zing render. Actual text glyph centers
must fall within three pixels of the interval anchor, allowing font side bearings.
A separate audio pulse
checks waveform alignment within 12 pixels (8 ms in that test's zoom).

Requests are bounded to 1–15 frames per row, 60 frames total, 12 rows,
960–2400 pixels wide, and 12 megapixels including cut legends. Timestamps must
fit in their thumbnail cells. Each row covers at most 120 seconds, with 600
seconds total across rows. At most 60 cut legends may appear in a selected
range. Over-limit requests fail with a narrower-range remedy. Each subprocess
has a 20-second timeout within a shared 50-second decoding budget. Commands
use argument lists and allow only local `file`/`pipe` FFmpeg protocols.

Existing files are refused unless `--overwrite` / `overwrite=true` is set.
A complete PNG is staged beside the destination and published atomically;
create-if-absent also protects against concurrent writers. Source inputs are
protected even with overwrite enabled. Publishing without overwrite requires
filesystem hard-link support (NTFS and ordinary Linux/macOS local filesystems
support it); filesystem errors are returned to the caller.

## Native implementation and attribution

The layout was informed by Browser Use's MIT-licensed
[timeline_view.py](https://github.com/browser-use/video-use/blob/43cfc566833548093455c9d4a46bd69913b7e552/helpers/timeline_view.py)
and its
[transcript helper](https://github.com/browser-use/video-use/blob/43cfc566833548093455c9d4a46bd69913b7e552/helpers/pack_transcripts.py),
reviewed at commit `43cfc566833548093455c9d4a46bd69913b7e552`.
The [upstream license](https://github.com/browser-use/video-use/blob/43cfc566833548093455c9d4a46bd69913b7e552/LICENSE)
is MIT, copyright 2026 Browser Use. No upstream code was copied or vendored.

A native module is smaller to integrate safely here: the reviewed helper has
an unimplemented EDL mode, imports NumPy, leaves subprocesses without timeouts,
and returns a zero envelope on audio failure. Zing needs explicit EDL mappings,
bounded work and visible failures. The native implementation uses stdlib PCM
aggregation plus existing Pillow and FFmpeg installations. No dependency or
lockfile change is needed. The existing bundled IBM Plex Sans font is OFL;
Pillow uses the HPND license. FFmpeg licensing depends on the installed build;
this feature does not distribute binaries.
