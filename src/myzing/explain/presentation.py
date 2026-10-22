"""Phone-size card and concise prose, drawn from the same evidence record."""

from pathlib import Path


def markdown(card):
    lines = [f"# Style card: {Path(card.source).name}", "", *card.summary, "",
             "Confidence scores are heuristic evidence, not probabilities. Full samples and gaps: card.json."]
    for key, section in card.sections.items():
        limit = 5 if key == "audio" else 4 if key in ("pacing", "captions") else 3
        lines += ["", f"## {section.title}", "", *(section.lines[:limit] or ["No supported measurement."])]
        if len(section.lines) > limit:
            lines.append(f"{len(section.lines)-limit} more observations in card.json.")
        lines += ["", "Confidence: " + confidence_text(section), "",
                  "Unknown: " + " ".join(section.unknowns[:2])]
        if key == "pacing":
            facts = section.facts
            pairs = facts.get("beat_alignment")
            if pairs is not None:
                lines += ["", f"{facts['cuts_on_beats']}/{len(pairs)} cuts fall within 80 ms of a supported beat."]
            drops = facts.get("drop_alignment")
            if drops:
                lines.append(f"{sum(abs(p['delta_seconds']) <= .08 for p in drops)}/{len(drops)} cuts fall within 80 ms of a detected drop.")
        if len(section.unknowns) > 2:
            lines.append(f"{len(section.unknowns)-2} further limitations in card.json.")
        comparison = card.comparison.get("sections", {}).get(key)
        if comparison:
            lines += ["", "Comparison: " + comparison_text(comparison)]
    lines += ["", "## Get this look", "", f"Reusable StyleRecipe: `{card.recipe_path}`.",
              "Use local clips you have permission to edit. Match makes a new project; color fits a clip-specific approximation.",
              "", "```sh", *card.commands, "```", "",
              "The original font, LUT, preset, editor project, hidden source layers and exact caption animation cannot be recovered from this export.",
              ""]
    return "\n".join(lines)


def confidence_text(section):
    c = section.confidence
    if not c:
        return "unmeasured"
    if c.get("score") is not None:
        return f"{c['score']:.2f}; {c.get('kind', c.get('basis', 'heuristic'))}"
    return c.get("basis", c.get("kind", "Probed dimensions; sampled face evidence where available."))


def comparison_text(comparison):
    def value(v):
        if isinstance(v, float):
            return f"{v:.3g}"
        if isinstance(v, list):
            return "[" + ", ".join(value(x) for x in v) + "]"
        return "unknown" if v is None else str(v)
    parts = [f"{name}: {value(m.get('target'))} vs {value(m.get('observed'))} ({m['status']})" for name, m in comparison["metrics"].items()]
    return comparison["status"] + ". " + "; ".join(parts)


