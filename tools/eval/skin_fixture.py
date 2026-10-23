"""Original skin-preservation calibration: Zing's looks versus green/magenta casts.

Every case grades a face patch and compares it with the SAME patch ungraded;
no case compares one skin tone with another. Run:
python -m tools.eval.skin_fixture --out zing-workspace/skin-calibration
No downloaded fixtures, model weights, assets or network calls.
"""

from __future__ import annotations

# Approximate CIELAB face colors: six tones from very light to very deep under
# neutral light (calibration claims are made on these), plus lighting variants
# that real footage contains. Values are generated, not measured from people.
SKIN_TONES = {
    "very-light": (70, 9, 15), "light": (65, 11, 17), "medium": (58, 12, 20),
    "tan": (50, 13, 22), "deep": (40, 13, 20), "very-deep": (30, 9, 13),
}
LIT_VARIANTS = {"pink-lit": (60, 19, 3), "tungsten": (60, 15, 30), "faded-film": (55, 3, 5)}


def lab_to_rgb(lab):
    from myzing.color.science import encode, np
    lightness, a, b = lab
    fy = (lightness + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200
    d = 6 / 29
    f = lambda t: t ** 3 if t > d else 3 * d * d * (t - 4 / 29)  # noqa: E731
    xyz = np.array([f(fx) * 0.95047, f(fy), f(fz) * 1.08883])
    matrix = np.array([[0.4124564, 0.3575761, 0.1804375],
                       [0.2126729, 0.7151522, 0.0721750],
                       [0.0193339, 0.1191920, 0.9503041]])
    return np.clip(encode(np.linalg.solve(matrix, xyz)), 0, 1)


def patch(lab, size=20, seed=0):
    """A size x size face patch with mild deterministic texture."""
    from myzing.color.science import np
    rng = np.random.default_rng(seed)
    return np.clip(lab_to_rgb(lab) + rng.normal(0, .015, (size, size, 3)), 0, 1)


def grades():
    """name -> (pixel function, expectation on SKIN_TONES).

    "pass"/"approximate": the worst status any of the six tones may reach.
    "miss": every one of the six tones must miss.
    """
    from myzing.color.cube import apply_cube, make_cube
    from myzing.color.looks import look_bank, transform_for
    from myzing.color.science import encode, linearize, np

    def cube(transform):
        table = make_cube(transform)
        return lambda px: apply_cube(px, table)

    def shift(values):
        return lambda px: np.clip(px + values, 0, 1)

    def gain(values):
        return lambda px: np.clip(encode(linearize(px) * values), 0, 1)

    cases = {f"look {name} @1": (cube(transform_for(name, 1)), "pass") for name in look_bank()}
    # Teal shadows at full strength tint the deepest skin; review, not a miss.
    cases["look teal-orange @1"] = (cases["look teal-orange @1"][0], "approximate")
    for name, kwargs in {"tint +0.06": {"tint": .06}, "tint -0.06": {"tint": -.06},
                         "temperature +0.06": {"temperature": .06}, "temperature -0.06": {"temperature": -.06},
                         "exposure +0.5": {"exposure_ev": .5}}.items():
        cases[f"correction {name}"] = (cube(transform_for("neutral", 0, **kwargs)), "pass")
    cases["teal-orange @1 + tint +0.06"] = (cube(transform_for("teal-orange", 1, tint=.06)), "approximate")
    cases["green code shift (+0.014 G, -0.035 R/B)"] = (shift([-.035, .014, -.035686]), "miss")
    cases["green gain x1.2 linear"] = (gain([.95, 1.2, .95]), "miss")
    cases["magenta code shift (-0.02 G, +0.05 R/B)"] = (shift([.05, -.02, .05]), "miss")
    return cases


def calibrate():
    from myzing.match.skin import compare_face
    rows = {}
    for name, (function, allowed) in grades().items():
        faces = {tone: compare_face(patch(lab).reshape(-1, 3), function) for tone, lab in {**SKIN_TONES, **LIT_VARIANTS}.items()}
        rows[name] = {"allowed_on_skin_tones": allowed,
                      "faces": {tone: {k: face[k] for k in ("shift", "toward_green", "toward_magenta", "status",
                                                             "a_delta", "b_delta", "hue_delta")}
                                for tone, face in faces.items()}}
    return rows


def main(argv=None):
    import argparse
    import json
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    rows = calibrate()
    (args.out / "skin-calibration.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    tones = list(SKIN_TONES) + list(LIT_VARIANTS)
    print(f"{'grade':42s} " + " ".join(f"{t:>10s}" for t in tones))
    for name, row in rows.items():
        print(f"{name:42s} " + " ".join(f"{row['faces'][t]['shift']:6.1f} {row['faces'][t]['status'][0]}  " for t in tones))


if __name__ == "__main__":
    main()
