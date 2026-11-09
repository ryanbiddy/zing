"""Long talking clips use sentence pauses and keep their estimated picks on resume."""

import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing.brief.api import load_brief
from myzing.director.models import ClipStudy, PlanningShortage
from myzing.director.moments import moments, sentences, suggest_moments
from myzing.director.selection import candidates, Envelope
from myzing.match import api
from myzing.match.state import read, write
from myzing.schemas import Breakdown, Shot, VideoMeta, Word


def talk(duration=300., gaps=(.8, 1.1, 1.5)):
    words, cursor, i = [], .1, 0
    while cursor + 2 < duration:
        for text in ("Friction", "is", "a", "force", "between", "surfaces."):
            words.append(Word(text, round(cursor, 4), round(cursor + .2, 4)))
            cursor += .3
        cursor = words[-1].end + gaps[i % len(gaps)]
        i += 1
    return ClipStudy("take-0", "talk.mp4", "a" * 64, duration, "ready",
                     words=words, shots=[Shot(0, 0., duration)])


def style():
    return Envelope(3.1, 2., None, 1, 0., "lower", {"shot_durations": [2., 3.1, 4.2]})


def test_sentence_pauses_allow_complete_moments():
    clip = talk()
    rows = suggest_moments(clip)
    assert len(rows) == 3
    speech = sentences(clip.words)
    for row in rows:
        assert .65 * 22 <= row["end"] - row["start"] <= 22
        assert row["start"] in {s.start for s in speech}
        assert row["end"] in {s.end for s in speech}
        assert any("Inter-sentence pauses total" in r for r in row["reasons"])
        assert not any("word gap >=0.6s inside" in r for r in row["reasons"])
        duration = row["end"] - row["start"]
        inside = [w for w in clip.words if row["start"] <= w.start and w.end <= row["end"]]
        density = sum(w.end - w.start for w in inside) / duration
        pause = sum(b.start - a.end for a, b in zip(inside, inside[1:]) if b.start - a.end >= .6)
        assert row["score"] == round(.3 * density + .25 * duration / 22 + .3 + .05 - .02 * pause / 22, 6)


@pytest.mark.parametrize("gap", [.8, 1.5, 1.999, 2., 2.1])
def test_sentence_pause_limit(gap):
    assert bool(suggest_moments(talk(45, (gap,)))) == (gap < 2)


def test_two_second_pause_is_not_admitted_by_float_roundoff():
    clip = ClipStudy("take-0", "talk.mp4", "a" * 64, 10., "ready",
                     words=[Word("Hello.", 0., .8), Word("Friction is a force.", 2.8, 10.)],
                     shots=[Shot(0, 0., 10.)])
    assert suggest_moments(clip, target=12) == []


def test_pause_inside_sentence_still_blocks():
    clip = talk(45)
    for i in range(5, len(clip.words), 6):
        clip.words[i].text = "surfaces"
    clip.words[-1].text = "surfaces."
    assert suggest_moments(clip, target=60) == []


@pytest.mark.parametrize("blocked", ["dead_air", "quarantined", "repairs", "forbidden"])
def test_excluded_sentence_pauses_still_block(blocked):
    clip = talk(60)
    spans = [(a.end, b.start) for a, b in zip(clip.words, clip.words[1:]) if b.start - a.end >= .6]
    records = [{"start": a, "end": b} for a, b in spans]
    if blocked == "dead_air":
        clip.dead_air = records
    elif blocked != "forbidden":
        clip.asr_repair[blocked] = records
    assert suggest_moments(clip, forbidden=spans if blocked == "forbidden" else ()) == []


def test_pause_free_suggestions_keep_scores_and_source_order():
    clip = talk(60, (.1,))
    rows = suggest_moments(clip)
    assert rows and rows[0]["start"] == .1
    for row in rows:
        inside = [w for w in clip.words if row["start"] <= w.start and w.end <= row["end"]]
        duration = row["end"] - row["start"]
        density = sum(w.end - w.start for w in inside) / duration
        assert row["score"] == round(.3 * density + .25 * duration / 22 + .3 + .05, 6)
        assert not any("Inter-sentence" in r for r in row["reasons"])


@pytest.mark.parametrize("suggestions", [False, True])
def test_shortage_remedy_names_the_study(tmp_path, suggestions):
    clip = talk(gaps=(.8,) if suggestions else (2.,))
    clip.study_path = str(tmp_path / "project with spaces" / "breakdowns" / "talk" / "breakdown.json")
    with pytest.raises(PlanningShortage) as caught:
        candidates([clip], {}, {}, style(), 22)
    shortage = caught.value.shortage
    assert shortage.code == "long_source_needs_moment"
    assert bool(shortage.suggestions) == suggestions
    assert f'zing moments "{clip.study_path}" --target 22 --json' in shortage.remedy
    if suggestions:
        assert "Review these Estimated suggestions" in shortage.remedy
        assert "No moment was selected automatically" in shortage.remedy
    else:
        assert "Review these Estimated suggestions" not in shortage.remedy
        assert "No complete-sentence moment near 22 s was found in talk.mp4." in shortage.remedy
        assert "Trim the clip to the part you want, or add a must_keep span to brief.json." in shortage.remedy


