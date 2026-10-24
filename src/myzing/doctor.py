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
from importlib import metadata
from pathlib import Path

from myzing.ffmpeg_capabilities import (
    FFmpegCapabilityError, LIBASS_REMEDY, caption_filter,
)

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


def check_libass() -> Check:
    """Caption burn-in is optional; measurement and HyperFrames work without it."""
    ffmpeg = _which("ffmpeg")
    try:
        if ffmpeg is None:
            raise FFmpegCapabilityError("ffmpeg not found on PATH; captions need libass")
        selected_filter = caption_filter(ffmpeg)
    except FFmpegCapabilityError as exc:
        return Check(
            name="libass", tier=OPTIONAL, ok=False,
            detail=str(exc), fix=LIBASS_REMEDY,
            degraded_mode="FFmpeg captions need libass; HyperFrames captions do not",
        )
    return Check(
        name="libass", tier=OPTIONAL, ok=True,
        detail=f"FFmpeg captions have libass ({selected_filter} filter)",
        data={"path": ffmpeg, "filter": selected_filter},
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


def _whisper_model_name() -> str:
    """The model transcribe.py will actually load (same env override)."""
    from .study import transcribe

    return (
        os.environ.get(transcribe.ENV_MODEL, "").strip()
        or transcribe.DEFAULT_MODEL
    )


def _whisper_cache() -> tuple[Path | None, bool]:
    from .study.speech_models import hub_cache, local_path
    cache = hub_cache()
    return cache if cache.is_dir() else None, local_path(_whisper_model_name()) is not None


def check_whisper() -> Check:
    from .study import speech_models
    model = _whisper_model_name()
    rows = speech_models.inventory()
    row = next(r for r in rows if r["model"] == model)
    installed = _has_module("faster_whisper")
    data = {**row, "models": rows, "network_used": False}
    cached = [r["model"] for r in rows if r["cached"]]
    detail = ("package installed" if installed else "faster_whisper not importable")
    detail += "; cached speech models: " + (", ".join(cached) or "none")
    local = Path(model)
    fix = 'python -m pip install "myzing[study]"' if not installed else ""
    ok = installed
    if local.is_dir() or local.is_absolute():
        missing = [n for n in ("model.bin", "config.json", "tokenizer.json")
                   if not (local / n).is_file() or not (local / n).stat().st_size]
        data.update(local=True, missing=missing)
        detail += "; native loading not probed" if not missing else "; local model is incomplete: " + ", ".join(missing)
        if missing:
            ok = False
            fix = "Set ZING_WHISPER_MODEL to a complete local faster-whisper model directory."
    elif row["cached"]:
        detail += f"; model '{model}' is downloaded; native loading not probed"
    else:
        # The remedy below downloads into ZING_HOME, so measure that drive,
        # not the Hugging Face cache (often another volume, or absent).
        cache = speech_models.speech_root()
        data["cache"] = str(cache)
        detail += f"; configured model '{model}' is not cached. Choose speech setup in zing studio or zing doctor --speech-model small.en"
        fix = fix or "Run zing doctor --speech-model small.en (English, ~486 MB), or --speech-model large-v2 (multilingual, ~3.09 GB); confirm the download."
        where = speech_models.existing_ancestor(cache)
        try:
            free = shutil.disk_usage(where).free / 1e9
        except OSError:
            detail += f"; free space at {where} could not be checked"
        else:
            data["free_gb"] = round(free, 1)
            detail += f"; {free:.1f} GB is free at {where} for Zing's speech cache"
            if free < (row["download_bytes"] or 4e9) / 1e9 + .1:
                ok = False
                fix += " Free space, move ZING_HOME, or choose a smaller model."
    return Check(name="faster-whisper", tier=RECOMMENDED, ok=ok, detail=detail, fix=fix,
                 degraded_mode="" if installed and row["cached"] else
                 ("transcription is skipped" if not installed else "transcription may be unavailable") +
                 ": empty transcript + warning; spoken captions and continuity unavailable",
                 data=data)


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


def check_caption_geometry() -> Check:
    """Offline, without importing native runtimes or initializing OCR."""
    from myzing.study import caption_models

    missing = [name for name in ("rapidocr", "onnxruntime", "cv2", "numpy") if not _has_module(name)]
    if missing:
        return Check("caption_geometry", OPTIONAL, False,
                     f"caption geometry runtime missing: {', '.join(missing)}",
                     fix='python -m pip install "myzing[study]"', data={"network_used": False})
    try:
        caption_models.model_paths()
    except (OSError, RuntimeError, ValueError) as exc:
        return Check("caption_geometry", OPTIONAL, False, str(exc),
                     fix="python -m myzing.study.caption_models --fetch", data={"network_used": False})
    return Check("caption_geometry", OPTIONAL, True, "caption geometry runtime and pinned OCR assets present",
                 data={"network_used": False})


def check_fonts() -> Check:
    from myzing.fonts import library
    missing = [name for name in ("PIL", "cv2", "numpy") if not _has_module(name)]
    if missing:
        return Check("fonts", OPTIONAL, False, f"font comparison runtime missing: {', '.join(missing)}",
                     fix=library.INSTALL_HINT, data={"network_used": False})
    try:
        rows = library.inventory()
    except (OSError, ValueError) as exc:
        return Check("fonts", OPTIONAL, False, str(exc), fix="reinstall Zing; run zing fonts list")
    available = [r["id"] for r in rows if r["available"]]
    return Check("fonts", OPTIONAL, bool(available), f"{len(available)}/{len(rows)} verified font assets available; native rendering not probed",
                 fix="" if available else "zing fonts fetch --all",
                 data={"available_fonts": available, "network_used": False})


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
            # The provider's OWN error is the source of truth here
            # (render/tts.py): kokoro-onnx is deliberately NOT in any
            # extra because its runtime pulls espeakng-loader, so it is
            # installed separately. An earlier version of this line
            # prescribed `myzing[render]`, which contains only pysubs2
            # and therefore could never make kokoro importable — a fix
            # that cannot work, written while fixing a fix that could
            # not work.
            "python -m pip install kokoro-onnx   (deliberately outside "
            "the extras: its runtime pulls espeakng-loader; needs Python "
            "3.10-3.13) — or set ELEVENLABS_API_KEY to use the optional "
            "cloud provider instead"
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
                "study and corpus push ready. " + uoink_suite_hint(state)
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
                "is configured. " + uoink_suite_hint(state)
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
                f"[probe evidence: {evidence}]. " + uoink_suite_hint(state)
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
        detail=f"no uoink at {url} (fine — Zing is fully standalone). " + uoink_suite_hint(state),
        # The consequence belongs in degraded_mode, not in a parenthetical:
        # zing_status serves these fields to an AI, and every other check
        # puts "what you lose" here. Found by the anti-stranding test —
        # this was the one branch reporting not-ok with neither a fix nor
        # a stated consequence in the field consumers read.
        degraded_mode=(
            "kept-media study (study_uoink_item) and corpus push are "
            "unavailable; studying URLs and local files is unaffected"
        ),
        data={"url": url, "peer": peer, "evidence": evidence},
    )


