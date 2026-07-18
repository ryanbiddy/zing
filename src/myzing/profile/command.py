"""`zing profile build|show` — thin CLI over profile.api and storage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from myzing.schemas import StatSummary, StyleProfile


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="zing profile",
        description="Build and inspect StyleProfiles from studied references.",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    build = sub.add_parser("build", help="aggregate studied slugs into a profile")
    build.add_argument("name")
    build.add_argument("slugs", nargs="+")
    build.add_argument("--genre", default="")
    build.add_argument("--platform", default="")
    build.add_argument("--workspace", type=Path, default=None)
    build.add_argument("--json", action="store_true")

    show = sub.add_parser("show", help="print a stored profile")
    show.add_argument("name")
    show.add_argument("--workspace", type=Path, default=None)
    show.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    from myzing import storage
    from myzing.profile.api import ProfileError, build_profile

    try:
        if args.action == "build":
            profile = build_profile(
                args.name,
                args.slugs,
                workspace=args.workspace,
                genre=args.genre,
                platform=args.platform,
            )
        else:
            context = (
                storage.use_workspace(args.workspace)
                if args.workspace is not None
                else storage.use_workspace(storage.workspace_root())
            )
            with context:
                profile = storage.load_profile(args.name)
    except (ProfileError, storage.SlugError) as exc:
        print(f"zing profile: {exc}")
        return 1
    except FileNotFoundError as exc:
        print(f"zing profile: {exc}")
        return 1

    if args.json:
        print(profile.to_json(indent=2))
        return 0
    print(render_text(profile))
    return 0


def _fmt(stat: StatSummary, unit: str = "s") -> str:
    if stat.n == 0:
        return "(no sources measured)"
    return (
        f"{stat.median:g}{unit} median "
        f"({stat.p25:g}–{stat.p75:g}{unit} IQR, n={stat.n})"
    )


def render_text(p: StyleProfile) -> str:
    lines = [f"profile: {p.name}"]
    if p.genre or p.platform:
        lines.append(
            "  " + " · ".join(x for x in (p.genre, p.platform) if x)
        )
    lines.append(f"  sources: {len(p.source_slugs)} "
                 f"({', '.join(p.source_slugs)})")
    lines.append(f"  duration: {_fmt(p.duration)}")
    lines.append(f"  shot length: {_fmt(p.shot_duration)}")
    lines.append(f"  first cut: {_fmt(p.time_to_first_cut)}")
    lines.append(f"  first word: {_fmt(p.time_to_first_word)}")
    lines.append(f"  first caption: {_fmt(p.time_to_first_caption)}")
    lines.append(f"  speech: {_fmt(p.speech_ratio, unit='')}")
    lines.append(
        f"  captions: {p.caption_all_caps_rate:.0%} ALL-CAPS, "
        f"~{p.caption_words_visible_mode} word(s) visible at a time"
    )
    lines.append(f"  music present: {p.music_present_rate:.0%} of measured sources")
    if p.cuts_per_10s_curve:
        medians = " ".join(f"{s.median:g}" for s in p.cuts_per_10s_curve)
        lines.append(f"  cut curve (10 relative buckets, median): {medians}")
    if p.transition_kind_counts:
        kinds = ", ".join(
            f"{kind.replace('_', ' ')}×{count}"
            for kind, count in p.transition_kind_counts.items()
        )
        lines.append(f"  transitions: {kinds}")
    judged_sections = sorted(k for k in p.judged if k != "_meta")
    if judged_sections:
        lines.append(f"  judged sections: {', '.join(judged_sections)}")
    if p.unjudged_source_slugs:
        lines.append(
            "  UNJUDGED sources: " + ", ".join(p.unjudged_source_slugs)
        )
    if p.warnings:
        lines.append("  measurement notes:")
        lines += [f"    - {w}" for w in p.warnings]
    return "\n".join(lines)
