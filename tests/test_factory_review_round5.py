"""Factory recovery regressions, without downloads or model calls."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing.factory import approval, batch, cut, judge, pipeline, plan, render, review, source, visuals
from myzing.factory.tools import FactoryError, data_path

RUN = subprocess.run


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(visuals.urllib.request, "build_opener", refuse)
    monkeypatch.setattr(source, "transcribe_episode", refuse)
    monkeypatch.setattr(source, "transcribe_moments", refuse)
    monkeypatch.setattr(visuals, "get_key", lambda name: None)


@pytest.fixture
def clip(tmp_path):
    root = tmp_path / "project"
    pipeline._write(root / "factory.json", {**pipeline.SETTINGS, "moments": 0, "shapes": []})
    pipeline._write(root / "source.json", {"media": str(root / "episode.mp4"), "name": "Show"})
    pipeline._write(root / "transcript.json", [])
    pipeline._write(root / "moments.json", {"scouted": True, "moments": [
        {"start": 0, "end": 10, "hook": "Ann's channel", "snapped": True}]})
    d = root / "clip01"
    pipeline._write(d / "cams.json", {})
    pipeline._write(d / "words.json", {"duration": 10, "words": [
        {"w": w, "os": i, "oe": i + .5} for i, w in enumerate("Ann cannot miss the channel anniversary.".split())]})
    pipeline._write(d / "post.json", {"x": "Ann cannot miss the channel anniversary."})
    judge.Judge(root).save("clip01-plan", {"hook": "Ann's channel", "shots": [{"from": 0, "layout": "solo"}]})
    return d


@pytest.mark.parametrize("error", [subprocess.CalledProcessError(1, "ffmpeg"), AttributeError("unreadable frame")])
def test_clip_failure_does_not_stop_later_clips(clip, monkeypatch, error):
    root, calls = clip.parent, []
    moment = pipeline.load_moments(root)["moments"][0]
    pipeline._write(root / "moments.json", {"scouted": True, "moments": [moment] * 4})

    def run(project, i, *args, **kwargs):
        calls.append(i)
        if i == 3:
            raise error
    monkeypatch.setattr(pipeline, "_clip", run)
    result = pipeline.run(root, judge.Judge(root), say=lambda m: None)
    assert calls == [1, 2, 3, 4]
    assert result["state"] == "done" and result["failed"] == {"clip03": str(error)}


def test_stop_inside_a_clip_stays_a_stop(clip, monkeypatch):
    def stop(*args, **kwargs):
        raise pipeline._Stopped
    monkeypatch.setattr(pipeline, "_clip", stop)
    result = pipeline.run(clip.parent, judge.Judge(clip.parent), say=lambda m: None)
    assert result["state"] == "stopped" and result["failed"] == {}


def scouting(root):
    cfg = pipeline._read(root / "factory.json")
    pipeline._write(root / "factory.json", {**cfg, "moments": 1})
    pipeline._write(root / "moments.json", {})
    pipeline._write(root / "transcript.json", [{"s": 0, "e": 600, "text": "The episode ends here."}])


def test_scout_answer_must_fit_the_episode(clip):
    root = clip.parent
    scouting(root)
    with pytest.raises(FactoryError, match="outside the episode"):
        pipeline.answer(root, "scout", {"moments": [{"start": 900, "end": 920, "hook": "Too late"}]})
    assert not (root / "answers" / "scout.json").exists()


@pytest.mark.parametrize("task,value", [
    ("scout", '{"moments":'),
    ("scout", '{"moments": [{"start": 900, "end": 920, "hook": "Too late"}]}'),
    ("scout", '{"moments": []}'),
    ("clip01-plan", '{"hook":'),
    ("clip01-plan", '{"hook": "Missing shots"}'),
])
def test_bad_saved_answer_is_removed_and_requested_again(clip, task, value):
    root = clip.parent
    if task == "scout":
        scouting(root)
    path = root / "answers" / f"{task}.json"
    path.write_text(value, encoding="utf-8")
    for _ in range(2):
        result = pipeline.run(root, judge.Judge(root), say=lambda m: None)
        assert result["state"] == "waiting" and result["failed"] == {}
        assert task in [p["task"] for p in result["pending"]]
        assert not path.exists()


@pytest.mark.parametrize("task,value", [("scout", {"moments": [{"start": 900, "end": 920, "hook": "Too late"}]}),
                                       ("clip01-plan", {"hook": "Missing shots"})])
def test_claude_answer_is_checked_before_it_is_saved(clip, monkeypatch, task, value):
    root = clip.parent
    if task == "scout":
        scouting(root)
    ask = judge.Judge(root, "claude")
    ask.forget(task)
    saved = []
    save = ask.save

    def record(task, value):
        saved.append(task)
        return save(task, value)
    monkeypatch.setattr(ask, "save", record)
    monkeypatch.setattr(ask, "_claude", lambda *a: json.dumps(value))
    result = pipeline.run(root, ask, say=lambda m: None)
    assert result["state"] == "waiting" and result["failed"] == {}
    assert task not in saved and not (root / "answers" / f"{task}.json").exists()
    assert task in [p["task"] for p in result["pending"]]


@pytest.mark.parametrize("duration", [0, 100])
@pytest.mark.parametrize("size", [63, 64, 65])
def test_video_excerpt_caps_ffmpeg_and_rejects_oversize_output(tmp_path, monkeypatch, duration, size):
    from myzing.factory import network
    url = "https://example.org/video.mp4"
    net = network.Network(tmp_path)
    ctx = SimpleNamespace(network=net, min_video=900)
    monkeypatch.setattr(visuals, "VID_CAP", 64)
    monkeypatch.setattr(visuals, "_video_url", lambda url, net: url)
    monkeypatch.setattr(visuals, "_max_redirects", lambda: False)
    monkeypatch.setattr(visuals, "probe_video", lambda *a, **k: {"width": 1920, "height": 1080, "duration_s": duration})
    calls = []

    def run(url, purpose, argv, **kwargs):
        calls.append(argv)
        assert int(argv[argv.index("-fs") + 1]) == 64
        Path(argv[-1]).write_bytes(b"x" * size)
    monkeypatch.setattr(net, "run_video", run)
    candidate = {"source": "commons", "width": 1920, "height": 1080, "duration": duration}
    if size >= 64:
        with pytest.raises(ValueError, match="video.*limit"):
            visuals.fetch_video(ctx, candidate, url, tmp_path)
        assert not list(tmp_path.glob("*.mp4*"))
    else:
        visuals.fetch_video(ctx, candidate, url, tmp_path)
        assert candidate["path"].read_bytes() == b"x" * size
    assert len(calls) == 1


@pytest.mark.parametrize("marker", ["cams.json", "visuals/manifest.json", "plan.json"])
def test_torn_stage_is_rebuilt(clip, monkeypatch, marker):
    root, calls = clip.parent, []
    raw = judge.Judge(root).cached("clip01-plan")
    raw["visual_requests"] = [{"id": "v1", "query": "channel"}]
    judge.Judge(root).save("clip01-plan", raw)
    plan.finalize(clip, raw, {})
    pipeline._write(clip / "visuals" / "manifest.json", {})
    path = clip / marker
    path.write_text('{"torn":', encoding="utf-8")
    newer = path.stat().st_mtime + 10
    os.utime(path, (newer, newer))

    def recut(d, *args, **kwargs):
        calls.append("cams.json")
        pipeline._write(d / "cams.json", {})

    def find(requests, outdir, *args, **kwargs):
        calls.append("visuals/manifest.json")
        pipeline._write(outdir / "manifest.json", {})

    finalize = plan.finalize

    def final(*args, **kwargs):
        calls.append("plan.json")
        return finalize(*args, **kwargs)
    monkeypatch.setattr(cut, "cut", recut)
    monkeypatch.setattr(visuals, "find", find)
    monkeypatch.setattr(plan, "finalize", final)
    result = pipeline.run(root, judge.Judge(root), say=lambda m: None)
    assert result["state"] == "done" and result["failed"] == {}
    assert marker in calls and isinstance(pipeline._read(path), dict)


@pytest.mark.parametrize("stage", ["cams", "manifest", "plan", "answer"])
def test_stage_and_answer_writes_keep_the_previous_file_on_interruption(clip, monkeypatch, stage):
    import cv2
    import numpy as np
    from myzing.layout import detector

    monkeypatch.setattr(cut, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(stderr=""))
    monkeypatch.setattr(detector, "require_model", lambda: clip / "model")
    monkeypatch.setattr(cv2, "FaceDetectorYN", SimpleNamespace(create=lambda *a: SimpleNamespace(
        setInputSize=lambda size: None, detect=lambda img: (None, None))))
    monkeypatch.setattr(cv2, "imread", lambda *a: np.zeros((16, 16, 3), dtype=np.uint8))
    monkeypatch.setattr(cut, "burned_caption_top", lambda d: None)
    operations = {
        "cams": (clip / "cams.json", lambda: cut.cams(clip)),
        "manifest": (clip / "visuals" / "manifest.json", lambda: visuals.find([], clip / "visuals", sheet=False)),
        "plan": (clip / "plan.json", lambda: plan.finalize(clip, judge.Judge(clip.parent).cached("clip01-plan"), {})),
        "answer": (clip.parent / "answers" / "scout.json", lambda: judge.Judge(clip.parent).save("scout", {"moments": []})),
    }
    path, write = operations[stage]
    pipeline._write(path, {"old": True})
    original = Path.write_text

    def torn(self, text, *args, **kwargs):
        if self == path or self == path.with_suffix(path.suffix + ".tmp"):
            original(self, text[:3], *args, **kwargs)
            raise OSError("interrupted write")
        return original(self, text, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", torn)
    with pytest.raises(OSError, match="interrupted write"):
        write()
    assert pipeline._read(path) == {"old": True}


def test_caption_fixes_preserve_unrelated_words_and_corrected_names(clip):
    text = "Ann cannot miss the channel anniversary. Anne agrees."
    raw = {"hook": text, "shots": [{"from": 0, "layout": "graphic", "graphic": {"kind": "list", "items": [
        {"text": text}]}}], "fixes": [{"heard": "Ann", "meant": "Anne"}]}
    pipeline._write(clip / "post.json", {"youtube_title": text})
    for _ in range(2):
        final = plan.finalize(clip, raw, {})
        expected = "Anne cannot miss the channel anniversary. Anne agrees."
        assert final["hook"] == final["shots"][0]["graphic"]["items"][0]["text"] == expected
        assert pipeline._read(clip / "post.json")["youtube_title"] == expected
    assert pipeline._read(clip / "words.json")["words"][0]["w"] == "Anne"


def test_many_silences_use_a_filter_script(tmp_path, monkeypatch):
    graphs = []

    def run(*args, **kwargs):
        if "-map" in args:
            assert "-filter_complex" not in args
            script = Path(args[args.index("-filter_complex_script") + 1])
            graphs.append(script.read_text(encoding="utf-8"))
    monkeypatch.setattr(cut, "run", run)
    monkeypatch.setattr(cut, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(cut, "silences", lambda *a: [(i + .2, i + .8) for i in range(220)])
    monkeypatch.setattr(cut, "cams", lambda d: {})
    cut.cut(tmp_path, tmp_path / "episode.mp4", [{"w": "Hello.", "s": 0, "e": .1}], 0, 221)
    assert len(graphs) == 1 and len(graphs[0]) > 32767
    assert "concat=n=221:v=1:a=1[v][a]" in graphs[0]


@pytest.mark.parametrize("names", [("foo.mp4", "foo.mov"), ("My Talk.mp4", "My-Talk.mp4")])
def test_batch_collisions_keep_both_episodes_and_existing_folder(tmp_path, monkeypatch, names):
    inbox, out = tmp_path / "inbox", tmp_path / "projects"
    inbox.mkdir()
    monkeypatch.setattr(batch.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(pipeline, "run", lambda root, ask, **kwargs: pipeline.status(root))
    paths = [inbox / name for name in names]
    for i, path in enumerate(paths):
        path.write_bytes(b"media")
        os.utime(path, (i + 1, i + 1))
    original = batch._project(out, paths[0])
    results = batch.run(inbox, out)["episodes"]
    assert [r["state"] for r in results] == ["new", "new"]
    projects = [Path(r["project"]) for r in results]
    assert projects[0] == original and projects[0] != projects[1]
    assert [pipeline._read(p / "source.json")["media"] for p in projects] == list(map(str, paths))
    assert [batch._project(out, path) for path in paths] == projects
    assert batch._project(out, Path(original.name + ".mp4")) == original
    assert [r["project"] for r in batch.run(inbox, out)["episodes"]] == list(map(str, projects))


def test_corrupt_batch_claim_does_not_stop_other_episodes(tmp_path, monkeypatch):
    inbox, out = tmp_path / "inbox", tmp_path / "projects"
    inbox.mkdir()
    for i, name in enumerate(("first", "second")):
        path = inbox / f"{name}.mp4"
        path.write_bytes(b"media")
        os.utime(path, (i + 1, i + 1))
    pipeline._write(out / "first" / "source.json", {})
    (out / "first" / "source.json").write_text('{"media":', encoding="utf-8")
    monkeypatch.setattr(batch.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(pipeline, "run", lambda root, ask, **kwargs: pipeline.status(root))
    rows = batch.run(inbox, out)["episodes"]
    assert [r["state"] for r in rows] == ["failed", "new"]


@pytest.mark.parametrize("cross_drive", [False, True])
def test_approval_handles_another_drive(clip, tmp_path, monkeypatch, cross_drive):
    video = clip / "clip.mp4"
    video.write_bytes(b"video")
    out = tmp_path / "review" / "approval.html"
    if cross_drive:
        def relpath(*args):
            raise ValueError("path is on another mount")
        monkeypatch.setattr(approval.os.path, "relpath", relpath)
    page = approval.build(clip.parent, out).read_text(encoding="utf-8")
    expected = video.resolve().as_uri() if cross_drive else "../project/clip01/clip.mp4"
    assert f'src="{expected}#t=0.5"' in page


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("succeeds", [False, True])
def test_render_publishes_only_a_successful_encode(clip, monkeypatch, existing, succeeds):
    final = clip / "clip.mp4"
    if existing:
        final.write_bytes(b"old")
    monkeypatch.setattr(render, "scene_data", lambda *a: {"duration": 1})
    monkeypatch.setattr(render, "check_brief", lambda *a: None)
    monkeypatch.setattr(render, "capture", lambda *a: None)
    monkeypatch.setattr(render, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)
    targets = []

    def encode(*args, **kwargs):
        target = Path(args[-1])
        targets.append(target)
        assert not target.match("clip*.mp4")
        target.write_bytes(b"new" if succeeds else b"partial")
        assert sorted(clip.glob("clip*.mp4")) == ([final] if existing else [])
        if not succeeds:
            raise subprocess.CalledProcessError(1, "ffmpeg")
    monkeypatch.setattr(render, "run", encode)
    if succeeds:
        assert render.render(clip) == final
        assert final.read_bytes() == b"new"
    else:
        with pytest.raises(subprocess.CalledProcessError):
            render.render(clip)
        assert final.read_bytes() == b"old" if existing else not final.exists()
    assert targets and not targets[0].exists()


@pytest.mark.parametrize("file,value", [("post.json", '{"x":'), ("post.json", '{"x": []}'),
                                       ("plan.json", '[]'), ("plan.json", '{"shots": [{}]}')])
def test_review_reports_bad_clip_and_keeps_other_cards(clip, file, value):
    root = clip.parent
    moment = pipeline.load_moments(root)["moments"][0]
    pipeline._write(root / "moments.json", {"scouted": True, "moments": [moment, {**moment, "hook": "Healthy clip"}]})
    (clip / "clip.mp4").write_bytes(b"video")
    other = root / "clip02"
    pipeline._write(other / "plan.json", {"shots": []})
    (other / "clip.mp4").write_bytes(b"video")
    (clip / file).write_text(value, encoding="utf-8")
    page = review.build(root).read_text(encoding="utf-8")
    assert "Healthy clip" in page and 'src="clip02/clip.mp4"' in page
    assert "Clip 1" in page and "could not be reviewed" in page


def test_failed_image_decode_is_retried_and_propagated():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is needed to run the page's JavaScript")
    script = data_path("scene.html").read_text(encoding="utf-8")
    function = script[script.index("async function setImg("):script.index("// cover-fit")]
    program = function + """
      (async () => {
        let calls = 0, rejected = false;
        const img = {dataset: {}, decode: async () => { if (++calls === 1) throw Error('bad frame'); }};
        try { await setImg(img, 'frame.jpg'); } catch (e) { rejected = true; }
        const cached = Object.hasOwn(img.dataset, 'src');
        await setImg(img, 'frame.jpg');
        await setImg(img, 'frame.jpg');
        console.log(JSON.stringify({calls, rejected, cached, src: img.dataset.src}));
      })().catch(e => { console.error(e); process.exitCode = 1; });
    """
    result = RUN([node, "-"], input=program, capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"calls": 2, "rejected": True, "cached": False, "src": "frame.jpg"}