def uoink_suite_hint(state: str) -> str:
    """Shared suite guidance without changing the peer's readiness verdict."""
    if state in {"available", "unconfigured"}:
        readiness = "available" if state == "available" else "detected; configure UOINK_TOKEN to connect"
        return (
            f"Uoink + Zing suite {readiness}: find references with "
            "zing project find-reference, resolve "
            "uoink:<id> kept media, and push breakdowns with MCP push_to_uoink."
        )
    return "Uoink adds saved references, kept-media reuse and breakdown storage: https://uoink.app"


def check_pillow() -> Check:
    present = _has_module("PIL")
    return Check(
        name="pillow", tier=OPTIONAL, ok=present,
        detail="Pillow available for still memes and timeline inspection" if present else "Pillow is not installed",
        fix='' if present else 'python -m pip install "myzing[memes]"',
        degraded_mode="" if present else "meme rendering and timeline inspection are unavailable; ideas, templates, and text checks still work",
    )


def check_heic() -> Check:
    """HEIC/HEIF photos decode through FFmpeg; probe its HEIF demuxer offline."""
    from myzing.memes.photo import heif_support

    ok, detail = heif_support()
    return Check(
        name="heic", tier=OPTIONAL, ok=ok,
        detail=("HEIC/HEIF photos for memes and stills: " + detail +
                ("" if ok else "; JPEG, PNG, WebP, BMP and TIFF photos are unaffected")),
        fix="" if ok else ("convert HEIC photos to JPEG/PNG, or put FFmpeg 7.1 or newer first on PATH "
                           "(Zing bundles no HEIC decoder)"),
        degraded_mode="" if ok else "HEIC/HEIF photos are refused with this message; other photos work",
    )


