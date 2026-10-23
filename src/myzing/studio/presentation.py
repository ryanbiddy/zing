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
    candidates = [r for r in rows if r["rendered"] and r["draft"] in DRAFTS and r["measurements"]]
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
    if answers.get("path") == "d":
        pass  # a style breakdown delivers no video, so resolution is not a delivery risk
    elif counts and answers.get("path") == "f":
        notes.append("Your video is " + ", ".join(f"{w}x{h}" for w, h in counts) + "; HD deliveries made from it can look soft.")
    elif counts:
        notes.append("Your clips include " + ", ".join(f"{n} at {w}x{h}" for (w, h), n in counts.items()) + "; HD versions can look soft.")
    warnings = result.get("warnings", [])
    joined = "\n".join(warnings).lower()
    categories = [
        (("crop-motion bound",), "A crop-motion check failed; this delivery used full-picture blurfill as a last resort."),
        (("blocked captions",), "Some requested spoken captions could not be made from valid timing. Review the speech before publishing."),
        (("phone captions need review",), "Some captions were reduced to fit safely. Check their readability on a phone."),
        (("detected faces do not fit", "measured subject does not fit"), "Some photos need a blurred background to keep faces and subjects inside the frame."),
        (("saliency/center fallback", "subject evidence has gaps"), "Some crops rely on estimated subject positions. Check that faces and important details stay visible."),
        (("exceeds 2.5x", "exceeds stated 2.5x"), "Some shots are enlarged more than 2.5x to fill the frame; check them for softness."),
    ]
    for needles, message in categories:
        if any(word in joined for word in needles):
            notes.append(message)
    shortages = [s for s in detail.get("shortages") or [] if isinstance(s, dict)]
    for message in reversed(list(dict.fromkeys(map(_shortage_note, shortages)))):
        notes.insert(0, message)
    if result.get("status") == "shortage" and not shortages:
        notes.insert(0, "Planning stopped before any draft was made. The full result names what is missing.")
    if detail.get("failures"):
        notes.insert(0, "Some drafts could not finish. Check their status in the table and the full result for the failure details."
                     if rows else "Studio stopped before any draft was made. The full result has the failure details.")
    if "stills" in detail:
        notes.append("Readability scores help with layout; you still need to judge the joke.")
    if not notes and any(r["rendered"] for r in rows):
        # Finished edits carry dozens of measurement disclaimers (color tags,
        # sampling limits); count them instead of listing engine jargon.
        notes = [f"{len(warnings)} detailed notes on measurement limits, color and framing are in the full result."] if warnings else []
    elif not notes:
        # Retain actionable unknowns without exposing producer identifiers,
        # internal field names or the pre-run planning caveats.
        notes = [w for w in warnings if not re.search(INTERNAL, w) and not w.startswith(PRE_RUN)][:5]
    actions = list(result.get("next_actions", []))
    if any(r["rendered"] and r["draft"] in DRAFTS for r in rows):
        chosen = chosen or next(r for r in rows if r["rendered"] and r["draft"] in DRAFTS)
        if chosen.get("plan"):
            actions = [f'Pick this draft: zing plan choose "{root}" --draft {chosen["draft"]} --draft-file "{chosen["plan"]}"',
                       "Want another shape? Run zing studio and choose 6, using the chosen plan.",
                       "Try another track: run zing studio and choose 5."]
    highlights = []
    for shape, still in detail.get("stills", {}).items():
        highlights.append({"label": f"Finished still ({shape})", "file": still["selected"]["path"]})
        highlights.append({"label": f"Contact sheet ({shape})", "file": still["concepts"]["contact_sheet"]})
    if detail.get("ok") and detail.get("card_json"):
        highlights = [{"label": label, "file": detail[key]} for key, label in
                      (("card_md", "Style card"), ("card_png", "Preview"), ("card_json", "Measured card"))
                      if detail.get(key)]
    if not rows and not highlights:
        highlights = [{"label": "Output", "file": p} for p in result.get("outputs", [])[:3]]
    return {"version": 1, "deliveries": rows, "recommendation": recommendation,
            "notes": list(dict.fromkeys(notes))[:5], "highlights": highlights,
            "style_summary": detail.get("summary", []) if detail.get("card_json") else [],
            "output_folder": str(root), "full_result": str(root / "studio-result.json"), "next_actions": actions}


DRAFTS = ("A", "B", "C")
# Producer IDs (asset_..., clip-3, text-0007, captions[3]), field paths and file
# names stay in the saved result, never in the five creator notes.
INTERNAL = r"asset_|studio_music_|\bclip-|\bshot-|\btext-\d|\bcaption-\d|\w\[\d+\]|saliency-|confidence|\binventory\.|\.json\b"
PRE_RUN = ("A/B/C can be blocked",)
LENGTH_SHORTAGES = {"target_length", "distinct_edits", "edit_constraints", "must_keep_length",
                    "must_keep_unavailable", "planner_capacity"}


def _shortage_note(shortage):
    """Name the producer's actual blocker; a missing study is not a length problem."""
    code = shortage.get("code")
    if code in LENGTH_SHORTAGES:
        return "There are not enough usable moments for the requested length. Add clips or shorten the edit."
    if code == "study_required":
        from .evidence import speech_model_note
        missing = speech_model_note()
        return ("None of your clips could be used: clips with speech need timed words from a local speech model, "
                "or measured silence. " + (
                    "Speech transcription is not installed; install myzing[study], then resume." if missing and "not installed" in missing else
                    missing.split(". ", 1)[0] + ". Download it once with zing study on one clip, "
                    "or set ZING_WHISPER_MODEL to a local model folder, then resume." if missing else
                    "Check the study warnings in the full result, then resume."))
    if code in {"audio_asset", "audio_placement", "music_analysis"}:
        return "A supplied music track could not be used. Check the track or choose original audio, then resume."
    text = " ".join(str(shortage.get(key, "")) for key in ("missing", "remedy"))
    return "Planning stopped: " + re.sub(r"\s*\(?\basset_[0-9a-f]+\)?", "", text).strip()


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
