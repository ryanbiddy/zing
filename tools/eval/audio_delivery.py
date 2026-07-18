"""Measure advisory delivery loudness without changing eval pass/fail."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Sequence


TARGET_INTEGRATED_LUFS = -14.0
INTEGRATED_RANGE_LUFS = (-18.0, -10.0)
MAX_TRUE_PEAK_DBTP = -1.0
MEASUREMENT = "ITU-R BS.1770 via FFmpeg ebur128=peak=true"


def unavailable_audio_delivery(reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "integrated_lufs": None,
        "true_peak_dbtp": None,
        "warnings": [],
        "reason": reason,
    }


def _last_finite(pattern: str, output: str) -> float | None:
    matches = re.findall(pattern, output, flags=re.IGNORECASE)
    if not matches:
        return None
    value = matches[-1]
    if value.lower() in {"inf", "+inf", "-inf"}:
        return None
    return float(value)


def parse_ebur128(output: str) -> tuple[float | None, float | None]:
    """Return the final ebur128 summary's integrated LUFS and true peak."""
    integrated = _last_finite(
        r"\bI:\s*([+-]?(?:\d+(?:\.\d+)?|inf))\s+LUFS",
        output,
    )
    true_peak = _last_finite(
        r"\bPeak:\s*([+-]?(?:\d+(?:\.\d+)?|inf))\s+dBFS",
        output,
    )
    return integrated, true_peak


def measure_audio_delivery(
    media_path: Path,
    ffmpeg: str = "ffmpeg",
) -> dict[str, Any]:
    if not media_path.is_file():
        return unavailable_audio_delivery("media file is not present")
    if shutil.which(ffmpeg) is None:
        return unavailable_audio_delivery(f"ffmpeg executable not found: {ffmpeg}")
    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-nostats",
                "-i",
                str(media_path),
                "-filter_complex",
                "ebur128=peak=true",
                "-f",
                "null",
                "-",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return unavailable_audio_delivery(f"could not run ffmpeg: {exc}")
    if result.returncode:
        detail = result.stderr.strip().splitlines()
        reason = detail[-1] if detail else "unknown FFmpeg error"
        return unavailable_audio_delivery(f"ffmpeg ebur128 failed: {reason}")

    integrated, true_peak = parse_ebur128(result.stderr)
    if integrated is None and true_peak is None:
        return unavailable_audio_delivery(
            "ffmpeg ebur128 returned no finite loudness measurements"
        )

    warnings = []
    if integrated is not None and not (
        INTEGRATED_RANGE_LUFS[0] <= integrated <= INTEGRATED_RANGE_LUFS[1]
    ):
        warnings.append(
            f"integrated loudness {integrated:.1f} LUFS is outside advisory "
            f"range [{INTEGRATED_RANGE_LUFS[0]:.1f}, "
            f"{INTEGRATED_RANGE_LUFS[1]:.1f}] LUFS"
        )
    if true_peak is not None and true_peak > MAX_TRUE_PEAK_DBTP:
        warnings.append(
            f"true peak {true_peak:.1f} dBTP exceeds advisory maximum "
            f"{MAX_TRUE_PEAK_DBTP:.1f} dBTP"
        )
    return {
        "available": True,
        "integrated_lufs": integrated,
        "true_peak_dbtp": true_peak,
        "warnings": warnings,
        "reason": None,
    }


def summarize_audio_delivery(cases: Sequence[dict[str, Any]]) -> dict[str, Any]:
    available = [
        case for case in cases if case["audio_delivery"]["available"]
    ]
    warnings = [
        f"{case['directory']}: {warning}"
        for case in cases
        for warning in case["audio_delivery"]["warnings"]
    ]
    return {
        "measurement": MEASUREMENT,
        "advisory_only": True,
        "target_integrated_lufs": TARGET_INTEGRATED_LUFS,
        "integrated_range_lufs": list(INTEGRATED_RANGE_LUFS),
        "max_true_peak_dbtp": MAX_TRUE_PEAK_DBTP,
        "available_case_count": len(available),
        "case_count": len(cases),
        "warnings": warnings,
    }
