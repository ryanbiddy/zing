"""Deterministic summaries of producer evidence, with no creative attribution."""

from statistics import median

from myzing.match.evidence import geometry_stats
from .models import Section


def pacing(b, audio):
    shots = b.get("shots", [])
    duration = b["meta"]["duration"]
    unknowns = ["Shot detection can miss gradual changes and very short shots."]
    if not shots or any("shot detection skipped" in w or "shot detection failed" in w for w in b.get("warnings", [])):
        return Section("Cuts and pacing", unknowns=["Shot detection unavailable; cut rate is unknown."])
    lengths = [s["end"] - s["start"] for s in shots]
    cuts = [s["start"] for s in shots[1:]]
    v6_cuts = [e["start_seconds"] for e in b.get("provenance", {}).get("transition_evidence", [])
               if e["signature"] == "hard_cut" and e["confidence"] >= .8]
    disagreement = [t for t in v6_cuts if not any(abs(t-c) <= 2/max(1, b["meta"]["fps"]) for c in cuts)]
    if disagreement:
        unknowns.insert(0, "Pacing uncertain: v6 found additional hard cuts at " + ", ".join(f"{t:.2f}s" for t in disagreement) + "; the shot detector missed them.")
    windows = []
    for start in range(0, max(1, int(duration + .999)), 10):
        end = min(duration, start + 10)
        rate = sum(start <= t < end for t in cuts) * 60 / (end - start)
        previous = windows[-1]["cuts_per_minute"] if windows else rate
        windows.append({"start": start, "end": end, "cuts_per_minute": rate,
                        "change": "faster" if rate > previous else "slower" if rate < previous else "steady"})
    beats = (audio or {}).get("beats", [])
    moments = ((audio or {}).get("structure") or {}).get("moments", [])
    def alignment(times):
        return [{"cut_seconds": t, "nearest_seconds": min(times, key=lambda a: abs(t-a)),
                 "delta_seconds": t-min(times, key=lambda a: abs(t-a))} for t in cuts] if times else None
    beat_pairs = alignment(beats)
    drop_pairs = alignment([m["time"] for m in moments if m["kind"] == "drop"])
    if not beats:
        unknowns.append("No supported beat grid; cuts on beats are unknown.")
    if not drop_pairs:
        unknowns.append("No measured drop alignment; a missed drop remains possible.")
    facts = {"cuts_per_minute": len(cuts)*60/duration, "cut_times": cuts, "shots": shots,
             "v6_additional_cut_times": disagreement,
             "shot_seconds": {"min": min(lengths), "median": median(lengths), "max": max(lengths), "values": lengths},
             "windows": windows, "beat_alignment": beat_pairs, "drop_alignment": drop_pairs,
             "alignment_tolerance_seconds": .08,
             "cuts_on_beats": sum(abs(p["delta_seconds"]) <= .08 for p in beat_pairs) if beat_pairs is not None else None}
    return Section("Cuts and pacing", facts, {"score": None, "basis": b.get("provenance", {}).get("shot_detector", "producer unreported")}, unknowns,
                   [f"Shot detector: {len(cuts)} cuts; {facts['cuts_per_minute']:.1f} per minute. Typical shot: {median(lengths):.2f}s.",
                    "Pace: " + "; ".join(f"{w['start']:g}-{w['end']:g}s {w['cuts_per_minute']:.1f}/min ({w['change']})" for w in windows[:6]) + ("; more windows in card.json." if len(windows) > 6 else "."),
                    *([unknowns[0]] if disagreement else []),
                    "Shot lengths span %.2f-%.2fs." % (min(lengths), max(lengths))])


def transitions(b):
    p = b.get("provenance", {})
    events = p.get("transition_evidence")
    unknowns = ["Signatures describe pixels, not the original effect or editor. Whip/flash reconstruction is unsupported."]
    if events is None:
        return Section("Transitions", unknowns=["Transition detection disabled or unavailable.", *unknowns])
    known = [e for e in events if e["signature"] != "unknown"]
    abstentions = [e for e in events if e["signature"] == "unknown"]
    unknowns += [f"Unclassified change at {e['start_seconds']:.2f}-{e['end_seconds']:.2f}s: {e['reason']}" for e in abstentions]
    return Section("Transitions", {"events": known, "abstentions": abstentions, "detector_version": p.get("transition_detector_version")},
                   {"kind": "heuristic; not probability", "events": [{"start_seconds": e["start_seconds"], "score": e["confidence"]} for e in events]}, unknowns,
                   [f"{e['signature'].replace('_', ' ')} at {e['start_seconds']:.2f}-{e['end_seconds']:.2f}s (score {e['confidence']:.2f})." for e in known]
                   or ["Detector ran; no supported transition signature found."])


