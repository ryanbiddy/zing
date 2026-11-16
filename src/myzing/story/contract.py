"""Validate the authored story and resolve the page's line-based cues."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path, PureWindowsPath
from urllib.parse import urlsplit

from . import StoryError, data_path

VOCABULARY = json.loads(data_path("vocabulary.json").read_text(encoding="utf-8"))
CARD_KINDS = tuple(VOCABULARY["cards"])
PROPS = tuple(VOCABULARY["props"])
POSES = tuple(VOCABULARY["poses"])
ID = re.compile(r"[a-z][a-z0-9_-]{0,59}\Z")
NUMBER = r"(?:\d+(?:\.\d*)?|\.\d+)"
CUE_SUFFIX = re.compile(rf"(?::(\d+))?(?::({NUMBER}))?(?::?([+-]{NUMBER}))?\Z")
COLOR = re.compile(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\Z")
CAPTION_BAND = {"x": 0, "y": 1560, "width": 1080, "height": 160}
PLACEHOLDER_SOURCE_URL = "https://example.invalid/replace-this-source"


def finite(value) -> bool:
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def cue_time(cue, timings: dict) -> float:
    if finite(cue):
        return float(cue)
    if not isinstance(cue, str):
        raise StoryError(f"bad cue {cue!r}")
    beats = {b["id"]: b for b in timings["beats"]}
    # Match whole known IDs first. A greedy ID regexp eats the minus in an offset.
    for name in sorted([*beats, "outro"], key=len, reverse=True):
        if not cue.startswith(name):
            continue
        suffix = cue[len(name):]
        match = CUE_SUFFIX.fullmatch(suffix)
        if not match:
            continue
        line, fraction, offset = match.groups()
        if fraction is not None and line is None:
            raise StoryError(f"cue {cue!r}: a fraction needs a line index")
        if name == "outro":
            if line is not None or fraction is not None:
                raise StoryError("outro cannot have a line index or fraction")
            result = timings["outro_start"] + float(offset or 0)
            if not math.isfinite(result):
                raise StoryError(f"bad cue {cue!r}")
            return result
        beat = beats[name]
        at = beat["start"]
        if line is not None:
            index = int(line)
            if index >= len(beat["lines"]):
                raise StoryError(f"cue {cue!r}: line index {index} out of range for {name}")
            frac = float(fraction or 0)
            if not 0 <= frac <= 1:
                raise StoryError(f"cue {cue!r}: fraction must be between 0 and 1")
            entry = beat["lines"][index]
            at = entry["start"] + (entry["end"] - entry["start"]) * frac
        result = at + float(offset or 0)
        if not math.isfinite(result):
            raise StoryError(f"bad cue {cue!r}")
        return result
    raise StoryError(f"unknown beat or bad cue {cue!r}")


def _url(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parts = urlsplit(value)
        return parts.scheme in ("http", "https") and bool(parts.hostname) and not parts.username
    except ValueError:
        return False


def local_photo(directory: Path, name: str) -> Path:
    """Photos stay inside the story folder; render never fetches a remote image."""
    relative = Path(name)
    if not name or relative.is_absolute() or PureWindowsPath(name).drive or ":" in name or "\\" in name:
        raise StoryError("photo path must be a relative file path inside the story folder (use /)")
    base = directory.resolve()
    target = (base / relative).resolve()
    if not target.is_relative_to(base):
        raise StoryError("photo path must stay inside the story folder")
    return target


def check(story, directory: Path | None = None, *, timings: dict | None = None) -> list[str]:
    """Collect all independent problems, including malformed nested objects."""
    errors: list[str] = []
    provided_timings = timings

    def err(where, message):
        errors.append(f"{where}: {message}")

    def obj(value, where, fields):
        if not isinstance(value, dict):
            err(where, "must be an object")
            return {}
        for key in value.keys() - set(fields.split()):
            err(where, f"unknown field {key!r}")
        return value

    def seq(value, where, minimum=0, maximum=None):
        if not isinstance(value, list):
            err(where, "must be a list")
            return []
        if len(value) < minimum or maximum is not None and len(value) > maximum:
            err(where, f"needs {minimum}" + (f" to {maximum}" if maximum is not None else " or more") + " entries")
        return value

    def text(value, where, limit, required=True):
        if not isinstance(value, str) or required and not value.strip():
            err(where, "must be non-empty text" if required else "must be text")
        elif len(value) > limit:
            err(where, f"at most {limit} characters")

    def num(value, where, low, high):
        if not finite(value) or not low <= value <= high:
            err(where, f"must be a finite number from {low} to {high}")

    def color(value, where):
        if not isinstance(value, str) or not COLOR.fullmatch(value):
            err(where, "must be a hex color such as #FFD21F")

    def choice(value, choices, where):
        if not isinstance(value, str) or value not in choices:
            err(where, f"unknown value {value!r}; choose from {', '.join(choices)}")

    s = obj(story, "story", "schema_version slug topic handle cast beats panels sources outro captions sfx music images")
    for flag in ("captions", "sfx"):
        if flag in s and type(s[flag]) is not bool:
            err(flag, "must be a boolean")
    if "schema_version" in s and (type(s["schema_version"]) is not int or s["schema_version"] != 1):
        err("schema_version", "must be 1")
    text(s.get("topic"), "topic", 60)
    text(s.get("handle", ""), "handle", 40, False)
    if "slug" in s and (not isinstance(s["slug"], str) or not ID.fullmatch(s["slug"])):
        err("slug", "use a lowercase ID (letters, digits, - and _)")
    num(s.get("outro", 3.2), "outro", 1, 30)
    for i, raw in enumerate(seq(s.get("sources"), "sources", 1)):
        source = obj(raw, f"sources[{i}]", "title url")
        text(source.get("title"), f"sources[{i}].title", 100)
        if not _url(source.get("url")):
            err(f"sources[{i}].url", "must be an http or https URL")
        if (source.get("url") == PLACEHOLDER_SOURCE_URL
                or str(source.get("title", "")).strip().lower() == "replace this source"):
            err(f"sources[{i}]", "replace this source with a source you have read before building")

    if "music" in s:
        music = obj(s["music"], "music", "path credit license source_url")
        for key, limit in (("path", 240), ("credit", 120), ("license", 100)):
            text(music.get(key), "music." + key, limit)
        if not _url(music.get("source_url")):
            err("music.source_url", "must be an http or https URL")
        if isinstance(music.get("path"), str):
            try:
                path = local_photo(directory or Path.cwd(), music["path"])
                if directory is not None and not path.is_file():
                    err("music.path", "music file is missing")
            except StoryError as exc:
                err("music.path", str(exc).replace("photo", "music"))
        if isinstance(music.get("license"), str) and music["license"].strip():
            from .heads import photo_rights
            try:
                if photo_rights(music) not in ("cleared", "attribution"):
                    err("music.license", "must permit reuse and changes; NC, ND and unknown licenses are refused")
            except StoryError as exc:
                err("music", str(exc))

    cast = s.get("cast", {})
    if not isinstance(cast, dict):
        err("cast", "must be an object keyed by cast ID")
        cast = {}
    for ident, raw in cast.items():
        where = f"cast.{ident}"
        if not ID.fullmatch(ident):
            err(where, "use a lowercase ID (letters, digits, - and _)")
        member = obj(raw, where, "name photos skin jacket shirt legs")
        text(member.get("name"), where + ".name", 60)
        for key in ("skin", "jacket", "shirt", "legs"):
            if key in member:
                color(member[key], where + "." + key)
        for i, raw_photo in enumerate(seq(member.get("photos", []), where + ".photos")):
            pwhere = f"{where}.photos[{i}]"
            photo = obj(raw_photo, pwhere, "path credit license source_url face")
            for key, limit in (("path", 240), ("credit", 120), ("license", 100)):
                text(photo.get(key), pwhere + "." + key, limit)
            if not _url(photo.get("source_url")):
                err(pwhere + ".source_url", "must be an http or https URL")
            if isinstance(photo.get("path"), str):
                try:
                    path = local_photo(directory or Path.cwd(), photo["path"])
                    if directory is not None and not path.is_file():
                        err(pwhere + ".path", "photo file is missing")
                except StoryError as exc:
                    err(pwhere + ".path", str(exc))
            if isinstance(photo.get("license"), str) and photo["license"].strip():
                from .heads import photo_rights
                try:
                    if photo_rights(photo) not in ("cleared", "attribution"):
                        err(pwhere + ".license", "must permit reuse and changes; NC, ND and unknown licenses are refused")
                except StoryError as exc:
                    err(pwhere, str(exc))
            if "face" in photo:
                face = seq(photo["face"], pwhere + ".face", 4, 4)
                for j, value in enumerate(face):
                    num(value, pwhere + f".face[{j}]", 0 if j < 2 else 1, 100000)

    images = s.get("images", {})
    if not isinstance(images, dict):
        err("images", "must be an object keyed by image ID")
        images = {}
    for ident, raw in images.items():
        where = f"images.{ident}"
        if not isinstance(ident, str) or not ID.fullmatch(ident):
            err(where, "use a lowercase ID (letters, digits, - and _)")
        image = obj(raw, where, "path credit license source_url cut box")
        for key, limit in (("path", 240), ("credit", 120), ("license", 100)):
            text(image.get(key), where + "." + key, limit)
        from .images import image_errors
        for problem in image_errors(image):
            err(where, problem)
        if isinstance(image.get("path"), str):
            try:
                path = local_photo(directory or Path.cwd(), image["path"])
                if directory is not None and not path.is_file():
                    err(where + ".path", "image file is missing")
            except StoryError as exc:
                err(where + ".path", str(exc).replace("photo", "image"))

    beats = seq(s.get("beats"), "beats", 4, 14)
    ids, timed, words, spoken = [], [], 0, 0
    for i, raw in enumerate(beats):
        where = f"beats[{i}]"
        beat = obj(raw, where, "id chapter lines tail")
        ident = beat.get("id")
        if not isinstance(ident, str) or not ID.fullmatch(ident) or ident == "outro":
            err(where + ".id", "use a lowercase ID; outro is reserved")
            ident = f"invalid_{i}"
        if ident in ids:
            err(where + ".id", "duplicate beat ID")
        ids.append(ident)
        text(beat.get("chapter", ""), where + ".chapter", 40, False)
        num(beat.get("tail", .3), where + ".tail", 0, 5)
        lines = seq(beat.get("lines"), where + ".lines", 1, 8)
        for j, raw_line in enumerate(lines):
            lwhere = f"{where}.lines[{j}]"
            line = obj(raw_line, lwhere, "text say gap")
            text(line.get("text"), lwhere + ".text", 300)
            if "say" in line:
                text(line["say"], lwhere + ".say", 300)
            for key in ("text", "say"):
                value = line.get(key)
                if isinstance(value, str) and len(value.split()) > 22:
                    err(lwhere + "." + key, "at most 22 words per line")
            words += len(line.get("text", "").split()) if isinstance(line.get("text"), str) else 0
            value = line.get("say", line.get("text", ""))
            spoken += len(value.split()) if isinstance(value, str) else 0
            num(line.get("gap", .16), lwhere + ".gap", 0, 5)
        timed.append({"id": ident, "start": i * 10, "end": (i + 1) * 10,
                      "lines": [{"start": i * 10 + j, "end": i * 10 + j + 1} for j in range(len(lines))]})
    if words > 160 or spoken > 160:
        err("beats", "whole narration is at most 160 words (text and spoken say each count)")
    timings = {"beats": timed, "outro_start": len(beats) * 10,
               "duration": len(beats) * 10 + (s.get("outro", 3.2) if finite(s.get("outro", 3.2)) else 3.2)}

    def cue(value, where):
        try:
            cue_time(value, timings)
        except StoryError as exc:
            err(where, str(exc))

    def common(entry, where, coords=True, animations="animations"):
        if coords:
            num(entry.get("x"), where + ".x", 0, 1080)
            num(entry.get("y"), where + ".y", 0, 1920)
        for key in ("at", "until"):
            if key in entry:
                cue(entry[key], where + "." + key)
        for key, lo, hi in (("scale", .1, 5), ("rot", -360, 360), ("size", 16, 300), ("w", 80, 1000),
                            ("z", 0, 10), ("opacity", 0, 1)):
            if key in entry:
                num(entry[key], where + "." + key, lo, hi)
        if "anim" in entry:
            choice(entry["anim"], VOCABULARY[animations], where + ".anim")
        for key in ("bg", "color", "fill", "stroke", "lit", "seat", "seat2", "bench"):
            if key in entry:
                color(entry[key], where + "." + key)

    starts = []
    for i, raw in enumerate(seq(s.get("panels"), "panels", 1)):
        where = f"panels[{i}]"
        panel = obj(raw, where, "from set props actors cards")
        start = panel.get("from")
        if start == "outro":
            index = len(beats)
        elif isinstance(start, str) and start in ids:
            index = ids.index(start)
        else:
            err(where + ".from", "must be a beat ID or outro (no offsets)")
            index = -1
        if index >= 0 and starts and index <= starts[-1]:
            err(where + ".from", "panels must start in beat order without duplicates; outro goes last")
        starts.append(index)
        setting = obj(panel.get("set", {}), where + ".set", "wall floor pattern floor_pattern")
        for key in ("wall", "floor"):
            if key in setting:
                color(setting[key], where + ".set." + key)
        for key, choices in (("pattern", "wall_patterns"), ("floor_pattern", "floor_patterns")):
            if key in setting:
                choice(setting[key], VOCABULARY[choices], where + ".set." + key)
        for j, raw_prop in enumerate(seq(panel.get("props", []), where + ".props")):
            pwhere = f"{where}.props[{j}]"
            prop = obj(raw_prop, pwhere, "prop x y r fill still n round opacity scale at until anim front rot gap dot night lit drop text stroke seat seat2 leg bench spin image w")
            choice(prop.get("prop"), PROPS, pwhere + ".prop")
            common(prop, pwhere, animations="prop_animations")
            for key in ("still", "round", "front", "night"):
                if key in prop and type(prop[key]) is not bool:
                    err(pwhere + "." + key, "must be a boolean")
            for key, lo, hi in (("r", 1, 1000), ("n", 1, 20), ("gap", 1, 200), ("dot", 1, 100),
                                ("drop", 1, 1500), ("leg", 1, 1500), ("spin", -90, 90)):
                if key in prop:
                    num(prop[key], pwhere + "." + key, lo, hi)
            if "text" in prop:
                text(prop["text"], pwhere + ".text", 8)
            if prop.get("prop") == "image":
                if not isinstance(prop.get("image"), str) or prop["image"] not in images:
                    err(pwhere + ".image", f"unknown image ID {prop.get('image')!r}; add it to images")
                num(prop.get("w"), pwhere + ".w", 80, 1000)
            elif "image" in prop:
                err(pwhere + ".image", "only image props use an image ID")
        for j, raw_actor in enumerate(seq(panel.get("actors", []), where + ".actors")):
            awhere = f"{where}.actors[{j}]"
            actor = obj(raw_actor, awhere, "who x y scale pose poses moves enter head head_at head_scale flip")
            who = actor.get("who")
            if not isinstance(who, str) or who not in cast:
                err(awhere + ".who", "unknown cast member")
            common(actor, awhere, False)
            num(actor.get("x"), awhere + ".x", 0, 1080)
            if "y" in actor:
                num(actor["y"], awhere + ".y", 0, 1920)
            choice(actor.get("pose", "idle"), POSES, awhere + ".pose")
            if "enter" in actor and actor["enter"] != "walk":
                cue(actor["enter"], awhere + ".enter")
            if "head_scale" in actor:
                num(actor["head_scale"], awhere + ".head_scale", .1, 3)
            if "flip" in actor and type(actor["flip"]) is not bool:
                err(awhere + ".flip", "must be a boolean")
            if s.get("captions") is not False and start != "outro":
                from .layout import head_overlaps_captions
                if head_overlaps_captions(actor):
                    err(awhere, "puppet head overlaps the caption band at y=1560..1720; move it up or increase scale")
            member = cast.get(who, {}) if isinstance(who, str) else {}
            photos = member.get("photos", []) if isinstance(member, dict) else []
            count = len(photos) if isinstance(photos, list) else 0

            def head(value, hwhere):
                if type(value) is not int or not 0 <= value < max(1, count):
                    err(hwhere, "head index is out of range")

            if "head" in actor:
                head(actor["head"], awhere + ".head")
            for key, fields in (("poses", "at pose"), ("moves", "at dur from to"), ("head_at", "at head")):
                for k, raw_change in enumerate(seq(actor.get(key, []), awhere + "." + key)):
                    cwhere = f"{awhere}.{key}[{k}]"
                    change = obj(raw_change, cwhere, fields)
                    cue(change.get("at"), cwhere + ".at")
                    if key == "poses":
                        choice(change.get("pose"), POSES, cwhere + ".pose")
                    elif key == "head_at":
                        head(change.get("head"), cwhere + ".head")
                    else:
                        num(change.get("dur"), cwhere + ".dur", .01, 30)
                        for field in ("from", "to"):
                            num(change.get(field), cwhere + "." + field, -1080, 2160)
        for j, raw_card in enumerate(seq(panel.get("cards", []), where + ".cards")):
            cwhere = f"{where}.cards[{j}]"
            card = obj(raw_card, cwhere, "kind text sub k rows x y w size bg color rot at until anim z from over_head")
            common(card, cwhere)
            if "over_head" in card and type(card["over_head"]) is not bool:
                err(cwhere + ".over_head", "must be a boolean")
            for field, edge in (("x", 1080), ("y", 1920)):
                if finite(card.get(field)) and card[field] == edge:
                    err(cwhere + "." + field, f"must be less than {edge}, inside the frame")
            cue(card.get("at"), cwhere + ".at")
            kind = card.get("kind")
            choice(kind, CARD_KINDS, cwhere + ".kind")
            if kind == "credits":
                err(cwhere, "credits are generated from sources and photo rights; do not write a credits card")
            limits = VOCABULARY["cards"].get(kind, {}) if isinstance(kind, str) else {}
            for field in ("text", "sub", "k"):
                if field in card or field == "text" and kind not in ("list", "credits"):
                    if field not in limits:
                        err(cwhere + "." + field, f"not used by {kind}")
                    else:
                        text(card.get(field), cwhere + "." + field, limits[field])
            if "from" in card:
                num(card["from"], cwhere + ".from", -2160, 2160)
            if kind == "list":
                for k, raw_row in enumerate(seq(card.get("rows"), cwhere + ".rows", 1, limits["rows"])):
                    rwhere = f"{cwhere}.rows[{k}]"
                    row = obj(raw_row, rwhere, "text at")
                    text(row.get("text"), rwhere + ".text", limits["row"])
                    cue(row.get("at"), rwhere + ".at")
            elif "rows" in card:
                err(cwhere + ".rows", "only list cards have rows")
            if s.get("captions") is not False and start != "outro":
                from .layout import card_overlaps_captions
                if card_overlaps_captions(card):
                    err(cwhere, "card box overlaps the caption band at y=1560..1720; move it above the band")
    if beats and (not starts or starts[0] != 0):
        err("panels", "the first panel must start at the first beat so every beat is covered")
    if not errors:
        # Structure checks use placeholder times to validate cue syntax. Once
        # voice exists, layout must use exactly the times the page will use.
        actual = provided_timings
        if actual is None and directory is not None:
            try:
                actual = json.loads((Path(directory) / "timings.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        if actual is not None and not check_timings(s, actual):
            timings = actual
        from .layout import panel_overlaps
        for index, panel in enumerate(s["panels"]):
            end = (cue_time(s["panels"][index + 1]["from"], timings)
                   if index + 1 < len(s["panels"]) else timings["duration"])
            try:
                errors.extend(f"panels[{index}].{problem}" for problem in
                              panel_overlaps(panel, timings, end=end, cast=cast, directory=directory))
            except StoryError as exc:
                err(f"panels[{index}]", str(exc))
    return errors


def load(directory: Path) -> dict:
    path = Path(directory) / "story.json"
    try:
        story = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StoryError(f"Cannot read story.json: {exc}") from exc
    errors = check(story, Path(directory))
    if errors:
        raise StoryError("\n".join(errors))
    return story


def check_timings(story: dict, timings) -> list[str]:
    """Reject stale, incomplete or unsafe timing files before the browser opens."""
    errors = []
    if not isinstance(timings, dict):
        return ["timings must be an object; run zing story voice"]
    if timings.get("provider") not in ("kokoro", "elevenlabs", "lines"):
        errors.append("timings.provider must be kokoro, elevenlabs or lines; run zing story voice")
    if timings.get("provider") in ("kokoro", "elevenlabs") and not isinstance(timings.get("voice"), str):
        errors.append("timings.voice must name the synthetic voice")
    duration, outro = timings.get("duration"), timings.get("outro_start")
    if not finite(duration) or not finite(outro) or not 0 < outro < duration:
        errors.append("timings need finite duration > outro_start > 0")
    beats = timings.get("beats")
    if not isinstance(beats, list) or len(beats) != len(story["beats"]):
        return errors + ["timings beats do not match story.json; run zing story voice"]
    previous = 0
    for expected, beat in zip(story["beats"], beats):
        if not isinstance(beat, dict):
            errors.append("timing beat must be an object")
            continue
        label = f"timings.{expected['id']}"
        if beat.get("id") != expected["id"]:
            errors.append(label + ": beat ID does not match story.json")
        a, b = beat.get("start"), beat.get("end")
        if not finite(a) or not finite(b) or not previous <= a < b:
            errors.append(label + ": invalid or overlapping beat times")
            continue
        previous = b
        lines = beat.get("lines")
        if not isinstance(lines, list) or len(lines) != len(expected["lines"]):
            errors.append(label + ": lines do not match story.json")
            continue
        end = a
        for line, wanted in zip(lines, expected["lines"]):
            if not isinstance(line, dict):
                errors.append(label + ": line must be an object")
                continue
            start, stop = line.get("start"), line.get("end")
            if not finite(start) or not finite(stop) or not end <= start < stop <= b:
                errors.append(label + ": invalid or overlapping line times")
            else:
                end = stop
            if line.get("text") != wanted["text"]:
                errors.append(label + ": text changed; run zing story voice")
    if finite(outro) and previous > outro:
        errors.append("timings: the last beat must end before the outro")
    return errors
