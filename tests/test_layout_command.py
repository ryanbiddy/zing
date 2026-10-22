import json
from pathlib import Path
import subprocess

import pytest

from myzing.cli import main
from myzing.layout import Box, CaptionEvent, Detection, LayoutPlan
from myzing.layout import command
from myzing.layout.media import probe_duration, sample_frames


def test_help_and_invalid_arguments(capsys):
    assert main(["layout", "--help"]) == 0
    assert "fetch-model" in capsys.readouterr().out
    assert main(["layout", "captions", "--unknown"]) == 2
    assert "zing layout:" in capsys.readouterr().err


def test_explicit_fetch_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(command, "fetch_model", lambda workspace: tmp_path / "model.onnx")
    assert main(["layout", "fetch-model", "--workspace", str(tmp_path)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["verified"] and data["license"] == "MIT"


def test_cli_validates_before_detector_or_download(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(command, "YuNetDetector", lambda *a, **k: pytest.fail("loaded too early"))
    events = tmp_path / "events.json"
    events.write_text('{"version": 7, "events": []}')
    assert main(["layout", "captions", "--video", "missing.mp4", "--events", str(events),
                 "--out", str(tmp_path / "out.json"), "--fetch-model"]) == 2
    assert "unsupported caption events version" in capsys.readouterr().err


def test_output_cannot_clobber_input(tmp_path, capsys):
    events = tmp_path / "events.json"
    events.write_text("[]")
    assert main(["layout", "captions", "--video", "missing.mp4", "--events", str(events),
                 "--out", str(events)]) == 2
    assert events.read_text() == "[]"
    assert "differ" in capsys.readouterr().err


@pytest.mark.parametrize("rate,duration", [(0, 2), (float("nan"), 1), (9, 1), (2, 301)])
def test_sampling_bounds_before_ffmpeg(tmp_path, monkeypatch, rate, duration):
    from myzing.layout import media
    monkeypatch.setattr(media.proc, "run", lambda *a, **k: pytest.fail("ran ffmpeg"))
    with pytest.raises((ValueError, RuntimeError)):
        sample_frames(tmp_path / "missing.mp4", tmp_path / "frames", duration=duration, sample_rate=rate)


def _generate(path: Path, filters="testsrc2=size=180x320:rate=30:duration=2", extra=()):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", filters,
                    *extra, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
                   capture_output=True, check=True, timeout=30)


@pytest.mark.ffmpeg
def test_real_ffmpeg_sampling_uses_actual_pts_and_bounded_dimensions(tmp_path):
    video = tmp_path / "portrait with ' spaces.mp4"
    _generate(video, "testsrc2=size=720x1280:rate=30:duration=2")
    duration = probe_duration(video)
    samples = sample_frames(video, tmp_path / "frames", duration=duration, sample_rate=2)
    assert [time for time, _ in samples] == pytest.approx([0, .5, 1, 1.5])
    # Read PNG IHDR via stdlib so this media gate doesn't need OpenCV.
    import struct
    width, height = struct.unpack(">II", samples[0][1].read_bytes()[16:24])
    assert (width, height) == (360, 640)


@pytest.mark.ffmpeg
def test_real_ffmpeg_vfr_sampling_keeps_pts_and_normalizes_pixel_aspect(tmp_path):
    video = tmp_path / "vfr.mkv"
    _generate(video, "testsrc2=size=160x240:rate=30:duration=2",
              ("-vf", "select='not(mod(n,7))',setsar=2", "-fps_mode", "vfr"))
    samples = sample_frames(video, tmp_path / "frames", duration=probe_duration(video), sample_rate=2)
    times = [t for t, _ in samples]
    assert times == pytest.approx([0, .7, 1.4], abs=.002)
    assert all(b - a >= .5 for a, b in zip(times, times[1:]))
    import struct
    width, height = struct.unpack(">II", samples[0][1].read_bytes()[16:24])
    assert width / height == pytest.approx(4 / 3, abs=.01)


@pytest.mark.ffmpeg
def test_real_cli_writes_plan_and_contact_sheet_without_model(tmp_path, monkeypatch, capsys):
    pytest.importorskip("cv2")
    from myzing.layout.detector import load_cv2

    class FakeDetector:
        cv2 = load_cv2()

        def __init__(self, workspace, *, download, score_threshold):
            assert not download

        def detect(self, image):
            return [Detection(Box(.2, .4, .6, .4), .95)]

    monkeypatch.setattr(command, "YuNetDetector", FakeDetector)
    video, events, output = (tmp_path / n for n in ("input.mp4", "events.json", "plan.json"))
    _generate(video)
    events.write_text(json.dumps({"version": 1, "events": [
        CaptionEvent("one", 0, 1, .5, .1).to_dict(), CaptionEvent("two", 1, 2, .5, .1).to_dict()]}))
    assert main(["layout", "captions", "--video", str(video), "--events", str(events),
                 "--platform", "tiktok", "--out", str(output), "--workspace", str(tmp_path / "home")]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["unsafe_events"] == []
    assert Path(summary["contact_sheet"]).read_bytes().startswith(b"\x89PNG")
    plan = LayoutPlan.from_dict(json.loads(output.read_text()))
    assert plan.events[0].box == plan.events[1].box
    assert plan.provenance["tracks_are_padded"]
    assert plan.provenance["sample_times"] == [0, .5, 1, 1.5]
    assert len(plan.provenance["video_sha256"]) == 64
    assert not list((tmp_path / "home" / "layout").iterdir())