@pytest.fixture
def project(tmp_path, monkeypatch, zing_workspace):
    from tools.plan_examples import example_project
    root, _, _ = example_project(tmp_path / "project")
    write(root / "match-state.json", {"version": 1, "steps": {}})
    reference = tmp_path / "reference.mp4"
    reference.write_bytes(b"reference")
    clip = talk()
    manifest = read(root / "project.json")
    manifest["assets"] = manifest["assets"][:1]
    manifest["assets"][0]["probe"]["duration"] = clip.duration
    manifest["reference"].update(value=str(reference), kind="file")
    write(root / "project.json", manifest)
    source = root / "clips" / "take-0.mp4"
    path = root / "breakdowns" / "take-0" / "breakdown.json"
    b = Breakdown.from_dict(read(path))
    b.meta.duration, b.words, b.shots = clip.duration, clip.words, clip.shots
    b.provenance["raw_mode"]["keepers"] = []
    write(path, b.to_dict())

    def study(source, workspace, **options):
        source = Path(source)
        path = root / "breakdowns" / source.stem / "breakdown.json"
        if not options.get("raw"):
            path = Path(workspace) / "breakdowns" / source.stem / "breakdown.json"
            b = Breakdown(VideoMeta(str(source), "file", duration=22., fps=30, width=320, height=180,
                                    media_path=str(source)), shots=[Shot(0, 0., 22.)],
                          provenance={"source_sha256": api.projects.hash_file(source)})
            write(path, b.to_dict())
        return {"path": str(path), "sha256": api.projects.hash_file(path), "media": str(source),
                "slug": source.stem, "geometry": None, "warnings": [], "outputs": [str(path)]}

    def render(plan, video, **options):
        video.write_bytes(b"synthetic render")
        return SimpleNamespace(warnings=[], audio_measurements=None)

    monkeypatch.setattr(api, "init", lambda *a: api.projects.load_project(root))
    monkeypatch.setattr(api, "capabilities", lambda: dict(fonts=False, audio=False, color=False, layout=False))
    monkeypatch.setattr(api, "_study", study)
    monkeypatch.setattr(api, "_audio", lambda *a: {"outputs": [], "warnings": []})
    monkeypatch.setattr(api, "_inspect", lambda *a: {"outputs": [], "warnings": []})
    monkeypatch.setattr(api.evidence, "decode", lambda *a: {"duration": 22., "full_decode": True})
    monkeypatch.setattr("myzing.match.preflight.check", lambda *a, **k: {"problems": [], "warnings": []})
    monkeypatch.setattr("myzing.layout.framing.analyze_subjects", lambda *a, **k: ([], []))
    monkeypatch.setattr("myzing.render.composition.render_composition", render)
    monkeypatch.setattr("subprocess.run", lambda *a, **k: pytest.fail("No decoder or model is needed"))
    answers = dict(target_length_seconds=22, caption_mode="none", picture_crop="off", aspect="16:9", short_side=180)
    return SimpleNamespace(root=root, source=source, study=path, reference=reference, answers=answers)


def match(project, **options):
    return api.match(str(project.reference), str(project.root / "clips"), str(project.root), **options)


@pytest.mark.parametrize("saved_brief", [False, True])
def test_auto_moment_is_top_pick_disclosed_and_reused(project, monkeypatch, saved_brief):
    top = moments(str(project.study))["suggestions"][0]
    result = match(project, answers=project.answers, auto_moment=True)
    assert result["status"] == "ready", result
    pick, = result["auto_moments"]
    assert pick["must_keep"] == top["must_keep"] == load_brief(project.root / "brief.json").must_keep
    assert pick["first_sentence"] == top["first_sentence"]
    assert f"{top['end'] - top['start']:.1f} s moment from take-0.mp4" in pick["disclosure"]
    assert f'zing moments "{project.study}"' in pick["disclosure"]
    assert pick["disclosure"] in (project.root / "comparison.md").read_text(encoding="utf-8")
    state = read(project.root / "match-state.json")
    assert state["auto_moments"]["picks"] == [{**pick, "study_path": project.study.relative_to(project.root).as_posix()}]
    for path in (project.root / "director").glob("plan-?.json"):
        assert any(c["asset_id"] == "take-0" and c["src_in"] <= top["start"] and c["src_out"] >= top["end"]
                   for c in read(path)["clips"])
    monkeypatch.setattr("myzing.director.moments.suggest_moments", lambda *a, **k: pytest.fail("Saved picks must be reused"))
    resumed = match(project, auto_moment=True, resume=True, **({} if saved_brief else {"answers": project.answers}))
    assert resumed["status"] == "ready", resumed
    assert resumed["auto_moments"] == [pick]
    assert "director" in resumed["reused_steps"]


