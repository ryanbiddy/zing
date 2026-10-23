"""Offline speech inventory and explicit, pinned, consented provisioning."""

from functools import lru_cache
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import sys

from myzing import storage
from myzing.model_fetch import fetch_verified, verified
from .speech_pins import MODELS

SPACE_MARGIN = 64_000_000  # bytes kept free beyond the pinned model sizes
RECOMMENDED = "small.en"
REASON = "small.en is a faster first draft for English speech. It can miss names, accents and quiet words; review captions. Choose large-v2 for other languages or more accurate speech."
SKIP_NOTE = "Speech skipped: spoken captions and whole-line continuity are unavailable. Clips with unverified speech may be excluded; no transcript is invented."
CHOICES = {
    "small.en": "small.en (~486 MB): faster, English only; less accurate on names, accents and quiet speech",
    "large-v2": "large-v2 (~3.09 GB): slower, multilingual; higher speech accuracy (study default)",
    "skip": "Skip speech (0 MB): no spoken captions or whole-line continuity; speech clips may be excluded",
}


def speech_root():
    """Where Zing's consented speech downloads land (ZING_HOME/models/speech)."""
    return storage.resolve_workspace() / "models" / "speech"


def _component(value):
    """A single plain file or folder name: no separators, drives, streams or dot segments."""
    return (isinstance(value, str) and value not in ("", ".", "..") and not any(c in value for c in "/\\:\0")
            and PurePosixPath(value).name == value and PureWindowsPath(value).name == value)


def pinned(name):
    """The pin for name, refusing any revision or file name that could leave its cache folder."""
    spec = MODELS[name]
    if not _component(name) or not re.fullmatch(r"[0-9a-f]{40}", str(spec.get("revision", ""))):
        raise ValueError(f"Speech pin for {name!r} has an invalid name or revision.")
    unsafe = [file for file in spec["files"] if not _component(file)]
    if unsafe:
        raise ValueError(f"Speech pin for {name!r} has unsafe file names: {unsafe!r}")
    return spec


def cache_dir(name):
    return speech_root() / name / pinned(name)["revision"]


def existing_ancestor(path):
    """The nearest folder that exists, so free space is measured on the right drive."""
    path = Path(path)
    return next((p for p in (path, *path.parents) if p.exists()), path)


@lru_cache(maxsize=64)
def _checked(path, digest, size, mtime_ns):
    return verified(Path(path), digest)


def managed_path(name):
    if name not in MODELS:
        return None
    root = cache_dir(name)
    for file, spec in MODELS[name]["files"].items():
        path = root / file
        try:
            stat = path.stat()
        except OSError:
            return None
        if stat.st_size != spec["size"] or not _checked(str(path), spec["sha256"], stat.st_size, stat.st_mtime_ns):
            return None
    return root


def _complete(path):
    return all((path / n).is_file() and (path / n).stat().st_size for n in
               ("model.bin", "config.json", "tokenizer.json"))


def hub_cache():
    return Path(os.environ.get("HF_HUB_CACHE") or os.environ.get("HUGGINGFACE_HUB_CACHE") or
                str(Path(os.environ.get("HF_HOME") or Path.home() / ".cache/huggingface") / "hub"))


def local_path(name):
    """Never load a model or contact the hub during inventory."""
    managed = managed_path(name)
    if managed:
        return managed
    path = Path(name).expanduser()
    if path.is_dir() or path.is_absolute():
        return path if _complete(path) else None
    # Existing user-provisioned hub snapshots remain usable offline.
    for path in sorted(hub_cache().glob(f"models--*faster-whisper-{name}/snapshots/*")):
        if _complete(path):
            return path
    return None


def configured_name():
    from .transcribe import DEFAULT_MODEL, ENV_MODEL
    return os.environ.get(ENV_MODEL, "").strip() or DEFAULT_MODEL


def inventory():
    names = list(MODELS)
    for path in sorted(hub_cache().glob("models--*faster-whisper-*")):
        name = path.name.rsplit("faster-whisper-", 1)[-1]
        if name and name not in names:
            names.append(name)
    configured = configured_name()
    if configured not in names:
        names.append(configured)
    rows = []
    for name in names:
        path = local_path(name)
        rows.append({"model": name, "cached": path is not None, "path": str(path) if path else None,
                     "verified": bool(path and name in MODELS and path == cache_dir(name)),
                     "download_bytes": sum(f["size"] for f in MODELS[name]["files"].values()) if name in MODELS else None})
    return rows


