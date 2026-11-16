"""Authored stories use invented people and no external media."""
from __future__ import annotations

import copy
import json

import pytest

from myzing.story import StoryError, data_path
from myzing.story.contract import CARD_KINDS, POSES, PROPS, VOCABULARY, check, check_timings, cue_time, load
from myzing.story.outro import credit_lines, prepare
from test_factory_brand_kit import node


def story():
    return {"topic": "a paper town", "handle": "", "cast": {"ada": {"name": "Ada Paper"}},
            "sources": [{"title": "Invented fixture", "url": "https://example.com/fiction"}],
            "beats": [{"id": ident, "chapter": "A PAPER TOWN", "lines": [{"text": line}]}
                      for ident, line in zip(("hook", "first-job", "turn", "kicker"),
                                             ("A paper town ran out of paper.", "Ada folded the last sheet.",
                                              "It became a little boat.", "The town sailed home."))],
            "panels": [{"from": "hook", "set": {"wall": "#FFD21F", "floor_pattern": "planks"},
                        "props": [{"prop": "tree", "x": 880, "y": 1500, "front": True}],
                        "actors": [{"who": "ada", "x": 300, "pose": "idle",
                                    "poses": [{"at": "turn:0:0.5", "pose": "wave"}],
                                    "head_at": [{"at": "turn", "head": 0}],
                                    "moves": [{"at": "turn", "from": 300, "to": 400, "dur": .5}]}],
                        "cards": [{"kind": "note", "text": "A paper town", "x": 80, "y": 250, "at": "hook"}]}]}


def timings():
    return {"duration": 12, "outro_start": 10, "provider": "lines", "voice": None,
            "beats": [{"id": beat["id"], "start": i * 2 + .35, "end": i * 2 + 2.35,
                       "lines": [{"text": beat["lines"][0]["text"], "start": i * 2 + .35, "end": i * 2 + 1.35}]}
                      for i, beat in enumerate(story()["beats"])]}


def put(value, path, replacement):
    target = value
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = replacement


def test_good_story_and_generated_outro(tmp_path):
    value = story()
    assert check(value, tmp_path) == []
    (tmp_path / "story.json").write_text(json.dumps(value), encoding="utf-8")
    assert load(tmp_path) == value
    assert check_timings(value, timings()) == []
    assert prepare(value, timings())["panels"][-1]["from"] == "outro"


@pytest.mark.parametrize("path,value,problem", [
    (("topic",), "", "topic"),
    (("schema_version",), 2, "schema_version"),
    (("handle",), "x" * 41, "40 characters"),
    (("beats",), [], "4 to 14"),
    (("beats",), story()["beats"] * 4, "4 to 14"),
    (("beats", 0, "id"), "outro", "reserved"),
    (("beats", 0, "id"), "turn", "duplicate"),
    (("beats", 0, "id"), "../bad", "lowercase ID"),
    (("beats", 0, "lines", 0, "text"), "word " * 23, "22 words"),
    (("beats", 0, "lines", 0, "say"), "word " * 23, "22 words"),
    (("beats", 0, "lines"), [], "1 to 8"),
    (("beats", 0, "lines", 0, "gap"), -1, "gap"),
    (("beats", 0, "tail"), float("nan"), "tail"),
    (("sources",), [], "sources"),
    (("sources", 0, "title"), "", "title"),
    (("sources", 0, "url"), "file:///private", "https URL"),
    (("panels", 0, "from"), "first-job", "every beat"),
    (("panels", 0, "from"), "unknown", "beat ID"),
    (("panels", 0, "from"), "hook+0.2", "no offsets"),
    (("panels", 0, "cards", 0, "kind"), "banner", "unknown value"),
    (("panels", 0, "cards", 0, "kind"), "credits", "generated"),
    (("panels", 0, "cards", 0, "x"), -1, ".x"),
    (("panels", 0, "cards", 0, "x"), 1081, ".x"),
    (("panels", 0, "cards", 0, "x"), 1080, "inside the frame"),
    (("panels", 0, "cards", 0, "y"), -1, ".y"),
    (("panels", 0, "cards", 0, "y"), 1921, ".y"),
    (("panels", 0, "cards", 0, "y"), 1920, "inside the frame"),
    (("panels", 0, "cards", 0, "at"), "missing", "unknown beat"),
    (("panels", 0, "cards", 0, "until"), "turn:9", "out of range"),
    (("panels", 0, "cards", 0, "at"), "turn:0:1.1", "fraction"),
    (("panels", 0, "props", 0, "prop"), "telephone", "unknown value"),
    (("panels", 0, "props", 0, "at"), "missing", "unknown beat"),
    (("panels", 0, "props", 0, "until"), "missing", "unknown beat"),
    (("panels", 0, "props", 0, "front"), "#FFFFFF", "boolean"),
    (("panels", 0, "props", 0, "anim"), "stamp", "unknown value"),
    (("panels", 0, "props", 0, "anim"), "slide", "unknown value"),
    (("panels", 0, "props", 0, "fill"), 'red" onload="bad()', "hex color"),
    (("panels", 0, "set", "wall"), "url(https://example.com)", "hex color"),
    (("panels", 0, "set", "pattern"), "checks", "unknown value"),
    (("panels", 0, "set", "floor_pattern"), "tiles", "unknown value"),
    (("panels", 0, "actors", 0, "who"), "bea", "unknown cast"),
    (("panels", 0, "actors", 0, "pose"), "dance", "unknown value"),
    (("panels", 0, "actors", 0, "poses", 0, "pose"), "dance", "unknown value"),
    (("panels", 0, "actors", 0, "poses", 0, "at"), "missing", "unknown beat"),
    (("panels", 0, "actors", 0, "head_at", 0, "at"), "missing", "unknown beat"),
    (("panels", 0, "actors", 0, "head_at", 0, "head"), 3, "out of range"),
    (("panels", 0, "actors", 0, "moves", 0, "at"), "missing", "unknown beat"),
    (("panels", 0, "actors", 0, "moves", 0, "dur"), 0, ".dur"),
    (("panels", 0, "actors", 0, "enter"), "missing", "unknown beat"),
    (("cast", "ada", "photos"), [None], "must be an object"),
    (("panels", 0, "actors"), None, "must be a list"),
    (("panels", 0, "cards"), [False], "must be an object"),
    (("outro",), 0, "outro"),
])
def test_rules_report_a_problem(path, value, problem):
    value_story = story()
    put(value_story, path, value)
    assert any(problem in error for error in check(value_story)), check(value_story)


