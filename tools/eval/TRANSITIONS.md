# Transition evaluation: detector v6

V6 recovers all 22 labeled real cuts, up from v5's 15/22, with no false
positives in the 45.75 reviewed seconds. It recovers the calibration dissolve
but still misses the held-out title dissolve. Held-out results are **7/7 cuts
and 0/1 dissolves** across five clips; this does not establish general optical
dissolve recall. The 48-case synthetic gate still passes at 100% precision and
recall for supported classes, with no confident effects on negatives.

The checked-in [results](real/transitions-v6-results.json) retain per-class
counts, per-clip misses, artifact hashes and the decision freeze. The
[real-video report](real/REAL-EVAL-2026-10.md#t6-transition-update) gives the
before/after tables and remaining miss PNG. Historical v4 records and
[V1's v5 results](real/results.json) have `matches_current_detector=false`.

## Real clip split and reproduction

[transition-split.json](real/transition-split.json) was recorded before tuning;
the [split receipt](real/transition-split-receipt.json) records its hash and
the baseline source hashes. Calibration uses `korky`, `tos-lab`, `tos-credits`,
`duck-classroom`, and `nasa-opening` (23.75 reviewed seconds; 15 cuts and one
dissolve). Held-out uses `tos-dialogue`, `tos-memory`, `duck-titles`,
`duck-street`, and `nasa-montage` (22 seconds; seven cuts and one dissolve).
No event from a held-out clip was used to select thresholds. The supplied V1
failure report was already known, and partitions share source works: this is
a clip-level tuning holdout, not a blind or source-disjoint benchmark.

Use the existing pinned media root read-only, or explicitly provision an owned
root with `run_real_eval.py --download`. No automatic download occurs here:

```console
uv run --frozen python -m tools.eval.real.run_transition_eval --root E:/AI/projects/zing/worktrees/v1-realeval/zing-workspace/real-eval --out zing-workspace/t6/replay-calibration
uv run --frozen python -m tools.eval.real.run_transition_eval --root E:/AI/projects/zing/worktrees/v1-realeval/zing-workspace/real-eval --split held_out --lock tools/eval/real/transition-v6-lock.json --out zing-workspace/t6/replay-held-out
```

Each output directory must be new. Clip SHA-256 must match both manifest and
labels. Held-out inference checks the frozen decision AST and input hashes;
changing a decision rule requires a new evaluation protocol, not overwriting
the lock. The AST hash excludes only the published `VALIDATION_STATUS` and
warning text, which were populated after measurement. It includes thresholds
and both production modules. The lock also pins the evaluator and scorer.
`--observations <V1 run-01/observations.json>` rescores the frozen v5 baseline
with the same split and unchanged matching tolerances.

The opt-in local test uses the pinned calibration classroom clip, without a
download or model dependency:

```powershell
$env:ZING_REAL_TRANSITIONS = '1'
$env:ZING_REAL_EVAL_ROOT = 'E:\AI\projects\zing\worktrees\v1-realeval\zing-workspace\real-eval'
uv run --frozen pytest -q tests/test_transition_v6.py -m real_media
```

`real_media` is registered separately from the mandatory FFmpeg marker so a
machine without these local assets reports a named skip. Corrupt media fails.
The mandatory CI FFmpeg baseline remains **212** tests; the transition
detector itself adds no mandatory FFmpeg test.

## Synthetic regression gate

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

## What v6 measures

V6 combines grayscale histogram distance, block SSIM contrast/structure loss,
and edge replacement on area-averaged frames. Local median motion and histogram
baselines tolerate grain and neighboring montage cuts. Adjacent peaks from a
short archival blend become one cut candidate. Persistent full- or limited-range
black gets a separate endpoint check; affine lighting changes and temporary
returns to the same scene remain unknown. Rapid translation on both sides of a
discontinuity preserves abstention for unsupported whip pans.

The original strict reconstruction path still handles synthetic dissolves,
wipes and centered zooms with quiet handles. A separate 0.4–1.5 s optical
window search permits limited handle motion. It requires monotone blend
fractions, distributed brightening and darkening, changed spatial structure,
and a worse fit as scene translation. It runs independently of active runs,
so a cut elsewhere in a moving clip cannot suppress a gradual candidate.
Evidence windows include the tested anchors; optical endpoints remain
approximate. The classroom detection is 7.000–7.700 s against the provisional
6.833–7.633 s label (IoU 0.731; worst endpoint error 0.167 s), passing the
unchanged IoU gate but exceeding the label's stated 0.10 s uncertainty.

No dependency was added: these features use the standard library and the
existing FFmpeg decoder. Confidence remains a heuristic evidence score, not
a probability. Low-contrast title changes, chroma-only cuts, very fast edits,
long transitions, off-center zooms and variable-frame-rate timing remain
limitations. No editing preset or original project is recovered from pixels.

`schemas.py` remains unchanged. `TransitionEvidence` in the study package has
`to_dict()`/`from_dict()` and its own version. Production stores every candidate
under `provenance.transition_evidence`: evidence start/end, confidence, detector
version, reason and optional wipe direction. `observation_index` links accepted
candidates to the existing observation list; unknowns have no index and never
enter the list used by profiles. The [Composition v2 contract](../../docs/COMPOSITION-V2.md)
reuses this evidence in `TransitionRecipe.observation`, preserving confidence
and explicit unknown signatures. The current schema's comment about confidence
being absent describes the legacy object only.

The existing test changes preserve its five-golden precision/recall assertions.
The production mock now supplies v6 evidence; the motion regression expects an
explicit unknown instead of silent omission. Frozen real-video measurements
remain labeled v4 and report `matches_current_detector=false`; mixed historical
versions still fail. They cannot be relabeled as current measurements or used
to claim current real-video recall. The historical dissolve summary replays
only its old monotonicity sub-gate, not the v5/v6 reconstruction tests.
