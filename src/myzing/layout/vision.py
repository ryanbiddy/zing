"""CPU OpenCV DNN adapters for Apache-2.0 OpenCV Zoo models.

Pre/postprocessing adapted from opencv_zoo at vision_models.REVISION;
see docs/THIRD-PARTY-NOTICES.md and bundled _data/docs/OPENCV-ZOO-LICENSES.md.
Scores are model confidence, not calibrated
probabilities of correctness. No mediapipe/Ultralytics runtime is used.
"""

from .detector import LayoutError, load_cv2
from .types import Detection, bounds
from .vision_models import require_model

COCO_CLASSES = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog",
    "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite",
    "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle",
    "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich",
    "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote",
    "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book",
    "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
)


def _detection(xyxy, width, height, score, label, method):
    import numpy as np
    if not np.isfinite(xyxy).all() or not 0 <= score <= 1:
        return None
    x1, y1, x2, y2 = xyxy
    x1, y1 = max(0., float(x1 / width)), max(0., float(y1 / height))
    x2, y2 = min(1., float(x2 / width)), min(1., float(y2 / height))
    if x2 <= x1 or y2 <= y1:
        return None
    return Detection(bounds(x1, y1, x2, y2), float(score), class_name=label, detector=method)


class _DNN:
    def __init__(self, name, workspace=None):
        self.cv2 = load_cv2()
        path = require_model(name, workspace)
        try:
            self.net = self.cv2.dnn.readNet(str(path))
            self.net.setPreferableBackend(self.cv2.dnn.DNN_BACKEND_OPENCV)
            self.net.setPreferableTarget(self.cv2.dnn.DNN_TARGET_CPU)
        except self.cv2.error as exc:
            raise LayoutError(f"Cannot load {name} model in pinned OpenCV: {exc}") from exc

    def detect(self, image):
        if image is None or len(image.shape) != 3 or image.shape[2] != 3 or min(image.shape[:2]) < 1:
            raise LayoutError("Vision detector needs a nonempty three-channel BGR image")
        try:
            blob, transform = self.preprocess(image)
            self.net.setInput(blob)
            outputs = self.net.forward(self.net.getUnconnectedOutLayersNames())
            return self.decode(outputs, image.shape[1], image.shape[0], transform)
        except self.cv2.error as exc:
            raise LayoutError(f"{self.method} inference failed: {exc}; verify the pinned OpenCV/model pair") from exc


class PersonDetector(_DNN):
    """MediaPipe pose detector's head-region boxes (not full-body extents)."""
    method = "mediapipe-person-head"
    threshold = .5

    def __init__(self, workspace=None):
        super().__init__("person", workspace)

    def preprocess(self, image):
        import numpy as np
        h, w = image.shape[:2]
        ratio = 224 / max(h, w)
        rw, rh = max(1, int(w * ratio)), max(1, int(h * ratio))
        left, top = (224 - rw) // 2, (224 - rh) // 2
        rgb = image[:, :, ::-1].astype(np.float32) / 127.5 - 1
        resized = self.cv2.resize(rgb, (rw, rh))
        padded = np.zeros((224, 224, 3), dtype=np.float32)
        padded[top:top + rh, left:left + rw] = resized
        return padded.transpose(2, 0, 1)[None], (ratio, left, top)

    def decode(self, outputs, width, height, transform):
        import numpy as np
        # Upstream's 2,254 fixed anchors: two at strides 8/16, six at 32.
        anchors = np.asarray([((x + .5) / size, (y + .5) / size)
                              for size, count in ((28, 2), (14, 2), (7, 6))
                              for y in range(size) for x in range(size) for _ in range(count)])
        raw = next(o for o in outputs if o.shape[-1] == 12)[0]
        logits = next(o for o in outputs if o.shape[-1] == 1)[0, :, 0]
        scores = 1 / (1 + np.exp(-np.clip(logits.astype(float), -100, 100)))
        chosen = np.flatnonzero(scores >= self.threshold)
        if not len(chosen):
            return []
        centers = raw[chosen, :2] + anchors[chosen] * 224
        sizes = raw[chosen, 2:4]
        xywh = np.c_[centers - sizes / 2, sizes]
        # OpenCV NMS consumes x,y,width,height, not x1,y1,x2,y2.
        keep = self.cv2.dnn.NMSBoxes(xywh.tolist(), scores[chosen].tolist(), self.threshold, .3)
        ratio, left, top = transform
        result = []
        for k in np.asarray(keep).reshape(-1):
            x, y, w, h = xywh[k]
            xyxy = (np.array([x, y, x + w, y + h]) - [left, top, left, top]) / ratio
            item = _detection(xyxy, width, height, scores[chosen[k]], "person", self.method)
            if item:
                result.append(item)
        return result


