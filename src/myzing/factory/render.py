"""Render one clip: a deterministic seek(t) page captured frame by frame in a local browser, then encoded by FFmpeg."""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from pathlib import Path, PureWindowsPath

from . import campaign, cutout, depth, provenance, tools, upscale
from .tools import FactoryError, data_path, ffmpeg, ffprobe, node_sidecar, run, sidecar_env

SHAPES = {"9x16": (1080, 1920), "4x5": (1080, 1350), "1x1": (1080, 1080), "16x9": (1920, 1080)}
VIDEO = (".mp4", ".mov", ".webm", ".gif")


def scale(cfg: dict) -> int:
    uhd = cfg.get("uhd", False)
    if not isinstance(uhd, bool):
        raise FactoryError("uhd must be true or false")
    return 2 if uhd else 1


def warn_uhd(project: Path, say=print) -> None:
    path = project / "factory.json"
    cfg = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    if scale(cfg) == 1:
        return
    src = json.loads((project / "source.json").read_text(encoding="utf-8"))
    got = run(ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
              "-of", "json", src["media"], capture_output=True, text=True, encoding="utf-8")
    video = json.loads(got.stdout)["streams"][0]
    short = min(video["width"], video["height"])
    if short < 2160:
        say(f"source is {short}p; 4K output will be upscaled")


def user_packs() -> Path:
    """Learned and hand-made packs live in the workspace, beside the built-in ones."""
    from myzing.storage import workspace_root
    return workspace_root() / "factory" / "packs"


def themes() -> list[str]:
    return sorted({p.stem for p in data_path("themes").glob("*.json")} | {p.stem for p in user_packs().glob("*.json")})


def theme_path(name: str) -> Path:
    if not re.fullmatch(r"[a-z0-9-]+", name):
        raise FactoryError(f"bad style pack name {name!r}: use lowercase letters, digits and dashes")
    for path in (user_packs() / f"{name}.json", data_path("themes", f"{name}.json")):
        if path.is_file():
            return path
    raise FactoryError(f"unknown style pack {name!r}; choose from {', '.join(themes())}")


def theme(name: str) -> dict:
    return json.loads(theme_path(name).read_text(encoding="utf-8"))


