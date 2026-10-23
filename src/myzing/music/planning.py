"""Music follows complete speech clauses; silent montage trims may follow beats."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from myzing.audio import analyze
from myzing.audio.media import numpy, run_ffmpeg
from myzing.composition import AssetRef, CompositionAudio
from myzing.director.continuity import clauses
from myzing.director.selection import overlaps
from myzing.director.models import shortage
from myzing.project.api import hash_file, resolve_path
from .advice import rate
from .models import MusicPlan, timeline_of

# Clip speech levels further apart than this get their own bed level, so a
# quiet clip's clauses do not sit 10 LU over a bed set for a loud one.
CLIP_SPREAD_LU = 6.0
MAX_BED_CUT_DB = 24.0
# Bed level changes move under the louder clip's speech, where the voice
# masks them (LISTEN1: a 0.4 s, 9 dB rise in the silent gap at a cut was heard
# as a swell): a rise starts at the louder clip's first word, a drop ends at
# its last word.
BED_RAMP_SECONDS = 1.0


def speech_spans(sequence, studies):
    lookup = {s.asset_id: s for s in studies}
    spans, cursor = [], 0.0
    for c in sequence:
        for phrase in clauses(lookup[c.asset_id].words):
            a, b = max(c.start, phrase.start), min(c.end, phrase.end)
            if a < b:
                spans.append([cursor + a - c.start, cursor + b - c.start])
        cursor += c.duration
    return spans


def visual_changes(sequence, studies, cache):
    """Low-resolution pixel change, not a claim to recognize a semantic reveal."""
    lookup = {s.asset_id: s for s in studies}
    np = numpy()
    def frame(c, t):
        key = (c.asset_id, round(t, 3))
        if key not in cache:
            raw = run_ffmpeg(["-v", "error", "-protocol_whitelist", "file,pipe", "-ss", f"{max(0, t):.6f}",
                              "-i", lookup[c.asset_id].path, "-frames:v", "1", "-vf", "scale=32:32",
                              "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"]).stdout
            cache[key] = np.frombuffer(raw, dtype=np.uint8).astype(float)
        return cache[key]
    scores = []
    for a, b in zip(sequence, sequence[1:]):
        x, y = frame(a, a.end - .05), frame(b, b.start)
        scores.append(float(np.mean(np.abs(x - y))) / 255 if x.size == y.size == 3072 else 0.0)
    return scores


def retime(sequence, studies, beats, phrases, offset, *, speech, required, forbidden, locked=None):
    """Move a join by at most 80ms for speech or 350ms for montage.

    End of outgoing and start of incoming move together, preserving total
    duration. Reject clause intersections, required/forbidden changes, source
    reuse, unobserved shots and quarantine. No word is retimed.
    """
    lookup = {s.asset_id: s for s in studies}
    result, decisions, cursor = list(sequence), [], 0.0
    tolerance = .08 if speech else .35
    for i in range(len(result) - 1):
        a, b = result[i:i + 2]
        cursor += a.duration
        if locked is not None and i == locked:
            decisions.append({"kind": "cut_locked", "cut_index": i + 1, "output_time": cursor,
                              "evidence_time": offset + cursor,
                              "reason": "Keep this join fixed to preserve the detected moment alignment."})
            continue
        candidates = [(t - offset, "phrase" if t in phrases else "beat", t) for t in {*beats, *phrases}
                      if abs(t - offset - cursor) <= tolerance]
        candidates.sort(key=lambda x: (x[1] != "phrase", abs(x[0] - cursor)))
        accepted = False
        attempts = []
        for target, kind, source_time in candidates:
            delta = target - cursor
            changed = [replace(a, end=a.end + delta), replace(b, start=b.start + delta)]
            blocked = []
            for c in changed:
                study = lookup[c.asset_id]
                if c.duration < .2 or c.start < 0 or c.end > study.duration:
                    blocked.append(f"{c.asset_id}: proposed trim {c.start:.3f}–{c.end:.3f}s exceeds source bounds or leaves less than 0.2s")
                for phrase in clauses(study.words):
                    if overlaps((c.start, c.end), (phrase.start, phrase.end)) and (c.start > phrase.start + 1e-8 or c.end < phrase.end - 1e-8):
                        blocked.append(f"{c.asset_id}: proposed trim cuts the complete clause at {phrase.start:.3f}–{phrase.end:.3f}s")
                if any(overlaps((c.start, c.end), span) for span in forbidden.get(c.asset_id, [])):
                    blocked.append(f"{c.asset_id}: proposed trim enters a forbidden span")
                if any(overlaps((old.start, old.end), span) and not (c.start <= span[0] and c.end >= span[1])
                       for old in (a, b) if old.asset_id == c.asset_id for span in required.get(c.asset_id, [])):
                    blocked.append(f"{c.asset_id}: proposed trim removes required footage")
                if any(overlaps((c.start, c.end), (q["start"], q["end"])) for q in study.asr_repair.get("quarantined", [])):
                    blocked.append(f"{c.asset_id}: proposed trim enters quarantined speech")
                # Expansions must be covered by the same source shot evidence.
                if not any(s.start <= c.start + 1e-8 and s.end >= c.end - 1e-8 for s in study.shots):
                    blocked.append(f"{c.asset_id}: no single observed source shot covers proposed trim {c.start:.3f}–{c.end:.3f}s; insufficient safe shot handles")
            proposed = result[:i] + changed + result[i + 2:]
            for j, c in enumerate(proposed):
                if any(c.content == d.content and overlaps((c.start, c.end), (d.start, d.end)) for d in proposed[j + 1:]):
                    blocked.append(f"{c.asset_id}: proposed trim reuses source footage")
            if not blocked:
                result[i:i + 2] = changed
                decisions.append({"kind": "cut_snap", "output_time": target, "evidence_time": source_time,
                                  "cut_index": i + 1, "previous_time": cursor, "tolerance_seconds": tolerance, "basis": kind,
                                  "delta_seconds": delta,
                                  "reason": "Complete clauses and source constraints preserved."})
                cursor = target
                accepted = True
                break
            attempts.append({"evidence_time": source_time, "output_time": target,
                             "delta_seconds": delta, "blocked_by": list(dict.fromkeys(blocked))})
        if not accepted:
            nearest = min(beats, key=lambda t: abs(t - offset - cursor)) if beats else None
            reason = "; ".join(dict.fromkeys(r for attempt in attempts for r in attempt["blocked_by"])) if attempts else (
                "No supported beat is available in this track window." if nearest is None else
                f"Nearest supported beat would move the join {nearest-offset-cursor:+.3f}s, outside the {tolerance:.3f}s tolerance.")
            decisions.append({"kind": "cut_kept", "cut_index": i + 1, "output_time": cursor, "evidence_time": nearest,
                              "tolerance_seconds": tolerance,
                              "candidate_attempts": attempts, "reason": reason})
    return result, decisions


def clip_offsets(levels, reference):
    """Bed offset (dB <= 0) per clip that keeps each clip's speech the same height over the bed."""
    offsets, notes = [], []
    for level in levels:
        value = level["speech_lufs"]
        if value is None:
            offsets.append(None)
            if level["has_speech"]:
                notes.append(f"Clip {level['asset_id']} at {level['output_start']:.2f}s has speech below the loudness "
                             "gate; its bed level follows the neighbouring clip. Check that its dialogue is audible.")
            continue
        wanted = value - reference
        offsets.append(max(-MAX_BED_CUT_DB, min(0.0, wanted)))
        if wanted < -MAX_BED_CUT_DB:
            notes.append(f"Clip {level['asset_id']} at {level['output_start']:.2f}s speaks {-wanted:.1f} LU below the "
                         f"loudest clip; the bed drops only {MAX_BED_CUT_DB:g} dB there, so its clauses sit "
                         f"{-wanted - MAX_BED_CUT_DB:.1f} LU closer to the bed. Raise that clip's dialogue.")
    # Clips without measured speech inherit the previous (else next) measured offset.
    known = [o for o in offsets if o is not None]
    filled, last = [], known[0] if known else 0.0
    for o in offsets:
        last = last if o is None else o
        filled.append(last)
    return filled, notes


