"""Offline CG2 caption-only replay; frozen clip split and hash-bound V1 labels.

Example: python -m tools.eval.real.cg2_eval --root <V1 real-eval directory>
  --split calibration --output zing-workspace/cg2/calibration
No downloads. Labels never enter OCR, segmentation, rejection or font ranking.
"""

import argparse
import copy
import hashlib
import json
from pathlib import Path
from statistics import median

from myzing.study import caption_geometry as cg
from .scoring import assign, iou, pr

HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def score_frames(geometry, frames, clip):
    rows = []
    for label in frames:
        sample = min(geometry.frames, key=lambda f: abs(f.t - label["t"]), default=None)
        if sample is None or abs(sample.t - label["t"]) > .01:
            rows.append({"clip": clip, "t": label["t"], "unavailable": True,
                         "tp": 0, "fp": 0, "fn": len(label["lines"]), "matches": []})
            continue
        predictions = [(i, d) for i, d in enumerate(sample.detections) if cg._confident(d)]
        truths = label["lines"]
        # Use the same final-box criterion for both versions. Raw OCR proposals
        # remain available in each sidecar for auditing why an overlap changed.
        def box(d):
            return d.appearance.get("ink_box") or d.box
        matches = assign(truths, predictions, lambda t, p: iou(t["box"], box(p[1]))
                         if iou(t["box"], box(p[1])) >= .5 else -1)
        details = []
        for ti, pi in matches:
            truth, (_, detection) = truths[ti], predictions[pi]
            ink = box(detection)
            color_error = None
            if truth.get("fill_lab") and detection.appearance.get("fill"):
                color_error = sum((a-b)**2 for a, b in zip(truth["fill_lab"], detection.appearance["fill"]["lab"]))**.5
            details.append({"truth": truth["text"], "predicted": detection.text,
                "ink_iou": iou(truth["box"], ink),
                "height_relative_error": abs((ink[3]-ink[1])/(truth["box"][3]-truth["box"][1])-1),
                "fill_delta_e76": color_error, "fill": detection.appearance.get("fill")})
        unmatched = {predictions[i][0] for i in range(len(predictions)) if i not in {p for _, p in matches}}
        false_tracks = [t.id for t in geometry.tracks if t.kind == "caption" and any(
            abs(s["t"] - sample.t) < 1e-8 and unmatched.intersection(s["detection_indices"]) for s in t.samples)]
        rows.append({"clip": clip, "t": sample.t, **pr(len(matches), len(predictions)-len(matches), len(truths)-len(matches)),
            "matches": details, "false_caption_tracks": false_tracks,
            "missed": [t["text"] for i, t in enumerate(truths) if i not in {t for t, _ in matches}],
            "rejections": [{"text": d.text, **d.validation} for d in sample.detections
                           if d.validation and not d.validation["accepted"]]})
    return rows


def summarize(rows):
    details = [d for r in rows for d in r["matches"]]
    colors = [d["fill_delta_e76"] for d in details if d["fill_delta_e76"] is not None]
    return {**pr(sum(r["tp"] for r in rows), sum(r["fp"] for r in rows), sum(r["fn"] for r in rows)),
        "frames_scored": sum(not r.get("unavailable") for r in rows),
        "false_caption_tracks_at_labeled_frames": len({(r["clip"], t) for r in rows for t in r.get("false_caption_tracks", [])}),
        "median_height_relative_error": median(d["height_relative_error"] for d in details) if details else None,
        "median_ink_iou": median(d["ink_iou"] for d in details) if details else None,
        "median_fill_delta_e76": median(colors) if colors else None,
        "fill_labeled_matches": len(colors), "per_frame": rows}


