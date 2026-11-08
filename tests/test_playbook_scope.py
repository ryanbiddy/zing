"""Cohort labels and early channel warnings without network or media calls."""
from __future__ import annotations

import json

import pytest

from myzing.playbook import command, distill, measure, notes, sources
from myzing.playbook.common import read_json, write_json
from myzing.schemas import Breakdown, VideoMeta


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(sources.proc, "run", refuse)
    monkeypatch.setattr(measure.study_api, "study", refuse)
    monkeypatch.setattr(notes.urls, "open_no_redirect", refuse)
    monkeypatch.setattr(notes.urllib.request, "urlopen", refuse)


@pytest.fixture
def listings(monkeypatch):
    def listing(handle):
        return [] if handle == "Empty" else [{"id": f"{handle}_{i}", "view_count": i + 1} for i in range(50)]
    monkeypatch.setattr(sources, "list_channel", listing)


def library(root, count=7, **extra):
    entries = [{"id": f"c{i}_{group}", "platform": "youtube", "channel": f"c{i}", "set": group,
                "url": f"https://www.youtube.com/shorts/c{i}_{group}"}
               for i in range(count) for group in ("worked", "didnt")]
    write_json(root / "library.json", {"schema_version": 1, "entries": entries, **extra})


def warning(count):
    return (f"distill needs at least 8 channels to keep a pattern; this library has {count}. "
            "Add channels, or pass --min-channels N to distill.\n") if count < 8 else ""


@pytest.mark.parametrize("scope,expected", [
    ("Developer channel Shorts", "Developer channel Shorts"),
    (" \tDeveloper\r\nchannel\nShorts \t", "Developer channel Shorts"),
    ("開発者 Shorts", "開発者 Shorts"),
    ("x" * 120, "x" * 120),
])
def test_list_saves_scope(tmp_path, listings, capsys, scope, expected):
    assert command.run(["list", "--channels", "@Example", "--out", str(tmp_path), "--scope", scope]) == 0
    data = read_json(tmp_path / "library.json")
    assert data["scope"] == expected
    assert len(data["entries"]) == 10
    assert json.loads(capsys.readouterr().out)["entries"] == 10


def test_import_saves_scope(tmp_path, capsys):
    source = tmp_path / "candidates.json"
    write_json(source, {"Example": sources.select([{"id": f"v{i}", "views": i + 1} for i in range(50)])})
    out = tmp_path / "out"
    assert command.run(["list", "--from-candidates", str(source), "--out", str(out),
                        "--scope", "Developer channel Shorts"]) == 0
    assert read_json(out / "library.json")["scope"] == "Developer channel Shorts"
    assert capsys.readouterr().err == warning(1)


@pytest.mark.parametrize("saved,flags,expected", [
    ({}, [], "YouTube Shorts"),
    ({"scope": "Developer channel Shorts"}, [], "Developer channel Shorts"),
    ({"scope": "Developer channel Shorts"}, ["--scope", "Coding tutorial Shorts"], "Coding tutorial Shorts"),
    ({}, ["--scope", "Developer channel Shorts"], "Developer channel Shorts"),
    ({"scope": " Developer\r\nchannel\tShorts "}, [], "Developer channel Shorts"),
    ({}, ["--scope", " Developer\r\nchannel\tShorts "], "Developer channel Shorts"),
    ({}, ["--scope", "x" * 120], "x" * 120),
])
def test_distill_scope_in_json_and_report(tmp_path, capsys, saved, flags, expected):
    library(tmp_path, **saved)
    before = (tmp_path / "library.json").read_bytes()
    assert command.run(["distill", str(tmp_path), "--version", "scope", *flags]) == 0
    data = read_json(tmp_path / "playbook-scope.json")
    report = (tmp_path / "WHATS-WORKING-scope.md").read_text(encoding="utf-8")
    assert data["scope"] == expected
    assert data["caveats"][0] == f"{expected} only; cohort membership is curated, not verified by listing."
    assert data["caveats"][0] in report
    assert "podcast" not in (json.dumps(data) + report).lower()
    assert data["thresholds"]["min_channels"] == distill.Thresholds().min_channels
    assert data["patterns"] == []
    assert all("too few eligible channels" in row["reasons"] for row in data["no_separation"])
    assert (tmp_path / "library.json").read_bytes() == before
    assert capsys.readouterr().err == ""


