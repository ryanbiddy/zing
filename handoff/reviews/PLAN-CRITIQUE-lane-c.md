# Lane C plan critique

Lane C can build the proposed harness and renderer, but two parts of the plan
currently reward an implementation for guessing: the audio golden does not
contain speech, and the EDL does not fully say what its timeline means. Those
are contract problems, not coding details. Fix them before their ambiguity
gets baked into tests.

## 1. Define the EDL's timeline and audio semantics before C-2

**Problem:** `Clip.timeline_start` says where a clip lands, while C-2 says to
trim and concatenate clips and reject overlaps. The plan does not say whether
timeline gaps are legal or, if they are, whether they become black/silence.
It also does not say whether clip audio survives, what a music track does when
it is shorter than the timeline, or what `duck_under_speech` listens to:
voiceover tracks, clip audio, or both. `AudioTrack` has no in/out trim fields,
so the renderer cannot infer these choices from the EDL.

**Recommendation:** Add binding S1 semantics without changing the current
schema:

- Sort clips by `timeline_start`; reject overlaps; either reject gaps in S1 or
  define them as black video plus silence.
- State whether source clip audio is retained.
- Play each `AudioTrack` once from its source start at `timeline_start`, trim
  it at the output end, and pad silence rather than loop it.
- Define `duck_under_speech` against named inputs. For S1, the least ambiguous
  rule is “duck music under voiceover tracks only.”
- Fix the output audio layout (48 kHz stereo), mix ceiling, and behavior when
  there are no audio inputs.

If those are not the intended rules, the schema needs an orchestrator-owned
revision before C-2.

## 2. Do not claim that tones test speech ratio

**Problem:** C-1 calls for tone/silence audio patterns and a
`speech_ratio ±0.1` score. A tone is not speech. A pipeline using Whisper
segments or VAD can correctly report no speech and still fail a truth file
that labels the tone interval as speech. Conversely, a bogus energy detector
could pass.

**Recommendation:** Split the audio oracle:

- Use generated tone/silence intervals to score loudness-window timing and
  silence detection.
- Use a short, checked-in spoken fixture with documented redistribution terms
  to score speech ratio. Generate the surrounding silence and muxing with
  ffmpeg so the interval remains exact.
- Until that speech fixture exists, mark speech-ratio scoring unavailable
  rather than substituting tone energy for speech.

## 3. Specify one-to-one matching, not only tolerances

**Problem:** “Cut count exact, cut times ±0.15s, caption text fuzzy ≥0.8” does
not define how expected and observed events are paired. Greedy matching can
match one observed cut twice. A single concatenated caption score can hide a
missing event, an extra hallucinated event, or a timing miss. Different text
normalization choices can move the result across 0.8.

**Recommendation:** Put the scoring rules in a versioned eval manifest:

- Match cuts one-to-one in chronological order and report missing, extra, and
  out-of-tolerance cuts separately.
- Match captions one-to-one by temporal overlap first, then text similarity.
- Normalize Unicode, whitespace, case, and punctuation explicitly before
  computing similarity.
- Require both event recall and per-event text similarity; penalize extra OCR
  events instead of allowing them to disappear in an average.
- Report raw deltas beside every pass/fail result.

Keep scorer tolerances out of the generated truth files so a tolerance change
cannot rewrite the facts it is meant to judge.

## 4. Make the Lane A integration a narrow adapter

**Problem:** `tools/eval/run.py` must “run Lane A's study pipeline,” but that
pipeline's callable interface and storage behavior are not part of the C-1
contract. Importing Lane A internals would couple the gate to an implementation
that is still being built; invoking the CLI would couple it to storage and
console formatting.

**Recommendation:** Define one eval adapter that accepts a local media path and
returns a `Breakdown`. Keep the scorer itself pure: `score(truth, breakdown)`.
The temporary checked-in sample should exercise that same pure function.
When Lane A lands, only the adapter changes. This also makes deliberately
mutated `Breakdown` objects cheap to test.

## 5. Turn the mutation gate into a small fault matrix