def test_auto_moment_false_keeps_shortage(project):
    result = match(project, answers=project.answers, auto_moment=False)
    assert result["status"] == "shortage"
    assert result["shortages"][0]["code"] == "long_source_needs_moment"
    assert not load_brief(project.root / "brief.json").must_keep
    assert not read(project.root / "match-state.json").get("auto_moments")


def test_auto_moment_without_suggestions_keeps_remedy(project):
    data = read(project.study)
    for word in data["words"]:
        word["text"] = word["text"].replace(".", "")
    write(project.study, data)
    result = match(project, answers=project.answers, auto_moment=True)
    assert result["status"] == "shortage", result
    assert not result["auto_moments"]
    shortage, = result["shortages"]
    assert not shortage["suggestions"]
    assert "No complete-sentence moment near 22 s was found in take-0.mp4." in shortage["remedy"]
    assert str(project.study) in shortage["remedy"]


def test_two_long_clips_fit_one_edit_and_can_switch_on_resume(project):
    manifest = read(project.root / "project.json")
    source = project.source.with_name("take-1.mp4")
    asset = {**manifest["assets"][0], "id": "take-1", "path": "clips/take-1.mp4", "original_path": "clips/take-1.mp4",
             "sha256": api.projects.hash_file(source), "size": source.stat().st_size, "mtime_ns": source.stat().st_mtime_ns}
    manifest["assets"].append(asset)
    write(project.root / "project.json", manifest)
    data = read(project.study)
    data["meta"].update(source_url=str(source), media_path=str(source))
    data["provenance"]["source_sha256"] = asset["sha256"]
    second = project.study.parent.with_name("take-1") / "breakdown.json"
    write(second, data)
    result = match(project, answers=project.answers, auto_moment=True)
    assert result["status"] == "ready", result
    assert len(result["auto_moments"]) == 1
    assert "Left take-1.mp4 out of this edit" in result["moment_scope"]
    assert read(project.root / "match-state.json")["auto_moments"]["excluded"] == ["take-1"]
    assert read(project.root / "director" / "comparison.json")["excluded_assets"] == ["take-1"]
    resumed = match(project, resume=True, auto_moment=True)
    assert resumed["status"] == "ready", resumed
    assert resumed["auto_moments"] == result["auto_moments"]
    assert "director" in resumed["reused_steps"]
    brief = read(project.root / "brief.json")
    brief["must_keep"] = moments(str(second))["suggestions"][0]["must_keep"]
    write(project.root / "brief.json", brief)
    switched = match(project, resume=True, auto_moment=True)
    assert switched["status"] == "ready", switched
    assert "Left take-0.mp4 out of this edit" in switched["moment_scope"]
    assert load_brief(project.root / "brief.json").must_keep == brief["must_keep"]


def test_changed_study_invalidates_auto_pick(project):
    result = match(project, answers=project.answers, auto_moment=True)
    assert result["status"] == "ready", result
    old = read(project.root / "match-state.json")["auto_moments"]
    data = read(project.study)
    data["words"][0]["text"] = "Actually"
    write(project.study, data)
    resumed = match(project, resume=True, auto_moment=True)
    assert resumed["status"] == "ready", resumed
    assert read(project.root / "match-state.json")["auto_moments"]["key"] != old["key"]
    assert "director" not in resumed["reused_steps"]


def test_auto_moment_uses_studios_effective_target(project):
    from myzing.brief.api import save_brief
    from myzing.brief.models import Brief
    from myzing.director.inventory import inventory
    from myzing.match.moments import AutoMoments
    from myzing.match.state import Checkpoints
    save_brief(project.root, Brief.from_answers(project.answers))
    top = moments(str(project.study), target=60)["suggestions"][0]
    path = project.root / "director" / "comparison.json"
    write(path, {"brief": {**load_brief(project.root / "brief.json").to_dict(), "target_length_seconds": 60},
                 "inventory": [c.to_dict() for c in inventory(project.root)[0]]})
    automatic = AutoMoments(Checkpoints(project.root, False), {"take-0": {"path": str(project.study)}}, [])
    assert automatic.pick({"comparison_path": str(path), "summary": {"shortages": [
        {"code": "long_source_needs_moment", "asset_ids": ["take-0"], "suggestions": [top]}]}}, api.projects.load_project(project.root))
    assert not automatic.data["excluded"]
    assert automatic.data["picks"][0]["target"] == 60
    assert "--target 60" in automatic.data["picks"][0]["disclosure"]


