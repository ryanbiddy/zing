# P14 transition evaluation

Generate the corpus and write an event-level JSON report from the repository root:

```console
uv run --frozen python -m tools.eval.transitions zing-workspace/p14-corpus --generate --report zing-workspace/p14-evaluation.json
```

Use `--generated` instead of `--generate` to reuse media. `--split calibration`
and `--split held_out` select a split. The command exits 1 when a threshold
fails, and 2 for invalid input or a failed media probe. The original five-golden
command remains available without either flag.

`transition_corpus.py` generates 48 three-second clips using locally authored,
seeded PGM textures and FFmpeg. Nothing is downloaded. Media stays under the
requested output directory; use `zing-workspace/`, which Git ignores. Each
`truth.json` stores the generator version, exact frame-quantized intervals,
texture seed, FFmpeg command and media SHA-256. The evaluator verifies that hash.

Each split contains two hard cuts (one between moving shots), an audio-aligned
cut, three dissolve lengths, four wipe directions, two short zooms, two blurred
whip pans across cuts, two dips to white, and eight negatives. Negatives cover
camera pan, handheld shake, subject motion, lighting ramp, slow push-in, a pan
with stationary handles, lighting step and lighting pulse. Held-out seeds,
resolution, frame rate and event placement differ from calibration. Both splits
use the same generator family; this is a synthetic regression set.

Scoring matches individual events one-to-one. Cuts must land within two frames;
gradual intervals need IoU at least 0.5. Duplicates, wrong labels and wrong-time
events count as false positives. Boundary errors are also recorded. This
detector gate is separate from the plan's one-frame renderer fidelity gate.

For each supported class, each split must reach precision >=0.95 and recall
>=0.85, with zero confident effects on negatives. Precision takes priority
because false effects corrupt style recipes; the lower recall target permits
abstention. Confidence >=0.8 is a heuristic acceptance score, not a calibrated
probability. For historical v4 results, all emitted labels count as claims
because v4 supplied no confidence.

Unknown counts include explicit abstentions only. Missing events remain false
negatives. Per-class unknown counts are truth events covered by an abstention;
the overall unknown count also includes activity in negatives, sometimes with
several runs per clip. Undefined precision is JSON `null`. Whip and flash remain
unsupported: their recall is reported as zero, and their unknown coverage is
tested. No accuracy threshold is silently assigned to them.

Detector v5 tests endpoint reconstruction, exposure continuity and quiet handles.
It keeps hard cuts, dissolves, wipes and short centered zooms experimental.
Moving backgrounds, low-contrast edits, long transitions and off-center zooms
can be missed. A matching scale trajectory does not prove use of an editing
preset. Real-video precision/recall, the Oct 21 one-shot audit clip, variable
frame-rate timestamps and renderer fidelity have not been validated by this set.

`schemas.py` remains unchanged. `TransitionEvidence` in the study package has
`to_dict()`/`from_dict()` and its own version. Production stores every candidate
under `provenance.transition_evidence`: evidence start/end, confidence, detector
version, reason and optional wipe direction. `observation_index` links accepted
candidates to the existing observation list; unknowns have no index and never
enter the list used by profiles. Pass 4 should adopt these fields into the shared
contract, preserve the confidence semantics and include an explicit unknown
state. The current schema's comment about confidence being absent describes the
legacy object only.

The existing test changes preserve its five-golden precision/recall assertions.
The production mock now supplies v5 evidence; the motion regression expects an
explicit unknown instead of silent omission. Frozen real-video measurements
remain labeled v4 and report `matches_current_detector=false`; mixed historical
versions still fail. They cannot be relabeled as new measurements or used to
claim real-video recall. The historical dissolve summary replays only its old
monotonicity sub-gate, not v5's reconstruction tests.