def check_screen() -> Check:
    import sys
    supported = sys.platform in {"win32", "darwin"}
    ready = sys.platform == "win32" or (sys.platform == "darwin" and _has_module("Quartz"))
    return Check("screen-cursor", OPTIONAL, ready,
                 "Local cursor recorder available" if ready else "Linux cursor capture is unsupported; pixel-activity planning works" if not supported else "macOS Quartz cursor capture is missing",
                 fix='pip install "myzing[screen]"' if supported and not ready else "",
                 degraded_mode="Plan existing screen recordings from frame-difference activity without telemetry." if not ready else "")


def check_layout() -> Check:
    """Offline metadata/cache probe; never import native runtimes in MCP status."""
    from myzing.layout.detector import INSTALL_HINT, model_path, verified_model
    from myzing.layout.vision_models import inventory

    vision = inventory()
    model_data = {"vision_models": vision, "network_used": False}

    if not _has_module("cv2"):
        return Check("layout", OPTIONAL, False, "OpenCV headless is not installed; vision inference unavailable", fix=INSTALL_HINT,
                     data=model_data)
    try:
        version = metadata.version("opencv-python-headless")
        conflicts = []
        for name in ("opencv-python", "opencv-contrib-python", "opencv-contrib-python-headless"):
            try:
                metadata.version(name)
                conflicts.append(name)
            except metadata.PackageNotFoundError:
                pass
        if version != "4.13.0.92" or conflicts:
            return Check("layout", OPTIONAL, False,
                         f"OpenCV headless package {version}; conflicting wheels: {conflicts}",
                         fix="Remove GUI/contrib OpenCV wheels, then reinstall opencv-python-headless==4.13.0.92; "
                             "checkout: uv sync --all-extras --reinstall-package opencv-python-headless", data=model_data)
        path = model_path()
        valid = verified_model(path)
    except (metadata.PackageNotFoundError, OSError) as exc:
        return Check("layout", OPTIONAL, False, str(exc), fix=INSTALL_HINT, data=model_data)
    return Check("layout", OPTIONAL, valid,
                 f"OpenCV headless package {version}; YuNet model {'verified' if valid else 'missing or corrupt'}; "
                 + "; ".join(f"{r['name']}: {'verified' if r['verified'] else 'missing/corrupt (HOG/saliency fallback)'}" for r in vision)
                 + "; native inference not probed",
                 fix=("" if valid else "zing layout fetch-model; ") +
                     ("" if all(r["verified"] for r in vision) else "zing layout fetch-model --vision"),
                 data={**model_data, "model": str(path), "model_verified": valid,
                       "runtime_probe": "package-metadata-only"})


def check_color() -> Check:
    present = _has_module("numpy")
    return Check(
        name="color", tier=OPTIONAL, ok=present,
        detail="numpy installed (local SDR color matching)" if present else "numpy is not importable",
        fix="" if present else 'python -m pip install "myzing[color]"',
        degraded_mode="" if present else "color match/apply unavailable; other commands are unaffected",
    )


def check_hyperframes() -> Check:
    """HyperFrames is optional unless a composition selects that backend."""
    from .render.hyperframes_adapter import HyperframesError, check_install

    try:
        data = check_install()
    except HyperframesError as exc:
        return Check(
            name="hyperframes", tier=OPTIONAL, ok=False,
            detail="local HyperFrames caption backend is unavailable",
            fix=str(exc),
            degraded_mode="HyperFrames captions fail preflight; ASS-only renders remain available",
        )
    return Check(
        name="hyperframes", tier=OPTIONAL, ok=True,
        detail="pinned local sidecar prerequisites found (render not exercised)",
        data=data,
    )


def check_audio() -> Check:
    present = _has_module("numpy")
    return Check(
        name="audio", tier=OPTIONAL, ok=present,
        detail="NumPy available for audio analysis" if present else "NumPy is not installed",
        fix='' if present else 'python -m pip install "myzing[audio]"',
        degraded_mode="" if present else "beat, onset, and audio-role analysis is unavailable",
    )