@pytest.mark.parametrize("value", [None, 1, "false"])
def test_auto_moment_must_be_boolean(tmp_path, value):
    for method in (api.validate, api.match):
        with pytest.raises(ValueError, match="auto_moment must be a boolean"):
            method("reference.mp4", "clips", str(tmp_path / "project"), auto_moment=value)
    assert not (tmp_path / "project").exists()


def test_interrupted_replan_reuses_saved_pick(project, monkeypatch):
    from myzing.director import api as director
    original, calls = director.plan_drafts, []
    def fail_retry(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("interrupted replan")
        return original(*args, **kwargs)
    monkeypatch.setattr(director, "plan_drafts", fail_retry)
    failed = match(project, answers=project.answers, auto_moment=True)
    assert failed["status"] == "failed"
    assert len(failed["failures"]) == 1
    saved = read(project.root / "match-state.json")["auto_moments"]["picks"]
    assert len(saved) == 1
    monkeypatch.setattr(director, "plan_drafts", original)
    monkeypatch.setattr("myzing.director.moments.suggest_moments", lambda *a, **k: pytest.fail("Saved pick must survive a failed replan"))
    resumed = match(project, answers=project.answers, resume=True, auto_moment=True)
    assert resumed["status"] == "ready", resumed
    assert resumed["auto_moments"] == [{**p, "study_path": str(project.root / p["study_path"])} for p in saved]


def test_edited_brief_replaces_auto_pick(project):
    result = match(project, answers=project.answers, auto_moment=True)
    assert result["status"] == "ready", result
    alternative = moments(str(project.study))["suggestions"][1]
    brief = read(project.root / "brief.json")
    brief["must_keep"] = alternative["must_keep"]
    write(project.root / "brief.json", brief)
    result = match(project, resume=True, auto_moment=True)
    assert result["status"] == "ready", result
    assert not result["auto_moments"]
    assert load_brief(project.root / "brief.json").must_keep == alternative["must_keep"]


def test_moments_project_finds_study_and_deduplicates(project, zing_workspace, capsys):
    from myzing.cli import main
    assert main(["moments", str(project.source), "--json"]) == 1
    error = json.loads(capsys.readouterr().out)["error"]
    assert "found 0" in error and "--project DIR" in error
    for workspace in ([], ["--workspace", str(project.root)]):
        assert main(["moments", str(project.source), "--project", str(project.root), "--json", *workspace]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["study_path"] == str(project.study)
        assert data["suggestions"][0]["must_keep"][0]["clip"] == "take-0"


@pytest.mark.parametrize("flag,automatic", [([], True), (["--no-auto-moment"], False)])
def test_match_cli_auto_moment_and_disclosure(project, monkeypatch, capsys, flag, automatic):
    from myzing.match.command import run
    calls = []
    def execute(options, **kwargs):
        calls.append(options)
        return {"status": "ready", "summary": "1 of 1 render complete",
                "auto_moments": [{"disclosure": "Picked an estimated 21.4 s moment from take-0.mp4."}]}
    monkeypatch.setattr("myzing.match.command.execute", execute)
    assert run([str(project.reference), "--clips", str(project.source.parent), "--out", str(project.root),
                "--answers", "{}", *flag]) == 0
    assert calls[0]["auto_moment"] is automatic
    assert "Picked an estimated 21.4 s moment" in capsys.readouterr().out


def test_mcp_keeps_manual_moment_choice(project):
    from myzing.mcp_server import h_match_start, h_zing_moments
    assert inspect.signature(api.match).parameters["auto_moment"].default is False
    assert "auto_moment" not in inspect.signature(h_match_start).parameters
    assert h_zing_moments(str(project.study))["suggestions"]


def test_studio_reference_path_enables_auto_moment(project, monkeypatch):
    from myzing.studio.execute import run_confirmed
    calls = []
    answers = dict(path="a", project=str(project.root), reference=str(project.reference),
                   clips=str(project.source.parent), captions="none", music={})
    monkeypatch.setattr("myzing.studio.execute.next_step", lambda a: {
        "status": "plan", "answers": answers, "plan": {"title": "Match", "warnings": [], "evidence": {}}})
    monkeypatch.setattr("myzing.studio.execute.brief_answers", lambda a: project.answers)
    monkeypatch.setattr("myzing.study.speech_models.prepare", lambda *a, **k: None)
    def execute(options, **kwargs):
        calls.append(options)
        return {"status": "ready"}
    monkeypatch.setattr("myzing.match.jobs.execute", execute)
    assert run_confirmed(answers)["ok"]
    assert calls[0]["auto_moment"] is True
