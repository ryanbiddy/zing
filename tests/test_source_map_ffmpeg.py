"""Authored cuts and lookalikes, encoded and decoded through the real stack."""

import shutil
import subprocess
from types import SimpleNamespace

import pytest

from myzing.study.shots import detect_shots
from myzing.study.source_map import build_source_map, planning_shots


CASES = ["short5", "short6", "flash1", "flash2", "flash3", "shake", "fast_pan",
         "whip_pan", "dissolve", "fade_in", "fade_out", "exposure_step", "suppressed_peak"]


def pictures(kind):
    import cv2
    import numpy as np

    rng = np.random.default_rng(1023)
    # Independent, textured pictures with different colors, not solid swatches.
    a, b, c, d = [cv2.GaussianBlur(rng.integers(0, 256, (96, 160, 3), dtype=np.uint8), (15, 15), 0)
                  for _ in range(4)]
    for i, frame in enumerate((a, b, c, d)):
        frame[:, :, i % 3] //= 4
        cv2.rectangle(frame, (12 + i * 18, 20), (50 + i * 18, 60), (230, 60 + i * 40, 30), -1)
    result = []
    gap = 5 if kind == "short5" else 6
    for n in range(90):
        frame = a if n < 30 else b
        if kind == "suppressed_peak":
            # Small red-tint changes cross HSV's hue wrap before a real cut.
            # Large neighboring hue scores suppress the adaptive ratio even
            # though the persistent RGB picture change at frame 45 is clear.
            gray = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
            frame = np.repeat(gray[:, :, None], 3, axis=2)
            frame[:, :, 2] += 20
            frame[:, :, 0 if 42 <= n < 45 and n % 2 else 1] += 2
            if n >= 45:
                frame = cv2.addWeighted(c, .9, np.full_like(c, 180), .1, 0)
        elif kind.startswith("short"):
            frame = c if 30 + gap <= n < 30 + gap + 6 else d if n >= 30 + gap + 6 else frame
        elif kind.startswith("flash") and 33 <= n < 33 + int(kind[-1]):
            frame = np.full_like(b, 255)
        elif kind == "shake" and 33 <= n < 36:
            frame = np.roll(b, (13, 43 if n % 2 else -37), axis=(0, 1))
        elif kind == "fast_pan" and n >= 33:
            frame = np.roll(b, 43 + min(n - 33, 25), axis=1)
        elif kind == "whip_pan" and n >= 33:
            frame = np.roll(b, min(60, (n - 32) * 12), axis=1)
            if n < 38:
                frame = cv2.blur(frame, (19, 1))
        elif kind == "dissolve" and n >= 33:
            t = min(1., (n - 32) / 15)
            frame = cv2.addWeighted(b, 1 - t, c, t, 0)
        elif kind in {"fade_in", "fade_out"} and n >= 33:
            t = min(1., (n - 32) / 18)
            # Fade toward white/black, then hold: no new source shot.
            frame = cv2.addWeighted(b, 1 - t, np.full_like(b, 255 if kind == "fade_in" else 0), t, 0)
        elif kind == "exposure_step" and n >= 33:
            frame = np.clip(b.astype(float) * 1.3 + 40, 0, 255).astype(np.uint8)
        result.append(frame)
    return result, ([45] if kind == "suppressed_peak" else
                    [30, 30 + gap, 30 + gap + 6] if kind.startswith("short") else [30])


@pytest.mark.ffmpeg
@pytest.mark.parametrize("kind", CASES)
def test_confirmed_fine_cuts_and_motion_lookalikes(tmp_path, kind):
    pytest.importorskip("cv2")
    pytest.importorskip("scenedetect")
    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg not installed")
    frames, truth = pictures(kind)
    # Preserve the subtle hue-wrap stimulus exactly in this one fixture.
    path = tmp_path / (kind + (".mkv" if kind == "suppressed_peak" else ".mp4"))
    codec = (["-c:v", "ffv1"] if kind == "suppressed_peak" else
             ["-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p"])
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
                    "-s", "160x96", "-r", "30", "-i", "pipe:0", *codec,
                    "-threads", "1", str(path)],
                   input=b"".join(f.tobytes() for f in frames), capture_output=True, check=True, timeout=30)
    before = detect_shots(path, 3., 30.)
    m = build_source_map(path, 3., 30., before.shots)
    assert m.status == "measured", m.warnings
    b = SimpleNamespace(shots=before.shots, meta=SimpleNamespace(duration=3., fps=30.),
                        provenance={"source_map": m.to_dict()})
    after = [round(s.start * 30) for s in planning_shots(b)[1:]]
    if kind.startswith("short") or kind == "suppressed_peak":
        assert after == truth, (kind, after, m.to_dict())
        assert len(before.shots) < len(after) + 1
        assert any(r["accepted"] for r in m.candidates)
        if kind == "suppressed_peak":
            assert any(r["accepted"] and r["evidence"]["proposal"] == "thumbnail HSV content>=25"
                       for r in m.candidates)
    else:
        # The public detector already over-cuts some flashes/fade endpoints.
        # This additive pass must introduce no new false boundaries, nor hide
        # those inherited errors by silently rewriting study.shots.
        assert after == [round(s.start * 30) for s in before.shots[1:]]
        assert set(truth) <= set(after)
        assert not any(r["accepted"] for r in m.candidates)