def choices():
    options = dict(CHOICES)
    for row in inventory():
        name = row["model"]
        if name not in options and row["cached"]:
            options[name] = f"Use cached model {name} (0 MB; quality depends on this model)"
    return options


def recommendation():
    configured = configured_name()
    if local_path(configured):
        return configured, "Your configured model is already cached; no download is needed. Review its transcript."
    if local_path(RECOMMENDED):
        return RECOMMENDED, "small.en is already cached; no download is needed. " + REASON
    cached = next((r for r in inventory() if r["cached"]), None)
    if cached:
        return cached["model"], "This model is already cached, so you can start without downloading. Review its transcript and language support."
    return RECOMMENDED, REASON


def fetch_model(name, *, consent=False, progress=None):
    if consent is not True:
        raise ValueError("Speech model download requires explicit yes (speech_download: true).")
    if name not in MODELS:
        raise ValueError("Choose small.en or large-v2 for a pinned speech download.")
    spec, root = MODELS[name], cache_dir(name)
    needed = sum(pin["size"] for file, pin in spec["files"].items()
                 if not ((root / file).is_file() and (root / file).stat().st_size == pin["size"]))
    if needed:
        where = existing_ancestor(root)
        free = shutil.disk_usage(where).free
        if free < needed + SPACE_MARGIN:
            raise RuntimeError(f"Speech model {name} needs {needed / 1e9:.2f} GB free at {where}; only "
                               f"{free / 1e9:.2f} GB is free. Free space, move ZING_HOME to a roomier drive, "
                               "or choose small.en or skip.")
    downloaded = 0
    for file, pin in spec["files"].items():
        url = f"https://huggingface.co/Systran/faster-whisper-{name}/resolve/{spec['revision']}/{file}"
        if fetch_verified(url, root / file, pin["sha256"], pin["size"], progress=progress):
            downloaded += pin["size"]
    if managed_path(name) is None:
        raise RuntimeError(f"Speech model {name} failed verification; retry setup.")
    return {"version": 1, "model": name, "path": str(root), "revision": spec["revision"],
            "sha256": {f: p["sha256"] for f, p in spec["files"].items()}, "verified": True,
            "downloaded_bytes": downloaded, "license": "MIT"}


def prepare(answers, *, progress=None):
    name = answers.get("speech_model")
    if name is None:
        return None
    if name == "skip":
        return {"version": 1, "model": "skip", "captions": "unavailable", "continuity": "unavailable",
                "downloaded_bytes": 0, "note": SKIP_NOTE}
    path = local_path(name)
    if path is None:
        return fetch_model(name, consent=answers.get("speech_download"), progress=progress)
    return {"version": 1, "model": name, "path": str(path), "downloaded_bytes": 0,
            "verified": bool(name in MODELS and path == cache_dir(name))}


def print_inventory():
    for row in inventory():
        state = "cached (SHA-256 verified)" if row["verified"] else "cached (user-provided; native loading not probed)" if row["cached"] else "not cached"
        print(f"Speech: {row['model']}: {state}")
    print("Speech setup: --speech-model small.en (or large-v2 / skip); downloads require an explicit yes.")


def setup(name, *, yes=False, json_mode=False):
    """Shared doctor/setup consent. --yes is meaningful only with a model choice."""
    if name == "skip":
        return prepare({"speech_model": name})
    if name not in MODELS:
        raise ValueError("Choose small.en, large-v2 or skip.")
    if not local_path(name) and not yes:
        if json_mode or not sys.stdin.isatty():
            raise ValueError("Speech download requires explicit consent: --speech-model " + name + " --yes.")
        print("To keep spoken lines whole and place captions: " + CHOICES[name])
        print("Download and verify this model? Type yes; Enter cancels: ", end="", flush=True)
        if sys.stdin.readline().strip().lower() not in {"yes", "y"}:
            raise ValueError("Speech download declined; choose skip or run setup again.")
        yes = True
    return prepare({"speech_model": name, "speech_download": yes},
                   progress=lambda text: print(text, file=sys.stderr if json_mode else sys.stdout, flush=True))
