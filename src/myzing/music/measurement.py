"""Measured isolated stems, never an estimate obtained by subtracting the mix."""
from __future__ import annotations

import math
import tempfile
from pathlib import Path
from myzing.audio.media import ffmpeg, numpy, run_ffmpeg, decode_mono, local_file, SAMPLE_RATE
from myzing.audio.loudness import measure_loudness, parse_ebur128
from .ducking import DEFAULT_SPEECH_TO_MUSIC_LU, MAX_SPANS, check_span_count, merge, span_expression

# docs/MUSIC.md: speech sits 19.2 LU over the bed in phrases by default, 18-24 LU accepted.
CLAUSE_TARGET_LU = DEFAULT_SPEECH_TO_MUSIC_LU
CLAUSE_BAND_LU = (18.0, 24.0)
KWEIGHT_RATE = 48000
KWEIGHT_FRAME = 2400  # 50 ms frames, 20 Hz bins


def window_loudness(path, spans, duration):
    """Integrated LUFS over the union of time windows, or None below the gate.

    Windows are merged and selected with a balanced expression read from a
    filter script, so neither FFmpeg 8's expression depth nor the Windows
    command-line limit bounds the span count (MAX_SPANS does, with a message).
    """
    windows = merge([[max(0.0, a), min(duration, b)] for a, b in spans])
    if not windows:
        return None
    # Pause windows are the complement of up to MAX_SPANS speech spans, so a
    # legal plan can produce one more window than it has spans.
    check_span_count(len(windows), "loudness windows", MAX_SPANS + 1)
    from myzing.render.pipeline import filter_script_args
    path = local_file(path)
    graph = f"[0:a:0]aselect='{span_expression(windows)}',asetpts=N/SR/TB,ebur128=peak=true[loudness]"
    with tempfile.TemporaryDirectory(prefix="zing-loudness-") as directory:
        script = Path(directory) / "loudness.txt"
        script.write_text(graph, encoding="utf-8")
        r = run_ffmpeg(["-v", "info", "-protocol_whitelist", "file,pipe", "-t", f"{duration:.9f}", "-i", str(path),
                        *filter_script_args(ffmpeg(), script), "-map", "[loudness]", "-f", "null", "-"],
                       timeout=max(30, duration * 2))
    return parse_ebur128(r.stderr.decode("utf-8", errors="replace")).integrated_lufs


def clip_speech_levels(sequence, studies):
    """Gated speech LUFS of each sequence clip over its complete clauses (or None)."""
    from myzing.director.continuity import clauses
    lookup = {s.asset_id: s for s in studies}
    levels, cursor = [], 0.0
    for c in sequence:
        spans = [[max(c.start, s.start), min(c.end, s.end)] for s in clauses(lookup[c.asset_id].words)
                 if max(c.start, s.start) < min(c.end, s.end)]
        value = window_loudness(lookup[c.asset_id].path, spans, c.end) if spans else None
        levels.append({"asset_id": c.asset_id, "output_start": cursor, "output_end": cursor + c.duration,
                       "speech_lufs": value, "speech_seconds": sum(b - a for a, b in spans), "has_speech": bool(spans)})
        cursor += c.duration
    return levels


def combine_levels(levels):
    """Speech-time-weighted energy mean of measured clip levels."""
    values = [(v["speech_lufs"], v["speech_seconds"]) for v in levels
              if v["speech_lufs"] is not None and v["speech_seconds"] > 0]
    if not values:
        return None
    return float(10 * math.log10(sum(10 ** (v / 10) * w for v, w in values) / sum(w for _, w in values)))


def source_speech_lufs(sequence, studies):
    return combine_levels(clip_speech_levels(sequence, studies))


def _biquad_power(b, a, freqs, rate):
    out = []
    for f in freqs:
        z = complex(math.cos(-2 * math.pi * f / rate), math.sin(-2 * math.pi * f / rate))
        out.append(abs((b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)) ** 2)
    return out


def kweighting_power(freqs, rate=KWEIGHT_RATE):
    """|H|^2 of the BS.1770 K-weighting (high shelf, then RLB high-pass) at ``freqs``."""
    gain, q, fc = 3.999843853973347, 0.7071752369554196, 1681.974450955533
    big_a, w0 = 10 ** (gain / 40), 2 * math.pi * fc / rate
    alpha, cos, root = math.sin(w0) / (2 * q), math.cos(w0), math.sqrt(10 ** (gain / 40))
    shelf = _biquad_power(
        [big_a * ((big_a + 1) + (big_a - 1) * cos + 2 * root * alpha), -2 * big_a * ((big_a - 1) + (big_a + 1) * cos),
         big_a * ((big_a + 1) + (big_a - 1) * cos - 2 * root * alpha)],
        [(big_a + 1) - (big_a - 1) * cos + 2 * root * alpha, 2 * ((big_a - 1) - (big_a + 1) * cos),
         (big_a + 1) - (big_a - 1) * cos - 2 * root * alpha], freqs, rate)
    q, fc = 0.5003270373238773, 38.13547087602444
    w0 = 2 * math.pi * fc / rate
    alpha, cos = math.sin(w0) / (2 * q), math.cos(w0)
    high = _biquad_power([(1 + cos) / 2, -(1 + cos), (1 + cos) / 2], [1 + alpha, -2 * cos, 1 - alpha], freqs, rate)
    return [x * y for x, y in zip(shelf, high)]


