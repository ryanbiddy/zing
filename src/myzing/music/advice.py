"""Explain suitability using measurements. Never identify a song or grant rights."""
from __future__ import annotations

import json
import math
from pathlib import Path
from dataclasses import dataclass, field
from statistics import median

from myzing.contracts import Record
from myzing.audio import analyze


@dataclass
class Advice(Record):
    track: str
    rating: str
    score: int
    reasons: list[dict]
    licensing: str
    measurements: dict = field(default_factory=dict)
    version: int = 1


def talking(brief):
    return bool(brief and any(s in brief.purpose.casefold() for s in ("talk", "speech", "interview", "explain", "dialogue", "voice")))


WEIGHTS = {
    "montage": {"pace": 25, "moment": 25, "energy": 25, "intro": 10},
    "speech-led": {"vocals": 30, "energy": 25, "moment": 20, "intro": 10},
    "general": {"pace": 10, "moment": 10, "energy": 10, "intro": 10},
}


def _percentile(values, fraction):
    return sorted(values)[round((len(values) - 1) * fraction)] if values else None


def _attacks(entry):
    # Map 2.2 counts salient attacks; 2.1 maps only stored every onset.
    return entry.get("attacks_per_second", entry.get("onsets_per_second", 0.0))


REGION_TOLERANCE = .02
SPEECH_SPREAD_DB, SPEECH_ATTACKS = 6.0, 1.5
MONTAGE_RISE_DB, MONTAGE_ATTACKS = 3.0, 1.5


def _regional_pulse(regions, start, end):
    """One pulse from local 16 s regions that agree and cover the excerpt.

    Regions must agree within 2% of their overlap-weighted median BPM (half or
    double time disagrees) and together cover at least 80% of the excerpt.
    """
    overlaps = [(r, min(end, r["end"]) - max(start, r["start"])) for r in regions]
    overlaps = [(r, o) for r, o in overlaps if o > 0]
    if not overlaps or sum(o for _, o in overlaps) < .8 * (end - start):
        return None
    half, acc, reference = sum(o for _, o in overlaps) / 2, 0.0, None
    for r, o in sorted(overlaps, key=lambda x: x[0]["bpm"]):
        acc += o
        if acc >= half:
            reference = r["bpm"]
            break
    if any(abs(r["bpm"] - reference) > REGION_TOLERANCE * reference for r, _ in overlaps):
        return None
    bpm = sum(r["bpm"] * o for r, o in overlaps) / sum(o for _, o in overlaps)
    return (round(bpm, 3), min(r["start"] for r, _ in overlaps), f"{len(overlaps)} agreeing local rhythm regions")


