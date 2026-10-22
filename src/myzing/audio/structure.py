"""Offline musical evidence. Scores are rules, never calibrated probabilities."""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import Record
from .media import SAMPLE_RATE, numpy, run_ffmpeg, input_args
from .features import HOP


@dataclass
class Moment(Record):
    time: float
    strength: float
    kind: str
    confidence: float
    evidence: str
    version: int = 1


@dataclass
class Structure(Record):
    rhythm_regions: list[dict] = field(default_factory=list)
    bars: list[float] = field(default_factory=list)
    meter: int | None = None
    meter_confidence: float = 0.0
    phrases: list[dict] = field(default_factory=list)
    sections: list[dict] = field(default_factory=list)
    energy: list[dict] = field(default_factory=list)
    moments: list[Moment] = field(default_factory=list)
    vocals: dict = field(default_factory=lambda: {"status": "unknown", "confidence": 0.0})
    intro_seconds: float | None = None
    quality: dict = field(default_factory=dict)
    version: int = 1

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        data["moments"] = [Moment.from_dict(m) for m in data.get("moments", [])]
        return super().from_dict(data)


ATTACK_RISE_DB = 6.0
ATTACK_SHARE = .005
ATTACK_FLOOR_RMS = 10 ** (-60 / 20)


def salient_attacks(features):
    """Times where a band rises >=6 dB above its level 20-80 ms earlier.

    The band must hold at least 0.5% of the loudest frame energy in the past
    second, so tails and clicks after a loud hit do not count, and the frame
    must be above -60 dBFS. Steady tones and noise beds produce none, and the
    floor does not depend on the loudest attack in the track, so a loud
    pickup cannot hide the quieter kicks after it.
    """
    np = numpy()
    bands = features["bands"]
    n = len(bands)
    if n < 12:
        return []
    window = np.lib.stride_tricks.sliding_window_view
    smooth = (bands + np.vstack([bands[1:], bands[-1:]])) / 2
    reference = window(np.pad(smooth, ((8, 0), (0, 0)), mode="edge"), 6, axis=0)[:n].mean(axis=-1)
    rise = 10 * np.log10((smooth + 1e-16) / (reference + 1e-16))
    total = smooth.sum(axis=1)
    recent = window(np.pad(total, (100, 0), mode="edge"), 101).max(axis=1)[:n]
    score = np.where(smooth / np.maximum(recent, 1e-16)[:, None] >= ATTACK_SHARE, rise, 0.0).max(axis=1)
    score[:3] = 0.0
    score[features["rms"] < ATTACK_FLOOR_RMS] = 0.0
    peaks = np.flatnonzero((score >= ATTACK_RISE_DB) & (score >= np.r_[0, score[:-1]]) & (score > np.r_[score[1:], 0]))
    chosen: list[int] = []
    for index in peaks:
        if chosen and (index - chosen[-1]) * HOP / SAMPLE_RATE < .08:
            if score[index] > score[chosen[-1]]:
                chosen[-1] = int(index)
        else:
            chosen.append(int(index))
    return [round(i * HOP / SAMPLE_RATE, 6) for i in chosen]