def pack_data(pack: str | dict) -> tuple[dict, dict, list[str]]:
    folder = None
    try:
        if isinstance(pack, str):
            path = theme_path(pack)
            folder, pack = path.with_suffix(""), json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, FactoryError) as exc:
        return {}, {}, [str(exc)]
    if not isinstance(pack, dict):
        return {}, {}, ["a style pack must be a JSON object"]
    errors, assets = [], {}

    def asset(file, extensions, label):
        if not isinstance(file, str) or not file or "\0" in file:
            errors.append(f"{label} needs a file name")
            return
        p = Path(file.replace("\\", "/"))
        if p.is_absolute() or PureWindowsPath(file).anchor or ".." in p.parts or ":" in file:
            errors.append(f"{label} file {file!r} must stay inside the pack folder")
            return
        if p.suffix.lower() not in extensions:
            errors.append(f"{label} file {file!r} has a bad extension; use {', '.join(extensions)}")
            return
        if folder is None:
            errors.append(f"{label} file {file!r} needs a named style pack to locate its folder")
            return
        try:
            root, resolved = folder.resolve(), (folder / p).resolve()
            if not resolved.is_relative_to(root):
                errors.append(f"{label} file {file!r} must stay inside the pack folder")
            elif not resolved.is_file():
                errors.append(f"{label} file {file!r} is missing")
            else:
                return resolved.as_uri()
        except (OSError, ValueError, RuntimeError) as exc:
            errors.append(f"{label} file {file!r} cannot be read; {exc}")

    fonts = pack.get("fonts", [])
    if not isinstance(fonts, list):
        errors.append("fonts must be a list")
        fonts = []
    families, loaded = set(), []
    for font in fonts:
        if not isinstance(font, dict) or not isinstance(font.get("family"), str) or not font["family"].strip():
            errors.append("each font needs a family name")
            continue
        family = font["family"]
        families.add(family.casefold())
        weight, style = font.get("weight", 400), font.get("style", "normal")
        if type(weight) is not int or not 1 <= weight <= 1000:
            errors.append(f"font {family!r} weight must be an integer from 1 to 1000")
        if style not in ("normal", "italic", "oblique"):
            errors.append(f"font {family!r} style must be normal, italic or oblique")
        src = asset(font.get("file"), (".ttf", ".otf", ".woff", ".woff2"), f"font {family!r}")
        if src:
            loaded.append({"family": family, "file": font["file"], "weight": weight, "style": style, "src": src})
    if loaded:
        assets["fonts"] = loaded
    scene = data_path("scene.html").read_text(encoding="utf-8")
    families.update(f.strip(" '\"").casefold() for f in re.findall(r"@font-face\s*\{\s*font-family:([^;]+);", scene))

    def faces(fields, prefix=""):
        for key, value in fields.items():
            if key.endswith("_font") or key == "font":
                if not isinstance(value, str) or value.casefold() not in families:
                    errors.append(f"{prefix}{key} uses unknown font family {value!r}")
            elif isinstance(value, dict):
                faces(value, f"{prefix}{key}.")

    faces(pack)

    def css(value, key=""):
        if isinstance(value, dict):
            for k, v in value.items():
                if k not in ("fonts", "logo"):
                    css(v, f"{key}.{k}" if key else k)
        elif isinstance(value, list):
            for v in value:
                css(v, key)
        elif isinstance(value, str):
            value = re.sub(r"/\*.*?\*/", "", value, flags=re.S)
            value = re.sub(r"\\([0-9a-fA-F]{1,6})\s?|\\(.)",
                           lambda m: chr(int(m[1], 16) or 0xfffd) if m[1] and int(m[1], 16) <= 0x10ffff else m[2] or "\ufffd", value)
            if re.search(r"(?:url|src|(?:-webkit-)?image(?:-set)?|(?:-webkit-)?cross-fade|paint|element)\s*\(|@import", value, re.I):
                errors.append(f"{key} cannot reference resources; use the pack's fonts and logo")

    css(pack)
    pos, height = pack.get("logo_pos", "top-right"), pack.get("logo_h", 72)
    if pos not in ("top-left", "top-right", "bottom-right"):
        errors.append("logo_pos must be top-left, top-right or bottom-right")
    if type(height) not in (int, float) or not math.isfinite(height) or height <= 0:
        errors.append("logo_h must be a positive number")
    if "logo" in pack:
        src = asset(pack["logo"], (".svg", ".png"), "logo")
        if src:
            assets["logo"] = {"file": pack["logo"], "src": src, "pos": pos, "h": height}
    return pack, assets, errors


