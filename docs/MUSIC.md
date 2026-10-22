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
the full pace weight; at most 20% earns 70%; at most 35% earns 40%.
A drop earns the full moment weight; a hit or section change earns half.
Swells do not earn moment points. A rise of at least 3 dB from the excerpt's
first quarter to its last earns full montage energy points when a supported
pulse or at least 1.5 attacks/s supplies activity; flatter active excerpts
earn 40%. Calm excerpts without that activity earn none.

For speech, unknown vocals earn 70% of the vocal weight and possible vocals
earn none. A bed with 10th–90th percentile level spread at most 6 dB and at
most 1.5 attacks/s earns full energy points; spread at most 10 dB earns half.
Intro energy within min(3 seconds, 35% of the excerpt) earns full points;
within six seconds earns half. Scores evaluate complete available excerpts
and suggest a source offset. The speech director uses the advised steady
excerpt without forcing a song moment under dialogue.

Quality deductions are 28 for insufficient duration, 14 for unavailable or
greater-than −7 LUFS integrated level, 10 for LRA over 15 LU, 28 for more
than 0.1% near-full-scale samples (or 12 for peak-only overload risk), and
35 for more than 9 dB mono fold-down loss. Gain can fix excess level, while
existing distortion needs a cleaner source. Scores remain rules, not taste
predictions; full-track vocal and quality estimates can obscure local changes.

The director checks all supplied candidates and selects the highest score.
It records the selected track, alternatives, analysis and reasons in a
versioned `MUSIC1 evidence: ` record carried in the v2 plan's warnings, and
in the comparison report's `music` field. The track's source offset places a
detected drop (or strongest available moment) on the largest measured pixel
change among the selected joins. That 32-pixel RGB difference is a visual
proxy: it cannot recognize a semantic reveal. If no complete source window
can align a moment, the offset stays zero.

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
or available track boundary. No loops are automatic.

The v2 renderer supports audio source trims and `duck_scope="source_speech"`.
It needs the director's known speech spans. Source audio keys the compressor
only inside those spans; background sound outside them cannot trigger it.
The key is normalized to a fixed level to give about 15 dB attenuation, with
20 ms attack and 250 ms recovery. Gated source loudness sets the music's gap
level about 6 LU below speech, targeting 21 LU below speech in phrases
(18–24 LU acceptance band). With no known speech, the planning target is
−16 LUFS for music. These are gain targets; the renderer measures the result.
It retains E2E1's oversampled −2 dBFS peak limiter before AAC. Encoded true
peak still needs verification.

Each music render produces a `.music.json` sidecar tied to the MP4 SHA-256.
It reports isolated post-duck music RMS and LUFS in speech and gap windows,
source-speech LUFS, their difference, integrated mix LUFS and true peak, and
a quarter-second music level curve. Work directories retain music/source WAV
stems. Stems precede the final limiter; the source stem can contain embedded
music. Below-gate or short windows may have null LUFS. A gap average includes
compressor recovery and fades, so it is not a pure compressor-depth test.

Match JSON includes the music choice and measured mix. `zing inspect timeline`
reads a matching sidecar, returns its measurements and draws pink moment
markers beside amber planned cuts. A mismatched SHA-256 is reported as stale.
Inspection accepts v2 plans with unity-speed hard cuts; overlaps and speed
maps remain unsupported.

Generated-audio tests establish accented 120 BPM downbeats within 33 ms,
a sustained drop within 250 ms, unknown meter for equal accents/drones,
vowel-like harmonic warnings, constructed advice rankings, offset alignment,
clause protection and rendered ducking deeper than 12 dB. These are bounded
tests, not a real-world accuracy estimate. The acceptance report under
`zing-workspace/MUSIC1-REPORT.md` records the real-media evidence and failures.
