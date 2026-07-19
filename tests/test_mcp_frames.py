"""get_frames (B-Q8): honest errors, per-frame degradation, real extraction.

Unit tests mock the ffmpeg subprocess; one @pytest.mark.ffmpeg integration
test extracts real frames from a synthetic two-color video and content-
probes them (JPEG SOI magic + the two frames differ), per the B-Q3 design
note's test plan.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from myzing import mcp_server, storage
from myzing.schemas import Breakdown, Shot, VideoMeta

SLUG = "tiktok-777"
FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"fakejpegbody"


@pytest.fixture
def studied(zing_workspace):
    b = Breakdown(
        meta=VideoMeta(
            source_url="https://www.tiktok.com/@a/video/777",
            platform="tiktok",
            duration=10.0,
        ),
        shots=[Shot(index=0, start=0.0, end=10.0)],
    )
    storage.save_breakdown(b, slug=SLUG)
    storage.media_target(SLUG, "mp4").write_bytes(b"fake media")
    return b


@pytest.fixture
def fake_ffmpeg(monkeypatch):
    monkeypatch.setattr(mcp_server.shutil, "which", lambda n: f"/bin/{n}")
    calls: list[list[str]] = []

    def fake_run(cmd, capture_output=True, timeout=0, check=False):
        calls.append(cmd)

        class R:
            returncode = 0
            stdout = FAKE_JPEG
            stderr = b""

        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


# -- validation --------------------------------------------------------------

def test_get_frames_requires_timestamps(studied):
    result = mcp_server.h_get_frames(SLUG, [])
    assert result["ok"] is False and "shots[].start" in result["error"]


def test_get_frames_rejects_junk_timestamps(studied):
    assert mcp_server.h_get_frames(SLUG, ["abc"])["ok"] is False
    assert mcp_server.h_get_frames(SLUG, [-1.0])["ok"] is False


def test_get_frames_enforces_hard_cap(studied):
    result = mcp_server.h_get_frames(SLUG, [float(i) for i in range(9)])
    assert result["ok"] is False
    assert str(mcp_server.FRAMES_HARD_CAP) in result["error"]
    assert "second call" in result["error"]


def test_get_frames_unknown_slug(zing_workspace, monkeypatch):
    monkeypatch.setattr(mcp_server.shutil, "which", lambda n: f"/bin/{n}")
    result = mcp_server.h_get_frames("ghost-slug", [1.0])
    assert result["ok"] is False and "list_breakdowns" in result["error"]


def test_get_frames_media_gone_is_actionable(zing_workspace, monkeypatch):
    monkeypatch.setattr(mcp_server.shutil, "which", lambda n: f"/bin/{n}")
    b = Breakdown(meta=VideoMeta(source_url="https://youtu.be/x", platform="youtube"))
    storage.save_breakdown(b, slug="youtube-x")
    result = mcp_server.h_get_frames("youtube-x", [1.0])
    assert result["ok"] is False
    assert "media" in result["error"] and "study_video" in result["error"]


def test_get_frames_missing_ffmpeg(studied, monkeypatch):
    monkeypatch.setattr(mcp_server.shutil, "which", lambda n: None)
    result = mcp_server.h_get_frames(SLUG, [1.0])
    assert result["ok"] is False and "zing doctor" in result["error"]


# -- extraction (mocked ffmpeg) ----------------------------------------------

def test_get_frames_orders_and_labels(studied, fake_ffmpeg):
    result = mcp_server.h_get_frames(SLUG, [5.0, 0.5])
    assert result["ok"] is True
    labels = [f["label"] for f in result["frames"]]
    assert labels == ["Frame 1 @ t=0.50s", "Frame 2 @ t=5.00s"]  # sorted
    assert all(f["jpeg"] == FAKE_JPEG for f in result["frames"])
    assert all(
        "out_range=full" in call[call.index("-vf") + 1]
        for call in fake_ffmpeg
    )
    assert all(
        call[call.index("-color_range") + 1] == "pc"
        for call in fake_ffmpeg
    )


def test_get_frames_past_end_is_per_frame_honest(studied, fake_ffmpeg):
    result = mcp_server.h_get_frames(SLUG, [2.0, 99.0])
    assert result["ok"] is True
    good, bad = result["frames"]
    assert good["jpeg"] == FAKE_JPEG
    assert bad["jpeg"] is None
    assert "past the video's end" in bad["error"]
    assert "10.00s" in bad["error"]
    assert len(fake_ffmpeg) == 1  # no ffmpeg call wasted on the bad timestamp


def test_get_frames_ffmpeg_failure_is_per_frame(studied, monkeypatch):
    monkeypatch.setattr(mcp_server.shutil, "which", lambda n: f"/bin/{n}")

    def broken_run(cmd, capture_output=True, timeout=0, check=False):
        class R:
            returncode = 1
            stdout = b""
            stderr = b"Invalid data found when processing input"

        return R()

    monkeypatch.setattr(subprocess, "run", broken_run)
    result = mcp_server.h_get_frames(SLUG, [1.0])
    assert result["ok"] is True  # the call survives; the frame reports
    assert result["frames"][0]["jpeg"] is None
    assert "Invalid data" in result["frames"][0]["error"]


# -- real extraction (content probe, per the design note) --------------------

@pytest.mark.ffmpeg
def test_get_frames_real_two_color_probe(zing_workspace, tmp_path):
    video = tmp_path / "two-color.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=red:s=320x568:d=1",
            "-f", "lavfi", "-i", "color=c=blue:s=320x568:d=1",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]",
            "-map", "[v]", "-pix_fmt", "yuv420p", str(video),
        ],
        check=True, timeout=120,
    )
    b = Breakdown(
        meta=VideoMeta(source_url=str(video), platform="file", duration=2.0)
    )
    slug = storage.slug_for(str(video))
    storage.save_breakdown(b, slug=slug)
    media = storage.media_target(slug, "mp4")
    media.write_bytes(video.read_bytes())

    result = mcp_server.h_get_frames(slug, [0.2, 1.8])
    assert result["ok"] is True, result.get("error")
    red, blue = (f["jpeg"] for f in result["frames"])
    assert red[:2] == b"\xff\xd8" and blue[:2] == b"\xff\xd8"  # JPEG SOI
    assert len(red) > 500 and len(blue) > 500
    assert red != blue  # different colors -> different frames


@pytest.mark.ffmpeg
def test_get_frames_converts_limited_range_before_jpeg(
    tmp_path,
) -> None:
    video = tmp_path / "limited-range.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=red:s=320x180:r=30:d=1",
            "-vf", "scale=in_range=full:out_range=limited",
            "-color_range", "tv",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-bsf:v", "h264_metadata=video_full_range_flag=0",
            "-an",
            str(video),
        ],
        check=True,
        timeout=120,
    )
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=color_range",
            "-of", "default=nw=1:nk=1",
            str(video),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert probe.stdout.strip() == "tv"

    jpeg = mcp_server._extract_frame_jpeg(video, 0.0)

    assert jpeg.startswith(b"\xff\xd8")
    assert len(jpeg) > 500


@pytest.mark.ffmpeg
def test_get_frames_extracts_from_subsecond_clip(tmp_path) -> None:
    video = tmp_path / "short.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=30:d=0.1",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-an",
            str(video),
        ],
        check=True,
        timeout=120,
    )

    jpeg = mcp_server._extract_frame_jpeg(video, 0.0)

    assert jpeg.startswith(b"\xff\xd8")
    assert len(jpeg) > 500


def test_wrapper_interleaves_text_and_images(studied, fake_ffmpeg):
    pytest.importorskip("mcp")
    server = mcp_server.build_server()
    import anyio

    async def call():
        return await server.call_tool(
            "get_frames", {"slug": SLUG, "timestamps": [1.0, 99.0]}
        )

    result = anyio.run(call)
    content = result[0] if isinstance(result, tuple) else result
    kinds = [c.type for c in content]
    assert kinds == ["text", "image", "text"]  # label, jpeg, past-end notice
    assert "Frame 1 @ t=1.00s" in content[0].text
    assert content[1].mimeType == "image/jpeg"
    assert "past the video's end" in content[2].text
