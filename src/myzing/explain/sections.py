"""Deterministic summaries of producer evidence, with no creative attribution.

`facts` keep every measurement; `lines` say the same numbers in editor words;
`unknowns` list every limitation; `not_knowable` is the one short sentence the
readable card shows about what pixels and a mixed export can never reveal.
"""

from statistics import median

from myzing.match.evidence import geometry_stats
from .models import Section
from .plain import (ZONE_PHRASES, aspect_name, color_cast, contrast_word, pace_word, plausible_text, quote,
                    saturation_word, seconds, signed, time_span, word_count)

NOT_KNOWABLE = {
    "pacing": "the editor's timeline and any cut hidden inside fast motion.",
    "transitions": "which effect, preset or plugin made a transition.",
    "captions": "the original font, shadow settings and word-highlight timing.",
    "color": "the original LUT, preset or skin-specific grade.",
    "framing": "whether a zoom was a punch-in or a camera move, and the app safe-zone intent.",
    "audio": "the music level under speech (that needs separate stems) and what the track is.",
}
QUOTE_CONFIDENCE = .85
# card.json is the readable record, not a second copy of the evidence files:
# long lists keep their first entries plus a total, and the evidence path.
MAX_TRACKS, MAX_TRACK_SAMPLES, MAX_LIST = 200, 8, 200


def _bounded(values, limit, name, truncated):
    if isinstance(values, list) and len(values) > limit:
        truncated[name] = len(values)
        return values[:limit]
    return values


def _windows(cuts, duration):
    """Ten-second windows; a final sliver under 2 s joins the previous window."""
    edges = sorted({min(float(e), duration) for e in range(0, max(1, int(duration + .999)), 10)} | {duration})
    if len(edges) > 2 and edges[-1] - edges[-2] < 2:
        edges.pop(-2)
    windows = []
    for start, end in zip(edges, edges[1:]):
        rate = sum(start <= t < end for t in cuts) * 60 / (end - start)
        previous = windows[-1]["cuts_per_minute"] if windows else rate
        windows.append({"start": start, "end": end, "cuts_per_minute": rate,
                        "change": "faster" if rate > previous else "slower" if rate < previous else "steady"})
    return windows


def pacing(b, audio):
    shots = b.get("shots", [])
    duration = b["meta"]["duration"]
    unknowns = ["Shot detection can miss gradual changes and very short shots."]
    if not duration or duration <= 0:
        # A zero-length timeline has no rate; never divide by it.
        return Section("Cuts and pacing", unknowns=["The video has no measurable duration; cut rate is unknown."],
                       lines=["Cut timing unknown: the video has no measurable duration."], not_knowable=NOT_KNOWABLE["pacing"])
    if not shots or any("shot detection skipped" in w or "shot detection failed" in w for w in b.get("warnings", [])):
        return Section("Cuts and pacing", unknowns=["Shot detection unavailable; cut rate is unknown."],
                       lines=["Cut timing unknown: shot detection did not run."], not_knowable=NOT_KNOWABLE["pacing"])
    lengths = [s["end"] - s["start"] for s in shots]
    cuts = [s["start"] for s in shots[1:]]
    fps = b["meta"].get("fps") or 0
    v6_cuts = [e["start_seconds"] for e in b.get("provenance", {}).get("transition_evidence") or []
               if e["signature"] == "hard_cut" and e["confidence"] >= .8]
    disagreement = [t for t in v6_cuts if not any(abs(t-c) <= 2/max(1, fps) for c in cuts)]
    if disagreement:
        unknowns.insert(0, "Pacing uncertain: v6 found additional hard cuts at " + ", ".join(f"{t:.2f}s" for t in disagreement) + "; the shot detector missed them.")
    windows = _windows(cuts, duration)
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
    if not cuts:
        lines = [f"One continuous shot: no cuts detected in {seconds(duration)}."]
    else:
        typical = median(lengths)
        lines = [f"{len(cuts)} cut{'s' if len(cuts) != 1 else ''} in {seconds(duration)}: a new shot about every {seconds(typical)} "
                 f"({pace_word(typical)}; {facts['cuts_per_minute']:.0f} cuts per minute).",
                 f"Shots run {seconds(min(lengths))} to {seconds(max(lengths))}." if max(lengths) - min(lengths) >= .01
                 else f"Every shot runs {seconds(typical)}."]
        if len(windows) > 1 and len({round(w["cuts_per_minute"]) for w in windows}) > 1:
            lines.append("Cuts per minute by 10 s window: " + ", ".join(f"{w['cuts_per_minute']:.0f}" for w in windows[:8])
                         + (" (more in card.json)." if len(windows) > 8 else "."))
    if disagreement:
        lines.insert(1, "Detectors disagree: the transition check found extra hard cuts at "
                     + ", ".join(f"{t:.2f}s" for t in disagreement[:5]) + ", so the cut count may be low.")
    return Section("Cuts and pacing", facts, {"score": None, "basis": b.get("provenance", {}).get("shot_detector", "producer unreported")},
                   unknowns, lines, not_knowable=NOT_KNOWABLE["pacing"])


