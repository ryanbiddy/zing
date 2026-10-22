"""Opt-in v2 -> ProRes alpha -> colored-video composite pixel acceptance."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

from myzing.composition import CompositionCaption, FontAsset, CaptionStyle
from myzing.layout.types import Box, EventLayout, Keyframe, OverlapCheck, box_at
from myzing.project.models import Rational
from myzing.schemas import Word
from myzing.render.hyperframes_adapter import render_hyperframes, write_plan
from myzing.render.hyperframes_v2 import captions_to_plan, composite_overlay


def fixture_events():
    font = Path(__file__).resolve().parents[2] / "src/myzing/_data/fonts/Anton-Regular.ttf"
    asset = FontAsset(str(font), hashlib.sha256(font.read_bytes()).hexdigest(), "OFL-1.1")
    style = CaptionStyle(44, outline_width=1, box_color="#204080")
    return [
        CompositionCaption(id="phrase", text="WORDS FOLLOW TIME", start=.2, end=1.4, all_caps=False,
            word_timed=True, words=[Word("WORDS", .2, .6), Word("FOLLOW", .6, 1), Word("TIME", 1, 1.4)],
            layout=EventLayout("phrase", .2, 1.4, "synthetic static box", OverlapCheck(True), box=Box(.1, .1, .8, .3)),
            font=asset, style=style, backend="hyperframes", template="phrase-highlight"),
        CompositionCaption(id="moving", text="MOVE WITH ME", start=1.6, end=2.9, all_caps=False,
            word_timed=True, words=[Word("MOVE", 1.6, 2), Word("WITH", 2, 2.4), Word("ME", 2.4, 2.9)],
            layout=EventLayout("moving", 1.6, 2.9, "synthetic piecewise path", OverlapCheck(True), path=[
                Keyframe(1.6, Box(.1, .55, .7, .3)), Keyframe(2.2, Box(.2, .35, .7, .3)),
                Keyframe(2.9, Box(.25, .15, .7, .3))]),
            font=asset, style=style, backend="hyperframes", template="kinetic"),
    ]


def decode(path, channels):
    import numpy as np
    data = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgba" if channels == 4 else "rgb24", "-"], capture_output=True, check=True, timeout=60).stdout
    result = np.frombuffer(data, dtype=np.uint8).reshape((-1, 360, 640, channels))
    assert len(result) == 90
    return result


def inspect_pixels(overlay, composite, background, events):
    import numpy as np
    rgba, rgb, base = decode(overlay, 4), decode(composite, 3), decode(background, 3)
    yy, xx = np.mgrid[:360, :640]
    samples, max_error = [], 0
    for n in range(90):
        t = n / 30
        event = next((e for e in events if e.start <= t < e.end), None)
        alpha = rgba[n, :, :, 3]
        if event is None:
            assert np.max(alpha) == 0, f"caption leaked outside event at frame {n}"
            assert np.max(np.abs(rgb[n].astype(int) - base[n].astype(int))) <= 10
            continue
        box = event.layout.box or box_at(event.layout.path, t)
        x, y, w, h = box.x * 640, box.y * 360, box.width * 640, box.height * 360
        outside = (xx < x - 2) | (xx > x + w + 2) | (yy < y - 2) | (yy > y + h + 2)
        assert np.all(alpha[outside] == 0), f"opaque pixels outside planned box at {n}"
        assert alpha[0, 0] == 0 and np.any(alpha == 255), f"missing transparent/opaque alpha at {n}"
        by, bx = np.where(alpha > 240)
        measured = [bx.min(), by.min(), bx.max() + 1, by.max() + 1]
        expected = [x, y, x + w, y + h]
        error = max(abs(a - b) / dimension for a, b, dimension in zip(measured, expected, [640, 360, 640, 360]))
        max_error = max(max_error, error)
        assert error <= .02, f"path differs by {error:.3%} at {n}"
        # Independent yellow-pixel centroid identifies the word, including the
        # frames immediately before/after all five switches. Gaps/end are checked.
        frame = rgba[n]
        yellow = (frame[:, :, 0] > 190) & (frame[:, :, 1] > 190) & (frame[:, :, 2] < 90) & (alpha > 240)
        active = next((j for j, word in enumerate(event.words) if word.start <= t < word.end), None)
        if active is None:
            assert not yellow.any(), f"highlight in gap at {n}"
        else:
            assert yellow.sum() > 15, f"highlight missing at {n}"
            center = (xx[yellow].mean() - x) / w
            lo, hi = [(0.15, .43), (.43, .64), (.64, .90)][active]
            assert lo < center < hi, f"wrong highlighted word at {n}: {center}"
            composed = rgb[n]
            composite_yellow = (composed[:, :, 0] > 190) & (composed[:, :, 1] > 190) & (composed[:, :, 2] < 90)
            assert composite_yellow.sum() > 15, f"composite lost highlighted glyphs at {n}"
            assert abs(xx[composite_yellow].mean() - xx[yellow].mean()) <= 4, f"composite shifted highlight at {n}"
        # H.264 4:2:0 can bleed at edges; inspect outside a four-pixel margin.
        far = (xx < x - 4) | (xx > x + w + 4) | (yy < y - 4) | (yy > y + h + 4)
        assert np.max(np.abs(rgb[n].astype(int) - base[n].astype(int))[far]) <= 14, f"composite changed background at {n}"
        # Interior plate must replace the colored footage, not show opaque black
        # or lose its alpha. Probe away from glyphs and compression boundaries.
        px, py = round(x + 16), round(y + 16)
        assert np.max(np.abs(rgb[n, py, px].astype(int) - [32, 64, 128])) <= 12, f"composite plate missing at {n}"
        samples.append({"frame": n, "active_word": active, "box": [int(v) for v in measured], "path_error_fraction": error})
    return {"version": 1, "checked_frames": 90, "fully_transparent_outside_captions": True,
            "word_boundary_error_frames": 0, "max_path_error_fraction": float(max_error), "samples": samples}


def run_proof(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    events = fixture_events()
    plan = captions_to_plan(events, width=640, height=360, fps=Rational(30, 1), duration=3)
    (root / "caption-events-v2.json").write_text(json.dumps([e.to_dict() for e in events], indent=2) + "\n", encoding="utf-8")
    write_plan(plan, root / "plan.json")
    background, overlay, composite = root / "background.mp4", root / "overlay.mov", root / "composite.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-n", "-f", "lavfi", "-i", "color=c=0xa03050:s=640x360:r=30:d=3",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(background)], check=True, timeout=30)
    jobs = root / "workspace"
    render_hyperframes(plan, overlay, workspace=jobs)
    composite_overlay(background, overlay, composite, plan=plan, workspace=jobs)
    assert not list((jobs / "hyperframes/jobs").iterdir()), "successful work directories were retained"
    audio = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_streams", "-of", "json", str(composite)], capture_output=True, text=True, check=True).stdout)
    assert len(audio["streams"]) == 1
    result = inspect_pixels(overlay, composite, background, events)
    (root / "pixel-proof.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    frames = [0, 6, 17, 18, 29, 30, 42, 48, 59, 60, 72, 86]
    selector = "+".join(f"eq(n,{n})" for n in frames)
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(composite), "-vf", f"select='{selector}',scale=320:180,tile=4x3", "-frames:v", "1", str(root / "contact-sheet.png")], check=True, timeout=30)
    (root / "contact-sheet-times.json").write_text(json.dumps({"frames": frames, "seconds": [n / 30 for n in frames]}, indent=2) + "\n")
    return result


if __name__ == "__main__":
    result = run_proof(Path(os.environ.get("ZING_HYPERFRAMES_PROOF_DIR", "zing-workspace/hyperframes/p10a-proof")))
    print(json.dumps({k: v for k, v in result.items() if k != "samples"}, indent=2))
