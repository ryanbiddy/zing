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

Clips whose speech levels differ need their voices matched, not only their
bed. A whispered clip next to a loud one leaves the quiet clauses about 11 LU
over the bed and jumps at the cut. When the gated speech levels of the edit's
recordings span more than 6 LU, the director first matches the dialogue. It
records `dialogue_gains` in the MUSIC1 evidence (output-time ranges, so
per-aspect framing splits keep them), and the renderer applies them to each
clip's source audio. Each quieter recording is raised toward the loudest
recording's speech, by at most 18 dB. Gains are per source asset: two
sentences of one recording keep their natural difference, and a jump cut
inside it gets no level step. If that static gain would push the clip's peaks more
than 3 dB past the −2 dBFS limiter, a 4:1 peak compressor (5 ms attack, 120 ms
release) follows the gain, with its threshold 6 dB above the target speech
level; the limiter catches what remains. The gain covers the whole clip,
ambience included, as an editor's clip gain would. The plan warns when it
compresses a clip (listen for pumping or raised room noise) or caps the boost.
Where the source changes at a hard cut in a speech-led edit, each clip's own
audio fades over its speech-free edge: out over at most 0.3 s before the cut,
in over at most 0.1 s after it, never reaching a known word. A clip's score or
room tone then does not stop dead at the cut. Cuts within one recording do
not fade, because their room tone continues (a fade there dipped it).

Whatever spread remains above 6 LU after that goes to the bed. The director
records `bed_gain_points` (`[seconds, dB <= 0]` pairs), which the renderer
adds to the duck envelope. A level change moves under the louder voice, where
speech masks it: a rise starts at the louder clip's first word and a drop ends
at its last, each over a 1.0 s raised cosine. The first pass offsets each clip
by its remaining speech level against the loudest clip. A second pass centres
each clip's planned clauses on 21 LU, so the music's own level changes are
accounted for. The track gain carries the loudest wanted bed, because the
envelope only lowers the bed. A bed cut is capped at 24 dB, and a clip whose
speech is below the loudness gate follows its neighbour; both cases add a plan
warning. The evidence lists `clip_levels` (source and matched speech LUFS and
bed offset per clip) and `clauses` (planned speech, music and separation per
clause). It warns when any clause is planned outside 18–24 LU. The exception
is a clause above the band that sits under a bed ramp, or in a compressed
clip, where the planned figure is an upper estimate; such clauses are reported
but do not warn.
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
and in the render's warnings. A clause above the band under a bed ramp is
reported (`above_band_under_bed_ramp`) but does not warn: the bed is only
further under the speech there. Work directories retain
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
measures 300 spans. Director tests with two generated talkers cover both
mechanisms. At 14 LU apart, the quiet clip is raised about 14 dB, one bed
gain remains, and every clause measures 18–24 LU. At 26 LU apart, the boost
caps at 18 dB with a warning, and the bed drops about 8 dB under the quiet clip
over the loud voice's last second. Every clause is then in band, while the
same mix with one bed gain puts the quiet clauses under 16 LU and warns.
These are bounded tests, not a real-world accuracy estimate. The acceptance report under
`zing-workspace/MUSIC1-REPORT.md` records the real-media evidence and failures.

## Listening

LISTEN1 had Gemini 4 Argon listen to the mixes through Google's Antigravity CLI
(`agy --mode plan`). It ran from folders holding only the final mix, the
isolated bed and the timing sheet of the licensed acceptance media. The prompt
asks for a hearing check (describe the music, quote the first and last words),
then timestamped answers on pumping, intelligibility, duck timing, cuts against
drops and beats, the ending, artifacts, and whether to publish.
`uv run --frozen python -m tools.eval.listen1_packet --root <acceptance root>
--out <dir> <case>...` builds those folders' files for each rendered case:

- the final mix (48 kHz WAV and 320k MP3)
- the isolated pre-limiter music bed
- a timing sheet without local paths
- `measurements.json`: 50 ms RMS and 400 ms momentary loudness curves, the
  planned duck gain, limiter gain reduction (the final mix against the sum of
  its stems), the largest bed level steps outside planned ramps, onsets and
  beats near each cut, peaks, stereo correlation, and per-clause separation
  (the renderer's rows plus a gated FFmpeg cross-check)

Every claim was checked against those measurements before anything changed.

What listening found, and what it changed:

- Pumping in the 0.84 s sentence gap, and an abrupt fade-in followed by an
  immediate duck at the start. Confirmed by the envelope; fixed by the
  plateau and edge rules above. Every later review heard the bed held.
- The quiet Tears of Steel speaker "partially masked" and the voice jumping
  at the 3.2 s cut. Confirmed: the clips' gated speech differs by 13.9 LU and
  two clauses sat 11 LU over the bed. A per-clip bed alone was then heard as a
  second jump: a 9 dB swell in the silent gap at the cut, which stayed
  noticeable even when moved under the louder voice. So the voices are now
  matched first (+13.3 dB on the Tears of Steel recording, with a peak
  compressor). After that, all five clauses measure 19.9–22.8 LU over one
  bed level, the mix measures −13.7 LUFS and −1.7 dBTP, and the limiter takes
  up to 3.4 dB on one plosive. A first version matched each clip and gave the
  second Korky Paul trim a +1.3 dB step at its jump cut; the listener heard
  it, so gains are now per recording.
- The outgoing clip's audio stopping dead at the cut. Confirmed: its floor
  fell about 30 dB at once. It now fades over its last 0.3 s. Fading the
  Korky Paul jump cut as well dipped its continuous room tone (heard, and up
  to 16 dB in the stem), so only source changes fade.

What listening found that Zing cannot fix in the mix: the Tears of Steel clip
carries its own film score, now louder along with the matched voice. Its
speech is dark and reverberant beside Korky Paul's dry recording, and an
untranscribed murmur trails "be honest". The edit also ends 0.33 s after the
last word. These belong to the clips and the authored source ranges. Three
of the last four talking reviews called the bed buried, and two asked for
4–6 dB more. It sits 20.8 LU under speech, inside both the 18–24 LU band and
P17's 15–25 LU range for talking beds. Raising it that much would leave the
documented band, so it stays a design decision (`speech_to_music_lu` in the
evidence) rather than a fix.

On the montage, the audio was identical in all three runs, yet Gemini placed
the drop at 4.0 s, then at 3.6–3.7 s, then at 4.25 s. It also called the two
retained cuts both 300 ms late and nearly on the beat, and once heard
"clipping" that the bed's −1.4 dBFS pre-limiter peak rules out. Measurement
is authoritative there: the drop's bass enters within 5 ms of the 4.000 s
cut, and the 4.9 and 6.15 s cuts sit 281 and 264 ms off the 100 BPM grid. The
3.70 s pickup is a real off-beat transient that a listener may hear as the
hit.

Limits: one model, on two short edits. Its timestamps drift; in one run it
heard the 12.97 s file as about 12 s long. Its transcription of quiet speech
changed between runs ("be tender to her", "pretend not to"). It also repeats
the timing sheet's numbers as if it had heard them, so only claims a
measurement can confirm were acted on. This is not a panel of human
listeners, and taste judgments (whether a fade ends "mid-groove") stay
unverified.
