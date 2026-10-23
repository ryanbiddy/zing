"""'What a viewer notices': three to five editor-language lines.

Each line restates measured section facts; weak evidence keeps its hedge and a
missing measurement says unknown. Nothing here is a new measurement.
"""

from __future__ import annotations

from .plain import ZONE_PHRASES, aspect_name, pace_word, quote, seconds


def _subject(framing, audio):
    presence, height = framing.get("face_presence"), framing.get("face_height_percent")
    speech = audio.get("speech_share")
    if presence is not None and height is not None and presence >= .6 and height >= 20 and (speech or 0) >= .4:
        return "talking-head"
    if presence is not None and presence >= .3:
        return "people-on-camera"
    return None


def _shots(pacing, framing, audio, duration):
    shape = aspect_name(framing["width"], framing["height"])
    subject = _subject(framing, audio)
    matte = framing.get("matte") or {}
    if matte.get("status") == "measured" and matte.get("kind") not in (None, "none"):
        aw, ah = matte["active_size"]
        boxed = f", {matte['kind']}ed (picture about {aw} x {ah})"
    elif matte.get("status") == "measured":
        boxed = ", full frame"
    else:
        boxed = ""
    if not pacing:
        return f"{shape.capitalize()} video{boxed}; cut timing unknown."
    cuts = len(pacing["cut_times"])
    doubt = " (may be undercounted)" if pacing.get("v6_additional_cut_times") else ""
    if cuts == 0:
        what = f"{subject} shot" if subject == "talking-head" else "shot"
        return f"One continuous {shape} {what}, {seconds(duration)} with no cuts{doubt}{boxed}."
    typical = pacing["shot_seconds"]["median"]
    kind = "montage" if typical < 2.5 and cuts >= 4 else "edit"
    people = " with people on camera" if subject else ""
    return (f"{pace_word(typical).capitalize()} {shape} {kind}{people}: {cuts} cut{'s' if cuts != 1 else ''} in "
            f"{seconds(duration)}, typical shot {seconds(typical)}{doubt}{boxed}.")


def _transitions(transitions, pacing):
    events = transitions.get("events")
    if events is None or not pacing or not pacing.get("cut_times"):
        return None
    effects = {}
    for e in events:
        if e["signature"] != "hard_cut":
            effects[e["signature"].replace("_", " ")] = effects.get(e["signature"].replace("_", " "), 0) + 1
    if not effects:
        return "Straight cuts; no dissolves or other transition effects detected."
    listed = ", ".join(f"{n} {name}{'s' if n != 1 else ''}" for name, n in effects.items())
    return f"Mostly cuts, plus {listed}."


def _text(captions, ocr_ran):
    from .sections import quotable_rows
    rows = captions.get("tracks") or []
    if not rows:
        return "No on-screen text read in the sampled frames." if ocr_ran else "On-screen text unknown (OCR did not run)."
    clean = quotable_rows(rows)
    sample = f", such as {quote(clean[0]['text'], 40)}" if clean else ""
    spoken = [r for r in rows if r["kind"] == "caption"]
    # One unreadable caption-role track is not enough to call the video captioned.
    if len(spoken) >= 2 or any(r.get("quotable") for r in spoken):
        r = max(spoken, key=lambda r: r.get("sample_count", len(r["samples"])))
        pop = ", word by word" if r["motion"] == "popping" else ""
        return f"Burned-in captions {ZONE_PHRASES[r['zone']]} of the frame, {r['case']} case{pop}."
    if spoken or any(r["kind"] in ("title", "credit", "persistent overlay") for r in rows):
        return f"Titles or large text on screen{sample}; whether any of it is captions is uncertain."
    return f"On-screen text not tied to speech (signs, screens or titles){sample}; no captions found."


def _audio(audio):
    if audio.get("has_audio_stream") is False:
        return "Silent: no audio track."
    speech, strength = audio.get("speech_share"), audio.get("music_evidence")
    bpm = (audio.get("tempo") or {}).get("bpm")
    if speech is None:
        return "Audio content unknown (speech detection did not run)."
    if speech >= .4:
        music = f" over music with a steady beat (~{bpm:.0f} BPM)" if bpm else "; music not confirmed"
        return f"Speech-led audio (talking {speech:.0%} of the time){music}."
    if speech < .05:
        if bpm:
            return f"No speech; music with a steady beat around {bpm:.0f} BPM."
        return ("No speech; continuous sound, probably music or score (not verified)." if strength == "weak" and audio.get("music_presence_candidate")
                else "No speech detected.")
    return f"Some speech ({speech:.0%} of the time)" + (f" over a steady beat (~{bpm:.0f} BPM)." if bpm else "; music not confirmed.")


def _color(color):
    if "cast" not in color:
        return "Color look unknown (measurement unavailable)."
    cast, contrast = color["cast"], color["contrast_word"]
    if color["saturation_word"].startswith("black-and-white"):
        return f"Black-and-white or nearly colorless picture, {contrast} contrast."
    adverb = {"slight": "slightly", "noticeable": "noticeably", "strong": "strongly"}.get(cast["strength"], "")
    if cast["temperature"] == "neutral":
        tone = ", no clear color cast"
    elif cast["temperature"] == "tint":
        tone = f" with a {cast['strength']} {cast['hue']} tint"
    else:
        tone = f" leaning {adverb} {cast['temperature']} ({cast['hue']})"
    return f"{color['saturation_word'].capitalize()} color{tone}; {contrast} contrast."


def viewer_notices(sections, duration, *, ocr_ran=True):
    pacing, framing, audio = sections["pacing"].facts, sections["framing"].facts, sections["audio"].facts
    lines = [_shots(pacing, framing, audio, duration), _transitions(sections["transitions"].facts, pacing),
             _text(sections["captions"].facts, ocr_ran), _audio(audio), _color(sections["color"].facts)]
    return [line for line in lines if line][:5]
