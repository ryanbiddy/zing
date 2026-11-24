"""Copy or extract one frame and record how the face was placed."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from myzing.factory.tools import ffmpeg, run
from myzing.render.hyperframes_publish import atomic_publish
from myzing.layout.detector import LayoutError, YuNetDetector, model_path, verified_model

from . import CoverError
from .contract import STYLES, finite
from .frame import dimensions


def find_face(path, w, h):
    default = {"cx": .5, "cy": .5, "fh": min(.3, w / h)}
    reason = "the verified YuNet model is unavailable"
    if verified_model(model_path()):
        try:
            detector = YuNetDetector(download=False)
            import numpy as np
            image = detector.cv2.imdecode(np.frombuffer(path.read_bytes(), dtype=np.uint8), detector.cv2.IMREAD_COLOR)
            matches = detector.detect(image)
            if matches:
                box = max((d.box for d in matches), key=lambda b: b.width * b.height)
                cx, cy = box.center
                fh = min(box.height, 2 * min(cx, 1 - cx) * w / h)
                return {"cx": cx, "cy": cy, "fh": fh}, f"YuNet found {len(matches)} face(s). Selected the largest."
            reason = "YuNet found no face"
        except (LayoutError, ImportError, OSError) as exc:
            reason = str(exc)
    return default, f"Used a centred default face box because {reason}. Adjust frame.face in cover.json."


def new(directory: Path, *, frame=None, video=None, at=None, style=None) -> dict:
    if (frame is None) == (video is None) or (video is None) != (at is None):
        raise CoverError("Supply either --frame IMAGE or both --video FILE and --at SECONDS.")
    if at is not None and not (finite(at) and at >= 0):
        raise CoverError("Set --at to a finite, nonnegative time in seconds.")
    if style is not None and style not in STYLES:
        raise CoverError("Choose a style from 'zing cover styles'.")
    source = Path(frame if frame is not None else video).expanduser().resolve()
    if not source.is_file():
        raise CoverError(f"Supply an existing local file. Cannot find {source}.")
    directory = directory.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    spec_path = directory / "cover.json"
    if spec_path.exists():
        raise CoverError(f"{spec_path} exists. Choose a new cover directory.")
    with tempfile.TemporaryDirectory(dir=directory, prefix=".cover-new-") as temp:
        if video is None:
            ext = source.suffix.lower()
            if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
                raise CoverError("Use a PNG, JPEG or WebP still, or extract a frame with --video and --at.")
            image = Path(temp) / ("frame" + ext)
            shutil.copyfile(source, image)
        else:
            image = Path(temp) / "frame.png"
            try:
                run(ffmpeg(), "-v", "error", "-nostdin", "-protocol_whitelist", "file,pipe",
                    "-ss", at, "-i", source, "-map", "0:v:0", "-frames:v", 1, image,
                    capture_output=True, timeout=120)
            except subprocess.CalledProcessError as exc:
                raise CoverError("Cannot extract frame. Check the video and timestamp. " +
                                 exc.stderr.decode("utf-8", errors="replace")[-400:]) from exc
            if not image.is_file():
                raise CoverError("No frame at that time. Choose --at inside the video's duration.")
        w, h = dimensions(image)
        face, note = find_face(image, w, h)
        name = "[REPLACE source]"
        blocks = {"clipping": {"masthead": name, "kicker": "[REPLACE kicker]", "dateline": "[REPLACE dateline]",
                               "body": "[REPLACE transcript passage]"},
                  "plate": {"top": "[REPLACE top]", "bottom": "[REPLACE bottom]"},
                  "number": {"figure": "[REPLACE 4]", "label": "[REPLACE label]"},
                  "quote": {"text": "[REPLACE quote]", "highlight": "[REPLACE quote]", "by": ["[REPLACE speaker]"]}}
        spec = {"version": 1, "seed": 11, "frame": {"src": image.name, "w": w, "h": h, "face": face},
                "source": {"name": name, "rights": "[REPLACE rights]"},
                **({style: blocks[style]} if style else blocks)}
        if at is not None:
            spec["source"]["timestamp"] = at
        target = directory / image.name
        draft = Path(temp) / "cover.json"
        draft.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        try:
            atomic_publish(image, target)
        except FileExistsError as exc:
            raise CoverError(f"{target} exists. Choose a new cover directory.") from exc
        try:
            atomic_publish(draft, spec_path)
        except OSError:
            target.unlink()
            raise
    return {"cover": str(spec_path), "frame": str(target), "face": face, "note": note}