**Problem:** One “deliberately-broken Breakdown” proves only that one branch
can fail. The scorer could silently ignore captions or audio and still satisfy
the gate by catching a missing cut.

**Recommendation:** Require at least one targeted mutation per scored
dimension: remove a cut, shift a cut past tolerance, corrupt caption text,
shift caption timing, add a spurious caption, and move speech ratio past its
limit. Each test should assert that the intended metric fails and unrelated
metrics stay green. That is the minimum evidence that the anti-slop gate is
wired to every claim it prints.

## 6. Make the ffmpeg graph deterministic and Windows-safe

**Problem:** C-2 combines trim, scale/pad, concat, captions, and audio mixing.
A shell-built filter string will be fragile on the primary Windows path,
especially with drive-letter colons, spaces, apostrophes, and ASS subtitle
paths. Concat also fails or drifts when inputs disagree on frame rate, pixel
format, sample rate, or channel layout.

**Recommendation:** Pass subprocess arguments as an argv list, never through a
shell. Normalize every video leg before concat (`setpts`, scale, pad, fps,
sample aspect ratio, pixel format) and every retained audio leg to the fixed
sample rate/channel layout. Put the complex graph in a temporary
`filter_complex_script` file when path escaping would otherwise enter the
filter language. Add fixtures whose paths contain spaces and apostrophes, and
run that test on Windows CI.

## 7. Test rendered content, not only its container

**Problem:** Duration, resolution, and stream counts can all pass when clips
are in the wrong order, trim points are wrong, audio starts late, captions are
missing, or ducking never happens. A single OCR probe frame adds another
fallible subsystem to the renderer oracle and still does not prove caption
timing.

**Recommendation:** Make the golden EDL visually and acoustically
unambiguous:

- Probe center pixels during solid-color clip intervals to verify order and
  trim placement.
- Measure RMS in known audio windows to verify start times, silence, gain, and
  ducking.
- Inspect the generated ASS for exact text and centisecond timing, then compare
  caption-region frame deltas immediately before, during, and after the event
  to prove it was burned in.

Reserve OCR for the Study evaluator. Renderer tests should not fail because an
OCR backend misread text that ffmpeg drew correctly.

## 8. Make ffmpeg a required, identified CI dependency

**Problem:** “Run the scorer when ffmpeg is present” permits the main gate to
skip. Installing an unrecorded distro ffmpeg also makes failures hard to
reproduce, and Linux-only CI misses the product's most failure-prone quoting
path.

**Recommendation:** Install ffmpeg explicitly, fail setup if the binary or
required filters are missing, and print `ffmpeg -version` plus the availability
of `drawtext`, `subtitles`, and `sidechaincompress`. Run the scorer and render
golden on Ubuntu; add a focused Windows job for path handling, ASS burn-in,
and one render smoke test. Keep ordinary unit tests offline by mocking
subprocesses; generated-media integration tests may use only local inputs.

## 9. Preserve evidence from every eval run

**Problem:** A console pass/fail table is useful to a person watching one run,
but it cannot show whether cut error or caption recall is degrading while
still inside tolerance. It also omits the runtime budget in the roadmap.

**Recommendation:** Emit a machine-readable report beside the table with
scorer version, fixture hashes, ffmpeg version, per-event deltas, aggregate
metrics, and wall-clock time. Upload it on CI failure and record per-case
runtime even before performance becomes a hard gate. This turns “green” into
inspectable evidence and gives S2 a baseline instead of anecdotes.

## Deeper threads

- Confidence is present in `CaptionEvent`, but the plan scores only recognized
  text. S2 should test calibration: wrong high-confidence OCR is more harmful
  to downstream judgment than honest low-confidence OCR.
- Synthetic clips prove measurement mechanics, not real-world accuracy.
  The three manually reviewed shorts need frozen annotations and provenance
  if they are to become a regression set rather than a one-time demo.
- The renderer will eventually need explicit policies for loudness,
  true-peak limiting, color metadata, and variable-frame-rate inputs. S1
  should capture the raw probe data now even if those become hard gates later.
