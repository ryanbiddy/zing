"""LISTEN1 listening packets: exported mixes, timing sheets and a measurement battery.

For each rendered MUSIC1 case (``<root>/<case>/`` holding a v2 plan, its MP4,
the SHA-bound ``.music.json`` sidecar and a kept render work folder), write
``<out>/<case>/``: the final mix as 48 kHz PCM WAV and 320k MP3, the isolated
music bed (the render graph's pre-limiter music stem) as WAV, a timing sheet
with no local paths (safe to hand to a listener), and ``measurements.json``.

Measurements exist to check a listener's claims, not to replace listening:
50 ms RMS and 400 ms momentary loudness curves, the planned duck gain, limiter
gain reduction (final mix against the sum of its stems), the largest bed level
steps outside planned ramps, music onsets and beats near each cut, sample and
true peak, stereo correlation, and per-clause speech-to-music separation.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

RATE = 48000
WINDOW = .05


def _np():
    import numpy
    return numpy


def decode(path, channels=2):
    np = _np()
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", str(channels),
                          "-ar", str(RATE), "-f", "f32le", "pipe:1"], check=True, capture_output=True, timeout=300).stdout
    return np.frombuffer(raw, dtype="<f4").reshape(-1, channels).astype(float)


def export(source, wav, mp3=None):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(source), "-map", "0:a:0", "-ar", str(RATE),
                    "-c:a", "pcm_s16le", str(wav)], check=True, capture_output=True, timeout=300)
    if mp3:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(source), "-map", "0:a:0", "-ar", str(RATE),
                        "-c:a", "libmp3lame", "-b:a", "320k", str(mp3)], check=True, capture_output=True, timeout=300)


def db(x):
    np = _np()
    return 20 * np.log10(np.maximum(1e-9, x))


def rms_curve(samples, window=WINDOW):
    np = _np()
    n = int(window * RATE)
    frames = len(samples) // n
    mono = samples[:frames * n].mean(axis=1) if samples.ndim == 2 else samples[:frames * n]
    return db(np.sqrt(np.mean(mono.reshape(frames, n) ** 2, axis=1)))


def momentary(path):
    """400 ms momentary loudness every 100 ms from FFmpeg's ebur128 frame log."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0",
                        "-af", "ebur128=peak=true:framelog=info", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=300)
    rows = re.findall(r"t:\s*([\d.]+)\s+TARGET:.*?M:\s*([-\d.inf]+)\s+S:\s*([-\d.inf]+)", r.stderr)
    tp = re.findall(r"Peak:\s*([-+\d.inf]+)\s+dBFS", r.stderr)
    integrated = re.findall(r"I:\s*([-\d.]+)\s+LUFS", r.stderr)
    value = lambda s: None if "inf" in s else float(s)
    return {"curve": [{"time": float(t), "momentary": value(m), "short_term": value(s)} for t, m, s in rows],
            "true_peak_dbtp": value(tp[-1]) if tp else None,
            "integrated_lufs": float(integrated[-1]) if integrated else None}


def onsets(samples):
    """Spectral-flux onsets (time, strength) of a mono signal; 1024/256 STFT."""
    np = _np()
    mono = samples.mean(axis=1) if samples.ndim == 2 else samples
    n, hop = 1024, 256
    frames = 1 + (len(mono) - n) // hop
    if frames < 3:
        return []
    index = np.arange(n)[None, :] + hop * np.arange(frames)[:, None]
    spectrum = np.log1p(100 * np.abs(np.fft.rfft(mono[index] * np.hanning(n), axis=1)))
    flux = np.maximum(0, np.diff(spectrum, axis=0)).sum(axis=1)
    found = []
    width = 8  # ~43 ms neighbourhood
    for i in range(width, len(flux) - width):
        local = flux[i - width:i + width + 1]
        threshold = np.median(flux[max(0, i - 40):i + 40]) * 1.5 + 1e-9
        if flux[i] == local.max() and flux[i] > threshold:
            found.append(((i + 1) * hop / RATE + n / 2 / RATE, float(flux[i])))
    return found


