"""Cut one moment: trim pauses, remap word times, extract frames, find camera shots and the speaker's face.

A moment is one span of the episode, or several spans played in a chosen order (a launch film assembled from a
long demo).
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

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


def cams(d: Path) -> dict:
    """Camera shots, and in each the face to frame. Close-ups teach what the main speaker wears; in wide shots the
    frame follows them, leaving only when someone else clearly out-talks them for a while."""
    import cv2
    from .pipeline import _write
    from myzing.layout.detector import require_model
    log = run(ffmpeg(), "-hide_banner", "-i", str(d / "cut.mp4"), "-vf", "select='gt(scene,0.3)',showinfo",
              "-f", "null", "-", check=False, capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    cuts = [float(x) for x in re.findall(r"pts_time:([0-9.]+)", log)]
    n = len(list((d / "frames").glob("*.jpg")))
    bounds = [0.0] + cuts + [n / FPS]
    yunet = cv2.FaceDetectorYN.create(str(require_model()), "", (320, 320), 0.6, 0.3, 5000)

    def frame(t: float):
        return cv2.imread(str(d / "frames" / f"{min(n, int(t * FPS) + 1):05d}.jpg"))

    def faces_in(img, min_frac):
        h_, w_ = img.shape[:2]
        yunet.setInputSize((w_, h_))
        _, found = yunet.detect(img)
        boxes = [] if found is None else [tuple(int(v) for v in f[:4]) for f in found]
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
        boxes = [faces_in(frame(a + (b - a) * frac), .08) for frac in (.3, .5, .7)]
        best = max(boxes, key=len)
        H, Wd = frame(a).shape[:2]
        cam = {"from": round(a, 3), "to": round(b, 3), "mode": "wide"}
        if best and (len(best) == 1 or best[0][2] * best[0][3] > 2.2 * best[1][2] * best[1][3]):
            x, y, w, h = best[0]
            cam.update(mode="face", cx=(x + w / 2) / Wd, cy=(y + h / 2) / H, fh=h / H)
            out.append(cam)
            mid = frame((a + b) / 2)
            fs = faces_in(mid, .08)
            if fs:
                th = torso(mid, fs[0])
                if th is not None:
                    ident.append((b - a, th))
            continue
        wides.append((a, b, cam, H, Wd))
    identity = sum(wt * h for wt, h in ident) / sum(wt for wt, _ in ident) if ident else None
    for a, b, cam, H, Wd in wides:
        img = frame((a + b) / 2)
        faces = faces_in(img, .04)
        cam["faces"] = len(faces)
        if len(faces) < 2 or b - a < 1.0:
            out.append(cam)
            continue
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
            out.append({"from": s["from"], "to": s["to"], "mode": "face", "wide": True,
                        "cx": (x + w / 2) / Wd, "cy": (y + h / 2) / H, "fh": h / H})
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
