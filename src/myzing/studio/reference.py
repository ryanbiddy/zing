"""Bounded, offline reference preview using the existing study measurements."""

import json
import sys
import tempfile
import threading
from pathlib import Path

BUDGET_SECONDS = 8


def quick_read(source):
    from myzing.match.process import Cancelled, run_owned
    result = {"warnings": []}
    cancel = threading.Event()
    timer = threading.Timer(BUDGET_SECONDS, cancel.set)

    def receive(line):
        try:
            row = json.loads(line)
            if isinstance(row, dict) and row.get("studio_reference"):
                result.update(row["data"])
        except (ValueError, TypeError):
            pass

    timer.start()
    try:
        # The parent owns cleanup too: a deadline can kill the worker before
        # its Python finally blocks run. The process supervisor first reaps
        # every owned child, then this temporary sample can be removed safely.
        with tempfile.TemporaryDirectory(prefix="zing-reference-") as workspace:
            run_owned([sys.executable, "-m", __name__], json.dumps({"source": source, "workspace": workspace}),
                      cancel=cancel, progress=receive)
    except Cancelled:
        result["warnings"].append(f"Reference quick read reached its {BUDGET_SECONDS}s limit; unfinished measurements are unknown.")
    except (OSError, RuntimeError) as exc:
        result["warnings"].append(f"Reference quick read failed: {exc}")
    finally:
        timer.cancel()
    if result.get("error"):
        result["warnings"].append("Reference quick read was incomplete: " + result["error"] + "; missing measurements are unknown.")
    return describe(result)


def describe(result):
    result.setdefault("tone", "natural")
    if not result.get("duration"):
        result["reason"] = "Reference quick read failed; its style is unknown. Using clip evidence and starting preferences."
        return result
    rate = result.get("cuts_per_minute")
    if rate is not None:
        result["tone"] = "energetic" if rate >= 45 else "calm" if rate < 15 else "natural"
    rate_text = f"about {rate:.0f} cuts/min" if rate is not None else "cut rate unknown"
    def presence(key, label):
        value = result.get(key)
        return f"{label} unknown" if value is None else f"{label} observed" if value else f"no {label} detected"
    speech = f"speech {result['speech_ratio']:.0%}" if result.get("speech_ratio") is not None else presence("speech_present", "speech")
    music = "music likely (heuristic)" if result.get("music_present") else presence("music_present", "music")
    text = presence("text_present", "text")
    if result.get("text_samples"):
        text += f" in {result['text_samples']} sampled frames"
    duration = f"{result['duration']:.1f}" if result["duration"] >= 1 else f"{result['duration']:.2g}"
    result["reason"] = (f"Your reference is {duration} s, {result.get('aspect', 'aspect unknown')}; "
                        f"{rate_text} in the first {result.get('sample_seconds', 0):.3g} s; "
                        + ", ".join((speech, music, text)) + ".")
    return result


COMMON_ASPECTS = ("16:9", "9:16", "1:1", "4:3", "3:4", "4:5", "5:4", "3:2", "2:3", "21:9", "2:1", "1:2")


def aspect_label(width, height):
    """Displayed shape: an exact common ratio, 'about' one within 1%, else pixels."""
    from math import gcd
    divisor = gcd(width, height)
    exact = f"{width // divisor}:{height // divisor}"
    if exact in COMMON_ASPECTS:
        return exact
    def error(label):
        w, h = map(int, label.split(":"))
        return abs(width * h / (height * w) - 1)
    near = min(COMMON_ASPECTS, key=error)
    return "about " + near if error(near) <= .01 else f"{width}x{height}"


def _worker(source, workspace):
    from myzing.project.probe import probe_file
    from myzing.study import shots, audio, captions, proc
    def emit(data):
        print(json.dumps({"studio_reference": True, "data": data}), flush=True)
    try:
        probe = probe_file(Path(source)).to_dict()
    except proc.ToolMissing:
        raise  # a missing tool says nothing about the file
    except proc.MediaError as exc:
        emit({"unreadable": str(exc).strip().splitlines()[-1][:200]})
        raise
    if "no_video" in probe.get("flags", []):
        emit({"no_video": True})
        raise ValueError("Reference has no video stream")
    duration = probe.get("duration") or 0
    w, h = probe.get("width"), probe.get("height")
    if not w or not h or not duration:
        raise ValueError("Reference video dimensions or duration unavailable")
    if abs(probe.get("rotation") or 0) % 180 == 90:
        w, h = h, w  # the displayed shape; FFmpeg autorotates the sample below too
    aspect = aspect_label(w, h)
    seconds = min(duration, 20)
    emit({"duration": duration, "aspect": aspect, "orientation": probe.get("orientation"), "display_size": [w, h],
          "has_audio": probe.get("has_audio"), "sample_seconds": seconds,
          "sample_width": 480, "scope": "first 20 seconds at most, reduced resolution; full study follows confirmation"})
    tmp = workspace
    sample = Path(tmp) / "sample.mp4"
    proc.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-i", source,
              "-t", str(seconds), "-vf", "scale=480:-2", "-c:v", "libx264", "-preset", "ultrafast",
              "-threads", "1", "-c:a", "aac", str(sample)], timeout=BUDGET_SECONDS)
    fps = probe.get("fps") or 30
    if isinstance(fps, dict):
        fps = fps["numerator"] / fps["denominator"]
    measured = shots.detect_shots(sample, seconds, fps)
    emit({"cuts_per_minute": (len(measured.shots) - 1) * 60 / seconds if measured.shots else None})
    if probe.get("has_audio"):
        measured_audio = audio.measure_audio(sample, seconds)
        emit({"speech_present": measured_audio.audio.has_voiceover if measured_audio.speech_segments is not None else None,
              "speech_ratio": measured_audio.audio.speech_ratio if measured_audio.speech_segments is not None else None,
              "music_present": measured_audio.audio.has_music if measured_audio.audio.music_confidence > 0 else None,
              "music_confidence": measured_audio.audio.music_confidence})
    else:
        emit({"speech_present": False, "music_present": False})
    # Sparse preview, using the study engine's local-only OCR backend and
    # confidence threshold. Full caption timing is left to confirmed study.
    try:
        import cv2
        from myzing.study.caption_models import engine
        reader, _ = engine()
        capture = cv2.VideoCapture(str(sample))
        found = []
        try:
            for second in (0, seconds / 2, max(0, seconds - .2)):
                capture.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
                ok, frame = capture.read()
                if ok:
                    found.append(bool(captions._ocr(reader, frame)))
        finally:
            capture.release()
        emit({"text_present": any(found) if found else None, "text_samples": len(found)})
    except (ImportError, OSError, ValueError, RuntimeError):
        emit({"text_present": None})
    # Explain performs a full study. Leave that to confirmed path d; this
    # preview reuses study's shot/audio/OCR measurements within its deadline.


if __name__ == "__main__":
    payload = json.loads(sys.stdin.readline())  # ownership handshake before children
    try:
        _worker(payload["source"], payload["workspace"])
    except Exception as exc:
        print(json.dumps({"studio_reference": True, "data": {"error": str(exc)}}), flush=True)
