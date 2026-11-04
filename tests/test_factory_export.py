"""Factory layers, scene captions and the editor timeline, without a judge or model downloads."""
from __future__ import annotations

import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from myzing.factory import command, export, judge, render, source

REAL_RUN = subprocess.run


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(source, "transcribe_moments", lambda media, pieces: [])


def clip(tmp_path, **plan):
    d = tmp_path / "clip01"
    d.mkdir()
    words = [{"w": w, "os": i * .4, "oe": i * .4 + .3}
             for i, w in enumerate("Hello there, a small test. Keep going now".split())]
    for file, data in (("plan", {"hook": "A *test* & <clip>", "hook_until": 0,
                               "shots": [{"from": 0, "layout": "solo"}], **plan}),
                       ("words", {"words": words}),
                       ("cams", {"size": [640, 360], "frames": 120,
                                 "cams": [{"from": 0, "to": 4, "mode": "wide"}]})):
        (d / f"{file}.json").write_text(json.dumps(data), encoding="utf-8")
    (d / "cut.mp4").write_bytes(b"cut")
    return d


def scene(d, pack="zing", shape="9x16"):
    return render.scene_data(d, shape, pack, parallax=False, front=False, sharpen=False)


def cues(data):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is needed to read the scene's caption cues")
    js = r"""
const fs = require('fs'), vm = require('vm');
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
const page = fs.readFileSync(process.argv[1], 'utf8');
const document = {documentElement: {style: {setProperty() {}}, dataset: {}}, body: {style: {}},
                  fonts: {load() {return Promise.resolve();}}};
const context = {window: {DATA: data}, document};
vm.runInNewContext(page.match(/<script>([\s\S]*?)<\/script>/)[1], context);
console.log(JSON.stringify(context.window.captionCues()));
"""
    got = REAL_RUN([node, "-e", js, str(render.data_path("scene.html"))], input=json.dumps(data),
                   capture_output=True, text=True, check=True)
    return json.loads(got.stdout)


def test_scene_captions_keep_grouping_punctuation_case_and_timing(tmp_path):
    data = scene(clip(tmp_path))
    got = cues(data)
    assert [c["text"] for c in got] == ["HELLO THERE", "A SMALL TEST.", "KEEP GOING NOW"]
    assert [(c["from"], c["to"]) for c in got] == [(0, .8), (.8, 2), (2, 3.4)]
    export.srt(tmp_path / "captions.srt", got)
    assert (tmp_path / "captions.srt").read_text() == (
        "1\n00:00:00,000 --> 00:00:00,800\nHELLO THERE\n\n"
        "2\n00:00:00,800 --> 00:00:02,000\nA SMALL TEST.\n\n"
        "3\n00:00:02,000 --> 00:00:03,400\nKEEP GOING NOW\n\n")
    data["theme"] = {"cap_words": 1, "cap_chars": 100, "cap_upper": False}
    assert [c["text"] for c in cues(data)] == [w["w"].rstrip(",") for w in data["words"]]


def test_scene_captions_follow_hook_quotes_and_endcards(tmp_path):
    data = scene(clip(tmp_path, hook_until=1, shots=[
        {"from": 0, "layout": "graphic", "graphic": {"kind": "counter", "value": 2}},
        {"from": 1.5, "layout": "graphic", "graphic": {"kind": "quote", "text": "Keep *going now*"}},
        {"from": 3, "layout": "graphic", "graphic": {"kind": "endcard", "name": "Done"}}]))
    got = cues(data)
    assert got[0]["from"] == 1 and got[0]["text"] == "A SMALL TEST."
    assert got[1]["text"] == "KEEP GOING NOW" and got[1]["from"] == pytest.approx(1.9)
    assert got[-1]["to"] == 3.9 and data["duration"] == 6
    data["quotes"] = []
    assert cues(data)[-1]["to"] == 3


@pytest.mark.parametrize("shape", render.SHAPES)
def test_timeline_has_two_video_tracks_and_one_audio_track(tmp_path, shape):
    out = tmp_path / "a folder # with & symbols"
    out.mkdir()
    width, height = render.SHAPES[shape]
    export.timeline(out, "A test & <clip>", width, height, 107)
    root = ET.parse(out / "timeline.xml").getroot()
    assert root.tag == "xmeml" and root.attrib == {"version": "5"}
    seq = root.find("sequence")
    assert seq.findtext("name") == "A test & <clip>" and seq.findtext("duration") == "107"
    assert seq.findtext("rate/timebase") == "30" and seq.findtext("rate/ntsc") == "FALSE"
    assert seq.findtext("media/video/format/samplecharacteristics/width") == str(width)
    assert seq.findtext("media/video/format/samplecharacteristics/height") == str(height)
    video = seq.findall("media/video/track/clipitem")
    audio = seq.findall("media/audio/track/clipitem")
    assert [c.findtext("name") for c in video + audio] == ["speaker.mp4", "overlay.mov", "audio.wav"]
    assert video[1].findtext("alphatype") == "straight"
    assert audio[0].findtext("file/media/audio/samplecharacteristics/samplerate") == "48000"
    for c in video + audio:
        assert [c.findtext(k) for k in ("start", "in", "end", "out", "duration", "file/duration")] == ["0", "0", "107", "107", "107", "107"]
        assert c.findtext("file/pathurl") == (out / c.findtext("name")).as_uri()
        assert "%20" in c.findtext("file/pathurl") and "%23" in c.findtext("file/pathurl")


