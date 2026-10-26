"""Long interviews: bounded choice, explicit scope, and honest audio coverage."""
import hashlib
import json
import random
from pathlib import Path

import pytest

from myzing.brief.models import Brief
from myzing.director.continuity import clauses
from myzing.director.models import ClipStudy, PlanningShortage
from myzing.director.moments import moments, suggest_moments
from myzing.director.selection import candidates, choose, constraints, Envelope, MAX_CANDIDATES
from myzing.schemas import Breakdown, Shot, VideoMeta, Word


def interview(duration=2700., cameras=False):
    rng = random.Random(451)
    words, cursor, sentence = [], .1, 0
    while cursor + 7 < duration:
        count = rng.randint(6, 16)
        for i in range(count):
            text = f"line{sentence}" if i == 0 else "spoken"
            if i == count - 1:
                text = "clearly."
            words.append(Word(text, round(cursor, 4), round(cursor + .3, 4)))
            cursor += .4
        sentence += 1
    shots = ([Shot(i, float(s), min(duration, s + 20.)) for i, s in enumerate(range(0, int(duration), 20))]
             if cameras else [Shot(0, 0., duration)])
    return ClipStudy("take-0", "interview.mp4", "a" * 64, duration, "ready", words=words, shots=shots)


def style():
    return Envelope(3.1, 2., None, 1, 0., "lower",
                    {"shot_durations": [2., 3.4, 2.9, 3.1, 4.2, 2.6, 3.8]})


