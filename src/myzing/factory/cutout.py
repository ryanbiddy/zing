"""Speaker cutout: the person lifted off their background, so a shot can stand them in front of the picture.

rembg's IS-Net general-use segmentation model (Apache-2.0) runs on the CPU through ONNX Runtime. The weights are
fetched only on request (``zing factory fetch-cutout --yes``) through Zing's shared verified downloader: pinned
release, byte limit and SHA-256 before publish. Rendering never downloads; without the weights, or when the speaker
is too small or too lost in the frame to lift cleanly, those shots stay split.
"""
from __future__ import annotations

import json
from pathlib import Path

from myzing import model_fetch
from myzing.storage import workspace_root

from .tools import FactoryError
from .network import Network

MODEL = "isnet-general-use"
URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx"
SHA256, SIZE = "60920e99c45464f2ba57bee2ad08c919a52bbf852739e96947fbb4358c0d964a", 178_648_008
FETCH_HINT = "zing factory fetch-cutout --yes (Apache-2.0 weights, about 179 MB)"
VERSION = 1                                     # bump when the mattes change so cached clips redo them
FPS, STEP, WIDTH = 30, 2, 960                   # segment every 2nd frame and blend between; mattes 960 px wide
PERSON = (.04, .85)                             # the speaker's share of the frame a cutout can work with
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
    if _checked != stamp:                       # hash the 179 MB once per process, not on every render
        if not model_fetch.verified(path, SHA256):
            return False
        _checked = stamp
    return True


def fetch(*, consent: bool = False, progress=None, project: Path | None = None) -> Path:
    net = Network(project)
    net.check("cutout model download")
    if consent is not True:
        raise FactoryError(f"the cutout model download needs explicit consent: {FETCH_HINT}")
    if not ready():
        net.fetch(URL, model_file(), SHA256, SIZE, purpose="cutout model download", progress=progress)
        if not ready():
            raise FactoryError("cutout model size/SHA-256 verification failed; nothing installed")
    return model_file()


def segment(rgb):
    """The person in an RGB uint8 image as alpha, 0 background to 1 person, at the image's own size."""
    global _session
    import cv2
    import numpy as np
    if not ready():
        raise FactoryError(f"cutout model missing; run {FETCH_HINT}")
    if _session is None:
        import onnxruntime
        _session = onnxruntime.InferenceSession(str(model_file()), providers=["CPUExecutionProvider"])
    h, w = rgb.shape[:2]
    x = cv2.resize(rgb, (1024, 1024), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    x = x / max(float(x.max()), 1e-6) - .5     # rembg's IS-Net preprocessing: scale to 0-1, mean .5, std 1
    out = _session.run(None, {_session.get_inputs()[0].name: x.transpose(2, 0, 1)[None]})[0][0, 0]
    lo, hi = float(out.min()), float(out.max())
    out = (out - lo) / max(hi - lo, 1e-6)
    return cv2.resize(out, (w, h), interpolation=cv2.INTER_LINEAR).astype(np.float32)


def tidy(alpha):
    """Firm up the matte: drop the faint haze around the person and soften the edge by a pixel."""
    import cv2
    import numpy as np
    a = np.clip((alpha - .15) / .7, 0, 1)
    return cv2.GaussianBlur(a, (0, 0), max(1.0, a.shape[1] / 960)).astype(np.float32)


def usable(shares: list[float]) -> str | None:
    """Why the speaker can't be lifted cleanly (too small, missing, filling the frame), or None when they can."""
    if not shares:
        return "no frames to cut out"
    present = sum(1 for s in shares if s > .02) / len(shares)
    mid = sorted(shares)[len(shares) // 2]
    if present < .9:
        return f"the speaker is missing from {1 - present:.0%} of the frames"
    if not PERSON[0] <= mid <= PERSON[1]:
        return f"the speaker fills {mid:.0%} of the frame; a cutout needs {PERSON[0]:.0%}-{PERSON[1]:.0%}"
    return None


def frames_in(spans: list[tuple[float, float]], total: int) -> list[int]:
    """1-based frame numbers inside the spans (seconds), with the frames a blend needs on either side."""
    want = set()
    for a, b in spans:
        first, last = max(1, int(a * FPS) + 1), min(total, int(b * FPS) + 1)
        want.update(range(first, last + 1))
    return sorted(want)


def mattes(clipdir: Path, spans: list[tuple[float, float]]) -> dict | None:
    """Alpha mattes for the clip's frames inside spans, as PNGs in clipdir/mattes, reused when unchanged.

    Returns {"dir": the folder, "frames": the frame numbers with a matte}, or None (with the reason kept in
    mattes/meta.json) when the speaker can't be lifted cleanly.
    """
    import cv2
    import numpy as np
    d = Path(clipdir)
    cam = json.loads((d / "cams.json").read_text(encoding="utf-8"))
    total, src = int(cam["frames"]), d / "frames"
    want = frames_in(spans, total)
    if not want:
        return None
    out, meta_path = d / "mattes", d / "mattes" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    if meta.get("v") == VERSION and ((meta.get("why") and meta.get("want") == want)
                                     or set(want) <= set(meta.get("frames", []))):
        return None if meta.get("why") else {"dir": out, "frames": meta["frames"]}
    out.mkdir(parents=True, exist_ok=True)
    keys = sorted(set(want[::STEP]) | {want[-1]})
    alphas, shares = {}, []
    for f in keys:
        bgr = cv2.imread(str(src / f"{f:05d}.jpg"))
        if bgr is None:
            continue
        if bgr.shape[1] > WIDTH:
            bgr = cv2.resize(bgr, (WIDTH, round(bgr.shape[0] * WIDTH / bgr.shape[1])), interpolation=cv2.INTER_AREA)
        alphas[f] = tidy(segment(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))
        shares.append(float((alphas[f] > .5).mean()))
    why = usable(shares)
    done = sorted(set(meta.get("frames", []))) if meta.get("v") == VERSION else []
    if why:
        meta_path.write_text(json.dumps({"v": VERSION, "why": why, "frames": [], "want": want}), encoding="utf-8")
        return None
    have = sorted(alphas)
    for f in want:                                   # in-between frames blend their two neighbours
        if f in alphas:
            a = alphas[f]
        else:
            k = int(np.searchsorted(have, f))
            lo, hi = have[max(k - 1, 0)], have[min(k, len(have) - 1)]
            x = 0 if hi == lo else (f - lo) / (hi - lo)
            a = alphas[lo] * (1 - x) + alphas[hi] * x
        a8 = (a * 255).astype(np.uint8)                # black, with the matte as its alpha: the scene keeps the
        cv2.imwrite(str(out / f"{f:05d}.png"), np.dstack([np.zeros_like(a8)] * 3 + [a8]),   # frame where it's opaque
                    [cv2.IMWRITE_PNG_COMPRESSION, 1])
    frames = sorted(set(done) | set(want))
    meta_path.write_text(json.dumps({"v": VERSION, "frames": frames, "share": round(sorted(shares)[len(shares) // 2], 3)}),
                         encoding="utf-8")
    return {"dir": out, "frames": frames}
