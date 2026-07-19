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


def pts_csv(deltas: list[float], start: float = 0.0) -> str:
    """Packet pts_time CSV as the F-06 scan reads it: one packet per line,
    times built by accumulating the given per-frame deltas."""
    times = [start]
    for d in deltas:
        times.append(times[-1] + d)
    return "\n".join(f"{t:.6f}" for t in times) + "\n"


CFR_30 = pts_csv([1 / 30] * 240)  # a clean constant-frame-rate packet scan


class FakeTools:
    """Dispatches proc.run calls per tool; records every command."""

    def __init__(self, probe_stdout: str = probe_json()):
        self.calls: list[list[str]] = []
        self.probe_stdouts = [probe_stdout]
        self.pts_csv = CFR_30
        self.info: dict = {"uploader": "cleo", "title": "why ice"}

    def __call__(self, cmd: list[str], timeout: float | None = None):
        self.calls.append(cmd)
        tool = cmd[0]
        if tool == "ffprobe":
            if any("packet=pts_time" in part for part in cmd):
                return ok(cmd, self.pts_csv)
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
    # D-11: ingest invokes whatever doctor's resolver returns; pin it to
    # the plain binary so FakeTools' cmd[0] dispatch stays deterministic
    # regardless of what this host has installed.
    monkeypatch.setattr("myzing.doctor.resolve_ytdlp_argv", lambda: ["yt-dlp"])


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


def test_d11_module_only_env_fetches_via_interpreter(zing_workspace, monkeypatch):
    """S5 gate defect D-11: doctor said "fully ready" from the importable
    module while _fetch ran the literal binary and died. Ingest must run
    exactly what the shared resolver returns — here, the module form."""
    import sys as _sys

    fake = FakeTools()

    def module_aware(cmd, timeout=None):
        if "yt_dlp" in cmd:
            return fake([("yt-dlp"), *cmd[3:]], timeout)  # reuse media writer
        return fake(cmd, timeout)

    monkeypatch.setattr("myzing.study.ingest.proc.run", module_aware)
    monkeypatch.setattr(
        "myzing.doctor.resolve_ytdlp_argv",
        lambda: [_sys.executable, "-m", "yt_dlp"],
    )

    result = ingest.ingest("https://www.tiktok.com/@cleo/video/7239871234")

    assert result.media_path.is_file()


def test_d11_no_ytdlp_at_all_is_actionable_before_running_anything(
    zing_workspace, monkeypatch
):
    calls = []
    monkeypatch.setattr("myzing.study.ingest.proc.run", lambda *a, **k: calls.append(a))
    monkeypatch.setattr("myzing.doctor.resolve_ytdlp_argv", lambda: None)
    with pytest.raises(MediaError, match="myzing\\[study\\]"):
        ingest.ingest("https://www.tiktok.com/@x/video/9")
    assert calls == []  # no subprocess ran just to fail with ENOENT


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


# -- F-06: locally-VFR H.264 (per-frame PTS delta scan) ----------------------

def test_locally_vfr_h264_is_normalized(zing_workspace, tmp_path, monkeypatch):
    """Bursty frame drops: avg-vs-declared is 0.23% (sails through the old
    2% gate) but per-frame PTS deltas betray real VFR — must normalize."""
    fake = FakeTools()
    fake.probe_stdouts = [probe_json(avg="2993/100", declared="30/1"), probe_json()]
    d = 1 / 30
    fake.pts_csv = pts_csv([d] * 100 + [2 * d] * 8 + [d] * 192)
    use(monkeypatch, fake)
    src = tmp_path / "bursty.mp4"
    src.write_bytes(b"fake")

    result = ingest.ingest(str(src))

    (ffmpeg_cmd,) = fake.commands("ffmpeg")
    assert "cfr" in ffmpeg_cmd and "libx264" in ffmpeg_cmd
    assert result.media_path.read_bytes() == b"fake-cfr-video"
    assert any("variable frame timing" in w for w in result.warnings)


def test_rare_drops_normalized_on_drift_budget(zing_workspace, tmp_path, monkeypatch):
    """Long clip with a few drops: delta variation stays under the CV
    threshold but cumulative frame-index drift breaks the ±0.15s budget."""
    fake = FakeTools()
    fake.probe_stdouts = [probe_json(), probe_json()]
    d = 1 / 30
    deltas = [d] * 3000
    for i in (400, 900, 1400, 1900, 2400, 2900):
        deltas[i] = 2 * d                     # 6 drops -> 0.2s total drift
    fake.pts_csv = pts_csv(deltas)
    use(monkeypatch, fake)
    src = tmp_path / "rare-drops.mp4"
    src.write_bytes(b"fake")

    result = ingest.ingest(str(src))

    assert len(fake.commands("ffmpeg")) == 1
    assert any("variable frame timing" in w for w in result.warnings)


def test_mild_jitter_skips_normalization_but_names_residual_risk(
    zing_workspace, tmp_path, monkeypatch
):
    """Drift measurable (0.1s) but under the ±0.15s budget: normalization is
    skipped, and that skip must be an explicit warning, not silence."""
    fake = FakeTools()
    d = 1 / 30
    deltas = [d] * 1800
    for i in (500, 1000, 1500):
        deltas[i] = 2 * d                     # 3 drops -> 0.1s drift
    fake.pts_csv = pts_csv(deltas)
    use(monkeypatch, fake)
    src = tmp_path / "mild.mp4"
    src.write_bytes(b"fake")

    result = ingest.ingest(str(src))

    assert fake.commands("ffmpeg") == []      # not normalized
    assert any("residual risk" in w for w in result.warnings)


def test_clean_cfr_pts_scan_stays_quiet(zing_workspace, tmp_path, monkeypatch):
    """Exactly constant deltas: no normalization, no scare warnings."""
    fake = FakeTools()
    fake.pts_csv = pts_csv([1 / 30] * 300)
    use(monkeypatch, fake)
    src = tmp_path / "clean.mp4"
    src.write_bytes(b"fake")

    result = ingest.ingest(str(src))

    assert fake.commands("ffmpeg") == []
    assert result.warnings == []


def test_timebase_rounding_jitter_stays_quiet(zing_workspace, tmp_path, monkeypatch):
    """29.97fps in a millisecond timebase alternates 33/34ms deltas — bounded
    rounding, not VFR; the gate must not cry wolf."""
    fake = FakeTools()
    fake.pts_csv = pts_csv([0.033, 0.034] * 150)
    use(monkeypatch, fake)
    src = tmp_path / "ntsc.mp4"
    src.write_bytes(b"fake")

    result = ingest.ingest(str(src))

    assert fake.commands("ffmpeg") == []
    assert result.warnings == []


def test_decode_order_packets_are_sorted_before_analysis(
    zing_workspace, tmp_path, monkeypatch
):
    """ffprobe emits packets in decode order (B-frames arrive out of
    presentation order); the scan must sort, not mistake reordering for VFR."""
    fake = FakeTools()
    d = 1 / 30
    times = [i * d for i in range(240)]
    for i in range(0, 238, 3):                # I P B pattern: swap each P/B pair
        times[i + 1], times[i + 2] = times[i + 2], times[i + 1]
    fake.pts_csv = "\n".join(f"{t:.6f}" for t in times) + "\n"
    use(monkeypatch, fake)
    src = tmp_path / "bframes.mp4"
    src.write_bytes(b"fake")

    result = ingest.ingest(str(src))

    assert fake.commands("ffmpeg") == []
    assert result.warnings == []


def test_unusable_pts_scan_warns_residual_risk(zing_workspace, tmp_path, monkeypatch):
    """When the packet scan cannot run, we must say the CFR assumption is
    unverified instead of silently trusting it."""
    inner = FakeTools()

    def failing_scan(cmd, timeout=None):
        if cmd[0] == "ffprobe" and any("packet=pts_time" in p for p in cmd):
            return subprocess.CompletedProcess(cmd, 1, "", "demux error\n")
        return inner(cmd, timeout)
    use(monkeypatch, failing_scan)
    src = tmp_path / "unscannable.mp4"
    src.write_bytes(b"fake")

    result = ingest.ingest(str(src))

    assert inner.commands("ffmpeg") == []     # nothing to justify a re-encode
    assert any("residual risk" in w for w in result.warnings)


def test_too_few_timestamps_is_unusable_not_verdict(
    zing_workspace, tmp_path, monkeypatch
):
    fake = FakeTools()
    fake.pts_csv = "0.000000\n0.033333\nN/A\n"
    use(monkeypatch, fake)
    src = tmp_path / "tiny.mp4"
    src.write_bytes(b"fake")

    result = ingest.ingest(str(src))

    assert fake.commands("ffmpeg") == []
    assert any("residual risk" in w for w in result.warnings)


def test_already_normalizing_skips_pts_scan(zing_workspace, tmp_path, monkeypatch):
    """The cheap codec gate already decided to normalize: no packet scan."""
    fake = FakeTools()
    fake.probe_stdouts = [probe_json(codec="vp9"), probe_json()]
    use(monkeypatch, fake)
    src = tmp_path / "clip.webm"
    src.write_bytes(b"fake")

    ingest.ingest(str(src))

    scans = [c for c in fake.commands("ffprobe")
             if any("packet=pts_time" in p for p in c)]
    assert scans == []


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


# -- A-S6: study-from-kept-media --------------------------------------------

def test_kept_media_studied_with_zero_fetch(zing_workspace, tmp_path, monkeypatch):
    """The S6 family scenario's zing hop: kept file present -> no yt-dlp,
    provenance cites the kept file with a sha256 anchor."""
    import hashlib

    fake = FakeTools()
    use(monkeypatch, fake)
    kept = tmp_path / "uoink-kept.mp4"
    kept.write_bytes(b"kept-by-uoink")
    url = "https://www.tiktok.com/@cleo/video/7239871234"

    result = ingest.ingest(url, kept_media=kept)

    assert fake.commands("yt-dlp") == []
    assert result.provenance["media_source"] == "kept-media"
    assert result.provenance["kept_media_path"] == str(kept.resolve())
    assert result.provenance["kept_media_sha256"] == hashlib.sha256(
        b"kept-by-uoink"
    ).hexdigest()
    assert result.meta.platform == "tiktok"      # slug/platform stay URL-derived
    assert result.slug == "tiktok-7239871234"
    assert result.media_path.is_file()
    assert not any("falling back" in w for w in result.warnings)


def test_kept_media_missing_falls_back_to_fetch(zing_workspace, tmp_path, monkeypatch):
    fake = FakeTools()
    use(monkeypatch, fake)
    url = "https://www.tiktok.com/@cleo/video/7239871234"

    result = ingest.ingest(url, kept_media=tmp_path / "gone.mp4")

    assert len(fake.commands("yt-dlp")) == 1
    assert any(
        "kept media unavailable" in w and "falling back to fetch" in w
        for w in result.warnings
    )
    assert "media_source" not in result.provenance


def test_kept_media_failing_probe_falls_back(zing_workspace, tmp_path, monkeypatch):
    """A corrupt kept file must not kill the study when the URL fetches."""
    fake = FakeTools()
    probe_calls = {"n": 0}
    real = fake.__call__

    def flaky(cmd, timeout=None):
        if cmd[0] == "ffprobe" and not any("packet=pts_time" in p for p in cmd):
            probe_calls["n"] += 1
            if probe_calls["n"] == 1:      # first probe = the kept file
                return subprocess.CompletedProcess(cmd, 1, "", "moov atom not found")
        return real(cmd, timeout)
    use(monkeypatch, flaky)
    kept = tmp_path / "corrupt.mp4"
    kept.write_bytes(b"not-really-video")
    url = "https://www.tiktok.com/@cleo/video/7239871234"

    result = ingest.ingest(url, kept_media=kept)

    assert len(fake.commands("yt-dlp")) == 1
    assert any("kept media failed probe" in w for w in result.warnings)
    assert "media_source" not in result.provenance


def test_kept_media_with_local_source_is_ignored_with_warning(
    zing_workspace, tmp_path, monkeypatch
):
    fake = FakeTools()
    use(monkeypatch, fake)
    local = tmp_path / "take.mp4"
    local.write_bytes(b"local-take")
    kept = tmp_path / "kept.mp4"
    kept.write_bytes(b"kept")

    result = ingest.ingest(str(local), kept_media=kept)

    assert any("kept_media ignored" in w for w in result.warnings)
    assert "media_source" not in result.provenance
