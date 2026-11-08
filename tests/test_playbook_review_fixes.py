"""Interrupted measurements and report writes with local fakes."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from myzing.playbook import command, distill, measure, sources
from myzing.playbook.common import read_json, write_json
from myzing.schemas import Breakdown, VideoMeta


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(measure.study_api, "study", refuse)
    monkeypatch.setattr(measure.time, "sleep", refuse)
    monkeypatch.setattr(sources.proc, "run", refuse)


def library(root, *ids):
    entries = [{"id": ident, "platform": "youtube", "channel": "Example", "set": "worked",
                "url": f"https://www.youtube.com/shorts/{ident}"} for ident in ids]
    write_json(root / "library.json", {"schema_version": 1, "entries": entries})
    return entries


def breakdown():
    return Breakdown(VideoMeta("file", "file", duration=11, width=1080, height=1920))


def failed(root, ident):
    path = root / "measured" / f"{ident}.failed.json"
    write_json(path, {"id": ident, "source": "measured", "status": "failed",
                      "reason": "RuntimeError: measurement failed; details omitted"})
    return path


def test_interrupted_retry_keeps_failure_for_next_retry(tmp_path, monkeypatch, capsys):
    entries = library(tmp_path, "A")
    failure = failed(tmp_path, "A")
    before = failure.read_bytes(), failure.stat().st_mtime_ns
    calls = []
    def study(source, **kwargs):
        calls.append(source)
        if len(calls) == 1:
            raise KeyboardInterrupt
        return breakdown()
    monkeypatch.setattr(measure.study_api, "study", study)
    args = ["measure", str(tmp_path), "--download", "--retry-failed", "--gap", "0"]
    with pytest.raises(KeyboardInterrupt):
        command.run(args)
    assert (failure.read_bytes(), failure.stat().st_mtime_ns) == before
    assert command.run(args) == 0
    assert calls == [entries[0]["url"]] * 2
    assert json.loads(capsys.readouterr().out)["done"] == 1
    assert not failure.exists()


@pytest.mark.parametrize("first", ["done", "cached", "failed", "unmeasured", "error"])
def test_interrupted_measure_keeps_unprocessed_features(tmp_path, monkeypatch, first):
    library(tmp_path, "A", "B", "C")
    previous = [{"id": ident, "source": "measured", "status": "measured", "duration": duration}
                for ident, duration in (("C", 30), ("A", 10), ("B", 20), ("removed", 40))]
    feature_path = tmp_path / "features.json"
    write_json(feature_path, {"schema_version": 1, "entries": previous})
    media = tmp_path / "media"
    media.mkdir()
    for ident in (("A", "B", "C") if first in ("done", "error") else ("B", "C")):
        (media / f"{ident}.mp4").write_bytes(b"fixture; not a video")
    if first == "cached":
        write_json(tmp_path / "measured/A.json", breakdown().to_dict())
    if first == "failed":
        failed(tmp_path, "A")
    calls = []
    def study(source, **kwargs):
        ident = Path(source).stem
        calls.append(ident)
        if ident == "B":
            raise KeyboardInterrupt
        if first == "error":
            raise RuntimeError("fixture failure")
        return breakdown()
    monkeypatch.setattr(measure.study_api, "study", study)
    with pytest.raises(KeyboardInterrupt):
        measure.measure(tmp_path)
    rows = read_json(feature_path)["entries"]
    assert [row["id"] for row in rows] == ["A", "C", "B", "removed"]
    assert rows[1:] == [previous[0], previous[2], previous[3]]
    status = "measured" if first in ("done", "cached") else "failed" if first == "error" else first
    assert rows[0]["status"] == status
    if status == "measured":
        assert rows[0]["duration"] == 11
    assert calls == (["A", "B"] if first in ("done", "error") else ["B"])
    monkeypatch.setattr(measure.study_api, "study", lambda *a, **kw: breakdown())
    measure.measure(tmp_path)
    final = read_json(feature_path)
    assert [row["id"] for row in final["entries"]] == ["A", "B", "C"]
    assert "created_at" in final


def test_empty_selection_clears_previous_features(tmp_path):
    library(tmp_path)
    write_json(tmp_path / "features.json", {"schema_version": 1, "entries": [{"id": "removed"}]})
    assert measure.measure(tmp_path)["entries"] == []
    assert read_json(tmp_path / "features.json")["entries"] == []


@pytest.mark.parametrize("mode", ["fresh", "force", "retry", "cached"])
def test_measure_uses_newest_caption_geometry(tmp_path, monkeypatch, mode):
    library(tmp_path, "A")
    old = {"frames": [{"width": 100, "height": 100, "face_boxes": []}]}
    new = {"frames": [{"width": 100, "height": 100, "face_boxes": [[0, 0, .5, .5]]}]}
    older = tmp_path / "working/A/a-old/caption-geometry.json"
    newer = tmp_path / "working/A/z-new/caption-geometry.json"
    write_json(older, old)
    os.utime(older, (100, 100))
    target = tmp_path / "measured/A.json"
    sidecar = target.with_suffix(".caption-geometry.json")
    if mode != "fresh":
        write_json(target, breakdown().to_dict())
    if mode in ("force", "retry"):
        write_json(sidecar, old)
    if mode == "retry":
        failed(tmp_path, "A")
    def study(*args, **kwargs):
        write_json(newer, new)
        os.utime(newer, (200, 200))
        return breakdown()
    if mode == "cached":
        study()
    else:
        monkeypatch.setattr(measure.study_api, "study", study)
    result = measure.measure(tmp_path, download=True, force=mode == "force", retry_failed=mode == "retry")
    assert result["cached" if mode == "cached" else "done"] == 1
    assert read_json(sidecar) == new
    row = read_json(tmp_path / "features.json")["entries"][0]
    assert row["face_presence_share"] == 1 and row["largest_face_area_share"] == .25


@pytest.mark.parametrize("odd", [None, "unexpected row", [], 7, False])
def test_listing_skips_non_dict_rows_and_keeps_channels(tmp_path, monkeypatch, odd):
    monkeypatch.setattr(sources.doctor, "resolve_ytdlp_argv", lambda: ["fixture-ytdlp"])
    rows = {handle: [{"id": f"{handle}_{i}", "view_count": i + 1} for i in range(50)]
            for handle in ("Example", "Other")}
    def run(argv, **kwargs):
        handle = argv[-1].split("@", 1)[1].split("/", 1)[0]
        values = [odd, *rows[handle][:20], odd, *rows[handle][20:]] if handle == "Example" else rows[handle]
        return subprocess.CompletedProcess(argv, 0, "\n".join(json.dumps(row) for row in values), "")
    monkeypatch.setattr(sources.proc, "run", run)
    assert sources.list_channel("Example") == rows["Example"]
    result = sources.build(tmp_path, ["Example", "Other"])
    assert len(result["entries"]) == 20
    assert read_json(tmp_path / "library.json") == result
    for handle in rows:
        selected = sources.select(rows[handle])
        assert result["channels"][handle]["status"] == "listed"
        assert result["channels"][handle]["n"] == selected["n"]
        assert [row["id"] for row in result["entries"] if row["channel"] == handle] == [
            row["id"] for group in ("worked", "didnt") for row in selected[group]]
        assert read_json(tmp_path / "channels" / f"{handle}.json") == result["channels"][handle]


@pytest.mark.parametrize("stage", ["write", "replace"])
def test_failed_report_write_keeps_previous_report(tmp_path, monkeypatch, stage):
    library(tmp_path, "A")
    target = tmp_path / "WHATS-WORKING-v0.md"
    distill.distill(tmp_path)
    before = target.read_bytes(), target.stat().st_mtime_ns
    write_text, replace = Path.write_text, Path.replace
    attempts = []
    def fail_write(path, text, *args, **kwargs):
        if path.name.startswith("WHATS-WORKING-"):
            attempts.append(path)
            write_text(path, text[:12], *args, **kwargs)
            raise OSError("fixture write failed")
        return write_text(path, text, *args, **kwargs)
    def fail_replace(path, destination):
        if destination == target:
            attempts.append(path)
            raise OSError("fixture replace failed")
        return replace(path, destination)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "write_text" if stage == "write" else "replace",
                      fail_write if stage == "write" else fail_replace)
        with pytest.raises(OSError, match=f"fixture {stage} failed"):
            distill.distill(tmp_path, scope="Updated cohort")
    assert (target.read_bytes(), target.stat().st_mtime_ns) == before
    assert len(attempts) == 1 and attempts[0].parent == target.parent and attempts[0] != target
    assert read_json(tmp_path / "playbook-v0.json")["scope"] == "Updated cohort"
    result = distill.distill(tmp_path, scope="Updated cohort")
    assert target.read_text(encoding="utf-8") == distill.report(result)
    assert not attempts[0].exists()
