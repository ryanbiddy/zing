"""Optional local face-interior color evidence; no skin-color segmentation."""

import math


def measure_faces(frames, timestamps, *, boxes_at=None):
    """Boxes are normalized edges in each already-cropped sharp RGB frame.

    Keep central 60% of each box to reduce hair/background contamination. Do
    not filter by a 'skin-colored' hue: doing so would hide a green cast.
    Supplied boxes need no layout extra. Otherwise use only verified local
    YuNet weights; an unavailable detector is an explicit measurement limit.
    """
    from myzing.color.science import np, rgb_to_lab
    result = {"version": 1, "status": "unmeasured", "ab_mean": None, "face_ab": [], "samples": [],
              "reason": "No face boxes in the sampled sharp picture; skin protection unmeasured."}
    if boxes_at is None:
        from myzing.layout.detector import LayoutError, YuNetDetector
        try:
            detector = YuNetDetector(download=False)
        except (LayoutError, ImportError) as exc:
            result["reason"] = f"Local face detector unavailable; skin protection unmeasured. {exc}"
            return result
        def boxes_at(timestamp, rgb):
            bgr = np.ascontiguousarray(np.rint(rgb[..., ::-1]*255).astype(np.uint8))
            return [(d.box.x, d.box.y, d.box.right, d.box.bottom) for d in detector.detect(bgr)]
        result["detector"] = "local YuNet; sampled sharp frame, no download"
    else:
        result["detector"] = "supplied face boxes in sampled sharp-frame coordinates"
    for rgb, timestamp in zip(frames, timestamps):
        height, width = rgb.shape[:2]
        try:
            boxes = boxes_at(timestamp, rgb)
        except Exception as exc:
            # Face inference is optional; the scene measurement is still valid.
            result["reason"] = f"Face sampling failed; skin protection unmeasured: {exc}"
            result.update(ab_mean=None, face_ab=[], samples=[])
            return result
        for box in boxes:
            if len(box) != 4 or not all(math.isfinite(v) for v in box):
                continue
            left, top, right, bottom = box
            if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
                continue
            dx, dy = .2*(right-left), .2*(bottom-top)
            x, y = math.ceil((left+dx)*width), math.ceil((top+dy)*height)
            r, b = math.floor((right-dx)*width), math.floor((bottom-dy)*height)
            if (r-x)*(b-y) < 16 or r <= x or b <= y:
                continue
            ab = rgb_to_lab(rgb[y:b, x:r]).reshape(-1, 3)[:, 1:].mean(axis=0).tolist()
            result["face_ab"].append(ab)
            result["samples"].append({"timestamp": timestamp, "box": list(box), "interior": [x, y, r, b], "ab_mean": ab})
    if result["face_ab"]:
        result.update(status="measured", ab_mean=np.mean(result["face_ab"], axis=0).tolist(),
                      reason="Central face-box color, equally weighted per face; sparse detections can miss faces. "
                             "Hair, makeup and lighting remain confounders; this is not skin segmentation.")
    return result
