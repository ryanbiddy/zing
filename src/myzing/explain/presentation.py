"""Phone-size card and concise prose, drawn from the same evidence record.

Order: what a viewer notices, how to get the look, then one block per section
with plain lines, a confidence note and a single "not knowable" sentence.
Every measurement, sample and itemized limitation stays in card.json.
"""

from pathlib import Path

from .plain import aspect_name

CAPTION_ROLES = ("caption", "title", "credit", "persistent overlay")


def command_label(command):
    if command.startswith("zing match"):
        return "Three drafts in this style from your clips (measures the reference again):"
    if command.startswith("zing plan drafts"):
        return "Already have a Zing project? Plan drafts from this card's recipe:"
    if command.startswith("zing color match"):
        return "Approximate this color on one of your clips:"
    if command.startswith("zing color apply"):
        return "Apply that look:"
    return None


def markdown(card):
    framing = card.sections["framing"].facts
    lines = [f"# Style card: {Path(card.source).name}", "",
             f"{card.duration_seconds:.1f}s, {framing['width']} x {framing['height']}. Measured from the exported video; "
             "the original project settings are unknown.", "",
             "## What a viewer notices", "", *[f"- {line}" for line in card.summary], ""]
    lines += ["## Get this look", "", "```sh"]
    for command in card.commands:
        label = command_label(command)
        lines += ([f"# {label}"] if label else []) + [command]
    lines += ["```", "",
              "Replace `./my-clips`, `./my-edit` and `clip1.mp4` with your own folder, project and clip. "
              f"The reusable StyleRecipe is `{card.recipe_path}`. Drafts approximate the look; they do not copy the original edit."]
    for key, section in card.sections.items():
        lines += ["", f"## {section.title}", "", *(section.lines or ["No supported measurement."])]
        if key == "pacing":
            facts = section.facts
            pairs = facts.get("beat_alignment")
            if pairs:
                lines.append(f"{facts['cuts_on_beats']} of {len(pairs)} cuts land within 80 ms of a detected beat.")
            drops = facts.get("drop_alignment")
            if drops:
                lines.append(f"{sum(abs(p['delta_seconds']) <= .08 for p in drops)} of {len(drops)} cuts land within 80 ms of a detected drop.")
        if key == "hook":
            lines += ["", "### How these were measured", "",
                      "Times refer to the studied interval (source range in card.json).", ""]
            for name, fact in section.facts.items():
                label = name.replace("time_to_", "").replace("_", " ").capitalize()
                lines.append(f"- {label} ({fact['status'].replace('_', ' ')}): "
                             f"{fact['method'].rstrip('.')}. {fact['basis']}")
        lines += ["", "Confidence: " + confidence_text(section)]
        if section.not_knowable:
            lines.append("Not knowable from pixels: " + section.not_knowable)
        comparison = card.comparison.get("sections", {}).get(key)
        if comparison:
            lines += ["", "Against the draft: " + comparison_text(comparison)]
    lines += ["", "---", "",
              "Scores are heuristic evidence, not probabilities. card.json keeps every measurement, sample and limitation.", ""]
    return "\n".join(lines)


def confidence_text(section):
    c = section.confidence
    if not c:
        return "unmeasured"
    if "music_evidence" in c:
        return f"music evidence {c['music_evidence']}; loudness is EBU R128; other audio values are heuristics"
    if c.get("score") is not None:
        return f"{c['score']:.2f} heuristic score; {c.get('kind', c.get('basis', 'heuristic'))}"
    if "dimensions" in c:
        return f"{c['dimensions']}; {c['faces']}; {c.get('matte', 'no matte check')}"
    if "basis" in c and section.title == "Cuts and pacing":
        return f"shot boundaries from {c['basis']}; no detector is ground truth"
    return c.get("kind", c.get("basis", "heuristic"))


METRIC_NAMES = {"median_shot_seconds": "median shot (s)", "aspect": "aspect", "face_height_percent": "face height (%)",
                "speech_share": "speech share", "bpm": "tempo (BPM)", "lufs": "loudness (LUFS)", "luma": "max luma percentile gap",
                "placement": "caption box overlap (IoU)"}


