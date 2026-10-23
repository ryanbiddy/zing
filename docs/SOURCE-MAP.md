# Source cuts used by planning

Study keeps its public `shots`, pacing summaries, and keyframes unchanged.
It also writes `provenance.source_map`, a version 1 record with the method
`adaptive-and-content-confirmed-v1`. The director splits the original shots at
accepted extra boundaries. Match uses those splits when it plans and reports
source-mapped pacing. Rendered verification runs the same confirmation on the
encoded output independently, without importing the source or planned cuts.

The extra pass uses AdaptiveDetector's existing thresholds (adaptive ratio 3,
content score 15) with a two-frame minimum. It also proposes strong thumbnail
HSV changes (score at least 25) to recover cuts suppressed by adaptive
averaging. These content-only candidates need a larger picture difference
(at least 0.12), an isolated peak (1.4 times both adjacent differences), and
more than two frames of separation from an existing boundary.
Each new candidate is checked on
nine decoded frames, resized to 192 pixels wide. Confirmation requires a
persistent isolated frame difference and a histogram change. Brief returns,
blank flash/fade endpoints, exposure changes, and changes explained by
translation are rejected. Five- and six-frame shots remain eligible.

Each candidate records its zero-based frame, acceptance, confidence, and
numeric evidence, including frame difference, peak ratio, persistence,
histogram distance, structure correlation, and translation residual. Seconds
are `frame / fps` on the study's normalized CFR clock. “High” confidence means
the heuristic checks passed; it is not a calibrated probability.

The map records its base cuts, duration, frame rate, method, and version.
The director rejects a map that disagrees with its study's clock or base cuts.
Historical studies without a map retain their original shots. A failed fine
pass records `unmeasured`, emits a warning, and retains the original evidence.
Run `zing study <clip> --raw --workspace <project>` to refresh an old study.
Match invalidates its source-study checkpoint when the map method changes.

This is an additive map. Existing false positives in the public detector are
not removed, and genuine cuts below its content/adaptive thresholds can still
be missed. Very short flashes and very short shots can be visually ambiguous;
confirmation favors precision. Candidate confidence does not certify the
whole map or a style match.

Offline evaluation against the pinned V1 label windows and the generated
transition corpus:

```powershell
$env:UOINK_URL='http://127.0.0.1:1'
uv run --frozen python -m tools.eval.source_map --clips zing-workspace/licensed-v1/clips --out zing-workspace/source-map-eval
```

The evaluator checks input hashes, uses the existing two-frame, one-to-one
boundary scorer, and writes before/after counts plus every candidate's
evidence. It does not expand the labeled windows or treat detector output as
truth. For the transition corpus, the authored midpoint of a whip-pan cut is
scored as a hard boundary; dissolves, wipes, and flashes are not hard cuts.
