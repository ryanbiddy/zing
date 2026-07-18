"""Build the Zing .mcpb bundle for one-click Claude Desktop install (B-Q9).

Stages exactly what the bundle needs into a clean directory, then packs it
with the official MCPB CLI:

    python packaging/build_mcpb.py            # stage + pack -> dist/myzing.mcpb
    python packaging/build_mcpb.py --stage-only   # stage, skip npx pack (CI)

The bundle is `server.type: "uv"`: the host runs
``uv run --directory <bundle> --extra mcp python -m myzing.cli serve-mcp``,
so dependencies resolve from pyproject.toml at install time — nothing
compiled is bundled (the pydantic-doesn't-bundle landmine from
handoff/research/R1-lane-b-surface-judgment.md §1a). The prompt pack rides
inside the bundle and is pinned via ZING_PROMPTS_DIR, so prompt lookup
never depends on how uv materializes the package.

Requires: Node (npx) for the pack step; network on first pack (downloads
@anthropic-ai/mcpb). The staging step is offline and tested in CI.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# (source relative to repo root, required)
STAGE_FILES = [
    ("packaging/mcpb/manifest.json", True),
    ("pyproject.toml", True),
    ("README.md", True),
    ("LICENSE", True),
]
STAGE_TREES = [
    ("src/myzing", True),
    ("prompts", True),
]


def stage(build_dir: Path) -> Path:
    """Copy the bundle contents into build_dir (wiped first). Returns it."""
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True)

    for rel, required in STAGE_FILES:
        src = REPO / rel
        if not src.is_file():
            if required:
                raise FileNotFoundError(f"bundle needs {rel} and it is missing")
            continue
        dest_name = "manifest.json" if rel.endswith("manifest.json") else src.name
        shutil.copy2(src, build_dir / dest_name)

    for rel, required in STAGE_TREES:
        src = REPO / rel
        if not src.is_dir():
            if required:
                raise FileNotFoundError(f"bundle needs {rel}/ and it is missing")
            continue
        shutil.copytree(
            src,
            build_dir / rel,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    return build_dir


def pack(build_dir: Path, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["npx", "--yes", "@anthropic-ai/mcpb", "pack", str(build_dir), str(out)]
    result = subprocess.run(cmd, shell=(sys.platform == "win32"))
    if result.returncode != 0:
        raise SystemExit(
            f"mcpb pack failed (exit {result.returncode}) — is Node installed? "
            "The staging step succeeded; inspect the staged bundle at "
            f"{build_dir}"
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage-only",
        action="store_true",
        help="stage the bundle tree but skip the npx pack step (offline/CI)",
    )
    parser.add_argument(
        "--build-dir",
        type=Path,
        default=REPO / "dist" / "mcpb-stage",
        help="staging directory (wiped on each run)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO / "dist" / "myzing.mcpb",
        help="output bundle path",
    )
    args = parser.parse_args(argv)

    build_dir = stage(args.build_dir)
    print(f"staged bundle tree: {build_dir}")
    if args.stage_only:
        print("(--stage-only: skipping npx pack)")
        return 0
    bundle = pack(build_dir, args.out)
    print(f"bundle: {bundle}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
