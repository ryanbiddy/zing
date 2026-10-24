"""Validate release version parity and extract its changelog without network."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def release_version(root=ROOT):
    project = (root / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'^version = "([^"]+)"$', project, re.M).group(1)
    module = ast.parse((root / "src/myzing/__init__.py").read_text(encoding="utf-8"))
    runtime = next(ast.literal_eval(n.value) for n in module.body
                   if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__version__" for t in n.targets))
    listing = json.loads((root / "server.json").read_text(encoding="utf-8"))
    bundle = json.loads((root / "packaging/mcpb/manifest.json").read_text(encoding="utf-8"))
    surfaces = {"runtime": runtime, "registry": listing["version"], "mcpb": bundle["version"]}
    surfaces.update({f"registry package {i}": p["version"] for i, p in enumerate(listing["packages"])})
    for folder in ("prompts", "src/myzing/_data/prompts"):
        for path in (root / folder).glob("*.md"):
            found = re.search(r"^release_version: (.+)$", path.read_text(encoding="utf-8"), re.M)
            surfaces[str(path.relative_to(root))] = found.group(1) if found else None
    lock = (root / "uv.lock").read_text(encoding="utf-8")
    surfaces["uv.lock"] = re.search(r'\[\[package\]\]\nname = "myzing"\nversion = "([^"]+)"', lock).group(1)
    for name, actual in surfaces.items():
        if actual != version:
            raise ValueError(f"{name}: {actual!r} != release {version!r}")
    for path in (root / "docs/DIRECTORY-SUBMISSIONS.md", root / "docs/RELEASING.md"):
        pins = re.findall(r'myzing(?:\[[a-z,]+\])?==([\w.]+)', path.read_text(encoding="utf-8"))
        if not pins or any(pin != version for pin in pins):
            raise ValueError(f"{path.name}: stale or missing install pin {pins}")
    for path in (root / "docs/CONNECT.md", root / "docs/RELEASING.md"):
        pins = re.findall(r'myzing-([\w.]+)-py3-none-any\.whl', path.read_text(encoding="utf-8"))
        if not pins or any(pin != version for pin in pins):
            raise ValueError(f"{path.name}: stale or missing wheel pin {pins}")
    return version


def notes(version, text):
    match = re.search(rf"^## {re.escape(version)}(?:[ \t]+[^\n]*)?\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not match or not match.group(1).strip():
        raise ValueError(f"Missing changelog section for {version}")
    return match.group(1).strip() + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    version = release_version()
    args.output.write_text(notes(version, (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")), encoding="utf-8")
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write(f"version={version}\n")
    print(version)


if __name__ == "__main__":
    main()
