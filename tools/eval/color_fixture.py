"""Original deterministic SDR chart and paired color acceptance evidence.

Run: python -m tools.eval.color_fixture --out zing-workspace/color-demo
No downloaded fixtures, model weights, assets, or network calls.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def chart(width=160, height=120):
    from myzing.color.science import np
    # A smooth RGB field plus a neutral ramp and distinct color patches.
    x, y = np.meshgrid(np.linspace(0.08, 0.92, width), np.linspace(0.08, 0.92, height))
    rgb = np.stack((x, y, 0.10 + 0.75 * (0.5 + 0.5 * np.sin(8 * x + 3 * y))), axis=-1)
    rgb[:height // 5] = np.linspace(0.04, 0.96, width)[None, :, None]
    return rgb


def make_video(path, rgb):
    from myzing.color.media import run_media
    from myzing.color.science import np
    h, w, _ = rgb.shape
    raw = np.rint(rgb * 255).astype(np.uint8).tobytes()
    run_media([
        "ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "rawvideo",
        "-pixel_format", "rgb24", "-video_size", f"{w}x{h}", "-framerate", "4",
        "-i", "pipe:0", "-c:v", "ffv1", "-pix_fmt", "bgr0",
        "-vf", "setparams=color_primaries=bt709:color_trc=iec61966-2-1:colorspace=gbr",
        "-color_primaries", "bt709", "-color_trc", "iec61966-2-1", "-colorspace", "rgb",
        str(path),
    ], data=raw * 8)


def main(argv=None):
    from myzing.color.api import match_video
    from myzing.color.cube import apply_cube, read_cube
    from myzing.color.looks import apply_transform, transform_for
    from myzing.color.media import apply_video, frame
    from myzing.color.science import delta_e_2000, np, rgb_to_lab

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    source = args.out / "clip.mkv"
    reference = args.out / "reference.mkv"
    rgb = chart()
    expected = apply_transform(rgb, transform_for("teal-orange", 0.87))
    make_video(source, rgb)
    make_video(reference, expected)
    recipe = match_video(str(reference), source, args.out / "match", samples=4)
    apply_video(recipe.cube_path, source, args.out / "graded.mp4")
    before = frame(source, 0.5, 160, 120)
    target = frame(reference, 0.5, 160, 120)
    after = frame(args.out / "graded.mp4", 0.5, 160, 120)
    cube_after = apply_cube(before, read_cube(recipe.cube_path))
    metrics = {
        "fixture": "original procedural chart; MIT; 160x120 RGB FFV1, 8 frames at 4 fps",
        "known_look": "teal-orange", "known_strength": 0.87,
        "chosen": recipe.match.chosen.transform.to_dict(),
        "strength_tolerance": 0.08,
        "median_delta_e_2000_before": float(np.median(delta_e_2000(rgb_to_lab(before), rgb_to_lab(target)))),
        "median_delta_e_2000_cube": float(np.median(delta_e_2000(rgb_to_lab(cube_after), rgb_to_lab(target)))),
        "median_delta_e_2000_rendered": float(np.median(delta_e_2000(rgb_to_lab(after), rgb_to_lab(target)))),
        "gate_maximum": 3.0,
        "reference_sha256": recipe.reference.sha256,
        "clip_sha256": recipe.clip.sha256,
        "cube_sha256": recipe.cube_sha256,
        "preview_path": recipe.preview_path,
        "clip_clipping": recipe.clip.aggregate.clipping,
        "reference_clipping": recipe.reference.aggregate.clipping,
        "graded_clipping": recipe.graded_stats.clipping,
    }
    (args.out / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    assert recipe.match.chosen.transform.look == "teal-orange"
    assert abs(recipe.match.chosen.transform.strength - 0.87) <= 0.08
    assert metrics["median_delta_e_2000_before"] > 3
    assert metrics["median_delta_e_2000_rendered"] <= 3


if __name__ == "__main__":
    main()
