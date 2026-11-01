"""Depth parallax for still photos: a slow camera move that follows the picture's own depth.

Depth Anything V2 Small (Apache-2.0) runs on the CPU through ONNX Runtime. The weights are fetched only on
request (``zing factory fetch-depth --yes``) through Zing's shared verified downloader: pinned revision, byte
limit and SHA-256 before publish. Rendering never downloads; without the weights a photo keeps the flat zoom.
The move only shifts and scales what is in the photo. Nothing is generated or added.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from myzing import model_fetch
from myzing.storage import workspace_root

from .tools import FactoryError, ffmpeg

MODEL = "depth-anything-v2-small"
REPOSITORY = "onnx-community/depth-anything-v2-small"
REVISION = "4472b7362082ad9968fee890ca0f1e5aca36b93d"
URL = f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/onnx/model.onnx"
SHA256, SIZE = "afb6a5c28f3b6bf1618c6e43f02073ef9dfdc70e937502d51603e57b0a1df10c", 99_060_839
FETCH_HINT = "zing factory fetch-depth --yes (Apache-2.0 weights, about 99 MB)"
VERSION = 1                                     # bump when the move changes so cached clips re-render
MOVES = {"push-left": (-1, 0), "push-right": (1, 0), "rise": (0, -1)}
_session = None
_checked = None


def model_file() -> Path:
    return workspace_root() / "models" / MODEL / "model.onnx"


def ready() -> bool:
    global _checked
    path = model_file()
    if not path.is_file() or path.stat().st_size != SIZE:
        return False
    stamp = (str(path), path.stat().st_mtime_ns)
    if _checked != stamp:                       # hash the 99 MB once per process, not on every render
        if not model_fetch.verified(path, SHA256):
            return False
        _checked = stamp
    return True


def fetch(*, consent: bool = False, progress=None) -> Path:
    if consent is not True:
        raise FactoryError(f"the depth model download needs explicit consent: {FETCH_HINT}")
    if not ready():
        model_fetch.fetch_verified(URL, model_file(), SHA256, SIZE, progress=progress)
        if not ready():
            raise FactoryError("depth model size/SHA-256 verification failed; nothing installed")
    return model_file()


def estimate(rgb):
    """Relative depth for an RGB uint8 image, 0 far to 1 near, at the image's own size."""
    global _session
    import cv2
    import numpy as np
    if not ready():
        raise FactoryError(f"depth model missing; run {FETCH_HINT}")
    if _session is None:
        import onnxruntime
        _session = onnxruntime.InferenceSession(str(model_file()), providers=["CPUExecutionProvider"])
    h, w = rgb.shape[:2]
    s = 518 / min(h, w)                         # the model card's preprocessing: short side 518, multiples of 14
    nh, nw = (max(14, round(x * s / 14) * 14) for x in (h, w))
    nh, nw = min(nh, 1036), min(nw, 1036)       # cap panoramas
    x = cv2.resize(rgb, (nw, nh), interpolation=cv2.INTER_CUBIC).astype(np.float32) / 255
    x = (x - np.array([.485, .456, .406], np.float32)) / np.array([.229, .224, .225], np.float32)
    feed = {_session.get_inputs()[0].name: x.transpose(2, 0, 1)[None]}
    out = _session.run(None, feed)[0].reshape(nh, nw)
    out = cv2.resize(out, (w, h), interpolation=cv2.INTER_CUBIC)
    lo, hi = np.percentile(out, (2, 98))
    return np.clip((out - lo) / max(hi - lo, 1e-6), 0, 1).astype(np.float32)


def flat(depth) -> bool:
    """A screenshot, chart or flat graphic: no depth worth moving through."""
    import numpy as np
    return float(np.std(depth)) < .12


def frames(bgr, depth, n: int, move: str = "push-left", travel: float = .022, push: float = .07, zoom: float = .03,
           margin: float = .04):
    """Yield n BGR frames of a camera move: near things slide and grow more than far ones.

    Output pixel p shows the source point q with p = c + (q - c)(1 + tau(zoom + push(d - f))) + t(tau)(d - f), where
    d is q's depth, f the subject's depth (it only zooms) and tau eases 0 to 1. q is found by a fixed-point
    iteration, which keeps the nearest surface at an edge. The view is cropped by margin so no edge ever shows.
    """
    import cv2
    import numpy as np
    h, w = depth.shape
    k = max(3, int(w * .006) | 1)               # grow near edges a little, then soften: the warp stretches, never tears
    d = cv2.GaussianBlur(cv2.dilate(depth, np.ones((k, k), np.uint8)), (0, 0), w * .008)
    f = float(np.percentile(d, 70))
    ux, uy = MOVES[move]
    cx, cy = (w - 1) / 2, (h - 1) / 2
    gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    px, py = cx + (gx - cx) * (1 - 2 * margin), cy + (gy - cy) * (1 - 2 * margin)
    for i in range(n):
        x = i / max(n - 1, 1)
        tau = 4 * x ** 3 if x < .5 else 1 - (-2 * x + 2) ** 3 / 2
        tx, ty = (tau - .5) * 2 * travel * w * ux, (tau - .5) * 2 * travel * w * uy
        qx, qy = px.copy(), py.copy()
        for _ in range(3):
            rel = cv2.remap(d, qx, qy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE) - f
            grow = 1 + tau * (zoom + push * rel)
            qx, qy = cx + (px - tx * rel - cx) / grow, cy + (py - ty * rel - cy) / grow
        yield cv2.remap(bgr, qx, qy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def move_for(key: str) -> str:
    names = sorted(MOVES)
    return names[int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(names)]


def parallax(image: Path, out: Path, seconds: float, *, key: str = "", width: int = 1600, fps: int = 30) -> Path | None:
    """Encode the move for a photo to out (an mp4), reusing it when nothing changed. None when the photo is flat."""
    import cv2
    import numpy as np
    image, out = Path(image), Path(out)
    n = max(2, round(seconds * fps))
    stamp = {"v": VERSION, "src": str(image.resolve()), "mtime": image.stat().st_mtime, "n": n, "w": width,
             "move": move_for(key or image.name)}
    meta = out.with_suffix(".json")
    if out.is_file() and meta.is_file() and json.loads(meta.read_text(encoding="utf-8")) == stamp:
        return out
    bgr = cv2.imdecode(np.fromfile(str(image), np.uint8), cv2.IMREAD_COLOR)
    if bgr is None or min(bgr.shape[:2]) < 360:
        return None
    if bgr.shape[1] > width:
        bgr = cv2.resize(bgr, (width, round(bgr.shape[0] * width / bgr.shape[1])), interpolation=cv2.INTER_AREA)
    bgr = bgr[: bgr.shape[0] // 2 * 2, : bgr.shape[1] // 2 * 2]
    depth = estimate(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    if flat(depth):
        return None
    h, w = depth.shape
    out.parent.mkdir(parents=True, exist_ok=True)
    enc = subprocess.Popen([ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
                            "-r", str(fps), "-i", "-", "-c:v", "libx264", "-crf", "17", "-preset", "medium",
                            "-pix_fmt", "yuv420p", str(out)], stdin=subprocess.PIPE)
    try:
        for frame in frames(bgr, depth, n, stamp["move"]):
            enc.stdin.write(np.ascontiguousarray(frame).tobytes())
    finally:
        enc.stdin.close()
        enc.wait()
    if enc.returncode:
        raise FactoryError(f"FFmpeg could not encode the parallax for {image.name}")
    meta.write_text(json.dumps(stamp), encoding="utf-8")
    return out
