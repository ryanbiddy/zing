# C-CD1 raw-mode source record

Checked 2026-07-19 by Lane C. This is the source-of-record for the
full-fidelity S3 direction rerun.

## Selected source

- **Fixture:** `raw-talking-head-korky-paul`
- **Title:** “Korky Paul Introduction”
- **Subject:** Korky Paul
- **Recorder/uploader:** Mvolz
- **Canonical page:** https://commons.wikimedia.org/wiki/File:Korky_Paul_Introduction.webm
- **Original media:** https://upload.wikimedia.org/wikipedia/commons/8/8d/Korky_Paul_Introduction.webm
- **Commons file-page ID:** `92974199`
- **Duration / frame:** 19.069 seconds, 1080 × 1920, 30 fps
- **Codecs:** VP8 video, Vorbis audio
- **Original byte size:** 8,399,608
- **Original SHA-256:** `8243758381ebca3f4ab75c714ecca8e02f60dee67037b3508301d89aa17da574`
- **Commons SHA-1:** `6d81684ef379677514940da2928b6c5642551c66`

## Rights and provenance

The Commons file page identifies the clip as the uploader’s own work and
labels it **CC0 1.0 Universal**. Commons’ machine-readable metadata reports
`LicenseShortName: CC0`, `AttributionRequired: false`, and the CC0 deed URL.
The rights page and original media URL were both live when checked.

CC0 does not require attribution. We still retain the subject, recorder,
canonical page, license evidence, and hashes so the source cannot become an
anonymous fixture.

## Genuinely unedited verdict

**Pass for this gate.** Lane C inspected a contact sheet sampled every two
seconds across the complete 19-second file. Every sample shows the same
speaker in the same portrait setup. There are no visible cuts, cutaways,
captions, lower thirds, title cards, or other overlays. An FFmpeg scene scan
at threshold `0.25` emitted zero scene candidates. The Zing study result must
also remain a one-shot breakdown before this fixture is accepted.

This verdict is deliberately narrower than “camera-original.” Commons
encodes uploads into supported formats, and codec metadata cannot prove that
no file operation occurred before upload. For the S3 full-fidelity gate,
“genuinely unedited” means the distributed clip itself is one continuous,
unadorned talking-head take rather than a marketed-raw montage like the
retired F-16 stand-in.

## Acquisition and regeneration

Run from the repository root in PowerShell. Replace `<media-root>` with an
absolute scratch directory; source media remains outside Git.

```powershell
curl.exe -L --fail --retry 3 -o "<media-root>/korky-paul-introduction.webm" "https://upload.wikimedia.org/wikipedia/commons/8/8d/Korky_Paul_Introduction.webm"
Get-FileHash -Algorithm SHA256 "<media-root>/korky-paul-introduction.webm"
python -m tools.eval.freeze_real_videos --media-root "<media-root>" --manifest tools/eval/real_videos/manifest-raw-mode.json --output tools/eval/real_videos
python -m tools.eval.backfill_frames --media-root "<media-root>" --manifest tools/eval/real_videos/manifest-raw-mode.json
```

The hash must match the pinned SHA-256 above before freezing. The manifest
sets `study_options.raw_mode` to `true`; a freeze that omits
`provenance.raw_mode` is invalid.

## Human truth for the regression

- The complete clip is a single portrait talking-head shot.
- No burned captions or graphic overlays are visible.
- No cutaway or scene transition is visible.
- The source is English speech and is long enough for word-timed
  transcription and raw keeper measurement.
- Raw measurements such as dead air, fillers, repeated takes, and keepers are
  analyzer outputs, not hand-labeled truth. The fixture tests their
  availability and provenance; it does not present them as independently
  annotated accuracy targets.