def evidence(media, geometry, labels, output, clip, tag, workspace):
    import cv2
    from myzing.study.font_match import match_geometry
    cap = cv2.VideoCapture(str(media))
    results = []
    try:
        for label in labels:
            sample = min(geometry.frames, key=lambda f: abs(f.t - label["t"]), default=None)
            if sample is None or abs(sample.t - label["t"]) > .01:
                continue
            cap.set(cv2.CAP_PROP_POS_FRAMES, sample.frame_index)
            ok, image = cap.read()
            if not ok:
                raise RuntimeError(f"Could not decode {clip} frame {sample.frame_index}")
            for d in sample.detections:
                box = d.appearance.get("ink_box") or d.box
                color = (255, 0, 255) if cg._confident(d) else (0, 190, 255)
                cv2.rectangle(image, (round(box[0]*sample.width), round(box[1]*sample.height)),
                              (round(box[2]*sample.width), round(box[3]*sample.height)), color, 1)
            for line in label["lines"]:
                b = line["box"]
                cv2.rectangle(image, (round(b[0]*sample.width), round(b[1]*sample.height)),
                              (round(b[2]*sample.width), round(b[3]*sample.height)), (0, 255, 0), 1)
            png = output / f"{clip}-{label['t']:g}-{tag}.png"
            if not cv2.imwrite(str(png), image):
                raise RuntimeError(f"Could not write {png}")
            single = cg.CaptionGeometry(geometry.duration, [copy.deepcopy(sample)], provenance=geometry.provenance)
            single.tracks = cg.track_frames(single.frames, geometry.duration)
            fonts = match_geometry(media, single, workspace)
            write(output / f"{clip}-{label['t']:g}-{tag}-fonts.json", fonts.to_dict())
            results.append({"t": sample.t, "png": str(png), "tracks": [{
                "text": t["text"], "status": t["status"], "top_three": [
                    {k: c[k] for k in ("font_id", "weight", "score")} for c in t["candidates"][:3]],
                "gaps": t["gaps"]} for t in fonts.tracks]})
    finally:
        cap.release()
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("calibration", "held_out"), required=True)
    parser.add_argument("--workspace", type=Path)
    args = parser.parse_args(argv)
    split = read(HERE / "cg2-split.json")
    labels = read(HERE / "labels.json")
    manifest = read(HERE / "manifest.json")
    baseline_path = args.root / "run-01/observations.json"
    baseline = read(baseline_path)
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"version": 1, "split": args.split, "split_sha256": digest(HERE / "cg2-split.json"),
              "labels_sha256": digest(HERE / "labels.json"), "baseline_sha256": digest(baseline_path),
              "scoring": "Final ink box IoU >= .5, one-to-one; missing observations count as misses. False tracks only at reviewed frames; no whole-clip false-track claim.",
              "fill_note": "V1 has no numeric fill labels. Colors are diagnostic estimates; error remains null.",
              "clips": {}}
    from importlib.metadata import version
    report["runtime"] = {p: version(p) for p in ("rapidocr", "onnxruntime", "opencv-python-headless", "numpy", "Pillow")}
    freeze_path = HERE / "cg2-freeze.json"
    if args.split == "held_out":
        freeze = read(freeze_path)
        for relative, expected in freeze["files"].items():
            if digest(HERE.parents[2] / relative) != expected:
                raise ValueError(f"Frozen CG2 file changed before held-out replay: {relative}")
        report["freeze_sha256"] = digest(freeze_path)
    rows = {"before": [], "after": []}
    diagnostics = {"before": [], "after": []}
    for item in manifest["clips"]:
        clip = item["id"]
        if clip not in split[args.split]:
            continue
        truth = labels["clips"][clip]
        if not truth.get("caption_frames") and not truth.get("diagnostic_frames"):
            continue
        media = args.root / item["file"]
        actual_hash = digest(media)
        if actual_hash != item["sha256"] or actual_hash != truth["media_sha256"] or actual_hash != baseline["clips"][clip]["media_sha256"]:
            raise ValueError(f"Media/label/baseline SHA-256 mismatch: {clip}")
        before = cg.CaptionGeometry.from_dict(baseline["clips"][clip]["geometry"])
        after = cg.read_geometry(media, item["duration"])
        if not after.frames or any(f.status == "ocr_error" for f in after.frames):
            raise RuntimeError(f"Incomplete CG2 inference: {clip}: {after.warnings}")
        folder = args.output / clip
        folder.mkdir(exist_ok=True)
        after.write(folder)
        diag = [{"t": d["t"], "lines": []} for d in truth.get("diagnostic_frames", []) if d.get("visible_text") == []]
        report["clips"][clip] = {"media_sha256": actual_hash}
        for tag, geometry in (("before", before), ("after", after)):
            rows[tag].extend(score_frames(geometry, truth["caption_frames"], clip))
            diagnostics[tag].extend(score_frames(geometry, diag, clip))
            report["clips"][clip][tag] = evidence(media, geometry, truth["caption_frames"] + diag, args.output, clip, tag, args.workspace)
        write(args.output / "results.json", report)
        print(f"{args.split}: {clip} complete", flush=True)
    report["metrics"] = {tag: summarize(values) for tag, values in rows.items()}
    report["post_hoc_diagnostics"] = {tag: summarize(values) for tag, values in diagnostics.items()}
    write(args.output / "results.json", report)
    print(json.dumps(report["metrics"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
