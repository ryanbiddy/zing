"""Two-pass x264 budgets and honest encoder-quality receipts."""

import json
import re
import subprocess

MINIMUM_VIDEO_BPS = 16000
CONTAINER_SHARE = .985  # Reserve 1.5% of a size target for MP4 structure.
RETRIES = 3  # Extra second passes when a size target overshoots.


def _audio_bytes(path, ffprobe):
    """Exact first-pass audio payload in bytes, or None when ffprobe cannot say.

    Packet sizes are summed instead of trusting stream bit_rate, which can be
    absent, null or "N/A". No audio stream measures as zero bytes.
    """
    try:
        probe = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries", "packet=size",
                                "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if probe.returncode:
        return None
    sizes = [line.strip().rstrip(",") for line in probe.stdout.splitlines() if line.strip()]
    if not all(size.isdigit() for size in sizes):
        return None
    return sum(int(size) for size in sizes)


def encode(command, settings, duration, width, height, fps, directory, *, ffprobe="ffprobe"):
    from .pipeline import RenderError

    if settings.target_mb is not None:
        budget = settings.target_mb * 1_000_000
        if budget * CONTAINER_SHARE * 8 / duration < MINIMUM_VIDEO_BPS:
            raise RenderError(f"Delivery target {settings.target_mb:g} MB leaves less than 16 kb/s for "
                              f"{duration:.2f}s of video; increase --target-mb.")
        # First-pass statistics barely depend on its bitrate; assume 192 kb/s
        # AAC here and correct the video budget from measured audio below.
        rate = max(MINIMUM_VIDEO_BPS, round(budget * CONTAINER_SHARE * 8 / duration - 192000))
    else:
        rate = round(settings.video_bitrate_kbps * 1000)
    command = list(command)
    index = command.index("-crf")
    command[index:index+2] = ["-b:v", str(rate), "-pass", "2", "-passlogfile", str(directory / "x264-budget")]
    command[command.index("-loglevel") + 1] = "info"
    first = command.copy()
    first[first.index("-pass") + 1] = "1"
    first_path = directory / "budget-pass1.mp4"
    first[first.index(str(directory / "rendered.mp4"))] = str(first_path)

    def run(args):
        result = subprocess.run(args, cwd=directory, capture_output=True, text=True, timeout=900, check=False)
        if result.returncode:
            raise RenderError(f"x264 two-pass render failed: {result.stderr[-4000:]}")
        return result

    def second_pass():
        """Pass two; x264 refuses a rate below its pass-one minimum, so use that floor."""
        nonlocal rate
        result = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=900, check=False)
        floor = re.search(r"requested bitrate is too low\. estimated minimum is (\d+) kbps", result.stderr)
        if result.returncode and floor and int(floor.group(1)) * 1000 > rate:
            rate = round(int(floor.group(1)) * 1000 * 1.05)
            command[command.index("-b:v") + 1] = str(rate)
            notes.append(f"x264 needs at least {floor.group(1)} kb/s for this material; encoded at {rate // 1000} kb/s.")
            return run(command), True
        if result.returncode:
            raise RenderError(f"x264 two-pass render failed: {result.stderr[-4000:]}")
        return result, False

    run(first)
    notes = []
    audio_bytes = _audio_bytes(first_path, ffprobe)
    if audio_bytes is None:
        audio_bytes = round(192000 * duration / 8)
        notes.append("First-pass audio size was unmeasurable; assumed the configured 192 kb/s AAC.")
    if settings.target_mb is not None:
        # Silence often uses far less than 192 kb/s. Use the measured payload,
        # so small files do not undershoot from a fictional audio bill. Pass
        # two may use any bitrate: x264 scales from pass-one complexity.
        video_bits = budget * CONTAINER_SHARE * 8 - audio_bytes * 8
        if video_bits / duration < MINIMUM_VIDEO_BPS:
            raise RenderError(f"Delivery target {settings.target_mb:g} MB leaves less than 16 kb/s for video after "
                              f"{audio_bytes * 8 / duration / 1000:.0f} kb/s of measured audio; increase --target-mb.")
        rate = round(video_bits / duration)
        command[command.index("-b:v") + 1] = str(rate)
    output = directory / "rendered.mp4"
    attempts = []
    for attempt in range(RETRIES + 1):
        result, floored = second_pass()
        size = output.stat().st_size
        attempts.append({"video_target_bps": rate, "bytes": size})
        if (settings.target_mb is None or size <= budget or rate <= MINIMUM_VIDEO_BPS or floored
                or attempt == RETRIES):
            break
        # x264's average bitrate overshoots on very short clips (the first
        # I-frame and rate-control warm-up dominate). Rerun pass two, reusing
        # the pass-one statistics, with the video share scaled to fit.
        spent = max(1, size - audio_bytes)
        rate = max(MINIMUM_VIDEO_BPS, round(rate * (budget * CONTAINER_SHARE - audio_bytes) / spent * .98))
        command[command.index("-b:v") + 1] = str(rate)
    rows = re.findall(r"frame\s+[IPB]:\s*(\d+)\s+Avg QP:\s*([\d.]+)", result.stderr)
    count = sum(int(n) for n, _ in rows)
    qp = sum(int(n) * float(q) for n, q in rows) / count if count else None
    bpp = rate / (width * height * fps)
    warnings = []
    if (qp is not None and qp >= 30) or bpp < .04:
        warnings.append("Delivery budget risks visible quality loss (high encoder quantization or low bits/pixel); increase target MB/bitrate and inspect faces and motion.")
    error = size / budget - 1 if settings.target_mb is not None else None
    if error is not None and error > 0:
        warnings.append(f"Delivery is {error:+.1%} over the {settings.target_mb:g} MB target after {len(attempts)} "
                        "second pass(es): the material needs more bits than the budget allows even at coarse "
                        "quantization; raise --target-mb or shorten the edit.")
    elif error is not None and error < -.10:
        notes.append(f"Delivery used {-error:.1%} less than the target: simple or very short material needed fewer bits.")
    receipt = {"version": 1, "method": "x264-two-pass", "requested": settings.to_dict(),
               "achieved_bytes": size, "achieved_mb": size / 1_000_000,
               "achieved_total_kbps": size * 8 / duration / 1000, "video_target_bps": rate,
               "audio_bytes": audio_bytes, "second_passes": attempts,
               "relative_size_error": error,
               "quality": {"mean_encoder_qp": qp, "target_bits_per_pixel_frame": bpp,
                           "basis": "Encoder quantization and bitrate risk heuristic; no perceptual quality score or human review implied."},
               "warnings": warnings, "notes": notes}
    (directory / "delivery-encoding.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    (directory / "x264-budget.log").write_text(result.stderr, encoding="utf-8")
    first_path.unlink()
    return result, command, receipt
