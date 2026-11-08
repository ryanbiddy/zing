"""Intake and posting regressions with local media and fake encoding."""
from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import pytest
from PIL import Image

from myzing.channels import brief, gate, kit, publish, queue, registry, watch
from myzing.factory import pipeline, render, source

from test_channels_recordings import NOW as TAKE_NOW, SCRIPT, channel as recordings, media, rows, seed, transcribe
from test_channels_review_fixes import NOW, channel, offline, ready
from test_factory_campaign import Answers


@pytest.fixture(autouse=True)
def local(offline, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked transcription")

    monkeypatch.setattr(source, "scout_model", lambda: None)
    monkeypatch.setattr(source, "transcribe_episode", refuse)
    monkeypatch.setattr(watch, "_duration", lambda path: 30)


class Visuals(Answers):
    def ask(self, task, text, images=()):
        if task.endswith("-plan"):
            return {"hook": "A test", "shots": [{"from": 0, "layout": "split", "visual": "v1"}],
                    "visual_requests": [{"id": "v1", "query": "test", "kind": "photo"}]}
        if task.endswith("-pick"):
            return {"v1": {"pick": 1}}
        return super().ask(task, text, images)


@pytest.fixture
def built(channel, tmp_path, monkeypatch, request):
    pack = getattr(request, "param", "zing")
    project = registry.directory(channel["slug"]) / "projects" / "rendered"
    media = tmp_path / "episode.mp4"
    media.write_bytes(b"source")
    pipeline.init(project, media, channel=channel["slug"], source="show", rights="permission", pack=pack,
                  shapes=["9x16", "1x1"], parallax=False, cutout=False, upscale=False, offline=True,
                  brief={"name": "Test", "max_seconds": 40})
    pipeline._write(project / "transcript.json", [{"s": 0, "e": 40, "text": "A test."}])
    pipeline._write(project / "moments.json", {"scouted": True, "moments": [
        {"start": 10, "end": 30, "hook": "A test", "snapped": True}]})
    pipeline._write(project / "ratings.json", {"clip01": {"v": "post"}})
    control = {"fail": None}

    def cut(d, *args):
        pipeline._write(d / "words.json", {"start": 10, "duration": 20, "words": [
            {"w": "A", "os": 0, "oe": 1}, {"w": "test.", "os": 1, "oe": 19.55}]})
        pipeline._write(d / "cams.json", {"frames": 600, "size": [1920, 1080], "cams": []})
        (d / "cut.mp4").write_bytes(b"cut")

    def find(reqs, vis, *args, **kwargs):
        for name in ("a.jpg", "b.jpg"):
            Image.new("RGB", (16, 16)).save(vis / name)
        pipeline._write(vis / "manifest.json", {"v1": [
            {"path": name, "rights": "cleared", "source": "local"} for name in ("a.jpg", "b.jpg")]})

    def run(program, *args, **kwargs):
        if program == "node":
            if control["fail"] == "capture":
                raise render.FactoryError("capture failed")
            (Path(args[-1]) / "00001.jpg").write_bytes(b"frame")
        else:
            if control["fail"] == "encode":
                raise render.FactoryError("encode failed")
            Path(args[-1]).write_bytes(b"render")

    monkeypatch.setattr(pipeline.cut, "cut", cut)
    monkeypatch.setattr(pipeline.visuals, "find", find)
    monkeypatch.setattr(pipeline.pick, "sheet", lambda vis, *a: vis / "pick_sheet.jpg")
    monkeypatch.setattr(render, "node_sidecar", lambda: ("node", tmp_path))
    monkeypatch.setattr(render, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(render, "run", run)
    monkeypatch.setattr(render.tools, "run", run)
    ask = Visuals(project)
    result = pipeline.run(project, ask, say=lambda m: None)
    assert result["state"] == "done" and not result["failed"] and not result["pending"]
    return project, ask, control, render.suffix("9x16", pack)


@pytest.mark.parametrize("built", ["zing", "documentary"], indirect=True)
def test_normal_pipeline_and_later_checks_pass_the_gate(channel, built):
    project, ask, _, tag = built
    d = project / "clip01"
    video = d / f"clip{tag}.mp4"
    assert gate.check(project, d.name, channel, now=NOW) == {"publishable": True, "blockers": []}
    for name in ("plan.json", "visuals/picks.json", "visuals/manifest.json", f"data{tag}.json"):
        assert (d / name).stat().st_mtime_ns <= video.stat().st_mtime_ns
    assert not pipeline.run(project, ask, say=lambda m: None)["failed"]
    for name in ("context.json", "brief_check.json", "post.json", "plan-raw.json"):
        path = d / name
        pipeline._write(path, pipeline._read(path))
        stamp = video.stat().st_mtime_ns + 10_000_000_000
        os.utime(path, ns=(stamp, stamp))
        assert gate.check(project, d.name, channel, now=NOW)["publishable"]


@pytest.mark.parametrize("built", ["zing", "documentary"], indirect=True)
@pytest.mark.parametrize("failure", ["capture", "encode"])
def test_visual_swap_and_failed_render_block_the_old_video(channel, built, failure):
    project, ask, control, tag = built
    d = project / "clip01"
    video = d / f"clip{tag}.mp4"
    before = video.read_bytes()
    stamp = video.stat().st_mtime_ns - 10_000_000_000
    for path in d.rglob("*"):
        if path.is_file():
            os.utime(path, ns=(stamp, stamp))
    pipeline._write(d / "visuals" / "picks.json", {"picks": {"v1": {"pick": 1}}})
    control["fail"] = failure
    result = pipeline.run(project, ask, say=lambda m: None)
    assert result["failed"] == {"clip01": f"{failure} failed"}
    assert pipeline._read(d / "plan.json")["visuals"]["v1"]["path"].endswith("b.jpg")
    assert video.read_bytes() == before and video.stat().st_mtime_ns == stamp
    assert gate.check(project, d.name, channel, now=NOW) == {
        "publishable": False, "blockers": ["The 9x16 render is older than its plan."]}


@pytest.mark.parametrize("name", ["plan.json", "data.json", "visuals/picks.json", "visuals/manifest.json",
                                 "words.json", "cams.json", "cut.mp4"])
def test_each_render_input_can_make_the_video_old(channel, built, name):
    project, _, _, _ = built
    d = project / "clip01"
    stamp = (d / "clip.mp4").stat().st_mtime_ns + 10_000_000_000
    os.utime(d / name, ns=(stamp, stamp))
    assert gate.check(project, d.name, channel, now=NOW)["blockers"] == ["The 9x16 render is older than its plan."]


@pytest.mark.parametrize("blocker", ["grant", "no", "context", "pause"])
def test_existing_kit_is_regated_and_removed_from_phone(channel, tmp_path, blocker):
    channel["phone_folder"] = str(tmp_path / "phone")
    registry.save(channel)
    project, row = ready(channel)
    folder = Path(row["kit"])
    phone = tmp_path / "phone" / f"{channel['slug']}-kits" / folder.name
    assert phone.is_dir() and not kit._stale(project / row["clip"], folder)
    if blocker == "grant":
        channel["sources"][0]["rights"]["expires"] = (NOW - timedelta(days=1)).date().isoformat()
        registry.save(channel)
    elif blocker == "no":
        pipeline._write(project / "ratings.json", {"clip01": {"v": "no"}})
    elif blocker == "context":
        pipeline._write(project / row["clip"] / "context.json", {"flags": [{"why": "Check this"}]})
    else:
        (registry.directory(channel["slug"]) / "PAUSE").touch()
    result = kit._kit(channel, None, None, NOW) if blocker == "pause" else kit.kit(channel["slug"], now=NOW)
    assert result["made"] == 0 and not result["warnings"]
    assert result["blocked"] == {row["id"]: gate.check(project, row["clip"], channel, now=NOW)["blockers"]}
    assert result["blocked"][row["id"]]
    assert queue.read(channel["slug"])[0]["status"] == "queued"
    assert folder.is_dir() and not phone.exists()
    assert "<video " not in (phone.parent / "index.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("change", ["size", "mtime"])
def test_replaced_recording_discards_stage_and_retries(recordings, monkeypatch, change):
    path, _ = seed(recordings)
    take = media(recordings)
    stat = take.stat()
    _, words = transcribe(monkeypatch)

    def replace(*args, **kwargs):
        if change == "size":
            take.write_bytes(b"new take with different words")
        stamp = stat.st_mtime_ns + (1_000_000_000 if change == "mtime" else 0)
        os.utime(take, ns=(stamp, stamp))
        return words

    monkeypatch.setattr(source, "transcribe_episode", replace)
    result = watch.run(recordings["slug"], now=TAKE_NOW)
    assert result == {"found": 1, "started": 0, "errors": []}
    row, = rows(recordings)
    assert row["state"] == "found, changed during intake" and "project" not in row and "item" not in row
    root = registry.directory(recordings["slug"])
    assert not list((root / "inbox").iterdir()) and not list((root / "projects").iterdir())
    assert pipeline._read(path)["items"][0]["status"] == "open"
    calls, fresh = transcribe(monkeypatch, text=SCRIPT + " Fresh ending.")
    assert watch.run(recordings["slug"], now=TAKE_NOW + timedelta(minutes=3)) == {
        "found": 0, "started": 1, "errors": []}
    project = Path(rows(recordings)[0]["project"])
    assert len(calls) == 1 and pipeline._read(project / "words.json") == fresh
    assert pipeline._read(path)["items"][0]["project"] == str(project)


@pytest.mark.parametrize("pack", ["zing", "documentary"])
@pytest.mark.parametrize("name", ["video", "post"])
@pytest.mark.parametrize("change", ["older", "equal"])
def test_source_replacement_stales_kit_and_blocks_upload(channel, name, change, pack):
    project, row = ready(channel, pack)
    d, folder = project / row["clip"], Path(row["kit"])
    path = d / (f"clip{render.suffix('9x16', pack)}.mp4" if name == "video" else "post.json")
    stat = path.stat()
    stamp = stat.st_mtime_ns - (10_000_000_000 if change == "older" else 0)
    if name == "video":
        path.write_bytes(b"other" if change == "older" else b"a longer replacement")
        os.utime(d / "plan.json", ns=(stamp - 1_000_000_000, stamp - 1_000_000_000))
        os.utime(d / "words.json", ns=(stamp - 1_000_000_000, stamp - 1_000_000_000))
        os.utime(d / "cams.json", ns=(stamp - 1_000_000_000, stamp - 1_000_000_000))
    else:
        path.write_bytes(path.read_bytes().replace(b"A story", b"B story") + (b" " if change == "equal" else b""))
    os.utime(path, ns=(stat.st_atime_ns, stamp))
    assert kit._stale(d, folder) and gate.check(project, row["clip"], channel, now=NOW)["publishable"]
    result = publish.upload(channel["slug"], dry_run=True, now=NOW)
    assert not result["uploads"] and result["blocked"] == {
        row["id"]: ["The kit is older than the clip. Run zing channels kit."]}
    assert kit.kit(channel["slug"], now=NOW)["kits"] == [str(folder)]
    assert not kit._stale(d, folder)
    assert len(publish.upload(channel["slug"], dry_run=True, now=NOW)["uploads"]) == 1


def test_kits_without_source_stamps_keep_the_newer_than_rule(channel):
    project, row = ready(channel)
    d, folder = project / row["clip"], Path(row["kit"])
    post = pipeline._read(folder / "post.json")
    post.pop("kit_sources")
    pipeline._write(folder / "post.json", post)
    assert not kit._stale(d, folder)
    stamp = (folder / "video.mp4").stat().st_mtime_ns
    os.utime(d / "clip.mp4", ns=(stamp, stamp))
    assert not kit._stale(d, folder)
    os.utime(d / "clip.mp4", ns=(stamp + 1_000_000_000, stamp + 1_000_000_000))
    assert kit._stale(d, folder)


def test_recovery_does_not_steal_another_projects_brief(recordings, monkeypatch, tmp_path):
    path, _ = seed(recordings)
    media(recordings)
    calls, _ = transcribe(monkeypatch)

    def fail(*args):
        raise OSError("brief write interrupted")

    with monkeypatch.context() as patch:
        patch.setattr(brief, "recorded", fail)
        assert watch.run(recordings["slug"], now=TAKE_NOW)["started"] == 0
    data = pipeline._read(path)
    data["items"][0].update(status="recorded", project=str(tmp_path / "another-project"))
    pipeline._write(path, data)
    before = path.read_bytes()
    assert watch.run(recordings["slug"], now=TAKE_NOW) == {"found": 0, "started": 0, "errors": []}
    row, = rows(recordings)
    project = Path(row["project"])
    take = pipeline._read(project / "recording.json")
    assert take == {"brief": "2026-11-06", "item": 1, "series": "breakdowns"}
    assert all(row[key] == value for key, value in take.items())
    assert path.read_bytes() == before and len(calls) == 1


@pytest.mark.parametrize("kind", ["folder", "own", "recordings"])
@pytest.mark.parametrize("bad", [b'{"title":', b'\xff', b'[]', None])
def test_bad_sidecar_only_skips_its_file(recordings, monkeypatch, kind, bad):
    recordings["sources"][0]["kind"] = kind
    registry.save(recordings)
    broken = media(recordings, "a-broken.mp4").with_suffix(".info.json")
    broken.write_bytes(bad or b'{}')
    read = Path.read_text

    def unreadable(path, *args, **kwargs):
        if path == broken:
            raise PermissionError("sidecar is unreadable")
        return read(path, *args, **kwargs)

    if bad is None:
        monkeypatch.setattr(Path, "read_text", unreadable)
    good = media(recordings, "b-good.mp4")
    pipeline._write(good.with_suffix(".info.json"), {"title": "Good take"})
    transcribe(monkeypatch)
    result = watch.run(recordings["slug"], now=TAKE_NOW)
    assert result["found"] == result["started"] == 1 and len(result["errors"]) == 1
    assert "a-broken.mp4" in result["errors"][0]
    row, = rows(recordings)
    assert row["title"] == "Good take" and Path(row["project"]).is_dir()
    broken.unlink()
    result = watch.run(recordings["slug"], now=TAKE_NOW)
    assert result == {"found": 1, "started": 1, "errors": []}
    assert len(rows(recordings)) == 2