@pytest.mark.parametrize("field", ["text", "say"])
def test_whole_narration_limit(field):
    value = story()
    for beat in value["beats"]:
        beat["lines"] = [{"text": "One idea.", field: "word " * 21} for _ in range(2)]
    assert any("160 words" in error for error in check(value))


@pytest.mark.parametrize("kind,limits", list(VOCABULARY["cards"].items()))
def test_card_limits(kind, limits):
    if kind == "credits":
        return  # Generated from validated metadata, never an author-written card.
    for field, limit in limits.items():
        value = story()
        card = {"kind": kind, "x": 50, "y": 200, "at": "hook"}
        if kind == "list":
            card["rows"] = [{"text": "Short", "at": "turn"}]
        else:
            card["text"] = "Short"
        if field == "rows":
            card["rows"] *= limit + 1
        elif field == "row":
            card["rows"][0]["text"] = "x" * (limit + 1)
        else:
            card[field] = "x" * (limit + 1)
        value["panels"][0]["cards"] = [card]
        assert any("characters" in e or "entries" in e for e in check(value)), (kind, field)


def test_panel_coverage_and_order():
    value = story()
    value["panels"].extend([{"from": "turn"}, {"from": "first-job"}, {"from": "outro"}, {"from": "outro"}])
    assert sum("without duplicates" in e for e in check(value)) == 2


@pytest.mark.parametrize("path", ["../photo.png", "https://example.com/photo.png", "C:/private/photo.png", "/photo.png"])
def test_photo_paths_stay_local(path):
    value = story()
    value["cast"]["ada"]["photos"] = [{"path": path, "credit": "Fixture artist", "license": "CC0",
                                         "source_url": "https://example.com/fixture"}]
    assert any("photo path" in e for e in check(value))


@pytest.mark.parametrize("license", ["", "CC BY-NC 4.0", "CC BY-ND 4.0", "all rights reserved"])
def test_validator_rejects_uncleared_photos(license):
    value = story()
    value["cast"]["ada"]["photos"] = [{"path": "photo.png", "credit": "Fixture artist", "license": license,
                                         "source_url": "https://example.com/fixture"}]
    assert any("license" in e for e in check(value))


def test_check_collects_errors_and_bad_json_is_plain(tmp_path):
    errors = check({"topic": "", "sources": [], "beats": [], "panels": []})
    assert len(errors) >= 4
    (tmp_path / "story.json").write_text("{", encoding="utf-8")
    with pytest.raises(StoryError, match="Cannot read story.json"):
        load(tmp_path)


CUES = [(0.2, .2), ("hook", .35), ("hook:0", .35), ("hook:0:0.5", .85),
        ("hook:0:.5+0.2", 1.05), ("hook:0:-0.2", .15), ("hook-0.2", .15),
        ("first-job", 2.35), ("first-job:0:1-0.2", 3.15), ("outro", 10),
        ("outro-0.3", 9.7), ("outro+0.2", 10.2), ("outro:-0.2", 9.8)]


@pytest.mark.parametrize("cue,want", CUES)
def test_cue_known_values(cue, want):
    assert cue_time(cue, timings()) == pytest.approx(want)


