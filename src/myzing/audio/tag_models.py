"""Explicit, verified CED weight provisioning; analysis never downloads.

The GPL training implementation is neither imported nor distributed. Only the
Apache-2.0 ONNX weights run, through sherpa-onnx's own feature extractor.
Downloads use the shared ``myzing.model_fetch`` path (HTTPS on every hop,
streamed with a byte limit, SHA-256 before publish, one downloader per folder)
and the same explicit consent as speech-model setup.
"""
from __future__ import annotations

import sys
from pathlib import Path

from myzing import model_fetch
from myzing.storage import workspace_root

MODEL = "ced-mini"
REVISION = "4da6df50dc47b25f91074b5ef7df4c1cc0dd7d4d"
REPOSITORY = "k2-fsa/sherpa-onnx-ced-mini-audio-tagging-2024-04-19"
BASE_URL = f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/"
ASSETS = {
    "model.int8.onnx": ("ff29f39f9fbe637f72535160e9d006d61d872fdab0fce838672265b9b38cf946", 10_451_715),
    "class_labels_indices.csv": ("cdd1049833c4b86127c2773ac0d14a2754b6a6d0d1798002ed5c66e699708429", 14_675),
}
INSTALL_HINT = 'python -m pip install "myzing[audio-ml]"'
FETCH_HINT = ("zing doctor --audio-model ced-mini (or zing audio fetch-model --consent; "
              "Apache-2.0 weights, about 10.5 MB)")
CHOICE = ("CED-mini audio tags (Apache-2.0, about 10.5 MB): tells singing from instruments, "
          "flags a clip's own music under speech, and marks laughter/applause candidates.")


def cache_dir() -> Path:
    return workspace_root() / "models" / MODEL


def verified(path: Path, digest: str, size: int) -> bool:
    path = Path(path)
    return path.is_file() and path.stat().st_size == size and model_fetch.verified(path, digest)


def model_paths() -> dict[str, Path]:
    paths = {name: cache_dir() / name for name in ASSETS}
    for name, (digest, size) in ASSETS.items():
        if not verified(paths[name], digest, size):
            raise RuntimeError(f"CED asset missing or corrupt: {name}. Run {FETCH_HINT}.")
    return paths


def fetch_models(*, consent: bool = False, progress=None) -> list[Path]:
    return _fetch_models(consent=consent, progress=progress)[0]


def _fetch_models(*, consent: bool, progress=None) -> tuple[list[Path], int]:
    if consent is not True:
        raise ValueError(f"Model download needs explicit consent. Run {FETCH_HINT}.")
    root = cache_dir()
    paths = []
    downloaded = 0
    for name, (digest, size) in ASSETS.items():
        target = root / name
        if not verified(target, digest, size):
            if model_fetch.fetch_verified(BASE_URL + name, target, digest, size, progress=progress):
                downloaded += size
            if not verified(target, digest, size):
                raise RuntimeError(f"CED size/SHA-256 verification failed: {name}; no asset installed")
        paths.append(target)
    return paths, downloaded


def receipt(paths, downloaded: int) -> dict:
    return {"version": 1, "model": MODEL, "path": str(cache_dir()), "repository": REPOSITORY,
            "revision": REVISION, "sha256": {name: digest for name, (digest, _) in ASSETS.items()},
            "verified": True, "downloaded_bytes": downloaded, "license": "Apache-2.0",
            "runtime_version": runtime_version(), "files": [str(p) for p in paths]}


def setup(name: str = MODEL, *, yes: bool = False, json_mode: bool = False) -> dict:
    """Shared doctor/setup consent, the same rules as speech-model setup."""
    if name != MODEL:
        raise ValueError(f"Choose {MODEL}.")
    missing = [n for n, (digest, size) in ASSETS.items() if not verified(cache_dir() / n, digest, size)]
    if not missing:
        return receipt(model_paths().values(), 0)
    if not yes:
        if json_mode or not sys.stdin.isatty():
            raise ValueError(f"Audio-tag download requires explicit consent: --audio-model {MODEL} --yes.")
        print("For learned audio tags: " + CHOICE)
        print("Download and verify these weights? Type yes; Enter cancels: ", end="", flush=True)
        if sys.stdin.readline().strip().lower() not in {"yes", "y"}:
            raise ValueError("Audio-tag download declined; tags keep the labeled heuristic fallback.")
        yes = True
    paths, downloaded = _fetch_models(consent=yes, progress=lambda text: print(text, file=sys.stderr if json_mode else sys.stdout, flush=True))
    return receipt(paths, downloaded)


# sherpa-onnx 1.x links espeak-ng (GPL-3.0-or-later) for TTS; 2.0.0 removed it.
MIN_RUNTIME = (2, 0)


def runtime_version() -> str | None:
    from importlib import metadata
    try:
        return metadata.version("sherpa-onnx")
    except metadata.PackageNotFoundError:
        return None


def runtime_supported(version: str | None) -> bool:
    try:
        return tuple(int(part) for part in version.split(".")[:2]) >= MIN_RUNTIME
    except (AttributeError, ValueError):
        return False


def engine():
    import sherpa_onnx

    version = runtime_version()
    if not runtime_supported(version):
        raise RuntimeError(f"sherpa-onnx {version or 'of unknown version'} predates 2.0 (1.x links GPL espeak-ng); "
                           f"upgrade with {INSTALL_HINT}")
    paths = model_paths()
    config = sherpa_onnx.AudioTaggingConfig(
        model=sherpa_onnx.AudioTaggingModelConfig(
            ced=str(paths["model.int8.onnx"]), num_threads=2, provider="cpu"),
        labels=str(paths["class_labels_indices.csv"]), top_k=527,
    )
    if not config.validate():
        raise RuntimeError("CED configuration failed validation; run zing doctor")
    return sherpa_onnx.AudioTagging(config)
