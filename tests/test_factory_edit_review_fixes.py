"""Dashboard edits keep renders and queued words tied to the current clip."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from myzing.factory import judge, pipeline, render, serve
from myzing.factory.tools import FactoryError
from test_factory_context import Answer
from test_factory_review_fixes import javascript, prepared, project
from test_factory_serve_round5 import request


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(serve.Studio, "_work", lambda self: None)


@pytest.mark.parametrize("shape,pack", [("9x16", "zing"), ("4x5", "swiss")])
@pytest.mark.parametrize("changed", ["theme", "fonts", "logo"])
def test_failed_encode_retries_after_capture(project, monkeypatch, shape, pack, changed):
    d = prepared(project)
    cfg = pipeline._read(project / "factory.json")
    pipeline._write(project / "factory.json", {**cfg, "shapes": [shape], "pack": pack})
    tag = render.suffix(shape, pack)
    out, data_file = d / f"clip{tag}.mp4", d / f"data{tag}.json"
    brand = {"theme": {"name": "New"}, "fonts": [{"src": "new.woff2"}], "logo": {"src": "new.png"}}
    data = {"duration": 10, **brand}
    pipeline._write(data_file, {**data, changed: None})
    out.write_bytes(b"old video")
    stamp = (d / "plan.json").stat().st_mtime_ns + 1_000_000_000
    os.utime(out, ns=(stamp, stamp))
    calls = []

    def run(program, *args, **kwargs):
        calls.append(program)
        if program == "node":
            assert pipeline._read(data_file) == data
            os.utime(data_file, ns=(stamp + 1_000_000_000,) * 2)
        elif calls.count("ffmpeg") == 1:
            raise subprocess.CalledProcessError(1, [program])
        else:
            part = Path(args[-1])
            part.write_bytes(b"new video")
            os.utime(part, ns=(stamp + 2_000_000_000,) * 2)

    monkeypatch.setattr(render, "pack_data", lambda pack: (brand["theme"], {k: brand[k] for k in ("fonts", "logo")}, []))
    monkeypatch.setattr(render, "scene_data", lambda *a: data)
    monkeypatch.setattr(render, "node_sidecar", lambda: ("node", d))
    monkeypatch.setattr(render, "sidecar_env", lambda tmp: {})
    monkeypatch.setattr(render, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(render, "run", run)
    monkeypatch.setattr(render.tools, "run", lambda *a, **kw: None)
    j = Answer(project, {"flags": []})
    failed = pipeline.run(project, j, say=lambda m: None)
    assert "ffmpeg" in failed["failed"]["clip01"]
    assert calls == ["node", "ffmpeg"] and out.read_bytes() == b"old video"
    assert pipeline._read(data_file) == data and data_file.stat().st_mtime_ns > out.stat().st_mtime_ns
    assert not pipeline.run(project, j, say=lambda m: None)["failed"]
    assert calls == ["node", "ffmpeg"] * 2 and out.read_bytes() == b"new video"
    assert not pipeline.run(project, j, say=lambda m: None)["failed"]
    assert calls == ["node", "ffmpeg"] * 2


def test_video_revisions_change_after_replacement(project):
    d = prepared(project)
    out = d / "clip.mp4"
    out.write_bytes(b"old video")
    studio = serve.Studio(project)
    stamp = out.stat().st_mtime_ns
    before = studio.state()["clips"][0]["videos"]
    assert before == {"clip.mp4": str(stamp)}
    part = d / "_clip.part.mp4"
    part.write_bytes(b"new video")
    os.utime(part, ns=(stamp + 1_000_000_000,) * 2)
    part.replace(out)
    after = studio.state()["clips"][0]["videos"]
    assert after == {"clip.mp4": str(out.stat().st_mtime_ns)} and after != before
    assert studio.media("clip01/clip.mp4?v=123") == out
    req = request(studio, path="/media/clip01/clip.mp4?v=123")
    req.do_GET()
    assert req.code == 200 and req.wfile.getvalue() == b"new video"
    req = request(studio, path="/media/clip01/clip.mp4?v=123", headers={"Range": "bytes=0-2"})
    req.do_GET()
    assert req.code == 206 and req.wfile.getvalue() == b"new"


@pytest.mark.parametrize("edited", ["plan.json", "words.json"])
def test_state_lists_only_older_variants_as_stale(project, edited):
    d = prepared(project)
    stamp = max((d / name).stat().st_mtime_ns for name in ("plan.json", "words.json")) + 1_000_000_000
    os.utime(d / edited, ns=(stamp, stamp))
    files = {"clip-4x5-swiss.mp4": stamp - 100, "clip.mp4": stamp, "clip-1x1.mp4": stamp + 100}
    for name, rev in files.items():
        (d / name).write_bytes(name.encode())
        os.utime(d / name, ns=(rev, rev))
    studio = serve.Studio(project)
    clip = studio.state()["clips"][0]
    assert clip["stale_videos"] == ["clip-4x5-swiss.mp4"]
    assert set(clip["videos"]) == set(files)
    assert all(studio.media(f"clip01/{name}").read_bytes() == name.encode() for name in files)


@pytest.mark.parametrize("selection", [{"index": 1}, {"index": 1, "old": "built"}, {"at": 1.2, "old": "built"}])
@pytest.mark.parametrize("change", ["shift", "shorten", "missing"])
def test_word_job_rejects_a_changed_word(project, monkeypatch, selection, change):
    d = prepared(project)
    studio = serve.Studio(project)
    called = []
    monkeypatch.setattr(studio, "_context", lambda d: called.append("context"))
    monkeypatch.setattr(studio, "_rerender", lambda d: called.append("render"))

    def earlier_job():
        path = d / "words.json"
        if change == "missing":
            path.unlink()
        else:
            data = pipeline._read(path)
            data["words"] = data["words"][1:] if change == "shift" else data["words"][:1]
            pipeline._write(path, data)

    studio.queue("trim", earlier_job)
    studio.word({"clip": "clip01", "new": "made", **selection})
    studio.jobs.get_nowait()[1]()
    before = {p: p.read_bytes() for p in d.rglob("*.json")}
    with pytest.raises(FactoryError, match="^the clip changed since this edit was queued; reload and try again$"):
        studio.jobs.get_nowait()[1]()
    assert {p: p.read_bytes() for p in d.rglob("*.json")} == before and not called


def test_dashboard_refreshes_only_when_video_revision_changes():
    got = javascript("dashboard.html", """
      Element.prototype.insertBefore = function(n, old) { this.children.splice(old ? this.children.indexOf(old) : this.children.length, 0, n); };
      Element.prototype.replaceChild = function(n, old) { this.children[this.children.indexOf(old)] = n; };
      ui.project = {state: 'done', settings: {pack: 'zing'}, clips: [
        {clip: 'clip01', videos: {'clip.mp4': '1700000000000000100'}}]};
      render();
      const video = all(nodes['#grid']).find(n => n.tagName === 'video');
      ui.project = JSON.parse(JSON.stringify(ui.project)); render();
      const kept = all(nodes['#grid']).includes(video);
      ui.project.clips[0].videos['clip.mp4'] = '1700000000000000200'; render();
      const next = all(nodes['#grid']).find(n => n.tagName === 'video');
      console.log(JSON.stringify({kept, replaced: next !== video, before: video.attrs.src, after: next.attrs.src,
        image: api.media('clip01', 'visuals/a b.jpg')}));
    """)
    assert got == {"kept": True, "replaced": True, "before": "/media/clip01/clip.mp4?v=1700000000000000100",
                   "after": "/media/clip01/clip.mp4?v=1700000000000000200", "image": "/media/clip01/visuals/a%20b.jpg"}


def test_dashboard_labels_stale_variants_and_keeps_them_playable():
    got = javascript("dashboard.html", """
      ui.project = {settings: {pack: 'zing'}}; ui.pack.clip01 = 'swiss'; ui.shape.clip01 = '4x5';
      const c = {clip: 'clip01', videos: {'clip.mp4': '200', 'clip-4x5-swiss.mp4': '100'},
        stale_videos: ['clip-4x5-swiss.mp4']};
      const card = all(clipCard(c));
      console.log(JSON.stringify({shapes: shapesFor(c).map(s => s.id),
        src: card.find(n => n.tagName === 'video').attrs.src,
        labels: card.map(n => n.textContent).filter(t => t.includes('older than the latest edit'))}));
    """)
    assert got == {"shapes": ["4x5"], "src": "/media/clip01/clip-4x5-swiss.mp4?v=100",
                   "labels": ["clip-4x5-swiss.mp4 is older than the latest edit"]}