def test_scope_only_changes_label(tmp_path):
    library(tmp_path)
    original = distill.distill(tmp_path)
    changed = distill.distill(tmp_path, scope="Developer channel Shorts")
    assert {k: v for k, v in original.items() if k not in ("scope", "caveats")} == {
        k: v for k, v in changed.items() if k not in ("scope", "caveats")}
    assert original["caveats"][1:] == changed["caveats"][1:]


@pytest.mark.parametrize("action", ["list", "distill"])
@pytest.mark.parametrize("scope", ["x" * 121, "", " \r\n\t ", "Developer\x00Shorts", "Developer\x1bShorts"])
def test_invalid_scope_leaves_no_output(tmp_path, capsys, action, scope):
    if action == "list":
        args = ["list", "--channels", "@Example", "--out", str(tmp_path)]
    else:
        library(tmp_path)
        args = ["distill", str(tmp_path), "--version", "scope"]
    assert command.run([*args, "--scope", scope]) == 2
    assert "scope must" in capsys.readouterr().out
    assert not (tmp_path / "playbook-scope.json").exists()
    assert not (tmp_path / "WHATS-WORKING-scope.md").exists()
    if action == "list":
        assert not (tmp_path / "library.json").exists()


@pytest.mark.parametrize("scope", ["x" * 121, 42, ["Developer Shorts"]])
def test_invalid_library_scope_and_valid_override(tmp_path, scope):
    library(tmp_path, scope=scope)
    with pytest.raises(ValueError, match="scope must"):
        distill.distill(tmp_path)
    assert not (tmp_path / "playbook-v0.json").exists()
    assert distill.distill(tmp_path, scope="Developer Shorts")["scope"] == "Developer Shorts"


@pytest.mark.parametrize("count", [0, 1, 3, 7, 8, 9])
def test_list_warns_for_distinct_selected_channels(tmp_path, listings, capsys, count):
    handles = [*(f"@c{i}" for i in range(count)), "@c0" if count else "@Empty", "@Empty"]
    assert command.run(["list", "--channels", *handles, "--out", str(tmp_path)]) == 0
    output = capsys.readouterr()
    assert output.err == warning(count)
    assert json.loads(output.out)["entries"] == count * 10
    data = read_json(tmp_path / "library.json")
    assert data["scope"] == "YouTube Shorts"
    assert data["channels"]["Empty"]["status"] == "skipped"
    assert len(data["channels"]) == count + 1


@pytest.mark.parametrize("count", [0, 1, 3, 7, 8, 9])
def test_measure_warns_for_distinct_channels(tmp_path, capsys, count):
    library(tmp_path, count)
    assert command.run(["measure", str(tmp_path)]) == 0
    output = capsys.readouterr()
    assert output.err == warning(count)
    assert json.loads(output.out)["unmeasured"] == count * 2


@pytest.mark.parametrize("count", [7, 8])
def test_measure_warning_precedes_downloads(tmp_path, monkeypatch, capsys, count):
    library(tmp_path, count)
    calls = []
    def study(source, **kwargs):
        output = capsys.readouterr()
        assert output.err == (warning(count) if not calls else "")
        assert output.out == ""
        calls.append(source)
        return Breakdown(VideoMeta("file", "file", duration=10, width=1080, height=1920))
    monkeypatch.setattr(measure.study_api, "study", study)
    assert command.run(["measure", str(tmp_path), "--download", "--gap", "0"]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert json.loads(output.out)["done"] == len(calls) == count * 2
