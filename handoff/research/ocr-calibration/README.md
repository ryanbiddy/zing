# P-C2 calibration measurements

The seven cells retain per-frame timestamps, confidence, geometry, frame
hashes and manual class labels. Source URLs and OCR backend versions remain
in the frozen headers. No redistribution license is recorded for these
sources, so SEC1 removed their OCR text on 2026-10-22.

Each former text field is now `text_sha256`, `normalized_text_sha256` and
`token_count`. The first hash covers the exact UTF-8 string. The second uses
`" ".join(text.upper().split())`; token count uses `len(text.split())`.
Hashes are provenance anchors, not encryption or anonymity guarantees.
Each header records the removed-text count and a joined-text hash.

`pc2_baseline.py` still calculates the confidence, position and persistence
scores from these measurements. Token counts preserve the candidate rule;
normalized hashes preserve its equality groups. Geometry, label classes and
timestamps were not changed.

Fuzzy clustering needs the original strings. Five empirical cases therefore
skip with registered reason SEC1-OCR; generated cases exercise overlay
exclusion and caption retention. See
[the coverage record](../../../tests/PRIVATE-FIXTURES.md).

Regenerate measurements from media you are authorized to use, from the repo
root:

```sh
uv run python -m handoff.research.ocr-calibration.freeze WORKSPACE SLUG
```

The freezer writes only hashes and measurements, including on regeneration.
Source media and frames belong under ignored `zing-workspace/`. A licensed
replacement corpus with independent labels is needed to restore the original
lexical calibration checks.
