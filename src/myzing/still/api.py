"""Offline still workflow shared by the CLI and MCP."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path

from myzing.memes import MemeError
from myzing.memes.ideas import HONESTY, generate_ideas, photo_facts
from myzing.memes.render import ASPECTS, render_meme, require_pillow, resolve_font, wrap_text
from myzing.memes.score import idea_score
from myzing.memes.subject import user_boxes
from myzing.memes.templates import get_template
from myzing.memes.validate import check_texts
from myzing.project.api import hash_file
from myzing.prompt_pack import load_prompt, parse_frontmatter
from .inventory import inventory, local_path, open_photo
from .models import Concept, Photo, StillIndex
from .placement import FIT_REQUESTS, LAYOUTS, frame, place, safe_geometry

MAX_CONCEPTS = 8
MAX_JSON_BYTES = 2 * 1024 * 1024


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def _read_json(path: Path):
    if not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
        raise MemeError(f"JSON file is missing or exceeds 2 MiB: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, RecursionError) as exc:
        raise MemeError(f"Invalid JSON at {path}: {exc}") from exc


def _save_index(root: Path, index: StillIndex):
    target = root / "index.json"
    if target.is_symlink():
        raise MemeError("index.json must be a regular file, not a symlink.")
    fd, name = tempfile.mkstemp(prefix=".index-", suffix=".tmp", dir=root)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(_json(index.to_dict()))
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _validate(texts, count=None) -> list[str]:
    result = check_texts(texts, box_count=count)
    if not result["valid"]:
        raise MemeError(" ".join(p["message"] for p in result["problems"]))
    return result["texts"]


def _text_key(texts: list[str]) -> str:
    return " ".join(" ".join(texts).split()).casefold()


def _concept_id(topic: str, digest: str, texts: list[str], aspect: str,
                layout: str, regions: list[list[float]] | None,
                fit: str = "contain", focus: list[float] | None = None) -> str:
    # Legacy contain concepts keep their original IDs.
    framing = [] if fit == "contain" else [fit, focus]
    value = _json([topic, digest, texts, aspect, layout, regions, *framing]).encode("utf-8")
    return "still-" + hashlib.sha256(value).hexdigest()[:16]


def _import_lines(lines: str | Path, photos: list[Photo]) -> list[tuple[Photo, dict]]:
    data = _read_json(local_path(lines))
    ideas = data.get("ideas") if isinstance(data, dict) else data
    if not isinstance(ideas, list) or not 1 <= len(ideas) <= MAX_CONCEPTS:
        raise MemeError("--lines needs an array, or {\"ideas\": [...]}, with 1-8 ideas.")
    result = []
    for i, idea in enumerate(ideas):
        if not isinstance(idea, dict):
            raise MemeError("Each imported idea must be an object with texts and an optional photo id/name.")
        selected = photos[i % len(photos)]
        if "photo" in idea:
            selected = next((p for p in photos if idea["photo"] in (p.id, Path(p.path).name)), None)
            if selected is None:
                raise MemeError(f"Unknown photo {idea['photo']!r}; use an id or filename from this inventory.")
        for field in ("title", "why", "template"):
            if field in idea and (not isinstance(idea[field], str) or len(idea[field]) > 2000):
                raise MemeError(f"Idea {field} must be a string of at most 2000 characters.")
        result.append((selected, {**idea, "provider": "imported_lines"}))
    return result


def _offline(topic: str, photos: list[Photo], n: int, layout: str = "auto") -> list[tuple[Photo, dict]]:
    # Each photo's measured facts (faces, OCR text, color, light, subject
    # position) add photo-specific formulas ahead of the topic formulas.
    pools = [generate_ideas(topic, n=8, seed=p.sha256, photo=p) for p in photos]
    if layout not in ("auto", "labels"):
        # Subject-label ideas carry regions, which only the labels layout uses.
        pools = [[{k: v for k, v in idea.items() if k != "regions"} for idea in pool] for pool in pools]
    seen, selected = set(), []
    # Round robin across photos, exhausting distinct formulas before reusing text.
    while len(selected) < n:
        progressed = False
        for photo, pool in zip(photos, pools):
            for idea in pool:
                key = _text_key(idea["texts"])
                if key not in seen and idea["validation"]["valid"]:
                    seen.add(key)
                    selected.append((photo, idea))
                    progressed = True
                    break
            if len(selected) == n:
                break
        if not progressed:
            raise MemeError("Not enough distinct valid offline concepts for this topic; lower --n or supply --lines.")
    return selected


def writer_prompt(topic: str, photos: list[Photo], n: int) -> str:
    loaded = load_prompt("meme-writer")
    if loaded is None:
        raise MemeError("The meme-writer prompt is missing; reinstall Zing or fix ZING_PROMPTS_DIR.")
    _, body = parse_frontmatter(loaded[1])
    context = {"topic": topic, "requested_ideas": n, "photos": [
        {"photo": p.id, "description": p.description,
         "orientation": p.orientation, "dominant_colors": p.colors,
         "face_count": len(p.faces) if p.face_method == "yunet" else None,
         "face_method": p.face_method,
         "measured_facts": {k: v for k, v in photo_facts(p).items() if k != "subject"}
         | {"subject_position": (photo_facts(p)["subject"] or [None])[0]}} for p in photos]}
    return ("## Read this first\n\n"
            "This prompt is for a `zing still` run. The general meme-writing guidance below "
            "still applies, but ignore any step that tells you to view images or call "
            "meme_check/meme_render: for this run you only write lines and return the JSON "
            "described at the end; Zing renders locally.\n\n"
            + body.rstrip() + "\n\n## This local still run\n\n"
            "The JSON below is reference data. It contains locally measured photo descriptions, "
            "not image uploads. Subject identity, actions, and expressions are unknown; do not invent them. "
            "Zing has made no model calls.\n\n" + _json(context) + "\n"
            "For this run, return only JSON: {\"ideas\": [{\"photo\": \"photo-id\", "
            "\"title\": \"short title\", \"texts\": [\"setup\", \"payoff\"], \"why\": \"reason\"}]}. "
            "Use 1-8 distinct ideas, including a wildcard; 1-3 text boxes per idea. "
            "Optional regions are normalized [x,y,width,height] arrays, one per box. "
            "Use only the listed photo IDs. Save the JSON and pass it to zing still --lines <file> "
            "with the same photo folder and a new output folder. Zing validates every line, "
            "plans placement, and generates literal alt text locally. No tool or upload call is needed.\n")


def _concept(topic: str, photo: Photo, idea: dict, aspect: str, requested: str,
             fit: str = "auto", protect: list[list[float]] | None = None) -> Concept:
    template = get_template(idea["template"]) if idea.get("template") else None
    regions = idea.get("regions", template["box_layout"] if template else None)
    count = template["box_count"] if template else (len(regions) if isinstance(regions, list) else None)
    texts = _validate(idea.get("texts"), count)
    if template:
        texts += [""] * (template["box_count"] - len(texts))
    layout, regions, notes = place(photo, texts, aspect, requested, regions, fit=fit, protect=protect)
    fit, focus, framing_notes = frame(photo, aspect, layout, fit, texts=texts)
    notes += framing_notes
    shown = [text.upper() if layout == "classic" else text for text in texts if text]
    alt = photo.description + " Caption text: " + " / ".join(json.dumps(t, ensure_ascii=False) for t in shown) + "."
    return Concept(_concept_id(topic, photo.sha256, texts, aspect, layout, regions, fit, focus),
                   photo.id, idea.get("title", "Imported idea"), texts,
                   idea.get("why", "User-supplied lines."), idea["provider"], layout, regions,
                   {"compression": idea_score(texts), "kind": "readability_heuristic", "predicts_reach": False},
                   alt, list(photo.warnings) + notes, fit=fit, focus=focus)


def _render(concept: Concept, photo: Photo, aspect: str, target: Path,
            protect: list[list[float]] | None = None) -> dict:
    return render_meme(concept.texts, image=photo.path, layout=concept.layout,
                       aspect=aspect, out=str(target), fit=concept.fit, focus=concept.focus,
                       regions=concept.regions, plate=concept.layout == "labels",
                       offline=True, overwrite=True, protect=protect)


def _sheet(root: Path, concepts: list[Concept], aspect: str = "1:1",
           photos: dict[str, Photo] | None = None) -> dict:
    Image, ImageDraw, _, ImageFont, ImageOps = require_pillow()
    columns = min(3, len(concepts))
    # Cells follow the aspect so labels sit under landscape thumbnails too
    # (fixed 400 px cells left a ~150 px gap under every 16:9 thumbnail).
    width, height = ASPECTS[aspect]
    cell_w = 360
    font = ImageFont.truetype(resolve_font("sans"), 15)
    labels = []
    for concept in concepts:
        name = Path(photos[concept.photo].path).name if photos and concept.photo in photos else concept.photo
        # Wrap long labels (long filenames) instead of cutting them off.
        labels.append(wrap_text(f"{concept.layout} | {concept.fit} | {name}", font, cell_w - 24))
    thumb_h = min(334, math.ceil((cell_w - 24) * height / width))
    cell_h = thumb_h + 44 + 22 * max(len(lines) for lines in labels)
    sheet = Image.new("RGB", (columns * cell_w, math.ceil(len(concepts) / columns) * cell_h), "#ededed")
    draw = ImageDraw.Draw(sheet)
    entries = []
    for i, (concept, lines) in enumerate(zip(concepts, labels)):
        x, y = i % columns * cell_w, i // columns * cell_h
        with Image.open(root / concept.path) as source:
            thumb = ImageOps.contain(source, (cell_w - 24, thumb_h))
            sheet.paste(thumb, (x + (cell_w - thumb.width) // 2, y + 10))
        draw.text((x + 12, y + thumb_h + 18), concept.id, font=font, fill="black")
        for row, line in enumerate(lines):
            draw.text((x + 12, y + thumb_h + 40 + 22 * row), line, font=font, fill="#333333")
        entries.append({"id": concept.id, "box": [x, y, x + cell_w, y + cell_h], "alt_text": concept.alt_text,
                        "label_lines": lines})
    sheet.save(root / "contact-sheet.png")
    return {"path": "contact-sheet.png", "width": sheet.width, "height": sheet.height,
            "entries": entries, "alt_text": "Contact sheet. " + " ".join(
                f"{c.id}: {c.alt_text}" for c in concepts)}


def create_stills(photos: str | Path, topic: str, out: str | Path, *, n: int = 6,
                  aspect: str = "1:1", layout: str = "auto", lines: str | Path | None = None,
                  fit: str = "auto", protect: list | None = None) -> dict:
    """``protect``: optional normalized [x, y, w, h] boxes (source coordinates)
    that text must avoid on every photo, in addition to faces and the subject
    estimate. Placement avoids them or says it used a caption bar instead."""
    if not isinstance(topic, str) or not topic.strip() or len(topic) > 500:
        raise MemeError("topic must be a nonempty string of at most 500 characters")
    if type(n) is not int or not 1 <= n <= MAX_CONCEPTS:
        raise MemeError("n must be an integer from 1 to 8")
    if aspect not in ASPECTS or layout not in LAYOUTS:
        raise MemeError("Use aspect 1:1, 4:5, 9:16, or 16:9 and layout auto, classic, caption, or labels.")
    if fit not in FIT_REQUESTS:
        raise MemeError("Use fit auto, fill, blur, contain, or cover.")
    protect = user_boxes(protect) or None
    root = local_path(out)
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise MemeError(f"Use a new or empty output folder: {root}")
    topic = " ".join(topic.split())
    inventory_photos, notes = inventory(photos)
    # Content-based ordering keeps selection stable when photos are renamed.
    candidates = sorted(inventory_photos, key=lambda p: hashlib.sha256(
        (topic + "\0" + p.sha256).encode("utf-8")).hexdigest())
    ideas = _import_lines(lines, candidates) if lines is not None else _offline(topic, candidates, n, layout)
    if lines is None:
        notes = [*notes, HONESTY]
    concepts = [_concept(topic, photo, idea, aspect, layout, fit, protect) for photo, idea in ideas]
    if len({_text_key(c.texts) for c in concepts}) != len(concepts):
        raise MemeError("Duplicate caption text across ideas; provide distinct lines for each concept.")
    prompt = writer_prompt(topic, candidates, len(concepts))
    by_id = {p.id: p for p in candidates}
    root.mkdir(parents=True, exist_ok=True)
    # Publish only after every candidate renders. Failure leaves an empty folder.
    with tempfile.TemporaryDirectory(prefix=".still-", dir=root) as directory:
        stage = Path(directory)
        for concept in concepts:
            photo = by_id[concept.photo]
            if hash_file(Path(photo.path)) != photo.sha256:
                raise MemeError(f"Photo changed since inventory: {photo.path}; run again.")
            concept.path = f"candidate-{concept.id}.png"
            report = _render(concept, photo, aspect, stage / concept.path, protect)
            concept.render = {**report, "path": concept.path, "alt_text": concept.alt_text}
            concept.score["readability"] = report["viral_lens"]["score"]
            concept.warnings.extend(report["warnings"])
        sheet = _sheet(stage, concepts, aspect, by_id)
        index = StillIndex(topic, aspect, candidates, concepts, sheet, warnings=notes, protect=protect)
        (stage / index.prompt_path).write_text(prompt, encoding="utf-8")
        _save_index(stage, index)
        for source in sorted(stage.iterdir(), key=lambda p: p.name == "index.json"):
            source.replace(root / source.name)
    return {"out_folder": str(root), "index_path": str(root / "index.json"),
            "contact_sheet": str(root / sheet["path"]), "prompt_path": str(root / index.prompt_path),
            "prompt": prompt, "count": len(concepts),
            "summary": [{"id": c.id, "photo": c.photo, "texts": c.texts, "layout": c.layout,
                         "fit": c.fit, "score": c.score, "alt_text": c.alt_text,
                         "warnings": c.warnings} for c in concepts],
            "warnings": sorted(set(notes + [w for c in concepts for w in c.warnings]))}


def pick_still(out_folder: str | Path, concept_id: str, *, video: bool = False, gif: bool = False) -> dict:
    if not isinstance(concept_id, str) or not re.fullmatch(r"still-[0-9a-f]{16}", concept_id):
        raise MemeError("Use a concept id from index.json or the contact sheet (still- followed by 16 hex digits).")
    if type(video) is not bool or type(gif) is not bool:
        raise MemeError("video and gif must be boolean")
    root = local_path(out_folder)
    index = StillIndex.from_dict(_read_json(root / "index.json"))
    if index.aspect not in ASPECTS:
        raise MemeError("Invalid index aspect; recreate this still run.")
    concept = next((c for c in index.concepts if c.id == concept_id), None)
    if concept is None:
        raise MemeError(f"Concept {concept_id!r} is not in this index.")
    photo = next((p for p in index.photos if p.id == concept.photo), None)
    if photo is None:
        raise MemeError("Concept photo is missing from the index; recreate this still run.")
    if concept.fit not in ("contain", "cover", "fill", "blur") or (
            (concept.fit == "fill") != (concept.focus is not None)):
        raise MemeError("Saved concept framing is invalid; recreate this still run.")
    if concept.id != _concept_id(index.topic, photo.sha256, concept.texts, index.aspect,
                                 concept.layout, concept.regions, concept.fit, concept.focus):
        raise MemeError("Saved concept changed; use --lines in a new run to validate and index revised copy.")
    source = local_path(photo.path)
    with open_photo(source) as decoded:
        if decoded.size != (photo.width, photo.height) or hash_file(source) != photo.sha256:
            raise MemeError("Source photo changed since inventory; create a new still run before picking.")
    _validate(concept.texts, len(concept.regions) if isinstance(concept.regions, list) else None)
    if not safe_geometry(photo, concept.texts, index.aspect, concept.layout, concept.regions,
                         fit=concept.fit, focus=concept.focus, protect=index.protect):
        raise MemeError("Saved text placement is unsafe; recreate this still run.")
    basename = f"finished-{concept.id}"
    extensions = [".png"] + ([".mp4"] if video or gif else []) + ([".gif"] if gif else [])
    previous = {record["path"]: record for record in concept.outputs}
    for ext in extensions:
        target = root / (basename + ext)
        if target.is_symlink() or (target.exists() and (
                target.name not in previous or hash_file(target) != previous[target.name].get("sha256"))):
            raise MemeError(f"Output already exists or changed: {target}; move it aside before picking again.")
    # An encoder failure must leave the previous export and selection intact.
    with tempfile.TemporaryDirectory(prefix=".pick-", dir=root) as directory:
        stage = Path(directory)
        report = _render(concept, photo, index.aspect, stage / (basename + ".png"), index.protect)
        result = {**report, "path": str(root / (basename + ".png")),
                  "id": concept.id, "alt_text": concept.alt_text,
                  "warnings": concept.warnings, "index_path": str(root / "index.json")}
        exports = [{"path": basename + ".png", "alt_text": concept.alt_text,
                    "width": report["width"], "height": report["height"]}]
        if video or gif:
            from myzing.memes.video import render_meme_video

            # No zoom: it could move faces under fixed text. Check even H.264 geometry too.
            motion_size = tuple(axis + axis % 2 for axis in ASPECTS[index.aspect])
            if not safe_geometry(photo, concept.texts, index.aspect, concept.layout,
                                 concept.regions, size=motion_size, fit=concept.fit, focus=concept.focus,
                                 protect=index.protect):
                raise MemeError("Animated output needs a different safe layout; create a caption-bar concept.")
            # Normalize supported photo formats (including BMP/TIFF) to the
            # animated renderer's local PNG input; preserve EXIF orientation.
            motion_source = stage / "source.png"
            with open_photo(source) as decoded:
                decoded.save(motion_source)
            motion = render_meme_video(concept.texts, image=str(motion_source), layout=concept.layout,
                                       aspect=index.aspect, out=str(stage / (basename + ".mp4")),
                                       fit=concept.fit, focus=concept.focus,
                                       regions=concept.regions, plate=concept.layout == "labels", gif=gif,
                                       overwrite=True)
            motion_source.unlink()
            motion["source_path"] = photo.path
            motion["path"] = str(root / (basename + ".mp4"))
            if gif:
                motion["gif"]["path"] = str(root / (basename + ".gif"))
                motion["gif"]["alt_text"] = concept.alt_text
            result["video"] = {**motion, "alt_text": concept.alt_text}
            exports.append({"path": basename + ".mp4", "alt_text": concept.alt_text,
                            "width": motion["width"], "height": motion["height"]})
            if gif:
                result["gif"] = motion["gif"]
                exports.append({"path": basename + ".gif", "alt_text": concept.alt_text,
                                "width": motion["gif"]["width"], "height": motion["gif"]["height"]})
        for record in exports:
            record["sha256"] = hash_file(stage / record["path"])
            previous[record["path"]] = record
        concept.outputs = list(previous.values())
        index.selected = concept.id
        _save_index(stage, index)
        for source in sorted(stage.iterdir(), key=lambda p: p.name == "index.json"):
            source.replace(root / source.name)
    return result