def low_band_rise(samples, around, span=1.0):
    """Time of the steepest 50 ms rise of <150 Hz energy within +-span of ``around``."""
    np = _np()
    mono = samples.mean(axis=1)
    n = int(WINDOW * RATE)
    frames = len(mono) // n
    if frames < 3:
        return None
    spectrum = np.abs(np.fft.rfft(mono[:frames * n].reshape(frames, n) * np.hanning(n), axis=1)) ** 2
    freqs = np.fft.rfftfreq(n, 1 / RATE)
    low = 10 * np.log10(spectrum[:, freqs < 150].sum(axis=1) + 1e-12)
    rise = np.diff(low)
    lo, hi = max(0, int((around - span) / WINDOW)), min(len(rise), int((around + span) / WINDOW))
    if hi <= lo:
        return None
    i = lo + int(np.argmax(rise[lo:hi]))
    return {"time": (i + 1) * WINDOW, "rise_db": float(rise[i]),
            "before_db": float(np.median(low[max(0, i - 10):i + 1])), "after_db": float(np.median(low[i + 1:i + 11]))}


def duck_gain(path, duration):
    """Planned duck gain (dB) per 10 ms from the renderer's 1 kHz envelope WAV."""
    import array
    import wave
    np = _np()
    with wave.open(str(path), "rb") as w:
        data = array.array("i", w.readframes(w.getnframes()))
    gain = db(np.array(data, dtype=float) / (2 ** 31 - 1))
    return [{"time": i / 1000, "gain_db": round(float(gain[i]), 3)} for i in range(0, min(len(gain), int(duration * 1000) + 1), 10)]


def correlation(samples, window=.4):
    np = _np()
    n = int(window * RATE)
    out = []
    for i in range(0, len(samples) - n + 1, n):
        left, right = samples[i:i + n, 0], samples[i:i + n, 1]
        denom = np.sqrt((left ** 2).sum() * (right ** 2).sum())
        out.append(float((left * right).sum() / denom) if denom > 1e-12 else None)
    return out


def case_files(folder):
    folder = Path(folder)
    sidecars = sorted(folder.glob("*.music.json"))
    if len(sidecars) != 1:
        raise SystemExit(f"{folder}: expected one .music.json sidecar, found {len(sidecars)}")
    sidecar = sidecars[0]
    video = sidecar.with_name(sidecar.name.removesuffix(".music.json") + ".mp4")
    plan = folder / "plan.json" if (folder / "plan.json").is_file() else sidecar.with_name(
        sidecar.name.removesuffix(".music.json") + ".json")
    works = [p.parent for p in folder.rglob("music-stem.wav")]
    if len(works) != 1:
        raise SystemExit(f"{folder}: expected one kept render work folder with music-stem.wav, found {len(works)}")
    return video, plan, sidecar, works[0]


