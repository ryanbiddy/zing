"""A conservative pulse fallback for layered attacks; never fill missing beats."""
from .media import SAMPLE_RATE, numpy
from .features import HOP
from .models import Tempo


def layered_pulse(features, onsets, duration):
    np = numpy()
    if duration < 8 or len(onsets) < 16:
        return None
    rms = features["rms"]
    if float(np.percentile(rms, 95)) < max(1e-4, float(np.percentile(rms, 20)) * 1.6):
        return None  # Beating partials in a steady drone are not percussion.
    flux = np.maximum(0, features["flux"] - np.median(features["flux"]))
    size = 1 << (2 * len(flux) - 1).bit_length()
    spectrum = np.fft.rfft(flux, size)
    ac = np.fft.irfft(spectrum * spectrum.conj(), size)[:len(flux)]
    if ac[0] <= 1e-10:
        return None
    ac /= ac[0]
    low, high = round(.3 * SAMPLE_RATE / HOP), round(1.0 * SAMPLE_RATE / HOP)
    peaks = [i for i in range(low, min(high, len(ac) - 1)) if ac[i] > ac[i - 1] and ac[i] >= ac[i + 1] and ac[i] >= .18]
    times = np.array([o.time for o in onsets])
    weights = np.array([o.strength for o in onsets])
    best = None
    for lag in sorted(peaks, key=lambda i: ac[i], reverse=True)[:8]:
        period = lag * HOP / SAMPLE_RATE
        # Sub-frame autocorrelation interpolation reduces drift on long tracks.
        denom = ac[lag - 1] - 2 * ac[lag] + ac[lag + 1]
        if abs(denom) > 1e-10:
            period += .5 * (ac[lag - 1] - ac[lag + 1]) / denom * HOP / SAMPLE_RATE
        phases = np.arange(0, period, .01)
        votes = [float(np.sum(weights[np.abs((times - p + period / 2) % period - period / 2) < .04])) for p in phases]
        phase = float(phases[int(np.argmax(votes))])
        for _ in range(3):
            ticks = np.rint((times - phase) / period)
            mask = np.abs(times - phase - ticks * period) < .04
            if mask.sum() < 16:
                break
            period, phase = np.polyfit(ticks[mask], times[mask], 1, w=weights[mask])
        else:
            # Evidence must cover repeated windows, not a single lucky burst.
            chosen = {}
            for t, tick, weight in zip(times[mask], ticks[mask], weights[mask]):
                if tick not in chosen or weight > chosen[tick][1]:
                    chosen[tick] = (float(t), float(weight))
            if len(chosen) < 16:
                continue
            keys = sorted(chosen)
            occupancy = len(keys) / (keys[-1] - keys[0] + 1)
            windows = [sum(a <= k < a + 16 for k in keys) / 16 for a in range(int(keys[0]), int(keys[-1]) - 15, 16)]
            if occupancy < .7 or not windows or np.mean(np.array(windows) >= .65) < .7:
                continue
            supported = [chosen[k][0] for k in keys]
            confidence = min(.8, float(ac[lag]) * .5 + float(occupancy) * .5)
            score = confidence * float(np.mean([chosen[k][1] for k in keys]))
            if best is None or score > best[0]:
                best = (score, Tempo("steady", round(60 / float(period), 3), confidence,
                    "layered pulse: spectral-flux autocorrelation >=0.18, >=70% measured pulse occupancy, 70% of 16-pulse windows supported within 40ms; metrical ambiguity remains"), supported)
    return (best[1], best[2]) if best else None
