# Caption presets

Choose `punch` for short vertical clips, `box` for a moving word highlight, or
`clean` for interviews and dialogue. Studio recommends Punch for phone video
and Clean for a single 16:9 delivery, with a reason in the caption question.
`reference`, `phone`, and explicit existing styles retain their old behavior.

| Preset | Type at 1080-wide output | Group | Highlight and motion |
|---|---|---|---|
| `punch` | Inter-derived ExtraBold 800, 97 px, capitals, black outline | 1–3 words, one line | `#FFD23F` active word; whole group enters over 140 ms, 80% → 105% → 100% |
| `box` | Inter-derived ExtraBold 800, 81 px, capitals | 2–4 words when boundaries and width permit, one line | Yellow plate glides for 80 ms behind fixed text; 100 ms entry fade |
| `clean` | Inter-derived Bold 700, 59 px, original case | Up to two balanced lines; 30 characters per line in portrait, 42 in landscape | White text; fixed bottom baseline, so a second line grows upward |

Sizes scale by output width. Grouping uses the actual face's glyph advances,
including the padding reserved by every Box word. Font metrics set the baseline;
letters with descenders or different capitalization cannot change the anchor.
These are chosen styles, not claims about the reference video's original font.

## Choose a preset

```powershell
$env:UOINK_URL='http://127.0.0.1:1'
zing match reference.mp4 --clips clips --out drafts --caption-mode punch
zing render plan.json -o captioned.mp4 --caption-mode box
zing brief new project --answers '{"caption_mode":"clean"}'
```

The same `caption_mode` values work in brief JSON and MCP `brief_save` or
`match_start` answers. MCP `zing_studio` accepts `answers.captions` and returns
the preset choices, recommendation, and reason. `brief_questions` lists the
optional field. `caption_options` remains available for explicit style overrides.

Selecting a preset rebuilds its groups, pinned font, and shot layout. Redelivery
regroups at the new width. Merely loading an old composition does not select a
preset or change its ASS output. Presets use libass and add no runtime dependency.

## Timing and placement

Sentence punctuation, substantial pauses, speaker changes when supplied, and
shot boundaries close a cue. English articles, prepositions and conjunctions
stay with the following word. The grouping search penalizes broken pronoun/verb
pairs, split names, single-word cues, short durations, and excessive reading speed.
The two-line chooser prefers a natural break near the balanced midpoint.

Clean targets at least 5/6 second, at most four seconds, and no more than
20 characters per second. It aims for a two-frame gap. A cue may lead speech
by up to two frames to reach the minimum duration. Pop presets target at least
0.3 second. Holds use available silence and never overlap the next cue or cross
a shot cut. Words and their source timing provenance remain available for review.

Speech can make these rules incompatible. A sentence ending at the video cut
may have less than 5/6 second available. A long word or a protected phrase can
force a single-word cue; a phrase that cannot fit even at the size floor fails
with a remedy. These shortages appear in plan warnings. Choose Clean or adjust
the edit's cut points when Punch or Box would flash through dense speech.

The caption layer uses faster-whisper's installed Silero VAD to trim overlapping
word windows to detected speech. It never downloads a model. Missing VAD or a
word with no speech overlap leaves the source timing in place with a warning.
This is a silence clamp, not forced alignment or a claim of word-level accuracy.
Highlights hold through gaps under 250 ms and through the final cue hold.

Each shot gets one centered rail, checked against the swept supplied face
tracks and existing UI reserves. The whole shot may shrink in 5% steps down to
80% to fit. Clean starts near the 74% bottom rail in portrait; 78% is available
when a face needs more clearance. An unsafe result stays marked unsafe and
requires the renderer's existing explicit acceptance. Detector coverage is not
proof that every face was found.

## Example frames and reproduction

CAPTION2's licensed V1 packet includes Korky Paul (CC0) and *Tears of Steel*
dialogue (CC BY 3.0, Blender Foundation). Source hashes and attribution are in
`tools/eval/real/manifest.json`. Media and renders stay under `zing-workspace`.
The local acceptance report records the transcript source and timing repairs.

After preparing the packet, run:

```powershell
$env:UOINK_URL='http://127.0.0.1:1'
uv run --frozen python tools/eval/caption2_acceptance.py
```

The generated examples below are local artifacts, not committed media:

- [Punch, Korky in 9:16](../zing-workspace/caption2/8.1.2/korky-9x16-punch/phone-contact.png)
- [Box, Tears of Steel in 16:9](../zing-workspace/caption2/8.1.2/tos-dialogue-16x9-box/phone-contact.png)
- [Clean, Korky in 9:16](../zing-workspace/caption2/8.1.2/korky-9x16-clean/phone-contact.png)

Every combination has a video, four example frames, a 400-pixel-wide contact
sheet, saved composition, ASS, and per-event metrics. The same packet is rendered
with FFmpeg 6.1.1 under `caption2/6.1.1`. `tests/test_caption2_ffmpeg.py` checks
glyph boxes across settled word states on both aspect ratios. Punch's deliberate
entry scale and Box's plate motion are excluded from the fixed-glyph comparison.

## Fonts and attribution

The two bundled static faces derive from the existing pinned Inter source.
Optional kerning and ligatures are disabled in these derivatives so their
fixed word slots use reproducible advances. Required font shaping tables remain.
Unsupported glyphs fail with a font remedy; Zing does not silently substitute
a system font. English protected-pair lists do not constitute multilingual NLP.

`caption-presets.json` pins source and output font hashes. The OFL license travels
with the fonts. `tools/eval/caption2_fonts.py` reproduces them using fontTools as
a build tool only. AutoSubs' MIT grouping and break-priority attribution is in
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