def captions(b, geometry):
    from myzing.study.text_roles import classify_text, caption_geometry
    from myzing.schemas import Breakdown
    roles = classify_text(Breakdown.from_dict(b), geometry)
    rows = []
    for track in geometry.get("tracks", []):
        samples = track["samples"]
        if not samples:
            continue
        boxes = [s["box"] for s in samples]
        box = [median(v[i] for v in boxes) for i in range(4)]
        y = (box[1] + box[3])/2
        text = track["text"]
        height = track.get("median_text_height")
        # Geometry heights are fractions of frame HEIGHT, not the short side.
        size = height * b["meta"]["height"] / min(b["meta"]["width"], b["meta"]["height"]) * 100 if height is not None else None
        matched_roles = {e["role"] for e in roles["events"] if track["id"] in e["features"]["matched_tracks"]}
        role = next(iter(matched_roles)) if len(matched_roles) == 1 else "unclassified text"
        if track["kind"] == "overlay":
            role = "persistent overlay"
        rows.append({"id": track["id"], "kind": role, "geometry_kind": track["kind"], "text": text, "box": box,
                     "zone": "top" if y < .3 else "center" if y < .6 else "lower" if y < .85 else "bottom",
                     "size_percent_short_side": size, "case": "upper" if text.isupper() else "lower" if text.islower() else "mixed",
                     "motion": track["motion"], "samples": samples,
                     "display": "cumulative word popping" if track["motion"] == "popping" else "phrase in samples" if median(len(s["text"].split()) for s in samples) > 1 else "single word in samples"})
    detections = [{"t": f["t"], "text": d["text"], "appearance": d.get("appearance", {}), "confidence": d.get("confidence")}
                  for f in geometry.get("frames", []) for d in f["detections"]
                  if d.get("validation", {}).get("accepted", geometry.get("version", 1) == 1 and (d.get("confidence") or 0) >= .75)]
    fonts = []
    for t in (geometry.get("font_candidates") or {}).get("tracks", []):
        candidates = t.get("candidates", [])[:3]
        fonts.append({"track_id": t.get("track_id", t.get("id")), "original_font": "unknown",
                      "candidates": [{**c, "label": "best substitute" if c.get("score", 0) < .9 else "plausible candidate; original unknown"} for c in candidates]})
    unknowns = ["Original font, drop shadow and highlight timing/color are unknown.",
                "Sparse OCR cannot prove word-by-word switching or distinguish every title from a caption."]
    if not rows:
        unknowns.append("No accepted text tracks; this does not prove the video has no text.")
    if not fonts:
        unknowns.append("Font candidates unavailable; prepare local OCR assets and install myzing[fonts].")
    facts = {"tracks": rows, "appearance_samples": detections, "font_candidates": fonts,
             "coverage": geometry.get("coverage", {}), "text_roles": roles,
             "caption_geometry_summary": geometry_stats(caption_geometry(geometry, roles))}
    display_rows = sorted(rows, key=lambda r: len(r["samples"])*min(80, len(r["text"])), reverse=True)
    lines = [f"{len(rows)} accepted OCR tracks; {sum(r['kind'] == 'caption' for r in rows)} speech-caption candidates (heuristic)."] if rows else []
    lines += [f"{r['kind']}: {r['zone']}, {r['case']}, {r['motion']}, {r['display']}; " +
             (f"ink height {r['size_percent_short_side']:.1f}% of short side. " if r['size_percent_short_side'] is not None else "ink height unknown. ") +
             f"OCR: {r['text'][:100]}" for r in display_rows]
    widths = [d["appearance"]["stroke_width_px"] for d in detections if d["appearance"].get("stroke_width_px") is not None]
    plates = [d["appearance"]["plate_present"] for d in detections if d["appearance"].get("plate_present") is not None]
    facts["stroke_width_px_median"] = median(widths) if widths else None
    facts["plate_sample_fraction"] = sum(plates)/len(plates) if plates else None
    facts["shadow"] = None
    facts["highlight_color"] = None
    if widths:
        lines.insert(2, f"Sampled outline width {median(widths):.1f}px; plate evidence in {sum(plates)}/{len(plates)} measured regions.")
    if fonts and fonts[0]["candidates"]:
        candidate = fonts[0]["candidates"][0]
        lines.insert(3, f"Font candidate for track {fonts[0]['track_id']}: {candidate.get('family', candidate.get('font_id'))}, {candidate['label']} (score {candidate['score']:.2f}).")
    return Section("Captions and on-screen text", facts,
                   {"kind": "sampled OCR and heuristic geometry" if rows else "no accepted text tracks; absence unproven", "scores": [d["confidence"] for d in detections]},
                   unknowns + geometry.get("warnings", []), lines or ["Text style is unknown."])


