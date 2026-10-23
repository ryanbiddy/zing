"""Dialogue level matching across clips of a speech-led edit. Standard library only.

LISTEN1's listening review heard the quiet opening clip of the talking edit
"brokenly quiet" next to the next speaker: the clips' gated speech differed by
13.9 LU, and a bed that follows each clip cannot fix the voices themselves.
When the speech levels of the edit's recordings span more than
``SPREAD_LU``, each quieter recording's clips are raised toward the loudest
recording's speech level (at most ``MAX_BOOST_DB``). Gains are per source
asset, not per clip: two sentences of one recording keep their natural
difference, and a jump cut inside it gets no level step (a +1.3 dB step on
the second Korky Paul trim was heard). Where that static gain would push the clip's peaks more
than ``LIMITER_GRACE_DB`` past the final -2 dBFS limiter (smaller overs the
oversampled limiter handles cleanly), a peak-detecting compressor sits after the gain,
its threshold ``HEADROOM_DB`` above the target speech level (never above the
limiter's ``LIMIT_DBFS``), so the limiter does not squash loud syllables on its
own. The peak covers every clip of the recording, speech-free trims included. The gain applies to the whole
clip, ambience included, as an editor's clip gain would.
"""
from __future__ import annotations

import math

SPREAD_LU = 6.0
MAX_BOOST_DB = 18.0
MIN_BOOST_DB = 0.5
LIMIT_DBFS = -2.0
LIMITER_GRACE_DB = 3.0
HEADROOM_DB = 6.0
RATIO, ATTACK_MS, RELEASE_MS, KNEE_DB = 4.0, 5.0, 120.0, 6.0


def asset_levels(levels):
    """Speech-time-weighted energy mean of each source asset's measured clips."""
    out = {}
    for v in levels:
        if v["speech_lufs"] is not None and v.get("speech_seconds", 1.0) > 0:
            out.setdefault(v["asset_id"], []).append((v["speech_lufs"], v.get("speech_seconds", 1.0)))
    return {k: 10 * math.log10(sum(10 ** (x / 10) * w for x, w in vs) / sum(w for _, w in vs)) for k, vs in out.items()}


def clip_peaks(sequence, levels, measure):
    """Sample peak of every clip of a recording that may be raised, speech-free trims included.

    The gain is per recording, so a slam in a B-roll trim of a quiet
    recording is raised too and must count toward the compressor decision.
    ``measure(clip)`` returns a peak in dBFS or None; other clips get None.
    """
    assets = asset_levels(levels)
    if len(assets) < 2 or max(assets.values()) - min(assets.values()) <= SPREAD_LU:
        return [None] * len(sequence)
    return [measure(c) if c.asset_id in assets else None for c in sequence]


def plan_gains(levels, peaks):
    """Rows of per-clip dialogue gain (one gain per source asset) and notes for the editor.

    ``levels`` are clip_speech_levels() rows; ``peaks`` the sample peak (dBFS)
    of each clip's used range, or None.
    """
    assets = asset_levels(levels)
    if len(assets) < 2 or max(assets.values()) - min(assets.values()) <= SPREAD_LU:
        return [], []
    target = max(assets.values())
    asset_peaks = {}
    for level, peak in zip(levels, peaks):
        if peak is not None:
            asset_peaks[level["asset_id"]] = max(peak, asset_peaks.get(level["asset_id"], peak))
    rows, notes, noted = [], [], set()
    for level in levels:
        if level["asset_id"] not in assets:
            continue
        peak = asset_peaks.get(level["asset_id"])
        wanted = target - assets[level["asset_id"]]
        gain = min(MAX_BOOST_DB, wanted)
        if gain < MIN_BOOST_DB:
            continue
        compress = peak is not None and peak + gain > LIMIT_DBFS + LIMITER_GRACE_DB
        # Hot loudest speech (above -8 LUFS) would put target + headroom over the limiter or 0 dBFS.
        threshold = max(-60.0, min(target + HEADROOM_DB, LIMIT_DBFS))
        rows.append({"asset_id": level["asset_id"], "start": level["output_start"], "end": level["output_end"],
                     "speech_lufs": level["speech_lufs"], "asset_speech_lufs": round(assets[level["asset_id"]], 2),
                     "target_lufs": round(target, 2), "gain_db": round(gain, 2),
                     "peak_dbfs": peak,
                     "compressor": {"threshold_db": round(threshold, 2), "ratio": RATIO, "attack_ms": ATTACK_MS,
                                    "release_ms": RELEASE_MS, "knee_db": KNEE_DB} if compress else None})
        if level["asset_id"] in noted:
            continue
        noted.add(level["asset_id"])
        where = f"clip {level['asset_id']} ({level['output_start']:.2f}-{level['output_end']:.2f}s)"
        if wanted > MAX_BOOST_DB:
            notes.append(f"Dialogue in {where} is {wanted:.1f} LU quieter than the loudest clip; Zing raised it only "
                         f"{MAX_BOOST_DB:g} dB, so {wanted - MAX_BOOST_DB:.1f} LU of the jump remains. Re-record or "
                         "level that clip in an editor, or use a closer-matched take.")
        if compress:
            sharp = (f" Sounds sharper than its {ATTACK_MS:g} ms attack, such as a slam or a clap, can still meet the "
                     f"final limiter with up to about {peak + gain - LIMIT_DBFS:.0f} dB of gain reduction."
                     if peak + gain - LIMIT_DBFS > 2 * HEADROOM_DB else "")
            notes.append(f"Dialogue in {where} was raised {gain:.1f} dB to match the other clips; its {peak:.1f} dBFS "
                         f"peaks would reach {peak + gain:.1f} dBFS, so a {RATIO:g}:1 compressor above "
                         f"{threshold:.1f} dBFS holds its loudest syllables.{sharp} Listen to that clip for "
                         "pumping or raised room noise.")
    return rows, notes