def comparison_text(comparison):
    def value(v):
        if isinstance(v, float):
            return f"{v:.3g}"
        if isinstance(v, list):
            return "[" + ", ".join(value(x) for x in v) + "]"
        return "unknown" if v is None else str(v)
    parts = []
    for name, m in comparison["metrics"].items():
        label = METRIC_NAMES.get(name, name.replace("_", " ") + "s per minute")
        if name == "luma":
            parts.append(f"{label} {value(m.get('max_delta'))} (limit 0.15, {m['status']})")
        elif name == "placement":
            parts.append(f"{label} {value(m.get('observed'))} (needs 0.8, {m['status']})")
        else:
            why = f": {m['reason'].split(';')[0].rstrip('.').lower()}" if m["status"] == "unknown" and m.get("reason") else ""
            parts.append(f"{label} {value(m.get('target'))} vs {value(m.get('observed'))} ({m['status']}{why})")
    if not parts:
        return comparison["status"] + ": " + comparison.get("reason", "nothing measurable in either video.")
    return comparison["status"] + ". " + "; ".join(parts) + "."


def _grab(media, t, width, height):
    """One display-oriented frame at exactly width x height (rotation and SAR applied)."""
    from myzing.inspect.media import Decoder
    decoder = Decoder()
    return decoder.run(decoder.input_args(Path(media), t) + [
        "-map", "0:v:0", "-an", "-sn", "-dn", "-frames:v", "1",
        "-vf", f"scale={width}:{height},setsar=1", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"],
        f"card key frame at {t:.3f}s")


def render_png(card, media, path):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise ImportError("The PNG card needs Pillow; install myzing[memes] (no model download).") from exc
    font_path = Path(__file__).resolve().parents[1] / "_data/fonts/IBMPlexSans.ttf"
    font = ImageFont.truetype(str(font_path), 30)
    heading = ImageFont.truetype(str(font_path), 40)
    small = ImageFont.truetype(str(font_path), 26)
    ink, muted, accent, paper = "#263335", "#52615c", "#78503d", "#f5f2eb"
    canvas = Image.new("RGB", (800, 12000), paper)
    draw = ImageDraw.Draw(canvas)
    y = 30
    def text(message, selected=font, color=ink, indent=0):
        nonlocal y
        width = 728 - indent
        for paragraph in str(message).splitlines():
            line = ""
            for word in paragraph.split():
                candidate = (line + " " + word).strip()
                if line and draw.textlength(candidate, font=selected) > width:
                    draw.text((36 + indent, y), line, font=selected, fill=color)
                    y += selected.size + 9
                    line = ""
                # Split only tokens wider than a whole line (paths/OCR noise).
                while draw.textlength(word, font=selected) > width:
                    end = len(word)
                    while draw.textlength(word[:end], font=selected) > width:
                        end -= 1
                    # Break long paths after a separator when one fits.
                    cut = max(word.rfind("\\", 0, end), word.rfind("/", 0, end))
                    end = cut + 1 if cut > end // 2 else end
                    draw.text((36 + indent, y), word[:end], font=selected, fill=color)
                    y += selected.size + 9
                    word = word[end:]
                line = (line + " " + word).strip()
            draw.text((36 + indent, y), line, font=selected, fill=color)
            y += selected.size + 9
    def rule():
        nonlocal y
        y += 14
        draw.line((36, y, 764, y), fill="#c6c9c0", width=2)
        y += 14
    framing = card.sections["framing"].facts
    aspect = framing["aspect"]
    text("ZING / STYLE CARD", heading)
    text(Path(card.source).name[:70], small)
    text(f"{card.duration_seconds:.1f}s / {framing['width']} x {framing['height']} {aspect_name(framing['width'], framing['height'])}"
         " / measured from the export", small, muted)
    y += 10
    # Key frames keep the displayed aspect; the outline marks the frame edge so
    # bars inside the picture are visible and none are added around it.
    th = min(300, round(232 / aspect))
    tw = min(232, round(th * aspect))
    tw, th = max(2, tw - tw % 2), max(2, th - th % 2)
    frames = []
    for i, t in enumerate(card.duration_seconds*f for f in (.15, .5, .85)):
        x = 36 + i*248 + (232 - tw)//2
        try:
            data = _grab(media, t, tw, th)
            if len(data) != tw*th*3:
                raise RuntimeError("incomplete frame")
            canvas.paste(Image.frombytes("RGB", (tw, th), data), (x, y))
            frames.append({"time": t, "box": [x, y, x+tw, y+th]})
        except Exception as exc:
            card.warnings.append(f"Key frame {t:.2f}s unavailable: {exc}")
            draw.rectangle((x, y, x+tw, y+th), fill="#d7d6ce")
            draw.text((x+8, y+th//2-14), "Unavailable", font=small, fill=ink)
        draw.rectangle((x-1, y-1, x+tw, y+th), outline="#9aa39b", width=1)
        draw.text((x, y+th+4), f"{t:.1f}s", font=small, fill=ink)
    y += th + 44
    text("What a viewer notices", heading)
    for line in card.summary:
        draw.ellipse((40, y+13, 50, y+23), fill="#247c75")
        text(line, indent=26)
    y += 8
    strip_y = y
    duration = card.duration_seconds
    def project(t):
        return 36 + round(min(1, max(0, t/duration))*728) if duration > 0 else 36
    text("SHOTS / detected boundaries", small, muted)
    shots = card.sections["pacing"].facts.get("shots", [])
    for i, shot in enumerate(shots):
        draw.rectangle((project(shot['start']), y, project(shot['end']), y+26), fill=("#247c75", "#b5d3bd")[i % 2], outline=paper)
    if not shots:
        draw.rectangle((36, y, 764, y+26), outline=muted)
        draw.text((48, y-2), "unknown", font=small, fill=muted)
    y += 34
    draw.text((36, y), "0s", font=small, fill=ink)
    draw.text((764, y), f"{duration:.1f}s", font=small, fill=ink, anchor="ra")
    y += small.size + 9
    for key, section in card.sections.items():
        rule()
        text(section.title, heading)
        shown = section.lines or ["Unknown; measurement unavailable."]
        for line in shown[:4]:
            text(line[:240])
        if key == "captions":
            rows = [r for r in section.facts.get("tracks", []) if r["kind"] in CAPTION_ROLES]
            if rows:
                bw, bh = (180, int(180/aspect)) if aspect >= 1 else (int(180*aspect), 180)
                for i, row in enumerate(sorted(rows, key=lambda r: -r.get("sample_count", len(r["samples"])))[:3]):
                    x = 36+i*248
                    draw.rectangle((x, y, x+bw, y+bh), fill="#dde2d8", outline=muted)
                    left, top, right, bottom = row["box"]
                    draw.rectangle((x+left*bw, y+top*bh, x+right*bw, y+bottom*bh), outline="#b14b2d", width=3)
                y += bh+12
                text("Where caption/title text sat (sampled boxes)", small, muted)
        if key == "color":
            swatches = section.facts.get("swatches", [])
            for i, swatch in enumerate(swatches[:8]):
                draw.rectangle((36+i*91, y, 120+i*91, y+36), fill=swatch)
            if swatches:
                y += 50
        if key == "audio":
            energy = (section.facts.get("structure") or {}).get("energy", [])
            if energy:
                text("MIX LEVEL over time (red: detected changes)", small, muted)
                draw.rectangle((36, y, 764, y+70), fill="#e3e5dc")
                points = [(project(e['time']), y+70-round(min(60, max(0, e['rms_dbfs']+60))/60*70)) for e in energy]
                if len(points) > 1:
                    draw.line(points, fill="#247c75", width=3)
                for m in (section.facts.get("structure") or {}).get("moments", []):
                    x = project(m['time'])
                    draw.line((x, y, x, y+70), fill="#b14b2d", width=2)
                y += 80
        if section.not_knowable:
            text("Not knowable: " + section.not_knowable, small, accent)
        comparison = card.comparison.get("sections", {}).get(key)
        if comparison:
            text("Against the draft: " + comparison["status"] + " (numbers in card.md)", small, muted)
    rule()
    text("Get this look", heading)
    for command in card.commands:
        label = command_label(command)
        if label:
            text(label, small, muted)
        top = y
        text(command, small, ink, indent=12)
        draw.line((38, top + 4, 38, y - 6), fill="#247c75", width=3)
        y += 6
    text("Swap ./my-clips, ./my-edit and clip1.mp4 for your own. Fonts, LUTs and the editor project cannot be recovered from an export.", small, muted)
    height = min(y + 28, canvas.height)
    canvas.crop((0, 0, 800, height)).save(path, "PNG")
    return {"width": 800, "height": height, "keyframes": frames, "keyframe_size": [tw, th], "pacing_strip_y": strip_y,
            "phone_width": 400, "minimum_font_at_phone_width": 13}
