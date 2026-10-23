# Evaluation contracts

## Performance budget

`tools/eval/performance.py` preserves the original study budget: low
single-digit minutes for a 30–60 second reference on the development PC
with GPU transcription, with an honest CPU fallback. This is an evaluation
target, not a measured promise for every machine.

The evaluator uses a 300-second target and a 600-second defect threshold.
For inputs longer than 60 seconds, both scale linearly with duration.
A 20-minute study of a short reference fails the gate even if its output
is otherwise correct. These thresholds are unchanged by HYG1.
