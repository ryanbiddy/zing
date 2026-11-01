"""Render one clip: a deterministic seek(t) page captured frame by frame in a local browser, then encoded by FFmpeg."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from .tools import FactoryError, data_path, ffmpeg, node_sidecar, run, sidecar_env

SHAPES = {"9x16": (1080, 1920), "1x1": (1080, 1080), "16x9": (1920, 1080)}
VIDEO = (".mp4", ".mov", ".webm", ".gif")


def themes() -> list[str]:
    return sorted(p.stem for p in data_path("themes").glob("*.json"))


def theme(name: str) -> dict:
    path = data_path("themes", f"{name}.json")
    if not re.fullmatch(r"[a-z0-9-]+", name) or not path.is_file():
        raise FactoryError(f"unknown style pack {name!r}; choose from {', '.join(themes())}")
    return json.loads(path.read_text(encoding="utf-8"))


def suffix(shape: str, pack: str) -> str:
    return ("" if shape == "9x16" else f"-{shape}") + ("" if pack == "zing" else f"-{pack}")


def scene_data(d: Path, shape: str, pack: str) -> dict:
    from PIL import Image
    plan = json.loads((d / "plan.json").read_text(encoding="utf-8"))
    words = json.loads((d / "words.json").read_text(encoding="utf-8"))
    cam = json.loads((d / "cams.json").read_text(encoding="utf-8"))
    visuals = {}
    for vid, v in plan.get("visuals", {}).items():
        p = Path(v["path"])
        if p.suffix.lower() in VIDEO:
            fd = d / "vis" / vid
            fd.mkdir(parents=True, exist_ok=True)
            for f in fd.glob("*.jpg"):
                f.unlink()
            run(ffmpeg(), "-v", "error", "-y", "-i", p, "-t", "20", "-vf", "fps=30,scale=1280:-2", "-q:v", "3", fd / "%05d.jpg")
            w, h = Image.open(fd / "00001.jpg").size
            visuals[vid] = {"dir": fd.resolve().as_uri(), "frames": len(list(fd.glob("*.jpg"))), "w": w, "h": h,
                            "credit": v.get("credit", ""), "fit": v.get("fit")}
        else:
            w, h = Image.open(p).size
            visuals[vid] = {"src": p.resolve().as_uri(), "w": w, "h": h, "credit": v.get("credit", ""), "fit": v.get("fit")}
    duration = round(words["words"][-1]["oe"] + 0.45, 3)
    shots = sorted(plan["shots"], key=lambda s: s["from"])
    for i, s in enumerate(shots):
        s["idx"] = i
        s["to"] = shots[i + 1]["from"] if i + 1 < len(shots) else duration + 1
    shots[0]["from"] = 0
    hook = plan["hook"].replace("&", "&amp;").replace("<", "&lt;")
    source = d.parent / "source.json"
    W, H = SHAPES[shape]
    return {"fps": 30, "words": words["words"], "frames": cam["frames"], "framesDir": (d / "frames").resolve().as_uri(),
            "srcSize": cam["size"], "cams": cam["cams"], "burnTop": cam.get("burn_top"), "shots": shots,
            "visuals": visuals, "hookHtml": re.sub(r"\*([^*]+)\*", r"<b>\1</b>", hook),
            "hookUntil": plan.get("hook_until", 3.0), "duration": duration,
            "sourceTag": json.loads(source.read_text(encoding="utf-8")).get("tag", "") if source.is_file() else "",
            "W": W, "H": H, "aspect": shape, "theme": theme(pack)}


def render(clipdir: Path, shape: str = "9x16", pack: str = "zing") -> Path:
    if shape not in SHAPES:
        raise FactoryError(f"unknown shape {shape!r}; choose from {', '.join(SHAPES)}")
    d = Path(clipdir).resolve()
    node, sidecar = node_sidecar()
    tag = suffix(shape, pack)
    data = scene_data(d, shape, pack)
    (d / f"data{tag}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    frames = d / f"out{tag}"
    frames.mkdir(exist_ok=True)
    for f in frames.glob("*.jpg"):
        f.unlink()
    run(node, sidecar / "render.cjs", data_path("scene.html"), d / f"data{tag}.json", frames,
        env=sidecar_env(d / "_tmp"), cwd=sidecar, capture_output=True)
    out = d / f"clip{tag}.mp4"
    duration = data["duration"]
    run(ffmpeg(), "-v", "error", "-y", "-framerate", 30, "-i", frames / "%05d.jpg", "-i", d / "cut.mp4",
        "-map", "0:v", "-map", "1:a", "-af", f"apad,afade=t=out:st={duration - 0.3:.2f}:d=0.3", "-t", duration,
        "-c:v", "libx264", "-crf", 18, "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", out)
    tall = shape == "9x16"
    subprocess.run([ffmpeg(), "-v", "error", "-y", "-i", str(out), "-vf",
                    f"fps=1/2.5,scale={180 if tall else 240}:-1,tile={10 if tall else 6}x{2 if tall else 4}",
                    "-frames:v", "1", str(d / f"sheet{tag}.jpg")], check=False)
    for f in frames.glob("*.jpg"):                     # the mp4 is the product; 2k JPEGs per clip are not
        f.unlink()
    frames.rmdir()
    shutil.rmtree(d / "_tmp", ignore_errors=True)      # the browser's throwaway profile
    return out
