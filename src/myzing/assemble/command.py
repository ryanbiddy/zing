"""`zing assemble <slug> --direction <file>` — CLI over draft_for_slug
(gate defect D-7: Track 1's direction→draft step was unreachable outside
Python imports)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="zing assemble",
        description="Draft an EDL from a studied video and a direction "
                    "judgment (keeper trims + measured word-timed captions).",
    )
    parser.add_argument("slug", help="a studied video's slug")
    parser.add_argument(
        "--direction", type=Path, required=True,
        help="direction judgment JSON (the prompts/direct.md contract)",
    )
    parser.add_argument("--workspace", type=Path, default=None)
    parser.add_argument("--json", action="store_true",
                        help="print the draft EDL JSON to stdout")
    args = parser.parse_args(argv)

    from myzing import storage
    from myzing.assemble.draft import AssembleError, draft_for_slug

    try:
        direction = json.loads(args.direction.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"zing assemble: unreadable direction file: {exc}")
        return 1

    context = (
        storage.use_workspace(args.workspace)
        if args.workspace is not None
        else storage.use_workspace(storage.workspace_root())
    )
    try:
        with context:
            result = draft_for_slug(args.slug, direction)
            target = storage.breakdown_dir(args.slug) / "draft-edl.json"
    except (AssembleError, FileNotFoundError, storage.SlugError) as exc:
        print(f"zing assemble: {exc}")
        return 1

    if args.json:
        print(result.edl.to_json(indent=2))
        return 0
    edl = result.edl
    total = sum(c.src_out - c.src_in for c in edl.clips)
    print(
        f"draft EDL: {len(edl.clips)} clip(s), {total:.1f}s, "
        f"{len(edl.captions)} caption(s), {edl.width}x{edl.height}"
    )
    for w in result.warnings:
        print(f"  note: {w}")
    print(f"  -> {target}")
    return 0
