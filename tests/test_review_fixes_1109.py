"""Regressions from the serve, Studio and match review."""

import json
from dataclasses import replace

import pytest

from myzing.brief.models import Brief
from myzing.factory import batch, command, pipeline, serve, source
from myzing.factory.tools import FactoryError
from myzing.layout import face_size
from myzing.layout.crop_planner import select_framing
from myzing.match.moments import AutoMoments
from myzing.match.state import Checkpoints, read, write
from myzing.studio import command as studio_command, flow
from myzing.style_recipe import ObservationProvenance, StyleRecipe, add_face_framing, reference_face_share
from test_factory_face_size import clip, face
from test_match_long_clips import match, project as match_project
from test_studio_episode import answers_file, inputs as episode_inputs


@pytest.mark.parametrize("port", [-1, 65536, 70000])
def test_review_port_is_checked_before_opening_project(tmp_path, monkeypatch, capsys, port):
    monkeypatch.setattr(serve, "Studio", lambda *a: pytest.fail("invalid port reached the project"))
    with pytest.raises(SystemExit) as caught:
        command.run(["serve", str(tmp_path), "--port", str(port)])
    assert caught.value.code == 2
    error = capsys.readouterr().err
    assert "0" in error and "65535" in error and "Traceback" not in error


@pytest.mark.parametrize("port", [-1, 70000])
def test_review_bind_overflow_is_a_friendly_error(tmp_path, monkeypatch, port):
    def refuse(*args, **kwargs):
        raise OverflowError("bind(): port must be 0-65535")

    monkeypatch.setattr(serve, "ThreadingHTTPServer", refuse)
    monkeypatch.setattr(serve, "Studio", lambda *a: object())
    with pytest.raises(FactoryError, match=r"Port .*0.*65535"):
        serve.serve(tmp_path, port, say=lambda m: None)


@pytest.mark.parametrize("data", [
    {"title": "Episode metadata"}, {}, [], {"words": []}, {"segments": []},
    {"segments": [{"s": 0, "e": 1, "text": "Hello."}]},
    [{"w": "Hello", "s": 0}], [{"s": 0, "e": 1}], [{"text": "Hello", "start": 0}],
    [{"w": "Hello", "s": 0, "e": 1}, {"s": 1, "e": 2}], ["Hello"], None,
])
def test_unreadable_json_transcript_names_the_file(tmp_path, data):
    path = tmp_path / "episode.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError) as caught:
        source.load_transcript(path)
    assert str(caught.value) == "episode.json is not a transcript Zing can read. Use .srt, .vtt, or JSON words or segments."


@pytest.mark.parametrize("data,word_timed", [
    ([{"w": "Hello.", "s": 0, "e": 1}], True),
    ({"words": [{"text": "Hello.", "start": 0, "end": 1}]}, True),
    ([{"s": 0, "e": 1, "text": "Hello."}], False),
    ([{"text": "Hello.", "start": 0, "end": 1}], True),
])
def test_readable_json_siblings_are_offered(episode_inputs, data, word_timed):
    media = episode_inputs.media
    episode_inputs.transcript.unlink()
    path = media.with_suffix(".json")
    path.write_text(json.dumps(data), encoding="utf-8")
    segments, words = source.load_transcript(path, offset=2)
    assert segments == [{"s": 2, "e": 3, "text": "Hello."}]
    assert bool(words) is word_timed
    question = flow.next_step({"path": "g", "episode": str(media)})["question"]
    assert question["recommended"] == str(path)
    assert batch._settings(media, {})["transcript"] == path


@pytest.mark.parametrize("body", ['{"title":"Metadata"}', "[]", '[{"w":"Hello","s":0}]', "{"])
def test_unreadable_json_siblings_are_not_offered(episode_inputs, body):
    media = episode_inputs.media
    episode_inputs.transcript.unlink()
    media.with_suffix(".json").write_text(body, encoding="utf-8")
    question = flow.next_step({"path": "g", "episode": str(media)})["question"]
    assert question["recommended"] == "none"
    assert batch._settings(media, {})["transcript"] is None


def test_batch_does_not_pick_up_metadata_json(tmp_path):
    media = tmp_path / "episode.mp4"
    media.write_bytes(b"episode")
    media.with_suffix(".json").write_text('{"title":"Metadata"}', encoding="utf-8")
    assert batch._settings(media, {})["transcript"] is None


def test_explicit_metadata_transcript_fails_before_factory_init(episode_inputs):
    path = episode_inputs.media.with_suffix(".json")
    path.write_text('{"title":"Metadata"}', encoding="utf-8")
    with pytest.raises(ValueError, match="episode.json is not a transcript Zing can read"):
        pipeline.init(episode_inputs.project, episode_inputs.media, transcript=path)
    assert not episode_inputs.project.exists()


def test_reference_face_size_uses_the_largest_face_per_frame():
    recipe = StyleRecipe(ObservationProvenance("reference.mp4"))
    frames = [{"t": t, "face_boxes": [[0, .1, .3, .4], [.8, .1, .85, .18]]} for t in (0, 1, 2)]
    add_face_framing(recipe, {"frames": frames})
    assert reference_face_share(recipe.measured) == pytest.approx(.3)
    assert recipe.measured[-1].coverage.samples == 3