def row_at(rows, time, asset_id=None):
    """The dialogue gain row covering output ``time`` (for ``asset_id``, when given), if any."""
    return next((r for r in rows if r["start"] - 1e-6 <= time < r["end"] - 1e-6
                 and (asset_id is None or r.get("asset_id") in (None, asset_id))), None)


def filters(row) -> tuple[str, ...]:
    """FFmpeg filters for one clip's audio: gain, then (if needed) the compressor."""
    if not row:
        return ()
    out = [f"volume={row['gain_db']:.6f}dB"]
    c = row.get("compressor")
    if c:
        out.append(f"acompressor=threshold={10 ** (c['threshold_db'] / 20):.6f}:ratio={c['ratio']:g}:"
                   f"attack={c['attack_ms']:g}:release={c['release_ms']:g}:knee={10 ** (c['knee_db'] / 20):.6f}:"
                   "detection=peak:link=maximum:makeup=1")
    return tuple(out)


def validate(rows) -> None:
    for r in rows:
        values = (r.get("start"), r.get("end"), r.get("gain_db"))
        if (not all(type(x) in (int, float) and math.isfinite(x) for x in values) or not 0 <= r["start"] < r["end"]
                or not 0 <= r["gain_db"] <= MAX_BOOST_DB):
            raise ValueError(f"dialogue_gains need 0 <= start < end and 0 <= gain_db <= {MAX_BOOST_DB:g}")
        c = r.get("compressor")
        if c is not None and not (-60 <= c.get("threshold_db", 1) <= 0 and 1 <= c.get("ratio", 0) <= 20):
            raise ValueError("dialogue compressor needs -60 <= threshold_db <= 0 and 1 <= ratio <= 20")


TAIL_FADE_SECONDS, HEAD_FADE_SECONDS, WORD_GUARD_SECONDS = 0.3, 0.1, 0.02


def edge_fade_seconds(clips, spans) -> list[tuple[float, float]]:
    """(fade-in, fade-out) seconds of each clip's own audio; 0 where none (see edge_fades)."""
    out = []
    for i, clip in enumerate(clips):
        start, end = clip.timeline_start, clip.timeline_start + clip.duration
        mine = [(a, b) for a, b in spans if a < end and b > start]

        def changes(other):
            return other is not None and other.asset_id != clip.asset_id
        fade_in = fade_out = 0.0
        if changes(clips[i - 1] if i else None):
            head = min((a for a, _ in mine), default=end) - start - WORD_GUARD_SECONDS
            if head >= .03:
                fade_in = min(HEAD_FADE_SECONDS, head)
        if changes(clips[i + 1] if i + 1 < len(clips) else None):
            tail = end - max((b for _, b in mine), default=start) - WORD_GUARD_SECONDS
            if tail >= .03:
                fade_out = min(TAIL_FADE_SECONDS, tail)
        out.append((fade_in, fade_out))
    return out


def edge_fades(clips, spans) -> list[tuple[str, ...]]:
    """Speech-free audio fades where the source changes at a hard cut.

    LISTEN1: the outgoing clip's own score and room tone stopped dead at the
    cut. Where consecutive clips come from different sources, the outgoing
    clip's audio fades out over its speech-free tail (at most
    TAIL_FADE_SECONDS) and the incoming clip's fades in over its speech-free
    head (at most HEAD_FADE_SECONDS). No fade reaches a known word. A jump cut
    within one recording keeps its continuous room tone: fading it was heard
    as a dip. ``clips`` are timeline-ordered composition clips; ``spans``
    the known speech spans in output seconds.
    """
    out = []
    for clip, (fade_in, fade_out) in zip(clips, edge_fade_seconds(clips, spans)):
        filters = []
        if fade_in:
            filters.append(f"afade=t=in:st=0:d={fade_in:.6f}")
        if fade_out:
            filters.append(f"afade=t=out:st={clip.duration - fade_out:.6f}:d={fade_out:.6f}")
        out.append(tuple(filters))
    return out
