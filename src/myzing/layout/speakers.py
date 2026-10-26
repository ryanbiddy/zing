"""Conservative turn association: supplied identities or a disclosed size heuristic.

No diarization or identity recognition is inferred from ordinary ASR timestamps.
"""

from dataclasses import replace
from statistics import median

from myzing.composition.speakers import SpeakerTurn
from .types import box_at
from .caption_safety import is_face


def output_time(clip, source_time):
    cursor = 0.0
    for segment in clip.speed_map:
        if source_time <= segment.src_out:
            return cursor + (source_time - segment.src_in) / segment.rate
        cursor += (segment.src_out - segment.src_in) / segment.rate
    return source_time - clip.src_in


def speaker_turns(clip, tracks, words):
    words = sorted((w for w in words if w.asset_id == clip.asset_id and
                    w.start < clip.src_out and w.end > clip.src_in), key=lambda w: (w.start, w.end))
    groups = []
    for word in words:
        if groups and word.speaker == groups[-1][-1].speaker and word.start - groups[-1][-1].end <= .8:
            groups[-1].append(word)
        else:
            groups.append([word])
    turns = []
    for group in groups:
        start, end = max(clip.src_in, group[0].start), min(clip.src_out, max(w.end for w in group))
        times = [max(start, min(end, (w.start + w.end) / 2)) for w in group]
        present = [t for t in tracks if is_face(t) and
                   t.keyframes[0].time < end and t.keyframes[-1].time > start]
        faces = [t for t in present if t.keyframes[0].time <= start + 1e-6 and t.keyframes[-1].time >= end - 1e-6]
        identity, confidence, method = None, 0.0, "unknown; retain two-shot"
        speaker = group[0].speaker
        supplied = {w.face_track_id for w in group}
        if speaker is not None and min(w.confidence for w in group) >= .5:
            if len(supplied) == 1 and None not in supplied:
                identity = next((t.id for t in faces if t.id in supplied), None)
                if identity:
                    confidence, method = min(w.confidence for w in group), "supplied speaker-to-face association"
            elif supplied == {None} and faces and len(faces) == len(present):
                # A face seen for only part of the turn is a competitor that
                # cannot be ranked over the whole turn: never call the other "the only face".
                ranked = sorted(((median(box_at(t.keyframes, time).width * box_at(t.keyframes, time).height
                                         for time in times), t.id) for t in faces), reverse=True)
                # Prominence is only a weak speaker proxy, never face-detector probability.
                if len(ranked) == 1 or ranked[0][0] >= 1.5 * ranked[1][0]:
                    identity, confidence, method = ranked[0][1], .55, "face-size heuristic; speaker identity unverified"
        turns.append(SpeakerTurn(output_time(clip, start), output_time(clip, end), speaker,
                                 identity, confidence, method))
    # Overlapping speakers cannot be followed by one window with word-safe moves.
    if any(a.end > b.start for a, b in zip(turns, turns[1:])):
        return [SpeakerTurn(0, clip.duration, None, None, 0, "overlapping speech; retain two-shot")]
    # Size alone cannot tell speakers apart: the dominant face would otherwise be
    # "the speaker" for everyone. A heuristic association must be one-to-one:
    # one face per speaker label and one speaker label per face in this clip.
    faces_of, speakers_of = {}, {}
    for turn in turns:
        if turn.face_track_id is not None:
            faces_of.setdefault(turn.speaker, set()).add(turn.face_track_id)
            speakers_of.setdefault(turn.face_track_id, set()).add(turn.speaker)
    return [replace(turn, face_track_id=None, confidence=0,
                    method="face-size heuristic is ambiguous across speakers/faces; retain two-shot")
            if turn.method.startswith("face-size heuristic")
            and (len(faces_of[turn.speaker]) > 1 or len(speakers_of[turn.face_track_id]) > 1) else turn
            for turn in turns]