class ObjectDetector(_DNN):
    method = "yolox-s-int8"
    threshold = .35

    def __init__(self, workspace=None):
        super().__init__("objects", workspace)

    def preprocess(self, image):
        import numpy as np
        h, w = image.shape[:2]
        ratio = 640 / max(h, w)
        rw, rh = max(1, int(w * ratio)), max(1, int(h * ratio))
        padded = np.full((640, 640, 3), 114, dtype=np.float32)
        padded[:rh, :rw] = self.cv2.resize(image[:, :, ::-1], (rw, rh))
        # Zoo export takes RGB 0..255, top-left letterbox, without normalization.
        return padded.transpose(2, 0, 1)[None], ratio

    def decode(self, outputs, width, height, transform):
        import numpy as np
        raw = outputs[0][0]
        grid = np.asarray([(x, y) for stride in (8, 16, 32)
                           for y in range(640 // stride) for x in range(640 // stride)])
        strides = np.concatenate([np.full((640 // s) ** 2, s) for s in (8, 16, 32)])[:, None]
        scores = raw[:, 4:5] * raw[:, 5:]
        labels = scores.argmax(axis=1)
        confidence = scores.max(axis=1)
        chosen = np.flatnonzero(confidence >= self.threshold)
        if not len(chosen):
            return []
        centers = (raw[chosen, :2] + grid[chosen]) * strides[chosen]
        sizes = np.exp(np.clip(raw[chosen, 2:4], -20, 20)) * strides[chosen]
        xywh = np.c_[centers - sizes / 2, sizes]
        keep = self.cv2.dnn.NMSBoxesBatched(xywh.tolist(), confidence[chosen].tolist(),
                                           labels[chosen].tolist(), self.threshold, .5)
        result = []
        for k in np.asarray(keep).reshape(-1):
            x, y, w, h = xywh[k]
            item = _detection(np.array([x, y, x + w, y + h]) / transform, width, height,
                              confidence[chosen[k]], COCO_CLASSES[labels[chosen[k]]], self.method)
            if item:
                result.append(item)
        return result


def optional_detectors(workspace=None, names=("person", "objects")):
    detectors, warnings = {}, []
    for name, kind in (("person", PersonDetector), ("objects", ObjectDetector)):
        if name not in names:
            continue
        try:
            detectors[name] = kind(workspace)
        except LayoutError as exc:
            warnings.append(str(exc))
    return detectors, warnings


def photo_detections(image):
    """Pillow input, source-normalized detections and explicit fallback notes."""
    detectors, warnings = optional_detectors(names=("objects",))
    detections = []
    if detectors:
        import numpy as np
        sample = image.convert("RGB")
        sample.thumbnail((1280, 1280))
        bgr = np.asarray(sample)[:, :, ::-1].copy()
        for detector in detectors.values():
            try:
                detections.extend(detector.detect(bgr))
            except LayoutError as exc:
                warnings.append(str(exc))
    if not detections:
        warnings.append("No semantic subject detected; model-free saliency remains the subject fallback.")
    return [d.to_dict() for d in detections], warnings
