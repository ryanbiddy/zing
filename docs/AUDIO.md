# Audio observations

`zing audio analyze` produces a versioned audio map for a local audio or video
file. It measures attacks, a supported tempo, audio-role candidates, and EBU
R128 loudness. This standalone pass does not change study or render behavior.

```sh
python -m pip install "myzing[audio]"
zing doctor
zing audio analyze clip.wav --json > audio-map.json
zing audio analyze clip.mp4 --breakdown my-study --workspace ./zing-workspace/home --json
```

FFmpeg must be on PATH. Analysis never downloads media or models, runs ASR, or
uploads audio. JSON goes to stdout; without `--json`, the command prints a
summary and warnings. Failures return exit 1 and an error (JSON when requested).
Invalid command syntax returns exit 2.

The map and its nested records have `version: 1` and `to_dict()` / `from_dict()`
methods in `myzing.audio`. Unsupported versions are rejected. `schemas.py` is
unchanged. The top-level fields are `source`, `duration_seconds`, `sample_rate`,
`max_seconds`, `truncated`, `tempo`, `beats`, `onsets`, `segments`, `loudness`,
`warnings`, `tool_versions`, and `breakdown_source`.

All timestamps are seconds from the first decoded audio sample at zero. Use a
breakdown of the same file with the same time origin; an arbitrary trim or
offset needs remapping first. A supplied breakdown is evidence, not a verified
source match. A duration mismatch above 250 ms is reported. Invalid word
intervals are ignored with counts; intervals beyond the excerpt are clipped or
excluded with counts. No transcript text is copied into the audio map.

## Measurement methods

The first audio stream is decoded to 22,050 Hz mono float32 PCM. Analysis covers
at most 600 seconds; `--max-seconds` can lower that limit. Decoding one extra
sample detects truncation. PCM is bounded to roughly 53 MB, FFTs run in batches,
and FFmpeg has a timeout. A truncated map describes only its excerpt, including
its loudness. Network protocols are disabled for FFmpeg inputs.

Onset strength is positive spectral flux from Hann-windowed, 1,024-sample FFTs
at a 220-sample hop (about 10 ms). Local peaks must exceed a 510 ms median plus
six median absolute deviations, an absolute floor, and 8% of the strongest
attack. Peaks within 80 ms compete by strength. `onsets` contains measured
attack times and strengths normalized within the file. They can guide hit
placement, but do not identify an SFX type, source, or isolated effect track.

Tempo comes from repeated inter-onset intervals in 40–240 BPM and a fitted
phase. It requires six attacks spanning at least three seconds, 75% regular
consecutive intervals, 85% agreement within 30 ms, and 80% pulse occupancy.
Returned `beats` are supported onset times; missing ticks are never filled in.
Unstable material returns `none`; short or speech-confounded evidence returns
`unknown`. Both have null BPM and no beats. Downbeats always remain unknown in
this version. Meter and half/double-time interpretations are unresolved.

The tracker favors regular, salient attacks. Quiet beats, syncopation, tempo
changes, dense subdivisions, and speech over most attacks can prevent a tempo
estimate even when a listener hears a beat. Rhythmically spoken syllables can
resemble percussion. These are heuristic observations, not musical ground truth.

Role segments partition the excerpt at 100 ms resolution, with exact additional
boundaries from supplied word timings:

- `speech`: an audible span supported by a supplied word with confidence at
  least 0.5. Confidence is capped at 0.9 because the existing word schema also
  uses 1.0 for unreported probabilities. Weak words or conflicts with silence
  become `uncertain`.
- `silence`: mono RMS at or below −55 dBFS, with confidence 0.95.
- `music`: stable tonal energy (spectral flatness below 0.12, adjacent spectral
  cosine similarity above 0.92, local level spread below 4 dB), confidence 0.6.
  Supplied speech is excluded from the surrounding bed's stability calculation.
  A sustained voice or machine tone can satisfy this heuristic.
- `uncertain`: audible activity without enough evidence, confidence 0.3.

Confidence values are evidence scores, not calibrated probabilities. Without
supplied words, speech-like activity can remain uncertain. A speech label does
not rule out simultaneous music: source separation is outside this pass.
Mono analysis can lose out-of-phase channel content. If the entire mono mix is
near-silent but source loudness is audible, roles become uncertain with a warning.

## Loudness and gain

Integrated LUFS, loudness range in LU, and true peak in dBTP come from the final
summary of FFmpeg's `ebur128=peak=true` filter. The meter uses the source channels
and sample rate, with dual-mono compensation disabled. Trimming happens before
the meter. The FFmpeg summary rounds values to 0.1 units. Below-gate or too-short
integrated measurements and nonfinite peaks become JSON null; a short excerpt's
LRA is reported with a warning about its limited meaning.

```python
from myzing.audio import analyze, recommend_gain

audio_map = analyze("clip.wav")
settings = recommend_gain(audio_map.loudness, target_lufs=-14, target_dbtp=-1)
print(settings.to_dict())
```

The recommendation returns target-minus-measured gain and limiter settings,
plus an advisory FFmpeg filter string. If linear gain would exceed the peak
ceiling, it suggests a 192 kHz oversampled lookahead limiter, 5 ms attack, 50 ms
release, disabled auto-level, latency compensation, and 48 kHz output. A 0.2 dB
margin allows for meter rounding and resampling. No limiter is applied when the
linear prediction already fits. Silence has no usable gain recommendation.

Limiting may lower integrated loudness, so a limited result has no predicted
LUFS. Re-measure the final encoded output and adjust if needed; the filter
string is not a guaranteed one-pass normalization or codec-independent ceiling.
The caller chooses whether to apply it. Existing rendering is unchanged.

## Dependencies and acceptance

The `audio` extra adds `numpy>=1.24,<3` and is included in `all`. NumPy uses the
[BSD 3-Clause license](https://numpy.org/doc/stable/license.html). It supplies
FFT and array operations without the SciPy/Numba stack or pretrained assets.
That keeps this conservative baseline small and compatible with Python 3.10.
No GPL analysis code, aubio, non-commercial weights, or audio assets are added.
The installed FFmpeg executable remains an external prerequisite; its license
depends on its build. No binary is bundled by this pass.

FFmpeg behavior follows its [filter documentation](https://ffmpeg.org/ffmpeg-filters.html).
The local test binary is the pass-rules essentials build; see the pass report
for its exact version and build license. Dependency notices for NumPy and its
wheel components remain in the installed distribution.

The 15 added FFmpeg tests use generated audio only: 120 BPM clicks at three
offsets; white/colored noise and a drone; irregular speech-like activity;
supplied speech timings over a tonal bed; stereo EBU R128 parity; linear and
limited gain re-measurement; silence and short input; bounded coverage; and
video without an audio stream. Click and tempo tolerances are 1/30 second and
1 BPM. Supplied speech boundaries allow 100 ms, music-only duration allows
500 ms total, and recommended gain allows 0.5 LU. These tests do not establish
real-world speech recognition, music classification, or listening quality.
