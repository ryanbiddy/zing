"""Pinned RapidOCR assets. Study only reads; provisioning is an explicit command.

Run ``python -m myzing.study.caption_models --fetch`` before an offline study.
The same PP-OCR assets are used by the existing caption reader (Apache-2.0).
"""

from __future__ import annotations

import argparse
import hashlib
from importlib.util import find_spec
from pathlib import Path

from myzing.storage import workspace_root
from myzing.model_fetch import fetch_verified, verified

BASE_URL = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.9.1/onnx/"
MODELS = {
    "Det": ("PP-OCRv6/det/PP-OCRv6_det_small.onnx",
            "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f"),
    "Cls": ("PP-OCRv4/cls/ch_ppocr_mobile_v2.0_cls_mobile.onnx",
            "e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c"),
    "Rec": ("PP-OCRv6/rec/PP-OCRv6_rec_small.onnx",
            "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884"),
}
FETCH_HINT = "Run python -m myzing.study.caption_models --fetch with the same ZING_HOME."


def cache_dir() -> Path:
    return workspace_root() / "models" / "caption-geometry"


def model_paths() -> dict[str, Path]:
    """Accept verified workspace assets or an existing RapidOCR installation cache."""
    spec = find_spec("rapidocr")
    installed = Path(spec.origin).parent / "models" if spec and spec.origin else None
    paths = {}
    for role, (relative, digest) in MODELS.items():
        name = Path(relative).name
        candidates = [cache_dir() / name]
        if installed:
            candidates.append(installed / name)
        path = next((p for p in candidates if verified(p, digest)), None)
        if path is None:
            raise RuntimeError(f"caption OCR model missing or corrupt: {name}. {FETCH_HINT}")
        paths[role] = path
    return paths


def fetch_models() -> list[Path]:
    """Explicit, bounded, hash-checked downloads; never called by study."""
    root = cache_dir()
    root.mkdir(parents=True, exist_ok=True)
    paths = []
    for relative, digest in MODELS.values():
        target = root / Path(relative).name
        fetch_verified(BASE_URL + relative, target, digest, 40_000_000)
        paths.append(target)
    return paths


def engine():
    from importlib.metadata import version
    from rapidocr import RapidOCR

    paths = model_paths()
    # Supplying all three paths bypasses RapidOCR's implicit download branch.
    params = {f"{role}.model_path": str(path) for role, path in paths.items()}
    params.update({"Global.text_score": 0.0, "Global.log_level": "error",
                   "EngineConfig.onnxruntime.intra_op_num_threads": 2,
                   "EngineConfig.onnxruntime.inter_op_num_threads": 1})
    return RapidOCR(params=params), f"rapidocr-{version('rapidocr')}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", required=True,
                        help="download pinned Apache-2.0 OCR assets into the workspace")
    parser.parse_args()
    for path in fetch_models():
        print(f"{path} | sha256={hashlib.sha256(path.read_bytes()).hexdigest()} | Apache-2.0")
