# Explain a video

Use `zing explain ./clips/reference.mp4 --out ./style-card` to create card.json,
card.md, card.png and style-recipe.json. For a draft comparison, append
`--against ./project/draft-A.mp4`. MCP `zing_explain` returns paths and summary
metadata with the same offline model policy.

The card opens with "What a viewer notices" (measured facts in editor words) and
"Get this look" (the zing match, plan drafts and color commands with the card's
own paths); relay those first. Read facts, confidence and unknowns separately.
Low-score font candidates are substitutes. Color statistics include lighting and
objects; a fitted LUT is an approximation. OCR can read scene text as well as
subtitles, and the readable card quotes only confident, word-like text. A close
comparison covers only its named metrics and tolerances, never complete style
fidelity.

URL acquisition needs explicit download consent (`--allow-download` in CLI or
`offline=false` in MCP). A `uoink:<id>` resolves only that requested item's verified
kept media, with no URL fallback. Do not browse the library to explain a file.
Models are never downloaded by explain. Missing optional measurements stay unknown.

Keep outputs outside input folders and use a fresh output directory. Read the
returned error when ok is false. A failed run removes what it wrote, and an
interrupted run can be repeated with the same output folder.
