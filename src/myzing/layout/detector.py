"""Explicit, checksum-verified YuNet provisioning and CPU-only inference."""

from __future__ import annotations

import hashlib
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from myzing.storage import workspace_root

from .types import Detection, bounds, number

OPENCV_VERSION = "4.13.0"
MODEL_COMMIT = "f12e12798e8314f7c074a6656816c048dcc95b7a"
MODEL_NAME = "face_detection_yunet_2023mar.onnx"
MODEL_URL = (f"https://media.githubusercontent.com/media/opencv/opencv_zoo/{MODEL_COMMIT}"
             f"/models/face_detection_yunet/{MODEL_NAME}")
MODEL_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
MODEL_SIZE = 232589
MODEL_LICENSE = "MIT"
INSTALL_HINT = 'Install the optional runtime: python -m pip install "myzing[layout]" (checkout: uv sync --all-extras).'


class LayoutError(RuntimeError):
    """An actionable layout failure."""


def model_path(workspace: Path | None = None) -> Path:
    return (workspace or workspace_root()).expanduser().resolve() / "models" / "yunet" / MODEL_NAME


def verified_model(path: Path) -> bool:
    return (path.is_file() and path.stat().st_size == MODEL_SIZE and
            hashlib.sha256(path.read_bytes()).hexdigest() == MODEL_SHA256)


def fetch_model(workspace: Path | None = None) -> Path:
    """Only call from explicit download commands/flags. Atomic cache replacement."""
    target = model_path(workspace)
    if verified_model(target):
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "Zing-layout/1"})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read(MODEL_SIZE + 1)
        if len(data) != MODEL_SIZE or hashlib.sha256(data).hexdigest() != MODEL_SHA256:
            raise LayoutError("YuNet download failed size/SHA-256 verification; cache was not changed. "
                              "Retry 'zing layout fetch-model'.")
        with tempfile.NamedTemporaryFile(dir=target.parent, suffix=".part", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, target)
    except (OSError, urllib.error.URLError) as exc:
        raise LayoutError(f"YuNet download failed: {exc}. Retry 'zing layout fetch-model'.") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target


def require_model(workspace: Path | None = None, *, download: bool = False) -> Path:
    path = fetch_model(workspace) if download else model_path(workspace)
    if not verified_model(path):
        raise LayoutError(f"YuNet model missing or corrupt at {path}. "
                          "Run 'zing layout fetch-model' with the same --workspace, "
                          "or explicitly pass --fetch-model to captions.")
    return path


def load_cv2():
    try:
        import cv2
    except (ImportError, OSError) as exc:
        raise LayoutError(f"OpenCV could not be loaded. {INSTALL_HINT}") from exc
    if cv2.__version__ != OPENCV_VERSION or not hasattr(cv2, "FaceDetectorYN"):
        raise LayoutError(f"YuNet requires OpenCV {OPENCV_VERSION}; found {cv2.__version__}. "
                          "Remove conflicting opencv-python/contrib wheels and reinstall "
                          "opencv-python-headless==4.13.0.92. In this checkout use "
                          "'uv sync --all-extras --reinstall-package opencv-python-headless'.")
    return cv2


class YuNetDetector:
    def __init__(self, workspace: Path | None = None, *, download: bool = False,
                 score_threshold: float = 0.6) -> None:
        number(score_threshold, "score_threshold", 0.01, 1)
        self.cv2 = load_cv2()
        self.model = require_model(workspace, download=download)
        try:
            self.detector = self.cv2.FaceDetectorYN.create(
                str(self.model), "", (320, 320), score_threshold, 0.3, 5000,
                self.cv2.dnn.DNN_BACKEND_OPENCV, self.cv2.dnn.DNN_TARGET_CPU,
            )
        except self.cv2.error as exc:
            raise LayoutError(f"YuNet initialization failed: {exc}. {INSTALL_HINT}") from exc

    def detect(self, image) -> list[Detection]:
        """BGR image in display orientation. Landmarks are discarded immediately."""
        if image is None or len(image.shape) != 3 or image.shape[2] != 3:
            raise LayoutError("YuNet needs a decoded three-channel BGR frame")
        height, width = image.shape[:2]
        if width <= 0 or height <= 0:
            raise LayoutError("YuNet received an empty frame")
        try:
            self.detector.setInputSize((width, height))
            _, faces = self.detector.detect(image)
        except self.cv2.error as exc:
            raise LayoutError(f"YuNet inference failed: {exc}; verify the pinned OpenCV/model pair") from exc
        detections = []
        if faces is not None:
            for face in faces:
                x, y, w, h = (float(v) for v in face[:4])
                left, top = max(0, x / width), max(0, y / height)
                right, bottom = min(1, (x + w) / width), min(1, (y + h) / height)
                if right > left and bottom > top:
                    detections.append(Detection(bounds(left, top, right, bottom), float(face[-1])))
        return sorted(detections, key=lambda d: (d.box.x, d.box.y, -d.confidence))
