# Frozen OCR measurements

`ocr-calibration/labels/` and `ocr-calibration/frozen/` contain seven paired
cells: 15,999 labeled lines, with OCR strings replaced by hashes and token
counts. HYG1 copied these SEC1-scrubbed files without changing their bytes.

Run `uv run python tools/eval/research/pc2_baseline.py` from the repository
root to reproduce the confidence, position and persistence scores.
To regenerate measurements from media you are authorized to use, run
`uv run python -m tools.eval.research.ocr_freeze WORKSPACE SLUG`.
The freezer writes to `ocr-calibration/frozen/` here.

The five lexical calibration cases still require original OCR strings and
remain skipped. See [the coverage record](../../PRIVATE-FIXTURES.md).