def check_audio_ml() -> Check:
    from .audio.tag_models import model_paths, runtime_supported, runtime_version, INSTALL_HINT, FETCH_HINT, REVISION
    present = _has_module("sherpa_onnx")
    version = runtime_version() if present else None
    supported = present and runtime_supported(version)
    try:
        paths = model_paths()
        valid, detail = True, "CED weights verified"
    except (OSError, RuntimeError) as exc:
        paths, valid, detail = {}, False, str(exc)
    runtime = (f"sherpa-onnx {version} installed; " if supported else
               f"sherpa-onnx {version or 'of unknown version'} predates 2.0 (1.x links GPL espeak-ng); " if present else
               "sherpa-onnx absent; ")
    return Check("audio-ml", OPTIONAL, supported and valid, runtime + detail,
                 fix="" if supported and valid else f"{INSTALL_HINT}; {FETCH_HINT}",
                 degraded_mode="" if supported and valid else "vocal/music heuristics remain active; learned tags unavailable",
                 data={"paths": {k: str(v) for k, v in paths.items()}, "revision": REVISION, "runtime_version": version,
                       "model_verified": valid, "network_used": False, "runtime_probe": "package-metadata-only"})


def run_checks(today: date | None = None) -> list[Check]:
    return [
        check_ffmpeg(),
        check_libass(),
        check_ytdlp(today),
        check_scenedetect(),
        check_whisper(),
        check_ocr(),
        check_caption_geometry(),
        check_fonts(),
        check_tts(),
        check_pillow(),
        check_heic(),
        check_layout(),
        check_screen(),
        check_color(),
        check_hyperframes(),
        check_audio(),
        check_audio_ml(),
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


def _next_step() -> str:
    """What to actually DO once the environment is usable.

    `zing doctor` is the first command a new user runs, and it ended on
    a bare "Ready." — correct, and a dead end. The next step depends on
    what the workspace already holds, so this reads state rather than
    printing an advert: nothing studied yet is a different situation
    from a workspace full of breakdowns.
    """
    from myzing import storage

    try:
        studied = len(storage.list_breakdowns())
        profiles = len(storage.list_profiles())
    except Exception:  # noqa: BLE001 — advice must never break the report
        return ""
    if studied == 0:
        return (
            "Next: study your first reference —\n"
            "  zing setup --list                 (curated preset packs)\n"
            "  zing study <url or file>          (your own)"
        )
    if profiles == 0:
        return (
            f"Next: {studied} studied video(s), no taste profile yet —\n"
            "  zing setup --links <url> ... --name my-taste\n"
            "  (or connect an AI to judge them: zing serve-mcp --print-config)"
        )
    return (
        f"Next: {studied} studied, {profiles} profile(s) — direct your own "
        "footage by\nconnecting an AI: zing serve-mcp --print-config"
    )


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
    if not missing:
        step = _next_step()
        if step:
            print("\n" + step)


_USAGE = "usage: zing doctor [--json] [--speech-model small.en|large-v2|skip] [--audio-model ced-mini] [--yes]"


def run(argv: list[str]) -> int:
    import argparse
    from .study import speech_models
    parser = argparse.ArgumentParser(prog="zing doctor", description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--speech-model", choices=["small.en", "large-v2", "skip"])
    parser.add_argument("--audio-model", choices=["ced-mini"], help="set up optional learned audio tags (myzing[audio-ml])")
    parser.add_argument("--yes", action="store_true", help="explicitly consent to the selected model download")
    unknown = [a for a in argv if a.startswith("--") and a not in {"--json", "--yes", "--help"}
               and a.split("=", 1)[0] not in {"--speech-model", "--audio-model"}]  # --speech-model=small.en is the same option
    if unknown:
        print("unrecognized arguments: " + " ".join(unknown), file=sys.stderr)
        return 2
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    if args.yes and not (args.speech_model or args.audio_model):
        print("--yes requires --speech-model or --audio-model", file=sys.stderr)
        return 2
    receipt = audio_receipt = None
    if args.speech_model or args.audio_model:
        from .audio import tag_models
        try:
            if args.speech_model:
                receipt = speech_models.setup(args.speech_model, yes=args.yes, json_mode=args.json)
            if args.audio_model:
                audio_receipt = tag_models.setup(args.audio_model, yes=args.yes, json_mode=args.json)
        except (ValueError, OSError, RuntimeError) as exc:
            if args.json:
                print(json.dumps({"ok": False, "error": str(exc)}))
            else:
                print(str(exc), file=sys.stderr)
            return 2
    checks = run_checks()
    summary = summarize(checks)
    if receipt:
        summary["speech_setup"] = receipt
    if audio_receipt:
        summary["audio_setup"] = audio_receipt
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        _print_human(checks)
        speech_models.print_inventory()
        for item in (receipt, audio_receipt):
            if item:
                print(json.dumps(item, indent=2))
    return 0 if summary["ok"] else 1
