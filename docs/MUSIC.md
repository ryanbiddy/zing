# Music that serves the edit

`zing music check track.wav other.mp3 --brief brief.json --json` rates local
tracks as good, usable or bad. `--plan plan-A.json` uses the edit's duration,
shot pace and known speech. Without either file, the target is 30 seconds;
`--length`, `--pace` (seconds per cut) and `--speech` override that context.
The `music_check` MCP tool returns the same metadata, never media bytes.
Install `myzing[audio]` and FFmpeg. No analysis step downloads a model or
asset, uploads audio, or identifies songs.

Advice covers supported tempo against 1/2/3/4/6/8/12/16-beat shot lengths, moments
within the requested length, energy changes, vocal risk, intro length,
available duration, loudness, dynamics, clipping risk and mono compatibility.
Scores combine explicit excerpt-fit weights with quality deductions. Licensing is
always unknown unless the user records a claim with `--license-record`;
Zing does not verify that claim or grant permission. The brief interview
already asks for supplied music; its recommendation now includes this advice.

Montage scoring starts at 15 points: pace fit earns up to 25, a usable moment
25, a rising active energy arc 25, and a short excerpt intro 10. Talking
scoring also starts at 15: low vocal risk earns 30, a steady sparse bed 25,
no detected drops in the excerpt 20, and a short intro 10. General advice
starts at 60 and gives pace, moment, energy and intro up to 10 each. Good
means at least 80; usable at least 55. JSON reasons expose their weights,
earned points, deductions and source times; text advice gives the next action.

Pace compares 1/2/3/4/6/8/12/16-beat cut lengths: at most 10% error earns
the full pace weight; at most 20% earns 70%; at most 35% earns 40%. The pulse
is the whole-track tempo when one is supported. Otherwise local 16-second
rhythm regions supply it when they agree within 2% of their overlap-weighted
median BPM and together cover at least 80% of the excerpt, so a track with a
breakdown still supports pace at any excerpt length. Half- or double-time
regions disagree and give no pulse. The pace reason says whether a reference
pace was missing or whether no supported pulse covers the excerpt.
A drop earns the full moment weight; a hit or section change earns half.
Swells do not earn moment points. A rise of at least 3 dB from the excerpt's
first quarter to its last earns full montage energy points when a supported
pulse or at least 1.5 attacks/s supplies activity; flatter active excerpts
earn 40%. Calm excerpts without that activity earn none. Attacks are salient
attacks from the audio map (a band rising at least 6 dB; see
[Audio](AUDIO.md)), so steady pads and noise beds count as zero.

For speech, unknown vocals earn 70% of the vocal weight and possible vocals
earn none. A bed with 10th–90th percentile level spread at most 6 dB and at
most 1.5 attacks/s earns full energy points; spread at most 10 dB earns half.
The energy reason names the rule that failed: "choose a steadier excerpt"
appears only when the spread exceeds 6 dB, and the attack warning only above
1.5 attacks/s.
Intro energy within min(3 seconds, 35% of the excerpt) earns full points;
within six seconds earns half. Scores evaluate complete available excerpts
and suggest a source offset. The speech director uses the advised steady
excerpt without forcing a song moment under dialogue.

Available duration is the probed track length; when analysis stops at its
600-second cap, advice says so instead of reporting the cap as the length.
Quality deductions are 28 for insufficient duration, 14 for unavailable or
greater-than −7 LUFS integrated level, 10 for LRA over 15 LU, 28 for more
than 0.1% near-full-scale samples (or 12 for peak-only overload risk), and
35 for more than 9 dB mono fold-down loss. Gain can fix excess level, while
existing distortion needs a cleaner source. Scores remain rules, not taste
predictions; full-track vocal and quality estimates can obscure local changes.

The director checks all supplied candidates and selects the highest score.
It records the selected track, alternatives, analysis and reasons in a
versioned `MUSIC1 evidence: ` record carried in the v2 plan's warnings, and
in the comparison report's `music` field, together with the clip timeline the
speech spans were computed for. The track's source offset places a
detected drop (or strongest available moment) on the largest measured pixel
change among the selected joins. That 32-pixel RGB difference is a visual
proxy: it cannot recognize a semantic reveal. If no complete source window
can align a moment, or every join frame is identical or unreadable, the
offset stays zero and a `moment_alignment_skipped` decision says why.

Montage joins may move up to 350 ms onto measured beats, preferring supported
metric phrases. Speech joins may move only 80 ms and only inside source
margins that retain every complete clause and required span. Forbidden spans,
quarantine and source reuse still block a change. Speech words are never
retimed to fit music. Hard cuts are the transition vocabulary of this pass;
it does not add overlapping effects. Every changed or retained join records
its music evidence time and reason. Rejected candidates list the proposed
trim and the blocking source/clause constraint for each cut. `cut_summary`
counts moved snaps, already-aligned joins, moment locks and retained cuts.
A supported phrase within two seconds of
the end ends the music early with a fade; otherwise a fade ends at the edit
or available track boundary. No loops are automatic: a track shorter than the
edit adds a plan warning naming how many seconds have no music.