def refine_offsets(levels, offsets, rows, target=None):
    """Centre each clip's planned clauses on ``target`` LU; returns (offsets, track gain shift).

    Speech-only offsets ignore the music's own level changes along the
    excerpt; one pass over the planned per-clause separations corrects that.
    Offsets stay <= 0 dB, so the loudest wanted bed moves the track gain.
    """
    if target is None:
        from .ducking import DEFAULT_SPEECH_TO_MUSIC_LU as target
    wanted = []
    for level, current in zip(levels, offsets):
        mine = [(r["separation_lu"], r["end"] - r["start"]) for r in rows if r["separation_lu"] is not None
                and level["output_start"] <= (r["start"] + r["end"]) / 2 < level["output_end"]]
        weight = sum(w for _, w in mine)
        wanted.append(current + (sum(v * w for v, w in mine) / weight - target) if weight > 0 else None)
    known = [w for w in wanted if w is not None]
    if not known:
        return offsets, 0.0
    shift = max(known)
    filled = [max(-MAX_BED_CUT_DB, (w if w is not None else current) - shift) for w, current in zip(wanted, offsets)]
    return [min(0.0, o) for o in filled], shift


def _windows(passages, spans, lo, hi, free, duration, need):
    """Room for a ramp: duck passages within the speech of [lo, hi], after ``free``, at least ``need`` long."""
    words = sorted([max(a, lo), min(b, hi)] for a, b in spans if a < hi and b > lo)
    if not words:
        return []
    first, last = words[0][0], max(b for _, b in words)
    room = [(max(a, first, free), min(b, last, duration)) for a, b in passages]
    return [(x, y) for x, y in room if y - x >= need - 1e-9]


