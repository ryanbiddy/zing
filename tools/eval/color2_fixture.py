"""Original COLOR2 calibration cases; arrays also run in CI without FFmpeg."""


def cases():
    from myzing.color.science import np
    from myzing.color.looks import apply_transform, transform_for
    from tools.eval.color_fixture import chart
    rgb = .12 + .72 * chart()
    weights = np.array([.2126, .7152, .0722])
    y = rgb @ weights
    blue = np.array([0., 0., .12])
    green = np.array([0., .105, 0.])
    # Subtract equal code values from all channels to preserve encoded Y'
    # exactly. The bounded chart leaves headroom; these cases do not clip.
    blue -= blue @ weights
    green -= green @ weights
    return rgb, {
        "same": (rgb.copy(), "pass"),
        "brightness-5-percent": (rgb * 1.05, "pass"),
        "equal-luma-blue": (rgb + blue, "miss"),
        "equal-luma-green": (rgb + green, "miss"),
        "desaturated": (y[..., None] + .35 * (rgb-y[..., None]), "miss"),
        "contrast-1.4": (np.clip((rgb-.5)*1.4+.5, 0, 1), "miss"),
        "teal-orange": (apply_transform(rgb, transform_for("teal-orange", 1)), "miss"),
        "borderline-blue": (rgb + .35*blue, "approximate"),
    }


def measurement(rgb):
    from myzing.color.stats import statistics
    return {"aggregate": statistics(rgb).to_dict(), "confidence": .85,
            "coverage": {"usable_samples": 4, "sample_fraction": 1}}


def main():
    import argparse
    import json
    from pathlib import Path
    from myzing.color.measure import measure_video
    from myzing.match.color import compare_color
    from tools.eval.color_fixture import make_video
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    rgb, variants = cases()
    make_video(args.out / "reference.mkv", rgb)
    target = measure_video(args.out / "reference.mkv", count=4)[0].to_dict()
    results = {}
    for name, (pixels, expected) in variants.items():
        path = args.out / (name + ".mkv")
        make_video(path, pixels)
        result = compare_color(target, measure_video(path, count=4)[0].to_dict())
        results[name] = {"expected": expected, **result}
        assert result["status"] == expected, (name, result)
    (args.out / "calibration.json").write_text(json.dumps(results, indent=2)+"\n", encoding="utf-8")
    for name, result in results.items():
        print(name, result["status"], result["reason"])


if __name__ == "__main__":
    main()