def color(measurement):
    unknowns = ["Original LUT/preset and skin-specific treatment are unknown. Scene colors include lighting, objects and text.",
                "A clip-specific LUT approximation can be fitted with zing color match."]
    if not measurement:
        return Section("Color look", unknowns=["Color measurement unavailable; install myzing[color] and check SDR input tags.", *unknowns])
    a = measurement["aggregate"]
    tint = "red" if a['ab_mean'][0] > 2 else "green" if a['ab_mean'][0] < -2 else "neutral tint"
    warmth = "yellow/warm" if a['ab_mean'][1] > 2 else "blue/cool" if a['ab_mean'][1] < -2 else "neutral warmth"
    return Section("Color look", {**a, "swatches": measurement.get("swatches", []), "coverage": measurement["coverage"]},
                   {"score": measurement["confidence"], "kind": "heuristic; SDR assumption"}, unknowns + measurement.get("warnings", []),
                   [f"Contrast {a['contrast']:.1f} L*; median chroma {a['saturation'][2]:.1f}.",
                    f"Sampled colors lean {warmth}, {tint} (Lab a* {a['ab_mean'][0]:+.1f}, b* {a['ab_mean'][1]:+.1f})."])


def framing(b, geometry):
    width, height = b["meta"]["width"], b["meta"]["height"]
    faces = [{"t": f["t"], "box": box} for f in geometry.get("frames", []) for box in (f.get("face_boxes") or [])]
    facts = {"width": width, "height": height, "aspect": width/height, "face_samples": faces,
             "vertical_safe_area": {"box": [.06, .08, .84, .8], "basis": "Zing 9:16 UI reserve recommendation, not measured source safety"}}
    lines = [f"{width} x {height}; aspect {width/height:.3f}:1."]
    if faces:
        facts.update(face_center=[median((f['box'][i] + f['box'][i+2])/2 for f in faces) for i in (0, 1)],
                     face_height_percent=100*median(f['box'][3]-f['box'][1] for f in faces),
                     headroom_percent=100*median(f['box'][1] for f in faces))
        lines.append(f"Sampled face height {facts['face_height_percent']:.1f}% of frame; top-of-face gap {facts['headroom_percent']:.1f}%.")
    return Section("Framing", facts, {"dimensions": "probed", "faces": "sampled YuNet boxes; no identity"},
                   ["Punch-ins cannot be distinguished reliably from camera/subject movement.",
                    "Top-of-face gap is not hair/head clearance. Unsampled subjects and app UI safety remain unknown."] +
                   ([] if faces else ["Face placement, face size and headroom are unknown; no accepted local face evidence."]), lines)


def audio_section(b, audio):
    base = b.get("audio", {})
    warnings = b.get("warnings", [])
    vad_failed = any(any(k in w.lower() for k in ("vad", "speech", "audio")) and any(k in w.lower() for k in ("skip", "fail", "unavailable", "not installed", "no audio")) for w in warnings)
    speech = base.get("speech_ratio") if not vad_failed and b.get("provenance", {}).get("vad") else None
    music = base.get("has_music") if base.get("music_confidence", 0) > 0 else None
    facts = {"speech_share": speech, "music_presence_candidate": music, "tempo": (audio or {}).get("tempo"),
             "loudness": (audio or {}).get("loudness"), "structure": (audio or {}).get("structure"),
             "analyzed_seconds": (audio or {}).get("duration_seconds"), "truncated": (audio or {}).get("truncated"),
             "ducking": None}
    lines = [(f"Speech activity covers {speech:.0%} of the clip (VAD)." if speech is not None else "Speech share unknown."),
             "Music presence: " + ("candidate detected (gap-floor heuristic)." if music else "not supported by gap-floor heuristic." if music is False else "unknown.")]
    if audio:
        tempo = audio["tempo"]
        lines.append(f"Tempo {tempo['bpm']:.1f} BPM." if tempo.get("bpm") else f"Tempo {tempo['status']}; no global beat grid.")
        loud = audio["loudness"]
        lines.append(f"Loudness {loud['integrated_lufs']} LUFS; true peak {loud['true_peak_dbtp']} dBTP.")
        moments = (audio.get("structure") or {}).get("moments", [])
        lines.append("Detected moments: " + (", ".join(f"{m['kind']} at {m['time']:.2f}s" for m in moments[:5]) or "none supported") + ".")
    return Section("Audio and music", facts,
                   {"music_score": base.get("music_confidence"), "tempo": (audio or {}).get("tempo", {}).get("confidence"), "basis": "heuristics; loudness is EBU R128"},
                   ["Ducking is unknown from a mixed source; separate stems are needed to establish music gain under speech.",
                    "Music labels can also describe steady voices or machinery."] + ((audio or {}).get("warnings", []) if audio else ["Tempo, drops and integrated loudness unavailable; install myzing[audio] or check the audio stream."]), lines)


def build_sections(b, geometry=None, audio=None, color_measurement=None):
    geometry = geometry or {}
    return {"pacing": pacing(b, audio), "transitions": transitions(b), "captions": captions(b, geometry),
            "color": color(color_measurement), "framing": framing(b, geometry), "audio": audio_section(b, audio)}
