"""EBU R128 on source channels, and advisory gain/limiter settings."""

from __future__ import annotations

import math
import re
from pathlib import Path

from .media import AudioError, MAX_SECONDS, duration_limit, input_args, local_file, run_ffmpeg
from .models import GainRecommendation, Loudness


def parse_ebur128(report: str) -> Loudness:
    """Read only the final summary, never momentary log values.

    FFmpeg reports the absolute-gate floor (-70 LUFS) for silence/too-short
    input. It is not a usable integrated measurement and becomes JSON null.
    """
    if "Summary:" not in report:
        raise AudioError("FFmpeg did not produce an ebur128 summary; check its ebur128 filter support.")
    summary = report.rsplit("Summary:", 1)[1]

    def number(pattern: str) -> float | None:
        match = re.search(pattern, summary)
        if not match:
            raise AudioError("Incomplete FFmpeg ebur128 report; integrated loudness, LRA, and true peak are required.")
        value = float(match.group(1))
        return value if math.isfinite(value) else None

    token = r"([-+]?\d+(?:\.\d+)?|[-+]?inf|nan)"
    integrated = number(r"\bI:\s*" + token + r"\s*LUFS")
    lra = number(r"\bLRA:\s*" + token + r"\s*LU")
    peak = number(r"True peak:\s*Peak:\s*" + token + r"\s*dBFS")
    if integrated is not None and integrated <= -70:
        integrated = None
    return Loudness(integrated, lra, peak)


def measure_loudness(path: str | Path, *, max_seconds: float = MAX_SECONDS) -> Loudness:
    duration_limit(max_seconds)
    path = local_file(path)
    result = run_ffmpeg([
        "-loglevel", "info", "-nostats", *input_args(path, max_seconds),
        "-af", f"atrim=duration={max_seconds:.9f},asetpts=PTS-STARTPTS,ebur128=peak=true:framelog=verbose",
        "-f", "null", "-",
    ], timeout=max(30, max_seconds * 2))
    return parse_ebur128(result.stderr.decode("utf-8", errors="replace"))


def recommend_gain(
    loudness: Loudness, *, target_lufs: float = -14.0, target_dbtp: float = -1.0,
) -> GainRecommendation:
    """Recommend settings; never modify media or promise an unmeasured result.

    Linear gain preserves integrated loudness except for gate changes. When
    peaks would exceed the ceiling, suggest an oversampled lookahead limiter
    with auto-level disabled. Limiting can lower LUFS: re-measure and iterate.
    """
    if not math.isfinite(target_lufs) or not -70 < target_lufs <= -5:
        raise ValueError("target_lufs must be finite, above -70 and at most -5")
    if not math.isfinite(target_dbtp) or not -9 <= target_dbtp <= 0:
        raise ValueError("target_dbtp must be finite and between -9 and 0")
    if loudness.integrated_lufs is None or loudness.true_peak_dbtp is None:
        raise ValueError("No usable loudness/true-peak measurement; measure a longer audible excerpt first.")
    gain = target_lufs - loudness.integrated_lufs
    # Allow 0.2 dB for summary rounding and resampling overshoot. This is a
    # planning margin, not a codec-independent true-peak guarantee.
    ceiling = target_dbtp - 0.2
    limiting = loudness.true_peak_dbtp + gain > ceiling
    filters = f"volume={gain:.6f}dB"
    warnings = ["Re-measure the final encoded output; gating and encoding can change LUFS and true peak."]
    if limiting:
        limit = 10 ** (ceiling / 20)
        filters = (
            f"aresample=192000,{filters},alimiter=limit={limit:.9f}:"
            "attack=5:release=50:level=0:latency=1,aresample=48000"
        )
        warnings.append("Limiting is required and may lower integrated loudness; the target needs a re-measure and possibly another pass.")
    return GainRecommendation(
        gain_db=round(gain, 6), target_lufs=target_lufs, target_dbtp=target_dbtp,
        limiter_required=limiting, limiter_ceiling_dbtp=ceiling,
        limiter_attack_ms=5.0, limiter_release_ms=50.0, limiter_sample_rate=192000,
        ffmpeg_filter=filters, predicted_lufs=None if limiting else target_lufs,
        warnings=warnings,
    )