def transitions(b):
    p = b.get("provenance", {})
    events = p.get("transition_evidence")
    unknowns = ["Signatures describe pixels, not the original effect or editor. Whip/flash reconstruction is unsupported."]
    if events is None:
        return Section("Transitions", unknowns=["Transition detection disabled or unavailable.", *unknowns],
                       lines=["Transition effects unknown: the transition check did not run."], not_knowable=NOT_KNOWABLE["transitions"])
    known = [e for e in events if e["signature"] != "unknown"]
    abstentions = [e for e in events if e["signature"] == "unknown"]
    unknowns += [f"Unclassified change at {e['start_seconds']:.2f}-{e['end_seconds']:.2f}s: {e['reason']}" for e in abstentions]
    lines = []
    kinds = {}
    for e in known:
        kinds.setdefault(e["signature"], []).append(e)
    for kind, items in sorted(kinds.items(), key=lambda kv: -len(kv[1])):
        name = kind.replace("_", " ")
        low = min(e["confidence"] for e in items)
        if len(items) == 1:
            span = time_span(items[0]["start_seconds"], items[0]["end_seconds"])
            lines.append(f"1 {name} {span} (score {low:.2f})." if span.startswith("at ") else f"1 {name} ({span}, score {low:.2f}).")
            continue
        shown = ", ".join(time_span(e["start_seconds"], e["end_seconds"]).removeprefix("at ") for e in items[:3])
        more = f" and {len(items)-3} more" if len(items) > 3 else ""
        lines.append(f"{len(items)} {name}s: {shown}{more} (scores {low:.2f} or higher).")
    if not known:
        lines.append("No dissolves, wipes or other transition effects detected.")
    if abstentions:
        lines.append(f"{len(abstentions)} other image change{'s' if len(abstentions) != 1 else ''} could not be classified as an edit; motion or lighting can cause these.")
    return Section("Transitions", {"events": known, "abstentions": abstentions, "detector_version": p.get("transition_detector_version")},
                   {"kind": "heuristic; not probability", "events": [{"start_seconds": e["start_seconds"], "score": e["confidence"]} for e in events]},
                   unknowns, lines, not_knowable=NOT_KNOWABLE["transitions"])


def _track_confidence(track, frames):
    """Median over samples of the weakest OCR line in that sample."""
    values = []
    for sample in track["samples"]:
        index = sample.get("sample_index")
        if not isinstance(index, int) or not 0 <= index < len(frames):
            continue
        detections = frames[index].get("detections", [])
        scores = [detections[i].get("confidence") for i in sample.get("detection_indices", []) if 0 <= i < len(detections)]
        scores = [s for s in scores if isinstance(s, (int, float))]
        if scores:
            values.append(min(scores))
    return median(values) if values else None


