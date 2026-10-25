# Caption presets

Choose `punch` for short vertical clips, `box` for a moving word highlight, or
`clean` for interviews and dialogue. Studio recommends Punch for phone video
and Clean for a single 16:9 delivery, with a reason in the caption question.
`reference`, `phone`, and explicit existing styles retain their old behavior.

| Preset | Type at a 1080 px short side | Group | Highlight and motion |
|---|---|---|---|
| `punch` | Inter-derived ExtraBold 800, 97 px, capitals, black outline | 1–3 words, one line | `#FFD23F` active word; whole group enters over 140 ms, 80% → 105% → 100% |
| `box` | Inter-derived ExtraBold 800, 81 px, capitals | 2–4 words when boundaries and width permit, one line | Yellow plate covers the active word from its first frame; 100 ms entry fade |
| `clean` | Inter-derived Bold 700, 59 px, original case | Up to two balanced lines; 30 characters per line in portrait, 42 in landscape | White text; fixed bottom baseline, so a second line grows upward |

Sizes scale by the output's short side in 16:9, 1:1 and 9:16. Grouping uses the actual face's glyph advances,
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

Sentence punctuation prefers a new cue; short fragments can merge with their
neighbour. Substantial pauses, speaker changes and shot boundaries close a cue.
English articles, prepositions and conjunctions
stay with the following word. The grouping search penalizes broken pronoun/verb
pairs, split names, single-word cues, short durations, and excessive reading speed.
The two-line chooser prefers a natural break near the balanced midpoint.

Clean targets at least 5/6 second, at most four seconds, and no more than
20 characters per second. It aims for a two-frame gap. A cue may lead speech
by up to 250 ms into silence to reach the reading time. Pop presets target at least
0.3 second. Holds use following silence first. When neighbouring cues have spare
time, their display boundary may move by at most 100 ms within an edge word;
`caption_display_sync` retains its original timing. Cues never overlap or cross
a shot cut. Words and their source timing provenance remain available for review.

Speech can make these rules incompatible. A sentence ending at the video cut
may have less than 5/6 second available. A long word or a protected phrase can
force a single-word cue. Long words and URLs split at measured cluster boundaries,
preferably after URL punctuation; splits retain the source timing and record
proportional display timing. Numbers, acronyms and contractions stay intact when
they fit. Punctuation-only tokens attach to their preceding word; CJK groups use
character widths. English protected-pair lists are not multilingual NLP, and RTL
uses per-word shaping with the first strong character setting the line direction.
These shortages appear in plan warnings. Choose Clean or adjust
the edit's cut points when Punch or Box would flash through dense speech.

The caption layer uses faster-whisper's installed Silero VAD to trim overlapping
word windows to detected speech. It never downloads a model. Missing VAD or a
word with no speech overlap leaves the source timing in place with a warning.
AUD1's successful `provenance.timing.method="vad_edge_snap"` and matching
`adjusted` words become a per-word marker before timeline mapping. The caption
VAD is a no-op for those words, including words AUD1 left unchanged. Unavailable
or stale study evidence does not suppress the caption check. This is a silence
clamp, not forced alignment or a claim of word-level accuracy.
Highlights hold through gaps under 250 ms and through the final cue hold.
Joined numeric tokens form one display unit: `$5` followed by `,000.` highlights
the whole `$5,000.` while either piece is active and across the pause between
them. Box covers the complete unit, including currency glyphs above cap height;
Punch colors every piece together. Original word timings remain available.

Each shot gets one rail centered in the usable safe area, checked against swept supplied face
tracks and existing UI reserves. The whole shot may shrink in 5% steps down to
80% to fit, while Punch and Box never go below the existing phone size floor.
Clean uses subtitle sizing instead. Clean starts near the 74% bottom rail in portrait; 78% is available
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
uv run --frozen python tools/eval/caption2_acceptance.py --revision=-verified
```

After that command, open these generated example sheets. They are local
artifacts; a fresh checkout does not contain the media:

- Punch, Korky in 9:16: `zing-workspace/caption2/8.1.2-verified/korky-9x16-punch/phone-contact.png`
- Box, Tears of Steel in 16:9: `zing-workspace/caption2/8.1.2-verified/tos-dialogue-16x9-box/phone-contact.png`
- Clean, Korky in 9:16: `zing-workspace/caption2/8.1.2-verified/korky-9x16-clean/phone-contact.png`

Every combination has a video, four example frames, a 400-pixel-wide contact
sheet, saved composition, ASS, and per-event metrics. The same packet is rendered
with FFmpeg 6.1.1 under `caption2/6.1.1-verified`. `tests/test_caption2_ffmpeg.py` checks
glyph boxes across settled word states on all three aspect ratios, including
missing font paths and libass fallback glyphs. Punch's deliberate
entry scale and Box's entry fade are excluded from the fixed-glyph comparison.

## Fonts and attribution

The two bundled static faces derive from the existing pinned Inter source.
Optional kerning and ligatures are disabled in these derivatives so their
fixed word slots use reproducible advances. Required font shaping tables remain.
Missing bundled font paths resolve by SHA-256 to this installation's identical
face. Libass receives those exact bytes under a private family name. Unsupported
glyphs use libass's system fallback, measured by rendering the actual word and
reported in plan warnings. This requires FFmpeg with libass; without it, Zing
asks for that installation instead of estimating character widths. System fallback
coverage varies by machine; a missing custom font requires reapplying the preset.

`caption-presets.json` pins source and output font hashes. The OFL license travels
with the fonts. `tools/eval/caption2_fonts.py` reproduces them using fontTools as
a build tool only. AutoSubs' MIT grouping and break-priority attribution is in
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