def gain_points(levels, offsets, spans, duration, ramp=BED_RAMP_SECONDS, passages=None, plateau=None):
    """[time, dB] points for per-clip bed offsets; raised-cosine ramps under the louder voice.

    A change ramps over the louder side's speech: a rise starts at the first
    word after the cut, a drop ends at the last word since the previous ramp.
    Each ramp stays inside one duck passage, where the duck is held, so it
    never adds to a pre-duck or a recovery. Ramps never overlap or pass the
    edit end, and none is faster than the default pre-duck slope
    (MIN_RAMP_SECONDS_PER_DB per dB). A rise is made only when the louder
    clip also has room for the drop after it and ``plateau`` seconds between,
    so short alternating clips do not pump the bed. Where the louder side has
    no such room, a rise is not made (the louder clip sits further over a
    lower bed) and a drop starts at the first room after the cut, under the
    quieter clip. The planned clause report shows either.
    """
    from .ducking import DEFAULT_PLATEAU_SECONDS, MIN_RAMP_SECONDS_PER_DB, duck_passages
    if all(abs(o) < 1e-9 for o in offsets):
        return []
    held = passages if passages is not None else duck_passages(spans, duration)
    plateau = DEFAULT_PLATEAU_SECONDS if plateau is None else plateau
    points, current, free = [[0.0, round(offsets[0], 3)]], offsets[0], 0.0
    for i in range(1, len(levels)):
        want = offsets[i]
        if abs(want - current) < 1e-9:
            continue
        cut, need = levels[i]["output_start"], abs(want - current) * MIN_RAMP_SECONDS_PER_DB
        later = [(v["output_start"], o) for v, o in zip(levels[i + 1:], offsets[i + 1:]) if abs(o - want) > 1e-9]
        following = later[0][0] if later else duration
        early = want > current
        if early:
            # Keep room for the drop back down (and a plateau) under the same voice.
            reserve = (want - later[0][1]) * MIN_RAMP_SECONDS_PER_DB + plateau if later and later[0][1] < want else 0.0
            room = [(x, y - reserve) for x, y in _windows(held, spans, max(cut, free), following, free, duration,
                                                          need + reserve)][:1]
        else:
            room = _windows(held, spans, free, cut, free, duration, need)[-1:]
            if not room:  # the bed goes down under the quieter clip instead
                early = True
                room = [(x, y) for x, y in ((max(a, free, cut), min(b, following, duration)) for a, b in held)
                        if y - x >= need - 1e-9][:1]
        if not room:
            continue
        x, y = room[0]
        length = max(need, min(ramp, y - x))
        start = x if early else y - length
        points += [[round(start, 4), round(current, 3)], [round(start + length, 4), round(want, 3)]]
        current, free = want, start + length
    points.append([round(max(points[-1][0], duration), 4), round(current, 3)])
    return [] if all(abs(g) < 1e-9 for _, g in points) else points