def test_zoomfill_failed_crop_search_is_bounded(monkeypatch):
    c, tracks = clip(), [face()]
    old = select_framing("auto", 5040, 2160, 720, 1280, c, tracks)
    assert old.mode == "zoomfill" and old.height == 2160
    calls, track = [], face_size.track_framing

    def tracked(candidate, *args, **kwargs):
        calls.append(candidate.height)
        return track(candidate, *args, **kwargs)

    monkeypatch.setattr(face_size, "track_framing", tracked)
    monkeypatch.setattr(face_size, "_assess", lambda *a, **k: replace(old.assessments[-1], reasons=["unsafe crop"]))
    new = face_size.match_face_framing(old, c, tracks, 720, 1280, .27)
    assert new.height == old.height
    assert new.face_match.limited_by == ["subject safety or crop motion"]
    assert 0 < len(calls) < 200


@pytest.mark.parametrize("threshold", [1188, 1189, 1203, 1507, 2159])
def test_zoomfill_refines_near_the_first_passing_crop(monkeypatch, threshold):
    c, tracks = clip(), [face()]
    old = select_framing("auto", 5040, 2160, 720, 1280, c, tracks)
    assess = face_size._assess

    def checked(candidate, *args, **kwargs):
        result = assess(candidate, *args, **kwargs)
        return replace(result, reasons=["unsafe crop"]) if candidate.height < threshold else result

    monkeypatch.setattr(face_size, "_assess", checked)
    new = face_size.match_face_framing(old, c, tracks, 720, 1280, .27)
    assert new.height == threshold
    assert not new.assessments[-1].reasons


@pytest.mark.parametrize("as_json", [False, True])
@pytest.mark.parametrize("name", ["studio-result.json", "studio-session.json"])
def test_studio_keeps_review_token_only_in_terminal(episode_inputs, monkeypatch, capsys, as_json, name):
    page = "http://127.0.0.1:12345/?t=temporary-token"
    monkeypatch.setattr(serve, "serve", lambda project, **kw: kw["ready"](page))
    file = answers_file(episode_inputs)
    assert studio_command.run(["--answers", str(file), "--yes", "--no-open", *(["--json"] if as_json else [])]) == 0
    assert page in capsys.readouterr().out
    text = (episode_inputs.project / name).read_text(encoding="utf-8")
    assert "?t=" not in text and "temporary-token" not in text
    assert "http://127.0.0.1:12345/" in text


@pytest.mark.parametrize("resume", [False, True])
def test_disabling_auto_moments_removes_saved_picks(match_project, resume):
    result = match(match_project, answers=match_project.answers, auto_moment=True)
    assert result["status"] == "ready", result
    assert read(match_project.root / "brief.json")["must_keep"]
    result = match(match_project, auto_moment=False, resume=resume)
    assert result["status"] == "shortage", result
    assert result["shortages"][0]["code"] == "long_source_needs_moment"
    assert not read(match_project.root / "brief.json")["must_keep"]
    assert not read(match_project.root / "match-state.json").get("auto_moments")


@pytest.mark.parametrize("resume", [False, True])
def test_disabling_auto_moments_keeps_user_spans_and_edits(match_project, resume):
    result = match(match_project, answers=match_project.answers, auto_moment=True)
    assert result["status"] == "ready", result
    path = match_project.root / "brief.json"
    brief = read(path)
    user_span = {"clip": "take-0", "start": 60., "end": 62.}
    brief["must_keep"].append(user_span)
    brief["purpose"] = "Keep my edit"
    write(path, brief)
    result = match(match_project, auto_moment=False, resume=resume)
    assert read(path)["must_keep"] == [user_span], result
    assert read(path)["purpose"] == "Keep my edit"


@pytest.mark.parametrize("supplied", ["answers", "brief"])
def test_disabling_auto_moments_keeps_explicit_user_choices(match_project, supplied):
    result = match(match_project, answers=match_project.answers, auto_moment=True)
    assert result["status"] == "ready", result
    brief = read(match_project.root / "brief.json")
    if supplied == "answers":
        options = {"answers": brief}
    else:
        path = match_project.root.parent / "chosen-brief.json"
        write(path, brief)
        options = {"brief": str(path)}
    result = match(match_project, auto_moment=False, **options)
    assert read(match_project.root / "brief.json")["must_keep"] == brief["must_keep"], result
    assert not read(match_project.root / "match-state.json").get("auto_moments")


def test_disabling_auto_moments_clears_picks_in_the_project_brief(match_project):
    result = match(match_project, answers=match_project.answers, auto_moment=True)
    assert result["status"] == "ready", result
    path = match_project.root / "brief.json"
    result = match(match_project, auto_moment=False, brief=str(path))
    assert result["status"] == "shortage", result
    assert not read(path)["must_keep"]


def test_auto_moments_does_not_rewrite_an_unchanged_brief(match_project):
    path = match_project.root / "brief.json"
    brief = Brief.from_answers(match_project.answers).to_dict()
    path.write_text(json.dumps(brief, separators=(",", ":")), encoding="utf-8")
    before = path.read_bytes(), path.stat().st_mtime_ns
    checkpoints = Checkpoints(match_project.root, False)
    AutoMoments(checkpoints, {}, [])
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_auto_moments_does_not_rewrite_unchanged_state(match_project, monkeypatch):
    write(match_project.root / "brief.json", Brief.from_answers(match_project.answers).to_dict())
    checkpoints = Checkpoints(match_project.root, True)
    AutoMoments(checkpoints, {}, [])
    monkeypatch.setattr(checkpoints, "save", lambda: pytest.fail("unchanged automatic moments rewrote state"))
    AutoMoments(checkpoints, {}, [])