The v2 renderer supports audio source trims and `duck_scope="source_speech"`.
It needs the director's known speech spans; sound outside them cannot move
the bed. It ducks `duck_depth_db` (default 9 dB) with a
`duck_attack_seconds` (0.2 s) raised-cosine pre-duck that ends at the first
word, and recovers over `duck_release_seconds` (0.8 s) after the last word.
A pause releases only when the bed can recover and stay up before the next
pre-duck. The gap must be at least `duck_hold_seconds` (0.8 s) and at least
attack + release + `duck_plateau_seconds` (0.3 s), which is 1.3 s with the
defaults. Shorter clause and sentence gaps stay ducked. Under the old
hold-only rule, a 0.84 s gap released, lifted the bed 8.4 dB for about half a
second and ducked it again; that is pumping. The edges follow the same idea.
When the first word comes within max(hold, attack + plateau) of the edit
start, the bed starts ducked and its 0.15 s fade-in rises only to the ducked
level. When the last word ends within max(hold, release + plateau) of the
edit end, the bed stays ducked into its fade. These follow the
slow-recovery ducking practice in
[the mix research](taste/TRANSITIONS-AND-MIX.md) (P15/P17: down within about
200 ms, back over 500 ms or more, no pumping between phrases). All five
values live in the plan's MUSIC1 evidence and can be edited there. The
renderer turns the passages into a 1 kHz gain envelope file multiplied into
the music (`amultiply`), so neither span count nor FFmpeg expression limits
bound it and no NumPy is needed. Gated source loudness sets the pause bed
21 − depth = 12 LU below speech, targeting 21 LU below speech in phrases
(18–24 LU acceptance band). With no known speech, the planning target is
−16 LUFS for music. These are gain targets; the renderer measures the result.

One bed gain cannot serve clips whose speech levels differ: a whispered clip
next to a loud one leaves the quiet clip's clauses about 11 LU over the bed.
When the gated speech levels of the edit's clips span more than 6 LU, the
director gives each clip its own bed level. It records `bed_gain_points`
(`[seconds, dB <= 0]` pairs in the MUSIC1 evidence), which the renderer adds
to the duck envelope. A 0.4 s raised-cosine ramp sits inside the clause gap
around each cut when one fits, and is centred on the cut otherwise. The first
pass offsets each clip by its speech level against the loudest clip. A second
pass then centres each clip's planned clauses on 21 LU, so the music's own
level changes along the excerpt are accounted for. The track gain carries the
loudest wanted bed, because the envelope only lowers the bed. A bed cut is
capped at 24 dB, and a clip whose speech is below the loudness gate follows its
neighbour; both cases add a plan warning. Edits within 6 LU keep one gain.
The evidence lists `clip_levels` (speech LUFS and bed offset per clip) and
`clauses` (planned speech, music and separation per clause), and warns when
any clause is planned outside 18–24 LU.
It retains E2E1's oversampled −2 dBFS peak limiter before AAC. On the two
real acceptance renders the encoded AAC measured −2.2 and −2.8 dBTP; other
material still needs its own check. Source-speech ducking is refused when the clip
timeline differs from the recorded planning timeline or when transitions
overlap clips, because the spans would no longer mark speech; re-plan first.
A plan carries at most 2,048 speech spans; more are rejected with a message.

A render measures its music only when the plan carries MUSIC1 evidence or
source-speech ducking. A plain music bed renders on a `myzing[render]`-only
install without measurement. When measurement is wanted but NumPy is
missing, the render still succeeds and warns that no sidecar was written.
A measured render produces a `.music.json` sidecar tied to the MP4 SHA-256.
It reports isolated post-duck music RMS and LUFS in speech windows, held
gaps between words and pauses outside passages, source-speech LUFS, their
difference, integrated mix LUFS and true peak, the duck settings, gain points
and passage count, and a quarter-second music level curve. Its `clauses` rows
give speech LUFS, music LUFS and separation for every clause, measured on the
stems with K-weighted 50 ms frames and no gate (within 0.2 LU of FFmpeg's
meter on steady tones and noise; short clauses are approximate).
`clause_separation` summarises them. A render whose clauses fall outside
18–24 LU carries a warning that names the furthest clause, in the sidecar
and in the render's warnings. Work directories retain
music/source WAV stems and the duck envelope; renders without music to
measure write no stems. Stems precede the final limiter; the source stem can
contain embedded music. Below-gate or short windows may have null LUFS. The
pause average includes recovery ramps and fades. Loudness windows use a
balanced FFmpeg selection expression read from a script file, so hundreds of
spans measure on FFmpeg 6.1 and 8.1.

