"""``zing doctor``: honest environment checks with actionable fixes.

Three tiers (binding, SPRINT-1-D1 §Critique resolutions B#5):

- required     ffmpeg/ffprobe — without them Zing measures nothing;
               missing required => exit 1.
- recommended  yt-dlp, faster-whisper, an OCR backend — each missing one
               names its degraded mode; never fails the machine.
- optional     the uoink helper on localhost — silently absent is fine.

Every failing line prints the exact command that fixes it. ``--json``
emits the same result machine-readably; the MCP ``zing_status`` tool is
built on ``run_checks()`` so humans and AIs read one source of truth.

Core install is stdlib-only by design: doctor must run before anything
else is installed. Heavy deps are detected, never imported.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import date

REQUIRED = "required"
RECOMMENDED = "recommended"
OPTIONAL = "optional"

UOINK_URL_ENV = "UOINK_URL"
UOINK_DEFAULT_URL = "http://127.0.0.1:5179"

# yt-dlp versions are calendar-based (e.g. 2026.06.09); extractors rot fast.
YTDLP_STALE_DAYS = 90


@dataclass
class Check:
    name: str
    tier: str
    ok: bool
    detail: str            # what we found, honestly
    fix: str = ""          # exact command / next step when not ok (or degraded)
    degraded_mode: str = ""  # what Zing does without it (recommended tier)
    data: dict = field(default_factory=dict)  # extra machine-readable facts


def _which(binary: str) -> str | None:
    return shutil.which(binary)


def _run_version(cmd: list[str]) -> str:
    """First line of a --version style call, "" on any failure."""
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15, check=False
        )
        first = (out.stdout or out.stderr).strip().splitlines()
        return first[0].strip() if first else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _has_module(name: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_ffmpeg() -> Check:
    ffmpeg = _which("ffmpeg")
    ffprobe = _which("ffprobe")
    if ffmpeg and ffprobe:
        version = _run_version([ffmpeg, "-version"])
        return Check(
            name="ffmpeg",
            tier=REQUIRED,
            ok=True,
            detail=version or f"found at {ffmpeg}",
            data={"path": ffmpeg},
        )
    missing = "ffmpeg and ffprobe" if not ffmpeg and not ffprobe else (
        "ffprobe" if ffmpeg else "ffmpeg"
    )
    fix = (
        "winget install Gyan.FFmpeg   (then restart the terminal)"
        if sys.platform == "win32"
        else "brew install ffmpeg"
        if sys.platform == "darwin"
        else "sudo apt install ffmpeg   (or see https://ffmpeg.org/download.html)"
    )
    return Check(
        name="ffmpeg",
        tier=REQUIRED,
        ok=False,
        detail=f"{missing} not found on PATH — Zing cannot measure anything without it",
        fix=fix,
    )


def _ytdlp_version_age_days(version: str, today: date) -> int | None:
    """Days since a calendar version like '2026.06.09'; None if unparsable."""
    m = re.match(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})", version)
    if not m:
        return None
    try:
        released = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    return (today - released).days


def check_ytdlp(today: date | None = None) -> Check:
    today = today or date.today()
    path = _which("yt-dlp")
    module = _has_module("yt_dlp")
    if not path and not module:
        return Check(
            name="yt-dlp",
            tier=RECOMMENDED,
            ok=False,
            detail="yt-dlp not found (binary or module)",
            fix='python -m pip install "myzing[study]"   (or: pip install yt-dlp)',
            degraded_mode="zing study works on local files only — no URL fetch",
        )
    version = _run_version([path, "--version"]) if path else _run_version(
        [sys.executable, "-m", "yt_dlp", "--version"]
    )
    age = _ytdlp_version_age_days(version, today) if version else None
    if age is not None and age > YTDLP_STALE_DAYS:
        return Check(
            name="yt-dlp",
            tier=RECOMMENDED,
            ok=True,
            detail=(
                f"version {version} is ~{age} days old — platform extractors "
                "rot fast; TikTok/Instagram fetches may fail until updated"
            ),
            fix="python -m pip install -U yt-dlp",
            data={"version": version, "age_days": age, "stale": True},
        )
    return Check(
        name="yt-dlp",
        tier=RECOMMENDED,
        ok=True,
        detail=f"version {version}" if version else f"found at {path}",
        data={"version": version, "age_days": age, "stale": False},
    )


def check_whisper() -> Check:
    if _has_module("faster_whisper"):
        return Check(
            name="faster-whisper",
            tier=RECOMMENDED,
            ok=True,
            detail=(
                "package installed (model weights download on first "
                "`zing study` run and are cached)"
            ),
        )
    return Check(
        name="faster-whisper",
        tier=RECOMMENDED,
        ok=False,
        detail="faster_whisper not importable",
        fix='python -m pip install "myzing[study]"',
        degraded_mode=(
            "transcription is skipped: empty transcript + a warning in the "
            "breakdown (words/pacing-by-speech unavailable)"
        ),
    )


def check_ocr() -> Check:
    for module, label in (
        ("rapidocr_onnxruntime", "RapidOCR (rapidocr_onnxruntime)"),
        ("rapidocr", "RapidOCR (rapidocr)"),
    ):
        if _has_module(module):
            return Check(
                name="ocr", tier=RECOMMENDED, ok=True, detail=f"{label} installed"
            )
    tesseract = _which("tesseract")
    if tesseract:
        return Check(
            name="ocr",
            tier=RECOMMENDED,
            ok=True,
            detail=f"tesseract found at {tesseract} (fallback backend; "
            "RapidOCR reads stylized captions better)",
            fix='python -m pip install "myzing[study]"   (installs RapidOCR)',
        )
    return Check(
        name="ocr",
        tier=RECOMMENDED,
        ok=False,
        detail="no OCR backend (RapidOCR module or tesseract binary)",
        fix='python -m pip install "myzing[study]"',
        degraded_mode=(
            "caption OCR is skipped: empty captions list + a warning in the "
            "breakdown (caption style can't be measured)"
        ),
    )


def check_uoink() -> Check:
    url = os.environ.get(UOINK_URL_ENV, "").strip() or UOINK_DEFAULT_URL
    try:
        with urllib.request.urlopen(url, timeout=1.5) as resp:
            reachable = 200 <= resp.status < 500
    except (urllib.error.URLError, OSError, ValueError):
        reachable = False
    if reachable:
        return Check(
            name="uoink",
            tier=OPTIONAL,
            ok=True,
            detail=f"uoink helper answering at {url} — breakdowns can be "
            "pushed back to your corpus",
            data={"url": url},
        )
    return Check(
        name="uoink",
        tier=OPTIONAL,
        ok=False,
        detail=f"no uoink helper at {url} (fine — Zing is fully standalone)",
        data={"url": url},
    )


def run_checks(today: date | None = None) -> list[Check]:
    return [
        check_ffmpeg(),
        check_ytdlp(today),
        check_whisper(),
        check_ocr(),
        check_uoink(),
    ]


def summarize(checks: list[Check]) -> dict:
    """Machine-readable summary; also the basis of MCP zing_status."""
    required_missing = [c.name for c in checks if c.tier == REQUIRED and not c.ok]
    return {
        "ok": not required_missing,
        "required_missing": required_missing,
        "checks": [asdict(c) for c in checks],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_MARKS = {True: "ok", False: "MISSING"}


def _print_human(checks: list[Check]) -> None:
    print("zing doctor\n")
    for c in checks:
        status = _MARKS[c.ok]
        if c.tier == OPTIONAL and not c.ok:
            status = "absent"
        print(f"  [{status:>7}] {c.name} ({c.tier})")
        print(f"           {c.detail}")
        if c.degraded_mode and not c.ok:
            print(f"           without it: {c.degraded_mode}")
        if c.fix and (not c.ok or c.data.get("stale")):
            print(f"           fix: {c.fix}")
    missing = [c for c in checks if c.tier == REQUIRED and not c.ok]
    if missing:
        names = ", ".join(c.name for c in missing)
        print(f"\nNOT ready: required tool(s) missing: {names} — fix above, then re-run.")
    else:
        print("\nReady. (Recommended items above may name degraded modes.)")


def run(argv: list[str]) -> int:
    if any(a in ("-h", "--help") for a in argv):
        print("usage: zing doctor [--json]\n\n" + (__doc__ or ""))
        return 0
    checks = run_checks()
    summary = summarize(checks)
    if "--json" in argv:
        print(json.dumps(summary, indent=2))
    else:
        _print_human(checks)
    return 0 if summary["ok"] else 1
