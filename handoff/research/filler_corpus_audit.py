"""Regenerate the filler precision/recall figures from any workspace.

The precision and recall notes state numbers measured over the corpus
Zing happened to study. That corpus lives in a scratch workspace, not
in the repo, so without this script the figures are assertions nobody
can re-derive — the same gap `shot_threshold_audit.py` closed for the
threshold work, and the one P-C2's freeze.py was built to avoid.

Usage:
    python filler_corpus_audit.py <workspace-root> [--word <w> ...]

<workspace-root> is any directory containing `*/breakdowns/*/
breakdown.json` (a zing workspace, or a parent of several). Reports
per-candidate hit counts AND the number of distinct transcripts each
appears in — the second number is what distinguishes a general filler
from one speaker's idiosyncrasy, which is the distinction the recall
note turns on.

Read-only, stdlib only, no network, no myzing import.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

MIN_WORDS = 100          # transcripts shorter than this are noise for frequency work

# The words the recall note ruled on. Counted here so anyone can check
# both the accepted and the REJECTED calls against their own corpus.
CANDIDATES = [
    "literally", "basically",                    # counted as fillers
    "obviously", "actually", "just", "well",     # rejected, with reasons
    "right", "yeah", "like", "um", "uh",
]


def transcripts(root: Path) -> list[tuple[str, str, list[str]]]:
    """-> [(slug, source_url, words)] for every breakdown with enough text."""
    out: list[tuple[str, str, list[str]]] = []
    seen: set[str] = set()
    for path in sorted(root.glob("*/breakdowns/*/breakdown.json")):
        slug = path.parent.name
        if slug in seen:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        words = [
            w["text"].strip(".,!?").lower()
            for w in (data.get("words") or [])
        ]
        if len(words) < MIN_WORDS:
            continue
        seen.add(slug)
        out.append((slug, str(data.get("meta", {}).get("source_url", "")), words))
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    root = Path(sys.argv[1])
    extra = [
        sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--word"
    ]
    corpus = transcripts(root)
    if not corpus:
        print(f"no transcripts with >={MIN_WORDS} words under {root}")
        return 1

    total_words = sum(len(w) for _, _, w in corpus)
    print(f"corpus: {len(corpus)} transcripts, {total_words} words\n")

    hits: dict[str, int] = collections.Counter()
    spread: dict[str, int] = collections.Counter()
    for _, _, words in corpus:
        counts = collections.Counter(words)
        for word in CANDIDATES + extra:
            if counts[word]:
                hits[word] += counts[word]
                spread[word] += 1

    print(f"{'word':12} {'hits':>6} {'transcripts':>12}   (spread is what")
    print(f"{'':12} {'':>6} {'':>12}    separates a general")
    print(f"{'':12} {'':>6} {'':>12}    filler from one")
    print(f"{'':12} {'':>6} {'':>12}    speaker's habit)")
    for word in CANDIDATES + extra:
        if hits[word]:
            print(f"{word:12} {hits[word]:6} {spread[word]:12}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
