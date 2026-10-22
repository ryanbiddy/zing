"""Opt-in local HyperFrames spike. No CLI render routing or schema v2 changes.

Times are absolute seconds, intervals are [start, end), boxes are normalized
top-left coordinates. The PH v1 contract deliberately supports integer fps.
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

HYPERFRAMES_VERSION = "0.8.144"
SETUP_HINT = "See docs/HYPERFRAMES-SIDECAR.md for local setup."


class HyperframesError(RuntimeError):
    """Invalid input, unavailable local tools, or a failed render."""


def _object(value: Any, keys: set[str], label: str) -> None:
    if not isinstance(value, dict):
        raise HyperframesError(f"{label}: expected object")
    unknown = value.keys() - keys
    if unknown:
        raise HyperframesError(f"{label}: unsupported fields {sorted(unknown)}")


def _number(value: Any, low: float, high: float, label: str) -> None:
    if (
        isinstance(value, bool) or not isinstance(value, (int, float))
        or not math.isfinite(value) or not low <= value <= high
    ):
        raise HyperframesError(f"{label}: expected finite number in [{low}, {high}]")


def _color(value: Any, label: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise HyperframesError(f"{label}: use #RRGGBB")


def _asset(value: Any, label: str, base_dir: Path | None) -> str:
    if (
        not isinstance(value, str) or not value
        or re.search(r"[\x00-\x1f]", value)
        or re.match(r"(?:[a-z]+:)?//|(?:https?|data|file):|\\\\", value, re.I)
    ):
        raise HyperframesError(f"{label}: use a local file path, not a URL or network share")
    if base_dir is None:
        return value
    path = Path(value).expanduser()
    path = (base_dir / path).resolve()
    if not path.is_file():
        raise HyperframesError(f"{label}: missing file {path}; supply an existing local file. {SETUP_HINT}")
    return str(path)


def _box(value: Any, label: str) -> None:
    _object(value, {"x", "y", "width", "height"}, label)
    for key in ("x", "y", "width", "height"):
        _number(value.get(key), 0, 1, f"{label}.{key}")
    if (
        not value["width"] or not value["height"]
        or value["x"] + value["width"] > 1 + 1e-9
        or value["y"] + value["height"] > 1 + 1e-9
    ):
        raise HyperframesError(f"{label}: box must fit within the frame")


def validate_plan(data: dict, *, base_dir: Path | None = None) -> dict:
    """Return a deep copy; with base_dir, resolve and require local assets.

    Reject unknown fields so unsupported effects cannot silently disappear.
    This validation is stdlib-only and runs even without Node installed.
    """
    p = copy.deepcopy(data)
    _object(p, {"version", "width", "height", "fps", "duration", "background", "captions"}, "plan")
    if type(p.get("version")) is not int or p["version"] != 1:
        raise HyperframesError("plan.version: only PH version 1 is supported")
    for key in ("width", "height"):
        _number(p.get(key), 2, 4096, key)
        if p[key] % 2:
            raise HyperframesError(f"{key}: use an even integer for H.264")
    _number(p.get("fps"), 1, 120, "fps")
    if p["fps"] % 1:
        raise HyperframesError("fps: PH supports integer fps only")
    _number(p.get("duration"), 1 / p["fps"], 600, "duration")
    frames = p["duration"] * p["fps"]
    if abs(frames - round(frames)) > 1e-7:
        raise HyperframesError("duration: must be a whole number of frames")
    bg = p.get("background")
    _object(bg, {"color", "video"}, "background")
    if len(bg) != 1:
        raise HyperframesError("background: choose exactly one of color or video")
    if "color" in bg:
        _color(bg["color"], "background.color")
    else:
        bg["video"] = _asset(bg["video"], "background.video", base_dir)
    if not isinstance(p.get("captions"), list):
        raise HyperframesError("captions: expected array")
    for i, event in enumerate(p["captions"]):
        label = f"captions[{i}]"
        _object(event, {"start", "end", "template", "words", "box", "path", "style"}, label)
        for key in ("start", "end"):
            _number(event.get(key), 0, p["duration"], f"{label}.{key}")
        if event["end"] <= event["start"]:
            raise HyperframesError(f"{label}: end must follow start")
        if event.get("template") not in ("phrase-highlight", "kinetic"):
            raise HyperframesError(f"{label}: unknown template")
        if ("box" in event) == ("path" in event):
            raise HyperframesError(f"{label}: choose exactly one box or path")
        if "box" in event:
            _box(event["box"], f"{label}.box")
        else:
            path = event["path"]
            if not isinstance(path, list) or len(path) < 2:
                raise HyperframesError(f"{label}.path: need at least two keyframes")
            previous = -1.0
            for keyframe in path:
                _object(keyframe, {"time", "box"}, f"{label}.path")
                _number(keyframe.get("time"), event["start"], event["end"], f"{label}.path.time")
                if keyframe["time"] <= previous:
                    raise HyperframesError(f"{label}.path: times must increase")
                _box(keyframe.get("box"), f"{label}.path.box")
                previous = keyframe["time"]
            if path[0]["time"] != event["start"] or path[-1]["time"] != event["end"]:
                raise HyperframesError(f"{label}.path: first/last times must match event start/end")
        style = event.get("style")
        _object(style, {"font", "size", "color", "highlight", "outline_color", "outline_width", "box_color"}, f"{label}.style")
        style["font"] = _asset(style.get("font"), f"{label}.style.font", base_dir)
        if Path(style["font"]).suffix.lower() not in (".ttf", ".otf", ".woff", ".woff2"):
            raise HyperframesError(f"{label}.style.font: use TTF, OTF, WOFF or WOFF2")
        _number(style.get("size"), 1, 512, f"{label}.style.size")
        _number(style.get("outline_width"), 0, 20, f"{label}.style.outline_width")
        for key in ("color", "highlight", "outline_color"):
            _color(style.get(key), f"{label}.style.{key}")
        if "box_color" in style:
            _color(style["box_color"], f"{label}.style.box_color")
        if not isinstance(event.get("words"), list) or not event["words"]:
            raise HyperframesError(f"{label}.words: need at least one word")
        previous = event["start"]
        for word in event["words"]:
            _object(word, {"text", "start", "end"}, f"{label}.words")
            text = word.get("text")
            if not isinstance(text, str) or not text.strip() or re.search(r"[\x00-\x1f]", text):
                raise HyperframesError(f"{label}.words: text must be nonempty without control characters")
            for key in ("start", "end"):
                _number(word.get(key), event["start"], event["end"], f"{label}.word.{key}")
            if word["end"] <= word["start"] or word["start"] < previous:
                raise HyperframesError(f"{label}.words: intervals must be positive, ordered and nonoverlapping")
            previous = word["end"]
    return p


@dataclass(frozen=True)
class HyperframesPlan:
    width: int
    height: int
    fps: int
    duration: float
    background: dict
    captions: list[dict]
    version: int = 1

    def to_dict(self) -> dict:
        return validate_plan(asdict(self))

    @classmethod
    def from_dict(cls, data: dict) -> HyperframesPlan:
        return cls(**validate_plan(data))


def write_plan(plan: HyperframesPlan | dict, path: Path, *, base_dir: Path | None = None) -> Path:
    """Write UTF-8 JSON with absolute asset paths, without altering the input."""
    data = plan.to_dict() if isinstance(plan, HyperframesPlan) else plan
    data = validate_plan(data, base_dir=(base_dir or Path.cwd()).resolve())
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    return path


def sidecar_directory() -> Path:
    configured = os.environ.get("ZING_HYPERFRAMES_SIDECAR")
    return Path(configured).resolve() if configured else Path(__file__).resolve().parents[3] / "tools" / "hyperframes-sidecar"


def check_install(*, sidecar: Path | None = None, browser: Path | None = None) -> dict:
    """Read-only prerequisite check; never npx, install, download, or sign in."""
    node = shutil.which("node")
    if not node:
        raise HyperframesError("Node is missing; install Node.js 24 LTS and add node to PATH.")
    try:
        version = subprocess.run([node, "--version"], capture_output=True, text=True, check=True, timeout=10).stdout.strip()
        if int(version.lstrip("v").split(".")[0]) < 24:
            raise ValueError(version)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        raise HyperframesError("Node.js 24 or newer is required; install it and retry.") from exc
    sidecar = (sidecar or sidecar_directory()).resolve()
    try:
        installed = json.loads((sidecar / "node_modules/hyperframes/package.json").read_text(encoding="utf-8"))["version"]
        if (
            installed != HYPERFRAMES_VERSION or not (sidecar / "render.mjs").is_file()
            or not (sidecar / "node_modules/hyperframes/bin/hyperframes.mjs").is_file()
        ):
            raise ValueError(installed)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HyperframesError(f"Missing pinned HyperFrames sidecar; run npm ci --ignore-scripts --no-audit --no-fund in {sidecar}. Set ZING_HYPERFRAMES_SIDECAR if installed elsewhere.") from exc
    browser = browser or Path(os.environ.get("HYPERFRAMES_BROWSER_PATH", ""))
    if not browser.is_file():
        raise HyperframesError(f"Missing browser; set HYPERFRAMES_BROWSER_PATH to the local chrome-headless-shell executable. {SETUP_HINT}")
    binaries = {}
    for name in ("ffmpeg", "ffprobe"):
        binary = os.environ.get(f"HYPERFRAMES_{name.upper()}_PATH") or shutil.which(name)
        if not binary or not Path(binary).is_file():
            raise HyperframesError(f"Missing {name}; install FFmpeg and add its bin directory to PATH.")
        binaries[name] = str(Path(binary).resolve())
    return {"node": node, "node_version": version, "sidecar": str(sidecar), "browser": str(browser.resolve()), **binaries}


def _run_process(command: list[str], *, env: dict, timeout: float, log: Path) -> None:
    options: dict = {"env": env, "stdout": subprocess.PIPE, "stderr": subprocess.STDOUT}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    try:
        process = subprocess.Popen(command, **options)
    except OSError as exc:
        raise HyperframesError(f"Could not start HyperFrames: {exc}. {SETUP_HINT}") from exc
    try:
        stdout, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        # Kill this render's entire tree: Node -> CLI -> Chrome/FFmpeg.
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=15, check=False)
        else:
            os.killpg(process.pid, signal.SIGKILL)
        stdout, _ = process.communicate(timeout=15)
        log.write_bytes(stdout or b"")
        raise HyperframesError(f"HyperFrames timed out after {timeout}s; render tree stopped. Inspect {log}, or increase timeout.") from exc
    log.write_bytes(stdout or b"")
    if process.returncode:
        detail = (stdout or b"").decode("utf-8", errors="replace")[-2000:]
        raise HyperframesError(f"HyperFrames failed ({process.returncode}); inspect {log}.\n{detail}")


def verify_output(path: Path, plan: HyperframesPlan | dict, ffprobe: str = "ffprobe") -> dict:
    p = plan.to_dict() if isinstance(plan, HyperframesPlan) else validate_plan(plan)
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True, text=True, check=True, timeout=60,
        )
        probe = json.loads(result.stdout)
        video = probe["streams"][0]
        duration = float(video.get("duration", probe["format"]["duration"]))
        rate = float(Fraction(video["avg_frame_rate"]))
        valid = (
            math.isfinite(duration) and abs(duration - p["duration"]) <= 1 / p["fps"] + 1e-6
            and video["width"] == p["width"] and video["height"] == p["height"]
            and abs(rate - p["fps"]) < 1e-6
            and int(video["nb_read_frames"]) == round(p["duration"] * p["fps"])
        )
        if not valid:
            raise ValueError("duration, size, fps or decoded frame count differs from plan")
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError, TypeError, ZeroDivisionError) as exc:
        raise HyperframesError(f"ffprobe verification failed for {path}: {exc}") from exc
    return probe


def render_hyperframes(
    plan: HyperframesPlan | dict, output_path: Path, *, base_dir: Path | None = None,
    sidecar: Path | None = None, browser: Path | None = None, timeout: float = 180,
) -> dict:
    """Render a plan locally and publish the MP4 only after ffprobe accepts it."""
    _number(timeout, 0.01, 86400, "timeout")
    output = Path(output_path).resolve()
    if output.suffix.lower() != ".mp4":
        raise HyperframesError("HyperFrames output must use .mp4")
    if output.exists():
        raise HyperframesError(f"Output already exists: {output}; choose a new path.")
    tools = check_install(sidecar=sidecar, browser=browser)
    output.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="hf-run-", dir=output.parent))
    plan_path = write_plan(plan, work / "plan.json", base_dir=base_dir)
    temporary_output = work / "render.mp4"
    env = os.environ.copy()
    env.update({"HYPERFRAMES_BROWSER_PATH": tools["browser"], "HYPERFRAMES_FFMPEG_PATH": tools["ffmpeg"], "HYPERFRAMES_FFPROBE_PATH": tools["ffprobe"]})
    started = time.perf_counter()
    _run_process([tools["node"], str(Path(tools["sidecar"]) / "render.mjs"), str(plan_path), str(temporary_output)], env=env, timeout=timeout, log=work / "sidecar.log")
    probe = verify_output(temporary_output, plan, tools["ffprobe"])
    receipt = json.loads(Path(str(temporary_output) + ".receipt.json").read_text(encoding="utf-8"))
    receipt.update({"output": str(output), "plan": str(plan_path), "wrapper_seconds": time.perf_counter() - started, "probe": probe})
    os.replace(temporary_output, output)
    Path(str(output) + ".receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt
