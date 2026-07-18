"""Offline tests for media ingest: all external tools are mocked at the
single proc.run choke point; no network, no real ffmpeg. Storage paths come
from the shared zing_workspace fixture (Lane B's conftest)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from myzing import storage
from myzing.study import ingest
from myzing.study.proc import MediaError, ToolMissing


def probe_json(
    codec: str = "h264",
    avg: str = "30/1",
    declared: str = "30/1",
    duration: str = "42.5",
    with_audio: bool = True,
    width: int = 1080,
    height: int = 1920,
) -> str:
    streams = [{
        "codec_type": "video",
        "codec_name": codec,
        "width": width,
        "height": height,
        "avg_frame_rate": avg,
        "r_frame_rate": declared,
    }]
    if with_audio:
        streams.append({"codec_type": "audio", "codec_name": "aac"})
    return json.dumps({"streams": streams, "format": {"duration": duration}})


def ok(cmd: list[str], stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")


class FakeTools:
    """Dispatches proc.run calls per tool; records every command."""

    def __init__(self, probe_stdout: str = probe_json()):
        self.calls: list[list[str]] = []
        self.probe_stdouts = [probe_stdout]
        self.info: dict = {"uploader": "cleo", "title": "why ice"}

    def __call__(self, cmd: list[str], timeout: float | None = None):
        self.calls.append(cmd)
        tool = cmd[0]
        if tool == "ffprobe":
            out = (
                self.probe_stdouts.pop(0)
                if len(self.probe_stdouts) > 1
                else self.probe_stdouts[0]
            )
            return ok(cmd, out)
        if tool == "yt-dlp":
            dest = Path(cmd[cmd.index("-P") + 1])
            (dest / "media.mp4").write_bytes(b"fake-video")
            (dest / "media.info.json").write_text(json.dumps(self.info), encoding="utf-8")
            return ok(cmd)
        if tool == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"fake-cfr-video")
            return ok(cmd)
        raise AssertionError(f"unexpected tool call: {cmd}")

    def commands(self, tool: str) -> list[list[str]]:
        return [c for c in self.calls if c[0] == tool]


def use(monkeypatch, fake) -> None:
    monkeypatch.setattr("myzing.study.ingest.proc.run", fake)


# -- platform / parsing -----------------------------------------------------

@pytest.mark.parametrize("source,platform", [
    ("https://www.tiktok.com/@x/video/1", "tiktok"),
    ("https://www.instagram.com/reel/abc/", "instagram"),
    ("https://youtube.com/shorts/nlGYV0bmddI", "youtube"),
    ("https://youtu.be/nlGYV0bmddI", "youtube"),
    ("https://example.com/v.mp4", "url"),
    (r"C:\clips\take.mp4", "file"),
])
def test_detect_platform(source, platform):
    assert ingest.detect_platform(source) == platform


def test_fps_parses_rationals():
    assert abs(ingest._fps("30000/1001") - 29.97) < 0.01
    assert ingest._fps("0/0") == 0.0
    assert ingest._fps("garbage") == 0.0


# -- local file ingest ------------------------------------------------------

def test_local_file_ingest(zing_workspace, tmp_path, monkeypatch):
    fake = FakeTools()
    use(monkeypatch, fake)
    src = tmp_path / "take one.mp4"
    src.write_bytes(b"fake-video")

    result = ingest.ingest(str(src))

    assert result.slug == storage.slug_for(str(src))
    assert result.media_path.name == "media.mp4"
    assert result.media_path.is_file()
    assert result.breakdown_dir == storage.breakdown_dir(result.slug)
    assert storage.find_media(result.slug) == result.media_path
    m = result.meta
    assert m.platform == "file"
    assert m.title == "take one"
    assert (m.duration, m.width, m.height, m.fps) == (42.5, 1080, 1920, 30.0)
    assert m.media_path == "media.mp4"  # relative: folder must survive a move
    assert result.warnings == []


def test_local_file_missing_is_honest(zing_workspace, tmp_path, monkeypatch):
    use(monkeypatch, FakeTools())
    with pytest.raises(MediaError, match="no such file"):
        ingest.ingest(str(tmp_path / "nope.mp4"))


# -- URL ingest -------------------------------------------------------------

def test_url_ingest_fetches_and_reads_info(zing_workspace, monkeypatch):
    fake = FakeTools()
    use(monkeypatch, fake)
    url = "https://www.tiktok.com/@cleo/video/7239871234"

    result = ingest.ingest(url)

    (ytdlp_cmd,) = fake.commands("yt-dlp")
    assert url in ytdlp_cmd and "--no-playlist" in ytdlp_cmd
    assert ingest.YTDLP_FORMAT in ytdlp_cmd
    assert result.slug == "tiktok-7239871234"
    m = result.meta
    assert (m.platform, m.author, m.title) == ("tiktok", "cleo", "why ice")
    assert m.source_url == url
    assert result.media_path.is_file()


def test_url_ingest_reuses_existing_media(zing_workspace, monkeypatch):
    fake = FakeTools()
    use(monkeypatch, fake)
    url = "https://www.tiktok.com/@cleo/video/7239871234"
    target = storage.media_target(storage.slug_for(url), "mp4")
    target.write_bytes(b"already-here")

    result = ingest.ingest(url)

    assert fake.commands("yt-dlp") == []
    assert any("reusing" in w for w in result.warnings)


def test_url_fetch_failure_surfaces_stderr(zing_workspace, monkeypatch):
    def failing(cmd, timeout=None):
        if cmd[0] == "yt-dlp":
            return subprocess.CompletedProcess(cmd, 1, "", "ERROR: rate limited\n")
        return ok(cmd, probe_json())
    use(monkeypatch, failing)
    with pytest.raises(MediaError, match="rate limited"):
        ingest.ingest("https://www.tiktok.com/@x/video/9")


# -- normalization ----------------------------------------------------------

def test_vfr_source_is_normalized_in_place(zing_workspace, tmp_path, monkeypatch):
    fake = FakeTools()
    fake.probe_stdouts = [probe_json(avg="30/1", declared="60/1"), probe_json()]
    use(monkeypatch, fake)
    src = tmp_path / "vfr.mp4"
    src.write_bytes(b"fake")

    result = ingest.ingest(str(src))

    (ffmpeg_cmd,) = fake.commands("ffmpeg")
    assert "cfr" in ffmpeg_cmd and "libx264" in ffmpeg_cmd
    # Normalized file REPLACES the staged media: one canonical media.mp4.
    assert result.media_path.name == "media.mp4"
    assert result.media_path.read_bytes() == b"fake-cfr-video"
    assert not (result.breakdown_dir / "media_normalizing.mp4").exists()
    assert any("variable frame rate" in w for w in result.warnings)


def test_foreign_codec_webm_is_normalized_to_single_mp4(
    zing_workspace, tmp_path, monkeypatch
):
    fake = FakeTools()
    fake.probe_stdouts = [probe_json(codec="vp9"), probe_json()]
    use(monkeypatch, fake)
    src = tmp_path / "clip.webm"
    src.write_bytes(b"fake")

    result = ingest.ingest(str(src))

    assert result.media_path.name == "media.mp4"
    assert not (result.breakdown_dir / "media.webm").exists()  # original replaced
    assert storage.find_media(result.slug) == result.media_path
    assert any("re-encoded to H.264" in w for w in result.warnings)


# -- honesty on missing pieces ----------------------------------------------

def test_missing_ffprobe_points_at_doctor(zing_workspace, tmp_path, monkeypatch):
    inner = FakeTools()

    def no_ffprobe(cmd, timeout=None):
        if cmd[0] == "ffprobe":
            raise ToolMissing("ffprobe")
        return inner(cmd, timeout)
    use(monkeypatch, no_ffprobe)
    src = tmp_path / "a.mp4"
    src.write_bytes(b"fake")
    with pytest.raises(ToolMissing, match="zing doctor"):
        ingest.ingest(str(src))


def test_no_video_stream_is_an_error(zing_workspace, tmp_path, monkeypatch):
    fake = FakeTools(probe_stdout=json.dumps(
        {"streams": [{"codec_type": "audio"}], "format": {"duration": "3"}}
    ))
    use(monkeypatch, fake)
    src = tmp_path / "audio-only.mp4"
    src.write_bytes(b"fake")
    with pytest.raises(MediaError, match="no video stream"):
        ingest.ingest(str(src))


def test_no_audio_stream_warns_but_succeeds(zing_workspace, tmp_path, monkeypatch):
    fake = FakeTools(probe_stdout=probe_json(with_audio=False))
    use(monkeypatch, fake)
    src = tmp_path / "mute.mp4"
    src.write_bytes(b"fake")

    result = ingest.ingest(str(src))

    assert any("no audio stream" in w for w in result.warnings)