ROLE_WORDS = {"caption": ("speech caption", "speech captions"), "title": ("title", "titles"), "credit": ("credit", "credits"),
              "scene_text": ("not matched to speech (signs, screens or titles)",) * 2,
              "persistent overlay": ("persistent overlay", "persistent overlays"),
              "unclassified text": ("unclassified text",) * 2}
STYLED_ROLES = ("caption", "title", "credit", "persistent overlay")


def quotable_rows(rows):
    """Clean reads first, ranked by real words, then OCR confidence, then repeats."""
    return sorted((r for r in rows if r["quotable"]),
                  key=lambda r: (-min(4, word_count(r["text"])), -(r["ocr_confidence"] or 0), -r.get("sample_count", len(r["samples"]))))


def captions(b, geometry):
    from myzing.study.text_roles import classify_text, caption_geometry
    from myzing.schemas import Breakdown
    roles = classify_text(Breakdown.from_dict(b), geometry)
    frames = geometry.get("frames", [])
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
        confidence = _track_confidence(track, frames)
        quotable = bool(confidence is not None and confidence >= QUOTE_CONFIDENCE
                        and (len(samples) >= 2 or confidence >= .95) and plausible_text(text))
        rows.append({"id": track["id"], "kind": role, "geometry_kind": track["kind"], "text": text, "box": box,
                     "zone": "top" if y < .3 else "center" if y < .6 else "lower" if y < .85 else "bottom",
                     "size_percent_short_side": size, "case": "upper" if text.isupper() else "lower" if text.islower() else "mixed",
                     "motion": track["motion"], "samples": samples, "ocr_confidence": confidence, "quotable": quotable,
                     "display": "cumulative word popping" if track["motion"] == "popping" else "phrase in samples" if median(len(s["text"].split()) for s in samples) > 1 else "single word in samples"})
    detections = [{"t": f["t"], "text": d["text"], "appearance": d.get("appearance", {}), "confidence": d.get("confidence")}
                  for f in frames for d in f["detections"]
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
    truncated = {}
    for r in rows:
        r["sample_count"] = len(r["samples"])
        r["samples"] = r["samples"][:MAX_TRACK_SAMPLES]
    bounded_roles = {**roles, "events": _bounded(roles.get("events", []), MAX_LIST, "text_roles.events", truncated)}
    facts = {"tracks": _bounded(rows, MAX_TRACKS, "tracks", truncated),
             "appearance_samples": _bounded(detections, MAX_LIST, "appearance_samples", truncated),
             "font_candidates": _bounded(fonts, MAX_LIST, "font_candidates", truncated),
             "coverage": geometry.get("coverage", {}), "text_roles": bounded_roles,
             "truncated": {"totals": truncated, "full_lists": "evidence caption-geometry.json"} if truncated else None,
             "quote_rule": f"median OCR confidence >= {QUOTE_CONFIDENCE}, two samples (or >= 0.95), and word-like text",
             "caption_geometry_summary": geometry_stats(caption_geometry(geometry, roles))}
    widths = [d["appearance"]["stroke_width_px"] for d in detections if d["appearance"].get("stroke_width_px") is not None]
    plates = [d["appearance"]["plate_present"] for d in detections if d["appearance"].get("plate_present") is not None]
    facts["stroke_width_px_median"] = median(widths) if widths else None
    facts["plate_sample_fraction"] = sum(plates)/len(plates) if plates else None
    facts["shadow"] = None
    facts["highlight_color"] = None
    if not rows:
        lines = ["No on-screen text was read in the sampled frames." if frames else
                 "On-screen text unknown: OCR did not run (prepare local OCR assets)."]
    else:
        counts = {}
        for r in rows:
            counts[r["kind"]] = counts.get(r["kind"], 0) + 1
        lines = [f"{len(rows)} text region{'s' if len(rows) != 1 else ''} read: " + ", ".join(
            f"{n} {ROLE_WORDS.get(k, (k, k))[n != 1]}" for k, n in sorted(counts.items(), key=lambda kv: -kv[1])) + "."]
        spoken = [r for r in rows if r["kind"] == "caption"]
        weak_captions = len(spoken) < 2 and not any(r["quotable"] for r in spoken)
        styled = [r for r in rows if r["kind"] in STYLED_ROLES]
        for r in sorted(styled, key=lambda r: -r.get("sample_count", len(r["samples"])))[:2]:
            size = f", ink about {r['size_percent_short_side']:.0f}% of the short side" if r["size_percent_short_side"] is not None else ""
            label = "Caption-like text (role uncertain)" if r["kind"] == "caption" and weak_captions else r["kind"].capitalize()
            lines.append(f"{label} style: {ZONE_PHRASES[r['zone']]}, {r['case']} case, {r['display']}{size}.")
        quotes = quotable_rows(rows)
        if quotes:
            lines.append("Clearly read: " + ", ".join(quote(r["text"]) for r in quotes[:3]) + ".")
        else:
            lines.append("None of it read cleanly enough to quote; raw OCR is in card.json.")
        if styled and widths:
            lines.append(f"Text outline about {median(widths):.1f}px; a background plate in {sum(plates)}/{len(plates)} measured regions.")
        if styled and fonts and fonts[0]["candidates"]:
            candidate = fonts[0]["candidates"][0]
            strength = "weak" if candidate["score"] < .5 else "moderate" if candidate["score"] < .9 else "close"
            lines.append(f"Closest bundled font: {candidate.get('family', candidate.get('font_id'))} ({strength} match, "
                         f"score {candidate['score']:.2f}); a substitute, not the original.")
    return Section("Captions and on-screen text", facts,
                   {"kind": "sampled OCR and heuristic geometry" if rows else "no accepted text tracks; absence unproven", "scores": [d["confidence"] for d in detections][:MAX_LIST * 5]},
                   unknowns + _bounded(geometry.get("warnings", []), 50, "warnings", {}), lines, not_knowable=NOT_KNOWABLE["captions"])


def color(measurement, error=None):
    unknowns = ["Original LUT/preset and skin-specific treatment are unknown. Scene colors include lighting, objects and text.",
                "A clip-specific LUT approximation can be fitted with zing color match."]
    if not measurement:
        reason = error or "install myzing[color] and check SDR input tags."
        return Section("Color look", unknowns=[f"Color measurement unavailable: {reason}", *unknowns],
                       lines=[f"Color unknown: {reason}"], not_knowable=NOT_KNOWABLE["color"])
    a = measurement["aggregate"]
    cast = color_cast(*a["ab_mean"][:2])
    chroma = a["saturation"][2]
    saturation = saturation_word(chroma)
    lines = [f"{contrast_word(a['contrast']).capitalize()} contrast (L* spread {a['contrast']:.0f}); "
             + (f"{saturation} (median chroma {chroma:.0f})." if saturation.startswith("black") else f"{saturation} color (median chroma {chroma:.0f})."),
             f"Sampled colors {'have' if cast['temperature'] == 'tint' else 'are'} {cast['phrase']} "
             f"(Lab a* {signed(a['ab_mean'][0])}, b* {signed(a['ab_mean'][1])})."]
    return Section("Color look", {**a, "swatches": measurement.get("swatches", []), "coverage": measurement["coverage"],
                                  "cast": cast, "contrast_word": contrast_word(a["contrast"]), "saturation_word": saturation_word(chroma)},
                   {"score": measurement["confidence"], "kind": "assumes SDR video; scene objects and lighting count"}, unknowns + measurement.get("warnings", []),
                   lines, not_knowable=NOT_KNOWABLE["color"])


def framing(b, geometry, display=None, matte=None):
    display = display or {}
    stored_w, stored_h = display.get("stored_width") or b["meta"]["width"], display.get("stored_height") or b["meta"]["height"]
    width, height = display.get("display_width") or b["meta"]["width"], display.get("display_height") or b["meta"]["height"]
    face_frames = [f for f in geometry.get("frames", []) if f.get("face_boxes") is not None]
    faces = [{"t": f["t"], "box": box} for f in face_frames for box in (f.get("face_boxes") or [])]
    facts = {"width": width, "height": height, "aspect": width/height, "face_samples": faces,
             "stored_width": stored_w, "stored_height": stored_h,
             "rotation_degrees": display.get("rotation", 0), "sample_aspect_ratio": display.get("sample_aspect_ratio"),
             "face_sampled_frames": len(face_frames),
             "face_presence": (sum(bool(f["face_boxes"]) for f in face_frames) / len(face_frames)) if face_frames else None,
             "matte": matte}
    lines = [f"{width} x {height}, {aspect_name(width, height)}."]
    notes = []
    if display.get("rotation"):
        notes.append(f"rotated {display['rotation']:g} degrees")
    if display.get("sample_aspect_ratio") not in (None, "1:1"):
        notes.append(f"pixel aspect {display['sample_aspect_ratio']}")
    if notes:
        lines[0] = lines[0][:-1] + f" (stored {stored_w} x {stored_h}, {', '.join(notes)})."
    unknowns = ["Punch-ins cannot be distinguished reliably from camera/subject movement.",
                "Top-of-face gap is not hair/head clearance. Unsampled subjects and app UI safety remain unknown.",
                "Blurred or textured fill bars are not detected; only solid bars are measured."]
    if matte and matte.get("status") == "measured":
        if matte["kind"] == "none":
            lines.append(f"Full frame used: no letterbox or pillarbox bars in {matte['samples_informative']} sampled frames.")
        else:
            sides = {"letterbox": "top and bottom", "pillarbox": "left and right", "windowbox": "on all four sides"}[matte["kind"]]
            aw, ah = matte["active_size"]
            lines.append(f"{matte['kind'].capitalize()}ed: solid bars {sides}; the picture fills about {aw} x {ah} ({aspect_name(aw, ah)}).")
    else:
        unknowns.append("Baked-in bars unknown: " + ((matte or {}).get("reason") or "the matte check did not run."))
    if faces:
        facts.update(face_center=[median((f['box'][i] + f['box'][i+2])/2 for f in faces) for i in (0, 1)],
                     face_height_percent=100*median(f['box'][3]-f['box'][1] for f in faces),
                     headroom_percent=100*median(f['box'][1] for f in faces))
        lines.append(f"A face appears in {facts['face_presence']:.0%} of sampled frames, about {facts['face_height_percent']:.0f}% of the frame height, "
                     f"its top {facts['headroom_percent']:.0f}% below the top edge.")
    else:
        unknowns.append("Face placement, face size and headroom are unknown; no accepted local face evidence.")
        lines.append("No face found in sampled frames." if face_frames else "Face placement unknown: face detection did not run.")
    return Section("Framing", facts, {"dimensions": "probed display size (rotation and pixel aspect applied)",
                                      "faces": "sampled YuNet boxes; no identity", "matte": "solid-bar check on sampled frames"},
                   unknowns, lines, not_knowable=NOT_KNOWABLE["framing"])


def music_evidence(speech, music, music_score, tempo):
    """Plain strength for music. The gap-floor heuristic alone is weak: on real
    talking-head footage it fires on room tone, so it never stands as a fact."""
    if tempo and tempo.get("bpm"):
        return "moderate", f"Music likely: a steady beat around {tempo['bpm']:.0f} BPM."
    if music is None:
        return "unknown", "Music unknown: too little measurable non-speech audio."
    if music and speech is not None and speech < .05:
        return "weak", "Sound continues throughout, probably music or score (not verified)."
    if music:
        return "weak", "Sound continues between spoken phrases (room tone, ambience or a music bed); music not confirmed."
    return "weak", "Pauses between speech go quiet; no music bed evident."


def audio_section(b, audio, error=None):
    base = b.get("audio", {})
    warnings = b.get("warnings", [])
    no_stream = any("no audio stream" in w.lower() for w in warnings)
    vad_failed = any(any(k in w.lower() for k in ("vad", "speech", "audio")) and any(k in w.lower() for k in ("skip", "fail", "unavailable", "not installed", "no audio")) for w in warnings)
    speech = base.get("speech_ratio") if not vad_failed and b.get("provenance", {}).get("vad") else None
    music = base.get("has_music") if base.get("music_confidence", 0) > 0 else None
    tempo = (audio or {}).get("tempo")
    strength, music_line = music_evidence(speech, music, base.get("music_confidence"), tempo)
    facts = {"speech_share": speech, "music_presence_candidate": music, "music_evidence": strength, "tempo": tempo,
             "loudness": (audio or {}).get("loudness"), "structure": (audio or {}).get("structure"),
             "analyzed_seconds": (audio or {}).get("duration_seconds"), "truncated": (audio or {}).get("truncated"),
             "has_audio_stream": not no_stream, "ducking": None}
    if no_stream:
        lines = ["No audio track in this file."]
    else:
        lines = [(f"Speech for about {speech:.0%} of the clip (voice activity detection)." if speech
                  else "No speech detected." if speech == 0 else "Speech share unknown."), music_line]
    if audio:
        if audio.get("truncated"):
            lines.append(f"Audio measured for the first {seconds(audio['duration_seconds'])} of {seconds(b['meta']['duration'])} only; "
                         "tempo, loudness and moments describe that part.")
        lines.append(f"Tempo: {tempo['bpm']:.1f} BPM." if tempo.get("bpm") else "No steady beat found.")
        loud = audio["loudness"]
        if loud.get("integrated_lufs") is not None:
            lines.append(f"Loudness {loud['integrated_lufs']} LUFS integrated; true peak {loud['true_peak_dbtp']} dBTP.")
        moments = (audio.get("structure") or {}).get("moments", [])
        drops = [m for m in moments if m["kind"] == "drop"]
        changes = [m for m in moments if m["kind"] != "drop"]
        if drops:
            lines.append("Possible drop " + ", ".join(f"at {m['time']:.2f}s" for m in drops[:3]) + " (sudden energy rise; unverified).")
        if changes:
            lines.append("Mix level shifts at " + ", ".join(f"{m['time']:.1f}s" for m in changes[:5])
                         + " (loudness changes, not identified song sections).")
    unknowns = ["Ducking is unknown from a mixed source; separate stems are needed to establish music gain under speech.",
                "Music labels can also describe steady voices or machinery."]
    if audio:
        unknowns += audio.get("warnings", [])
    elif no_stream:
        unknowns.append("No audio stream; speech, music, tempo and loudness do not apply.")
    else:
        unknowns.append("Tempo, drops and integrated loudness unavailable: " + (error or "install myzing[audio] or check the audio stream."))
    return Section("Audio and music", facts,
                   {"music_score": base.get("music_confidence"), "music_evidence": strength,
                    "tempo": (audio or {}).get("tempo", {}).get("confidence"), "basis": "heuristics; loudness is EBU R128"},
                   unknowns, lines, not_knowable=NOT_KNOWABLE["audio"])


def build_sections(b, geometry=None, audio=None, color_measurement=None, *, display=None, matte=None,
                   color_error=None, audio_error=None):
    geometry = geometry or {}
    shown = b
    if display and display.get("display_width") and display.get("display_height"):
        # Caption sizes and framing use the displayed picture, not storage.
        shown = {**b, "meta": {**b["meta"], "width": display["display_width"], "height": display["display_height"]}}
    return {"pacing": pacing(b, audio), "transitions": transitions(b), "captions": captions(shown, geometry),
            "color": color(color_measurement, color_error), "framing": framing(b, geometry, display, matte),
            "audio": audio_section(b, audio, audio_error)}
