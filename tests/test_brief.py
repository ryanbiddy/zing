"""Brief acceptance: real stdin, deterministic saves, honest evidence, and recovery."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys

import pytest

from myzing import cli
from myzing.brief import api as brief_api
from myzing.brief.models import Brief, BriefError
from myzing.brief.questions import brief_questions
from myzing.brief.recommend import recommend
from myzing.mcp_server import h_brief_questions, h_brief_save
from myzing.project import api as project_api
from myzing.project.probe import parse_probe
from myzing.study.proc import MediaError


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "Ryan's project"
    clips = root / "clips"
    clips.mkdir(parents=True)
    for name in ("intro.mp4", "wide.mp4", "missing.mp4", "notes.xyz", "bed.wav"):
        (clips / name).write_bytes(name.encode())

    def probe(path):
        if path.suffix == ".xyz":
            raise MediaError("unsupported fixture")
        streams = [{"codec_type": "audio"}]
        if path.suffix == ".mp4":
            width, height = (1920, 1080) if path.name == "wide.mp4" else (1080, 1920)
            streams.append({"codec_type": "video", "width": width, "height": height,
                            "avg_frame_rate": "30/1", "r_frame_rate": "30/1"})
        return parse_probe({"streams": streams, "format": {"duration": "8"}})

    monkeypatch.setattr(project_api, "probe_file", probe)
    project_api.init_project("uoink:example", clips, root)
    (clips / "missing.mp4").unlink()
    return root


def answers():
    return {
        "purpose": "Meet the maker", "audience": "New customers", "platform": "Instagram",
        "aspect": "9:16", "target_length_seconds": 20,
        "must_keep": [{"clip": "intro.mp4", "start": 1, "end": 3.5}, {"phrase": "Made by Zoë; by hand"}],
        "forbidden": [{"clip": "wide.mp4", "start": 4, "end": 5}],
        "caption_language": "French", "exact_spellings": ["Zoë", "Zing", "ACME  Works"],
        "music": {"source": "supplied files", "files": ["clips/bed.wav"]},
        "sfx": {"source": "none"}, "reference_match": "pacing only",
    }


def scripted_answers():
    return '\n'.join([
        "Meet the maker", "New customers", "Instagram", "9:16", "20",
        'intro.mp4 @ 0:01-0:03.5; "Made by Zoë; by hand"', "wide.mp4 @ 4-5",
        "French", "Zoë; Zing; ACME  Works", "supplied files: clips/bed.wav", "none", "pacing only", "",
    ])


class NoInput:
    def readline(self):
        raise AssertionError("A non-interactive run read stdin")


def test_scripted_stdin_answers_file_and_mcp_save_identical(project, tmp_path, monkeypatch):
    # Real entry point with piped stdin; no input(), TTY, or curses dependency.
    process = subprocess.run([sys.executable, "-m", "myzing.cli", "brief", "new", str(project)],
                             input=scripted_answers(), capture_output=True, text=True,
                             encoding="utf-8", timeout=30)
    assert process.returncode == 0, process.stderr
    assert "Six topics" in process.stdout and "I'd start here" in process.stdout
    assert "default:" in process.stdout
    expected = (project / "brief.json").read_bytes()
    imported = tmp_path / "saved.json"
    imported.write_bytes(expected)
    monkeypatch.setattr(sys, "stdin", NoInput())
    assert cli.main(["brief", "new", str(project), "--answers", json.dumps(answers())]) == 0
    assert (project / "brief.json").read_bytes() == expected
    assert cli.main(["brief", "new", str(project), "--brief", str(imported)]) == 0
    assert (project / "brief.json").read_bytes() == expected
    response = h_brief_save(str(project), answers())
    assert response["ok"] is True
    assert (project / "brief.json").read_bytes() == expected
    assert response["brief_path"] == str(project / "brief.json")


def test_skips_are_disclosed_and_equal_omitted_json(project, monkeypatch, capsys):
    questions = brief_questions()["questions"]
    fields = [f for q in questions for f in q["fields"]]
    assert len(questions) == 6
    assert [f["key"] for f in fields] == list(Brief().to_dict())[:-1]
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n" * len(fields)))
    assert cli.main(["brief", "new", str(project)]) == 0
    output = capsys.readouterr().out
    for field in fields:
        assert "[default: " + json.dumps(field["default"], ensure_ascii=False) + "]" in output
    saved = (project / "brief.json").read_bytes()
    assert json.loads(saved) == Brief().to_dict()
    assert cli.main(["brief", "new", str(project), "--answers", "{}"]) == 0
    assert (project / "brief.json").read_bytes() == saved


def test_resume_scan_move_and_other_cwd_preserve_answers(project, tmp_path, monkeypatch, capsys):
    brief = brief_api.save_brief(project, Brief.from_answers(answers()))
    path = project / "brief.json"
    saved, mtime = path.read_bytes(), path.stat().st_mtime_ns
    project_api.scan_project(project)
    monkeypatch.setattr(sys, "stdin", NoInput())
    assert cli.main(["brief", "new", str(project), "--json"]) == 0
    assert path.read_bytes() == saved and path.stat().st_mtime_ns == mtime
    result = json.loads(capsys.readouterr().out)
    assert result["brief"]["caption_language"] == "French"
    assert result["brief"]["exact_spellings"] == ["Zoë", "Zing", "ACME  Works"]
    assert result["brief"]["must_keep"] == brief.must_keep
    moved = tmp_path / "moved project"
    shutil.move(str(project), moved)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["brief", "show", str(moved), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["brief"] == brief.to_dict()
    assert not any("Missing supplied music" in s for s in result["recommendation"]["missing"])


def test_invalid_interactive_answer_reasked_in_place(project, monkeypatch, capsys):
    lines = scripted_answers().splitlines()
    lines.insert(3, "4:3")
    lines.insert(6, "intro.mp4 @ 0-99")
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n".join(lines) + "\n"))
    assert cli.main(["brief", "new", str(project)]) == 0
    output = capsys.readouterr().out
    assert "aspect: choose 9:16, 1:1, or 16:9" in output
    assert "ends at 8 s" in output
    assert output.count("Please try that answer again") == 2
    assert brief_api.load_brief(project / "brief.json").exact_spellings == answers()["exact_spellings"]


@pytest.mark.parametrize("bad,message", [
    ({"aspect": "4:3"}, "aspect"), ({"target_length_seconds": 0}, "target_length_seconds"),
    ({"target_length_seconds": 61}, "60 seconds"), ({"target_length_seconds": True}, "finite number"),
    ({"target_length_seconds": float("nan")}, "finite number"),
    ({"target_length_seconds": 10 ** 500}, "finite number"),
    ({"target_length_seconds": "20"}, "finite number"), ({"audience": None}, "audience"),
    ({"purpose": ""}, "purpose"), ({"caption_language": []}, "caption_language"),
    ({"exact_spellings": "Zing"}, "exact_spellings"), ({"exact_spellings": [None]}, "exact_spellings"),
    ({"music": "none"}, "music"), ({"music": {"source": "download"}}, "music.source"),
    ({"music": {"source": "supplied files"}}, "at least one file"),
    ({"sfx": {"source": "none", "files": ["hit.wav"]}}, "cannot include files"),
    ({"reference_match": "close"}, "reference_match"), ({"typo": 1}, "Unknown answer"),
    ({"must_keep": [{"clip": "unknown", "start": 0, "end": 1}]}, "unknown clip"),
    ({"must_keep": [{"clip": "intro.mp4", "start": 3, "end": 1}]}, "start < end"),
    ({"must_keep": [{"clip": "intro.mp4", "start": 0, "end": 9}]}, "ends at 8 s"),
    ({"must_keep": [{"clip": "bed.wav", "start": 0, "end": 1}]}, "no video stream"),
    ({"must_keep": [{"phrase": ""}]}, "phrase"), ({"must_keep": ["quote"]}, "object"),
    ({"must_keep": [{"phrase": "x", "guess": 1}]}, "quoted phrase"),
    ({"must_keep": [{"phrase": "x"}], "forbidden": [{"phrase": "x"}]}, "overlaps"),
    ({"must_keep": [{"clip": "intro.mp4", "start": 0, "end": 2}],
      "forbidden": [{"clip": "clips/intro.mp4", "start": 1, "end": 3}]}, "overlaps"),
    ([], "JSON object"),
])
def test_invalid_noninteractive_rejected_without_overwrite(project, monkeypatch, capsys, bad, message):
    brief_api.save_brief(project, Brief())
    saved = (project / "brief.json").read_bytes()
    monkeypatch.setattr(sys, "stdin", NoInput())
    assert cli.main(["brief", "new", str(project), "--answers", json.dumps(bad)]) == 1
    assert message in capsys.readouterr().err
    response = h_brief_save(str(project), bad)
    assert response["ok"] is False and message in response["error"]
    assert (project / "brief.json").read_bytes() == saved


def test_version_and_roundtrip_validation():
    brief = Brief.from_answers(answers())
    assert Brief.from_dict(brief.to_dict()) == brief
    for version in (None, True, "1", 2):
        with pytest.raises(BriefError, match="version"):
            Brief.from_dict({**brief.to_dict(), "version": version})
    with pytest.raises(BriefError, match="Incomplete saved brief"):
        Brief.from_dict({"version": 1})


def test_atomic_failure_and_interrupted_interview_leave_previous_brief(project, monkeypatch, capsys):
    brief_api.save_brief(project, Brief())
    before = (project / "brief.json").read_bytes()

    def fail_replace(*args):
        raise OSError("simulated interrupted replacement")

    monkeypatch.setattr(brief_api.os, "replace", fail_replace)
    with pytest.raises(OSError, match="interrupted"):
        brief_api.save_brief(project, Brief(purpose="replacement"))
    assert not list(project.glob(".brief-*.tmp"))
    assert not (project / ".project.lock").exists()
    monkeypatch.setattr(sys, "stdin", io.StringIO("first answer\n"))
    assert cli.main(["brief", "new", str(project), "--restart"]) == 1
    assert "Input ended" in capsys.readouterr().err
    assert (project / "brief.json").read_bytes() == before


def test_colocated_inventory_does_not_scan_brief_or_temporary_files(tmp_path):
    project_api.init_project("uoink:example", tmp_path, tmp_path)
    brief_api.save_brief(tmp_path, Brief())
    (tmp_path / ".brief-interrupted.tmp").write_text("partial", encoding="utf-8")
    assert project_api.scan_project(tmp_path).assets == []


def test_recommendation_has_concrete_facts_and_named_gaps(project):
    result = recommend(project, Brief.from_answers(answers()))
    assert "Shorten the 20 s target or add footage first" in result["summary"]
    basis = " ".join(result["basis"])
    gaps = " ".join(result["missing"])
    assert "5 assets; 3 probed video clips, 2 currently usable" in basis
    assert "1 landscape" in basis and "1 portrait" in basis
    assert "16 source seconds" in basis and "range 8-8 s" in basis
    assert "missing.mp4" in gaps and "notes.xyz" in gaps
    assert "No usable clip shorter than 3 s" in gaps
    assert "16 s of usable source duration for a 20 s target" in gaps
    assert "No studied reference" in gaps and "phrase locations" in gaps
    assert "safe crop" in gaps


@pytest.mark.parametrize("attachment", ["inline", "wrapped", "path"])
def test_reference_pace_captions_confidence_and_warnings(project, attachment):
    breakdown = {"schema_version": 1, "meta": {"duration": 4},
                 "shots": [{"start": 0, "end": 1}, {"start": 1, "end": 4}],
                 "captions": [{"position": "lower", "words_visible": 2, "all_caps": True, "confidence": .6}],
                 "warnings": ["OCR coverage partial"]}
    manifest = project_api.load_project(project)
    if attachment == "path":
        (project / "reference.json").write_text(json.dumps(breakdown), encoding="utf-8")
        manifest.reference.study = {"breakdown_path": "reference.json"}
    else:
        manifest.reference.study = breakdown if attachment == "inline" else {"breakdown": breakdown, "state": "done"}
    project_api._save(project, manifest)
    result = recommend(project, Brief())
    basis, gaps = " ".join(result["basis"]), " ".join(result["missing"])
    assert "2 measured shots; median shot 2 s" in basis
    assert "lower 1" in basis and "median 2 words visible" in basis and "confidence 0.60" in basis
    assert "OCR coverage partial" in gaps and "Exact font" in gaps
    assert "2 s median shot" in result["summary"]
    exact = recommend(project, Brief(reference_match="exact"))
    assert "cannot establish an exact match" in exact["summary"]


@pytest.mark.parametrize("study", [
    {"breakdown_path": "missing.json"}, {"state": "running"},
    {"meta": {}, "shots": [{"start": 2, "end": 1}]}, {"meta": {}, "captions": [None]},
    {"schema_version": 99, "meta": {}},
])
def test_unavailable_or_invalid_study_remains_unknown(project, study):
    manifest = project_api.load_project(project)
    manifest.reference.study = study
    project_api._save(project, manifest)
    result = recommend(project, Brief())
    assert "unknown" in " ".join(result["missing"])
    assert not any("measured shots" in s for s in result["basis"])


def test_changed_media_excluded_and_missing_audio_named(project):
    (project / "clips" / "intro.mp4").write_bytes(b"changed, needs scan")
    brief = Brief(music={"source": "supplied files", "files": ["absent.wav"]})
    result = recommend(project, brief)
    assert "8 source seconds" in " ".join(result["basis"])
    gaps = " ".join(result["missing"])
    assert "needs a scan: clips/intro.mp4" in gaps
    assert "Missing supplied music file: absent.wav" in gaps


def test_mcp_defaults_and_errors_do_not_need_sdk(project):
    result = h_brief_questions()
    assert result["ok"] and result["questions"] == brief_questions()["questions"]
    assert h_brief_save("", {})["ok"] is False
    assert "zing project init" in h_brief_save(str(project / "absent"), {})["error"]


def test_json_output_does_not_prompt_and_missing_files_fail_clearly(project, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", NoInput())
    assert cli.main(["brief", "new", str(project), "--json"]) == 1
    assert "Supply --answers" in capsys.readouterr().err
    assert cli.main(["brief", "show", str(project)]) == 1
    assert "No brief" in capsys.readouterr().err
    assert cli.main(["brief", "new", str(project), "--answers", "{"]) == 1
    assert "invalid JSON" in capsys.readouterr().err
    assert not (project / "brief.json").exists()


def test_existing_new_does_not_overwrite_a_concurrent_save(project):
    brief_api.save_brief(project, Brief(purpose="another writer"))
    with pytest.raises(BriefError, match="saved while you were answering"):
        brief_api.save_brief(project, Brief(purpose="late interview"), replace=False)
    assert brief_api.load_brief(project / "brief.json").purpose == "another writer"


def test_must_keep_time_shortage_counts_overlaps_once(project):
    brief = Brief(target_length_seconds=5, must_keep=[
        {"clip": "intro.mp4", "start": 0, "end": 4},
        {"clip": "intro.mp4", "start": 2, "end": 6},
    ])
    result = recommend(project, brief_api.validate_for_project(project, brief))
    assert "require 6 s at original speed" in " ".join(result["missing"])


def test_answers_accept_the_version_shown_in_help():
    from myzing.brief.models import Brief, BriefError

    assert Brief.from_answers({"version": 1}) == Brief.from_answers({})
    with pytest.raises(BriefError, match="version must be 1"):
        Brief.from_answers({"version": 2})


def test_piped_non_ascii_answers_decode_as_utf8(tmp_path):
    import subprocess
    import sys

    probe = ("import sys; from myzing import cli; cli.main(['--version']); "
             "sys.stdout.write(sys.stdin.encoding)")
    env = {k: v for k, v in __import__("os").environ.items() if k != "PYTHONUTF8"}
    env["PYTHONIOENCODING"] = ""
    result = subprocess.run([sys.executable, "-c", probe], input="Zoë".encode("utf-8"),
                            capture_output=True, env=env, timeout=60)
    assert result.stdout.decode("utf-8").strip().endswith("utf-8")