def frame_powers(path, duration, *, start=0.0):
    """K-weighted mean-square power per 50 ms frame, summed over channels.

    Frequency-domain weighting of rectangular frames (no SciPy needed). It
    approximates BS.1770 for short ungated windows; it is not the gated meter.
    """
    np = numpy()
    if duration <= 0:
        return np.zeros(0)
    path = local_file(path)
    r = run_ffmpeg(["-v", "error", "-protocol_whitelist", "file,pipe", "-ss", f"{max(0.0, start):.6f}",
                    "-t", f"{duration:.6f}", "-i", str(path), "-map", "0:a:0", "-ac", "2", "-ar", str(KWEIGHT_RATE),
                    "-f", "f32le", "pipe:1"], timeout=max(30, duration * 2))
    samples = np.frombuffer(r.stdout, dtype="<f4")
    frames = len(samples) // (2 * KWEIGHT_FRAME)
    if not frames:
        return np.zeros(0)
    pcm = samples[:frames * 2 * KWEIGHT_FRAME].reshape(frames, KWEIGHT_FRAME, 2)
    weight = np.array(kweighting_power(np.fft.rfftfreq(KWEIGHT_FRAME, 1 / KWEIGHT_RATE)))
    weight[1:-1] *= 2  # one-sided spectrum: Parseval counts interior bins twice
    out = np.zeros(frames)
    for i in range(0, frames, 256):
        spectrum = np.abs(np.fft.rfft(pcm[i:i + 256].astype(np.float64), axis=1)) ** 2
        out[i:i + 256] = (spectrum * weight[None, :, None]).sum(axis=(1, 2)) / KWEIGHT_FRAME ** 2
    return out


def peak_dbfs(path, duration, *, start=0.0):
    """Sample peak (dBFS) of a decoded range, or None when it is silent."""
    np = numpy()
    r = run_ffmpeg(["-v", "error", "-protocol_whitelist", "file,pipe", "-ss", f"{max(0.0, start):.6f}",
                    "-t", f"{duration:.6f}", "-i", str(local_file(path)), "-map", "0:a:0", "-ac", "2",
                    "-ar", str(KWEIGHT_RATE), "-f", "f32le", "pipe:1"], timeout=max(30, duration * 2))
    samples = np.frombuffer(r.stdout, dtype="<f4")
    peak = float(np.abs(samples).max()) if samples.size else 0.0
    return round(20 * math.log10(peak), 1) if peak > 1e-9 else None


def window_levels(powers, windows, *, offset=0.0):
    """Ungated K-weighted LUFS of each window from frame powers (None if silent).

    ``offset`` is the time of the first frame; a window shorter than a frame
    uses the frame at its midpoint.
    """
    np = numpy()
    step = KWEIGHT_FRAME / KWEIGHT_RATE
    centers = (np.arange(len(powers)) + .5) * step + offset
    out = []
    for a, b in windows:
        inside = powers[(centers >= a) & (centers < b)]
        middle = int(((a + b) / 2 - offset) / step)
        if not inside.size and 0 <= middle < len(powers):
            inside = powers[middle][None]
        mean = float(inside.mean()) if inside.size else 0.0
        out.append(round(-0.691 + 10 * math.log10(mean), 1) if mean > 1e-12 else None)
    return out


def clause_report(speech, music, spans, band=CLAUSE_BAND_LU, ramps=(), compressed=()):
    """Per-clause speech-over-music rows, a summary and the rows to warn about.

    A clause under a planned bed level ramp (``ramps``) hears the bed between
    two balanced levels; it can only sit further under the speech, so being
    above the band there is reported but not warned about. A planned clause in
    a compressed dialogue clip (``compressed`` windows) is an upper estimate:
    compression only lowers the speech, so the same exemption applies.
    """
    rows = []
    for (a, b), s, m in zip(spans, speech, music):
        sep = None if s is None or m is None else round(s - m, 1)
        rows.append({"start": a, "end": b, "speech_lufs": s, "music_lufs": m, "separation_lu": sep,
                     "in_band": None if sep is None else band[0] <= sep <= band[1],
                     "bed_ramp": any(a < y and b > x for x, y in ramps),
                     "compressed": any(a < y and b > x for x, y in compressed)})
    known = [r for r in rows if r["separation_lu"] is not None]
    outside = [r for r in known if not r["in_band"]
               and not ((r["bed_ramp"] or r["compressed"]) and r["separation_lu"] > band[1])]
    summary = {"band_lu": list(band), "clauses": len(rows), "measured": len(known), "outside_band": len(outside),
               "above_band_under_bed_ramp": sum(1 for r in known if r["bed_ramp"] and r["separation_lu"] > band[1]),
               "above_band_upper_estimate": sum(1 for r in known if r["compressed"] and not r["bed_ramp"]
                                                and r["separation_lu"] > band[1]),
               "min_separation_lu": min((r["separation_lu"] for r in known), default=None),
               "max_separation_lu": max((r["separation_lu"] for r in known), default=None)}
    return rows, summary, outside


