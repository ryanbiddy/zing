"""Creator-facing summaries; full measurements remain in the saved result."""

from collections import Counter
from pathlib import Path
import re

from .models import read_json


def progress_label(text, answers):
    key, _, state = text.partition(": ")
    if not state:
        return text
    if state not in {"starting", "done", "cached", "reused"}:
        return "Checking the edit" if "asset_" in text else text
    if state == "done" and not key.startswith("decode-"):
        return None
    if key.startswith(("study-asset_", "audio-asset_", "color-asset_")):
        try:
            assets = read_json(Path(answers["project"]) / "project.json")["assets"]
            videos = [a for a in assets if a.get("probe", {}).get("width")]
            asset = next(a for a in videos if a["id"] == key.split("-", 1)[1])
            verb = {"study": "Studying", "audio": "Checking audio in", "color": "Checking color in"}[key.split("-", 1)[0]]
            return f"{verb} {Path(asset['path']).name} ({videos.index(asset) + 1} of {len(videos)})"
        except (OSError, ValueError, KeyError, StopIteration):
            return "Studying your clips"
    match = re.fullmatch(r"(plan|render|decode|restudy|inspect|color-report|report)-([ABC])\.(16x9|1x1|9x16)", key)
    if match:
        phase, draft, shape = match.groups()
        shape = shape.replace("x", ":")
        aspects = answers.get("aspects", [shape])
        index = "ABC".index(draft) * len(aspects) + aspects.index(shape) + 1
        verb = {"plan": "Preparing", "render": "Rendering", "decode": "Checking playback of", "restudy": "Measuring",
                "inspect": "Making a preview of", "color-report": "Checking color in", "report": "Comparing"}[phase]
        if phase == "decode" and state == "done":
            verb = "Playback checked for"
        return f"{verb} draft {draft}, {shape} ({index} of {3 * len(aspects)})"
    labels = {"project-scan": "Checking your clips", "reference-resolve": "Opening the reference",
              "reference-study": "Studying the reference", "reference-audio": "Checking reference audio",
              "style-recipe": "Describing the reference style", "brief": "Saving your creative choices",
              "director": "Planning three edits"}
    if key.startswith("aspects-"):
        return f"Planning shapes for draft {key[-1]}"
    return labels.get(key, "Checking the edit")


def creator_summary(result, answers, facts):
    detail = result.get("result", {})
    root = Path(result["project"])
    rows = []
    for key, row in detail.get("drafts", {}).items():
        label, _, shape = key.partition(".")
        rows.append(_row(label, shape.replace("x", ":"), row))
    if not rows:
        for label, value in detail.get("deliveries", {}).items():
            if "deliveries" in value:
                rows.extend(_row(label, shape, row) for shape, row in value["deliveries"].items())
            elif isinstance(value, dict) and value.get("video"):
                rows.append(_row("Edit", label, value))
    recommendation = None
    chosen = None
    candidates = [r for r in rows if r["rendered"] and r["draft"] in "ABC" and r["measurements"]]
    if candidates:
        def rank(row):
            values = list(row["measurements"].values())
            return (values.count("miss"), -values.count("pass"))
        best_rank = min(map(rank, candidates))
        best = [r for r in candidates if rank(r) == best_rank]
        preferred = answers.get("aspects", ["16:9"])[0]
        chosen = next((r for r in best if r["shape"] == preferred), best[0])
        passed = [k.replace("_", " ") for k, v in chosen["measurements"].items() if v == "pass"]
        tied = len({r["draft"] for r in best}) > 1
        recommendation = ("No draft is clearly better on the measured checks. " if tied else "")
        recommendation += f"Start with draft {chosen['draft']} ({chosen['shape']}) because "
        recommendation += (f"it passes {', '.join(passed[:3])}" if passed else "it has the fewest measured style misses")
        noun = "miss" if best_rank[0] == 1 else "misses"
        recommendation += f" ({best_rank[0]} measured {noun}). Unverified checks are not passes; watch it before choosing."
    elif any(r["rendered"] for r in rows):
        recommendation = "Start with the rendered delivery and review the crop; no measured comparison establishes a better draft."
    notes = []
    counts = Counter((c["width"], c["height"]) for c in facts.get("clips", []) if min(c["width"], c["height"]) < 1080)
    if counts:
        notes.append("Your clips include " + ", ".join(f"{n} at {w}x{h}" for (w, h), n in counts.items()) + "; HD versions can look soft.")
    warnings = result.get("warnings", [])
    joined = "\n".join(warnings).lower()
    categories = [
        (("crop-motion bound",), "A crop-motion check failed; this delivery used full-picture blurfill as a last resort."),
        (("blocked captions",), "Some requested spoken captions could not be made from valid timing. Review the speech before publishing."),
        (("phone captions need review",), "Some captions were reduced to fit safely. Check their readability on a phone."),
        (("detected faces do not fit", "measured subject does not fit"), "Some photos need a blurred background to keep faces and subjects inside the frame."),
        (("saliency/center fallback", "subject evidence has gaps"), "Some crops rely on estimated subject positions. Check that faces and important details stay visible."),
    ]
    for needles, message in categories:
        if any(word in joined for word in needles):
            notes.append(message)
    if detail.get("shortages") or result.get("status") == "shortage":
        notes.insert(0, "There are not enough usable moments for the requested length. Add clips or shorten the edit.")
    if detail.get("failures"):
        notes.insert(0, "Some drafts could not finish. Check their status below and the full result for the failure details.")
    if "stills" in detail:
        notes.append("Readability scores help with layout; you still need to judge the joke.")
    if not notes:
        # Retain actionable unknowns without exposing producer identifiers.
        notes = [w for w in warnings if not re.search(r"asset_|clip-|shot-|saliency-|confidence", w)][:5]
    actions = list(result.get("next_actions", []))
    if any(r["rendered"] and r["draft"] in "ABC" for r in rows):
        chosen = chosen or next(r for r in rows if r["rendered"] and r["draft"] in "ABC")
        if chosen.get("plan"):
            actions = [f'Pick this draft: zing plan choose "{root}" --draft {chosen["draft"]} --draft-file "{chosen["plan"]}"',
                       "Want another shape? Run zing studio and choose 6, using the chosen plan.",
                       "Try another track: run zing studio and choose 5."]
    highlights = []
    for shape, still in detail.get("stills", {}).items():
        highlights.append({"label": f"Finished still ({shape})", "file": still["selected"]["path"]})
        highlights.append({"label": f"Contact sheet ({shape})", "file": still["concepts"]["contact_sheet"]})
    if not rows and not highlights:
        highlights = [{"label": "Output", "file": p} for p in result.get("outputs", [])[:3]]
    return {"version": 1, "deliveries": rows, "recommendation": recommendation,
            "notes": list(dict.fromkeys(notes))[:5], "highlights": highlights,
            "output_folder": str(root), "full_result": str(root / "studio-result.json"), "next_actions": actions}


def _row(draft, shape, row):
    measurements = {k: v.get("status", "unverified") for k, v in row.get("dimensions", {}).items() if isinstance(v, dict)}
    misses = [k.replace("_", " ") for k, v in measurements.items() if v == "miss"]
    unknown = any(v != "pass" for v in measurements.values()) or not measurements
    status = "style match failed: " + ", ".join(misses) if misses else "unverified" if unknown else "rendered"
    video = row.get("video")
    if not video or row.get("status", "ready") != "ready":
        status = "render failed"
    return {"draft": draft, "shape": shape, "file": video, "plan": row.get("plan"),
            "status": status, "rendered": bool(video) and status != "render failed", "measurements": measurements}
