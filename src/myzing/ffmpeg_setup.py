"""Inspect installed FFmpeg and offer a consented OS package-manager install.

No binaries are downloaded by Zing. Probes are uncached so a repaired build at
the same path is checked again after installation.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys


MIN_VERSION = (6, 0)
# The delivery capabilities exercised by the cross-platform CI gates.
REQUIRED_FILTERS = frozenset({
    "drawtext", "sidechaincompress", "lut3d", "xfade", "acrossfade", "zoompan",
})


def install_plan() -> dict:
    """Select a fixed argv, never a shell command derived from user input."""
    notes = "Restart your terminal after installation, then run zing doctor."
    alternatives = []
    if sys.platform == "win32":
        argv = ["winget", "install", "--id", "Gyan.FFmpeg", "-e"]
        alternatives = ["choco install ffmpeg-full"]
    elif sys.platform == "darwin":
        argv = ["brew", "install", "ffmpeg-full"]
        notes = ('ffmpeg-full is keg-only. After installation run '
                 '`export PATH="$(brew --prefix ffmpeg-full)/bin:$PATH"`, '
                 'add that line to ~/.zprofile, then run zing doctor.')
    elif sys.platform.startswith("linux"):
        if shutil.which("dnf") and not shutil.which("apt"):
            argv = ["sudo", "dnf", "install", "ffmpeg"]
            notes = ("Requires a repository providing full FFmpeg, such as RPM Fusion on Fedora. "
                     "Fedora's ffmpeg-free may lack libx264. Zing does not enable repositories. "
                     "Run zing doctor after installation.")
        else:
            argv = ["sudo", "apt", "install", "ffmpeg"]
        alternatives = ["sudo dnf install ffmpeg (full-codec repository required)"]
    else:
        argv = []
        notes = "Install FFmpeg 6+ with libx264 and libass through your OS package manager."
    return {"version": 1, "argv": argv, "command": " ".join(argv),
            "alternatives": alternatives, "notes": notes}


def install_hint() -> str:
    plan = install_plan()
    alternative = "; alternative: " + "; ".join(plan["alternatives"]) if plan["alternatives"] else ""
    return f"{plan['command']}{alternative}. {plan['notes']} Or run zing setup --ffmpeg."


def _probe(argv: list[str]) -> str:
    result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=30, check=False)
    if result.returncode:
        raise RuntimeError(f"{argv[-1]} probe exited {result.returncode}: {result.stderr.strip()[-500:]}")
    return result.stdout or result.stderr


def inspect_build(ffmpeg: str | None, ffprobe: str | None) -> dict:
    missing = [name + " not found on PATH" for name, path in
               (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)) if not path]
    errors: list[str] = []
    versions = {}
    filters: set[str] = set()
    encoders: set[str] = set()
    for name, path in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)):
        if not path:
            continue
        try:
            output = _probe([path, "-version"])
            versions[name] = output.splitlines()[0] if output.splitlines() else ""
            match = re.search(r"version\s+n?(\d+)\.(\d+)", output)
            if not match:
                errors.append(f"{name} version could not be verified; use a released FFmpeg 6+ build")
            elif tuple(map(int, match.groups())) < MIN_VERSION:
                missing.append(f"{name} >= 6.0 (found {match.group(1)}.{match.group(2)})")
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            errors.append(f"{name}: {exc}")
    if ffmpeg:
        try:
            filters = set(re.findall(r"^\s*[TSC.]+\s+(\w+)\s+\S+->\S+",
                                     _probe([ffmpeg, "-hide_banner", "-filters"]), re.M))
            encoders = set(re.findall(r"^\s*[VAS][A-Z.]{5}\s+(\w+)\s+",
                                      _probe([ffmpeg, "-hide_banner", "-encoders"]), re.M))
            if "libx264" not in encoders:
                missing.append("libx264 encoder")
            if not filters & {"ass", "subtitles"}:
                missing.append("libass (ass or subtitles filter)")
            missing.extend(f"{name} filter" for name in sorted(REQUIRED_FILTERS - filters))
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            errors.append(f"ffmpeg capabilities: {exc}")
    return {"version": 1, "ok": not missing and not errors, "path": ffmpeg,
            "ffprobe_path": ffprobe, "versions": versions, "missing": missing,
            "errors": errors, "filters": sorted(filters), "libx264": "libx264" in encoders,
            "libass": bool(filters & {"ass", "subtitles"}), "drawtext": "drawtext" in filters}


def current_build() -> dict:
    return inspect_build(shutil.which("ffmpeg"), shutil.which("ffprobe"))


def describe(build: dict) -> str:
    if not build["ok"]:
        return "; ".join(build["missing"] + build["errors"])
    return (f"{build['versions']['ffmpeg']}; libx264, libass, drawtext and required filters available "
            f"({', '.join(sorted(REQUIRED_FILTERS))}); ffprobe available")


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def run(*, json_output: bool = False, non_interactive: bool = False) -> int:
    plan = install_plan()
    if json_output:
        print(json.dumps({**plan, "status": "print-only", "executed": False,
                          "consent": "Run interactively and type yes; --yes does not skip this prompt."}, indent=2))
        return 0
    print("FFmpeg is installed by your OS package manager, under its own license (GPL builds).")
    print("Command: " + (plan["command"] or "No supported package manager command for this OS."))
    for alternative in plan["alternatives"]:
        print("Alternative: " + alternative)
    print(plan["notes"])
    if non_interactive or not _interactive() or not plan["argv"]:
        print("Print only. Run zing setup --ffmpeg in a terminal and type yes to install.")
        return 0
    try:
        consent = input("Run this package-manager command? Type yes to continue: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        consent = ""
    if consent != "yes":
        print("Cancelled. Nothing installed.")
        return 0
    if not shutil.which(plan["argv"][0]):
        print(f"Package manager {plan['argv'][0]} is not on PATH. Install it or use the alternative above.")
        return 1
    try:
        result = subprocess.run(plan["argv"], check=False)
    except (OSError, KeyboardInterrupt) as exc:
        print(f"Installation did not finish: {exc}. Run zing doctor before retrying.")
        return 1
    # Check even after a nonzero package-manager exit; never equate exit 0 with readiness.
    build = current_build()
    print("Verification: " + describe(build))
    if result.returncode or not build["ok"]:
        print(f"Package manager exit: {result.returncode}. {plan['notes']}")
        return 1
    print("FFmpeg ready on this terminal's PATH.")
    return 0
