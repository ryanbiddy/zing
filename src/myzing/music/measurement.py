"""Measured isolated stems, never an estimate obtained by subtracting the mix."""
from __future__ import annotations

from pathlib import Path
from myzing.audio.media import numpy, run_ffmpeg, input_args, decode_mono, SAMPLE_RATE
from myzing.audio.loudness import measure_loudness, parse_ebur128


def window_loudness(path, spans, duration):
    if not spans:
        return None
    expr = "+".join(f"between(t,{a:.6f},{b:.6f})" for a, b in spans)
    r = run_ffmpeg(["-v", "info", *input_args(Path(path), duration), "-af",
        f"aselect='{expr}',asetpts=N/SR/TB,ebur128=peak=true", "-f", "null", "-"], timeout=max(30, duration * 2))
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


def measure_mix(output, music, source, spans, duration):
    np = numpy()
    samples, _ = decode_mono(music, max_seconds=min(600, duration))
    mask = np.zeros(len(samples), dtype=bool)
    merged = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(b, merged[-1][1])
        else:
            merged.append([max(0, a), min(duration, b)])
    for a, b in merged:
        mask[int(a * SAMPLE_RATE):int(b * SAMPLE_RATE)] = True
    gaps, cursor = [], 0.0
    for a, b in merged:
        if a > cursor:
            gaps.append([cursor, a])
        cursor = b
    if cursor < duration:
        gaps.append([cursor, duration])
    def rms(x):
        return round(float(20 * np.log10(max(1e-12, np.sqrt(np.mean(x.astype(float) ** 2))))), 3) if x.size else None
    speech_music = window_loudness(music, merged, duration)
    speech_source = window_loudness(source, merged, duration) if source else None
    return {"version": 1, "method": "isolated post-duck music and source stems from the render graph, before final peak limiter; EBU R128 windows use audio-frame selection",
        "music_speech_rms_dbfs": rms(samples[mask]), "music_gap_rms_dbfs": rms(samples[~mask]),
        "music_speech_lufs": speech_music, "music_gap_lufs": window_loudness(music, gaps, duration),
        "source_speech_lufs": speech_source,
        "speech_to_music_lu": speech_source - speech_music if speech_source is not None and speech_music is not None else None,
        "speech_seconds": float(mask.sum()) / SAMPLE_RATE, "gap_seconds": float((~mask).sum()) / SAMPLE_RATE,
        "integrated": measure_loudness(output, max_seconds=min(600, duration)).to_dict(),
        "music_integrated": measure_loudness(music, max_seconds=min(600, duration)).to_dict(),
        "curve": [{"time": i / SAMPLE_RATE, "music_rms_dbfs": rms(samples[i:i + SAMPLE_RATE // 4])}
                  for i in range(0, len(samples), SAMPLE_RATE // 4)],
        "limits": "Source stem includes embedded sounds. LUFS can be unknown below gate or in short windows. These measurements do not replace listening."}
