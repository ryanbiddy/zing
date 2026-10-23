"""Two-pass x264 budgets and honest encoder-quality receipts."""

import json
import re
import subprocess


def encode(command, settings, duration, width, height, fps, directory, *, ffprobe="ffprobe"):
    from .pipeline import RenderError

    rate = settings.video_rate(duration)
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

    run(first)
    # Silence often uses far less than 192 kb/s AAC. Use its measured first-pass
    # payload rate, so small files do not undershoot from a fictional audio bill.
    if settings.target_mb is not None:
        probe = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries",
                                "stream=bit_rate", "-of", "json", str(first_path)],
                               capture_output=True, text=True, timeout=30, check=False)
        if probe.returncode:
            raise RenderError("Cannot measure first-pass audio budget: " + probe.stderr[-1000:])
        streams = json.loads(probe.stdout).get("streams", [])
        audio_rate = float(streams[0].get("bit_rate", 192000)) if streams else 0
        rate = max(16000, round(settings.target_mb * 8_000_000 * .985 / duration - audio_rate))
        command[command.index("-b:v") + 1] = str(rate)
    result = run(command)
    output = directory / "rendered.mp4"
    size = output.stat().st_size
    rows = re.findall(r"frame\s+[IPB]:\s*(\d+)\s+Avg QP:\s*([\d.]+)", result.stderr)
    count = sum(int(n) for n, _ in rows)
    qp = sum(int(n) * float(q) for n, q in rows) / count if count else None
    bpp = rate / (width * height * fps)
    warnings = []
    if (qp is not None and qp >= 30) or bpp < .04:
        warnings.append("Delivery budget risks visible quality loss (high encoder quantization or low bits/pixel); increase target MB/bitrate and inspect faces and motion.")
    error = size / (settings.target_mb * 1_000_000) - 1 if settings.target_mb is not None else None
    if error is not None and abs(error) > .10:
        warnings.append(f"Achieved size differs from the target by {error:+.1%}; very simple or very short clips can miss a two-pass budget.")
    receipt = {"version": 1, "method": "x264-two-pass", "requested": settings.to_dict(),
               "achieved_bytes": size, "achieved_mb": size / 1_000_000,
               "achieved_total_kbps": size * 8 / duration / 1000, "video_target_bps": rate,
               "relative_size_error": error,
               "quality": {"mean_encoder_qp": qp, "target_bits_per_pixel_frame": bpp,
                           "basis": "Encoder quantization and bitrate risk heuristic; no perceptual quality score or human review implied."},
               "warnings": warnings}
    (directory / "delivery-encoding.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    (directory / "x264-budget.log").write_text(result.stderr, encoding="utf-8")
    first_path.unlink()
    return result, command, receipt