def planned_clauses(sequence, studies, music_path, offset, music_seconds, gain, evidence):
    """Estimated speech-over-music separation per clause before rendering."""
    from myzing.director.continuity import clauses
    from .ducking import mean_gain, ramp_windows
    from .measurement import clause_report, frame_powers, window_levels
    lookup = {s.asset_id: s for s in studies}
    spans, speech, cursor = [], [], 0.0
    for c in sequence:
        mine = [[cursor + max(c.start, k.start) - c.start, cursor + min(c.end, k.end) - c.start]
                for k in clauses(lookup[c.asset_id].words) if max(c.start, k.start) < min(c.end, k.end)]
        if mine:
            powers = frame_powers(lookup[c.asset_id].path, c.duration, start=c.start)
            speech += window_levels(powers, mine, offset=cursor)
            spans += mine
        cursor += c.duration
    from .dialogue import row_at
    speech = [None if v is None else v + ((row_at(evidence.dialogue_gains, (a + b) / 2) or {}).get("gain_db", 0.0))
              for (a, b), v in zip(spans, speech)]
    music = window_levels(frame_powers(music_path, music_seconds, start=offset), spans)
    under = [None if m is None else round(m + gain - evidence.duck_depth_db + mean_gain(evidence.bed_gain_points, a, b), 1)
             for (a, b), m in zip(spans, music)]
    return clause_report(speech, under, spans, ramps=ramp_windows(evidence.bed_gain_points),
                         compressed=[[r["start"], r["end"]] for r in evidence.dialogue_gains if r.get("compressor")])


