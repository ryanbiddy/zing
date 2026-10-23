"""Explicit, verified CED weight provisioning; analysis never downloads.

The GPL training implementation is neither imported nor distributed. Only the
Apache-2.0 ONNX weights run, through sherpa-onnx's own feature extractor.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from myzing.storage import workspace_root

REVISION = "4da6df50dc47b25f91074b5ef7df4c1cc0dd7d4d"
REPOSITORY = "k2-fsa/sherpa-onnx-ced-mini-audio-tagging-2024-04-19"
BASE_URL = f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/"
ASSETS = {
    "model.int8.onnx": ("ff29f39f9fbe637f72535160e9d006d61d872fdab0fce838672265b9b38cf946", 10_451_715),
    "class_labels_indices.csv": ("cdd1049833c4b86127c2773ac0d14a2754b6a6d0d1798002ed5c66e699708429", 14_675),
}
INSTALL_HINT = 'python -m pip install "myzing[audio-ml]"'
FETCH_HINT = "zing audio fetch-model --consent (Apache-2.0 weights; about 10.5 MB)"


def cache_dir() -> Path:
    return workspace_root() / "models" / "ced-mini"


def verified(path: Path, digest: str, size: int) -> bool:
    return (path.is_file() and path.stat().st_size == size
            and hashlib.sha256(path.read_bytes()).hexdigest() == digest)


def model_paths() -> dict[str, Path]:
    paths = {name: cache_dir() / name for name in ASSETS}
    for name, (digest, size) in ASSETS.items():
        if not verified(paths[name], digest, size):
            raise RuntimeError(f"CED asset missing or corrupt: {name}. Run {FETCH_HINT}.")
    return paths


def _https(url: str) -> None:
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError("CED downloads and redirects must use HTTPS")


class _HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _https(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_models(*, consent: bool = False) -> list[Path]:
    if not consent:
        raise ValueError(f"Model download needs explicit consent. Run {FETCH_HINT}.")
    root = cache_dir()
    root.mkdir(parents=True, exist_ok=True)
    opener = urllib.request.build_opener(_HTTPSRedirect())
    paths = []
    for name, (digest, size) in ASSETS.items():
        target = root / name
        if not verified(target, digest, size):
            url = BASE_URL + name
            _https(url)
            with opener.open(url, timeout=60) as response:
                _https(response.geturl())
                payload = response.read(size + 1)
            if len(payload) != size or hashlib.sha256(payload).hexdigest() != digest:
                raise RuntimeError(f"CED size/SHA-256 verification failed: {name}; no asset installed")
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=root, suffix=".part", delete=False) as out:
                    temporary = Path(out.name)
                    out.write(payload)
                os.replace(temporary, target)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        paths.append(target)
    return paths


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