def check_pack(pack: str | dict) -> list[str]:
    return pack_data(pack)[2]


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
    if card is not None:                               # an end card holds for three seconds, bounded even for a
        last = words["words"][-1]["oe"] if words.get("words") else duration   # hand-edited plan
        duration = max(duration, round(min(card, last + 3.0) + 3.0, 3))
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
    theme, assets, errors = pack_data(pack)
    if errors:
        raise FactoryError(f"style pack {pack if isinstance(pack, str) else pack.get('name', 'trial')!r} failed checks\n"
                           + "\n".join(errors))
    from PIL import Image
    plan = json.loads((d / "plan.json").read_text(encoding="utf-8"))
    if speaker_only:                                   # style checks compare captions over the speaker only
        plan = {**plan, "shots": [{"from": 0, "layout": "solo"}], "visuals": {}, "hook_until": 0}
    words = json.loads((d / "words.json").read_text(encoding="utf-8"))
    cam = json.loads((d / "cams.json").read_text(encoding="utf-8"))
    duration, shots, moments = timeline(plan, words)
    brief = campaign.read(d.parent)
    overlay = campaign.disclosure(brief)
    check_brief(d, {"duration": duration, "disclosure": overlay})
    cfg_file = d.parent / "factory.json"
    cfg = json.loads(cfg_file.read_text(encoding="utf-8")) if cfg_file.is_file() else {}
    uhd = scale(cfg) == 2
    if parallax is None:                       # the project's setting, then whether the weights are installed
        parallax = cfg.get("parallax", True) and depth.ready()
    if front is None:
        front = cfg.get("cutout", False) and cutout.ready()
    if sharpen is None:
        sharpen = cfg.get("upscale", True) and upscale.ready()
    splits = [s for s in shots if s.get("layout") == "split"]
    lifted = cutout.mattes(d, [(s["from"], min(s["to"], duration)) for s in splits],
                            **({"width": None} if uhd else {})) if front and splits else None
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
                moved = depth.parallax(p, d / "vis" / f"{vid}-parallax.mp4", min(max(longest, 2), 20), key=vid,
                                       **({"width": None} if uhd else {}))
        if moved or p.suffix.lower() in VIDEO:
            fd = d / "vis" / vid
            fd.mkdir(parents=True, exist_ok=True)
            for f in fd.glob("*.jpg"):
                f.unlink()
            run(ffmpeg(), "-v", "error", "-y", "-i", moved or p, "-t", "20", "-vf", "fps=30" if moved or uhd else "fps=30,scale=1280:-2",
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
    return {"fps": 30, **({"scale": 2} if uhd else {}),
            "words": words["words"], "frames": cam["frames"], "framesDir": (d / "frames").resolve().as_uri(),
            "srcSize": cam["size"], "cams": cam["cams"], "burnTop": cam.get("burn_top"), "shots": shots, "quotes": moments,
            **({"mattesDir": lifted["dir"].resolve().as_uri()} if lifted else {}),
            "visuals": visuals, "hookHtml": re.sub(r"\*([^*]+)\*", r"<b>\1</b>", hook),
            "hookUntil": plan.get("hook_until", 3.0), "duration": duration,
            **({"disclosure": overlay} if overlay else {}),
            "sourceTag": json.loads(source.read_text(encoding="utf-8")).get("tag", "") if source.is_file() else "",
            "W": W, "H": H, "aspect": shape, "theme": theme, **assets, **provenance.scene(d.parent)}


def check_brief(d: Path, data: dict | None = None, *, stop: bool = True) -> dict | None:
    if not (d.parent / "brief.json").is_file():
        (d / "brief_check.json").unlink(missing_ok=True)
        return None
    brief = campaign.read(d.parent)
    plan = json.loads((d / "plan.json").read_text(encoding="utf-8"))
    words = json.loads((d / "words.json").read_text(encoding="utf-8"))
    duration = data["duration"] if data is not None else timeline(plan, words)[0]
    overlay = data.get("disclosure") if data is not None else campaign.disclosure(brief)
    result = campaign.check(d, brief, duration, plan["hook"], words["words"], overlay)
    if stop and result["errors"]:
        raise FactoryError(f"{d.name} cannot render. " + "; ".join(result["errors"]))
    return result


def capture(data: dict, data_file: Path, frames: Path, *, layer: str | None = None,
            samples: list[int] | None = None):
    node, sidecar = node_sidecar()
    data = {k: v for k, v in data.items() if k not in {"overlay", "speakerLayer", "captureFrames"}}
    if layer:
        data["overlay" if layer == "overlay" else "speakerLayer"] = True
    if samples is not None:
        data["captureFrames"] = samples
    data_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    frames.mkdir(exist_ok=True)
    tmp = frames.parent / "_tmp"
    count = len(samples) if samples is not None else round(data["duration"] * data.get("fps", 30))
    try:
        run(node, data_path("render.cjs"), data_path("scene.html"), data_file, frames,
            env=sidecar_env(tmp), cwd=sidecar, capture_output=True, timeout=300 + 3 * count)
        if layer == "overlay":
            flatten_backdrop(frames)
    except subprocess.TimeoutExpired as exc:
        raise FactoryError("scene render timed out") from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr
        raise FactoryError(message or "scene capture failed") from exc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def flatten_backdrop(frames: Path):
    """Keep cutout edges and backdrop-dependent grain when the overlay sits above an opaque speaker track."""
    import numpy as np
    from PIL import Image
    for path in (frames / "normal").glob("*.png"):
        def pixels(file, mode):
            with Image.open(file) as img:
                return np.asarray(img.convert(mode), dtype=np.float32) / 255
        normal = pixels(path, "RGB")
        speaker = pixels(frames / "speaker" / path.name, "RGB")
        alpha = pixels(frames / path.name, "RGBA")[:, :, 3:]
        matte = frames / "matte" / path.name
        if matte.is_file():
            alpha *= 1 - pixels(matte, "RGBA")[:, :, 3:]
        need = np.maximum((normal - speaker) / np.maximum(1 - speaker, 1 / 255),
                          (speaker - normal) / np.maximum(speaker, 1 / 255)).max(axis=2, keepdims=True)
        alpha = np.ceil(np.clip(np.maximum(alpha, need), 0, 1) * 255) / 255   # round up so the recovered color stays in gamut
        rgb = (normal - speaker * (1 - alpha)) / np.maximum(alpha, 1 / 255)
        rgba = np.concatenate([np.clip(rgb, 0, 1), alpha], axis=2)
        Image.fromarray(np.rint(rgba * 255).astype(np.uint8)).save(frames / path.name)


def render(clipdir: Path, shape: str = "9x16", pack: str | dict = "zing", *, out: Path | None = None,
           speaker_only: bool = False, parallax: bool | None = None, front: bool | None = None,
           sharpen: bool | None = None) -> Path:
    """Render a clip in a shape and pack (a name, or a pack dict being tried out) to clip[-shape][-pack].mp4."""
    if shape not in SHAPES:
        raise FactoryError(f"unknown shape {shape!r}; choose from {', '.join(SHAPES)}")
    d = Path(clipdir).resolve()
    tag = suffix(shape, pack if isinstance(pack, str) else "trial")
    data = scene_data(d, shape, pack, speaker_only, parallax, front, sharpen)
    check_brief(d, data)
    out = Path(out).resolve() if out else d / f"clip{tag}.mp4"
    # a trial render (out given) keeps its scratch files beside the trial, not in the clip folder
    scratch = (out.with_suffix(".data.json"), out.with_suffix(".frames"), out.with_suffix(".sheet.jpg")) \
        if out.parent != d else (d / f"data{tag}.json", d / f"out{tag}", d / f"sheet{tag}.jpg")
    data_file, frames, sheet = scratch
    frames.mkdir(exist_ok=True)
    for f in frames.glob("*.jpg"):
        f.unlink()
    capture(data, data_file, frames)
    duration = data["duration"]
    uhd = data.get("scale", 1) == 2
    part = out.with_name(f"_{out.stem}.part{out.suffix}")
    try:
        run(ffmpeg(), "-v", "error", "-y", "-framerate", 30, "-i", frames / "%05d.jpg", "-i", d / "cut.mp4",
            "-map", "0:v", "-map", "1:a", "-af", f"apad,afade=t=out:st={duration - 0.3:.2f}:d=0.3", "-t", duration,
            "-c:v", "libx264", "-crf", 20 if uhd else 18, "-preset", "medium",
            *(["-profile:v", "high", "-level:v", "5.1", "-maxrate", "40M", "-bufsize", "80M",
               "-vf", "scale=in_range=pc:out_range=tv", "-color_range", "tv"] if uhd else []),
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", part)
        part.replace(out)
    finally:
        part.unlink(missing_ok=True)
    tall = shape == "9x16"
    tools.run(ffmpeg(), "-v", "error", "-y", "-i", str(out), "-vf",
        f"fps=1/2.5,scale={180 if tall else 240}:-1,tile={10 if tall else 6}x{2 if tall else 4}",
        "-frames:v", "1", str(sheet), check=False)
    for f in frames.glob("*.jpg"):                     # the mp4 is the product; 2k JPEGs per clip are not
        f.unlink()
    frames.rmdir()
    shutil.rmtree(d / "_tmp", ignore_errors=True)      # the browser's throwaway profile
    for fd in (d / "vis").glob("*"):                   # visual frames are extracted again on every render
        if fd.is_dir():
            shutil.rmtree(fd, ignore_errors=True)
    return out
