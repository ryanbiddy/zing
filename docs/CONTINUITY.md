# Complete speech and timing repair

`zing match` and `zing plan drafts` use complete speech clauses and bounded ASR timing repair by default. To retain strict whole-clip exclusion for invalid source ASR, pass `--no-repair-asr`. Python callers use `repair_asr=False`. Public inspection remains strict. Neither mode modifies the raw study or source media.

## Selection rules

The director splits at sentence punctuation (`. ! ? ;`), a pause of at least 600 ms, or a comma followed by at least 300 ms of silence. Dependent prefixes such as “if” and “when” stay with their continuation. Trailing function words, unfinished pronouns, ellipses, isolated comma-ended names and a small list of dependent openings block a complete-clause result. A final unpunctuated fragment stays flagged. The rules are conservative English heuristics; punctuation is evidence of a boundary, not proof of grammatical or semantic completeness.

Candidates must contain every clause they touch. They can include surrounding silence and cross visual cuts, but cannot trim speech to meet a shot-duration target. Must-keep moments expand to clause boundaries; a conflicting forbidden interval produces a shortage. Source timestamps must increase within each source checksum, even when clips are interleaved. The exact directive `[allow source reordering]` in the brief's `purpose` explicitly permits reordering. The directive is recorded in the saved brief and continuity report.

The bounded search first seeks three distinct drafts containing only complete clauses. If that fails, it can return flagged drafts containing incomplete source clauses. It never silently cuts a clause to make the target length. `continuity` records complete and partial clause counts, dangling endings, source-order violations and every included clause. Its score is the fraction of complete selected clauses, minus 0.25 per unapproved order violation, floored at zero. A selection with no transcribed speech has score null and status `not_applicable`; it is never graded as a perfect pass, so it cannot outrank drafts that carry speech. This is a structural score, not an editorial quality grade or ASR accuracy measurement.

Each generated caption event contains a whole selected clause. Match preparation inserts visual line wraps at word boundaries and measures the actual libass ink to fit the layout. It refuses a fit below 24 output pixels. A visual line inside a wrapped event can be a fragment; the complete event stays onscreen together. This can differ from a reference's shorter caption groups, and the comparison discloses that deviation.

## ASR repair rules

Invalid intervals include zero/negative durations, negative/nonfinite timestamps, out-of-range endpoints and overlap with preceding valid words. Consecutive invalid words form a repair span. Interpolation uses the gap between surrounding valid words; at a media edge, it uses the edge and the available neighbor. The interval must be positive, no longer than 2 seconds, contain at most 12 words, and leave at least 20 ms per word.

When packed words leave no gap, the repair may redistribute one valid neighbor on each side along with the invalid words. Every changed neighbor is also marked as repaired. Valid words outside that window remain unchanged. No recognizer, retry, model or network call runs during repair.

Each changed word retains `timing.original`, method `bounded_neighbor_interpolation`, and a `timing.adjustments` entry containing `repaired: true`, the window and prior provenance. Subsequent timeline mapping retains that history. Nonfinite originals are stored as their literal string representation so the derived ledger remains valid JSON. These timings are estimates, not recovered measurements.

If the bounds cannot be met, only the unsafe span between trusted neighbors is quarantined. Selection cannot cross that span; unrelated parts of the clip remain eligible. The inventory and match comparison list every repair and quarantined interval under `source_asr` / `asr_repair`. An entirely invalid transcript can leave no usable span, resulting in a footage shortage.

## Pacing, text roles and status

The pacing comparison retains both pixel-detected output shots and the source studies' cuts mapped through selected spans. Internal source cuts count even when output padding defeats the pixel detector. Either measurement missing the reference median by more than 10% flags pacing as unmet. The first cut uses a two-frame tolerance. A search miss is not proof that no human edit could meet the brief.

Before recipe extraction, OCR events receive a rule-based `caption`, `title`, `credit` or `scene_text` role. Features include coarse position, event duration, track persistence/motion, overlap with timed speech and lexical agreement with that speech. Credit vocabulary without speech agreement, persistent overlays and unmatched signage cannot supply caption style. Speech-aligned text requires at least 15% speech overlap and 60% lexical agreement; a recurring lower anchor permits 50% overlap plus 30% agreement when static. Sustained centered text outside speech is a title candidate. Uncertain events fall into `scene_text` and remain disclosed. Missing geometry is recorded as unmeasured.

Only caption-role events and unambiguously associated tracks supply caption timing, fonts or geometry. Recipe facts and comparisons retain role counts and feature evidence. Roles are heuristic, not annotated ground truth; subtitles with poor ASR or translation may be conservatively excluded.

Visible summaries say **render complete** beside failed style dimensions. Existing JSON `status: ready` and `ready` counts remain for API compatibility and indicate technical completion only. Unverified dimensions never establish an exact style match. Warning prose groups font and caption failures by cause; JSON retains the individual warnings.

Regression coverage is in `tests/test_continuity.py` and `tests/test_continuity_ffmpeg.py`. Media is generated locally; authored ASR and labeled OCR negatives need no downloaded models. The full gate is:

```text
ZING_REQUIRE_OCR=1 ZING_REQUIRE_FFMPEG=1 uv run --frozen pytest -q -m ffmpeg --expected-ffmpeg-tests 353
```
