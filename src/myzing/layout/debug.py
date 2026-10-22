"""Contact sheet of measured faces, padded tracks, UI masks and chosen boxes."""

from __future__ import annotations

import math
from pathlib import Path

from .detector import LayoutError, load_cv2
from .types import FrameDetections, LayoutPlan, box_at


def read_image(path: Path):
    import numpy as np

    cv2 = load_cv2()
    frame = cv2.imdecode(np.frombuffer(path.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise LayoutError(f"Cannot decode sampled frame: {path}")
    return frame


def write_contact_sheet(samples: list[tuple[float, Path]], detections: list[FrameDetections],
                        plan: LayoutPlan, output: Path, *, limit: int = 24) -> Path:
    import numpy as np

    cv2 = load_cv2()
    if not samples or not 1 <= limit <= 24:
        raise ValueError("contact sheet needs samples and a limit between 1 and 24")
    count = min(limit, len(samples))
    indices = sorted({round(i * (len(samples) - 1) / max(1, count - 1)) for i in range(count)})
    tiles = []
    for index in indices:
        time, path = samples[index]
        source = read_image(path)
        height, width = source.shape[:2]
        ratio = min(280 / width, 400 / height)
        frame = cv2.resize(source, (round(width * ratio), round(height * ratio)))
        h, w = frame.shape[:2]

        def rectangle(box, color, label, *, fill=False):
            p0 = (round(box.x * w), round(box.y * h))
            p1 = (min(w - 1, round(box.right * w)), min(h - 1, round(box.bottom * h)))
            if fill:
                overlay = frame.copy()
                cv2.rectangle(overlay, p0, p1, color, -1)
                cv2.addWeighted(overlay, 0.22, frame, 0.78, 0, frame)
            cv2.rectangle(frame, p0, p1, color, 2)
            cv2.putText(frame, label, (p0[0] + 2, min(h - 4, p0[1] + 13)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.32, color, 1, cv2.LINE_AA)

        for mask in plan.masks:
            rectangle(mask.box, (255, 160, 60), mask.name, fill=True)
        for detection in detections[index].detections:
            rectangle(detection.box, (40, 50, 255), f"face {detection.confidence:.2f}")
        for track in plan.tracks:
            if track.keyframes[0].time <= time <= track.keyframes[-1].time:
                rectangle(box_at(track.keyframes, time), (0, 190, 255), f"{track.id} padded")
        active = [e for e in plan.events if e.start <= time < e.end]
        for event in active:
            rectangle(box_at(event.as_path(), time), (70, 230, 70) if event.overlap.safe else (220, 30, 220),
                      f"{event.id[:18]} {'clear' if event.overlap.safe else 'UNSAFE'}")
        tile = np.full((450, 300, 3), 25, dtype=np.uint8)
        tile[24:24 + h, (300 - w) // 2:(300 - w) // 2 + w] = frame
        cv2.putText(tile, f"{time:.3f}s", (10, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (235, 235, 235), 1)
        label = active[0].reason if active else "no caption"
        cv2.putText(tile, label, (10, 440), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (235, 235, 235), 1)
        tiles.append(tile)
    columns = min(4, len(tiles))
    sheet = np.full((40 + 450 * math.ceil(len(tiles) / columns), columns * 300, 3), 25, dtype=np.uint8)
    cv2.putText(sheet, "face:red padded:amber UI:blue caption:green unsafe:magenta", (8, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, (235, 235, 235), 1)
    for index, tile in enumerate(tiles):
        y, x = 40 + (index // columns) * 450, (index % columns) * 300
        sheet[y:y + 450, x:x + 300] = tile
    ok, encoded = cv2.imencode(".png", sheet)
    if not ok:
        raise LayoutError("OpenCV could not encode the debug contact sheet")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(encoded.tobytes())
    return output
