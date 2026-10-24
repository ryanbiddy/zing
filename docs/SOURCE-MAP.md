# Source cuts used by planning

Study keeps its public `shots`, pacing summaries, and keyframes unchanged.
It also writes `provenance.source_map`, a version 1 record with the method
`adaptive-and-content-confirmed-v2`. The director splits the original shots at
accepted extra boundaries. Match uses those splits when it plans and reports
source-mapped pacing. Rendered verification runs the same confirmation on the
encoded output independently, without importing the source or planned cuts.

The extra pass uses AdaptiveDetector's existing thresholds (adaptive ratio 3,
content score 15) with a two-frame minimum, fed exactly as `scenedetect.detect`
feeds it, from the same single decode that supplies the confirmation
thumbnails. It also proposes strong thumbnail
HSV changes (score at least 25) to recover cuts suppressed by adaptive
averaging. These content-only candidates need a larger picture difference
(at least 0.12), an isolated peak (1.4 times both adjacent differences), and
more than two frames of separation from an existing boundary.
Each new candidate is checked on
nine decoded frames, resized to 192 pixels wide. Confirmation requires a
persistent isolated frame difference and a histogram change. Brief returns,
blank flash/fade endpoints, exposure changes, and changes explained by
translation are rejected. So are tone changes: when per-channel histogram
matching maps one frame onto the other with a residual under 0.3 of the
picture's own spread, a strobe, light switch or clipped exposure explains the
change (review corpus: strobes 0.08-0.20, confirmed cuts 0.47 and above).
Five- and six-frame shots remain eligible.

Each recorded candidate has its zero-based frame, acceptance, confidence, and
numeric evidence, including frame difference, peak ratio, persistence,
histogram distance, structure correlation, tone-matched residual and
translation residual. Every accepted cut is recorded. Rejections are counted
in `rejected_counts` by proposal and reason; only the 64 strongest rejected
changes keep full evidence, so shaky or strobing footage cannot grow the
breakdown without bound. MCP `get_breakdown` with `detail="summary"` reports
the map's accepted frames and counts; `detail="full"` carries the evidence. Seconds
are `frame / fps` on the study's normalized CFR clock. “High” confidence means
the heuristic checks passed; it is not a calibrated probability.

The map records its base cuts, duration, frame rate, method, and version.
The director rejects a map that disagrees with its study's clock or base cuts.
Historical studies without a map retain their original shots. A failed fine
pass records `unmeasured`, emits a warning, and retains the original evidence.
Run `zing study <clip> --raw --workspace <project>` to refresh an old study.
Match keys its source-study and rendered-restudy checkpoints on the map
method, so a changed fine pass is recomputed on `--resume`; a map with another
method is refused with a restudy hint.

Cost is one more full decode, with memory bounded by the nine-frame window.
On a 10-minute 1080p30 source (Windows, Oct 23) the public detector took
39.6 s and the fine pass 64.5 s, with a 215 MB peak working set and a 32 KB
map. A shaky, noisy version of the same edit took 103.7 s; its 14,667
rejections were counted and the map stayed at 85 KB.

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
boundary scorer, and writes before/after counts plus each recorded candidate's
evidence. It does not expand the labeled windows or treat detector output as
truth. For the transition corpus, the authored midpoint of a whip-pan cut is
scored as a hard boundary; dissolves, wipes, and flashes are not hard cuts.
