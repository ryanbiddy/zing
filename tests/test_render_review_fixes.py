import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from myzing.composition import AssetRef, CompositionAudio
from myzing.composition.encoding import DeliveryEncoding
from myzing.music import measurement
from myzing.music.models import MusicPlan, attach
from myzing.render import composition, deliveries, encoding, otio_export, pipeline
from myzing.render.validation import MediaInfo
from myzing.schemas import AudioTrack, Clip, EDL
from test_render_otio import fake_otio
from test_render_review_round5 import fake_render, plan


@pytest.mark.parametrize("mode", ["edl", "composition", "two_pass"])
@pytest.mark.parametrize("same_output", [False, True])
@pytest.mark.parametrize("fails", [False, True])
def test_render_stages_before_replacing_output(fake_render, tmp_path, monkeypatch, mode, same_output, fails):
    work = tmp_path / "work"
    work.mkdir()
    output = work / "rendered.mp4" if same_output else tmp_path / "out.mp4"
    output.write_bytes(b"previous video")
    targets = []

    def run(command, **kwargs):
        target = Path(command[-1])
        targets.append(target)
        target.write_bytes(b"rendered")
        first_pass = "-pass" in command and command[command.index("-pass") + 1] == "1"
        return subprocess.CompletedProcess(command, int(fails and not first_pass), "", "render failed" if fails else "")

    monkeypatch.setattr(pipeline.subprocess, "run", run)
    monkeypatch.setattr(encoding, "_audio_bytes", lambda *a: 0)

    def render():
        if mode == "edl":
            return pipeline.render_edl(EDL(clips=[Clip(str(fake_render), 0, 1, 0)]), output, work_dir=work)
        p = plan(fake_render)
        if mode == "two_pass":
            p.delivery = DeliveryEncoding(video_bitrate_kbps=1000)
        return composition.render_composition(p, output, work_dir=work)

    if fails:
        with pytest.raises(pipeline.RenderError, match="render failed"):
            render()
        assert output.read_bytes() == b"previous video"
    else:
        result = render()
        assert result.output_path == output
        assert output.read_bytes() == b"rendered"
        if mode == "two_pass":
            assert json.loads(output.with_suffix(".encoding.json").read_text()) == result.delivery_measurements
    assert targets[-1].parent == work
    assert targets[-1] != output
    if not same_output:
        assert targets[-1] == work / "rendered.mp4"


@pytest.mark.parametrize("version", [1, 2])
def test_alternate_staging_path_cannot_overwrite_input(fake_render, tmp_path, version):
    work = tmp_path / "work"
    work.mkdir()
    os.link(fake_render, work / "rendered-staging.mp4")
    output = work / "rendered.mp4"
    output.write_bytes(b"previous video")
    with pytest.raises(pipeline.RenderError, match="work.*input"):
        if version == 1:
            pipeline.render_edl(EDL(clips=[Clip(str(fake_render), 0, 1, 0)]), output, work_dir=work)
        else:
            composition.render_composition(plan(fake_render), output, work_dir=work)
    assert fake_render.read_bytes() == b"source"
    assert output.read_bytes() == b"previous video"


@pytest.mark.parametrize("failure", ["encoding", "music", None])
def test_receipts_publish_before_delivery_video(fake_render, tmp_path, monkeypatch, failure):
    music = tmp_path / "music.wav"
    music.write_bytes(b"music")
    p = plan(fake_render)
    p.delivery = DeliveryEncoding(video_bitrate_kbps=1000)
    p.assets.append(AssetRef("m", str(music), None))
    p.audio = [CompositionAudio(str(music), "music", id="music", asset_id="m", role="music")]
    attach(p, MusicPlan(tracks=[{"id": "music"}]))
    output = tmp_path / "out.16x9.mp4"
    output.write_bytes(b"previous video")
    monkeypatch.setattr(pipeline, "probe_media", lambda path, *a, **k: MediaInfo(10, path == fake_render, path == music))
    monkeypatch.setattr(deliveries, "delivery_plans", lambda *a, **k: (
        {"16:9": p}, {"resolution": {"16:9": {}}}))
    monkeypatch.setattr(encoding, "_audio_bytes", lambda *a: 0)
    monkeypatch.setattr("myzing.audio.media.numpy", lambda: None)
    monkeypatch.setattr(measurement, "measure_mix", lambda *a, **k: {"warnings": []})

    def run(command, **kwargs):
        Path(command[command.index("-f") + 2]).write_bytes(b"rendered")
        return subprocess.CompletedProcess(command, 0, "", "")

    replace = os.replace

    def publish(source, destination):
        if failure and Path(destination) == output.with_suffix(f".{failure}.json"):
            raise PermissionError("receipt is locked")
        replace(source, destination)

    monkeypatch.setattr(pipeline.subprocess, "run", run)
    monkeypatch.setattr(pipeline.os, "replace", publish)
    result = deliveries.render_deliveries(p, tmp_path / "out.mp4", aspects=["16:9"],
                                          work_dir=tmp_path / "work", continue_on_error=True)
    row = result["deliveries"]["16:9"]
    if failure:
        assert result["status"] == row["status"] == "failed"
        assert "receipt is locked" in row["error"]
        assert "failed_artifact" not in row
        assert "video" not in row
        assert output.read_bytes() == b"previous video"
    else:
        assert result["status"] == row["status"] == "ready"
        assert output.read_bytes() == b"rendered"
        assert json.loads(output.with_suffix(".encoding.json").read_text()) == row["encoding"]
        assert Path(row["music"]) == output.with_suffix(".music.json")
        assert json.loads(Path(row["music"]).read_text()) == {
            "warnings": [], "render_sha256": hashlib.sha256(b"rendered").hexdigest(),
            "music_plan": MusicPlan(tracks=[{"id": "music"}]).to_dict(),
        }
    assert not list(tmp_path.glob("*.failed"))


@pytest.mark.parametrize("start", [2, 5])
@pytest.mark.parametrize("kind", ["voiceover", "music"])
def test_late_audio_does_not_extend_otio_timeline(tmp_path, monkeypatch, start, kind):
    source, audio = tmp_path / "source.mp4", tmp_path / "audio.wav"
    source.write_bytes(b"source")
    audio.write_bytes(b"audio")
    edl = EDL(clips=[Clip(str(source), 0, 2, 0)], audio=[AudioTrack(str(audio), kind, timeline_start=start)])
    record = {}
    monkeypatch.setattr(otio_export, "_load_otio", lambda: fake_otio(record))
    result = otio_export.export_otio(edl, tmp_path / "out.otio",
        probe=lambda path: MediaInfo(10, path == source, path == audio))
    tracks = record["timeline"].tracks
    durations = [sum(child.source_range.duration.value / child.source_range.duration.rate
                     for child in track.children) for track in tracks]
    assert max(durations) == result.duration == 2
    assert len(tracks[-1].children) == 1
    assert not hasattr(tracks[-1].children[0], "media_reference")
    assert durations[-1] == 2
