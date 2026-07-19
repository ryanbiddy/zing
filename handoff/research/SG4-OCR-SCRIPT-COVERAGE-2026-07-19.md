# SG-4 scan: OCR script coverage (SW-1's unsupported_script class)

Scope: the sweep's SW-1 finding gave us a labeled failure class —
real Cyrillic text fabricated into confident Latin junk. This scan
asks whether trending OSS offers a license-clean fix path. Two
targets scanned, one deliberately skipped.

## surya (datalab-to) — REJECT

90+ language OCR with strong multilingual benchmarks — technically
the closest fit for the failure class. Rejected on license: the CODE
is Apache-2.0, but the WEIGHTS are cc-by-nc-sa / OpenRAIL-M with a
<$5M-revenue waiver and a no-competing-with-their-API clause. Zing is
MIT; a weights license with commercial restrictions travels with the
product no matter what the code license says. Not adoptable, not
vendorable. (Also a useful precedent: dep vetting must check weights
licenses separately from code licenses.)

## PP-OCRv5/v6 multilingual rec models via rapidocr — ADOPT-CANDIDATE (gated)

The Paddle family (Apache-2.0 end to end, weights included) ships
per-script and multilingual recognition models — PP-OCRv5 covers 106
languages incl. Russian/Cyrillic, Greek, Thai; PP-OCRv6's training
spans Latin, CJK, Arabic, Cyrillic, Devanagari. rapidocr (already our
backend) can load alternate rec models; upstream integration of the
v5 small-language models is tracked in RapidAI/RapidOCR#499.
Fix shape when promoted: detect non-Latin-dominant frames (or run a
cheap script classifier on low-lexicality reads) and re-recognize
with the matching script model — flag, never silently swap, per
measurement honesty.
**Gate: do NOT adopt ahead of evidence.** P-C2's calibration pack now
contains exactly the ground truth needed to measure whether a
script-aware second pass separates unsupported_script from
likely_caption without recall loss — that is the promotion bar, and
it is Lane C's harness half. Filed as the concrete candidate signal.

## whisperX forced alignment — SKIPPED (already dispositioned)

transcribe.py's docstring already records the standing decision:
whisperX is the upgrade IF the eval harness shows word-timing misses.
The sweep's 7 live cells showed timings meeting the bar (and SW-4's
seam fix addressed the one ordering defect). Re-scanning it each
cycle would be churn; the trigger condition is written down and has
not fired.
