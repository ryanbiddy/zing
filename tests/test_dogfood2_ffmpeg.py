"""Generated-media DOGFOOD2 gate. No downloads or third-party footage."""

import json
import subprocess
from pathlib import Path

import pytest

from myzing.project.probe import probe_file
from myzing.reference_range import select_local

pytestmark = pytest.mark.ffmpeg


def ff(*args):
    result = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", *map(str, args)],
                            capture_output=True, timeout=180)
    assert not result.returncode, result.stderr.decode(errors="replace")
    return result.stdout


def test_reference_trim_exact_non_keyframe_and_provenance(tmp_path):
    source = tmp_path / "long.mp4"
    ff("-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=82", "-c:v", "libx264", "-threads", "1",
       "-g", "300", "-preset", "ultrafast", source)
    from myzing.project.api import hash_file
    before = hash_file(source)
    selected, receipt = select_local(source, tmp_path / "selection", "0:30.1", "1:20.1", limit=60)
    video = next(s for s in probe_file(selected).streams if s["codec_type"] == "video")
    assert int(video["nb_frames"]) == 1500
    assert receipt["start_frame"] == 903 and receipt["end_frame"] == 2403
    assert receipt["source_sha256"] == before == hash_file(source)
    np = pytest.importorskip("numpy")
    def pixels(path, seek):
        return np.frombuffer(ff("-ss", seek, "-i", path, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"), dtype=np.uint8).astype(float)
    assert np.abs(pixels(source, 30.1)-pixels(selected, 0)).mean() < 5
    selected_hash = hash_file(selected)
    repeated, repeat_receipt = select_local(source, tmp_path / "selection", "0:30.1", "1:20.1", limit=60)
    assert hash_file(repeated) == selected_hash
    assert repeat_receipt == receipt and hash_file(source) == before


def test_trim_uses_video_and_container_origins_before_accurate_seek(tmp_path):
    np = pytest.importorskip("numpy")
    source = tmp_path / "offset.mp4"
    ff("-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=4", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
       "-filter_complex", "[0:v]setpts=PTS+1.5/TB[v]", "-map", "[v]", "-map", "1:a", "-t", "6",
       "-fps_mode", "passthrough", "-c:v", "libx264", "-threads", "1", "-c:a", "aac",
       "-output_ts_offset", "2", source)
    probe = probe_file(source)
    video = next(s for s in probe.streams if s["codec_type"] == "video")
    assert float(video["start_time"]) - float(probe.format["start_time"]) == pytest.approx(1.5, abs=.025)
    assert float(probe.format["start_time"]) > 1
    selected, receipt = select_local(source, tmp_path / "selected", .5, 2.5)
    assert receipt["start_frame"] == 15 and receipt["end_frame"] == 75
    assert int(probe_file(selected).streams[0]["nb_frames"]) == 60
    expected = np.frombuffer(ff("-i", source, "-vf", "select=eq(n\\,15)", "-frames:v", "1",
                                "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"), dtype=np.uint8).astype(float)
    actual = np.frombuffer(ff("-i", selected, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"), dtype=np.uint8).astype(float)
    assert np.abs(expected-actual).mean() < 5


def test_padded_audio_does_not_add_377th_picture_frame(tmp_path):
    from myzing.studio.adapters import load_edit
    from myzing.render.composition import render_composition
    source, output = tmp_path / "padded.mp4", tmp_path / "rendered.mp4"
    ff("-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=12.5333333333", "-f", "lavfi", "-i",
       "anullsrc=r=48000:cl=mono", "-t", "12.566341", "-c:v", "libx264", "-threads", "1",
       "-fps_mode", "passthrough", "-c:a", "aac", source)
    probe = probe_file(source)
    assert int(probe.streams[0]["nb_frames"]) == 376
    assert float(probe.format["duration"]) > probe.duration
    plan = load_edit(source)
    assert plan.clips[0].duration == 376 / 30
    render_composition(plan, output)
    assert int(probe_file(output).streams[0]["nb_frames"]) == 376


def test_vfr_trim_uses_decoded_timestamps_not_average_frame_grid(tmp_path):
    source = tmp_path / "vfr.mp4"
    ff("-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=4", "-vf",
       "select='if(lt(t,2),not(mod(n,3)),1)'", "-fps_mode", "vfr", "-c:v", "libx264",
       "-threads", "1", "-preset", "ultrafast", source)
    assert "vfr_suspected" in probe_file(source).flags
    selected, receipt = select_local(source, tmp_path / "selection", .15, 2.2)
    assert receipt["start"] == pytest.approx(.2)
    assert receipt["start_frame"] is None
    assert receipt["source_frames"]["selected_source_frames"] == 24
    assert receipt["source_frames"]["last_frame_time"] == pytest.approx(2.166667)
    np = pytest.importorskip("numpy")
    expected = np.frombuffer(ff("-ss", .2, "-i", source, "-frames:v", 1, "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"), dtype=np.uint8).astype(float)
    actual = np.frombuffer(ff("-i", selected, "-frames:v", 1, "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"), dtype=np.uint8).astype(float)
    assert np.abs(expected-actual).mean() < 5


def test_explain_media_budget_bounds_duration_and_resolution(tmp_path):
    source = tmp_path / "long-hd.mp4"
    ff("-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=2:d=90", "-c:v", "libx264", "-threads", "1",
       "-preset", "ultrafast", source)
    selected, receipt = select_local(source, tmp_path / "bounded", analysis_seconds=60, max_side=960)
    probe = probe_file(selected)
    assert probe.duration == 60 and max(probe.width, probe.height) == 960
    assert receipt["analysis_limited"] and receipt["requested_end"] == 90


def test_dark_broadcast_picture_survives_encoding(tmp_path):
    np = pytest.importorskip("numpy")
    from test_dogfood2 import dark_chrome
    from myzing.layout.picture import analyze_picture
    source = tmp_path / "dark-chrome.mp4"
    frames = dark_chrome()
    process = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray",
                               "-s", "160x100", "-r", "2", "-i", "pipe:0", "-c:v", "libx264",
                               "-threads", "1", "-crf", "10", "-pix_fmt", "yuv420p", str(source)],
                              stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    for frame in frames:
        process.stdin.write(np.ascontiguousarray(frame).tobytes())
    process.stdin.close()
    error = process.stderr.read()
    assert process.wait(timeout=60) == 0, error
    result = analyze_picture(source, [(0, 6)], (160, 100))
    assert result["confident"], result
    assert result["confidence"] >= .8
    assert result["bounds_pixels"] == [18, 14, 124, 64]


def test_cli_brief_single_moment_renders_box_in_all_shapes(tmp_path, monkeypatch, zing_workspace):
    from myzing import storage
    from myzing.schemas import Word
    from myzing.study.transcribe import TranscribeResult
    from myzing.studio import command, execute
    from myzing.composition import Composition
    clips = tmp_path / "clips"
    clips.mkdir()
    source = clips / "moment.mp4"
    ff("-f", "lavfi", "-i", "color=c=navy:s=320x180:r=30:d=12", "-c:v", "libx264", "-threads", "1", source)
    # Generated video has a known synthetic transcript; no ASR model fixture.
    words = [Word(text, i*.7+.2, i*.7+.65) for i, text in enumerate("One short moment can now make a useful captioned draft.".split())]
    words += [Word("and", 11.62, 11.94), Word("big.", 11.94, 11.98)]
    monkeypatch.setattr("myzing.study.transcribe.transcribe", lambda *a, **k: TranscribeResult(words=words))
    monkeypatch.setattr("myzing.study.speech_models.prepare", lambda *a, **k: None)
    monkeypatch.setattr("myzing.studio.jobs.execute", lambda a, **k: execute.run_confirmed(a))
    # The CLI is tested in-process so the synthetic transcript seam is inherited.
    root = tmp_path / "studio"
    answers = {"path": "b", "project": str(root), "clips": str(clips), "topic": "one moment",
               "platform": "all", "aspects": ["16:9", "1:1", "9:16"], "length": 12, "tone": "natural",
               "captions": "box", "music": "original", "draft": "keep all"}
    path = tmp_path / "answers.json"
    path.write_text(json.dumps(answers), encoding="utf-8")
    monkeypatch.setattr("myzing.study.speech_models.choices", lambda: {"tiny": "fixture"})
    assert command.run(["--answers", str(path), "--yes", "--caption-mode", "box", "--short-side", "180", "--target-mb", "2"]) == 0
    result = json.loads((root / "studio-result.json").read_text(encoding="utf-8"))
    assert result["ok"], result
    assert result["creator_summary"]["notes"][0].startswith("VARIETY limit: delivered 1")
    assert "Add clips or shorten" not in str(result["creator_summary"])
    deliveries = result["result"]["deliveries"]
    assert list(deliveries) == ["A"]
    rows = deliveries["A"]["deliveries"]
    assert set(rows) == {"16:9", "1:1", "9:16"}
    for row in rows.values():
        plan = Composition.from_json(Path(row["plan"]).read_text(encoding="utf-8"))
        assert plan.captions and all(c.preset == "box" and c.style.highlight_box_color for c in plan.captions)
        assert Path(row["video"]).stat().st_size < 2_000_000
        assert int(probe_file(Path(row["video"])).streams[0]["nb_frames"]) == 360