def conversational_interview(duration):
    clip = interview(duration)
    for word in clip.words:
        if word.text.startswith("line"):
            sentence = int(word.text[4:])
            if sentence % 2:
                word.text = ("And", "But", "So")[(sentence // 2) % 3]
    return clip


def test_conversational_interview_produces_eight_bounded_moments():
    clip = conversational_interview(600)
    speech = clauses(clip.words)
    sentences = sum(w.text.endswith(".") for w in clip.words)
    assert len(speech) == (sentences + 1) // 2
    assert all(c.complete and c.end - c.start <= 20 for c in speech)
    rows = suggest_moments(clip, target=30, top=8)
    assert len(rows) == 8
    assert all(19.5 <= r["end"] - r["start"] <= 30 for r in rows)
    assert all(r["start"] in {c.start for c in speech} and r["end"] in {c.end for c in speech} for r in rows)
    assert all(a["end"] <= b["start"] or b["end"] <= a["start"]
               for i, a in enumerate(rows) for b in rows[i+1:])


def test_conversational_selection_constraints_and_captions_share_boundaries():
    from types import SimpleNamespace
    from myzing.director.plans import captions_for
    from myzing.style_recipe import build_style_recipe

    clip = conversational_interview(60)
    speech = clauses(clip.words)
    selected_clause = speech[len(speech) // 2]
    brief = Brief(target_length_seconds=22, must_keep=[{
        "clip": clip.asset_id, "start": selected_clause.start + .2, "end": selected_clause.end - .2}])
    manifest = SimpleNamespace(assets=[SimpleNamespace(id=clip.asset_id, path=clip.path,
                                                       original_path=clip.path, previous_paths=[])])
    keep, forbidden = constraints(brief, manifest, [clip])
    assert keep[clip.asset_id] == [(selected_clause.start, selected_clause.end)]
    pool, required = candidates([clip], keep, forbidden, style(), 22)
    assert pool and all(c.dangling_clauses == 0 for c in pool if c.word_count)
    selected = choose(pool, required, [clip], style(), 22, 30, 0)
    assert selected
    recipe = build_style_recipe(Breakdown(VideoMeta("fixture", "file", duration=clip.duration),
                                         words=clip.words, shots=clip.shots))
    for sequence in selected.values():
        assert any(c.start <= selected_clause.start and c.end >= selected_clause.end for c in sequence)
        captions = captions_for(sequence, [clip], style(), recipe, None, brief)
        assert captions
        assert all(c.text in {s.text for s in speech} and c.end - c.start <= 20 for c in captions)


@pytest.mark.parametrize("cameras", [False, True])
def test_long_source_focus_contains_choices_and_respects_forbidden(cameras):
    from types import SimpleNamespace
    clip = interview(cameras=cameras)
    brief = Brief(target_length_seconds=22, must_keep=[{"phrase": "line300 spoken"}],
                  forbidden=[{"clip": "take-0", "start": 1280., "end": 1285.}])
    manifest = SimpleNamespace(assets=[SimpleNamespace(id="take-0", path=clip.path, original_path=clip.path, previous_paths=[])])
    keep, forbidden = constraints(brief, manifest, [clip])
    windows = {}
    pool, required = candidates([clip], keep, forbidden, style(), 22, search_windows=windows)
    assert 0 < len(pool) <= MAX_CANDIDATES
    window = windows[clip.asset_id]
    assert window["label"] == "Measured" and "whole interview was not searched" in window["text"]
    assert window["start"] <= keep[clip.asset_id][0][0] - 33
    assert window["end"] >= keep[clip.asset_id][-1][1] + 33
    assert window["end"] - window["start"] < 90
    assert all(window["start"] <= c.start < c.end <= window["end"] for c in pool)
    assert all(not (c.start < b and c.end > a) for c in pool for a, b in forbidden[clip.asset_id])
    selected = choose(pool, required, [clip], style(), 22, 30, 0)
    assert selected
    assert all(window["start"] <= c.start < c.end <= window["end"] for seq in selected.values() for c in seq)


def test_long_source_requires_explicit_choice_and_suggestions_roundtrip():
    clip = interview()
    with pytest.raises(PlanningShortage) as caught:
        candidates([clip], {}, {}, style(), 22)
    failure = caught.value.shortage
    assert failure.code == "long_source_needs_moment"
    assert len(failure.suggestions) == 3
    assert "No moment was selected automatically" in failure.remedy
    for row in failure.suggestions:
        assert row["label"] == "Estimated" and row["reasons"]
        brief = Brief.from_dict({**Brief().to_dict(), "must_keep": row["must_keep"]})
        assert brief.must_keep == row["must_keep"]
        assert row["end"] - row["start"] <= 22


@pytest.mark.parametrize("expand_timing", [False, True])
def test_short_clip_pool_unchanged(expand_timing):
    clip = interview(60)
    windows = {}
    pool, required = candidates([clip], {}, {}, style(), 22, expand_timing=expand_timing, search_windows=windows)
    assert not windows and not required
    # Golden hashes captured from main e58af7e's candidate implementation.
    payload = json.dumps([c.to_dict() for c in pool], sort_keys=True).encode()
    expected = {False: "39497da63ca58c8b6423fc59c47c98a7ee3daa17a28250ac35be7b67ac423308", True: "94f7536dd5dcd91901203d395cc07a266dc47774f6599237d31080a4beac8e5f"}
    assert hashlib.sha256(payload).hexdigest() == expected[expand_timing]


def test_moments_reject_dead_air_incomplete_clauses_and_exclusions():
    clip = interview(120)
    clip.dead_air = [{"start": 20., "end": 22.}]
    clip.words[-1].text = "because"
    forbidden = [(40., 55.)]
    rows = suggest_moments(clip, target=15, top=10, forbidden=forbidden)
    assert rows and rows == suggest_moments(clip, target=15, top=10, forbidden=forbidden)
    complete = clauses(clip.words)
    for row in rows:
        assert row["start"] in {c.start for c in complete if c.complete}
        assert row["end"] in {c.end for c in complete if c.complete}
        assert all(not (row["start"] < b and row["end"] > a) for a, b in [(20, 22), *forbidden])
    assert all(a["end"] <= b["start"] or b["end"] <= a["start"]
               for i, a in enumerate(rows) for b in rows[i+1:])


@pytest.mark.parametrize("target,top", [(0, 3), (float("nan"), 3), (61, 3), (22, 0), (22, True)])
def test_moments_invalid_arguments(target, top):
    with pytest.raises(ValueError):
        suggest_moments(interview(60), target=target, top=top)


def save_study(tmp_path):
    clip = interview(120)
    source = tmp_path / "interview.mp4"
    source.write_bytes(b"synthetic source")
    b = Breakdown(VideoMeta(str(source), "file", duration=120., media_path=str(source)),
                  words=clip.words, shots=clip.shots)
    study = tmp_path / "breakdown.json"
    study.write_text(b.to_json(), encoding="utf-8")
    return source, study


def test_moments_cli_json_and_mcp_schema(tmp_path, capsys):
    from myzing.cli import main
    source, study = save_study(tmp_path)
    assert main(["moments", str(study), "--target", "22", "--top", "3", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] and data["version"] == 1 and len(data["suggestions"]) == 3
    assert {"start", "end", "text", "score", "reasons", "must_keep", "label"} <= data["suggestions"][0].keys()
    assert data["suggestions"][0]["must_keep"][0]["clip"] == str(source.resolve())
    from myzing.mcp_server import h_zing_moments
    assert h_zing_moments(str(study))["suggestions"] == data["suggestions"]
    assert not h_zing_moments(str(study), target=-1)["ok"]


@pytest.mark.skipif(not __import__("importlib.util", fromlist=["find_spec"]).find_spec("mcp"), reason='mcp SDK not installed (pip install "myzing[mcp]")')
def test_moments_wire_schema(client):
    tools = client.send("tools/list", {})["tools"]
    tool = next(t for t in tools if t["name"] == "zing_moments")
    schema = tool["inputSchema"]
    assert schema["required"] == ["source"]
    assert schema["properties"]["target"]["default"] == 22
    assert schema["properties"]["top"]["default"] == 3


def test_audio_drift_inventory(tmp_path, zing_workspace):
    from tools.plan_examples import example_project, write_json
    from myzing.director.inventory import inventory
    from myzing.audio.models import AudioMap, Loudness, Segment, Tempo
    root, _, _ = example_project(tmp_path / "project")
    manifest = json.loads((root / "project.json").read_text())
    manifest["assets"][0]["probe"]["duration"] = 120.053
    write_json(root / "project.json", manifest)
    path = root / "breakdowns/take-0/breakdown.json"
    data = json.loads(path.read_text())
    data["meta"]["duration"] = 120.053
    data["shots"][-1]["end"] = 120.053
    data["provenance"]["raw_mode"]["dead_air"] = [{"start": 119., "end": 120.053}, {"start": 120.01, "end": 120.03}]
    write_json(path, data)
    audio = AudioMap(str(root / "clips/take-0.mp4"), 120., 48000, 600, False, Tempo(), [], [],
                     [Segment(119., 120., "silence", 1., "synthetic")], Loudness(None, None, None))
    write_json(path.parent / "audio-map.json", audio.to_dict())
    clip = inventory(root)[0][0]
    assert clip.status == "ready", clip.warnings
    assert any("0.053s" in w and "unmeasured" in w for w in clip.warnings)
    assert max(d["end"] for d in clip.dead_air) == 120.
    assert clip.dead_air[0]["original"]["end"] == 120.053
    assert len(clip.dead_air) == 2
    audio.duration_seconds = 120.2
    audio.segments = [Segment(119., 120.2, "silence", 1., "synthetic")]
    write_json(path.parent / "audio-map.json", audio.to_dict())
    clip = inventory(root)[0][0]
    assert clip.status == "ready" and clip.dead_air[-1]["end"] == 120.053
    assert clip.dead_air[-1]["original"]["end"] == 120.2
    audio.duration_seconds = 121.
    write_json(path.parent / "audio-map.json", audio.to_dict())
    clip = inventory(root)[0][0]
    assert clip.status == "needs_study"
    assert any("121.000s" in w and "120.053s" in w and "0.250s" in w for w in clip.warnings)


def test_long_match_skips_partial_audio_map(tmp_path, monkeypatch):
    from myzing.match.api import _audio
    from myzing.audio import api
    source, study = save_study(tmp_path)
    b = json.loads(study.read_text())
    b["meta"]["duration"] = 2700
    study.write_text(json.dumps(b))
    old = {"source": str(source), "truncated": True, "duration_seconds": 600}
    audio = tmp_path / "audio-map.json"
    audio.write_text(json.dumps(old))
    monkeypatch.setattr(api, "analyze", lambda *a, **k: pytest.fail("Must not decode a long audio map"))
    result = _audio({"path": str(study), "media": str(source)}, True)
    assert "unmeasured" in result["warnings"][0]
    assert not audio.exists()
    assert json.loads((tmp_path / "audio-map.partial.json").read_text()) == old


def test_focus_record_survives_plan_and_match_reports(tmp_path, zing_workspace, monkeypatch):
    from tools.plan_examples import example_project, write_json
    from myzing.director.api import plan_drafts
    from myzing.director.plans import REPORT_PREFIX
    from myzing.composition import Composition
    from myzing.layout import framing
    from myzing.match.evidence import report as match_report, markdown
    from myzing.style_recipe import StyleRecipe
    root, _, _ = example_project(tmp_path / "project")
    clip = interview()
    manifest = json.loads((root / "project.json").read_text())
    manifest["assets"] = manifest["assets"][:1]
    manifest["assets"][0]["probe"]["duration"] = clip.duration
    write_json(root / "project.json", manifest)
    path = root / "breakdowns/take-0/breakdown.json"
    b = Breakdown.from_json(path.read_text())
    b.meta.duration, b.words, b.shots = clip.duration, clip.words, clip.shots
    write_json(path, b.to_dict())
    write_json(root / "brief.json", Brief(target_length_seconds=22, caption_mode="none", picture_crop="off",
                                          must_keep=[{"phrase": "line300 spoken"}]).to_dict())
    monkeypatch.setattr(framing, "analyze_subjects", lambda *a, **k: ([], []))
    result = plan_drafts(root, root / "recipe.json", root / "plans")
    comparison = json.loads(Path(result["comparison_path"]).read_text())
    assert result["status"] == "ready", comparison["shortages"]
    windows = comparison["search_windows"]
    assert windows and result["summary"]["search_windows"] == windows
    for path in result["plans"].values():
        plan = Composition.from_json(Path(path).read_text())
        evidence = json.loads(next(w[len(REPORT_PREFIX):] for w in plan.warnings if w.startswith(REPORT_PREFIX)))
        assert evidence["search_windows"] == windows
        assert all(windows[c.asset_id]["start"] <= c.src_in < c.src_out <= windows[c.asset_id]["end"] for c in plan.clips)
        rendered = Breakdown(VideoMeta("render.mp4", "file", duration=22), shots=[Shot(0, 0, 22)])
        measured = match_report(StyleRecipe.from_json((root / "recipe.json").read_text()), rendered, {}, None, {}, plan)
        assert measured["search_windows"] == windows
        assert any("Measured:" in w and "whole interview was not searched" in w for w in measured["warnings"])
    text = markdown({"summary": "Synthetic report", "drafts": {}, "warnings": result["summary"]["warnings"]})
    assert "Measured:" in text and "Search focused on" in text


def test_first_line_heuristics_and_repaired_evidence_are_disclosed():
    clip = interview(120)
    clip.words[0].text = "Actually"
    clip.words[1].text = "42"
    first = clauses(clip.words)[0]
    next(w for w in clip.words if w.end == first.end).text = "questions?"
    rows = suggest_moments(clip)
    opening = next(r for r in rows if r["start"] == .1)
    assert sum("Opening heuristic:" in reason for reason in opening["reasons"]) == 3
    clip.asr_repair = {"repairs": [{"start": .1, "end": 1.2}]}
    assert all(r["start"] >= 1.2 for r in suggest_moments(clip))


@pytest.mark.parametrize("kept,full", [([(1., 2.), (2698., 2699.)], True),
                                      ([(400., 402.), (2300., 2302.)], False)])
def test_distant_keeps_report_actual_scope_and_capacity_remedy(kept, full):
    clip = interview()
    windows = {}
    with pytest.raises(PlanningShortage) as caught:
        candidates([clip], {clip.asset_id: kept}, {}, style(), 22, search_windows=windows)
    failure = caught.value.shortage
    assert failure.code == "planner_capacity"
    assert "2400" in failure.missing
    assert "Move or drop a must-keep" in failure.remedy and "split the job" in failure.remedy
    window = windows[clip.asset_id]
    assert "all your must-keep moments, including the time between them" in window["text"]
    if full:
        assert (window["start"], window["end"]) == (0., 2700.)
        assert "full clip (0:00.000-45:00.000)" in window["text"]
        assert "did not narrow" in window["text"]
        assert "whole interview was not searched" not in window["text"]
    else:
        assert 0 < window["start"] < kept[0][0] < kept[-1][1] < window["end"] < clip.duration
        assert "in one window" in window["text"]
        assert "whole interview was not searched" in window["text"]


@pytest.mark.parametrize("edge", ["start", "end"])
def test_focus_clamps_one_edge_and_remains_plannable(edge):
    clip = interview()
    clause = clauses(clip.words)[0 if edge == "start" else -1]
    keep = {clip.asset_id: [(clause.start, clause.end)]}
    windows = {}
    pool, required = candidates([clip], keep, {}, style(), 22, search_windows=windows)
    window = windows[clip.asset_id]
    assert window["start"] == 0 if edge == "start" else window["end"] == clip.duration
    assert window["end"] - window["start"] < 70
    assert "your must-keep moment;" in window["text"]
    assert "full clip" not in window["text"]
    assert all(window["start"] <= c.start < c.end <= window["end"] for c in pool)
    assert choose(pool, required, [clip], style(), 22, 30, 0)


def even_speech():
    # Binary-exact timestamps and identical clauses make equal-score ties real.
    return ClipStudy("take-0", "interview.mp4", "a" * 64, 18., "ready",
                     words=[Word("Hello." if i % 4 == 3 else "hello", i / 2 + .125, i / 2 + .375)
                            for i in range(36)], shots=[Shot(0, 0., 18.)])


@pytest.mark.parametrize("gap", [0., .2])
def test_moment_shot_coverage_and_constraint_planning(gap):
    from types import SimpleNamespace
    from myzing.director.selection import subtract
    clip = even_speech()
    clip.shots = [Shot(0, 0., 4.), Shot(1, 4. + gap, 18.)]
    rows = suggest_moments(clip, target=6, top=3)
    assert rows
    assert rows[0]["start"] == (.125 if gap == 0 else 6.125)
    if gap == 0:
        assert rows[0]["start"] < 4. < rows[0]["end"]
    manifest = SimpleNamespace(assets=[SimpleNamespace(id=clip.asset_id, path=clip.path,
                                                       original_path=clip.path, previous_paths=[])])
    for row in rows:
        assert not subtract([(row["start"], row["end"])], [(s.start, s.end) for s in clip.shots])
        keep, forbidden = constraints(Brief(must_keep=row["must_keep"]), manifest, [clip])
        pool, required = candidates([clip], keep, forbidden, style(), 6)
        assert choose(pool, required, [clip], style(), 6, 30, 0)


def test_equal_score_moments_use_source_order():
    rows = suggest_moments(even_speech(), target=6, top=3)
    assert len(rows) == 3 and len({r["score"] for r in rows}) == 1
    assert [r["start"] for r in rows] == [.125, 6.125, 12.125]


@pytest.mark.parametrize("kind", ["static_slate", "no_transcript", "very_short"])
def test_no_moments_without_sufficient_observed_speech(kind):
    clip = even_speech()
    if kind == "very_short":
        clip.duration, clip.words, clip.shots = .5, [Word("Hello.", .1, .4)], [Shot(0, 0., .5)]
    else:
        clip.words = []
        clip.shots = [Shot(0, 0., 18.)] if kind == "static_slate" else [Shot(0, 0., 9.), Shot(1, 9., 18.)]
    assert suggest_moments(clip) == []


@pytest.mark.parametrize("external", [False, True])
@pytest.mark.parametrize("source_kind", ["media", "study"])
def test_moments_cli_inventory_constraint_roundtrip(tmp_path, zing_workspace, capsys, external, source_kind):
    from tools.plan_examples import example_project, write_json
    from myzing.cli import main
    from myzing.director.inventory import inventory
    from myzing.project.api import load_project
    root, _, _ = example_project(tmp_path / "project")
    media = root / "clips/take-0.mp4"
    study = root / "breakdowns/take-0/breakdown.json"
    if external:
        external_dir = tmp_path / "external-clips"
        external_dir.mkdir()
        outside = external_dir / media.name
        outside.write_bytes(media.read_bytes())
        manifest = json.loads((root / "project.json").read_text())
        manifest["assets"][0].update(path=str(outside), original_path=str(outside),
                                     mtime_ns=outside.stat().st_mtime_ns)
        write_json(root / "project.json", manifest)
        data = json.loads(study.read_text())
        data["meta"].update(source_url=str(outside), media_path=str(outside))
        write_json(study, data)
        media = outside
    source = media if source_kind == "media" else study
    assert main(["moments", str(source), "--workspace", str(root), "--target", "6", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] and data["suggestions"]
    clips, _ = inventory(root)
    for row in data["suggestions"]:
        assert row["must_keep"][0]["clip"] == "take-0"
        brief = Brief.from_dict({**Brief(target_length_seconds=6).to_dict(), "must_keep": row["must_keep"]})
        keep, forbidden = constraints(brief, load_project(root), clips)
        assert keep["take-0"] == [(row["start"], row["end"])]
        pool, required = candidates(clips, keep, forbidden, style(), 6)
        assert choose(pool, required, clips, style(), 6, 30, 0)


@pytest.mark.parametrize("direction", [-1, 1])
def test_audio_drift_exact_boundary_and_just_over(direction):
    from myzing.director.inventory import audio_duration_notes
    assert "accepted" in audio_duration_notes(120 + direction * .25, 120)[0]
    with pytest.raises(ValueError, match="measured drift is more than 0.250s"):
        audio_duration_notes(120 + direction * .25001, 120)


@pytest.mark.parametrize("speech_elsewhere", [False, True])
def test_silent_single_shot_selection_warns_in_plan_and_report(tmp_path, zing_workspace, monkeypatch, speech_elsewhere):
    from tools.plan_examples import example_project, write_json
    from myzing.director.api import plan_drafts
    from myzing.director.plans import REPORT_PREFIX
    from myzing.composition import Composition
    from myzing.layout import framing
    root, _, _ = example_project(tmp_path / "project")
    manifest = json.loads((root / "project.json").read_text())
    manifest["assets"] = manifest["assets"][:1]
    manifest["assets"][0]["probe"]["duration"] = 40.
    write_json(root / "project.json", manifest)
    study = root / "breakdowns/take-0/breakdown.json"
    data = json.loads(study.read_text())
    data["meta"]["duration"] = 40.
    data["shots"] = [Shot(0, 0., 40.).__dict__]
    data["words"] = [Word("Hello.", 35., 36.).__dict__] if speech_elsewhere else []
    if not speech_elsewhere:
        data["provenance"]["vad"] = {"method": "synthetic measured silence"}
        data["audio"]["speech_ratio"] = 0.
    write_json(study, data)
    brief = Brief(target_length_seconds=30, caption_mode="none", picture_crop="off",
                  must_keep=[{"clip": "take-0", "start": 0., "end": 30.}])
    write_json(root / "brief.json", brief.to_dict())
    monkeypatch.setattr(framing, "analyze_subjects", lambda *a, **k: ([], []))
    result = plan_drafts(root, root / "recipe.json", root / "plans")
    comparison = json.loads(Path(result["comparison_path"]).read_text())
    assert result["status"] == "ready", comparison["shortages"]
    for label, path in result["plans"].items():
        plan = Composition.from_json(Path(path).read_text())
        warning = next(w for w in plan.warnings if "may be a static title slate" in w)
        assert "no transcribed speech and one observed shot" in warning
        assert warning in comparison["plans"][label]["warnings"]
        evidence = json.loads(next(w[len(REPORT_PREFIX):] for w in plan.warnings if w.startswith(REPORT_PREFIX)))
        assert warning in evidence["warnings"]


# Reuse the real MCP stdio fixture; the registry and schema travel over the wire.
from test_mcp_stdio import client


def test_millisecond_rounded_shot_end_past_duration_is_snapped(tmp_path, zing_workspace):
    # Real NASA podcast: duration 3901.38083 s, last shot rounded to 3901.381 s,
    # and the whole 65-minute study was excluded as "time beyond media duration".
    from tools.plan_examples import example_project, write_json
    from myzing.director.inventory import inventory
    root, _, _ = example_project(tmp_path / "project")
    manifest = json.loads((root / "project.json").read_text())
    manifest["assets"][0]["probe"]["duration"] = 120.0004
    write_json(root / "project.json", manifest)
    path = root / "breakdowns/take-0/breakdown.json"
    data = json.loads(path.read_text())
    data["meta"]["duration"] = 120.0004
    data["shots"][-1]["end"] = 120.0009  # 0.5 ms past: rounding, snapped
    data["provenance"]["raw_mode"]["dead_air"] = [{"start": 119., "end": 120.0009}]
    write_json(path, data)
    clip = inventory(root)[0][0]
    assert clip.status == "ready", clip.warnings
    assert clip.shots[-1].end == clip.duration and clip.dead_air[-1]["end"] == clip.duration
    data["shots"][-1]["end"] = 120.002  # 1.6 ms past: a real error, still refused
    write_json(path, data)
    clip = inventory(root)[0][0]
    assert clip.status == "needs_study"
    assert any("beyond media duration" in w for w in clip.warnings)
