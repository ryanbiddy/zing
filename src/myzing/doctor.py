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
    mark: str = ""         # display-state override: "degraded" = installed
    #                        but a promised capability currently fails
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


def resolve_ytdlp_argv() -> list[str] | None:
    """The exact argv prefix used to invoke yt-dlp — ONE resolver for
    doctor's probe and study's fetch (S5 gate defect D-11: doctor
    accepted binary-OR-module while ingest ran the literal binary, so a
    module-only env got "fully ready" and then every study failed).
    Binary on PATH wins; else the importable module runs through this
    interpreter; None means yt-dlp is absent entirely."""
    path = _which("yt-dlp")
    if path:
        return [path]
    if _has_module("yt_dlp"):
        return [sys.executable, "-m", "yt_dlp"]
    return None


def _ytdlp_config_paths() -> list[Path]:
    """Standard user-scope yt-dlp config locations (documented load
    order). Portable configs next to the binary and custom
    --config-locations are out of doctor's reach — wording that cites
    this list must say "standard locations", not "your config"."""
    candidates: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates += [
            Path(appdata) / "yt-dlp" / "config",
            Path(appdata) / "yt-dlp" / "config.txt",
        ]
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        candidates += [
            Path(xdg) / "yt-dlp" / "config",
            Path(xdg) / "yt-dlp" / "config.txt",
        ]
    home = Path.home()
    candidates += [
        home / ".config" / "yt-dlp" / "config",
        home / ".config" / "yt-dlp" / "config.txt",
        home / "yt-dlp.conf",
        home / "yt-dlp.conf.txt",
    ]
    return candidates


def _ytdlp_config_node_enabled() -> Path | None:
    """S5 gate defect D-13: doctor kept prescribing '--js-runtimes node'
    on a box whose config already contained it — a re-prescribed fix
    erodes trust in every other fix doctor prints. Returns the first
    standard config file with a non-comment '--js-runtimes ... node'
    line, else None."""
    for p in _ytdlp_config_paths():
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                continue
            if "--js-runtimes" in line and "node" in line:
                return p
    return None


def _youtube_js_advice(
    module: bool,
) -> tuple[str | None, bool, str, str, str, Path | None]:
    """YouTube-challenge readiness, separate from staleness parsing.

    B-Q12: yt-dlp's YouTube extractor executes real JavaScript for
    signature solving, which needs BOTH an external JS runtime and the
    EJS solver scripts (yt_dlp_ejs, shipped by yt-dlp[default]).
    Returns (js_runtime, has_solver, note, fix, degraded_mode,
    node_config); the strings are "" when the host is fully configured,
    and a non-empty degraded_mode means a promised fetch capability
    currently FAILS — the check must not report ok (audit #201 P1,
    re-found by Lane C SG-1 2026-07-19: leaf detail said "WILL fail"
    while the verdict line still aggregated to "fully ready").
    """
    js_runtime = next((rt for rt in ("deno", "node") if _which(rt)), None)
    note = ""
    fix = ""
    degraded = ""
    node_config: Path | None = None
    if js_runtime is None:
        # D-9: what S2 warned about is now reality — YouTube fetches FAIL
        # without an external JS runtime, they don't just warn.
        note = (
            "; no JS runtime (deno/node) found — YouTube fetches WILL fail "
            "(yt-dlp requires one for YouTube's signature solving)"
        )
        fix = "winget install DenoLand.Deno   (guide: " + _troubleshooting_ref() + ")"
        degraded = (
            "YouTube URL study fails until a JS runtime is installed; "
            "TikTok/Instagram URLs and local files still work"
        )
    elif js_runtime == "node":
        # SW-3 (Lane A sweep): node on PATH is NOT enough — yt-dlp only
        # enables deno by default; node needs explicit opt-in, and without
        # it signature-challenge videos 403 while others pass, looking
        # like an intermittent wall.
        node_config = _ytdlp_config_node_enabled()
        if node_config is not None:
            # D-13: the opt-in is already applied — say so, prescribe
            # nothing.
            note = f"; node JS runtime enabled via yt-dlp config ({node_config})"
        else:
            note = (
                "; node found but yt-dlp only uses deno by default — "
                "signature-challenge YouTube videos will 403 until configured"
            )
            fix = (
                "add '--js-runtimes node' to your yt-dlp config, or install "
                "deno (guide: " + _troubleshooting_ref() + ")"
            )
            degraded = (
                "signature-challenge YouTube videos 403 until node is "
                "enabled: no '--js-runtimes node' line in the standard "
                "yt-dlp config locations doctor checks (a custom "
                "--config-locations file is invisible to doctor — ignore "
                "this if yours has the line); other platforms and local "
                "files unaffected"
            )
    # Audit #201 P1: runtime-without-solver reproduces as "n challenge
    # solving failed" on every YouTube fetch.
    has_solver = _has_module("yt_dlp_ejs")
    if module and not has_solver:
        note += (
            "; EJS solver scripts missing — YouTube challenge solving "
            "fails even with a JS runtime"
        )
        solver_fix = 'python -m pip install "yt-dlp[default]"'
        fix = f"{solver_fix}; {fix}" if fix else (
            solver_fix + "   (guide: " + _troubleshooting_ref() + ")"
        )
        degraded = degraded or (
            "YouTube challenge solving fails until the EJS solver "
            "scripts are installed; other platforms and local files "
            "still work"
        )
    return js_runtime, has_solver, note, fix, degraded, node_config


