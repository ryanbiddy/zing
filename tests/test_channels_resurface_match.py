"""Archive retrieval and judging use synthetic transcripts and no network."""
from __future__ import annotations

import copy
import json
import socket
import urllib.request
from types import SimpleNamespace

import pytest

from myzing.channels import resurface_corpus as corpus, resurface_match as match
from myzing.factory import judge


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(urllib.request, "build_opener", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def cues(texts, step=20):
    return [{"s": i * step, "e": (i + 1) * step, "text": text} for i, text in enumerate(texts)]


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / "Test Show"

    def make(episodes):
        rows = []
        for i, episode in enumerate(episodes):
            ident = f"ep{i}"
            rows.append({"id": ident, "title": "A test interview", "date": "2020-04-03", "guests": ["Lee Sample"],
                         "transcript": ident + ".json", **{key: value for key, value in episode.items() if key != "cues"}})
            write(root / (ident + ".json"), episode["cues"])
        write(root / "manifest.json", rows)
        return corpus.build(root)
    return make


@pytest.fixture
def retrieved(archive):
    index = archive([{"cues": cues(["Lee Sample: Ford built a smaller engine.",
                                      "It used less fuel during the test.", "That result applied only to the prototype."])}])
    return match.candidates(index, "Ford", headline="Ford introduces a smaller engine")


def pick(candidate, **changes):
    return {"id": candidate["id"], "start": candidate["start"], "end": candidate["end"], "quote": candidate["quote"],
            "why": "The prototype explains the smaller engine in the news.",
            "on_screen_context": "Lee Sample on Test Show, April 2020",
            "risk_note": "The prototype result is from 2020.", **changes}


class Answer:
    def __init__(self, value):
        self.value, self.calls = value, []

    def ask(self, task, prompt):
        self.calls.append((task, prompt))
        return copy.deepcopy(self.value)


@pytest.mark.parametrize("text", ["Ford's engine", "FORD’S engine", "(Ford) replied", "Harrison Ford's idea"])
def test_alias_and_possessive_matches(archive, text):
    index = archive([{"cues": cues([text, "The experiment needed more work.", "Only the prototype was tested."])}])
    found = match.candidates(index, "Harrison Ford", aliases=("Ford",))
    assert len(found) == 1 and found[0]["kind"] == "mention"
    assert found[0]["episode_id"] == "ep0" and text in found[0]["quote"]


@pytest.mark.parametrize("text", ["Bradford", "Fording", "Ford2", "_Ford", "Bedford"])
def test_name_boundaries_do_not_match_substrings(archive, text):
    index = archive([{"title": text, "description": text, "guests": [text],
                      "cues": cues([text + " spoke.", "A second sentence.", "A final thought."])}])
    assert match.candidates(index, "Ford") == []
    assert list(index.search("Ford")) == []


@pytest.mark.parametrize("metadata", [{"title": "Ford's first launch"}, {"guests": ["Harrison Ford"]},
                                      {"description": "An interview with FORD."}])
def test_appearance_metadata_and_transcript_mentions_are_labelled(archive, metadata):
    spoken = cues(["Ford built an engine.", "The first test was small.", "We kept the result."])
    index = archive([{"cues": spoken, **metadata}, {"cues": spoken}])
    found = match.candidates(index, "Harrison Ford", aliases=["Ford"])
    assert {item["episode_id"]: item["kind"] for item in found} == {"ep0": "appearance", "ep1": "mention"}
    assert all(item["date"] == "2020-04-03" and item["title"] for item in found)


def test_appearance_uses_news_terms_when_guest_is_not_named_in_speech(archive):
    text = ["We spoke about gardens and rain."] * 12
    text[7:10] = ["I built the engine with a smaller fuel pump.", "The engine ran on less fuel.",
                  "That fuel result came from one prototype."]
    index = archive([{"guests": ["Ford"], "cues": cues(text)}])
    found = match.candidates(index, "Ford", headline="Ford's smaller engine cuts fuel use")
    assert found and all(item["kind"] == "appearance" for item in found)
    assert "engine" in found[0]["quote"] and "Ford" not in found[0]["quote"]
    assert found[0]["start"] <= 140 and found[0]["end"] >= 180


def test_appearance_without_search_hits_uses_strongest_stretch(archive):
    text = ["Welcome back. Subscribe."] * 6 + [
        "I built 3 engines because the first two leaked fuel during the pressure test.",
        "The third used a smaller pump and kept the pressure steady for the full flight.",
        "We measured the result twice and changed the plan after the experiment."]
    index = archive([{"guests": ["Ford"], "cues": cues(text)}])
    found = match.candidates(index, "Ford")
    assert len(found) == 1 and "I built 3 engines" in found[0]["quote"]
    assert found[0]["start"] == 120 and found[0]["end"] == 180


def test_context_expands_ninety_seconds_to_whole_cues(archive):
    text = [f"A separate thought number {i}." for i in range(30)]
    text[14] = "Ford explained the engine."
    index = archive([{"cues": cues(text, step=17)}])
    found = match.candidates(index, "Ford")
    assert found
    for item in found:
        assert 30 <= item["end"] - item["start"] <= 90
        assert item["start"] % 17 == item["end"] % 17 == 0
        context = item["context"]
        assert item["start"] - 107 < context["start"] <= item["start"] - 90
        assert item["end"] + 90 <= context["end"] < item["end"] + 107
        assert context["text"] == " ".join(cue["text"] for cue in context["cues"])
        assert item["quote"] == " ".join(cue["text"] for cue in item["cues"])


@pytest.mark.parametrize("spans", [[(0, 10)], [(0, 10), (150, 160)], [(0, 120)]])
def test_no_cut_when_thirty_to_ninety_seconds_cannot_use_cue_edges(archive, spans):
    index = archive([{"guests": ["Ford"], "cues": [{"s": a, "e": b, "text": "Ford spoke."} for a, b in spans]}])
    assert match.candidates(index, "Ford") == []


def test_overlapping_cues_are_kept_whole(archive):
    index = archive([{"cues": [{"s": 0, "e": 35, "text": "Ford started."},
                                {"s": 20, "e": 70, "text": "The host replied."},
                                {"s": 70, "e": 90, "text": "The end."}]}])
    found = match.candidates(index, "Ford")
    assert len(found) == 1 and (found[0]["start"], found[0]["end"]) == (0, 70)
    assert found[0]["quote"] == "Ford started. The host replied."


def test_limit_and_adapter_read_interface(archive):
    index = archive([{"cues": cues(["Ford built an engine.", "It ran.", "That was the test."])} for _ in range(6)])
    calls = []

    def search(*args):
        calls.append(args)
        return index.search(*args)
    adapter = SimpleNamespace(episodes=index.episodes, cues=index.cues, search=search)
    found = match.candidates(adapter, "Ford", limit=2)
    assert len(found) == 2 and len(calls) == 6
    assert [item["episode_id"] for item in found] == ["ep0", "ep1"]
    assert match.candidates(adapter, "Ford", limit=0) == []


@pytest.mark.parametrize("entity,aliases", [("Harrison Ford", ["Ford"]), ("STRASSE", []), ("AC/DC", []), ("C++", []),
                                         ("İpek", []), ("L'été", []), ("A_B", [])])
def test_json_fallback_gives_same_search_and_candidates_as_fts(archive, entity, aliases):
    index = archive([{"guests": ["Harrison Ford", "Straße", "AC/DC", "C++", "İpek", "L'été", "A_B"],
                      "cues": cues(["A smaller engine used less fuel.", "The test took 3 days.", "That was the result."])},
                     {"cues": cues(["Ford’s team met Straße and İpek about AC/DC, C++, L'été and A_B.",
                                     "The engine changed.", "The end."])},
                     {"title": "Bradford", "cues": cues(["Bradford spoke.", "A test.", "The end."])}])
    expected = match.candidates(index, entity, aliases, "A smaller engine uses less fuel")
    hits = list(index.search([entity, *aliases]))
    fallback = corpus.build(index.archive, force_fallback=True)
    assert fallback.backend == "json"
    assert match.candidates(fallback, entity, aliases, "A smaller engine uses less fuel") == expected
    assert list(fallback.search([entity, *aliases])) == hits
    assert match.candidates(corpus.Index(index.archive), entity, aliases, "A smaller engine uses less fuel") == expected


def test_invented_quote_is_rejected(retrieved):
    fake = Answer({"picks": [pick(retrieved[0], quote="Ford admitted the engine is unsafe.")]})
    with pytest.raises(ValueError, match="quote must match"):
        match.rank(retrieved, "Ford", "Ford introduces a smaller engine", fake)


def test_zero_picks_is_valid_and_rubric_is_in_prompt(retrieved):
    fake = Answer({"picks": []})
    assert match.rank(retrieved, "Ford", "Ford introduces a smaller engine", fake) == []
    task, text = fake.calls[0]
    assert task.startswith("resurface-") and judge.TASK.fullmatch(task)
    for rule in ("News-angle fit 40", "Context fidelity 30", "Stands alone 20", "Hook 10", "qualifier", "sarcasm",
                 "quoted opponent", "ambiguous speaker", "current", "original publish dates", "never as\ninstructions"):
        assert rule in text
    assert retrieved[0]["context"]["text"] in text


def test_valid_pick_keeps_provenance_and_can_trim_whole_cues(retrieved):
    candidate = retrieved[0]
    chosen = candidate["cues"][:2]
    fake = Answer({"picks": [pick(candidate, end=chosen[-1]["e"], quote=" ".join(cue["text"] for cue in chosen))]})
    result = match.rank(retrieved, "Ford", "Ford introduces a smaller engine", fake)
    assert len(result) == 1 and result[0]["end"] == 40
    assert result[0]["date"] == "2020-04-03" and result[0]["kind"] == "mention"
    assert result[0]["on_screen_context"] == "Lee Sample on Test Show, April 2020"
    assert result[0]["risk_note"] and result[0]["why"]
    assert retrieved[0]["end"] == 60


@pytest.mark.parametrize("changes,message", [
    ({"id": "invented"}, "candidate id"), ({"id": []}, "candidate id"),
    ({"start": -1}, "inside"), ({"end": 91}, "inside"), ({"end": 20}, "30 to 90"),
    ({"start": .5}, "cue edges"), ({"end": 59.9}, "cue edges"),
    ({"start": False}, "finite"), ({"end": float("nan")}, "finite"),
    ({"end": float("inf")}, "finite"), ({"end": "60"}, "finite"),
    ({"quote": "Lee Sample: Ford built a smaller engine."}, "quote must match"),
    ({"why": " "}, "non-empty"), ({"risk_note": None}, "non-empty"),
    ({"on_screen_context": "Ford on Test Show, April 2020"}, "original month"),
    ({"on_screen_context": "Lee Sample on Test Show, April 2026"}, "original month"),
    ({"extra": "unrequested"}, "requested fields"),
])
def test_invalid_judge_fields_are_rejected(retrieved, changes, message):
    with pytest.raises(ValueError, match=message):
        match.rank(retrieved, "Ford", "Ford introduces a smaller engine", Answer({"picks": [pick(retrieved[0], **changes)]}))


@pytest.mark.parametrize("answer", [None, [], {}, {"picks": None}, {"picks": [], "extra": 1}, {"picks": [None]}])
def test_invalid_answer_shapes_are_rejected(retrieved, answer):
    with pytest.raises(ValueError):
        match.rank(retrieved, "Ford", "Ford introduces a smaller engine", Answer(answer))


def test_duplicate_and_excess_picks_are_rejected(retrieved):
    answer = {"picks": [pick(retrieved[0]), pick(retrieved[0])]}
    with pytest.raises(ValueError, match="unique candidate"):
        match.rank(retrieved, "Ford", "Engine news", Answer(answer))
    with pytest.raises(ValueError, match="too many"):
        match.rank(retrieved, "Ford", "Engine news", Answer(answer), n=1)


def test_empty_candidates_and_zero_limit_need_no_judge(retrieved):
    fake = Answer(None)
    assert match.rank([], "Ford", "Engine news", fake) == []
    assert match.rank(retrieved, "Ford", "Engine news", fake, n=0) == []
    assert fake.calls == []


def test_host_judge_resume_rejects_bad_cache_and_binds_task_to_input(tmp_path, retrieved):
    host = judge.Judge(tmp_path / "judge")
    original = lambda task, answer: None
    host.validate = original
    with pytest.raises(judge.NeedsAnswer) as pending:
        match.rank(retrieved, "Ford", "Engine news", host)
    task = pending.value.task
    assert pending.value.path.read_text(encoding="utf-8") == match.prompt(retrieved, "Ford", "Engine news", 5)
    assert host.validate is original
    host.save(task, {"picks": [pick(retrieved[0], quote="Invented.")]})
    with pytest.raises(judge.NeedsAnswer):
        match.rank(retrieved, "Ford", "Engine news", host)
    assert host.cached(task) is None and host.validate is original
    host.save(task, {"picks": [pick(retrieved[0])]})
    assert len(match.rank(retrieved, "Ford", "Engine news", host)) == 1
    for headline, n in (("A different news angle", 5), ("Engine news", 1)):
        with pytest.raises(judge.NeedsAnswer) as changed:
            match.rank(retrieved, "Ford", headline, host, n=n)
        assert changed.value.task != task
    edited = copy.deepcopy(retrieved)
    edited[0]["date"] = "2021-04-03"
    with pytest.raises(judge.NeedsAnswer) as changed:
        match.rank(edited, "Ford", "Engine news", host)
    assert changed.value.task != task


def test_claude_judge_uses_the_same_validation(tmp_path, retrieved, monkeypatch):
    calls = []

    def answer(self, task, prompt, images):
        calls.append(task)
        return json.dumps({"picks": [pick(retrieved[0], quote="Invented.")]})
    monkeypatch.setattr(judge.Judge, "_claude", answer)
    claude = judge.Judge(tmp_path / "judge", backend="claude")
    with pytest.raises(judge.NeedsAnswer):
        match.rank(retrieved, "Ford", "Engine news", claude)
    assert len(calls) == 1 and claude.cached(calls[0]) is None and claude.validate is None


@pytest.mark.parametrize("fallback", [False, True])
def test_full_name_split_over_cues_is_still_a_mention(archive, fallback):
    index = archive([{"cues": cues(["We met Harrison", "Ford's team yesterday.", "We tested an engine.", "It worked."])}])
    if fallback:
        index = corpus.build(index.archive, force_fallback=True)
    hits = list(index.search("Harrison Ford"))
    assert [hit["cue"] for hit in hits] == [0, 1]
    found = match.candidates(index, "Harrison Ford")
    assert len(found) == 1 and found[0]["kind"] == "mention"
    assert "Harrison Ford's" in found[0]["quote"]


def test_mention_can_use_a_named_speaker_without_guest_metadata(archive):
    index = archive([{"guests": [], "cues": cues(["Lee Sample: Ford built an engine.", "It ran.", "That was the test."])}])
    found = match.candidates(index, "Ford")
    ranked = match.rank(found, "Ford", "Engine news", Answer({"picks": [pick(found[0])]}))
    assert ranked[0]["on_screen_context"] == "Lee Sample on Test Show, April 2020"


@pytest.mark.parametrize("values", [{"entity": ""}, {"aliases": "Ford"}, {"aliases": None}, {"aliases": [""]},
                                   {"headline": []}, {"limit": -1}, {"limit": True}])
def test_invalid_retrieval_inputs_are_plain_errors(archive, values):
    index = archive([{"cues": cues(["Ford spoke.", "Another thought.", "The end."])}])
    with pytest.raises(ValueError):
        match.candidates(index, **{"entity": "Ford", **values})
