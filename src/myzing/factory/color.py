"""Optional footage grading before the factory adds captions and graphics.

Validation and the source bypass are stdlib-only. Graded JPEGs are disposable,
content-addressed derivatives; the extracted frames and cut video stay intact.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

from .tools import FactoryError, ffmpeg, ffprobe, run

VERSION = 1
LOOK_VERSION = 2  # Increment when the procedural look or JPEG transform changes.
DEFAULTS = {
    "color_look": "source",
    "color_strength": 0.5,
    "color_exposure": 0.0,
    "color_temperature": 0.0,
    "color_tint": 0.0,
}
_BOUNDS = {
    "color_strength": (0.0, 1.0),
    "color_exposure": (-1.0, 1.0),
    "color_temperature": (-0.25, 0.25),
    "color_tint": (-0.25, 0.25),
}


def normalize(settings: dict) -> dict:
    """Return only the color settings, without loading optional dependencies."""
    if not isinstance(settings, dict):
        raise FactoryError("Color settings must be an object.")
    result = {key: settings.get(key, value) for key, value in DEFAULTS.items()}
    if result["color_look"] not in ("source", "cinematic-cool"):
        raise FactoryError("color_look must be source or cinematic-cool.")
    for key, (low, high) in _BOUNDS.items():
        value = result[key]
        if type(value) not in (int, float) or not low <= value <= high or not math.isfinite(value):
            raise FactoryError(f"{key} must be a finite number from {low:g} to {high:g}.")
        result[key] = float(value)
    return result


def active(settings: dict) -> bool:
    return ((settings["color_look"] != "source" and settings["color_strength"] > 0)
            or any(settings[key] for key in ("color_exposure", "color_temperature", "color_tint")))


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _frames(folder: Path) -> list[dict]:
    files = sorted(folder.glob("*.jpg"), key=lambda path: (len(path.stem), path.stem))
    if not files:
        raise FactoryError(f"No source frames in {folder}; cut the clip before grading it.")
    rows = []
    for number, path in enumerate(files, 1):
        if path.name != f"{number:05d}.jpg" or not path.is_file() or path.stat().st_size == 0:
            raise FactoryError("Color grading needs complete numbered frames starting at 00001.jpg; re-cut this clip.")
        rows.append({"name": path.name, "sha256": _digest(path)})
    return rows


def _run(*args, cwd=None):
    """Use factory cancellation, limited CPU, and no visible Windows helper."""
    try:
        return run(*args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600,
                   **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
    except subprocess.CalledProcessError as exc:
        raise FactoryError(f"Color grading failed: {(exc.stderr or str(exc))[-2000:]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise FactoryError("Color grading timed out; retry with a shorter clip.") from exc
    except OSError as exc:
        raise FactoryError(f"Cannot run color grading: {exc}") from exc


def _probe_metadata(path: Path) -> dict:
    # Mirror color.media.probe's metadata contract through the factory's
    # cancellable process runner. No protocol besides local files is enabled.
    if str(path).replace("\\", "/").startswith("//"):
        raise FactoryError("Color grading needs local source files; network paths are not supported.")
    if not path.is_file():
        raise FactoryError(f"Color source is missing: {path}")
    data = json.loads(_run(ffprobe(), "-v", "error", "-protocol_whitelist", "file,pipe",
                           "-select_streams", "v:0", "-show_streams", "-show_format", "-of", "json", path).stdout)
    streams = data.get("streams") or []
    if not streams:
        raise FactoryError(f"Color source has no video stream: {path}")
    stream = streams[0]
    metadata = {key: str(stream.get(key, "unknown")) for key in (
        "color_space", "color_transfer", "color_primaries", "color_range", "pix_fmt")}
    tags = {**data.get("format", {}).get("tags", {}), **stream.get("tags", {})}
    metadata["profile_tags"] = json.dumps({key: value for key, value in tags.items()
        if any(term in key.lower() for term in ("color", "gamma", "transfer", "profile"))}, sort_keys=True)
    return metadata


def _metadata(directory: Path) -> tuple[dict, list[str]]:
    from myzing.color.media import check_color_space
    metadata, warnings = {}, []
    metadata["cut"] = _probe_metadata(directory / "cut.mp4")
    warnings.extend(check_color_space(metadata["cut"]))
    words = directory / "words.json"
    original = None
    if words.is_file():
        data = json.loads(words.read_text(encoding="utf-8"))
        source = data.get("source")
        if isinstance(source, str) and source:
            candidate = Path(source).expanduser()
            if not candidate.is_absolute():
                candidate = directory.parent / candidate
            if str(candidate).replace("\\", "/").startswith("//"):
                raise FactoryError("Color grading needs local source files; network paths are not supported.")
            if candidate.is_file():
                original = candidate
    if original is not None:
        metadata["original"] = _probe_metadata(original)
        warnings.extend(check_color_space(metadata["original"]))
    else:
        warnings.append("Original source is unavailable; only cut.mp4 color metadata was checked. "
                        "Untagged LOG/HDR cannot be ruled out.")
    warnings.append("Original procedural look, not the reference creator's LUT. "
                    "Warm-hue protection is a color mask, not face or skin detection.")
    return metadata, list(dict.fromkeys(warnings))


def _cube(settings: dict):
    """A conservative original look; every correction is explicit and baked once."""
    from myzing.color.cube import Cube
    from myzing.color.looks import apply_transform
    from myzing.color.models import LookParameters, Transform
    from myzing.color.science import encode, linearize, np

    axis = np.linspace(0, 1, 33)
    b, g, r = np.meshgrid(axis, axis, axis, indexing="ij")
    rgb = np.stack((r, g, b), axis=-1).reshape(-1, 3)
    # These gains are deliberate controls, never a guessed camera white balance
    # or temperature in kelvin. Positive tint moves toward magenta.
    temperature, tint = settings["color_temperature"], settings["color_tint"]
    gains = np.exp2([temperature + tint / 2, -tint / 2, -temperature + tint / 2])
    x = np.clip(encode(linearize(rgb) * (2 ** settings["color_exposure"]) * gains), 0, 1)
    strength = settings["color_strength"] if settings["color_look"] == "cinematic-cool" else 0
    if strength:
        parameters = LookParameters(contrast=1.18, saturation=1.04, gamma=1.02,
                                    shadows=[-0.05, 0.012, 0.045], highlights=[0.025, 0.008, -0.007])
        graded = apply_transform(x, Transform("cinematic-cool", parameters))
        # A smooth mask softens the creative grade across warm reds/yellows.
        # It protects those colors in objects too; it makes no skin claims.
        maximum, minimum = x.max(axis=1), x.min(axis=1)
        chroma = maximum - minimum
        hue = np.zeros_like(chroma)
        nonzero = chroma > 1e-9
        red = nonzero & (maximum == x[:, 0])
        green = nonzero & ~red & (maximum == x[:, 1])
        blue = nonzero & ~red & ~green
        hue[red] = ((x[red, 1] - x[red, 2]) / chroma[red]) % 6
        hue[green] = (x[green, 2] - x[green, 0]) / chroma[green] + 2
        hue[blue] = (x[blue, 0] - x[blue, 1]) / chroma[blue] + 4
        hue *= 60
        distance = np.minimum(np.abs(hue - 30), 360 - np.abs(hue - 30))
        warm = np.exp(-((distance / 38) ** 4)) * np.clip(chroma / 0.12, 0, 1)
        # Selective green saturation is slight and only changes already-green
        # pixels. It does not create a green wash over neutral backgrounds.
        green_distance = np.minimum(np.abs(hue - 125), 360 - np.abs(hue - 125))
        green_weight = np.exp(-((green_distance / 40) ** 4)) * np.clip(chroma / 0.15, 0, 1)
        luma = graded @ np.array([0.2126, 0.7152, 0.0722])
        graded += (graded - luma[:, None]) * (0.08 * green_weight[:, None])
        # Anchor black and white so the shadow tint does not turn true black
        # blue or tint white highlights. The manual corrections stay separate.
        source_luma = x @ np.array([0.2126, 0.7152, 0.0722])
        headroom = np.clip(np.minimum(source_luma / 0.08, (1 - source_luma) / 0.10), 0, 1)
        graded = x + headroom[:, None] * (graded - x)
        x = np.clip(x + strength * (1 - 0.8 * warm[:, None]) * (graded - x), 0, 1)
    title = "Zing manual corrections" if settings["color_look"] == "source" else "Zing cinematic-cool original procedural look"
    return Cube(33, x.tolist(), title)


def _valid_cache(target: Path, identity: dict, names: list[str]) -> dict | None:
    try:
        if target.is_symlink() or (target / "frames").is_symlink():
            return None
        manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
        if manifest["identity"] != identity:
            return None
        outputs = manifest["outputs"]
        if [row["name"] for row in outputs] != names:
            return None
        actual = sorted((p.name for p in (target / "frames").iterdir()), key=lambda name: (len(name), name))
        if actual != names:
            return None
        if any(not (target / "frames" / row["name"]).is_file()
               or _digest(target / "frames" / row["name"]) != row["sha256"] for row in outputs):
            return None
        color = manifest["color"]
        if color["settings"] != identity["settings"] or color["version"] != VERSION or color["active"] is not True:
            return None
        if _digest(target / "look.cube") != color["lut_sha256"]:
            return None
        return manifest["color"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def prepare(directory: Path, settings: dict) -> dict:
    """Return source or complete cached graded frames, with a saved color recipe."""
    settings = normalize(settings)
    directory = Path(directory).resolve()
    source = directory / "frames"
    color = {"version": VERSION, "active": active(settings), "settings": settings, "warnings": []}
    if not color["active"]:
        return {"frames_dir": str(source), "color": color}
    from myzing.color import ColorError, require_numpy
    try:
        require_numpy()
        from myzing.color.cube import write_cube
        metadata, warnings = _metadata(directory)
        inputs = _frames(source)
        identity = {"version": VERSION, "look_version": LOOK_VERSION, "settings": settings,
                    "inputs": inputs, "color_metadata": metadata}
        key = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        cache = directory / "color-cache"
        if cache.is_symlink():
            raise FactoryError("Color cache must be a local directory, not a symbolic link.")
        cache.mkdir(exist_ok=True)
        target = cache / key
        names = [row["name"] for row in inputs]
        cached = _valid_cache(target, identity, names)
        if cached is not None:
            return {"frames_dir": str(target / "frames"), "color": cached}
        staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=cache))
        try:
            (staging / "frames").mkdir()
            write_cube(_cube(settings), staging / "look.cube")
            # Factory frames are JPEG display images, not the original YUV
            # video. Explicit full-range JPEG BT.601 decoding avoids applying
            # the source video's matrix a second time. Browser JPEGs use the
            # same matrix on output; the creative transform works in RGB.
            filters = ("scale=in_color_matrix=bt601:in_range=pc,format=rgb24,"
                       "lut3d=file=look.cube:interp=trilinear,"
                       "scale=out_color_matrix=bt601:out_range=pc,format=yuvj444p")
            command = [ffmpeg(), "-v", "error", "-nostdin", "-xerror", "-n", "-threads", "2",
                       "-filter_threads", "1", "-protocol_whitelist", "file,pipe", "-framerate", "30",
                       "-start_number", "1", "-i", "../../frames/%05d.jpg", "-an", "-sn", "-vf", filters,
                       "-frames:v", str(len(inputs)), "-fps_mode", "passthrough", "-threads", "2",
                       "-q:v", "2", "-start_number", "1", "frames/%05d.jpg"]
            # Only controlled LUT/output basenames enter the filtergraph.
            _run(*command, cwd=staging)
            outputs = _frames(staging / "frames")
            if [row["name"] for row in outputs] != names:
                raise FactoryError("Color grading did not produce every source frame; the original clip is unchanged.")
            if _frames(source) != inputs:
                raise FactoryError("Source frames changed during color grading; retry after the re-cut completes.")
            color.update(warnings=warnings, color_metadata=metadata, cache_key=key, frame_count=len(inputs),
                         look_version=LOOK_VERSION,
                         lut_sha256=_digest(staging / "look.cube"),
                         color_space="SDR Rec.709/sRGB display RGB; JPEG full-range BT.601 decode and encode",
                         interpretation="Original procedural look; manual exposure and white balance, no automatic correction.")
            (staging / "recipe.json").write_text(json.dumps(color, indent=2, allow_nan=False), encoding="utf-8")
            (staging / "manifest.json").write_text(json.dumps(
                {"identity": identity, "outputs": outputs, "color": color}, sort_keys=True, allow_nan=False), encoding="utf-8")
            if target.exists():
                # Another renderer may have finished while this one was busy.
                cached = _valid_cache(target, identity, names)
                if cached is not None:
                    return {"frames_dir": str(target / "frames"), "color": cached}
                if target.is_symlink():
                    raise FactoryError("Color cache entry is a symbolic link; remove it before retrying.")
                # Keep damaged generated entries for diagnosis rather than
                # changing an existing directory while a reader uses it.
                target.rename(cache / f".invalid-{key}-{uuid.uuid4().hex[:8]}")
            try:
                staging.rename(target)
            except OSError:
                cached = _valid_cache(target, identity, names)
                if cached is None:
                    raise
                color = cached
            return {"frames_dir": str(target / "frames"), "color": color}
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
    except (ColorError, OSError, ValueError, TypeError, KeyError) as exc:
        raise FactoryError(f"Cannot prepare footage color: {exc}") from exc
