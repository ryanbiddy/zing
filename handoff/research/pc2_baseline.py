"""Regenerate the figures in P-C2-BASELINE-2026-07-20.md.

Reads the frozen labels in `ocr-calibration/labels/` and reports:
the confidence-only baseline P-C2 exists to challenge, the candidate
position+token rule, and the hold-out check across captioned cells.

Read-only, stdlib only, no network, no myzing import. Run from the
repo root:

    python handoff/research/pc2_baseline.py
"""

from __future__ import annotations

import collections
import json
import statistics
from pathlib import Path

CAPTION = "likely_caption"
LABELS_DIR = Path(__file__).resolve().parent / "ocr-calibration" / "labels"


def load() -> list[dict]:
    rows: list[dict] = []
    for path in sorted(LABELS_DIR.glob("*.jsonl")):
        slug = path.stem
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if "label" in row:          # skip each file's header row
                row["slug"] = slug
                rows.append(row)
    return rows


def score(rows: list[dict], predicate) -> tuple[float, float, float]:
    tp = sum(1 for r in rows if predicate(r) and r["label"] == CAPTION)
    fp = sum(1 for r in rows if predicate(r) and r["label"] != CAPTION)
    fn = sum(1 for r in rows if not predicate(r) and r["label"] == CAPTION)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return prec, rec, f1


def rule(row: dict) -> bool:
    """FALSIFIED candidate, kept so the failure stays reproducible:
    lower-third position AND at least two tokens."""
    return row["y_center"] >= 0.55 and len(row["text"].split()) >= 2


def persistence_rule(row: dict) -> bool:
    """The surviving candidate: text that does NOT sit still. Watermarks
    and HUD counters persist; captions move with speech. Position-agnostic,
    so it survives the style that killed the rule above."""
    return row.get("frames", 0) <= 20 and len(row["text"].split()) >= 2


def annotate_persistence(rows: list[dict]) -> None:
    """Attach, per row, how many sampled frames carry the same text in
    that cell. Uses only the frozen text and timestamps — never the
    transcript."""
    per: dict[str, dict[str, set]] = collections.defaultdict(
        lambda: collections.defaultdict(set)
    )
    for r in rows:
        per[r["slug"]][" ".join(r["text"].upper().split())].add(r["t"])
    for r in rows:
        r["frames"] = len(per[r["slug"]][" ".join(r["text"].upper().split())])


def main() -> int:
    rows = load()
    annotate_persistence(rows)
    if not rows:
        print(f"no labels found under {LABELS_DIR}")
        return 1
    caps = [r for r in rows if r["label"] == CAPTION]
    non = [r for r in rows if r["label"] != CAPTION]
    print(f"labeled lines: {len(rows)} | captions {len(caps)} | other {len(non)}\n")

    print("composition by cell (3 of 6 cells contain zero captions):")
    per = collections.defaultdict(lambda: [0, 0])
    for r in rows:
        per[r["slug"]][0] += 1
        per[r["slug"]][1] += r["label"] == CAPTION
    for slug, (n, c) in sorted(per.items(), key=lambda kv: -kv[1][0]):
        print(f"  {slug:26} {n:6} lines, {c:4} captions")

    print("\nfinding 1 — confidence is ANTI-correlated with caption-ness:")
    print(f"  median confidence, captions : {statistics.median([r['score'] for r in caps]):.3f}")
    print(f"  median confidence, other    : {statistics.median([r['score'] for r in non]):.3f}")
    print(f"\n  {'threshold':>10} {'precision':>10} {'recall':>8}")
    for t in (0.75, 0.90, 0.95, 0.98):
        p, r, _ = score(rows, lambda row, t=t: row["score"] >= t)
        print(f"  {t:10.2f} {p:10.3f} {r:8.3f}")

    print("\nfinding 2 — two features already in the data:")
    for name, pred in (
        ("confidence >= 0.75 (ships today)", lambda r: r["score"] >= 0.75),
        ("lower-third (y >= 0.55)", lambda r: r["y_center"] >= 0.55),
        ("lower-third AND >=2 words (FALSIFIED)", rule),
        ("persists <=20 frames AND >=2 words", persistence_rule),
    ):
        p, r, f = score(rows, pred)
        print(f"  {name:34} P={p:.3f} R={r:.3f} F1={f:.3f}")

    captioned = sorted({r["slug"] for r in caps})
    print("\nhold-out across captioned cells:")
    for slug in captioned:
        p, r, _ = score([x for x in rows if x["slug"] == slug], rule)
        print(f"  test={slug:26} P={p:.3f} R={r:.3f}")

    print("\nLIMIT — caption placement in this dataset:")
    for slug in captioned:
        ys = [r["y_center"] for r in caps if r["slug"] == slug]
        print(f"  {slug:26} y min={min(ys):.2f} median={statistics.median(ys):.2f} max={max(ys):.2f}")
    print("  The y>=0.55 rule was FALSIFIED by adding youtube-fuxm3vz-keo")
    print("  (karaoke captions at y~0.38, frame-verified): it scores")
    print("  P=0.000 R=0.000 there, and aggregate recall fell 1.000 ->")
    print("  0.778. Position is style-dependent, not a caption invariant.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