def build(folder, out, tracks):
    """Export one case and return its measurement record."""
    from myzing.audio import analyze
    from myzing.composition import Composition
    from myzing.music.ducking import duck_passages, passages, release_gap
    from myzing.music.dialogue import edge_fades
    from myzing.music.models import extract, timeline_of
    np = _np()
    video, plan_path, sidecar_path, work = case_files(folder)
    out.mkdir(parents=True, exist_ok=True)
    plan = Composition.from_json(plan_path.read_text(encoding="utf-8"))
    evidence = extract(plan)
    sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    duration = max(c.timeline_end for c in plan.clips)
    export(video, out / "mix.wav", out / "mix.mp3")
    export(work / "music-stem.wav", out / "music-bed.wav")
    mix, bed = decode(out / "mix.wav"), decode(work / "music-stem.wav")
    source = decode(work / "source-stem.wav") if (work / "source-stem.wav").is_file() else np.zeros_like(bed)
    length = min(len(mix), len(bed), len(source))
    mix, bed, source = mix[:length], bed[:length], source[:length]
    track = evidence.tracks[0]
    record = next((t for t in tracks if t["sha256"] == track["sha256"]), {"id": track["asset_id"]})
    offset, end = track["source_offset"], track["source_end"]
    audio = analyze(track["path"])
    beats = audio.beats or (sorted({t for r in audio.structure.rhythm_regions for t in r["beats"]}) if audio.structure else [])
    beats = [round(t - offset, 4) for t in beats if offset <= t <= end]
    moments = [{"kind": m.kind, "time": round(m.time - offset, 4), "confidence": m.confidence}
               for m in (audio.structure.moments if audio.structure else []) if offset <= m.time <= end]
    rows = timeline_of(plan.clips)
    cuts = [round(r["timeline_start"], 4) for r in rows[1:]]
    found = onsets(bed)
    strong = sorted(s for _, s in found)
    floor = strong[int(len(strong) * .75)] if strong else 0
    cut_report = []
    for cut in cuts:
        near = [(t, s) for t, s in found if abs(t - cut) <= .5]
        nearest = min(near, key=lambda x: abs(x[0] - cut), default=None)
        strongest = max(near, key=lambda x: x[1], default=None)
        cut_report.append({
            "cut": cut,
            "nearest_beat": min(beats, key=lambda b: abs(b - cut), default=None),
            "nearest_onset": None if nearest is None else {"time": round(nearest[0], 4), "offset_ms": round(1000 * (nearest[0] - cut), 1),
                                                           "strong": nearest[1] >= floor},
            "strongest_onset_within_500ms": None if strongest is None else {
                "time": round(strongest[0], 4), "offset_ms": round(1000 * (strongest[0] - cut), 1)}})
    alignments = [d for d in evidence.decisions if d["kind"] in ("drop_alignment", "moment_alignment")]
    drop_checks = [{"planned_output_time": d["output_time"], "low_band_rise": low_band_rise(bed, d["output_time"])}
                   for d in alignments]
    # Describe what the render did: sidecars written before the plateau rule
    # (no "plateau" key) used the plain hold merge and no edge rule.
    duck = {**evidence.duck(), **{k: v for k, v in (sidecar.get("duck") or {}).items() if k != "method"}}
    legacy = bool(sidecar.get("duck")) and "plateau" not in sidecar["duck"]
    if legacy:
        duck.update(plateau=0.0, gain_points=[])
    held = (passages(evidence.speech_spans, duck["hold"]) if legacy else
            duck_passages(evidence.speech_spans, duration, hold=duck["hold"], attack=duck["attack"],
                          release=duck["release"], plateau=duck["plateau"])) if evidence.speech_spans else []
    ramps = [(a - duck["attack"], a) for a, _ in held] + [(b, b + duck["release"]) for _, b in held]
    ramps += [(a, b) for (a, ga), (b, gb) in zip(duck["gain_points"], duck["gain_points"][1:]) if ga != gb]
    fade_in, fade_out = min(.15, (end - offset) / 4), min(1., (end - offset) / 4)
    ramps += [(0, fade_in), (end - offset - fade_out, end - offset)]
    bed_curve = rms_curve(bed)
    steps = []
    for i in range(1, len(bed_curve)):
        t = i * WINDOW
        if bed_curve[i] > -70 and not any(a - WINDOW <= t <= b + WINDOW for a, b in ramps):
            steps.append((abs(float(bed_curve[i] - bed_curve[i - 1])), t))
    steps.sort(reverse=True)
    reduction = rms_curve(mix, .01) - rms_curve(source + bed, .01)
    active = rms_curve(source + bed, .01) > -60
    active[:5] = active[-5:] = False  # AAC priming and padding at the edges are not limiting
    peak = float(np.abs(mix).max())
    record_out = {
        "version": 1, "case": Path(folder).name, "duration": duration, "width": plan.width, "height": plan.height,
        "track": {"id": record.get("id"), "attribution": record.get("attribution"), "license": record.get("license"),
                  "source_offset": offset, "source_end": end, "gain_db": next(a.gain_db for a in plan.audio if a.id == track["id"])},
        "cuts": cut_report, "planned_alignments": alignments, "drop_checks": drop_checks,
        "moments": moments, "beats": beats,
        "speech_spans": evidence.speech_spans, "duck": duck, "duck_passages": held,
        "dialogue_gains": evidence.dialogue_gains,
        "edge_fades": [[round(c.timeline_start, 3), list(f)] for c, f in zip(
            sorted(plan.clips, key=lambda c: c.timeline_start),
            edge_fades(sorted(plan.clips, key=lambda c: c.timeline_start), evidence.speech_spans)) if f]
        if evidence.speech_spans and any(a.duck_scope == "source_speech" for a in plan.audio) and not legacy else [],
        "release_gap": duck["hold"] if legacy else release_gap(duck["hold"], duck["attack"], duck["release"], duck["plateau"]),
        "fades": {"in": [0, fade_in], "out": [end - offset - fade_out, end - offset]},
        "sidecar": {k: v for k, v in sidecar.items() if k not in ("curve", "music_plan")},
        "mix_loudness": momentary(out / "mix.wav"), "bed_loudness": momentary(out / "music-bed.wav"),
        "mix_rms_50ms": [round(float(v), 2) for v in rms_curve(mix)],
        "bed_rms_50ms": [round(float(v), 2) for v in bed_curve],
        "source_rms_50ms": [round(float(v), 2) for v in rms_curve(source)],
        "largest_bed_steps_outside_ramps": [{"time": round(t, 3), "step_db": round(s, 2)} for s, t in steps[:8]],
        "limiter": {"max_gain_reduction_db": round(float(-reduction[active].min()), 2) if active.any() else 0.0,
                    "windows_over_1db": int((reduction[active] < -1).sum()),
                    "basis": "10 ms RMS of final mix minus sum of pre-limiter stems (AAC encode included; first and last 50 ms excluded)"},
        "peaks": {"sample_peak_dbfs": round(float(db(peak)), 2),
                  "samples_over_minus1_dbfs": int((np.abs(mix) > 10 ** (-1 / 20)).sum()),
                  "true_peak_dbtp": None},
        "stereo_correlation_400ms": {"mix": correlation(mix), "bed": correlation(bed)},
    }
    record_out["peaks"]["true_peak_dbtp"] = record_out["mix_loudness"]["true_peak_dbtp"]
    if (work / "source-stem.wav").is_file():
        # The sidecar's speech-to-music figure is one gated aggregate; quiet
        # clauses can sit much closer to the bed than it suggests.
        from myzing.music.measurement import window_loudness
        clauses = []
        for a, b in evidence.speech_spans:
            speech = window_loudness(work / "source-stem.wav", [[a, b]], duration)
            music = window_loudness(work / "music-stem.wav", [[a, b]], duration)
            clauses.append({"span": [a, b], "speech_lufs": speech, "music_lufs": music,
                            "separation_lu": None if speech is None or music is None else round(speech - music, 1)})
        record_out["clause_separation"] = clauses  # gated FFmpeg meter per clause, a cross-check
        record_out["sidecar_clauses"] = sidecar.get("clauses", [])  # renderer's ungated per-clause rows
    if (work / "music-duck.wav").is_file():
        record_out["duck_gain_10ms"] = duck_gain(work / "music-duck.wav", duration)
    (out / "measurements.json").write_text(json.dumps(record_out, indent=1, allow_nan=False), encoding="utf-8")
    (out / "timing.md").write_text(timing_sheet(record_out), encoding="utf-8")
    return record_out


