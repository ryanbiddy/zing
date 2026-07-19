"""``zing doctor``: honest environment checks with actionable fixes.

Three tiers (binding, SPRINT-1-D1 §Critique resolutions B#5):

- required     ffmpeg/ffprobe — without them Zing measures nothing;
               missing required => exit 1.
- recommended  yt-dlp, scenedetect, faster-whisper, rapidocr — each
               missing one names its degraded mode; never fails the
               machine, but "Ready." is qualified while any are missing.
- optional     the uoink helper on localhost — silently absent is fine.

Doctor checks exactly what the study pipeline imports (F-05/F-10): the
module names below are asserted against the study sources by tests, so a
backend swap in the pipeline breaks the build until doctor agrees.

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
from pathlib import Path

REQUIRED = "required"
RECOMMENDED = "recommended"
OPTIONAL = "optional"

UOINK_URL_ENV = "UOINK_URL"
UOINK_DEFAULT_URL = "http://127.0.0.1:5179"

# yt-dlp versions are calendar-based (e.g. 2026.06.09); extractors rot fast.
YTDLP_STALE_DAYS = 90

# Audit #201 P2: launching `python -m yt_dlp --version` costs ~0.25s and
# zing_status is polled during studies — cache the probe briefly. The
# version only changes on install; 60s staleness is honest.
_VERSION_CACHE_TTL_S = 60.0
_version_cache: dict[str, tuple[float, str]] = {}


def _run_version_cached(cmd: list[str]) -> str:
    import time as _time

    key = " ".join(cmd)
    now = _time.monotonic()
    hit = _version_cache.get(key)
    if hit and now - hit[0] < _VERSION_CACHE_TTL_S:
        return hit[1]
    version = _run_version(cmd)
    _version_cache[key] = (now, version)
    return version


def _troubleshooting_ref() -> str:
    """A path to FETCH-TROUBLESHOOTING.md that EXISTS for this install:
    repo checkout when present, else the copy shipped in the wheel
    (audit #201 P1: a repo-relative pointer is dead for installed users)."""
    repo = Path(__file__).resolve().parents[2] / "docs" / "FETCH-TROUBLESHOOTING.md"
    if repo.is_file():
        return str(repo)
    return str(Path(__file__).resolve().parent / "_data" / "docs" / "FETCH-TROUBLESHOOTING.md")

# What the study pipeline actually imports — the single source of truth for
# the ocr and shot-detection verdicts (tests assert the sources agree):
OCR_MODULE = "rapidocr"        # study/captions.py: from rapidocr import RapidOCR
SHOT_MODULE = "scenedetect"    # study/shots.py: import scenedetect


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
    version = _run_version_cached(
        [path, "--version"] if path else [sys.executable, "-m", "yt_dlp", "--version"]
    )
    age = _ytdlp_version_age_days(version, today) if version else None
    # B-Q12: yt-dlp's YouTube extractor needs an external JS runtime (deno
    # preferred, node accepted) for signature solving; without one it prints
    # a deprecation warning on every fetch and YouTube downloads can fail.
    # Staleness parsing never covered this — it is a separate, named fact.
    js_runtime = next(
        (rt for rt in ("deno", "node") if _which(rt)), None
    )
    js_note = ""
    js_fix = ""
    if js_runtime is None:
        # D-9: what S2 warned about is now reality — YouTube fetches FAIL
        # without an external JS runtime, they don't just warn.
        js_note = (
            "; no JS runtime (deno/node) found — YouTube fetches WILL fail "
            "(yt-dlp requires one for YouTube's signature solving)"
        )
        js_fix = (
            "winget install DenoLand.Deno   (guide: "
            + _troubleshooting_ref() + ")"
        )
    elif js_runtime == "node":
        # SW-3 (Lane A sweep): node on PATH is NOT enough — yt-dlp only
        # enables deno by default; node needs explicit opt-in, and without
        # it signature-challenge videos 403 while others pass, looking
        # like an intermittent wall.
        js_note = (
            "; node found but yt-dlp only uses deno by default — "
            "signature-challenge YouTube videos will 403 until configured"
        )
        js_fix = (
            "add '--js-runtimes node' to your yt-dlp config, or install "
            "deno (guide: " + _troubleshooting_ref() + ")"
        )
    # Audit #201 P1: a runtime is NOT the whole story — yt-dlp's YouTube
    # challenge solving also needs the EJS solver scripts (shipped by
    # yt-dlp[default] as the yt_dlp_ejs package). Runtime-without-solver
    # reproduces as "n challenge solving failed" on every YouTube fetch.
    has_solver = _has_module("yt_dlp_ejs")
    if module and not has_solver:
        js_note += (
            "; EJS solver scripts missing — YouTube challenge solving "
            "fails even with a JS runtime"
        )
        solver_fix = 'python -m pip install "yt-dlp[default]"'
        js_fix = f"{solver_fix}; {js_fix}" if js_fix else (
            solver_fix + "   (guide: " + _troubleshooting_ref() + ")"
        )
    data = {
        "version": version,
        "age_days": age,
        "stale": False,
        "js_runtime": js_runtime,
        "ejs_solver": has_solver,
    }
    if age is not None and age > YTDLP_STALE_DAYS:
        data["stale"] = True
        return Check(
            name="yt-dlp",
            tier=RECOMMENDED,
            ok=True,
            detail=(
                f"version {version} is ~{age} days old — platform extractors "
                f"rot fast; TikTok/Instagram fetches may fail until updated"
                f"{js_note}"
            ),
            fix="python -m pip install -U yt-dlp"
            + (f"   then: {js_fix}" if js_fix else ""),
            data=data,
        )
    return Check(
        name="yt-dlp",
        tier=RECOMMENDED,
        ok=True,
        detail=(f"version {version}" if version else f"found at {path}") + js_note,
        fix=js_fix,
        data=data,
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
    """ok only when the exact module the pipeline imports is importable.

    study/captions.py does ``from rapidocr import RapidOCR`` — nothing
    else. The old ``rapidocr_onnxruntime`` package and a ``tesseract``
    binary are reported honestly as found-but-not-wired: with either
    alone, every study still skips OCR (F-05).
    """
    if _has_module(OCR_MODULE):
        return Check(
            name="ocr",
            tier=RECOMMENDED,
            ok=True,
            detail="rapidocr installed (the module the study pipeline imports)",
        )
    found_instead = []
    if _has_module("rapidocr_onnxruntime"):
        found_instead.append("the rapidocr_onnxruntime module")
    tesseract = _which("tesseract")
    if tesseract:
        found_instead.append(f"tesseract at {tesseract}")
    detail = "the `rapidocr` package is not importable"
    if found_instead:
        detail += (
            f" — found {' and '.join(found_instead)}, but Zing's OCR "
            "imports `rapidocr` only, so OCR is still skipped"
        )
    return Check(
        name="ocr",
        tier=RECOMMENDED,
        ok=False,
        detail=detail,
        fix='python -m pip install "myzing[study]"   (installs rapidocr)',
        degraded_mode=(
            "caption OCR is skipped: empty captions list + a warning in the "
            "breakdown (caption style can't be measured)"
        ),
    )


def check_scenedetect() -> Check:
    """Shot detection is the core measurement — doctor must check it (F-10)."""
    if _has_module(SHOT_MODULE):
        return Check(
            name="scenedetect",
            tier=RECOMMENDED,
            ok=True,
            detail="scenedetect installed (PySceneDetect AdaptiveDetector)",
        )
    return Check(
        name="scenedetect",
        tier=RECOMMENDED,
        ok=False,
        detail="scenedetect not importable — Zing cannot detect shots without it",
        fix='python -m pip install "myzing[study]"',
        degraded_mode=(
            "shot detection is skipped: zero shots + a warning in the "
            "breakdown (cut rhythm, keyframes, and the eval cut score "
            "are all unavailable)"
        ),
    )


def check_tts() -> Check:
    """S4: voiceover rendering state — optional tier (assemble works
    without VO; the render degrades honestly)."""
    try:
        from myzing.tts_providers import tts_status

        status = tts_status()
    except ImportError:
        return Check(
            name="tts",
            tier=OPTIONAL,
            ok=False,
            detail="TTS surface not importable (render extras missing)",
            fix='python -m pip install "myzing[render]"',
        )
    selected = status["selected"]
    provider = status["providers"].get(selected, {})
    ready = bool(provider.get("ready"))
    others = ", ".join(
        f"{name}: {p['detail']}"
        for name, p in status["providers"].items()
        if name != selected
    )
    if ready:
        return Check(
            name="tts",
            tier=OPTIONAL,
            ok=True,
            detail=f"voiceover via '{selected}' ({provider['detail']}); {others}",
            data=status,
        )
    return Check(
        name="tts",
        tier=OPTIONAL,
        ok=False,
        detail=f"selected TTS '{selected}' not ready: {provider.get('detail', '?')}; {others}",
        fix=(
            "download the kokoro model files to ~/.cache/myzing/kokoro (or "
            "point ZING_KOKORO_MODEL/ZING_KOKORO_VOICES at them) — Zing "
            "never auto-downloads models (D-6); ElevenLabs is optional via "
            "ELEVENLABS_API_KEY"
        ),
        degraded_mode="renders proceed without voiceover tracks (stated in output)",
        data=status,
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
        check_scenedetect(),
        check_whisper(),
        check_ocr(),
        check_tts(),
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


def _verdict_line(checks: list[Check]) -> str:
    """One-line first-run verdict (S5 install-gate observation #2): a new
    user should learn readiness from the first line, not from scanning
    seven items."""
    required_missing = [c.name for c in checks if c.tier == REQUIRED and not c.ok]
    if required_missing:
        return (
            "Verdict: NOT ready — required missing: "
            f"{', '.join(required_missing)} (fix below, then re-run)"
        )
    degraded = [c.name for c in checks if c.tier == RECOMMENDED and not c.ok]
    if degraded:
        return (
            f"Verdict: ready for local-file study; {len(degraded)} feature(s) "
            f"degraded ({', '.join(degraded)}) — details below"
        )
    return "Verdict: fully ready"


def _print_human(checks: list[Check]) -> None:
    print("zing doctor\n")
    print(_verdict_line(checks) + "\n")
    for c in checks:
        status = _MARKS[c.ok]
        if c.tier == OPTIONAL and not c.ok:
            status = "absent"
        print(f"  [{status:>7}] {c.name} ({c.tier})")
        print(f"           {c.detail}")
        if c.degraded_mode and not c.ok:
            print(f"           without it: {c.degraded_mode}")
        if c.fix:  # a fix line only exists when something is worth fixing
            print(f"           fix: {c.fix}")
    missing = [c for c in checks if c.tier == REQUIRED and not c.ok]
    degraded = [c for c in checks if c.tier == RECOMMENDED and not c.ok]
    if missing:
        names = ", ".join(c.name for c in missing)
        print(f"\nNOT ready: required tool(s) missing: {names} — fix above, then re-run.")
    elif degraded:
        # Never an unqualified "Ready." while a measurement is degraded (F-10).
        names = ", ".join(c.name for c in degraded)
        print(
            f"\nReady for basic use, but degraded — missing recommended "
            f"tool(s): {names} (fixes above)."
        )
    else:
        print("\nReady.")


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
