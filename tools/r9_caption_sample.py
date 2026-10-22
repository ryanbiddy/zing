"""Generate an offline R9 caption sample and its contact sheet using OFL fonts."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
from pathlib import Path

from myzing.composition import AssetRef, CaptionStyle, Composition, CompositionCaption, CompositionClip, FontAsset
from myzing.layout.types import Box, EventLayout, Keyframe, OverlapCheck
from myzing.render import render_composition
from myzing.schemas import Word

ROOT = Path(__file__).resolve().parents[1]


def generate(root: Path) -> Path:
    root = root.resolve()
    assets = root / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    fonts = ROOT / "src/myzing/_data/fonts"
    for name in ("Anton-Regular.ttf", "Anton-OFL.txt", "IBMPlexSans.ttf", "IBMPlexSans-OFL.txt"):
        shutil.copyfile(fonts / name, assets / name)
    source = assets / "generated-background.mp4"
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
        "color=c=0x101624:s=960x540:r=30:d=4.8", "-vf", "drawgrid=w=120:h=90:t=1:c=0x23304a",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
    ], check=True, timeout=60)

    def font(name):
        return FontAsset(f"assets/{name}", hashlib.sha256((assets / name).read_bytes()).hexdigest(), "OFL-1.1")

    static = CompositionCaption(
        "WORDS LAND HERE", .2, 1.9, id="positioned", all_caps=True,
        words=[Word("WORDS", .2, .7), Word("LAND", .7, 1.2), Word("HERE", 1.2, 1.9)],
        font=font("Anton-Regular.ttf"), style=CaptionStyle(54, color="#DCE6F5", highlight="#F4DD55", outline_color="#101624", outline_width=2),
        layout=EventLayout("positioned", .2, 1.9, "fixture-position", OverlapCheck(True), box=Box(.1, .14, .8, .25)),
    )
    moving = CompositionCaption(
        "AND FOLLOW THIS PATH", 1.9, 4.8, id="moving",
        words=[Word("AND", 1.9, 2.4), Word("FOLLOW", 2.4, 3.2),
               Word("THIS", 3.2, 3.9, timing={"version": 1, "status": "corrected", "method": "user_correction",
                    "original": {"start": 3.2, "end": 3.2}, "adjustments": []}), Word("PATH", 3.9, 4.8)],
        font=font("IBMPlexSans.ttf"), style=CaptionStyle(38, color="#DCE6F5", highlight="#78EFBD", outline_color="#182239", outline_width=1, box_color="#182239"),
        layout=EventLayout("moving", 1.9, 4.8, "explicit-path", OverlapCheck(True), path=[
            Keyframe(1.9, Box(.05, .62, .65, .2)), Keyframe(2.9, Box(.3, .27, .65, .2)),
            Keyframe(3.9, Box(.05, .4, .65, .2)), Keyframe(4.8, Box(.2, .65, .65, .2)),
        ]),
    )
    c = Composition(
        assets=[AssetRef("background", "assets/generated-background.mp4", hashlib.sha256(source.read_bytes()).hexdigest())],
        clips=[CompositionClip("assets/generated-background.mp4", 0, 4.8, 0, id="clip", asset_id="background")],
        captions=[static, moving], width=960, height=540,
    )
    (root / "composition.json").write_text(c.to_json(indent=2) + "\n", encoding="utf-8", newline="\n")
    result = render_composition(c, root / "positioned-word-captions.mp4", base_dir=root, work_dir=root / "render-work")
    subprocess.run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(result.output_path), "-vf",
        "select='gte(n,9)*not(mod(n-9,12))',scale=480:270,tile=4x3:padding=6:margin=6:color=0x101624",
        "-frames:v", "1", str(root / "contact-sheet.png"),
    ], check=True, timeout=60)
    return result.output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "zing-workspace/r9-render")
    print(generate(parser.parse_args().out))
