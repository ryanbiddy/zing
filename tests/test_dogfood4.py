"""DOGFOOD4: speechless target fills and clip-folder disclosures."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing.director.models import ClipStudy, PlanningShortage
from myzing.director.selection import candidates, choose, envelope
from myzing.schemas import Breakdown, Shot, VideoMeta, Word
from myzing.style_recipe import build_style_recipe


def short_studies(words=False):
    return [ClipStudy(str(i), f"{i}.mp4", str(i) * 64, 3, "ready",
                      shots=[Shot(0, 0, 3)], words=[Word("Whole.", 0, 3)] if words else [])
            for i in range(3)]


def style():
    return envelope(build_style_recipe(Breakdown(
        VideoMeta("reference", "file", duration=4, fps=30), shots=[Shot(0, 0, 4)])))


@pytest.mark.parametrize("target", [4, 7.5, 8])
def test_short_speechless_shots_fill_target_deterministically(target):
    studies = short_studies()
    pool, required = candidates(studies, {}, {}, style(), target)
    evidence = {}
    chosen = choose(pool, required, studies, style(), target, 30, 17, timing_evidence=evidence)
    assert chosen == choose(pool, required, studies, style(), target, 30, 17)
    assert set(chosen) == set("ABC")
    for label, seq in chosen.items():
        assert sum(c.duration for c in seq) == pytest.approx(target)
        assert len({c.content for c in seq}) == len(seq)
        assert all(c.start == 0 and .2 <= c.end <= 3 for c in seq)
        assert evidence[label]["median_shot_seconds"]["distance_outside_seconds"] > 0


def test_speechless_finish_keeps_constraints_and_never_splits_spoken_clauses():
    studies = short_studies()
    keep = {"0": [(2, 3)]}
    forbidden = {"1": [(0, 2)]}
    pool, required = candidates(studies, keep, forbidden, style(), 4)
    chosen = choose(pool, required, studies, style(), 4, 30, 17)
    for seq in chosen.values():
        assert any(c.asset_id == "0" and c.start <= 2 and c.end >= 3 for c in seq)
        assert all(c.start >= 2 for c in seq if c.asset_id == "1")
        assert sum(c.duration for c in seq) == pytest.approx(4)

    # Empty text after invalid ASR is not evidence of a speechless source.
    uncertain = short_studies()
    for study in uncertain:
        study.asr_repair = {"quarantined": [{"start": 0, "end": 0}]}
    pool, required = candidates(uncertain, {}, {}, style(), 4)
    with pytest.raises(PlanningShortage, match="edit_constraints"):
        choose(pool, required, uncertain, style(), 4, 30, 17)

    spoken = short_studies(words=True)
    pool, required = candidates(spoken, {}, {}, style(), 4)
    with pytest.raises(PlanningShortage, match="edit_constraints"):
        choose(pool, required, spoken, style(), 4, 30, 17)


def test_duplicate_silent_content_cannot_fill_missing_duration():
    studies = short_studies()
    for study in studies:
        study.sha256 = "same-source"
    pool, required = candidates(studies, {}, {}, style(), 4)
    with pytest.raises(PlanningShortage, match="edit_constraints"):
        choose(pool, required, studies, style(), 4, 30, 17)


def test_studio_discloses_stills_without_probing_them(tmp_path, monkeypatch):
    from myzing.studio.evidence import collect
    from myzing.studio.presentation import creator_summary

    for index in range(3):
        (tmp_path / f"{index}.JPG").write_bytes(b"not a video")
    monkeypatch.setattr("myzing.studio.evidence.cached_probe",
                        lambda *args: pytest.fail("stills must not be probed as videos"))
    facts = collect({"path": "b", "clips": str(tmp_path)})
    notice = "Skipped 3 still images; Studio cuts video clips."
    assert notice in facts["warnings"] and not facts["clips"]
    summary = creator_summary({"project": str(tmp_path / "out"), "warnings": facts["warnings"]}, {"path": "b"}, facts)
    assert notice in summary["notes"]


def test_stills_notice_survives_failures_and_many_shortages(tmp_path):
    from myzing.studio.presentation import creator_summary

    notice = "Skipped 3 still images; Studio cuts video clips."
    result = {"project": str(tmp_path), "warnings": [notice, notice, "variety limit", "blocked captions"],
              "result": {"failures": ["failed"], "shortages": [
                  {"code": code} for code in ("target_length", "distinct_edits", "edit_constraints", "audio_asset")]}}
    summary = creator_summary(result, {"path": "b"}, {"clips": [{"width": 640, "height": 360}]})
    assert len(summary["notes"]) == 5
    assert summary["notes"].count(notice) == 1
    assert "stopped" in summary["notes"][0]


@pytest.mark.parametrize("suffix", [".JPG", ".png", ".webp"])
def test_style_breakdown_refuses_explicit_still_before_any_probe(tmp_path, monkeypatch, suffix):
    from myzing.studio.evidence import collect

    path = tmp_path / ("photo" + suffix)
    path.write_bytes(b"not video")
    (tmp_path / "clip.mp4").write_bytes(b"also must not be probed")
    monkeypatch.setattr("myzing.studio.evidence.cached_probe", lambda *a: pytest.fail("probe before still refusal"))
    with pytest.raises(ValueError, match=f"Style breakdown needs a video; photo{suffix} is a still image."):
        collect({"path": "d", "source": str(path), "clips": str(tmp_path)})


def test_terminal_default_does_not_write_in_cwd(tmp_path, monkeypatch, zing_workspace):
    from myzing import storage
    from myzing.studio.flow import reserve_project

    cwd = tmp_path / "other-checkout"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    project = Path(reserve_project())
    assert project.parent == storage.resolve_workspace()
    assert list(cwd.iterdir()) == []


def test_screen_plan_default_does_not_write_in_cwd(tmp_path, monkeypatch, zing_workspace):
    from myzing import storage
    from myzing.screen import command

    cwd = tmp_path / "other-checkout"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    saved = []
    monkeypatch.setattr(command, "plan_screen", lambda video, **_: SimpleNamespace(warnings=[]))
    monkeypatch.setattr(command, "save_plan", lambda plan, out: saved.append(Path(out)) or out)
    assert command.run([str(tmp_path / "demo.mp4")]) == 0
    assert saved == [storage.resolve_workspace() / "screen" / "demo-screen.json"]
    assert list(cwd.iterdir()) == []

@pytest.mark.parametrize("measured_silence", [False, True])
def test_empty_transcript_needs_no_audio_or_measured_absence_of_speech(tmp_path, zing_workspace, measured_silence):
    from myzing.director.inventory import inventory
    from tools.plan_examples import example_project, write_json

    root, _, _ = example_project(tmp_path / "project")
    study_path = root / "breakdowns/take-0/breakdown.json"
    data = json.loads(study_path.read_text())
    data["words"] = []
    data["provenance"]["raw_mode"]["dead_air"] = [{"start": 0, "end": 8}]
    if measured_silence:
        data["provenance"]["vad"] = {"method": "fixture-measured-silence"}
        data["audio"]["speech_ratio"] = 0
    write_json(study_path, data)
    studies, _ = inventory(root)
    silent = next(s for s in studies if s.asset_id == "take-0")
    if measured_silence:
        assert silent.status == "ready" and silent.dead_air == []
        assert any("selection uses measured shots" in w for w in silent.warnings)
    else:
        assert silent.status == "needs_study"
        assert any("no validated words or measured absence of speech" in w for w in silent.warnings)