def _window(audio, start, length, pace):
    """Evidence for a complete usable excerpt, not the whole song's extrema."""
    s = audio.structure
    end = min(audio.duration_seconds, start + length)
    energy = [e for e in s.energy if start <= e["time"] < end] if s else []
    levels = [e["rms_dbfs"] for e in energy]
    quarter = max(1, len(levels) // 4)
    rise = median(levels[-quarter:]) - median(levels[:quarter]) if levels else None
    spread = _percentile(levels, .9) - _percentile(levels, .1) if levels else None
    density = sum(_attacks(e) for e in energy) / len(energy) if energy else None
    moments = [m for m in s.moments if start < m.time < end and m.kind in {"drop", "hit", "section_change"}] if s else []
    moment = max(moments, key=lambda m: (m.kind == "drop", m.strength * m.confidence), default=None)
    bpms = [(audio.tempo.bpm, start, "global")] if audio.tempo.bpm else []
    if s and not bpms:
        regional = _regional_pulse(s.rhythm_regions, start, end)
        bpms = [regional] if regional else []
    fits = [(min(abs(pace - 60 / bpm * n) / pace for n in (1, 2, 3, 4, 6, 8, 12, 16)), bpm, time, basis)
            for bpm, time, basis in bpms] if pace else []
    fit = min(fits, default=None)
    intro = None
    if levels:
        ceiling = _percentile(levels, .85)
        intro = next((e["time"] - start for i, e in enumerate(energy)
                      if len(levels[i:i + 4]) == 4 and median(levels[i:i + 4]) >= ceiling - 5), None)
    return {"start": start, "end": end, "rise_db": rise, "spread_db": spread,
            "density": density, "moment": moment, "drops": [m for m in moments if m.kind == "drop"],
            "pace_fit": fit, "has_pulse": bool(bpms), "intro_seconds": intro}


def _points(window, mode, vocal_status):
    fit = window["pace_fit"]
    pace = (1 if fit[0] <= .1 else .7 if fit[0] <= .2 else .4 if fit[0] <= .35 else 0) if fit else 0
    rise, spread, density = (window[k] for k in ("rise_db", "spread_db", "density"))
    active = window["has_pulse"] or (density is not None and density >= MONTAGE_ATTACKS)
    intro = window["intro_seconds"]
    short = min(3., (window["end"] - window["start"]) * .35)
    intro_points = 0 if intro is None else 1 if intro <= short else .5 if intro <= max(short, 6) else 0
    if mode == "speech-led":
        return {"vocals": 1 if vocal_status == "not_detected" else .7 if vocal_status == "unknown" else 0,
                "energy": (1 if spread <= SPEECH_SPREAD_DB and density <= SPEECH_ATTACKS else .5 if spread <= 10 else 0) if spread is not None else 0,
                "moment": 0 if window["drops"] else 1, "intro": intro_points}
    moment = window["moment"]
    return {"pace": pace, "moment": 1 if moment and moment.kind == "drop" else .5 if moment else 0,
            "energy": (1 if rise >= MONTAGE_RISE_DB and active else .4 if active else 0) if rise is not None else 0,
            "intro": intro_points}


def _excerpt(audio, length, pace, mode):
    limit = max(0., audio.duration_seconds - length)
    starts = {0.}
    if audio.structure:
        starts.update(m.time - length / 2 for m in audio.structure.moments
                      if m.kind in {"drop", "hit", "section_change"} and 0 <= m.time - length / 2 <= limit)
        if mode == "speech-led":
            step = max(1., length / 2)
            starts.update(min(limit, i * step) for i in range(int(limit / step) + 2))
    status = audio.structure.vocals.get("status", "unknown") if audio.structure else "unknown"
    windows = [_window(audio, start, length, pace) for start in sorted(starts)]
    return max(windows, key=lambda w: (sum(WEIGHTS[mode][k] * v for k, v in _points(w, mode, status).items()), -w["start"]))


def rate(audio, *, length=30.0, speech=False, pace=None, purpose="", license_record=None, source_duration=None):
    if not math.isfinite(length) or not 0 < length <= 600:
        raise ValueError("target length must be 0 < seconds <= 600")
    if pace is not None and (not math.isfinite(pace) or pace <= 0):
        raise ValueError("reference pace must be positive finite seconds per cut")
    mode = "speech-led" if speech else "montage" if pace is not None or any(
        term in purpose.casefold() for term in ("montage", "music-led", "reveal", "energetic", "hook")) else "general"
    weights = WEIGHTS[mode]
    base = 100 - sum(weights.values())
    reasons, penalty = [], 0
    def add(topic, text, cost=0, time=None, points=None):
        nonlocal penalty
        penalty += cost
        reasons.append({"topic": topic, "reason": text, "penalty": cost, "evidence_time": time,
                        "weight": weights.get(topic, 0), "points": points or 0})
    s = audio.structure
    window = _excerpt(audio, length, pace, mode)
    vocal_status = s.vocals.get("status", "unknown") if s else "unknown"
    points = {k: weights[k] * v for k, v in _points(window, mode, vocal_status).items()}
    start, end = window["start"], window["end"]
    add("excerpt", f"Try source {start:.3f}–{end:.3f}s for this {mode} brief; compare this excerpt before choosing the track.", time=start)
    if window["pace_fit"]:
        error, bpm, time, basis = window["pace_fit"]
        add("pace", f"Use the supported {bpm:g} BPM pulse ({'whole-track tempo' if basis == 'global' else basis}): "
            f"the nearest 1/2/3/4/6/8/12/16-beat cut differs from {pace:g}s reference shots by {error:.0%}. "
            + ("Keep that cut cadence." if error <= .1 else "Adjust the shot pace or choose a closer-tempo track."), time=time, points=points.get("pace"))
    elif pace is None:
        add("pace", "No reference pace was supplied, so cut lengths were not compared with the music. "
            + ("Let speech clauses set the cuts." if speech else
               "Supply --pace (seconds per cut) or a brief with a studied reference to compare cut lengths."
               if window["has_pulse"] else "This excerpt also has no supported pulse for beat cuts."))
    else:
        add("pace", f"No supported pulse covers this excerpt, so the {pace:g}s reference pace cannot be matched to beats. "
            + ("Let speech clauses set the cuts." if speech else
               "Choose an excerpt or track with a steady beat before relying on beat cuts."))
    moment = window["moment"]
    if speech:
        drops = window["drops"]
        add("moment", (f"Avoid the drop at {drops[0].time:.3f}s under dialogue; move the music start or choose a steadier bed." if drops else
                       "No detected drop falls in this excerpt; use it as a speech bed and keep clause boundaries."),
            time=drops[0].time if drops else start, points=points["moment"])
    else:
        add("moment", (f"Place the {moment.kind} at source {moment.time:.3f}s on a reveal; starting at {start:.3f}s puts it {moment.time-start:.3f}s into the edit." if moment else
                       "No usable drop or hit is available in this excerpt; choose a stronger moment for a reveal or use this as a steady bed."),
            time=moment.time if moment else None, points=points["moment"])
    rise, spread, density = (window[k] for k in ("rise_db", "spread_db", "density"))
    if rise is None:
        energy_reason = "Energy evidence is missing; analyze the track again before matching its arc to the edit."
    elif speech:
        # Each sentence names the rule that actually failed (docs/MUSIC.md).
        swings, busy = spread > SPEECH_SPREAD_DB, density > SPEECH_ATTACKS
        energy_reason = f"Excerpt level spread is {spread:.1f} dB with {density:.2f} salient attacks/s. " + (
            "Keep this restrained bed low under speech." if not swings and not busy else
            f"The level swings more than {SPEECH_SPREAD_DB:g} dB; choose a steadier excerpt or automate the bed. " * swings
            + f"More than {SPEECH_ATTACKS:g} attacks/s can compete with speech; choose a sparser excerpt or lower the bed further." * busy).strip()
    else:
        active = window["has_pulse"] or density >= MONTAGE_ATTACKS
        energy_reason = f"Excerpt rises {rise:+.1f} dB from its first to last quarter, with {density:.2f} salient attacks/s. " + (
            "Use that build to support the visual reveal." if rise >= MONTAGE_RISE_DB and active else
            f"It rises less than {MONTAGE_RISE_DB:g} dB; for a reveal, choose an excerpt that builds into the moment." if active else
            f"It has no supported pulse and fewer than {MONTAGE_ATTACKS:g} attacks/s; for a driving montage choose a more active excerpt.")
    add("energy", energy_reason, time=start, points=points["energy"])
    add("vocals", f"Vocals {vocal_status}. " + ("Prefer an instrumental alternative under speech; listen to confirm because harmonic instruments can trigger this warning." if speech and vocal_status == "possible" else
        "Listen for masked vocals before placing dialogue over this track; the heuristic cannot rule them out." if speech else
        "Check that any lyrics suit the images; voices and harmonic instruments can look alike to this heuristic."), points=points.get("vocals"))
    intro = window["intro_seconds"]
    add("intro", f"Energy arrives {intro:.2f}s into the suggested excerpt. " + ("Keep this start for a quick hook." if points["intro"] == weights["intro"] else "Trim the lead-in or reserve it for an intentional build.") if intro is not None else
        "Energy arrival is unknown; audition a start point before building the hook.", time=start + intro if intro is not None else None, points=points["intro"])
    available = source_duration if audio.truncated and source_duration else audio.duration_seconds
    length_text = (f"{available:.2f}s available" if source_duration or not audio.truncated else
                   f"More than {audio.duration_seconds:.0f}s available")
    if audio.truncated:
        length_text += f" (analysis covers the first {audio.duration_seconds:.0f}s)"
    add("duration", f"{length_text} for {length:g}s: " + ("use one continuous excerpt; no loop is needed." if available >= length else "choose a longer track or arrange a loop/edit, which is not automatic."), 28 if available < length else 0)
    l = audio.loudness
    add("loudness", f"Track measures {l.integrated_lufs} LUFS and {l.true_peak_dbtp} dBTP; set excerpt gain " + ("for a 21 LU speech-to-music difference, then measure the render." if speech else "near the -16 LUFS music-led target, then check the encoded peak."), 14 if l.integrated_lufs is None or l.integrated_lufs > -7 else 0)
    add("dynamics", "Automate or compress the large loudness swings before mixing this track." if l.loudness_range_lu is not None and l.loudness_range_lu > 15 else "Keep the measured dynamics unless listening reveals masking; short tracks make LRA less informative.", 10 if l.loudness_range_lu is not None and l.loudness_range_lu > 15 else 0)
    q = s.quality if s else {}
    clipping_cost = 28 if q.get("near_full_scale_fraction", 0) > .001 else 12 if q.get("clipping_suspected") else 0
    add("clipping", "Use a cleaner master if distortion is audible; lower gain/limit overload peaks, but gain cannot repair prior clipping." if clipping_cost else "No measured clipping risk; preserve peak headroom and listen for prior distortion.", clipping_cost)
    add("phase", f"Mono fold-down loss {q.get('mono_loss_db')} dB; channel correlation {q.get('channel_correlation')}. " + ("Choose a mono-safe source before publishing to phone speakers." if q.get("mono_loss_db", 0) < -9 else "Check the final mix on a mono speaker; no severe measured cancellation needs repair."), 35 if q.get("mono_loss_db", 0) < -9 else 0)
    licensing = "Licensing unknown unless the user records it; analysis cannot verify permission."
    if license_record:
        licensing += " User-recorded claim (unverified by Zing): " + str(license_record)
    score = max(0, round(base + sum(points.values()) - penalty))
    return Advice(audio.source, "good" if score >= 80 else "usable" if score >= 55 else "bad", score, reasons, licensing,
                  {"duration_seconds": audio.duration_seconds, "tempo": audio.tempo.to_dict(), "loudness": l.to_dict(),
                   "structure": s.to_dict() if s else None,
                   "scoring": {"mode": mode, "base": base, "weights": weights, "points": points, "quality_penalty": penalty,
                               "source_offset": start, "source_end": end, "rise_db": rise, "spread_db": spread,
                               "rule": "base + weighted excerpt suitability - quality penalties; good >=80, usable >=55"}})


def probe_duration(path):
    """Container duration for tracks longer than the analysis cap, else None."""
    import shutil
    import subprocess
    probe = shutil.which("ffprobe")
    if not probe:
        return None
    try:
        out = subprocess.run([probe, "-v", "error", "-protocol_whitelist", "file,pipe", "-show_entries",
                              "format=duration", "-of", "default=nokey=1:noprint_wrappers=1", str(path)],
                             capture_output=True, text=True, timeout=30, check=False).stdout.strip()
        value = float(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def check_tracks(tracks, *, brief=None, plan=None, length=None, pace=None, speech=None, license_record=None):
    from myzing.brief.models import Brief
    from myzing.composition import Composition
    if brief and plan:
        raise ValueError("Supply a brief or plan, not both")
    b = Brief.from_dict(json.loads(Path(brief).read_text(encoding="utf-8-sig"))) if brief else None
    if plan:
        p = Composition.from_json(Path(plan).read_text(encoding="utf-8-sig"))
        from .models import extract
        e = extract(p)
        b = p.brief
        if speech is None:
            speech = bool(e.speech_spans or any(c.words for c in p.captions))
        length = length or max(c.timeline_end for c in p.clips)
        pace = pace or median(c.duration for c in p.clips)
    length = length or (b.target_length_seconds if b else 30)
    speech = talking(b) if speech is None else speech
    results = []
    for t in tracks:
        audio = analyze(t)
        results.append(rate(audio, length=length, speech=speech, pace=pace, purpose=b.purpose if b else "",
                            license_record=license_record,
                            source_duration=probe_duration(t) if audio.truncated else None).to_dict())
    return {"version": 1, "context": {"length": length, "speech": speech, "pace": pace},
            "tracks": sorted(results, key=lambda a: (-a["score"], a["track"])),
            "scope": "Local rules and DSP; no downloads, uploads, song identification or licensing claims."}
