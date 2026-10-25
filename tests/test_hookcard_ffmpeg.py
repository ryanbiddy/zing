"""Known RGB frames verify endpoint and cold-open evidence on real FFmpeg."""

import subprocess

import pytest

from myzing.explain.hook import measure_visual

pytestmark = pytest.mark.ffmpeg


def encode(path, colors):
    data = b"".join(bytes(color) * (64 * 64) for color in colors)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                    "-s", "64x64", "-r", "10", "-i", "pipe:0", "-an", "-c:v", "libx264",
                    "-crf", "0", "-pix_fmt", "yuv444p", str(path)],
                   input=data, check=True, capture_output=True, timeout=30)
    return path


RED, BLUE, GREEN, WHITE = (240, 10, 10), (10, 10, 240), (10, 200, 10), (240, 240, 240)


@pytest.mark.parametrize("clean", [True, False])
def test_loop_compares_actual_last_frame_not_last_half_second_sample(tmp_path, clean):
    colors = [RED] * 10 + [WHITE] * 69 + [RED if clean else BLUE]
    source = encode(tmp_path / "seam.mp4", colors)
    row = measure_visual(source, 8, 10)["loop_seam"]
    assert row["status"] == "measured", row
    value = row["value"]
    assert value["loops_cleanly"] is clean and value["last_seconds"] == 7.9
    assert (value["similarity"] > .98) is clean


@pytest.mark.parametrize("repeat", [True, False])
def test_flash_forward_reports_matching_later_timestamp_or_abstains(tmp_path, repeat):
    colors = [RED] * 10 + [GREEN] * 20 + [WHITE] * 30 + [RED if repeat else BLUE] * 10 + [BLUE] * 10
    source = encode(tmp_path / "cold-open.mp4", colors)
    row = measure_visual(source, 8, 10)["flash_forward"]
    assert row["status"] == "measured", row
    value = row["value"]
    assert value["candidate"] is repeat
    assert value["matched_seconds"] == (6 if repeat else None)
    assert value["best_later_seconds"] > 4
