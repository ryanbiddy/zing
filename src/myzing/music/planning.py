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
    # passages, so the pause bed sits (21 - depth) LU under gated speech.
    from .measurement import source_speech_lufs, window_loudness
    speech_lufs = source_speech_lufs(sequence, studies) if spans else None
    pause_under = evidence.speech_to_music_lu - evidence.duck_depth_db
    target_lufs = speech_lufs - pause_under if speech_lufs is not None else -23 - pause_under if spans else -16
    music_windows = [[max(offset, offset + a), min(end, offset + b)] for a, b in evidence.speech_spans
                     if max(offset, offset + a) < min(end, offset + b)] if spans else [[offset, end]]
    excerpt_lufs = window_loudness(path, music_windows, end)
    gain = max(-60, min(12, target_lufs - excerpt_lufs)) if excerpt_lufs is not None else -24 if spans else -6
    evidence.decisions.append({"kind": "music_level", "output_time": 0.0, "evidence_time": offset,
        "gain_db": gain, "speech_lufs": speech_lufs, "gap_target_lufs": target_lufs,
        "music_window_lufs": excerpt_lufs,
        "speech_to_music_target_lu": evidence.speech_to_music_lu if spans else None,
        "pause_bed_under_speech_lu": pause_under if spans else None,
        "duck": evidence.duck() if spans else None,
        "reason": (f"Known speech passages duck the bed {evidence.duck_depth_db:g} dB: "
                   f"{evidence.duck_attack_seconds:g}s pre-duck before the first word, held through clause gaps under "
                   f"{evidence.duck_hold_seconds:g}s, {evidence.duck_release_seconds:g}s recovery in longer pauses. "
                   "Target needs output measurement.") if spans else
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
