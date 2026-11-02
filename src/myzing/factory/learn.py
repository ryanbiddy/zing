"""Learn a style pack from a clip you like, then prove the copy looks and moves like it.

measure -> pack -> render a sample clip in the pack -> measure the render the same way -> compare -> correct, a few
rounds. Captions are measured with Zing's offline caption geometry (OCR boxes, fill/outline/plate colors, text height,
font candidates); the pop is measured from full-frame-rate frames around caption onsets; layout from face positions;
pacing from scene cuts. Every number in the report is a measurement of pixels, not a claim about the original
project, its font or its settings.
"""
from __future__ import annotations

import json
import math
import re
import statistics
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .tools import FactoryError, ffmpeg, ffprobe

FONTS = {"anton": ("Anton", 400), "ibmplexsans": ("IBM Plex Sans", None)}
TOLERANCE = {"cap_y": 0.03, "text_height": 0.12, "words": 0.6, "fill": 15.0, "highlight": 20.0, "plate": 20.0,
             "pop_ms": 80.0}


# ---------------------------------------------------------------- color helpers
def hex_of(rgb) -> str:
    return "#" + "".join(f"{int(round(max(0, min(255, c)))):02X}" for c in rgb[:3])


def _lab(rgb):
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(float(c)) for c in rgb[:3])
    x, y, z = (r * .4124 + g * .3576 + b * .1805) / .95047, r * .2126 + g * .7152 + b * .0722, \
        (r * .0193 + g * .1192 + b * .9505) / 1.08883
    f = lambda t: t ** (1 / 3) if t > .008856 else 7.787 * t + 16 / 116
    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def delta_e(a, b) -> float:
    return math.dist(_lab(a), _lab(b))


def _median_rgb(colors):
    return [statistics.median(c[i] for c in colors) for i in range(3)] if colors else None


# ---------------------------------------------------------------- measuring
def _duration(video: Path) -> float:
    out = subprocess.run([ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "json", str(video)],
                         capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60).stdout
    return float(json.loads(out or "{}").get("format", {}).get("duration") or 0)


def geometry(video: Path) -> dict:
    from myzing.study.caption_geometry import read_geometry
    geo = read_geometry(Path(video), _duration(video))
    try:
        from myzing.study.font_match import budget_geometry, match_geometry
        budgeted, _ = budget_geometry(geo)
        geo.font_candidates = match_geometry(Path(video), budgeted).to_dict()
    except Exception as exc:                       # fonts are optional evidence; never fail the measurement
        geo.warnings.append(f"font candidates unavailable: {exc}")
    return geo.to_dict()


def caption_band(tracks: list[dict]) -> list[dict]:
    """Caption tracks in the band where most captions sit (a title or source tag elsewhere is not a caption)."""
    tracks = [t for t in tracks if t.get("kind") == "caption" and t.get("samples") and re.search(r"[A-Za-z0-9]", t.get("text", ""))]
    if not tracks:
        return []
    centers = {t["id"]: statistics.median((s["box"][1] + s["box"][3]) / 2 for s in t["samples"]) for t in tracks}
    bins: dict[int, list[dict]] = {}
    for t in tracks:
        bins.setdefault(round(centers[t["id"]] * 10), []).append(t)
    best = max(bins, key=lambda k: len(bins[k]))
    return [t for t in tracks if abs(round(centers[t["id"]] * 10) - best) <= 1]


def _detections(geo: dict, tracks: list[dict]) -> list[tuple[float, dict]]:
    frames = {round(f["t"], 3): f for f in geo.get("frames", [])}
    out = []
    for t in tracks:
        for s in t["samples"]:
            frame = frames.get(round(s["t"], 3))
            for i in s.get("detection_indices") or []:
                if frame and i < len(frame.get("detections", [])):
                    out.append((s["t"], frame["detections"][i]))
    return out


def _frame_at(cap, t: float):
    import cv2
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, img = cap.read()
    return img if ok else None