def render_png(card, media, path):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError("The PNG card needs Pillow; install myzing[memes] (no model download).") from exc
    from myzing.inspect.media import Decoder
    font_path = Path(__file__).resolve().parents[1] / "_data/fonts/IBMPlexSans.ttf"
    font = ImageFont.truetype(str(font_path), 30)
    title = ImageFont.truetype(str(font_path), 42)
    small = ImageFont.truetype(str(font_path), 26)
    canvas = Image.new("RGB", (800, 8000), "#f5f2eb")
    draw = ImageDraw.Draw(canvas)
    y = 30
    def text(message, selected=font, color="#263335"):
        nonlocal y
        for paragraph in str(message).splitlines():
            line = ""
            for word in paragraph.split():
                candidate = (line + " " + word).strip()
                if line and draw.textlength(candidate, font=selected) > 728:
                    draw.text((36, y), line, font=selected, fill=color)
                    y += selected.size + 9
                    line = ""
                # Split only tokens wider than a whole line (paths/OCR noise).
                while draw.textlength(word, font=selected) > 728:
                    end = len(word)
                    while draw.textlength(word[:end], font=selected) > 728:
                        end -= 1
                    draw.text((36, y), word[:end], font=selected, fill=color)
                    y += selected.size + 9
                    word = word[end:]
                line = (line + " " + word).strip()
            draw.text((36, y), line, font=selected, fill=color)
            y += selected.size + 9
    text("ZING / STYLE CARD", title)
    text(Path(card.source).name[:70], small)
    text(f"{card.duration_seconds:.1f}s / measured export / original settings unknown", small)
    y += 10
    decoder = Decoder()
    times = [card.duration_seconds*f for f in (.15, .5, .85)]
    frames = []
    for i, t in enumerate(times):
        x = 36 + i*248
        try:
            data = decoder.frame(Path(media), t, 232, 170)
            canvas.paste(Image.frombytes("RGB", (232, 170), data), (x, y))
            frames.append({"time": t, "box": [x, y, x+232, y+170]})
        except Exception as exc:
            card.warnings.append(f"Key frame {t:.2f}s unavailable: {exc}")
            draw.rectangle((x, y, x+232, y+170), fill="#d7d6ce")
            draw.text((x+10, y+65), "Unavailable", font=small, fill="#263335")
        draw.text((x, y+174), f"{t:.2f}s", font=small, fill="#263335")
    y += 224
    strip_y = y
    duration = card.duration_seconds
    def project(t):
        return 36 + round(min(1, max(0, t/duration))*728)
    text("PACING / detected shot boundaries", small)
    for i, shot in enumerate(card.sections["pacing"].facts.get("shots", [])):
        draw.rectangle((project(shot['start']), y, project(shot['end']), y+26), fill=("#247c75", "#b5d3bd")[i%2], outline="#f5f2eb")
    if not card.sections["pacing"].facts:
        text("Unknown", small)
    y += 44
    draw.text((36, y), "0s", font=small, fill="#263335")
    draw.text((764, y), f"{duration:.1f}s", font=small, fill="#263335", anchor="rt")
    y += small.size+9
    for key, section in card.sections.items():
        y += 16
        draw.line((36, y, 764, y), fill="#c6c9c0", width=2)
        y += 16
        text(section.title, title)
        for line in section.lines[:2] or ["Unknown; measurement unavailable."]:
            text(line[:210])
        if key == "audio":
            for line in section.lines[2:4]:
                text(line, small)
        text("Confidence: " + confidence_text(section), small, "#52615c")
        if key == "captions":
            rows = section.facts.get("tracks", [])
            if rows:
                # Separate normalized frame diagrams retain the source aspect.
                aspect = card.sections['framing'].facts['aspect']
                bw, bh = (180, int(180/aspect)) if aspect >= 1 else (int(180*aspect), 180)
                for i, row in enumerate(rows[:3]):
                    x = 36+i*248
                    draw.rectangle((x, y, x+bw, y+bh), fill="#dde2d8", outline="#52615c")
                    l, t, r, b = row["box"]
                    draw.rectangle((x+l*bw, y+t*bh, x+r*bw, y+b*bh), outline="#b14b2d", width=3)
                y += bh+12
                text("Sampled text boxes; full-frame coordinates", small)
        if key == "color":
            swatches = section.facts.get("swatches", [])
            for i, swatch in enumerate(swatches[:8]):
                draw.rectangle((36+i*91, y, 120+i*91, y+36), fill=swatch)
            if swatches:
                y += 50
        if key == "audio":
            structure = section.facts.get("structure") or {}
            energy = structure.get("energy", [])
            text("MIX ENERGY / RMS -60 to 0 dBFS", small)
            draw.rectangle((36, y, 764, y+70), fill="#e3e5dc")
            points = [(project(e['time']), y+70-round(min(60, max(0, e['rms_dbfs']+60))/60*70)) for e in energy]
            if len(points) > 1:
                draw.line(points, fill="#247c75", width=3)
            for m in structure.get("moments", []):
                x = project(m['time'])
                draw.line((x, y, x, y+70), fill="#b14b2d", width=2)
            y += 80
            text("Red: detected moments (drops/hits/changes)." if energy else "Energy and moments unknown.", small)
        if section.unknowns:
            text("Unknown / " + section.unknowns[0], small, "#78503d")
        comparison = card.comparison.get("sections", {}).get(key)
        if comparison:
            text("Against / " + comparison["status"] + "; numbers in card.md", small)
    y += 20
    text("Get this look", title)
    text("Open card.md for exact match and color commands. Reuse style-recipe.json.")
    text("Original fonts, LUTs and hidden layers remain unknown. Review sampled evidence before copying the style.", small)
    canvas.crop((0, 0, 800, y+28)).save(path, "PNG")
    return {"width": 800, "height": y+28, "keyframes": frames, "pacing_strip_y": strip_y,
            "phone_width": 400, "minimum_font_at_phone_width": 13}
