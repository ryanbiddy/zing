"""Render one clip: a deterministic seek(t) page captured frame by frame in a local browser, then encoded by FFmpeg."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from . import cutout, depth, upscale
from .tools import FactoryError, data_path, ffmpeg, node_sidecar, run, sidecar_env

SHAPES = {"9x16": (1080, 1920), "4x5": (1080, 1350), "1x1": (1080, 1080), "16x9": (1920, 1080)}
VIDEO = (".mp4", ".mov", ".webm", ".gif")


def user_packs() -> Path:
    """Learned and hand-made packs live in the workspace, beside the built-in ones."""
    from myzing.storage import workspace_root
    return workspace_root() / "factory" / "packs"


def themes() -> list[str]:
    return sorted({p.stem for p in data_path("themes").glob("*.json")} | {p.stem for p in user_packs().glob("*.json")})


def theme(name: str) -> dict:
    if not re.fullmatch(r"[a-z0-9-]+", name):
        raise FactoryError(f"bad style pack name {name!r}: use lowercase letters, digits and dashes")
    for path in (user_packs() / f"{name}.json", data_path("themes", f"{name}.json")):
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    raise FactoryError(f"unknown style pack {name!r}; choose from {', '.join(themes())}")


def suffix(shape: str, pack: str) -> str:
    return ("" if shape == "9x16" else f"-{shape}") + ("" if pack == "zing" else f"-{pack}")


def quotes(shots: list[dict], words: list[dict]) -> list[dict]:
    """Quote shots become moments where the captions take over: the quoted words, the marked ones, and the window.

    The shot itself turns solo, so around the quote the speaker carries on with normal captions.
    """
    from .plan import _norm, tokens
    toks, owner = tokens(words)
    out = []
    for s in shots:
        g = s.get("graphic") or {}
        if s.get("layout") != "graphic" or g.get("kind") != "quote":
            continue
        s["layout"] = "solo"
        want, marked = [], []
        for part in re.split(r"(\*[^*]+\*)", str(g.get("text", ""))):
            for tok in _norm(part.strip("*")).split():
                want.append(tok)
                marked.append(part.startswith("*"))
        n = len(want)
        starts = [k for k in range(len(toks) - n + 1) if n and toks[k:k + n] == want]
        if not starts:
            continue
        k = min(starts, key=lambda k: abs(words[owner[k]]["os"] - s["from"]))   # a line said twice: the one at the shot
        a, b = owner[k], owner[k + n - 1]
        q = {"a": a, "b": b, "marks": sorted({owner[k + j] for j in range(n) if marked[j]}),
             "from": round(words[a]["os"] - .12, 3), "to": round(words[b]["oe"] + .8, 3)}
        if not out or q["from"] >= out[-1]["to"]:
            out.append(q)
    return out


def timeline(plan: dict, words: dict) -> tuple[float, list[dict], list[dict]]:
    duration = round(words["words"][-1]["oe"] + 0.45, 3) if words.get("words") else words.get("duration", 0)
    shots = sorted((dict(s) for s in plan["shots"]), key=lambda s: s["from"])
    card = next((s["from"] for s in shots if (s.get("graphic") or {}).get("kind") == "endcard"), None)
    if card is not None:                               # an end card holds for three seconds
        duration = max(duration, round(card + 3.0, 3))
    for i, s in enumerate(shots):
        s["idx"] = i
        s["to"] = shots[i + 1]["from"] if i + 1 < len(shots) else duration + 1
    if shots:
        shots[0]["from"] = 0
    return duration, shots, quotes(shots, words.get("words", []))


def scene_data(d: Path, shape: str, pack: str | dict, speaker_only: bool = False, parallax: bool | None = None,
               front: bool | None = None, sharpen: bool | None = None) -> dict:
    """Everything the scene needs. parallax: move photos through their depth (None: when the depth model is installed).
    sharpen: upscale small photos first (None: the project's upscale setting, when the upscaler is installed).

    front: stand the speaker, cut out, in front of each split shot's picture (None: the project's cutout setting, when
    the cutout model is installed). Shots stay split when the speaker can't be lifted cleanly.
    """
    from PIL import Image
    plan = json.loads((d / "plan.json").read_text(encoding="utf-8"))
    if speaker_only:                                   # style checks compare captions over the speaker only
        plan = {**plan, "shots": [{"from": 0, "layout": "solo"}], "visuals": {}, "hook_until": 0}
    words = json.loads((d / "words.json").read_text(encoding="utf-8"))
    cam = json.loads((d / "cams.json").read_text(encoding="utf-8"))
    duration, shots, moments = timeline(plan, words)
    cfg_file = d.parent / "factory.json"
    cfg = json.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.is_file() else {}
    if parallax is None:                       # the project's setting, then whether the weights are installed
        parallax = cfg.get("parallax", True) and depth.ready()
    if front is None:
        front = cfg.get("cutout", False) and cutout.ready()
    if sharpen is None:
        sharpen = cfg.get("upscale", True) and upscale.ready()
    splits = [s for s in shots if s.get("layout") == "split"]
    lifted = cutout.mattes(d, [(s["from"], min(s["to"], duration)) for s in splits]) if front and splits else None
    for s in splits if lifted else ():
        s["layout"] = "front"
    visuals = {}
    for vid, v in plan.get("visuals", {}).items():
        p, moved, credit = Path(v["path"]), None, v.get("credit", "")
        if sharpen and p.suffix.lower() not in VIDEO and v.get("fit") != "contain":   # photos only: never a logo or page
            sharp = upscale.upscale(p, d / "vis" / f"{vid}-upscaled.jpg")
            if sharp:
                p, credit = sharp, f"{credit} · upscaled" if credit else "upscaled"
        if parallax and p.suffix.lower() not in VIDEO and v.get("fit") != "contain":
            longest = max((min(s["to"], duration) - s["from"] for s in shots if s.get("visual") == vid), default=0)
            if longest > 0:                    # the move plays across each shot, so the longest one sets its length
                moved = depth.parallax(p, d / "vis" / f"{vid}-parallax.mp4", min(max(longest, 2), 20), key=vid)
        if moved or p.suffix.lower() in VIDEO:
            fd = d / "vis" / vid
            fd.mkdir(parents=True, exist_ok=True)
            for f in fd.glob("*.jpg"):
                f.unlink()
            run(ffmpeg(), "-v", "error", "-y", "-i", moved or p, "-t", "20", "-vf", "fps=30" if moved else "fps=30,scale=1280:-2",
                "-q:v", "3", fd / "%05d.jpg")
            w, h = Image.open(fd / "00001.jpg").size
            visuals[vid] = {"dir": fd.resolve().as_uri(), "frames": len(list(fd.glob("*.jpg"))), "w": w, "h": h,
                            "credit": credit, "fit": v.get("fit"), **({"move": True} if moved else {})}
        else:
            w, h = Image.open(p).size
            visuals[vid] = {"src": p.resolve().as_uri(), "w": w, "h": h, "credit": credit, "fit": v.get("fit")}
    hook = plan["hook"].replace("&", "&amp;").replace("<", "&lt;")
    source = d.parent / "source.json"
    W, H = SHAPES[shape]
    return {"fps": 30, "words": words["words"], "frames": cam["frames"], "framesDir": (d / "frames").resolve().as_uri(),
            "srcSize": cam["size"], "cams": cam["cams"], "burnTop": cam.get("burn_top"), "shots": shots, "quotes": moments,
            **({"mattesDir": lifted["dir"].resolve().as_uri()} if lifted else {}),
            "visuals": visuals, "hookHtml": re.sub(r"\*([^*]+)\*", r"<b>\1</b>", hook),
            "hookUntil": plan.get("hook_until", 3.0), "duration": duration,
            "sourceTag": json.loads(source.read_text(encoding="utf-8")).get("tag", "") if source.is_file() else "",
            "W": W, "H": H, "aspect": shape, "theme": pack if isinstance(pack, dict) else theme(pack)}


def render(clipdir: Path, shape: str = "9x16", pack: str | dict = "zing", *, out: Path | None = None,
           speaker_only: bool = False, parallax: bool | None = None, front: bool | None = None,
           sharpen: bool | None = None) -> Path:
    """Render a clip in a shape and pack (a name, or a pack dict being tried out) to clip[-shape][-pack].mp4."""
    if shape not in SHAPES:
        raise FactoryError(f"unknown shape {shape!r}; choose from {', '.join(SHAPES)}")
    d = Path(clipdir).resolve()
    node, sidecar = node_sidecar()
    tag = suffix(shape, pack if isinstance(pack, str) else "trial")
    data = scene_data(d, shape, pack, speaker_only, parallax, front, sharpen)
    out = Path(out).resolve() if out else d / f"clip{tag}.mp4"
    # a trial render (out given) keeps its scratch files beside the trial, not in the clip folder
    scratch = (out.with_suffix(".data.json"), out.with_suffix(".frames"), out.with_suffix(".sheet.jpg")) \
        if out.parent != d else (d / f"data{tag}.json", d / f"out{tag}", d / f"sheet{tag}.jpg")
    data_file, frames, sheet = scratch
    data_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    frames.mkdir(exist_ok=True)
    for f in frames.glob("*.jpg"):
        f.unlink()
    run(node, sidecar / "render.cjs", data_path("scene.html"), data_file, frames,
        env=sidecar_env(d / "_tmp"), cwd=sidecar, capture_output=True)
    duration = data["duration"]
    run(ffmpeg(), "-v", "error", "-y", "-framerate", 30, "-i", frames / "%05d.jpg", "-i", d / "cut.mp4",
        "-map", "0:v", "-map", "1:a", "-af", f"apad,afade=t=out:st={duration - 0.3:.2f}:d=0.3", "-t", duration,
        "-c:v", "libx264", "-crf", 18, "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", out)
    tall = shape == "9x16"
    subprocess.run([ffmpeg(), "-v", "error", "-y", "-i", str(out), "-vf",
                    f"fps=1/2.5,scale={180 if tall else 240}:-1,tile={10 if tall else 6}x{2 if tall else 4}",
                    "-frames:v", "1", str(sheet)], check=False)
    for f in frames.glob("*.jpg"):                     # the mp4 is the product; 2k JPEGs per clip are not
        f.unlink()
    frames.rmdir()
    shutil.rmtree(d / "_tmp", ignore_errors=True)      # the browser's throwaway profile
    for fd in (d / "vis").glob("*"):                   # visual frames are extracted again on every render
        if fd.is_dir():
            shutil.rmtree(fd, ignore_errors=True)
    return out