def _lab_array(bgr):
    import cv2
    import numpy as np
    lab = cv2.cvtColor(np.ascontiguousarray(bgr, dtype=np.uint8).reshape(-1, 1, 3), cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(float)
    return np.stack([lab[:, 0] * 100 / 255, lab[:, 1] - 128, lab[:, 2] - 128], -1)


def highlight(video: Path, dets: list[tuple[float, dict]], fill, plate, surroundings: bool = True) -> dict:
    """A second, colored ink inside caption boxes, if it shows up often enough and is not the video behind the text.

    Pixels count as colored ink only when they are far from the caption's fill, saturated, and unlike the video just
    above and below the caption (b-roll behind unboxed captions is not a word color), and the colors agree across
    samples. Most captions carrying it = the active word lights up; some = chosen words are emphasized. Text on a
    known solid plate (surroundings=False) is compared with the plate alone, so stacked lines don't hide each other's color.
    """
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(str(video))
    seen, found = 0, []
    fill_lab = np.array(_lab(fill))
    step = max(1, len(dets) // 24)
    for t, det in dets[::step][:24]:
        img = _frame_at(cap, t)
        if img is None:
            continue
        H, W = img.shape[:2]
        x0, y0, x1, y1 = det["box"]          # the whole line: the fill-only ink box stops at a differently colored word
        top, bottom, left, right = max(0, int(y0 * H) - 2), int(y1 * H) + 2, max(0, int(x0 * W) - 2), int(x1 * W) + 2
        crop = img[top:bottom, left:right]
        if crop.size < 60:
            continue
        seen += 1
        h = bottom - top
        around = np.concatenate([img[max(0, top - h):top, left:right].reshape(-1, 3),
                                 img[bottom:bottom + h, left:right].reshape(-1, 3)]) if surroundings else np.zeros((0, 3))
        if plate:
            around = np.concatenate([around, np.array([plate[::-1]] * 50)])
        bg = _lab_array(around[:: max(1, len(around) // 400)]) if len(around) else _lab_array(np.array([[0, 0, 0]]))
        px_bgr = crop.reshape(-1, 3)[::2]
        px = _lab_array(px_bgr)
        near_bg = np.min(np.linalg.norm(px[:, None, :] - bg[None, :, :], axis=-1), axis=1) < 25
        ink = ~near_bg
        chroma = np.hypot(px[:, 1], px[:, 2])
        colored = ink & (np.linalg.norm(px - fill_lab, axis=-1) > 30) & (chroma > 25)
        if ink.sum() >= 20 and colored.sum() >= 12 and colored.sum() / ink.sum() >= .10:
            core = colored & (chroma >= np.percentile(chroma[colored], 70))     # letter cores, not edges
            found.append(np.median(px_bgr[core][:, ::-1].astype(float), axis=0).tolist())
    cap.release()
    color = _median_rgb(found) if found else None
    agree = color and sum(delta_e(c, color) < 25 for c in found) >= .6 * len(found)
    share = len(found) / seen if seen >= 3 and agree else 0
    mode = "active" if share >= .35 else "emphasis" if share >= .10 else None
    return {"present": mode is not None, "mode": mode, "rgb": color if mode else None,
            "samples": seen, "with_color": len(found)}


def pop(video: Path, tracks: list[dict], fill) -> dict:
    """How captions come in: frames from each onset until the text's ink settles (full frame rate)."""
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    target = np.array(_lab(fill))
    results = []
    starts = sorted({round(t["samples"][0]["t"], 2): t for t in tracks}.items())[1:]
    for t0, track in starts[:: max(1, len(starts) // 12)][:12]:
        box = track["samples"][0]["box"]
        frames, t = [], max(0.0, t0 - 0.35)
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        for _ in range(int(0.8 * fps)):
            ok, img = cap.read()
            if not ok:
                break
            H, W = img.shape[:2]
            pad_x, pad_y = (box[2] - box[0]) * .25, (box[3] - box[1]) * .6
            crop = img[max(0, int((box[1] - pad_y) * H)):int((box[3] + pad_y) * H),
                       max(0, int((box[0] - pad_x) * W)):int((box[2] + pad_x) * W)]
            lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB).astype(float)
            lab = np.stack([lab[..., 0] * 100 / 255, lab[..., 1] - 128, lab[..., 2] - 128], -1)
            frames.append(np.linalg.norm(lab - target, axis=-1) < 18)
        if len(frames) < 8:
            continue
        change = [float((a ^ b).mean()) for a, b in zip(frames, frames[1:])]
        onset = int(np.argmax(change[: int(0.6 * fps)])) + 1          # the biggest switch near the measured start
        peak = change[onset - 1]
        # the caption's settled look is the frame before the next switch (pops finish well inside 0.2 s)
        nxt = next((k for k in range(onset + int(0.2 * fps), len(change)) if change[k] > .5 * peak), len(frames) - 1)
        final = frames[nxt]
        if final.sum() < 30:
            continue
        iou = [float((m & final).sum() / max(1, (m | final).sum())) for m in frames]
        settle = next((k for k in range(onset, nxt + 1) if iou[k] > 0.85), None)
        if settle is None:
            continue
        rows = [np.where(m.any(axis=1))[0] for m in (frames[onset], final)]
        heights = [r.max() - r.min() + 1 if len(r) else 0 for r in rows]
        results.append({"ms": (settle - onset) * 1000 / fps, "from": heights[0] / heights[1] if heights[1] else 1.0,
                        "overshoot": any(i < .85 for i in iou[settle:settle + 3]) or
                        any(f.sum() > final.sum() * 1.12 for f in frames[onset:settle + 1])})
    cap.release()
    if len(results) < 3:
        return {"measured": False, "onsets": len(results)}
    ms = statistics.median(r["ms"] for r in results)
    return {"measured": True, "onsets": len(results), "ms": round(ms), "from": round(statistics.median(
        min(1.0, max(.5, r["from"])) for r in results), 2), "overshoot": sum(r["overshoot"] for r in results) > len(results) / 2}


def frame_size(video: Path) -> tuple[int, int]:
    out = subprocess.run([ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "json", str(video)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=60).stdout
    st = (json.loads(out or "{}").get("streams") or [{}])[0]
    return int(st.get("width") or 0), int(st.get("height") or 0)


def nearest_shape(width: int, height: int) -> str:
    from .render import SHAPES
    ratio = width / height if height else 9 / 16
    return min(SHAPES, key=lambda k: abs(math.log(SHAPES[k][0] / SHAPES[k][1]) - math.log(ratio)))


def panel(video: Path) -> dict:
    """A solid strip at the bottom that never changes while the video above it moves (a headline panel)."""
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(str(video))
    duration = _duration(video)
    frames = []
    for k in range(16):
        img = _frame_at(cap, duration * (k + .5) / 16)
        if img is not None:
            frames.append(cv2.resize(img, (90, int(90 * img.shape[0] / img.shape[1]))))
    cap.release()
    if len(frames) < 8:
        return {"present": False}
    stack = np.stack(frames).astype(float)
    row_motion = stack.std(axis=0).mean(axis=(1, 2))           # per row, over time
    H = stack.shape[1]
    run = 0
    while run < H and row_motion[H - 1 - run] < 3:
        run += 1
    size = run / H
    if not .12 <= size <= .5 or row_motion[: H - run].mean() < 6:     # the video above must actually move
        return {"present": False}
    region = stack[0, H - run:].reshape(-1, 3)
    quant = (region // 16).astype(int)
    keys, counts = np.unique(quant, axis=0, return_counts=True)
    mode = keys[counts.argmax()]
    solid = (np.abs(quant - mode).max(axis=1) <= 1).mean()
    if solid < .55:
        return {"present": False}
    bg = np.median(region[np.abs(quant - mode).max(axis=1) <= 1], axis=0)[::-1]
    return {"present": True, "side": "bottom", "size": round(size, 3), "bg": [round(float(c)) for c in bg]}


def cuts_per_minute(video: Path) -> float:
    log = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(video), "-vf", "select='gt(scene,0.3)',showinfo", "-f", "null", "-"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    duration = _duration(video)
    return round(len(re.findall(r"pts_time:", log)) * 60 / duration, 1) if duration else 0.0


def measure(video: Path, say=print) -> dict:
    video = Path(video)
    say(f"measuring {video.name}")
    geo = geometry(video)
    band = caption_band(geo.get("tracks", []))
    m: dict = {"video": video.name, "captions": len(band), "warnings": list(geo.get("warnings", []))[:5]}
    m["shape"] = nearest_shape(*frame_size(video))
    m["panel"] = panel(video)
    if band:
        samples = [s for t in band for s in t["samples"]]
        m["cap_y"] = round(statistics.median((s["box"][1] + s["box"][3]) / 2 for s in samples), 3)
        m["text_height"] = round(statistics.median(t["median_text_height"] for t in band), 4)
        m["words"] = round(statistics.median(len(t["text"].split()) for t in band), 2)
        letters = [t["text"] for t in band if re.search(r"[A-Za-z]", t["text"])]
        m["upper"] = round(sum(x.upper() == x for x in letters) / max(1, len(letters)), 2)
        dets = _detections(geo, band)
        appear = [d.get("appearance") or {} for _, d in dets]
        fills = [a["fill"]["rgb"] for a in appear if (a.get("fill") or {}).get("rgb")]
        m["fill"] = _median_rgb(fills)
        plates = [a for a in appear if a.get("plate_present") is not None]
        m["plate"] = {"present": bool(plates) and sum(bool(a["plate_present"]) for a in plates) / len(plates) > .5}
        if m["plate"]["present"]:
            m["plate"]["rgb"] = _median_rgb([a["plate_color"]["rgb"] for a in plates
                                             if a.get("plate_present") and (a.get("plate_color") or {}).get("rgb")])
        outlines = [a for a in appear if a.get("outline")]
        m["outline"] = {"present": len(outlines) > .4 * max(1, len(appear))}
        if m["outline"]["present"]:
            m["outline"]["rgb"] = _median_rgb([a["outline"]["rgb"] for a in outlines if a["outline"].get("rgb")])
            widths = [a["stroke_width_fraction"] for a in outlines if a.get("stroke_width_fraction")]
            m["outline"]["width"] = round(statistics.median(widths), 4) if widths else None
        if m["fill"]:
            m["highlight"] = highlight(video, dets, m["fill"], m["plate"].get("rgb"))
            m["pop"] = pop(video, band, m["fill"])
        fonts = [t["candidates"][0] for t in (geo.get("font_candidates") or {}).get("tracks", []) if t.get("candidates")]
        if fonts:
            best = statistics.mode(f["font_id"] for f in fonts)
            pick = [f for f in fonts if f["font_id"] == best]
            m["font"] = {"id": best, "family": pick[0]["family"], "weight": statistics.median(f.get("weight") or 400 for f in pick),
                         "similarity": round(statistics.median(f["score"] for f in pick), 2)}
        # a big title that stays up (a hook header), apart from the captions
        ids, duration = {t["id"] for t in band}, geo.get("duration") or 0

        def span(t):
            ts = [x["t"] for x in t["samples"]]
            return (max(ts) - min(ts)) / duration if duration and ts else 0
        steady = [t for t in geo.get("tracks", []) if t["id"] not in ids and t.get("samples") and span(t) > .4
                  and statistics.median((x["box"][1] + x["box"][3]) / 2 for x in t["samples"]) < .35]
        # a headline is caption-sized and says something; a short or small mark is the show's name or logo
        pn = m["panel"]
        if pn.get("present"):
            # the standing headline: caption-sized lines that stay up inside the panel
            top = 1 - pn["size"]
            lines = [t for t in geo.get("tracks", []) if t["id"] not in ids and t.get("samples") and span(t) > .4
                     and statistics.median((x["box"][1] + x["box"][3]) / 2 for x in t["samples"]) > top
                     and (t.get("median_text_height") or 0) >= .9 * m["text_height"]]
            lines.sort(key=lambda t: t["samples"][0]["box"][1])
            pn["brand"] = any(t["id"] not in ids and t not in lines and t.get("samples") and span(t) > .4
                              and statistics.median((x["box"][1] + x["box"][3]) / 2 for x in t["samples"]) > top
                              for t in geo.get("tracks", []))
            colors = []
            for t in lines:
                fills = [(d.get("appearance") or {}).get("fill", {}).get("rgb") for _, d in _detections(geo, [t])]
                fills = [f for f in fills if f]
                if fills:
                    colors.append(_median_rgb(fills))
            if lines:
                text = " ".join(t["text"] for t in lines)
                pn["headline_lines"], pn["upper"] = len(lines), text.upper() == text
                if colors:
                    ink = max(colors, key=lambda c: sum(delta_e(c, o) < 20 for o in colors))
                    other = [c for c in colors if delta_e(c, ink) >= 25]          # a whole line in the accent
                    inside = highlight(video, _detections(geo, lines), ink, pn["bg"], surroundings=False)  # or accent words in a line
                    pn["ink"] = ink
                    pn["on"] = other[0] if other else inside["rgb"] if inside.get("present") else None
                ids = ids | {t["id"] for t in lines}
            steady = [t for t in steady if statistics.median((x["box"][1] + x["box"][3]) / 2 for x in t["samples"]) <= top]
        m["header"] = any(len(t["text"].split()) >= 3 and (t.get("median_text_height") or 0) >= .9 * m["text_height"]
                          for t in steady)
        steady.sort(key=lambda t: (round(t["samples"][0]["box"][1], 2), t["samples"][0]["box"][0]))
        m["brand"] = [t["text"] for t in steady if not (len(t["text"].split()) >= 3
                                                       and (t.get("median_text_height") or 0) >= .9 * m["text_height"])][:3]
    faces = [((b[1] + b[3]) / 2) for f in geo.get("frames", []) for b in (f.get("face_boxes") or [])[:1]]
    if faces:
        m["face_y"] = round(statistics.median(faces), 3)
        m["layout"] = "speaker-top" if m["face_y"] < .4 else "speaker-bottom" if m["face_y"] > .62 else "speaker-full"
    m["cuts_per_minute"] = cuts_per_minute(video)
    return m


# ---------------------------------------------------------------- pack
def _ink_on(rgb) -> str:
    r, g, b = rgb[:3]
    return "#111111" if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else "#FFFFFF"


def to_pack(m: dict, name: str, base: dict, height: int = 1920) -> dict:
    if not m.get("captions"):
        raise FactoryError("no captions were found in the reference; learn-style needs burned-in captions to copy")
    pack = {**base, "name": name, "learned": True}
    font = m.get("font")
    if font and font["id"] in FONTS:
        family, fixed = FONTS[font["id"]]
        pack["cap_font"], pack["cap_weight"] = family, fixed or int(font["weight"] or 700)
    pack["cap_size"] = round(m["text_height"] * height / 0.72)            # ink height -> font size, corrected by rounds
    pack["cap_y"] = m["cap_y"]
    pack["cap_words"] = max(1, min(5, round(m["words"])))
    pack["cap_chars"] = 12 if pack["cap_words"] <= 2 else 18
    pack["cap_upper"] = m["upper"] > .6
    pack["cap_ink"] = hex_of(m["fill"])
    hl = m.get("highlight") or {}
    pack["cap_on"] = hex_of(hl["rgb"]) if hl.get("mode") == "active" else pack["cap_ink"]
    if hl.get("mode") == "emphasis":
        pack["cap_emphasis"] = hex_of(hl["rgb"])           # numbers and the hook's starred words
    if m["plate"]["present"] and m["plate"].get("rgb"):
        pack["cap_bg"] = hex_of(m["plate"]["rgb"])
    else:
        pack["cap_bg"] = "none"
        pack["cap_shadow"] = "0 3px 14px rgba(0,0,0,.55)"            # unplated text needs separation from video
    if m["outline"]["present"] and m["outline"].get("rgb"):
        pack["cap_stroke"] = hex_of(m["outline"]["rgb"])
        pack["cap_stroke_w"] = max(2, round((m["outline"].get("width") or .004) * height))
    else:
        pack.pop("cap_stroke", None)
    p = m.get("pop") or {}
    if p.get("measured"):
        pack["cap_pop_ms"] = max(0, p["ms"])
        pack["cap_pop_from"] = p["from"] if p["ms"] > 40 else 1.0
        pack["cap_pop_overshoot"] = bool(p["overshoot"])
    if hl.get("rgb"):                                                  # graphics share the caption's signal color
        pack["accent"], pack["accent_ink"] = hex_of(hl["rgb"]), _ink_on(hl["rgb"])
    pn = m.get("panel") or {}
    if pn.get("present"):
        # the hook becomes the standing headline; our own source credit takes the brand row (theirs is never copied)
        pack["panel"] = {"side": "bottom", "size": pn["size"], "bg": hex_of(pn["bg"]), "brand": bool(pn.get("brand")),
                         "upper": pn.get("upper", True), "font": "Anton" if pn.get("upper", True) else pack.get("cap_font", "Inter"),
                         **({"ink": hex_of(pn["ink"])} if pn.get("ink") else {}), **({"on": hex_of(pn["on"])} if pn.get("on") else {})}
    if m.get("shape"):
        pack["shape"] = m["shape"]
    layout = m.get("layout")
    pack["hook_header"] = bool(m.get("header"))
    pack["solo_fill"] = layout in ("speaker-top", "speaker-full")
    if layout == "speaker-top":                     # speaker above, visuals below, captions on the seam
        pack["split"] = "speaker-top"
        if .35 <= m["cap_y"] <= .7:
            pack["seam"] = m["cap_y"]
        pack["pace"] = {"cuts_per_minute": m.get("cuts_per_minute"), "layout": m.get("layout")}
    return pack


def compare(ref: dict, ours: dict) -> list[dict]:
    rows = []

    def row(name, a, b, ok, note=""):
        rows.append({"name": name, "reference": a, "ours": b, "match": bool(ok), "note": note})
    if not ours.get("captions"):
        return [{"name": "captions", "reference": ref.get("captions"), "ours": 0, "match": False,
                 "note": "no captions measured in our render"}]
    if ref.get("shape"):
        row("frame shape", ref["shape"], ours.get("shape"), ref["shape"] == ours.get("shape"))
    rp_, op_ = ref.get("panel") or {}, ours.get("panel") or {}
    if rp_.get("present") or op_.get("present"):
        same = bool(rp_.get("present")) == bool(op_.get("present"))
        close = same and (not rp_.get("present") or abs(rp_["size"] - op_["size"]) <= .04)
        row("headline panel", f"{rp_.get('size', 0):.0%} of height" if rp_.get("present") else "none",
            f"{op_.get('size', 0):.0%} of height" if op_.get("present") else "none", close)
    row("caption position", ref["cap_y"], ours["cap_y"], abs(ref["cap_y"] - ours["cap_y"]) <= TOLERANCE["cap_y"], "center, fraction of height")
    ratio = ours["text_height"] / ref["text_height"]
    row("caption size", ref["text_height"], ours["text_height"], abs(ratio - 1) <= TOLERANCE["text_height"], f"ours is {ratio:.0%} of the reference")
    row("words per caption", ref["words"], ours["words"], abs(ref["words"] - ours["words"]) <= TOLERANCE["words"])
    row("all caps", ref["upper"] > .6, ours["upper"] > .6, (ref["upper"] > .6) == (ours["upper"] > .6))
    if ref.get("fill") and ours.get("fill"):
        d = delta_e(ref["fill"], ours["fill"])
        row("text color", hex_of(ref["fill"]), hex_of(ours["fill"]), d <= TOLERANCE["fill"], f"color difference {d:.0f}")
    rh, oh = ref.get("highlight") or {}, ours.get("highlight") or {}
    same = rh.get("mode") == oh.get("mode")
    d = delta_e(rh["rgb"], oh["rgb"]) if same and rh.get("rgb") and oh.get("rgb") else 0
    label = lambda h: f"{h.get('mode')} {hex_of(h['rgb'])}" if h.get("rgb") else "none"
    row("word color", label(rh), label(oh), same and d <= TOLERANCE["highlight"],
        (f"color difference {d:.0f}; " if d else "") + f"colored in {rh.get('with_color', 0)}/{rh.get('samples', 0)} "
        f"vs {oh.get('with_color', 0)}/{oh.get('samples', 0)} sampled captions")
    rp, op = ref["plate"], ours["plate"]
    d = delta_e(rp["rgb"], op["rgb"]) if rp.get("rgb") and op.get("rgb") else 0
    row("background box", hex_of(rp["rgb"]) if rp.get("rgb") else "none", hex_of(op["rgb"]) if op.get("rgb") else "none",
        rp["present"] == op["present"] and d <= TOLERANCE["plate"])
    row("outline", ref["outline"]["present"], ours["outline"]["present"], ref["outline"]["present"] == ours["outline"]["present"])
    row("title header", bool(ref.get("header")), bool(ours.get("header")), bool(ref.get("header")) == bool(ours.get("header")))
    if ref.get("face_y") is not None and ours.get("face_y") is not None:
        row("speaker position", ref["face_y"], ours["face_y"], abs(ref["face_y"] - ours["face_y"]) <= .08,
            "face center, fraction of height")
    a, b = ref.get("pop") or {}, ours.get("pop") or {}
    if a.get("measured") and b.get("measured"):
        row("pop-in time", f"{a['ms']} ms", f"{b['ms']} ms", abs(a["ms"] - b["ms"]) <= TOLERANCE["pop_ms"])
    else:
        rows.append({"name": "pop-in time", "reference": a.get("ms"), "ours": b.get("ms"), "match": None,
                     "note": "not enough clean caption onsets to measure"})
    return rows


def correct(pack: dict, ref: dict, ours: dict) -> dict:
    """One round of corrections from what the comparison measured."""
    pack = dict(pack)
    if ours.get("text_height"):
        pack["cap_size"] = round(pack["cap_size"] * ref["text_height"] / ours["text_height"])
    if ours.get("cap_y") is not None:
        pack["cap_y"] = round(min(.95, max(.05, pack["cap_y"] + ref["cap_y"] - ours["cap_y"])), 3)
    if ours.get("words") and abs(ref["words"] - ours["words"]) > TOLERANCE["words"]:
        pack["cap_words"] = max(1, min(5, pack["cap_words"] + (1 if ref["words"] > ours["words"] else -1)))
        pack["cap_chars"] = pack["cap_chars"] + (4 if ref["words"] > ours["words"] else -4)
    rp_, op_ = ref.get("panel") or {}, ours.get("panel") or {}
    if pack.get("panel") and rp_.get("present") and op_.get("present"):
        pack["panel"] = {**pack["panel"], "size": round(min(.5, max(.1, pack["panel"]["size"] + rp_["size"] - op_["size"])), 3)}
    a, b = ref.get("pop") or {}, ours.get("pop") or {}
    if a.get("measured") and b.get("measured"):
        pack["cap_pop_ms"] = max(0, pack.get("cap_pop_ms", 120) + a["ms"] - b["ms"])
    if not ref["outline"]["present"] and ours.get("outline", {}).get("present"):
        # our separation reads as an outline: drop any stroke and soften the shadow, then remove it
        pack.pop("cap_stroke", None)
        pack["cap_shadow"] = "0 2px 5px rgba(0,0,0,.3)" if pack.get("cap_shadow") not in (None, "none", "0 2px 5px rgba(0,0,0,.3)") else "none"
    elif ref["outline"]["present"] and not ours.get("outline", {}).get("present"):
        pack["cap_stroke"] = hex_of(ref["outline"].get("rgb") or [0, 0, 0])
        pack["cap_stroke_w"] = pack.get("cap_stroke_w", 4) + 2
    return pack


# ---------------------------------------------------------------- the loop
def learn(reference: Path, name: str, sample: Path, *, rounds: int = 3, base: str = "zing", out: Path | None = None,
          say=print) -> dict:
    from .render import render, theme, user_packs
    if not re.fullmatch(r"[a-z0-9-]{2,40}", name):
        raise FactoryError("pack name: 2-40 lowercase letters, digits or dashes")
    reference, sample = Path(reference).resolve(), Path(sample).resolve()
    if not reference.is_file():
        raise FactoryError(f"reference not found: {reference}")
    if not (sample / "cams.json").is_file() or not (sample / "plan.json").is_file():
        raise FactoryError(f"{sample} is not a rendered factory clip folder (needs cams.json and plan.json)")
    work = Path(out or user_packs() / f"{name}-learn").resolve()
    work.mkdir(parents=True, exist_ok=True)
    ref = measure(reference, say)
    (work / "reference.json").write_text(json.dumps(ref, indent=1), encoding="utf-8")
    pack = to_pack(ref, name, theme(base))
    history = []
    for k in range(1, max(1, rounds) + 1):
        trial = work / f"trial-{k}.mp4"
        say(f"round {k}: rendering a sample in the learned style")
        # a reference whose speaker fills the frame is checked over the speaker; a split one with its visuals
        render(sample, ref.get("shape") or "9x16", pack, out=trial,
               speaker_only=ref.get("layout") != "speaker-top" and not (ref.get("panel") or {}).get("present"))
        ours = measure(trial, say)
        rows = compare(ref, ours)
        history.append({"round": k, "pack": pack, "measured": ours, "comparison": rows})
        misses = [r["name"] for r in rows if r["match"] is False]
        say(f"round {k}: {sum(r['match'] is True for r in rows)}/{sum(r['match'] is not None for r in rows)} match"
            + (f"; off: {', '.join(misses)}" if misses else ""))
        if not misses or k == rounds:
            break
        pack = correct(pack, ref, ours)
    final = history[-1]
    user_packs().mkdir(parents=True, exist_ok=True)
    pack_path = user_packs() / f"{name}.json"
    stamped = {**final["pack"], "learned_from": {"file": reference.name, "measured": datetime.now(timezone.utc).isoformat(timespec="seconds")}}
    pack_path.write_text(json.dumps(stamped, indent=1), encoding="utf-8")
    report = {"pack": str(pack_path), "reference": ref, "rounds": history,
              "matched": sum(r["match"] is True for r in final["comparison"]),
              "checked": sum(r["match"] is not None for r in final["comparison"])}
    (work / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    side_by_side(reference, work / f"trial-{final['round']}.mp4", ref, work / "compare.jpg")
    (work / "report.md").write_text(report_md(name, report), encoding="utf-8")
    return {"pack": name, "pack_path": str(pack_path), "report": str(work / "report.md"), "compare": str(work / "compare.jpg"),
            "matched": report["matched"], "checked": report["checked"], "rounds": len(history)}


def side_by_side(reference: Path, trial: Path, ref: dict, out: Path) -> None:
    """Three moments from each, reference on top, ours below, every frame scaled to 640 px tall."""
    import io
    from PIL import Image
    rows = []
    for video in (reference, trial):
        d, row = _duration(video), []
        for f in (.2, .5, .8):
            png = subprocess.run([ffmpeg(), "-v", "error", "-ss", f"{d * f:.2f}", "-i", str(video), "-frames:v", "1",
                                  "-vf", "scale=-2:640", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True).stdout
            if png:
                row.append(Image.open(io.BytesIO(png)).convert("RGB"))
        rows.append(row)
    if not all(rows):
        return
    width = max(sum(im.width for im in row) for row in rows)
    sheet = Image.new("RGB", (width, 640 * len(rows)), (0, 0, 0))
    for y, row in enumerate(rows):
        x = 0
        for im in row:
            sheet.paste(im, (x, y * 640))
            x += im.width
    sheet.save(out, quality=88)


def report_md(name: str, report: dict) -> str:
    final = report["rounds"][-1]
    lines = [f"# Learned style: {name}", "",
             f"Matched {report['matched']} of {report['checked']} measured traits after {len(report['rounds'])} round(s).",
             "Measured from pixels; the original font, project and settings are unknown.", "",
             "| Trait | Reference | Ours | Match |", "|---|---|---|---|"]
    for r in final["comparison"]:
        mark = "yes" if r["match"] else ("not measured" if r["match"] is None else "no")
        lines.append(f"| {r['name']} | {r['reference']} | {r['ours']} | {mark}{' (' + r['note'] + ')' if r['note'] else ''} |")
    ref = report["reference"]
    font = ref.get("font")
    lines += ["", f"Closest bundled font: {font['family']} {int(font['weight'])} (similarity {font['similarity']})" if font
              else "No font candidate measured.",
              f"Layout: {ref.get('layout', 'unknown')}; cuts per minute: {ref.get('cuts_per_minute')}.",
              *([f"A show name or logo stays at the top ({' '.join(ref['brand'])}); it is not copied."] if ref.get("brand") else []),
              "", "`compare.jpg`: reference on top, ours below."]
    return "\n".join(lines) + "\n"
