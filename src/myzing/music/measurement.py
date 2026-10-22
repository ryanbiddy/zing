"""Measured isolated stems, never an estimate obtained by subtracting the mix."""
from __future__ import annotations

import tempfile
from pathlib import Path
from myzing.audio.media import ffmpeg, numpy, run_ffmpeg, decode_mono, local_file, SAMPLE_RATE
from myzing.audio.loudness import measure_loudness, parse_ebur128
from .ducking import MAX_SPANS, check_span_count, merge, span_expression


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


def source_speech_lufs(sequence, studies):
    from myzing.director.continuity import clauses
    np = numpy()
    lookup = {s.asset_id: s for s in studies}
    values = []
    for c in sequence:
        spans = [[max(c.start, s.start), min(c.end, s.end)] for s in clauses(lookup[c.asset_id].words)
                 if max(c.start, s.start) < min(c.end, s.end)]
        if spans:
            value = window_loudness(lookup[c.asset_id].path, spans, c.end)
            if value is not None:
                values.append((value, sum(b - a for a, b in spans)))
    return float(10 * np.log10(sum(10 ** (v / 10) * w for v, w in values) / sum(w for _, w in values))) if values else None


def complement(windows, duration):
    gaps, cursor = [], 0.0
    for a, b in windows:
        if a > cursor:
            gaps.append([cursor, a])
        cursor = max(cursor, b)
    if cursor < duration:
        gaps.append([cursor, duration])
    return gaps


def measure_mix(output, music, source, spans, duration, *, passages=None):
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
    return {"version": 1, "method": "isolated post-duck music and source stems from the render graph, before final peak limiter; EBU R128 windows use audio-frame selection",
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
