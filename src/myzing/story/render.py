"""Capture the local cutout page and mux its frames with narration."""
from __future__ import annotations

import json
import math
import subprocess
import tempfile
import wave
from pathlib import Path

from myzing.factory.tools import FactoryError, ffmpeg, node_sidecar, run, sidecar_env

from . import StoryError, data_path
from .audio import mix
from .contract import check_timings, load, local_photo
from .outro import prepare

FPS = 30


def _timings(directory: Path, story: dict) -> dict:
    try:
        timings = json.loads((directory / "timings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StoryError("Cannot read timings.json. Run 'zing story voice' first.") from exc
    problems = check_timings(story, timings)
    if problems:
        raise StoryError("Invalid timings.json:\n" + "\n".join(problems))
    return timings


def _samples(stills: str | list[float] | None, duration: float) -> list[float] | None:
    if stills is None:
        return None
    try:
        samples = [float(value) for value in (stills.split(",") if isinstance(stills, str) else stills)]
    except (TypeError, ValueError) as exc:
        raise StoryError("Stills must be comma-separated times in seconds.") from exc
    if not samples or any(not math.isfinite(t) or t < 0 or t >= duration for t in samples):
        raise StoryError(f"Still times must be at least 0 and less than {duration:g} seconds.")
    return samples


def capture(data: dict, scratch: Path, frames: Path) -> None:
    """Use the same local browser, environment and process handling as factory."""
    node, sidecar = node_sidecar()
    data_file = scratch / "data.json"
    data_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    count = len(data["stills"]) if data.get("stills") is not None else math.ceil(data["timings"]["duration"] * FPS)
    try:
        run(node, data_path("render.cjs"), data_path("cutout.html"), data_file, frames,
            env=sidecar_env(scratch / "browser"), cwd=sidecar, capture_output=True, timeout=300 + 3 * count)
    except subprocess.TimeoutExpired as exc:
        raise StoryError("Story capture timed out.") from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr
        raise StoryError(message or "Story capture failed.") from exc


def render(directory: Path, *, out: Path | None = None,
           stills: str | list[float] | None = None, no_sfx: bool = False) -> Path | list[Path]:
    """Write a 1080 x 1920, 30 fps MP4, or sampled JPEGs in the story's stills folder."""
    directory = Path(directory).resolve()
    story = load(directory)
    timings = _timings(directory, story)
    samples = _samples(stills, timings["duration"])
    output = Path(out).resolve() if out is not None else directory / "story.mp4"
    if samples is not None and out is not None:
        raise StoryError("Use --stills by itself; JPEGs are written to the story's stills folder.")
    if samples is None:
        if output.suffix.lower() != ".mp4":
            raise StoryError("The story output file must end in .mp4.")
        try:
            with wave.open(str(directory / "narration.wav"), "rb") as audio:
                duration = audio.getnframes() / audio.getframerate()
        except (OSError, EOFError, wave.Error) as exc:
            raise StoryError("Cannot read narration.wav. Run 'zing story voice' first.") from exc
        if abs(duration - timings["duration"]) > .002:
            raise StoryError("narration.wav and timings.json have different durations. Run 'zing story voice' again.")
        output.parent.mkdir(parents=True, exist_ok=True)
    data = {"story": prepare(story, timings), "timings": timings,
            "base": directory.as_uri() + "/", "vocabulary": json.loads(data_path("vocabulary.json").read_text(encoding="utf-8"))}
    for ident, picture in data["story"].get("images", {}).items():
        try:
            prepared = local_photo(directory, picture["prepared"])
        except StoryError as exc:
            raise StoryError(f"image {ident}: {str(exc).replace('photo', 'image')}") from exc
        if not prepared.is_file():
            raise StoryError(f"Prepared image {ident} is missing. Run 'zing story images' first.")
    if samples is not None:
        data["stills"] = samples
    scratch_root = directory if samples is not None else output.parent
    try:
        encoder = ffmpeg() if samples is None else None
        with tempfile.TemporaryDirectory(prefix=".story-render-", dir=scratch_root) as temporary:
            scratch = Path(temporary)
            frames = scratch / "frames"
            audio_path = mix(directory, data["story"], timings, scratch, no_sfx=no_sfx) if samples is None else None
            capture(data, scratch, frames)
            if samples is not None:
                target = directory / "stills"
                target.mkdir(exist_ok=True)
                images = []
                for i in range(len(samples)):
                    image = target / f"{i + 1:05d}.jpg"
                    (frames / image.name).replace(image)
                    images.append(image)
                return images
            part = scratch / "story.mp4"
            run(encoder, "-v", "error", "-y", "-framerate", FPS, "-i", frames / "%05d.jpg",
                "-i", audio_path, "-map", "0:v", "-map", "1:a",
                "-t", timings["duration"], "-c:v", "libx264", "-preset", "medium", "-crf", 20,
                "-maxrate", "12M", "-bufsize", "24M", "-pix_fmt", "yuv420p", "-threads", 4,
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", part,
                capture_output=True)
            part.replace(output)
    except FactoryError as exc:
        raise StoryError(str(exc)) from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr
        raise StoryError(message or "Story encoding failed.") from exc
    return output