def check_ytdlp(today: date | None = None) -> Check:
    today = today or date.today()
    # D-11: probe the SAME invocation study will run, not a looser
    # notion of "installed" — the gate saw "fully ready" from a module
    # probe while every fetch ran (and failed to find) the binary.
    argv = resolve_ytdlp_argv()
    module = _has_module("yt_dlp")
    if argv is None:
        return Check(
            name="yt-dlp",
            tier=RECOMMENDED,
            ok=False,
            detail="yt-dlp not found (binary or module)",
            fix='python -m pip install "myzing[study]"   (or: pip install yt-dlp)',
            degraded_mode="zing study works on local files only — no URL fetch",
        )
    version = _run_version_cached(argv + ["--version"])
    age = _ytdlp_version_age_days(version, today) if version else None
    js_runtime, has_solver, js_note, js_fix, js_degraded, node_config = (
        _youtube_js_advice(module)
    )
    stale = age is not None and age > YTDLP_STALE_DAYS
    if stale:
        detail = (
            f"version {version} is ~{age} days old — platform extractors "
            f"rot fast; TikTok/Instagram fetches may fail until updated"
        )
        fix = "python -m pip install -U yt-dlp" + (
            f"   then: {js_fix}" if js_fix else ""
        )
    else:
        detail = f"version {version}" if version else f"found ({argv[0]})"
        fix = js_fix
    # Staleness stays warning-grade (ok=True); a broken YouTube fetch
    # path does not — ok feeds the verdict line, and "fully ready" over
    # a failing capability was audit #201's exact false comfort.
    return Check(
        name="yt-dlp",
        tier=RECOMMENDED,
        ok=not js_degraded,
        detail=detail + js_note,
        fix=fix,
        degraded_mode=js_degraded,
        mark="degraded" if js_degraded else "",
        data={
            "version": version,
            "age_days": age,
            "stale": stale,
            "js_runtime": js_runtime,
            "ejs_solver": has_solver,
            "invocation": argv,
            "node_config": str(node_config) if node_config else None,
        },
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
        # The fix must address what is ACTUALLY missing: a runtime the
        # model files cannot substitute for is a different problem than
        # absent model files, and prescribing the download to someone
        # whose Python cannot run kokoro-onnx is the re-prescribed-fix
        # dead end D-13 and the review's P1-1 both punished.
        fix=(
            "install the render extras so kokoro-onnx is importable: "
            'python -m pip install "myzing[render]" — if your Python is too '
            "new for it, run zing on a Python it supports or set "
            "ELEVENLABS_API_KEY to use the optional cloud provider"
            if "not importable" in str(provider.get("detail", ""))
            else "download the kokoro model files to ~/.cache/myzing/kokoro "
            "(or point ZING_KOKORO_MODEL/ZING_KOKORO_VOICES at them) — Zing "
            "never auto-downloads models (D-6); ElevenLabs is optional via "
            "ELEVENLABS_API_KEY"
        ),
        degraded_mode="renders proceed without voiceover tracks (stated in output)",
        data=status,
    )


# §4 background-status cadence: retryable states may be re-probed at
# most once per 60s — the cache IS the rate limit, since zing_status
# polls doctor during studies.
_PEER_CACHE_TTL_S = 60.0
_peer_cache: dict[str, tuple[float, dict]] = {}


def _probe_uoink_cached() -> tuple[dict, str]:
    import time as _time

    from myzing import suite_peer

    now = _time.monotonic()
    hit = _peer_cache.get("uoink")
    if hit and now - hit[0] < _PEER_CACHE_TTL_S:
        return hit[1]
    result = suite_peer.probe_uoink()
    _peer_cache["uoink"] = (now, result)
    return result


def _token_location() -> str:
    """One source of truth for the token-location guidance, shared with
    the bridge (which owns the constant). Imported lazily: doctor must
    stay importable before optional modules load."""
    from myzing.uoink_bridge import TOKEN_LOCATION

    return TOKEN_LOCATION


def check_uoink() -> Check:
    """INTEGRATION-CONTRACT v1 §8 probe, replacing the pre-contract
    ambiguity the contract itself cites (any-status-below-500 counted as
    "reachable"). The peer envelope rides in data; human and JSON say
    the same state."""
    url = os.environ.get(UOINK_URL_ENV, "").strip() or UOINK_DEFAULT_URL
    peer, evidence = _probe_uoink_cached()
    state = peer["state"]
    if state == "available":
        return Check(
            name="uoink",
            tier=OPTIONAL,
            ok=True,
            detail=(
                f"uoink available at {url} ({evidence}) — kept-media "
                "study and corpus push ready"
            ),
            data={"url": url, "peer": peer, "evidence": evidence},
        )
    if state == "unconfigured":
        return Check(
            name="uoink",
            tier=OPTIONAL,
            ok=False,
            mark="unconfig",  # detected-but-uncredentialed is NOT absence
            detail=(
                f"uoink detected at {url} ({evidence}) but no credential "
                "is configured"
            ),
            fix=(
                "set UOINK_TOKEN to uoink's per-install token — "
                + _token_location()
            ),
            data={"url": url, "peer": peer, "evidence": evidence},
        )
    if state == "unhealthy":
        err = peer["error"]
        return Check(
            name="uoink",
            tier=OPTIONAL,
            ok=False,
            mark="unhealthy",  # drift/auth/identity is never shown as absent
            detail=(
                f"uoink peer unhealthy ({err['code']}): {err['message']} "
                f"[probe evidence: {evidence}]"
            ),
            fix=(
                "check UOINK_TOKEN" if err["code"] == "authentication_failed"
                else "check UOINK_URL" if err["code"] == "invalid_configuration"
                else "update uoink (or zing) so both speak "
                "INTEGRATION-CONTRACT v1"
            ),
            data={"url": url, "peer": peer},
        )
    return Check(
        name="uoink",
        tier=OPTIONAL,
        ok=False,
        detail=f"no uoink at {url} (fine — Zing is fully standalone)",
        data={"url": url, "peer": peer, "evidence": evidence},
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
        if c.mark:  # installed-but-failing must not print as MISSING
            status = c.mark
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