def test_capture_sets_only_the_requested_layer(tmp_path, monkeypatch):
    data = scene(clip(tmp_path))
    calls = []
    monkeypatch.setattr(render, "node_sidecar", lambda: ("node", tmp_path))
    monkeypatch.setattr(render, "sidecar_env", lambda tmp: {})
    monkeypatch.setattr(render, "run", lambda *args, **kw: calls.append(json.loads(Path(args[3]).read_text())))
    for layer in ("speaker", "overlay", None):
        render.capture(data, tmp_path / "data.json", tmp_path / "frames", layer=layer,
                       samples=[0, 30, 60] if layer is None else None)
    assert [c.get("overlay", False) for c in calls] == [False, True, False]
    assert [c.get("speakerLayer", False) for c in calls] == [True, False, False]
    assert "overlay" not in data and "speakerLayer" not in data
    assert all(c["shots"] == data["shots"] and c["duration"] == data["duration"] for c in calls)
    assert calls[-1]["captureFrames"] == [0, 30, 60]


def test_backdrop_correction_keeps_front_holes_and_grain(tmp_path):
    import numpy as np
    from PIL import Image
    for folder in ("normal", "speaker", "matte"):
        (tmp_path / folder).mkdir()
    speaker = np.array([[[80, 100, 120], [50, 50, 50], [130, 150, 170], [50, 70, 90]]], dtype=np.uint8)
    normal = np.array([[[80, 100, 120], [40, 60, 80], [140, 157, 176], [120, 50, 100]]], dtype=np.uint8)
    Image.fromarray(speaker).save(tmp_path / "speaker/00001.png")
    Image.fromarray(normal).save(tmp_path / "normal/00001.png")
    Image.new("RGBA", (4, 1), (10, 20, 30, 255)).save(tmp_path / "00001.png")
    matte = np.zeros((1, 4, 4), dtype=np.uint8)
    matte[:, :, 3] = [255, 0, 255, 128]
    Image.fromarray(matte).save(tmp_path / "matte/00001.png")
    render.flatten_backdrop(tmp_path)
    overlay = np.asarray(Image.open(tmp_path / "00001.png"), dtype=np.float32)
    alpha = overlay[:, :, 3:] / 255
    composite = overlay[:, :, :3] * alpha + speaker * (1 - alpha)
    assert np.abs(composite - normal).max() <= 1
    assert overlay[0, 0, 3] == 0 and overlay[0, 1, 3] == 255
    assert 0 < overlay[0, 2, 3] < 255


def test_export_writes_files_codecs_cues_and_comparison(tmp_path, monkeypatch, capsys):
    d = clip(tmp_path)
    data = scene(d)
    got = cues(data)
    monkeypatch.setattr(render, "scene_data", lambda *args: data)
    passes, runs = [], []
    def capture(data, file, images, **kw):
        passes.append(kw)
        images.mkdir()
        if "samples" in kw:
            (images / "captions.json").write_text(json.dumps(got))
    def run(*args, **kw):
        runs.append(args)
        Path(args[-1]).write_bytes(b"media")
    monkeypatch.setattr(render, "capture", capture)
    monkeypatch.setattr(export, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(export, "run", run)
    checks = [{"time": 1, "mae": .5, "psnr_db": 40}]
    monkeypatch.setattr(export, "compare", lambda *args: checks)
    assert command.run(["export", str(d)]) == 0
    result = json.loads(capsys.readouterr().out)
    out = d / "export-9x16"
    assert result["exported"] == str(out) and result["comparison"] == checks
    assert set(result["bytes"]) == {p.name for p in out.iterdir()}
    assert len((out / "README.txt").read_text().splitlines()) == 3
    assert (out / "captions.srt").read_text().startswith("1\n00:00:00,000 --> 00:00:00,800\nHELLO THERE\n")
    assert (out / "words.srt").read_text().count(" --> ") == len(data["words"])
    assert passes == [{"layer": "speaker"}, {"layer": "overlay"}, {"samples": [10, 53, 96]}]
    assert "libx264" in runs[0] and "-an" in runs[0]
    assert "prores_ks" in runs[1] and "4444" in runs[1] and "yuva444p10le" in runs[1] and "-an" in runs[1]
    assert "pcm_s24le" in runs[2] and 48000 in runs[2]
    assert result["frames"] == 107
    assert ET.parse(out / "timeline.xml").findtext("sequence/name") == "A test & <clip>"


def test_cli_forwards_shape_pack_and_out(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(export, "export", lambda *args, **kw: calls.append((args, kw)) or {"exported": "ok"})
    assert command.run(["export", str(tmp_path), "--shape", "4x5", "--pack", "swiss", "--out", str(tmp_path / "edit")]) == 0
    assert calls == [((tmp_path, "4x5", "swiss"), {"out": tmp_path / "edit"})]
    assert json.loads(capsys.readouterr().out) == {"exported": "ok"}