def analyze_structure(features, tempo, beats, onsets, duration):
    np = numpy()
    result = Structure()
    times = np.arange(len(features["rms"])) * HOP / SAMPLE_RATE
    attacks = salient_attacks(features) if "bands" in features else [o.time for o in onsets]
    bins = np.arange(0, duration + .25, .25)
    onset_counts = np.histogram([o.time for o in onsets], bins=bins)[0] if len(bins) > 1 else []
    attack_counts = np.histogram(attacks, bins=bins)[0] if len(bins) > 1 else []
    # Quarter-second energy observations; loudness here is RMS dBFS, not LUFS.
    # Density counts salient attacks: a band rising >=6 dB over its recent
    # level. Every onset candidate is kept as onsets_per_second for audit.
    for k, t in enumerate(np.arange(0, duration, .25)):
        mask = (times >= t) & (times < t + .25)
        if not mask.any():
            continue
        rms = float(np.sqrt(np.mean(features["rms"][mask] ** 2)))
        low = float(np.sqrt(np.mean(features["low"][mask] ** 2)))
        result.energy.append({"time": round(float(t), 6), "rms_dbfs": round(20 * float(np.log10(max(rms, 1e-8))), 3),
                              "low_db": round(20 * float(np.log10(max(low, 1e-8))), 3),
                              "flux": float(np.mean(features["flux"][mask])),
                              "onsets_per_second": float(onset_counts[k] * 4.0) if k < len(onset_counts) else 0.0,
                              "attacks_per_second": float(attack_counts[k] * 4.0) if k < len(attack_counts) else 0.0})
    levels = np.array([e["rms_dbfs"] for e in result.energy])
    lows = np.array([e["low_db"] for e in result.energy])
    densities = np.array([e["attacks_per_second"] for e in result.energy])
    if len(levels) >= 8 and levels.max() > -50:
        ceiling = float(np.percentile(levels, 85))
        result.intro_seconds = next((i * .25 for i in range(len(levels) - 3)
                                     if float(np.median(levels[i:i + 4])) >= ceiling - 5), None)
        candidates = []
        events = [(o.time, True) for o in onsets if 4 <= o.time <= duration - 4]
        events += [(i * .25, False) for i in range(16, len(levels) - 15)
                   if not any(abs(o.time - i * .25) <= .75 for o in onsets)]
        for event_time, observed_attack in events:
            # The bin containing the attack belongs to the post-change side.
            # Rounding forward would contaminate the before window with it.
            i = int(event_time / .25)
            if i < 16 or i + 16 > len(levels):
                continue
            before, after = float(np.median(levels[i - 8:i])), float(np.median(levels[i:i + 16]))
            jump = after - before
            bass = float(np.median(lows[i:i + 16]) - np.median(lows[i - 8:i]))
            # A gain swell raises both bands together. Require a change of
            # texture: returning bass with repeated attacks, or a new attack
            # pattern. Sparse piano bass notes alone are not a beat drop.
            bass_share = float(np.median(lows[i:i + 16] - levels[i:i + 16]))
            share_jump = bass_share - float(np.median(lows[i - 8:i] - levels[i - 8:i]))
            density_before = float(np.mean(densities[i - 8:i]))
            density_after = float(np.mean(densities[i:i + 16]))
            recurring_attacks = sum(float(np.mean(densities[j:j + 4])) >= 1.5 for j in range(i, i + 16, 4)) >= 3
            frame = round(event_time * SAMPLE_RATE / HOP)
            def attack_jump(band, first=2, last=20):
                left = float(np.median(features[band][max(0, frame - 20):frame - 2]))
                right = float(np.median(features[band][frame + first:frame + last]))
                return 20 * float(np.log10(max(right, 1e-8) / max(left, 1e-8)))
            # Short decaying stabs carry their arrival in the first 10-80 ms;
            # a 200 ms median would hide it under the preceding pad.
            bass_attack, rms_attack = attack_jump("low"), attack_jump("rms", 1, 8)
            arrived = observed_attack and float(np.median(levels[i:i + 2])) >= after - 3
            bass_return = arrived and bass >= 6 and share_jump >= 3 and bass_share >= -18 and density_after >= 1.5 and recurring_attacks and bass_attack >= 6
            attack_return = arrived and density_after >= max(2., density_before * 1.75, density_before + 1.) and recurring_attacks and rms_attack >= 3
            earlier = levels[max(0, i - 24):i - 8]
            build = len(earlier) >= 4 and before - float(np.median(earlier)) >= 3
            # A break is a quieter dip, or a quieter section with sparse attacks
            # (a pad-only bar before a midrange drop).
            brk = (before < ceiling - 7 or (len(earlier) >= 4 and float(np.median(earlier)) - before >= 3)
                   or (before <= ceiling - 5 and density_before < 1.0))
            prior_activity = np.count_nonzero(levels[:i - 4] > -50) >= 4
            if jump >= 5 and (build or brk) and prior_activity and np.mean(levels[i:i + 16] >= before + 4) >= .8:
                kind = "drop" if bass_return or attack_return else "swell"
                # Rank actual texture returns within a change cluster, not
                # full-band flux (a vocal pickup can be louder than the kick).
                priority = (jump + max(0, bass)) * max(1., bass_attack if bass_return else rms_attack)
                candidates.append((kind == "drop", priority, event_time, jump, bass, build,
                                   share_jump, density_before, density_after, bass_attack, rms_attack, kind))
        for _, _, t, jump, bass, build, share_jump, density_before, density_after, bass_attack, rms_attack, kind in sorted(candidates, reverse=True):
            if any(abs(m.time - t) < 3 for m in result.moments):
                continue
            result.moments.append(Moment(t, min(1, max(0, jump + bass) / 30), kind, .8 if kind == "drop" else .6,
                f"4s sustained RMS +{jump:.1f} dB, bass +{bass:.1f} dB, bass-share change {share_jump:+.1f} dB, "
                f"attacks {density_before:.2f} to {density_after:.2f}/s after {'build' if build else 'break'}; "
                f"at the onset: bass {bass_attack:+.1f} dB (20–200 ms after vs before), RMS {rms_attack:+.1f} dB (10–80 ms after vs 20–200 ms before); "
                + ("texture return supports a drop" if kind == "drop" else "no supported bass/rhythm return; level swell only")))
        changes = []
        for i in range(8, len(levels) - 7):
            delta = abs(float(np.median(levels[i:i + 8]) - np.median(levels[i - 8:i])))
            if delta >= 4:
                changes.append((delta, i * .25))
        boundaries = [0.0]
        for delta, t in sorted(changes, reverse=True):
            if all(abs(t - b) >= 4 for b in boundaries):
                boundaries.append(t)
                if not any(abs(t - m.time) < 1 for m in result.moments):
                    result.moments.append(Moment(t, min(1, delta / 18), "section_change", .6, "sustained 2s level change; section name unknown"))
        boundaries = sorted(boundaries) + [duration]
        result.sections = [{"start": a, "end": b, "label": "section", "confidence": .6,
                            "evidence": "sustained energy partition; verse/chorus unknown"} for a, b in zip(boundaries, boundaries[1:])]
    # Isolated salient attacks, not every identical kick in a regular pulse.
    strengths = [o.strength for o in onsets]
    typical = float(np.median(strengths)) if strengths else 1
    for onset in onsets:
        if onset.strength >= max(.65, typical * 1.7) and all(abs(onset.time - m.time) > .8 for m in result.moments):
            result.moments.append(Moment(onset.time, onset.strength, "hit", .65, "salient spectral-flux attack above 1.7x median"))
    result.moments.sort(key=lambda m: m.time)
    if tempo.status == "steady" and len(beats) >= 16:
        interval = 60 / tempo.bpm
        ticks = np.rint((np.array(beats) - beats[0]) / interval).astype(int)
        accents = np.array([max((o.strength for o in onsets if abs(o.time - t) < .04), default=0) for t in beats])
        groups = [accents[ticks % 4 == p] for p in range(4)]
        medians = np.array([np.median(g) if len(g) >= 4 else 0 for g in groups])
        order = np.argsort(medians)
        phase = int(order[-1])
        if medians[phase] > max(.15, medians[order[-2]] * 1.55) and np.mean(groups[phase] > medians[order[-2]] * 1.35) >= .8:
            result.bars = [float(t) for t, tick in zip(beats, ticks) if tick % 4 == phase]
            result.meter, result.meter_confidence = 4, .7
            tempo.downbeats = list(result.bars)
            tempo.downbeat_status = "supported"
            # These are metric phrase candidates, anchored to supported accents.
            first_tick = next(int(tick) for tick in ticks if tick % 4 == phase)
            for bars in (4, 8, 16):
                result.phrases.extend({"time": float(t), "bars": bars, "confidence": .55,
                                       "evidence": "stable pulse and repeated 4-beat accent; metric phrase candidate"}
                                      for t, tick in zip(beats, ticks) if tick > first_tick and (tick - first_tick) % (bars * 4) == 0)
    audible = features["rms"] > 10 ** (-45 / 20)
    ratio = float(np.mean(features["vocal"][audible])) if audible.any() else 0.0
    result.vocals = {"status": "possible" if ratio >= .3 else "unknown" if ratio >= .18 else "not_detected", "confidence": .6 if ratio >= .3 else .3,
                     "coverage": ratio, "evidence": "multi-partial midrange with harmonic peaks and formant-region energy",
                     "limits": "Cannot distinguish singing/speech from harmonic instruments, or rule out masked/whispered vocals; no ASR or separation."}
    return result