@pytest.mark.parametrize("cue", ["unknown", "hook:1", "hook:0:1.2", "hook:.5", "outro:0", "outro:0:0.3", "hook+-0.2", None, True, float("inf")])
def test_bad_cues_are_errors(cue):
    with pytest.raises(StoryError):
        cue_time(cue, timings())


def test_page_and_python_agree_on_vocabulary_and_cues():
    page = data_path("cutout.html").read_text(encoding="utf-8")
    script = page.split("<script>", 1)[1].rsplit("</script>", 1)[0]
    program = "global.window={};\n" + script + "\nconsole.log(JSON.stringify({v:window.storyVocabulary,t:INPUT.cues.map(c=>cueTime(c,INPUT.timings))}));"
    program = program.replace("INPUT", json.dumps({"cues": [c for c, _ in CUES], "timings": timings()}))
    result = node(program)
    assert result.returncode == 0, result.stderr
    got = json.loads(result.stdout)
    assert set(got["v"]["cards"]) == set(CARD_KINDS)
    assert set(got["v"]["props"]) == set(PROPS)
    assert set(got["v"]["poses"]) == set(POSES)
    assert got["t"] == pytest.approx([t for _, t in CUES])


@pytest.mark.parametrize("provider,disclosure", [("kokoro", True), ("lines", False)])
@pytest.mark.parametrize("custom", [True, False])
def test_outro_credits_cannot_be_removed(provider, disclosure, custom):
    value = story()
    value["cast"]["ada"]["photos"] = [{"path": "synthetic.png", "credit": "Fixture artist", "license": "CC0",
                                         "source_url": "https://example.com/fixture"}]
    if custom:
        value["panels"].append({"from": "outro", "set": {"wall": "#112233"}, "cards": []})
    before = copy.deepcopy(value)
    result = prepare(value, {**timings(), "provider": provider, "voice": "test"})
    card = result["panels"][-1]["cards"][-1]
    assert card["kind"] == "credits"
    assert ("narration is an AI voice" in card["lines"]) == disclosure
    assert "source: Invented fixture" in card["lines"]
    assert "photo: Fixture artist · CC0" in card["lines"]
    assert value == before
    assert result["cast"]["ada"]["heads"] == ["ada-0.png"]
    if custom:
        assert result["panels"][-1]["set"]["wall"] == "#112233"


def test_unknown_provider_does_not_suppress_disclosure():
    with pytest.raises(StoryError, match="provider"):
        credit_lines(story(), {"provider": "mystery"})


def test_minimal_panels_and_long_credits_are_prepared():
    value = story()
    value["panels"] = [{"from": "hook"}]
    value["cast"]["ada"]["photos"] = [{"credit": "x" * 120, "license": "y" * 100}]
    result = prepare(value, timings())
    assert result["panels"][0]["set"] == {}
    lines = result["panels"][-1]["cards"][-1]["lines"]
    assert all(len(line) <= VOCABULARY["cards"]["credits"]["line"] for line in lines)


@pytest.mark.parametrize("path,value", [(("provider",), "unknown"), (("duration",), float("nan")),
    (("beats",), []), (("beats", 0, "id"), "other"), (("beats", 0, "start"), -1),
    (("beats", 0, "lines", 0, "text"), "Changed"), (("beats", 0, "lines", 0, "end"), 20)])
def test_invalid_timings_are_errors(path, value):
    times = timings()
    put(times, path, value)
    assert check_timings(story(), times)


@pytest.mark.parametrize("license", ["CC BY-NC 4.0", "CC BY-ND 4.0", "unknown"])
def test_music_license_is_refused_by_check(license):
    value = story()
    value["music"] = {"path": "tone.wav", "credit": "Test artist", "license": license,
                      "source_url": "https://example.org/tone"}
    assert any("music.license: must permit reuse" in e for e in check(value))


def test_music_local_path_and_required_metadata():
    value = story()
    value["music"] = {"path": "../tone.wav", "credit": "", "license": "CC0", "source_url": "file:///tone"}
    errors = check(value)
    assert any(e.startswith("music.path:") for e in errors)
    assert any(e.startswith("music.credit:") for e in errors)
    assert any(e.startswith("music.source_url:") for e in errors)


def test_many_sources_share_one_wrapped_credit_line():
    many = story()
    many["sources"] = [{"title": f"Outlet number {i}", "url": f"https://example.org/{i}"} for i in range(6)]
    lines = credit_lines(many, {"provider": "lines"})
    assert lines[0].startswith("sources: Outlet number 0 · Outlet number 1")
    assert all(len(line) <= 58 for line in lines)
    assert sum("Outlet number" in line for line in lines) < 6
    assert all(f"Outlet number {i}" in " ".join(lines) for i in range(6))