def band_warning(outside, total, verb):
    """One actionable sentence for clauses outside the band, or None."""
    if not outside:
        return None
    worst = max(outside, key=lambda r: abs(r["separation_lu"] - CLAUSE_TARGET_LU))
    where = "too close to" if worst["separation_lu"] < CLAUSE_BAND_LU[0] else "too far under"
    return (f"{len(outside)} of {total} clauses {verb} outside the {CLAUSE_BAND_LU[0]:g}-{CLAUSE_BAND_LU[1]:g} LU "
            f"speech-over-music band; the furthest is {worst['separation_lu']:g} LU at "
            f"{worst['start']:.2f}-{worst['end']:.2f}s (the bed sits {where} the speech). Balance that clause's "
            "dialogue level, or edit bed_gain_points in the plan's MUSIC1 evidence.")


def complement(windows, duration):
    gaps, cursor = [], 0.0
    for a, b in windows:
        if a > cursor:
            gaps.append([cursor, a])
        cursor = max(cursor, b)
    if cursor < duration:
        gaps.append([cursor, duration])
    return gaps


def measure_mix(output, music, source, spans, duration, *, passages=None, ramps=()):
    """Speech windows are the known spans; pauses lie outside duck passages.

    Held gaps are clause gaps inside a passage, where the bed stays ducked.
    """
    np = numpy()
    samples, _ = decode_mono(music, max_seconds=min(600, duration))
    speech = merge([[max(0.0, a), min(duration, b)] for a, b in spans])
    held_passages = merge([[max(0.0, a), min(duration, b)] for a, b in (passages or speech)])
    pauses = complement(held_passages, duration)
    held = []
    for start, end in held_passages:
        inside = [[max(0.0, a - start), min(end, b) - start] for a, b in speech if a < end and b > start]
        held += [[start + a, start + b] for a, b in complement(inside, end - start)]
    if speech:
        # Ducked lead-ins and tails sit under the music fades; held gaps are
        # the gaps between words only.
        held = [[a, b] for a, b in held if a >= speech[0][0] - 1e-6 and b <= speech[-1][1] + 1e-6]

    def mask(windows):
        m = np.zeros(len(samples), dtype=bool)
        for a, b in windows:
            m[int(a * SAMPLE_RATE):int(b * SAMPLE_RATE)] = True
        return m

    def rms(x):
        return round(float(20 * np.log10(max(1e-12, np.sqrt(np.mean(x.astype(float) ** 2))))), 3) if x.size else None

    speech_mask, pause_mask, held_mask = mask(speech), mask(pauses), mask(held)
    speech_music = window_loudness(music, speech, duration)
    speech_source = window_loudness(source, speech, duration) if source else None
    clause_rows, clause_summary, warnings = [], None, []
    if source and spans:
        ordered = sorted([float(a), float(b)] for a, b in spans)
        clause_rows, clause_summary, outside = clause_report(
            window_levels(frame_powers(source, duration), ordered), window_levels(frame_powers(music, duration), ordered),
            ordered, ramps=ramps)
        warning = band_warning(outside, len(clause_rows), "measure")
        if warning:
            warnings.append(warning)
    return {"version": 1, "clauses": clause_rows, "clause_separation": clause_summary, "warnings": warnings,
            "clause_method": "ungated K-weighted 50 ms frames over each clause (BS.1770 weighting without gating)",
            "method": "isolated post-duck music and source stems from the render graph, before final peak limiter; EBU R128 windows use audio-frame selection",
        "music_speech_rms_dbfs": rms(samples[speech_mask]), "music_gap_rms_dbfs": rms(samples[pause_mask]),
        "music_held_gap_rms_dbfs": rms(samples[held_mask]),
        "music_speech_lufs": speech_music, "music_gap_lufs": window_loudness(music, pauses, duration),
        "source_speech_lufs": speech_source,
        "speech_to_music_lu": round(speech_source - speech_music, 3) if speech_source is not None and speech_music is not None else None,
        "speech_seconds": float(speech_mask.sum()) / SAMPLE_RATE, "gap_seconds": float(pause_mask.sum()) / SAMPLE_RATE,
        "held_gap_seconds": float(held_mask.sum()) / SAMPLE_RATE,
        "integrated": measure_loudness(output, max_seconds=min(600, duration)).to_dict(),
        "music_integrated": measure_loudness(music, max_seconds=min(600, duration)).to_dict(),
        "curve": [{"time": i / SAMPLE_RATE, "music_rms_dbfs": rms(samples[i:i + SAMPLE_RATE // 4])}
                  for i in range(0, len(samples), SAMPLE_RATE // 4)],
        "limits": "Gaps are pauses outside duck passages and include recovery ramps and fades; held gaps are clause gaps "
                  "kept ducked. Source stem includes embedded sounds. LUFS can be unknown below gate or in short windows. "
                  "These measurements do not replace listening."}
