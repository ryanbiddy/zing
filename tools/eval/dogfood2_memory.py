"""Sequential peak-RSS regression harness for caption geometry on generated media.

OCR and pixel evidence are deterministic stubs: this isolates the geometry,
tracking and JSON allocation cost, not ASR/OCR model memory or accuracy.
The decoder reads the real generated reference; no frames are retained here.
"""

import argparse
import ctypes
import importlib.util
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace


def peak_bytes():
    if sys.platform == "win32":
        class Counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                        *[(n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize",
                           "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                           "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]]
        value = Counters()
        value.cb = ctypes.sizeof(value)
        kernel = ctypes.WinDLL("kernel32")
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        psapi = ctypes.WinDLL("psapi")
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(value), value.cb):
            raise ctypes.WinError()
        return value.PeakWorkingSetSize
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("media", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    import cv2
    cv2.setNumThreads(1)
    from myzing.study import caption_geometry as cg, caption_models, caption_pixels
    if args.baseline:
        spec = importlib.util.spec_from_file_location("myzing.study._baseline_geometry", args.baseline)
        cg = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cg
        spec.loader.exec_module(cg)
    from myzing.project.probe import probe_file
    duration = probe_file(args.media).duration

    def engine(frame):
        h, w = frame.shape[:2]
        boxes = [[[.1*w, y*h], [.8*w, y*h], [.8*w, (y+.025)*h], [.1*w, (y+.025)*h]]
                 for y in (.08, .15, .22, .29, .36, .43, .50, .57, .64, .71, .78, .85)]
        return SimpleNamespace(boxes=boxes, txts=["MEASURED MEMORY SAMPLE FOR CAPTION GEOMETRY"]*len(boxes), scores=[.99]*len(boxes))

    def pixels(frame, polygon, text):
        box = [polygon[0][0], polygon[0][1], polygon[2][0], polygon[2][1]]
        return {"ink_box": box, "text_height": box[3]-box[1],
                "ink_evidence": {"ink_density": .25, "edge_density": .2, "component_count": 20, "stroke_fraction": .1},
                "fill": {"lab": [95., 0., 0.], "rgb": [240, 240, 240], "confidence": .9}}
    caption_models.engine = lambda: (engine, "deterministic-memory-fixture")
    caption_pixels.measure = pixels
    from myzing.layout import detector
    detector.verified_model = lambda path: False
    args.out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    geometry = cg.read_geometry(args.media, duration)
    output = geometry.write(args.out)
    result = {"version": 1, "scope": __doc__.strip(), "media": str(args.media), "duration": duration,
              "baseline": str(args.baseline) if args.baseline else None,
              "seconds": round(time.monotonic()-started, 3), "peak_rss_bytes": peak_bytes(),
              "json_bytes": output.stat().st_size, "frames": len(geometry.frames), "tracks": len(geometry.tracks),
              "geometry_summary": geometry.summary()}
    (args.out / "measurement.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