Framing may split a clip at source shot boundaries, in the director or in a
per-aspect delivery. Contiguous pieces of one source keep the planned
timeline, so each 16:9, 1:1 and 9:16 delivery ducks under the same speech
spans and measures the same mix; a generated test renders all three and
compares their sidecars within 0.2 LU.

Match JSON includes the music choice and measured mix. `zing inspect timeline`
reads a matching sidecar, returns its measurements and draws pink moment
markers beside amber planned cuts. A mismatched SHA-256 is reported as stale.
Inspection accepts v2 plans with unity-speed hard cuts; overlaps and speed
maps remain unsupported.

Generated-audio tests establish accented 120 BPM downbeats within 33 ms,
a sustained drop within 250 ms (also after a louder pickup and as a midrange
return after a pad-only break), unknown meter for equal accents/drones,
zero attacks for steady pads, reasons consistent with their numbers,
regional pace for 12–30 s excerpts, vowel-like harmonic warnings,
constructed advice rankings, offset alignment and clause protection. Rendered
ducking holds within 0.5 dB through 0.2–1.0 s gaps (including 0.84 s), and
recovers at least 8.5 dB in a 1.6 s pause, with at least 0.3 s within 1 dB of
full level. It never moves more than 1 dB per 10 ms, and it renders and
measures 300 spans. A director test with two generated talkers 14 LU apart
plans a bed about 14 dB lower under the quiet clip. Every rendered clause then
measures 18–24 LU, while the same mix with one bed gain puts the quiet clauses
under 12 LU and warns. These are bounded tests, not a real-world accuracy
estimate. The acceptance report under
`zing-workspace/MUSIC1-REPORT.md` records the real-media evidence and failures.

## Listening

No one has listened to these mixes yet. The LISTEN1 pass prepared a
listening review with Gemini and could not run it, because the Gemini CLI on
the build machine was not signed in. The ducking changes above fix problems
that break this page's own targets, measured on the real acceptance media;
they were not tuned by ear.
`uv run --frozen python -m tools.eval.listen1_packet --root <acceptance root>
--out <dir> <case>...` exports, for each rendered case:

- the final mix (48 kHz WAV and 320k MP3)
- the isolated pre-limiter music bed
- a timing sheet without local paths
- `measurements.json`: 50 ms RMS and 400 ms momentary loudness curves, the
  planned duck gain, limiter gain reduction (the final mix against the sum of
  its stems), the largest bed level steps outside planned ramps, onsets and
  beats near each cut, peaks, stereo correlation, and per-clause separation
  (the renderer's rows plus a gated FFmpeg cross-check)

Use the measurements to check a listener's claims, which can be wrong about
timing.

On the real acceptance media (MUSIC1's tracks and V1 clips), before and after
these changes:

- Talking edit (Vaporware piano under Tears of Steel and Korky Paul): the
  0.84 s sentence gap at 8.08–8.92 s now holds at −9 dB, where the envelope
  used to rise to −0.6 dB. The bed starts ducked: it fades in to −63 to
  −50 dBFS, where it once played about 0.25 s at up to −33 dBFS before the first
  word. The tail stays ducked into the fade. The clips' speech differs by
  13.9 LU, so the bed sits 9.3 dB lower under the Tears of Steel clip. Per
  clause, speech now stands 21.2, 20.4, 23.2, 20.5 and 21.4 LU over the bed;
  it was 11.3, 10.8, 23.7, 20.6 and 21.2 LU. The gated cross-check reads
  20.3–23.4 LU. The aggregate went from 21.8 to 21.3 LU, the mix from −13.9 to
  −13.8 LUFS, and the true peak stayed at −2.8 dBTP. The 16:9 and 9:16
  deliveries have bit-identical audio.
- Montage (The Charm 68): unchanged and bit-identical, since it has no
  speech. The drop's bass enters within 5 ms of the 4.000 s cut (a 40 dB
  rise below 150 Hz). A stronger broadband transient sits 300 ms earlier, at
  3.70 s, off the beat grid; only a listener can say which one reads as the
  hit. The two retained cuts sit 281 and 264 ms off the nearest beat.
  Measured: −2.2 dBTP, no samples above −1 dBFS, limiter reduction under 1 dB.

Still open for a listener: whether the bed under fully held speech is
audible at all on a phone speaker, the montage pickup at 3.70 s, and the
27 dB drop in the clips' own ambience at the 3.2 s hard cut, which comes from
the sources, not the bed.
