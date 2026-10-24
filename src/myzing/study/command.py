"""`zing study <url|file>` — thin CLI wrapper around study.api.study()."""

from __future__ import annotations

import argparse
from pathlib import Path

USAGE = "zing study <url|file> [--workspace DIR] [--transitions] [--caption-geometry [--fonts]] [--json]"


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
    parser.add_argument(
        "--caption-geometry", action="store_true",
        help="measure caption polygons, appearance and motion into caption-geometry.json (offline OCR models required)",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="raw-footage mode: measure dead air, filler words, and "
             "repeated takes (S3 retake-spotting facts)",
    )
    parser.add_argument(
        "--kept-media", type=Path, default=None, metavar="FILE",
        help="A-S6: locally kept copy of the URL source (uoink keep_media) "
             "-- studied with zero refetch; unusable kept media falls back "
             "to a normal fetch with a warning",
    )
    parser.add_argument("--fonts", action="store_true",
                        help="rank locally available fonts (requires --caption-geometry; never downloads fonts)")
    parser.add_argument("--vocabulary", action="append", default=[], metavar="TERM,TERM",
                        help="exact names/terms for ASR; repeat or comma-separate (64 terms, 500 UTF-8 bytes total)")
    parser.add_argument("--brief", type=Path, help="creative brief supplying purpose and exact_spellings")
    args = parser.parse_args(argv)
    if args.fonts and not args.caption_geometry:
        parser.error("--fonts requires --caption-geometry")

    from myzing import storage
    from myzing.study.api import study
    from myzing.study.proc import MediaError

    root = storage.resolve_workspace(args.workspace)
    try:
        study_kwargs = {"workspace": root}
        if args.transitions:
            study_kwargs["detect_transitions"] = True
        if args.caption_geometry:
            study_kwargs["caption_geometry"] = True
        if args.fonts:
            study_kwargs["fonts"] = True
        if args.raw:
            study_kwargs["raw_mode"] = True
        if args.kept_media is not None:
            study_kwargs["kept_media"] = args.kept_media
        if args.vocabulary:
            study_kwargs["vocabulary"] = [term for group in args.vocabulary for term in group.split(",")]
        if args.brief:
            from myzing.brief.api import load_brief
            study_kwargs["brief"] = load_brief(args.brief)
        breakdown = study(args.source, **study_kwargs)
    except (MediaError, ValueError, OSError) as e:
        print(f"zing study: {e}")
        return 1

    if args.json:
        print(breakdown.to_json(indent=2))
        return 0

    slug = storage.slug_for(args.source)
    with storage.use_workspace(root):
        folder = storage.breakdown_dir(slug)
    m = breakdown.meta
    print(f"studied: {m.title or m.source_url}")
    print(
        f"  {m.duration:.1f}s | {len(breakdown.shots)} shots | "
        f"{len(breakdown.words)} words | {len(breakdown.captions)} captions"
    )
    if breakdown.warnings:
        print(f"  {len(breakdown.warnings)} measurement note(s) -- see breakdown.md")
    print(f"  -> {folder / 'breakdown.md'}")
    print(f"  -> {folder / 'breakdown.json'}")
    if "caption_geometry" in breakdown.provenance:
        print(f"  -> {folder / 'caption-geometry.json'}")
    return 0

