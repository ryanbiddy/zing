"""Generate the opt-in PH acceptance fixture and inspect decoded MP4 pixels.

Run from the checkout with uv run --frozen python tools/hyperframes-sidecar/proof.py.
No downloads here: run the explicit npm font fetch during setup.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from myzing.render.hyperframes_adapter import HyperframesPlan, render_hyperframes, sidecar_directory


def fixture_plan(font: Path, video: Path | None = None) -> HyperframesPlan:
    style = {"font": str(font.resolve()), "size": 44, "color": "#ffffff", "highlight": "#ffff00", "outline_color": "#000000", "outline_width": 1, "box_color": "#204080"}
    return HyperframesPlan.from_dict({
        "version": 1, "width": 640, "height": 360, "fps": 30, "duration": 3,
        "background": {"video": str(video.resolve())} if video else {"color": "#101820"},
        "captions": [
            {"start": .2, "end": 1.4, "template": "phrase-highlight", "box": {"x": .1, "y": .1, "width": .8, "height": .3}, "style": style,
             "words": [{"text": "WORDS", "start": .2, "end": .6}, {"text": "FOLLOW", "start": .6, "end": 1}, {"text": "TIME", "start": 1, "end": 1.4}]},
            {"start": 1.6, "end": 2.9, "template": "kinetic", "path": [
                {"time": 1.6, "box": {"x": .1, "y": .55, "width": .7, "height": .3}},
                {"time": 2.9, "box": {"x": .25, "y": .15, "width": .7, "height": .3}}], "style": style,
             "words": [{"text": "MOVE", "start": 1.6, "end": 2}, {"text": "WITH", "start": 2, "end": 2.4}, {"text": "ME", "start": 2.4, "end": 2.9}]},
        ],
    })


def inspect_pixels(output: Path, plan: HyperframesPlan, ffmpeg: str = "ffmpeg") -> dict:
    data = subprocess.run([ffmpeg, "-v", "error", "-i", str(output), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True, timeout=60).stdout
    frame_bytes = plan.width * plan.height * 3
    assert len(data) == frame_bytes * round(plan.duration * plan.fps), "wrong decoded frame count"
    # Independent color probes on all frames, including both sides of each word
    # boundary. Pixel thresholds allow H.264 chroma subsampling at glyph edges.
    samples = []
    for n in range(round(plan.duration * plan.fps)):
        t = n / plan.fps
        frame = memoryview(data)[n * frame_bytes:(n + 1) * frame_bytes]
        if plan.background.get("video"):
            r, g, b = frame[(340 * plan.width + 30) * 3:(340 * plan.width + 30) * 3 + 3]
            assert (r > 80 and b > 30) == (n >= 45), f"background video not synchronized at frame {n}"
        event = next((e for e in plan.captions if e["start"] <= t < e["end"]), None)
        if event:
            box = event.get("box")
            if box is None:
                a, b = event["path"]
                q = (t - a["time"]) / (b["time"] - a["time"])
                box = {k: a["box"][k] + q * (b["box"][k] - a["box"][k]) for k in a["box"]}
            x, y, w, h = [box[k] * (plan.width if k in ("x", "width") else plan.height) for k in ("x", "y", "width", "height")]
        blues, yellows = [], []
        # Caption region excludes the source-video marker at y >= 330.
        for py in range(0, 325):
            for px in range(plan.width):
                offset = (py * plan.width + px) * 3
                r, g, b = frame[offset], frame[offset + 1], frame[offset + 2]
                if abs(r - 32) < 18 and abs(g - 64) < 18 and abs(b - 128) < 18:
                    blues.append((px, py))
                if r > 190 and g > 190 and b < 90:
                    yellows.append((px, py))
        if not event:
            assert not blues and not yellows, f"caption leaked outside event at frame {n}"
            continue
        assert blues, f"caption box missing at frame {n}"
        bounds = [min(v[0] for v in blues), min(v[1] for v in blues), max(v[0] for v in blues) + 1, max(v[1] for v in blues) + 1]
        expected = [x, y, x + w, y + h]
        assert max(abs(a - b) for a, b in zip(bounds, expected)) <= 3, f"box mismatch at {n}: {bounds} != {expected}"
        # Every detected blue pixel is inside the planned box (+ codec margin).
        assert all(x - 3 <= px <= x + w + 3 and y - 3 <= py <= y + h + 3 for px, py in blues)
        active = next((j for j, word in enumerate(event["words"]) if word["start"] <= t < word["end"]), None)
        if active is None:
            assert not yellows, f"highlight in word gap at frame {n}"
        else:
            assert len(yellows) > 15, f"highlight missing at frame {n}"
            center = sum(px for px, _ in yellows) / len(yellows)
            relative = (center - x) / w
            # Authored three-word fixture: word centroids occupy distinct bands.
            # These are pixel criteria, not DOM coordinates supplied by the renderer.
            limits = [(0.15, .43), (.43, .64), (.64, .90)]
            lo, hi = limits[active]
            assert lo < relative < hi, f"wrong highlighted word at frame {n}: {relative}, expected {active}"
            samples.append({"frame": n, "active_word": active, "highlight_center_fraction": relative, "box": bounds})
    return {"version": 1, "decoded_frames": 90, "checked_frames": 90, "word_boundary_error_frames": 0, "box_tolerance_pixels": 3, "samples": samples}


def run_proof(root: Path, font: Path) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    background = root / "background.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=0x101820:s=640x360:r=30:d=3",
        "-vf", "drawbox=x=20:y=330:w=600:h=20:color=0x800040:t=fill:enable='gte(t,1.5)'",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(background),
    ], check=True, timeout=30)
    plan = fixture_plan(font, background)
    output = root / "fixture.mp4"
    receipt = render_hyperframes(plan, output, timeout=180)
    pixels = inspect_pixels(output, plan)
    (root / "pixel-proof.json").write_text(json.dumps(pixels, indent=2) + "\n", encoding="utf-8")
    subprocess.run([
        "node", str(sidecar_directory() / "verify-seeks.mjs"), receipt["project"],
    ], check=True, capture_output=True, timeout=60)
    frames = [6, 17, 18, 29, 30, 41, 48, 59, 60, 71, 72, 84]
    frame_dir = root / "frames"
    frame_dir.mkdir(exist_ok=True)
    for n in frames:
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(output),
            "-vf", f"select=eq(n\\,{n})", "-frames:v", "1", str(frame_dir / f"frame-{n:03d}.png"),
        ], check=True, timeout=30)
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(output),
        "-vf", "select='eq(n,6)+eq(n,17)+eq(n,18)+eq(n,29)+eq(n,30)+eq(n,41)+eq(n,48)+eq(n,59)+eq(n,60)+eq(n,71)+eq(n,72)+eq(n,84)',scale=320:180,tile=4x3",
        "-frames:v", "1", str(root / "contact-sheet.png"),
    ], check=True, timeout=30)
    (root / "contact-sheet-times.json").write_text(json.dumps({"frames": frames, "seconds": [n / 30 for n in frames]}, indent=2) + "\n", encoding="utf-8")
    return receipt


if __name__ == "__main__":
    root = Path(os.environ.get("ZING_HYPERFRAMES_PROOF_DIR", "zing-workspace/hyperframes/proof"))
    font = Path(os.environ.get("ZING_HYPERFRAMES_FONT", "zing-workspace/hyperframes/fonts/Anton-Regular.ttf"))
    print(json.dumps(run_proof(root, font), indent=2))
