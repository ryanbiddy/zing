"""The Zing prompt pack: loading, and the ``zing prompt`` CLI.

The pack is markdown files with minimal YAML frontmatter
(``name``/``description``/``version``/``required_keys``) living in the
repo-root ``prompts/`` directory (``ZING_PROMPTS_DIR`` overrides — used by
tests and nonstandard installs). It is served three ways: MCP prompts
capability, the ``get_prompt`` MCP tool, and ``zing prompt <name>`` here.

``required_keys`` in a prompt's frontmatter is a contract: the MCP
``save_judgment`` tool rejects judgments for that section that lack any of
those keys. Version bumps follow semver — major = output-contract break.

Wheel/.mcpb packaging of the pack is queued (B-Q2); this loader's repo-
relative fallback is the S1 checkout reality.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

PROMPTS_DIR_ENV = "ZING_PROMPTS_DIR"


def prompts_dir() -> Path:
    override = os.environ.get(PROMPTS_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parents[2] / "prompts"


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Minimal YAML-ish frontmatter parser (stdlib only).

    Understands ``key: value`` lines and inline lists ``key: [a, b]`` —
    exactly what the pack uses. Returns (meta, body).
    """
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, Any] = {}
    for line in parts[1].splitlines():
        m = re.match(r"^(\w[\w-]*):\s*(.*)$", line.strip())
        if not m:
            continue
        key, value = m.group(1), m.group(2).strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key] = [v.strip() for v in value[1:-1].split(",") if v.strip()]
        else:
            meta[key] = value.strip('"')
    return meta, parts[2].lstrip("\n")


def load_prompt(name: str) -> tuple[dict[str, Any], str] | None:
    """(frontmatter meta, full text incl. frontmatter) or None if absent."""
    if not re.fullmatch(r"[a-z0-9_-]+", name or ""):
        return None
    path = prompts_dir() / f"{name}.md"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    meta, _body = parse_frontmatter(text)
    return meta, text


def available_prompts() -> list[str]:
    d = prompts_dir()
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.md"))


def run(argv: list[str]) -> int:
    """``zing prompt <name>`` — print a pack prompt for the paste flow."""
    if not argv or argv[0] in ("-h", "--help"):
        names = available_prompts()
        listing = ", ".join(names) if names else "(none found)"
        print(f"usage: zing prompt <name>\n\navailable prompts: {listing}")
        return 0 if argv else 2
    name = argv[0]
    loaded = load_prompt(name)
    if loaded is None:
        names = available_prompts()
        if names:
            print(
                f"zing prompt: no prompt named '{name}' — "
                f"available: {', '.join(names)}"
            )
        else:
            print(
                f"zing prompt: no prompt pack found (looked in "
                f"{prompts_dir()}) — set {PROMPTS_DIR_ENV} or reinstall Zing"
            )
        return 1
    _meta, text = loaded
    print(text)
    return 0
