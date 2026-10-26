"""Prevent source text cards from being cropped by subject reframing."""

from dataclasses import replace


def protect_text(framing, clip, geometry, requested, width, height):
    if requested not in ("auto", "reframe", "zoomfill"):
        return framing
    samples = [(s["t"], s["boxes"], s["words"]) for s in geometry.get("protected_samples", [])
               if clip.src_in <= s["t"] < clip.src_out]
    for frame in geometry.get("frames", []):
        if not clip.src_in <= frame["t"] < clip.src_out:
            continue
        detections = [d for d in frame.get("detections", []) if (d.get("confidence") or 0) >= .5]
        boxes = [d.get("appearance", {}).get("ink_box") or d["box"] for d in detections]
        if boxes:
            samples.append((frame["t"], boxes, sum(len(d["text"].split()) for d in detections)))
    # Older sidecars may retain tracks without raw OCR frames.
    if not samples:
        by_time = {}
        for track in geometry.get("tracks", []):
            for s in track.get("samples", []):
                if clip.src_in <= s["t"] < clip.src_out:
                    boxes, count = by_time.get(s["t"], ([], 0))
                    by_time[s["t"]] = (boxes + (s.get("line_boxes") or [s["box"]]),
                                        count + len(s.get("text", track["text"]).split()))
        samples = [(time, boxes, count) for time, (boxes, count) in sorted(by_time.items())]
    cards = []
    for time, boxes, words in samples:
        area = sum((b[2]-b[0])*(b[3]-b[1]) for b in boxes)
        span = max(b[2] for b in boxes)-min(b[0] for b in boxes)
        tall = max(b[3] for b in boxes)-min(b[1] for b in boxes)
        if words >= 8 and (area >= .08 or (span >= .55 and tall >= .18)):
            cards.append((time, boxes, words, area))
    if not cards:
        return framing
    # Check every crop extremum against all observed card text. Interpolation
    # remains inside those extrema; the full shot is protected between samples.
    centers = [(framing.center_x, framing.center_y), *[(k.center_x, k.center_y) for k in framing.keyframes]]
    safe = all(x-framing.width/2 <= b[0]*framing.source_width-2
               and x+framing.width/2 >= b[2]*framing.source_width+2
               and y-framing.height/2 <= b[1]*framing.source_height-2
               and y+framing.height/2 >= b[3]*framing.source_height+2
               for _, boxes, _, _ in cards for b in boxes for x, y in centers)
    evidence = {"decision": "retain crop" if safe else "full-source blurfill", "sample_times": [c[0] for c in cards],
                "word_counts": [c[2] for c in cards], "text_area": [c[3] for c in cards],
                "samples": [{"t": c[0], "boxes": c[1], "words": c[2]} for c in cards],
                "basis": "source OCR text geometry; >=8 words and >=8% area or broad multiline text"}
    note = (f"Shot {clip.id} ({clip.src_in:g}-{clip.src_out:g}s): measured text-heavy graphic; "
            + ("all observed text fits every crop extremum." if safe else "using full-source blurfill to avoid cropping text."))
    if not safe:
        from .framing import centered_framing
        framing = centered_framing("blurfill", framing.source_width, framing.source_height, width, height)
    return replace(framing, picture={**framing.picture, "text_safety": evidence}, warnings=[*framing.warnings, note])
