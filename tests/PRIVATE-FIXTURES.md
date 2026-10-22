# SEC1-OCR: unavailable lexical calibration

Five cases in `test_overlay_rule_against_labels.py` need the original OCR
strings to run fuzzy text clustering: four caption-recall cells and one
long-form HUD cell. No redistribution permission is recorded for that text.
The cases remain registered as `requires_private_ocr` and skip with reason
`SEC1-OCR`. Hashes cannot reproduce fuzzy matching, so the public suite does
not claim to rerun those five empirical checks.

Generated overlay regressions in the same module exercise caption retention,
persistent-overlay exclusion and changing HUD text. They cover the code's
behavior, not the historical corpus's measured accuracy. To restore the five
empirical checks, supply a licensed replacement corpus, label it independently,
update the calibration claims and remove the skip decorators in review.

The public OCR corpus retains all geometry, confidence, timestamps and class
labels. `pc2_baseline.py` uses token counts and normalized-text hashes to
recompute the historical confidence, position and persistence scores. Prompt
contamination checks still run against the retained labels.
