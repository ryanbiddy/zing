"""Small, silent generated fixtures for offline Studio acceptance scripts."""

import hashlib
import json
from pathlib import Path
import subprocess


def prepare(out):
    out = Path(out).resolve()
    media, clips, photos = out / "verified", out / "clips", out / "photos"
    for folder in (media, clips, photos):
        folder.mkdir(parents=True, exist_ok=True)
    receipts = []
    colors = ["0x863d33", "0x2c527d", "0x437b53", "0x7b6530", "0x643e75", "0x327c80"]
    for i, name in enumerate(("nasa-montage", "korky", "tos-lab", "nasa-opening")):
        target = media / (name + ".mp4")
        count = 3 if i == 0 else 6
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y"]
        for n in range(count):
            command += ["-f", "lavfi", "-i", f"color=c={colors[(n+i)%len(colors)]}:s=320x180:r=30:d=2"]
        graph = "".join(f"[{n}:v]" for n in range(count)) + f"concat=n={count}:v=1:a=0[v]"
        command += ["-filter_complex_threads", "1", "-filter_complex", graph, "-map", "[v]",
                    "-c:v", "libx264", "-threads", "1", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(target)]
        subprocess.run(command, check=True, capture_output=True, timeout=60)
        receipts.append({"file": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                         "license": "CC0", "source": "Generated color bars; legacy filenames only, no licensed V1 media used."})
        if i:
            (clips / target.name).write_bytes(target.read_bytes())
            subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(target), "-frames:v", "1",
                            str(photos / (name + ".png"))], check=True, capture_output=True, timeout=30)
    (out / "media-receipts.json").write_text(json.dumps(receipts, indent=2), encoding="utf-8")


def match_answers(reference, clips, *, generated=False, platform="YouTube", speech="skip"):
    """Question order is exercised through the real command loop in tests."""
    return ["1", str(reference), str(clips), "general", "a short introduction to people making things",
            platform, "6" if generated else "15", "none" if generated else "phone", "original",
            *([] if generated else [speech]), "yes"]