def plan_music(sequence, studies, brief, manifest, root, pace, required, forbidden, cache=None):
    cache = cache if cache is not None else {}
    evidence = MusicPlan()
    if brief.music["source"] != "supplied files":
        return sequence, [], [], evidence
    spans = speech_spans(sequence, studies)
    evidence.mode = "speech-led" if spans else "music-led"
    duration = sum(c.duration for c in sequence)
    choices = []
    for selector in brief.music["files"]:
        matches = [a for a in manifest.assets if selector in (a.id, a.path) or resolve_path(a.path, root) == resolve_path(selector, root)]
        if len(matches) != 1:
            shortage("music_asset", f"Music {selector!r} is not uniquely inventoried.", "Add the local file and run zing project scan.")
        a = matches[0]
        path = resolve_path(a.path, root)
        if a.state != "ready" or not a.probe or not a.probe.has_audio or not path.is_file() or hash_file(path) != a.sha256:
            shortage("music_asset", f"Music {selector!r} is stale, missing or has no audio.", "Restore it and run zing project scan.")
        if a.sha256 not in cache:
            cache[a.sha256] = analyze(path)
        m = cache[a.sha256]
        advice = rate(m, length=duration, speech=bool(spans), pace=pace, purpose=brief.purpose,
                      source_duration=a.probe.duration)
        choices.append((advice.score, a, path, m, advice))
    _, asset, path, m, advice = max(choices, key=lambda x: (x[0], x[1].id))
    offset = advice.measurements["scoring"]["source_offset"] if spans else 0.0
    locked, target, moment = None, None, None
    phrases = sorted({v["time"] for v in m.structure.phrases}) if m.structure else []
    beats = (m.beats or sorted({t for r in m.structure.rhythm_regions for t in r["beats"]})) if m.structure else m.beats
    if spans:
        evidence.decisions.append({"kind": "bed_excerpt", "output_time": 0.0, "evidence_time": offset,
            "source_offset": offset, "reason": "Use the advised steady excerpt under speech; clauses set the edit, with no forced song moment."})
    if not spans and len(sequence) > 1 and m.structure:
        changes = visual_changes(sequence, studies, cache.setdefault("frames", {}))
        locked = max(range(len(changes)), key=lambda i: changes[i])
        target = sum(c.duration for c in sequence[:locked + 1])
        eligible = [v for v in m.structure.moments if v.kind != "swell" and 0 <= v.time - target <= m.duration_seconds - duration]
        if changes[locked] <= 1e-9:
            # Unreadable or identical join frames are not evidence of a reveal.
            evidence.decisions.append({"kind": "moment_alignment_skipped", "output_time": None, "evidence_time": None,
                "reason": "No measurable pixel change at any selected join (frames identical or unreadable); "
                          "no song moment was aligned to a cut."})
            locked = None
        elif eligible:
            moment = max(eligible, key=lambda v: (v.kind == "drop", v.strength * v.confidence))
            offset = moment.time - target
            evidence.decisions.append({"kind": "drop_alignment" if moment.kind == "drop" else "moment_alignment",
                "output_time": target, "cut_index": locked + 1, "evidence_time": moment.time, "source_offset": offset, "confidence": moment.confidence,
                "visual_change_score": changes[locked], "reason": "Largest measured 32px RGB change among selected joins; semantic reveal unknown."})
        else:
            locked = None
    sequence, decisions = retime(sequence, studies, beats, phrases, offset, speech=bool(spans),
                                required=required, forbidden=forbidden, locked=locked)
    evidence.decisions += decisions
    evidence.cut_summary = {"total": len(sequence) - 1,
        "snapped": sum(d["kind"] == "cut_snap" and abs(d["delta_seconds"]) > 1e-8 for d in decisions),
        "already_aligned": sum(d["kind"] == "cut_snap" and abs(d["delta_seconds"]) <= 1e-8 for d in decisions),
        "moment_locked": sum(d["kind"] == "cut_locked" for d in decisions),
        "kept": sum(d["kind"] == "cut_kept" for d in decisions)}
    evidence.speech_spans = speech_spans(sequence, studies)
    evidence.timeline = timeline_of(sequence)
    # End the bed on a supported metric phrase when close enough; video and
    # complete speech remain at the requested length. Never extend beyond media.
    short = m.duration_seconds < offset + duration - 1e-6
    end = min(m.duration_seconds, offset + duration)
    candidates = [t for t in phrases if max(offset + .5, end - 2) <= t <= end]
    if candidates:
        end = max(candidates)
    fade = min(1.0, (end - offset) / 4)
    if short:
        missing = duration - (end - offset)
        evidence.warnings.append(
            f"Music {Path(path).name} supplies {end - offset:.2f}s for a {duration:.2f}s edit; the last {missing:.2f}s has no "
            "music. Supply a longer track or edit a loop yourself; Zing does not loop music.")
    evidence.decisions.append({"kind": "music_end", "output_time": end - offset, "evidence_time": end,
        "fade_seconds": fade, "reason": (
            ("Supported metric phrase with fade before the track runs out." if candidates else
             "The track ends before the edit; fade at the track end.") if short else
            "Supported metric phrase with fade." if candidates else "No nearby supported phrase; fade at the edit end.")})
    # Known-speech ducking lowers the bed by duck_depth_db inside speech
    # passages, so the pause bed sits (speech_to_music_lu - depth) LU under gated speech.
    # When clip speech levels differ by more than CLIP_SPREAD_LU, the track
    # gain follows the loudest clip and gain points lower the bed under the
    # quieter ones (docs/MUSIC.md).
    from .ducking import release_gap
    from .measurement import band_warning, clip_speech_levels, combine_levels, window_loudness
    levels = clip_speech_levels(sequence, studies) if spans else []
    if spans:
        # Match the voices first (dialogue.py); the bed then follows only what remains.
        from .dialogue import clip_peaks, plan_gains, row_at
        from .measurement import peak_dbfs
        lookup = {s.asset_id: s for s in studies}
        peaks = clip_peaks(sequence, levels, lambda c: peak_dbfs(lookup[c.asset_id].path, c.duration, start=c.start))
        evidence.dialogue_gains, notes = plan_gains(levels, peaks)
        evidence.warnings += notes
        if evidence.dialogue_gains:
            evidence.decisions.append({"kind": "dialogue_level", "output_time": 0.0, "evidence_time": None,
                "gains": evidence.dialogue_gains,
                "reason": "Clip speech levels differ by more than 6 LU; quieter clips are raised toward the loudest "
                          "clip's speech (at most 18 dB), with a peak compressor where the gain would reach the limiter."})
            levels = [{**v, "source_speech_lufs": v["speech_lufs"],
                       "speech_lufs": None if v["speech_lufs"] is None else
                       v["speech_lufs"] + (row_at(evidence.dialogue_gains, (v["output_start"] + v["output_end"]) / 2) or {}).get("gain_db", 0.0)}
                      for v in levels]
    speech_lufs = combine_levels(levels) if spans else None
    measured = [v["speech_lufs"] for v in levels if v["speech_lufs"] is not None]
    spread = max(measured) - min(measured) if len(measured) > 1 else 0.0
    per_clip = spread > CLIP_SPREAD_LU
    reference = max(measured) if per_clip else speech_lufs
    pause_under = evidence.speech_to_music_lu - evidence.duck_depth_db
    target_lufs = reference - pause_under if reference is not None else -23 - pause_under if spans else -16
    music_windows = [[max(offset, offset + a), min(end, offset + b)] for a, b in evidence.speech_spans
                     if max(offset, offset + a) < min(end, offset + b)] if spans else [[offset, end]]
    excerpt_lufs = window_loudness(path, music_windows, end)
    gain = max(-60, min(12, target_lufs - excerpt_lufs)) if excerpt_lufs is not None else -24 if spans else -6
    if spans:
        from .ducking import duck_passages
        held = duck_passages(evidence.speech_spans, duration, hold=evidence.duck_hold_seconds,
                             attack=evidence.duck_attack_seconds, release=evidence.duck_release_seconds,
                             plateau=evidence.duck_plateau_seconds)
        offsets, notes = clip_offsets(levels, reference) if per_clip else ([0.0] * len(levels), [])
        evidence.bed_gain_points = gain_points(levels, offsets, evidence.speech_spans, duration, passages=held,
                                                 plateau=evidence.duck_plateau_seconds) if per_clip else []
        evidence.clip_levels = [{**v, "bed_offset_db": round(o, 3)} for v, o in zip(levels, offsets)]
        evidence.warnings += notes
        if per_clip:
            evidence.decisions.append({"kind": "bed_clip_gain", "output_time": 0.0, "evidence_time": None,
                "clip_spread_lu": round(spread, 2), "gain_points": evidence.bed_gain_points,
                "reason": f"Clip speech levels differ by {spread:.1f} LU (more than {CLIP_SPREAD_LU:g}); the bed drops "
                          f"under quieter clips, centred so each clip's planned clauses sit about "
                          f"{evidence.speech_to_music_lu:g} LU under its speech, ramping up to {BED_RAMP_SECONDS:g}s under "
                          "the louder voice at each change."})
        if excerpt_lufs is not None:
            rows, summary, outside = planned_clauses(sequence, studies, path, offset, end - offset, gain, evidence)
            if per_clip:
                offsets, shift = refine_offsets(levels, offsets, rows, evidence.speech_to_music_lu)
                gain = max(-60, min(12, gain + shift))
                evidence.bed_gain_points = gain_points(levels, offsets, evidence.speech_spans, duration, passages=held,
                                                       plateau=evidence.duck_plateau_seconds)
                evidence.clip_levels = [{**v, "bed_offset_db": round(o, 3)} for v, o in zip(levels, offsets)]
                next(d for d in evidence.decisions if d["kind"] == "bed_clip_gain")["gain_points"] = evidence.bed_gain_points
                rows, summary, outside = planned_clauses(sequence, studies, path, offset, end - offset, gain, evidence)
            evidence.clauses = rows
            warning = band_warning(outside, len(rows), "are planned")
            if warning:
                evidence.warnings.append(warning)
    evidence.decisions.append({"kind": "music_level", "output_time": 0.0, "evidence_time": offset,
        "gain_db": gain, "speech_lufs": speech_lufs, "gap_target_lufs": target_lufs,
        "music_window_lufs": excerpt_lufs,
        "speech_to_music_target_lu": evidence.speech_to_music_lu if spans else None,
        "pause_bed_under_speech_lu": pause_under if spans else None,
        "per_clip_bed_gain": per_clip if spans else None,
        "duck": evidence.duck() if spans else None,
        "reason": (f"Known speech passages duck the bed {evidence.duck_depth_db:g} dB: "
                   f"{evidence.duck_attack_seconds:g}s pre-duck before the first word, held through gaps under "
                   f"{release_gap(evidence.duck_hold_seconds, evidence.duck_attack_seconds, evidence.duck_release_seconds, evidence.duck_plateau_seconds):g}s "
                   f"(hold, or room for a {evidence.duck_plateau_seconds:g}s recovered plateau), "
                   f"{evidence.duck_release_seconds:g}s recovery in longer pauses. Target needs output measurement.") if spans else
                  "No known speech: music remains at a -16 LUFS planning target."})
    evidence.tracks = [{"id": "music-1", "asset_id": asset.id, "path": str(path), "sha256": asset.sha256,
        "source_offset": offset, "source_end": end, "fade_in": min(.15, fade), "fade_out": fade,
        "advice": advice.to_dict(), "candidates": [c[4].to_dict() for c in choices],
        "reason": f"Highest suitability score among supplied candidates: {advice.rating}, {advice.score}/100.",
        "moments": [{**v.to_dict(), "output_time": v.time - offset} for v in m.structure.moments if offset <= v.time <= end] if m.structure else []}]
    track = CompositionAudio(id="music-1", asset_id=asset.id, src=str(path), kind="music", role="music",
        src_in=offset, src_out=end, gain_db=gain, duck_under_speech=bool(spans),
        duck_scope="source_speech" if spans else "voiceover")
    return sequence, [AssetRef(asset.id, str(path), asset.sha256, asset.probe.duration)], [track], evidence
