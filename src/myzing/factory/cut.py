"""Cut one moment: trim pauses, remap word times, extract frames, find camera shots and the speaker's face.

A moment is one span of the episode, or several spans played in a chosen order (a launch film assembled from a
long demo).
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from statistics import median

from .tools import FactoryError, ffmpeg, ffprobe, run

FPS = 30
SILENCE_DB, SILENCE_S, KEEP_S = -32, 0.3, 0.06
PAD = 0.25                      # around each span of a multi-span moment


def silences(wav: Path, start: float, end: float) -> list[tuple[float, float]]:
    log = run(ffmpeg(), "-hide_banner", "-ss", str(start), "-t", str(end - start), "-i", str(wav),
              "-af", f"silencedetect=noise={SILENCE_DB}dB:d={SILENCE_S}", "-f", "null", "-",
              check=False, capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    marks = [float(x) + start for x in re.findall(r"silence_(?:start|end): ([0-9.]+)", log)]
    return [(a, b) for a, b in zip(marks[::2], marks[1::2]) if b - a > SILENCE_S]


def keep_ranges(gaps: list[tuple[float, float]], s0: float, e0: float) -> list[list[float]]:
    ranges, cur = [], s0
    for a, b in gaps:
        ranges.append([cur, a + KEEP_S])
        cur = b - KEEP_S
    ranges.append([cur, e0])
    return [r for r in ranges if r[1] - r[0] > 0.05]


def remap(t: float, ranges: list[list[float]]) -> float:
    """Source time -> output time once the gaps between ranges are removed."""
    out = 0.0
    for s, e in ranges:
        if t < s:
            return out
        if t <= e:
            return out + t - s
        out += e - s
    return out


def moment_words(words: list[dict], start: float, end: float, off: float) -> list[dict]:
    out = []
    for w in words:
        if w["s"] >= start - 0.05 and w["e"] <= end + 0.35:
            w = {**w, "s": w["s"] - off, "e": w["e"] - off}
            if out and w["w"].startswith(",") and re.match(r"^,\d", w["w"]) and out[-1]["w"].rstrip(",").isdigit():
                out[-1]["w"] += w["w"]                      # "18" ",000" -> "18,000"
                out[-1]["e"] = w["e"]
                continue
            out.append(w)
    return out


def _duration(path: Path) -> float:
    out = run(ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path),
              check=False, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    return float(out.strip())


def cut(clipdir: Path, source: Path, words: list[dict], start: float, end: float,
        spans: list[list[float]] | None = None) -> dict:
    from myzing.layout.detector import require_model
    require_model()
    d = Path(clipdir)
    d.mkdir(parents=True, exist_ok=True)
    ff = ffmpeg()
    seg = d / "seg.mp4"
    spans = [[float(a), float(b)] for a, b in spans] if spans else [[start, end]]
    pad = 1.0 if len(spans) == 1 else PAD
    ws, windows, base, pieces = [], [], 0.0, []     # windows: (from, to, seg time - source time) per span
    for k, (s, e) in enumerate(spans):
        off = max(0.0, s - pad)
        piece = seg if len(spans) == 1 else d / f"seg{k}.mp4"
        run(ff, "-v", "error", "-y", "-ss", off, "-i", source, "-t", e - off + pad, "-c:v", "libx264", "-crf", "14",
            "-preset", "fast", "-r", FPS, "-c:a", "aac", "-b:a", "192k", "-ar", "48000", piece)
        shift = base - off
        got = moment_words(words, s, e, -shift)          # seg time from here on
        if not got:
            raise FactoryError(f"no transcript words between {s:.1f}s and {e:.1f}s")
        ws += got
        windows.append((s + shift, e + shift, shift))
        pieces.append(piece)
        base += _duration(piece) if len(spans) > 1 else 0.0
    if len(spans) > 1:                                   # the spans, back to back in the chosen order
        (d / "pieces.txt").write_text("".join(f"file '{p.name}'\n" for p in pieces), encoding="utf-8")
        run(ff, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", d / "pieces.txt", "-c", "copy", seg)
        for p in pieces:
            p.unlink(missing_ok=True)
        (d / "pieces.txt").unlink(missing_ok=True)
    run(ff, "-v", "error", "-y", "-i", seg, "-ac", "1", "-ar", "16000", d / "seg.wav")
    ranges = [r for a, b, _ in windows for r in keep_ranges(silences(d / "seg.wav", a, b), a, b)]
    for w in ws:
        w["os"], w["oe"] = round(remap(w["s"], ranges), 3), round(remap(w["e"], ranges), 3)
    total = sum(e - s for s, e in ranges)
    parts, labels = [], []
    for i, (s, e) in enumerate(ranges):
        parts.append(f"[0:v]trim={s:.3f}:{e:.3f},setpts=PTS-STARTPTS[v{i}];[0:a]atrim={s:.3f}:{e:.3f},asetpts=PTS-STARTPTS,"
                     f"afade=t=in:d=0.02,afade=t=out:st={max(0, e - s - 0.02):.3f}:d=0.02[a{i}]")
        labels.append(f"[v{i}][a{i}]")
    graph = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(ranges)}:v=1:a=1[v][a]"
    script = d / "silences.txt"
    script.write_text(graph, encoding="utf-8")
    run(ff, "-v", "error", "-y", "-i", seg, "-filter_complex_script", script, "-map", "[v]", "-map", "[a]", "-r", FPS,
        "-c:v", "libx264", "-crf", "12", "-preset", "fast", "-c:a", "aac", "-b:a", "192k", d / "cut.mp4")
    script.unlink(missing_ok=True)
    (d / "frames").mkdir(exist_ok=True)
    for f in (d / "frames").glob("*.jpg"):
        f.unlink()
    run(ff, "-v", "error", "-y", "-i", d / "cut.mp4", "-q:v", "2", d / "frames" / "%05d.jpg")
    seg.unlink(missing_ok=True)
    (d / "seg.wav").unlink(missing_ok=True)
    def src(r):                                          # a kept range back in episode time
        shift = next((sh for a, b, sh in windows if a - .01 <= r[0] <= b + .01), windows[0][2])
        return [round(r[0] - shift, 3), round(r[1] - shift, 3)]
    info = {"words": [{"w": w["w"], "os": w["os"], "oe": w["oe"]} for w in ws], "duration": round(total, 3),
            "source": str(source), "start": spans[0][0], "end": spans[-1][1], "ranges": [src(r) for r in ranges],
            **({"spans": spans} if len(spans) > 1 else {})}
    (d / "words.json").write_text(json.dumps(info, indent=0), encoding="utf-8")
    (d / "words-heard.json").unlink(missing_ok=True)
    (d / "word-fixes.json").unlink(missing_ok=True)
    cams(d)
    return info


def _text_cut(img, reader) -> dict:
    import cv2
    from myzing.study.caption_geometry import parse_ocr
    from myzing.study.captions import CONF_THRESHOLD
    H, Wd = img.shape[:2]
    s = min(1, 960 / max(H, Wd))
    small = cv2.resize(img, (max(1, round(Wd * s)), max(1, round(H * s))), interpolation=cv2.INTER_AREA)
    boxes = [d.box for d in parse_ocr(reader(small), small)
             if d.text and d.confidence is not None and d.confidence >= CONF_THRESHOLD]
    if sum((r - l) * (b - t) for l, t, r, b in boxes) < .03:
        return {}
    box = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
    out = {"text_box": [round(v, 3) for v in box]}
    s = max(1080 / Wd, 960 / H)                  # keep the old split-panel flag for saved projects
    w, h = 1080 / (Wd * s), 960 / (H * s)
    x, y = max(0, min(1 - w, .5 - w / 2)), max(0, min(1 - h, .38 - h / 2))
    if any(l < x or r > x + w or t < y or b > y + h for l, t, r, b in boxes):
        out["text"] = True
    return out


def _camera_cuts(d: Path, frame, duration: float) -> list[float]:
    import cv2
    log = run(ffmpeg(), "-hide_banner", "-i", str(d / "cut.mp4"), "-an", "-vf",
              "select='gte(scene,0)',metadata=print:key=lavfi.scene_score", "-f", "null", "-",
              check=False, capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    scores = [(float(t), float(s)) for t, s in re.findall(
        r"pts_time:([0-9.]+)\s*\n[^\n]*lavfi.scene_score=([0-9.]+)", log)]
    groups = []
    for t, score in scores:
        if score < .15 or not 0 < t < duration:
            continue
        nearby = [s for at, s in scores if 0 < abs(at - t) <= .5]
        if score < (2 if score >= .3 else 4) * median(nearby or [0]):   # a strong cut only has to beat busy motion
            continue
        if groups and t - groups[-1][-1] < .5:
            groups[-1].append(t)
        else:
            groups.append([t])
    cuts = []
    for group in groups:
        a, b = group[0], group[-1]
        if len(group) > 1:
            before = cv2.resize(frame(max(0, a - 1 / FPS)), (64, 36), interpolation=cv2.INTER_AREA)
            after = cv2.resize(frame(b + 1 / FPS), (64, 36), interpolation=cv2.INTER_AREA)
            if cv2.absdiff(before, after).mean() < 8:     # a brief occlusion returns to the same view
                continue
        cuts.append(b)
    return cuts


def _grid_tiles(images, faces) -> list[list[float]]:
    import cv2
    import numpy as np
    if len(faces) < 2 or any(img.size == 0 for img in images):
        return []
    H, Wd = images[0].shape[:2]
    scale = min(1, 960 / Wd)
    boxes = [[v * scale for v in f] for f in faces]
    samples, grays = [], []
    for img in images:
        small = cv2.resize(img, (round(Wd * scale), round(H * scale)), interpolation=cv2.INTER_AREA)
        h, w = small.shape[:2]
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        grays.append(gray)
        edges = cv2.Canny(gray, 20, 60)
        thick = cv2.dilate(edges, np.ones((3, 3), dtype=np.uint8))
        lines = cv2.morphologyEx(thick, cv2.MORPH_CLOSE, np.ones((3, 1), dtype=np.uint8))
        lines = cv2.morphologyEx(lines, cv2.MORPH_OPEN, np.ones((max(40, round(h*.25)), 1), dtype=np.uint8))
        contours, _ = cv2.findContours(lines, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        vertical = [(x+(ww-1)/2, y, y+hh-1) for x, y, ww, hh in map(cv2.boundingRect, contours) if ww <= 8]
        rects = []
        for x, y, fw, fh in boxes:
            candidates = []
            left = [v for v in vertical if v[0] < x and v[1] < y and v[2] > y+fh]
            right = [v for v in vertical if v[0] > x+fw and v[1] < y and v[2] > y+fh]
            for l, lt, lb in left:
                for r, rt, rb in right:
                    top = min(v[1] for v in vertical if abs(v[1]-min(lt, rt)) < h*.06)
                    bottom = max(v[2] for v in vertical if abs(v[2]-max(lb, rb)) < h*.06)
                    if abs(lt-rt) > h*.06 or abs(lb-rb) > h*.06 or r-l > w*.8 or bottom-top > h*.95:
                        continue
                    if any(l < xx+ww/2 < r and top < yy+hh/2 < bottom
                           for xx, yy, ww, hh in boxes if (xx, yy, ww, hh) != (x, y, fw, fh)):
                        continue
                    rows = np.flatnonzero((thick[:, int(l)+2:int(r)-1] > 0).mean(axis=1) >= .8)
                    above = rows[(rows >= top-8) & (rows <= max(lt, rt)+8) & (rows < y)]
                    below = rows[(rows >= bottom-8) & (rows <= bottom+8) & (rows > y+fh)]
                    if not len(above) or not len(below):
                        continue
                    candidates.append([l+1, int(above.max())+1, r, int(below.min())])
            rects.append(min(candidates, key=lambda r: (r[2]-r[0])*(r[3]-r[1])) if candidates else None)
        samples.append(rects)
    stable = []
    for rects in zip(*samples):
        if any(r is None for r in rects):
            continue
        if any(max(v)-min(v) > 5 for v in zip(*rects)):
            continue
        stable.append([max(r[0] for r in rects), max(r[1] for r in rects),
                       min(r[2] for r in rects), min(r[3] for r in rects)])
    tiles = []
    for l, t, r, b in stable:
        adjacent = any((min(b, bb)-max(t, tt) > .8*max(b-t, bb-tt) and min(abs(ll-r), abs(l-rr)) < 40) or
                       (min(r, rr)-max(l, ll) > .8*max(r-l, rr-ll) and min(abs(tt-b), abs(t-bb)) < 40)
                       for ll, tt, rr, bb in stable if [ll, tt, rr, bb] != [l, t, r, b])
        flanked = any(x+fw < l and t < y+fh/2 < b for x, y, fw, fh in boxes) and \
                  any(x > r and t < y+fh/2 < b for x, y, fw, fh in boxes)
        gutters = flanked and all(np.quantile(side, .9) < 35 and side.std() < 8
            for g in grays for side in (g[int(t):int(b), max(0, int(l)-3)],
                                       g[int(t):int(b), min(w-1, int(r)+3)],
                                       g[max(0, int(t)-3), int(l):int(r)],
                                       g[min(h-1, int(b)+3), int(l):int(r)]))
        if adjacent or gutters:
            tiles.append([round(l/(Wd*scale), 4), round(t/(H*scale), 4),
                          round(r/(Wd*scale), 4), round(b/(H*scale), 4)])
    return tiles


def cams(d: Path) -> dict:
    """Camera shots, and in each the face to frame. Close-ups teach what the main speaker wears; in wide shots the
    frame follows them, leaving only when someone else clearly out-talks them for a while."""
    import cv2
    from .pipeline import _write
    from myzing.layout.detector import face_landmarks, require_model
    n = len(list((d / "frames").glob("*.jpg")))

    def frame(t: float):
        return cv2.imread(str(d / "frames" / f"{min(n, int(t * FPS) + 1):05d}.jpg"))

    bounds = [0.0] + _camera_cuts(d, frame, n / FPS) + [n / FPS]
    yunet = cv2.FaceDetectorYN.create(str(require_model()), "", (320, 320), 0.6, 0.3, 5000)

    def faces_in(img, min_frac):
        h_, w_ = img.shape[:2]
        yunet.setInputSize((w_, h_))
        _, found = yunet.detect(img)
        boxes = [] if found is None else [tuple(int(v) for v in f[:4]) for f in found if face_landmarks(f)]
        return sorted([b for b in boxes if b[3] >= min_frac * h_], key=lambda f: -f[2] * f[3])

    def torso(img, f):
        x, y, w, h = f
        H_, W_ = img.shape[:2]
        roi = img[min(H_ - 2, y + int(h * 1.3)):min(H_, y + int(h * 3.0)), max(0, x - int(w * .6)):min(W_, x + int(w * 1.6))]
        if roi.size == 0:
            return None
        hist = cv2.calcHist([cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)], [0, 1], None, [30, 32], [0, 180, 0, 256])
        return cv2.normalize(hist, hist).flatten()

    def mouth(img, f):
        x, y, w, h = f
        return cv2.cvtColor(img[y + int(h * .62):y + int(h * 1.0), x + int(w * .2):x + int(w * .8)],
                            cv2.COLOR_BGR2GRAY).astype("float32")

    out, wides, ident = [], [], []
    for a, b in zip(bounds, bounds[1:]):
        samples = [frame(a + (b - a) * frac) for frac in (.3, .5, .7)]
        boxes = [faces_in(img, .08) for img in samples]
        best = max(boxes, key=len)
        H, Wd = frame(a).shape[:2]
        cam = {"from": round(a, 3), "to": round(b, 3), "mode": "wide"}
        if best and (len(best) == 1 or best[0][2] * best[0][3] > 2.2 * best[1][2] * best[1][3]):
            x, y, w, h = best[0]
            cam.update(mode="face", cx=(x + w / 2) / Wd, cy=(y + h / 2) / H, fh=h / H)
            for tile in _grid_tiles(samples, best):
                if tile[0] <= x/Wd and tile[1] <= y/H and tile[2] >= (x+w)/Wd and tile[3] >= (y+h)/H:
                    cam["tile"] = tile
            out.append(cam)
            mid = frame((a + b) / 2)
            fs = faces_in(mid, .08)
            if fs:
                th = torso(mid, fs[0])
                if th is not None:
                    ident.append((b - a, th))
            continue
        wides.append((a, b, cam, H, Wd, best))
    identity = sum(wt * h for wt, h in ident) / sum(wt for wt, _ in ident) if ident else None
    ocr = None
    for a, b, cam, H, Wd, best in wides:
        img = frame((a + b) / 2)
        faces = faces_in(img, .04)
        cam["faces"] = len(faces)
        if not faces and not best:
            if ocr is None:
                try:
                    from myzing.study.caption_models import engine
                    ocr, _ = engine()
                except Exception:
                    ocr = False
            if ocr:
                try:
                    cam.update(_text_cut(img, ocr))
                except Exception:
                    pass
        if len(faces) < 2 or b - a < 1.0:
            out.append(cam)
            continue
        tiles = _grid_tiles([frame(a + (b-a)*frac) for frac in (.3, .5, .7)], faces)
        windows, t = [], a
        while t < b - 0.2:
            te = min(b, t + 1.5)
            score = [0.0] * len(faces)
            for k in range(6):
                at = t + (te - t) * (k + .5) / 6
                f1, f2 = frame(at), frame(at + 2 / FPS)
                for j, f in enumerate(faces):
                    score[j] += float(abs(mouth(f1, f) - mouth(f2, f)).mean())
            windows.append((t, te, score))
            t = te
        main = max(range(len(faces)), key=lambda q: sum(w[2][q] for w in windows))
        if identity is not None:
            sims = [cv2.compareHist(identity.astype("float32"), h.astype("float32"), cv2.HISTCMP_CORREL) if h is not None
                    else -1 for h in (torso(img, f) for f in faces)]
            main = max(range(len(faces)), key=lambda q: sims[q])
        segs = []
        for t, te, score in windows:
            other = max((q for q in range(len(faces)) if q != main), key=lambda q: score[q])
            j = other if score[other] > 1.7 * score[main] else main
            if segs and segs[-1]["face"] == j:
                segs[-1]["to"] = round(te, 3)
            else:
                segs.append({"from": round(t, 3), "to": round(te, 3), "face": j})
        for k in range(1, len(segs) - 1):           # a lone 1.5 s detour is noise, not a turn
            if segs[k]["to"] - segs[k]["from"] < 1.6 and segs[k - 1]["face"] == segs[k + 1]["face"] == main:
                segs[k]["face"] = main
        merged = []
        for s in segs:
            if merged and merged[-1]["face"] == s["face"]:
                merged[-1]["to"] = s["to"]
            else:
                merged.append(dict(s))
        for s in merged:
            x, y, w, h = faces[s["face"]]
            cam = {"from": s["from"], "to": s["to"], "mode": "face", "wide": True,
                   "cx": (x + w / 2) / Wd, "cy": (y + h / 2) / H, "fh": h / H}
            for tile in tiles:
                if tile[0] <= x/Wd and tile[1] <= y/H and tile[2] >= (x+w)/Wd and tile[3] >= (y+h)/H:
                    cam["tile"] = tile
            out.append(cam)
    out.sort(key=lambda c: c["from"])
    first = frame(0)
    info = {"cams": out, "size": [first.shape[1], first.shape[0]], "frames": n, "burn_top": burned_caption_top(d)}
    _write(d / "cams.json", info)
    return info


def busy_rows(gray_frames) -> "object":
    """Mean bright/dark switches per row: captions burned into a source make their rows busy."""
    import numpy as np
    rows = None
    for g in gray_frames:
        t = np.abs(np.diff((g > 200).astype(np.int16), axis=1)).sum(axis=1) / g.shape[1]
        rows = t if rows is None else rows + t
    return rows / max(1, len(gray_frames))


def burned_caption_top(d: Path) -> float | None:
    """Top of a burned-in caption band as a fraction of the height, or None."""
    import cv2
    import numpy as np
    files = sorted((d / "frames").glob("*.jpg"))
    sample = [cv2.imread(str(f), cv2.IMREAD_GRAYSCALE) for f in files[:: max(1, len(files) // 24)][:24]]
    if not sample:
        return None
    H = sample[0].shape[0]
    rows = busy_rows(sample)
    hot = np.where(rows > max(0.04, 4 * float(np.median(rows))))[0]
    hot = hot[hot > H * .55]
    return round(max(0.5, (int(hot.min()) - H * .02) / H), 3) if len(hot) >= 4 else None
