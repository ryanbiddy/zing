"""Sharper small photos: Real-ESRGAN upscales a photo that would otherwise render soft.

The ncnn Vulkan build of Real-ESRGAN (BSD-3-Clause) runs on any GPU with Vulkan, AMD and Intel included. It is fetched
only on request (``zing factory fetch-upscale --yes``): this platform's release zip is size- and SHA-256-checked, then
only the program and the realesrgan-x4plus model are unpacked from it. Rendering never downloads; without it a photo
renders at its own size. An upscaled photo is sharper, but its finest texture is the model's guess, so its credit
says "upscaled".
"""
from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
import zipfile
from pathlib import Path

from myzing import model_fetch
from myzing.storage import workspace_root

from .tools import FactoryError

RELEASE = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-{}.zip"
BUILDS = {                                      # this platform's release zip: SHA-256 and size
    "windows": ("abc02804e17982a3be33675e4d471e91ea374e65b70167abc09e31acb412802d", 45_474_481),
    "macos": ("e0ad05580abfeb25f8d8fb55aaf7bedf552c375b5b4d9bd3c8d59764d2cc333a", 51_817_124),
    "ubuntu": ("e5aa6eb131234b87c0c51f82b89390f5e3e642b7b70f2b9bbe95b6a285a40c96", 46_931_474),
}
MODEL = "realesrgan-x4plus"
FETCH_HINT = "zing factory fetch-upscale --yes (Real-ESRGAN, BSD-3-Clause, about 50 MB)"
NEED, LONG = 1600, 2400                         # photos under 1600 px on the long side are upscaled, kept at 2400
VERSION = 1                                     # bump when the result changes so cached photos redo it
_checked = None


def build() -> str:
    return {"Windows": "windows", "Darwin": "macos"}.get(platform.system(), "ubuntu")


def folder() -> Path:
    return workspace_root() / "models" / "realesrgan-ncnn-vulkan"


def program() -> Path:
    return folder() / ("realesrgan-ncnn-vulkan.exe" if build() == "windows" else "realesrgan-ncnn-vulkan")


def members() -> list[str]:
    return [program().name, f"models/{MODEL}.param", f"models/{MODEL}.bin"] + (["vcomp140.dll"] if build() == "windows" else [])


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def ready() -> bool:
    global _checked
    info_path = folder() / "installed.json"
    if not info_path.is_file():
        return False
    info = json.loads(info_path.read_text(encoding="utf-8"))
    files = info.get("files", {})
    if info.get("zip") != BUILDS[build()][0] or sorted(files) != sorted(members()):
        return False
    stamp = tuple((n, (folder() / n).stat().st_mtime_ns) for n in files if (folder() / n).is_file())
    if len(stamp) != len(files):
        return False
    if _checked != stamp:                       # what runs is what was unpacked: hash it once per process
        if any(_sha(folder() / n) != digest for n, digest in files.items()):
            return False
        _checked = stamp
    return True


def fetch(*, consent: bool = False, progress=None) -> Path:
    if consent is not True:
        raise FactoryError(f"the upscaler download needs explicit consent: {FETCH_HINT}")
    if ready():
        return program()
    digest, size = BUILDS[build()]
    archive = folder() / "release.zip"
    folder().mkdir(parents=True, exist_ok=True)
    model_fetch.fetch_verified(RELEASE.format(build()), archive, digest, size, progress=progress)
    files = {}
    with zipfile.ZipFile(archive) as z:          # only the named members, so nothing lands outside the folder
        for name in members():
            target = folder() / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(name) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            files[name] = _sha(target)
    if build() != "windows":
        program().chmod(0o755)
    (folder() / "installed.json").write_text(json.dumps({"zip": digest, "files": files}, indent=1), encoding="utf-8")
    archive.unlink()
    if not ready():
        raise FactoryError("upscaler verification failed after unpacking; nothing usable installed")
    return program()


def upscale(photo: Path, out: Path) -> Path | None:
    """A 4x upscale of a small photo, saved as out (a JPEG) and reused when the photo is unchanged.

    None when the photo is already big enough, too tiny to be worth it, or the GPU run fails.
    """
    from PIL import Image
    photo, out = Path(photo), Path(out)
    stamp = {"v": VERSION, "src": str(photo.resolve()), "mtime": photo.stat().st_mtime}
    meta = out.with_suffix(".json")
    if out.is_file() and meta.is_file() and json.loads(meta.read_text(encoding="utf-8")) == stamp:
        return out
    with Image.open(photo) as im:
        w, h = im.size
    if max(w, h) >= NEED or min(w, h) < 64:
        return None
    if not ready():
        raise FactoryError(f"upscaler missing; run {FETCH_HINT}")
    out.parent.mkdir(parents=True, exist_ok=True)
    big = out.with_name(out.stem + ".x4.png")
    done = subprocess.run([str(program()), "-i", str(photo), "-o", str(big), "-n", MODEL, "-s", "4",
                           "-m", str(folder() / "models"), "-f", "png"], capture_output=True, check=False)
    if done.returncode or not big.is_file():
        big.unlink(missing_ok=True)
        return None                             # no Vulkan device, or the photo won't decode: keep it as it is
    with Image.open(big) as im:
        im = im.convert("RGB")
        s = min(1.0, LONG / max(im.size))
        if s < 1:
            im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
        im.save(out, "JPEG", quality=92)
    big.unlink()
    meta.write_text(json.dumps(stamp), encoding="utf-8")
    return out