def timing_sheet(m):
    t = m["track"]
    lines = [f"# Timing sheet: {m['case']}", "",
             f"Edit: {m['duration']:.3f} s, {m['width']}x{m['height']}. All times are seconds in the edit (mix.wav).",
             f"Music: {t['id']} by {t['attribution']} ({t['license']}); source excerpt {t['source_offset']:.3f}-"
             f"{t['source_end']:.3f} s, gain {t['gain_db']:+.2f} dB.", "",
             "## Cuts", ""]
    for c in m["cuts"]:
        lines.append(f"- {c['cut']:.3f}")
    lines += ["", "## Planned music alignments", ""]
    for d in m["planned_alignments"]:
        lines.append(f"- {d['kind']}: cut at {d['output_time']:.3f} placed on the track's detected drop/moment.")
    if not m["planned_alignments"]:
        lines.append("- none (speech-led edits do not force a song moment under dialogue)")
    lines += ["", "## Detected song moments inside the excerpt", ""]
    lines += [f"- {x['kind']} at {x['time']:.3f}" for x in m["moments"]] or ["- none"]
    lines += ["", "## Speech clauses (source speech)", ""]
    separation = {tuple(c["span"]): c["separation_lu"] for c in m.get("clause_separation", [])}
    separation.update({(c["start"], c["end"]): c["separation_lu"] for c in m.get("sidecar_clauses", [])})
    lines += [f"- {a:.3f}-{b:.3f}" + (f" (speech {separation[(a, b)]} LU above the bed)" if separation.get((a, b)) is not None else "")
              for a, b in m["speech_spans"]] or ["- none (music only)"]
    if m["duck_passages"]:
        d = m["duck"]
        lines += ["", f"## Music ducking: {d['depth_db']:g} dB", "",
                  f"Gaps shorter than {m['release_gap']:g} s stay ducked. The bed starts going down {d['attack']:g} s "
                  f"before a passage and recovers over {d['release']:g} s after it. A passage that starts at 0.000 or "
                  "ends at the edit end keeps the bed ducked at that edge.", ""]
        for a, b in m["duck_passages"]:
            start = "ducked from the start" if a <= 1e-6 else f"down from {a - d['attack']:.3f}"
            end = ("held to the edit end" if b >= m["duration"] - 1e-6 else
                   f"recovering {b:.3f}-{min(m['duration'], b + d['release']):.3f}")
            lines.append(f"- ducked passage {a:.3f}-{b:.3f} ({start}, {end})")
    if m.get("dialogue_gains"):
        lines += ["", "## Dialogue gain per clip (source audio)", ""]
        lines += [f"- {r['start']:.3f}-{r['end']:.3f}: {r['gain_db']:+.1f} dB"
                  + (f", then a {r['compressor']['ratio']:g}:1 peak compressor above {r['compressor']['threshold_db']:.1f} dBFS"
                     if r.get("compressor") else "") for r in m["dialogue_gains"]]
    if m.get("edge_fades"):
        lines += ["", "## Source audio edge fades at cuts (clip start: filters)", ""]
        lines += [f"- clip at {t:.3f}: {', '.join(f)}" for t, f in m["edge_fades"]]
    points = m["duck"].get("gain_points") or []
    if points:
        lines += ["", "## Per-clip bed level (dB, on top of ducking)", ""]
        lines += [f"- {a:.3f}: {g:+.1f} dB" for a, g in points]
    f = m["fades"]
    lines += ["", "## Music fades", "", f"- fade in {f['in'][0]:.3f}-{f['in'][1]:.3f}", f"- fade out {f['out'][0]:.3f}-{f['out'][1]:.3f}",
              "", "## Measured loudness", ""]
    s = m["sidecar"]
    lines.append(f"- final mix: {s['integrated']['integrated_lufs']} LUFS integrated, {s['integrated']['true_peak_dbtp']} dBTP true peak, "
                 f"LRA {s['integrated']['loudness_range_lu']} LU")
    lines.append(f"- music bed alone: {s['music_integrated']['integrated_lufs']} LUFS integrated")
    if s.get("speech_to_music_lu") is not None:
        lines.append(f"- music under speech {s['music_speech_lufs']} LUFS vs source speech {s['source_speech_lufs']} LUFS "
                     f"({s['speech_to_music_lu']} LU apart); music in pauses "
                     + (f"{s['music_gap_lufs']} LUFS" if s.get("music_gap_lufs") is not None else "n/a (no released pause)"))
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="acceptance root with tracks.json and case folders")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("cases", nargs="+")
    args = parser.parse_args(argv)
    tracks = json.loads((args.root / "tracks.json").read_text(encoding="utf-8"))
    for case in args.cases:
        m = build(args.root / case, args.out / case, tracks)
        print(case, json.dumps({"cuts": m["cuts"], "limiter": m["limiter"], "peaks": m["peaks"],
                                "steps": m["largest_bed_steps_outside_ramps"][:3], "drops": m["drop_checks"]}))


if __name__ == "__main__":
    main()
