"""Short editing actions from the comparison's measured values."""

ORDER = {"differs": 0, "unknown": 1, "close": 2}
METRICS = {
    "median_shot_seconds": ("Median shot", "s"),
    "face_height_percent": ("Face height", "%"),
    "aspect": ("Frame aspect", "width/height"),
    "lufs": ("Loudness", "LUFS"),
    "speech_share": ("Speech share", "%"),
    "bpm": ("Tempo", "BPM"),
    "placement": ("Caption box", "% of frame"),
    "luma": ("Luma percentiles", "on a 0-1 scale"),
}


def _value(value, unit):
    if value is None:
        return "unknown"
    if isinstance(value, list):
        number = "[" + ", ".join(f"{n:.3g}" for n in value) + "]"
    else:
        number = f"{value:.3g}"
    return number + ("" if unit == "%" else " ") + unit


def _action(name, a, b):
    if name == "median_shot_seconds":
        return f"Cut about every {a:.1f} s (yours every {b:.1f} s)."
    if name == "face_height_percent":
        move = "Punch in" if a > b else "Widen the framing"
        return f"{move} so the face fills about {a:.0f}% of the height (yours {b:.0f}%)."
    if name == "aspect":
        return f"Set the frame width to about {a:.3g} times its height."
    if name == "lufs":
        direction = "down" if a < b else "up"
        return f"Bring loudness {direction} about {abs(a-b):.1f} dB to {a:.1f} LUFS."
    if name == "speech_share":
        return f"Aim for speech in about {a:.0f}% of the clip (yours {b:.0f}%)."
    if name == "bpm":
        return f"Use a tempo near {a:.0f} BPM (yours {b:.0f} BPM)."
    if name == "placement":
        y, other_y = (a[1]+a[3])/2, (b[1]+b[3])/2
        if abs(y - other_y) > 5:
            return f"Move captions {'down' if y > other_y else 'up'} to about {y:.0f}% of the height."
        return f"Match the caption box width, about {a[2]-a[0]:.0f}% of the frame (yours {b[2]-b[0]:.0f}%)."
    if name == "luma":
        return "Match the reference's measured brightness range."
    return f"Aim for about {a:.0f} {name.replace('_', ' ')}s per minute (yours {b:.0f})."


def comparison_summary(comparison):
    rows = []
    for section, result in comparison["sections"].items():
        metrics = result["metrics"]
        verdict = result["status"]
        if not metrics:
            numbers = result.get("reason", "Required measurements are unknown.")
            if verdict == "unknown":
                numbers = "Transition rates unknown in one or both videos."
            else:
                numbers = numbers[:1].upper() + numbers[1:]
            action = "Measure transitions in both videos before changing them." if verdict == "unknown" else "No change needed in detected transitions."
        else:
            name = min(metrics, key=lambda key: (ORDER[metrics[key]["status"]],
                       list(METRICS).index(key) if key in METRICS else len(METRICS)))
            metric = metrics[name]
            label, unit = METRICS.get(name, (name.replace("_", " ").capitalize() + " rate", "per minute"))
            a, b = metric.get("target"), metric.get("observed")
            if name == "speech_share":
                a, b = (v * 100 if v is not None else None for v in (a, b))
            elif name == "placement":
                a, b = ([v * 100 for v in box["box"]] if box else None
                        for box in (metric.get("target_box"), metric.get("observed_box")))
            if name == "placement" and a is not None and b is not None:
                numbers = f"Captions sit {(a[1]+a[3])/2:.0f}% down in the reference, {(b[1]+b[3])/2:.0f}% down in yours."
            elif name == "luma":
                gap = metric.get("max_delta")
                numbers = ("Brightness range unknown." if gap is None else
                           f"Brightness range within {gap:.2f} of the reference." if verdict == "close" else
                           f"Brightness range differs by up to {gap:.2f}.")
            else:
                numbers = f"{label} {_value(a, unit)} reference vs {_value(b, unit)} yours."
            missing = [METRICS.get(key, (key.replace("_", " "), ""))[0].lower()
                       for key, value in metrics.items() if key != name and value["status"] == "unknown"]
            if missing:
                numbers += " Unknown " + ", ".join(missing) + "."
            if verdict == "unknown" or a is None or b is None:
                action = f"Measure {label.lower()} in both videos before changing it."
                if a is not None and b is not None:
                    action = metric.get("reason") or action
            elif verdict == "close":
                action = "No change needed in these measurements."
            else:
                action = _action(name, a, b)
        rows.append({"section": section, "verdict": verdict, "numbers": numbers, "action": action})
    return sorted(rows, key=lambda row: ORDER[row["verdict"]])[:6]


def summary_text(row):
    return f"{row['section'].capitalize()}: {row['verdict']}. {row['numbers']} {row['action']}"