def channel_quality(path, duration, true_peak):
    np = numpy()
    raw = run_ffmpeg(["-v", "error", *input_args(path, duration), "-ac", "2", "-ar", str(SAMPLE_RATE),
                      "-f", "f32le", "pipe:1"], timeout=max(30, duration * 2)).stdout
    x = np.frombuffer(raw, dtype="<f4").reshape(-1, 2).astype(np.float64)
    power = float(np.mean(x ** 2))
    corr = float(np.sum(x[:, 0] * x[:, 1]) / max(1e-20, np.sqrt(np.sum(x[:, 0] ** 2) * np.sum(x[:, 1] ** 2))))
    mono = float(np.mean(np.mean(x, axis=1) ** 2))
    return {"channel_correlation": corr if power > 1e-12 else None,
            "mono_loss_db": round(10 * float(np.log10(max(mono, 1e-20) / max(power, 1e-20))), 3),
            "mono_or_identical_channels": bool(power > 1e-12 and np.mean((x[:, 0] - x[:, 1]) ** 2) < power * 1e-5),
            "near_full_scale_fraction": float(np.mean(np.abs(x) >= .999)),
            "clipping_suspected": bool((true_peak is not None and true_peak >= 0) or np.mean(np.abs(x) >= .999) > .001),
            "basis": "22.05kHz stereo downmix + original-channel EBU true peak; clipping is a risk indicator, not proof of prior clipping"}
