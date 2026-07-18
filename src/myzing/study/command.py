"""`zing study <url|file>` — thin CLI wrapper around study.api.study()."""

from __future__ import annotations

import argparse
from pathlib import Path

USAGE = "zing study <url|file> [--workspace DIR] [--transitions] [--json]"


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="zing study",
        description="Measure a short video into an edit breakdown.",
    )
    parser.add_argument("source", help="video URL (tiktok/instagram/youtube) or local file")
    parser.add_argument(
        "--workspace", type=Path, default=None,
        help="override the zing workspace directory (default: ~/.zing or $ZING_HOME)",
    )
    parser.add_argument(
        "--json", action="store_true", help="print the full breakdown JSON to stdout"
    )
    parser.add_argument(
        "--transitions",
        action="store_true",
        help="run the opt-in synthetic-calibrated transition detector",
    )
    args = parser.parse_args(argv)

    from myzing import storage
    from myzing.study.api import study
    from myzing.study.proc import MediaError

    try:
        study_kwargs = {"workspace": args.workspace}
        if args.transitions:
            study_kwargs["detect_transitions"] = True
        breakdown = study(args.source, **study_kwargs)
    except MediaError as e:
        print(f"zing study: {e}")
        return 1

    if args.json:
        print(breakdown.to_json(indent=2))
        return 0

    slug = storage.slug_for(args.source)
    with _workspace_env(args.workspace):
        folder = storage.breakdown_dir(slug)
    m = breakdown.meta
    print(f"studied: {m.title or m.source_url}")
    print(
        f"  {m.duration:.1f}s · {len(breakdown.shots)} shots · "
        f"{len(breakdown.words)} words · {len(breakdown.captions)} captions"
    )
    if breakdown.warnings:
        print(f"  {len(breakdown.warnings)} measurement note(s) — see breakdown.md")
    print(f"  -> {folder / 'breakdown.md'}")
    print(f"  -> {folder / 'breakdown.json'}")
    return 0


def _workspace_env(workspace: Path | None):
    from myzing.study.api import _workspace_override

    return _workspace_override(workspace)
