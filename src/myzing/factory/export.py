"""Export a factory clip as two video layers, audio, captions and an NLE timeline."""
from __future__ import annotations

import html
import json
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import TemporaryDirectory

from . import render
from .tools import FactoryError, ffmpeg, run


def srt(path: Path, cues: list[dict]):
    def stamp(t):
        ms = max(0, round(t * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    path.write_text("".join(f"{i}\n{stamp(c['from'])} --> {stamp(c['to'])}\n{c['text']}\n\n"
                            for i, c in enumerate(cues, 1)), encoding="utf-8")


def timeline(out: Path, name: str, width: int, height: int, frames: int):
    def add(parent, tag, text=None, **attrs):
        el = ET.SubElement(parent, tag, attrs)
        if text is not None:
            el.text = str(text)
        return el
    def rate(parent):
        r = add(parent, "rate")
        add(r, "timebase", 30)
        add(r, "ntsc", "FALSE")
    def video_format(parent):
        s = add(parent, "samplecharacteristics")
        rate(s)
        for k, v in (("width", width), ("height", height), ("anamorphic", "FALSE"),
                     ("pixelaspectratio", "square"), ("fielddominance", "none")):
            add(s, k, v)
    root = ET.Element("xmeml", version="5")
    seq = add(root, "sequence", id="sequence-1")
    add(seq, "name", name)
    add(seq, "duration", frames)
    rate(seq)
    tc = add(seq, "timecode")
    rate(tc)
    add(tc, "string", "00:00:00:00")
    add(tc, "frame", 0)
    add(tc, "displayformat", "NDF")
    media = add(seq, "media")
    video, audio = add(media, "video"), add(media, "audio")
    video_format(add(video, "format"))
    sound = add(add(audio, "format"), "samplecharacteristics")
    add(sound, "depth", 24)
    add(sound, "samplerate", 48000)
    for i, (file, kind) in enumerate((("speaker.mp4", "video"), ("overlay.mov", "video"), ("audio.wav", "audio")), 1):
        track = add(video if kind == "video" else audio, "track")
        clip = add(track, "clipitem", id=f"clip-{i}")
        add(clip, "name", file)
        add(clip, "enabled", "TRUE")
        add(clip, "duration", frames)
        rate(clip)
        for k, v in (("start", 0), ("end", frames), ("in", 0), ("out", frames)):
            add(clip, k, v)
        if kind == "video":
            add(clip, "alphatype", "straight" if file == "overlay.mov" else "none")
        f = add(clip, "file", id=f"file-{i}")
        add(f, "name", file)
        add(f, "pathurl", (out / file).resolve().as_uri())
        rate(f)
        add(f, "duration", frames)
        m = add(add(f, "media"), kind)
        if kind == "video":
            video_format(m)
        else:
            s = add(m, "samplecharacteristics")
            add(s, "depth", 24)
            add(s, "samplerate", 48000)
            add(m, "channelcount", 2)
        source = add(clip, "sourcetrack")
        add(source, "mediatype", kind)
        add(source, "trackindex", 1)
    ET.indent(root)
    ET.ElementTree(root).write(out / "timeline.xml", encoding="utf-8", xml_declaration=True)


def compare(out: Path, reference: Path, samples: list[int], fps: int) -> list[dict]:
    import numpy as np
    from PIL import Image
    results = []
    for f in samples:
        at = f / fps
        dest = reference / f"composite-{f}.png"
        run(ffmpeg(), "-v", "error", "-y", "-ss", at, "-i", out / "speaker.mp4", "-ss", at,
            "-i", out / "overlay.mov", "-filter_complex", "[0:v][1:v]overlay=format=rgb:alpha=straight",
            "-frames:v", 1, "-threads", 1, dest)
        with Image.open(dest) as a, Image.open(reference / f"{f + 1:05d}.png") as b:
            diff = np.asarray(a.convert("RGB"), dtype=np.float32) - np.asarray(b.convert("RGB"), dtype=np.float32)
        mse = float(np.mean(diff * diff))
        results.append({"frame": f, "time": round(at, 6), "mae": round(float(np.abs(diff).mean()), 4),
                        "psnr_db": round(float(10 * np.log10(255 ** 2 / mse)), 3) if mse else None})
    return results


def export(clipdir: Path, shape: str = "9x16", pack: str = "desk", *, out: Path | None = None) -> dict:
    if shape not in render.SHAPES:
        raise FactoryError(f"unknown shape {shape!r}; choose from {', '.join(render.SHAPES)}")
    started = time.monotonic()
    d = Path(clipdir).resolve()
    out = Path(out).resolve() if out else d / f"export-{shape}"
    out.mkdir(parents=True, exist_ok=True)
    data = render.scene_data(d, shape, pack)
    fps, scale = data["fps"], data.get("scale", 1)
    width, height = data["W"] * scale, data["H"] * scale
    frames = int(data["duration"] * fps + .5)
    duration = frames / fps
    samples = [min(frames - 1, int(frames * p)) for p in (.1, .5, .9)]
    try:
        with TemporaryDirectory(prefix=".export-", dir=out) as scratch:
            work = Path(scratch)
            for layer, file in (("speaker", "speaker.mp4"), ("overlay", "overlay.mov")):
                images = work / layer
                render.capture(data, work / f"{layer}.json", images, layer=layer)
                codec = ("-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-alpha_bits", "16") \
                    if layer == "overlay" else ("-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-movflags", "+faststart")
                run(ffmpeg(), "-v", "error", "-y", "-framerate", fps, "-i", images / "%05d.png", "-frames:v", frames,
                    "-an", *codec, out / file)
            run(ffmpeg(), "-v", "error", "-y", "-i", d / "cut.mp4", "-map", "0:a:0", "-vn", "-af",
                render.audio_filter(data), "-t", duration,
                "-ar", 48000, "-ac", 2, "-c:a", "pcm_s24le", out / "audio.wav")
            reference = work / "reference"
            render.capture(data, work / "reference.json", reference, samples=samples)
            srt(out / "captions.srt", json.loads((reference / "captions.json").read_text(encoding="utf-8")))
            srt(out / "words.srt", [{"from": w["os"], "to": w["oe"], "text": w["w"]} for w in data["words"]])
            checks = compare(out, reference, samples, fps)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr or str(exc)
        raise FactoryError(f"export failed\n{detail[-2000:]}") from exc
    name = html.unescape(re.sub(r"<[^>]*>", "", data["hookHtml"]))
    timeline(out, name, width, height, frames)
    (out / "README.txt").write_text(
        "Import timeline.xml into Premiere Pro or DaVinci Resolve.\n"
        "Keep speaker.mp4, overlay.mov and audio.wav beside the XML; relink them if you move the folder.\n"
        "Import captions.srt or words.srt to style new captions; the overlay also contains the rendered captions.\n",
        encoding="utf-8")
    files = ["speaker.mp4", "overlay.mov", "captions.srt", "words.srt", "audio.wav", "timeline.xml", "README.txt"]
    return {"exported": str(out), "shape": shape, "pack": pack, "frames": frames, "fps": fps,
            "duration": duration, "comparison": checks, "bytes": {f: (out / f).stat().st_size for f in files},
            "seconds": round(time.monotonic() - started, 3)}
