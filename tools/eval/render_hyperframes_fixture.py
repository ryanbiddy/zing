"""Generate a graded dissolve with mixed caption backends; no downloads.

Run: python -m tools.eval.render_hyperframes_fixture --out zing-workspace/p10b-sample
Requires the installed HyperFrames sidecar and HYPERFRAMES_BROWSER_PATH.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess

from myzing.composition import (
    AssetRef, CaptionStyle, ColorTransform, Composition, CompositionCaption,
    CompositionClip, FontAsset, SourceRange, Transition, TransitionRecipe,
)
from myzing.layout.types import Box, EventLayout, OverlapCheck
from myzing.project.models import Rational
from myzing.render import render_composition
from myzing.schemas import Word


def run(args, **kwargs):
    result = subprocess.run(["ffmpeg", "-v", "error", "-y", *map(str, args)],
                            capture_output=True, timeout=120, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace"))
    return result.stdout


def fixture(directory: Path, fps: Rational = Rational(30, 1), *, width=640, height=360) -> Composition:
    directory.mkdir(parents=True, exist_ok=True)
    rate = f"{fps.numerator}/{fps.denominator}"
    step = fps.denominator / fps.numerator
    assets, clips = [], []
    cube = directory / "channel-swap.cube"
    cube.write_text("LUT_3D_SIZE 2\n" + "".join(f"{g} {b} {r}\n" for b in (0, 1) for g in (0, 1) for r in (0, 1)), encoding="utf-8")
    grade = ColorTransform(str(cube), hashlib.sha256(cube.read_bytes()).hexdigest(), 1, "bt709")
    for i, color in enumerate(("0x263F69", "0x7B4628")):
        path = directory / f"source-{i}.mov"
        run(["-f", "lavfi", "-i", f"color=c={color}:s={width}x{height}:r={rate},format=rgb24",
             "-f", "lavfi", "-i", f"sine=frequency={330 + 220 * i}:sample_rate=48000:duration=2",
             "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,"
             "setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709",
             "-frames:v", "42", "-t", str(42 * step), "-c:v", "libx264", "-crf", "12",
             "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
             "-c:a", "pcm_s16le", path])
        assets.append(AssetRef(f"asset-{i}", str(path), hashlib.sha256(path.read_bytes()).hexdigest()))
        clips.append(CompositionClip(str(path), 0, 42 * step, i * 30 * step,
                                     id=f"clip-{i}", asset_id=f"asset-{i}", color=grade))
    transition = Transition("dissolve", "clip-0", "clip-1", 30 * step, 42 * step,
                            TransitionRecipe("dissolve", 12 * step, "generated P10b fixture"),
                            SourceRange(30 * step, 42 * step), SourceRange(0, 12 * step))
    font = Path(__file__).resolve().parents[2] / "src/myzing/_data/fonts/Anton-Regular.ttf"
    font_asset = FontAsset(str(font), hashlib.sha256(font.read_bytes()).hexdigest(), "OFL-1.1")
    events = []
    for backend, text, box, size in (
        ("hyperframes", "MOVE WITH COLOR", Box(.1, .23, .8, .45), width * .065),
        ("ass", "ASS stays above the grade", Box(.08, .76, .84, .15), width * .038),
    ):
        start, end = 6 * step, 66 * step
        events.append(CompositionCaption(
            id=backend, text=text, start=start, end=end, all_caps=False,
            word_timed=backend == "hyperframes",
            words=[Word(word, (6 + 20 * n) * step, (26 + 20 * n) * step)
                   for n, word in enumerate(text.split())] if backend == "hyperframes" else [],
            font=font_asset, style=CaptionStyle(size, outline_width=0, highlight="#F0C040"),
            layout=EventLayout(backend, start, end, "generated safe box", OverlapCheck(True), box=box),
            backend=backend, template="kinetic" if backend == "hyperframes" else None,
        ))
    return Composition(assets=assets, clips=clips, transitions=[transition], captions=events,
                       width=width, height=height, fps=fps)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    directory = args.out.resolve()
    c = fixture(directory / "assets")
    (directory / "composition.json").write_text(c.to_json(indent=2) + "\n", encoding="utf-8")
    result = render_composition(c, directory / "mixed-captions.mp4", work_dir=directory / "render-work")
    run(["-i", result.output_path, "-vf", "select='eq(n,12)+eq(n,30)+eq(n,36)+eq(n,42)+eq(n,54)+eq(n,69)',"
         "scale=480:270,tile=3x2", "-frames:v", "1", directory / "contact-sheet.png"])
    print(result.output_path)


if __name__ == "__main__":
    main()
