"""Generated R13 before/after renders and measured LUT parity; no downloads."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def make_source(path, rgb=None):
    from myzing.color.media import run_media
    from myzing.color.science import np
    from tools.eval.color_fixture import chart

    rgb = chart(320, 180) if rgb is None else rgb
    h, w, _ = rgb.shape
    raw = np.rint(rgb * 255).astype(np.uint8).tobytes()
    run_media([
        "ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "rawvideo", "-pixel_format", "rgb24",
        "-video_size", f"{w}x{h}", "-framerate", "4", "-i", "pipe:0",
        "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,"
        "setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709",
        "-c:v", "ffv1", "-pix_fmt", "yuv420p", "-color_primaries", "bt709",
        "-color_trc", "bt709", "-colorspace", "bt709", str(path),
    ], data=raw * 8)
    return Path(path)


def decode(path, timestamp=.5, width=320, height=180):
    from myzing.color.media import run_media
    from myzing.color.science import np

    raw = run_media(["ffmpeg", "-v", "error", "-ss", str(timestamp), "-i", str(path),
                     "-map", "0:v:0", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"])
    return np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3).astype(float) / 255


def composition(source, color=None, *, width=320, height=180):
    from myzing.color.media import sha256
    from myzing.composition import AssetRef, Composition, CompositionClip
    from myzing.project.models import Rational

    return Composition(
        assets=[AssetRef("source", str(Path(source).resolve()), sha256(source))],
        clips=[CompositionClip(str(Path(source).resolve()), 0, 2, 0, id="clip", asset_id="source", color=color)],
        width=width, height=height, fps=Rational(12, 1),
    )


def color_transform(path, strength=1):
    from myzing.color import COLOR_SPACE
    from myzing.color.media import sha256
    from myzing.composition import ColorTransform

    return ColorTransform(str(Path(path).resolve()), sha256(path), strength, COLOR_SPACE)


def metrics(actual, expected):
    from myzing.color.science import delta_e_2000, np, rgb_to_lab

    # Fixed, evenly spaced native-resolution samples; no resize or color adjustment.
    a, b = actual[8:-8:8, 8:-8:8], expected[8:-8:8, 8:-8:8]
    error = np.abs(actual - expected) * 255
    return {
        "median_delta_e_2000": float(np.median(delta_e_2000(rgb_to_lab(a), rgb_to_lab(b)))),
        "mean_code_error": float(error.mean()), "p99_code_error": float(np.percentile(error, 99)),
        "black_fraction": float(np.mean(np.any(actual <= 1 / 255, axis=-1))),
        "white_fraction": float(np.mean(np.any(actual >= 254 / 255, axis=-1))),
    }


def main(argv=None):
    from myzing.color.cube import apply_cube, make_cube, read_cube, write_cube
    from myzing.color.looks import transform_for
    from myzing.render import render_composition

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = make_source(out / "source.mkv")
    lut = write_cube(make_cube(transform_for("teal-orange")), out / "teal-orange.cube")
    for name, color in (("before", None), ("after", color_transform(lut))):
        plan = composition(source, color)
        (out / f"{name}.json").write_text(plan.to_json(), encoding="utf-8")
        render_composition(plan, out / f"{name}.mp4", work_dir=out / f"{name}-work")
    result = metrics(decode(out / "after.mp4"), apply_cube(decode(source), read_cube(lut)))
    result.update({"fixture": "original generated SDR chart, MIT; 320x180, 2 seconds",
                   "median_delta_e_2000_limit": 2, "look": "teal-orange", "strength": 1})
    (out / "metrics.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    assert result["median_delta_e_2000"] <= 2


if __name__ == "__main__":
    main()
