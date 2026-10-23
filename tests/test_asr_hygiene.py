from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing.schemas import Word
from myzing.study.asr_hygiene import clamp_words, vocabulary_context
from myzing.study import transcribe


def test_supplied_vocabulary_is_bounded_deduplicated_and_traceable():
    context = vocabulary_context([" Korky   Paul ", "Korky Paul", "x" * 81],
        brief={"exact_spellings": ["NASA"], "purpose": "space exploration"},
        metadata={"title": "Tears of Steel", "tags": ["Celia"]})
    assert context["terms"] == ["Korky Paul", "NASA", "space exploration", "Tears of Steel", "Celia"]
    assert context["sources"] == ["user", "brief.exact_spellings", "brief.purpose", "reference.title", "reference.tags"]
    assert context["omitted_terms"] == 1
    long = vocabulary_context([f"term{i}" for i in range(200)])
    assert len(long["terms"]) <= 64 and len(long["hotwords"]) <= 500
    assert vocabulary_context(["Korky"])["cache_key"] != vocabulary_context(["Corky"])["cache_key"]


def test_vocabulary_never_invents_or_corrects_a_name():
    assert vocabulary_context()["terms"] == []
    assert vocabulary_context(["Corky"])["hotwords"] == "Corky"
    with pytest.raises(ValueError, match="strings"):
        vocabulary_context([22])


@pytest.mark.parametrize("batched", [False, True])
def test_hotwords_and_prompt_reach_faster_whisper(monkeypatch, batched):
    import sys
    seen = {}
    class Model:
        def transcribe(self, source, **kwargs):
            seen.update(kwargs)
            return iter([]), SimpleNamespace(language="en", language_probability=.9)
    if batched:
        monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(BatchedInferencePipeline=lambda model: model))
    run = transcribe._run_model_batched if batched else transcribe._run_model
    run(Model(), Path("fake.wav"), vocabulary=["Korky Paul", "NASA"])
    assert seen["hotwords"] == "Korky Paul, NASA"
    assert seen["initial_prompt"] == "Korky Paul, NASA"
    assert seen["vad_filter"] and not seen["condition_on_previous_text"]
    assert "vad_parameters" not in seen  # preserve recognition's previous VAD defaults


def test_batch_fallback_retains_vocabulary_and_provenance(monkeypatch):
    seen = []
    monkeypatch.setattr(transcribe, "_load_model", lambda name: (object(), "cpu", "int8", "test"))
    def batch(*args, **kwargs):
        seen.append(kwargs)
        raise RuntimeError("batch failed")
    def sequential(*args, **kwargs):
        seen.append(kwargs)
        return [], "en", 1.0
    monkeypatch.setattr(transcribe, "_run_model_batched", batch)
    monkeypatch.setattr(transcribe, "_run_model", sequential)
    result = transcribe.transcribe(Path("fake.wav"), duration=600, vocabulary=["Korky Paul"])
    assert seen == [{"vocabulary": ["Korky Paul"]}] * 2
    assert result.provenance["asr_vocabulary"]["terms"] == ["Korky Paul"]


def test_edges_in_silence_are_pulled_in_with_originals_retained():
    words = [Word("Hello", .1, .7), Word("world", .7, 1.5)]
    result, timing = clamp_words(words, [(.3, 1.2)])
    assert [(w.start, w.end) for w in result] == [(.3, .7), (.7, 1.2)]
    assert [(w.start, w.end) for w in words] == [(.1, .7), (.7, 1.5)]
    assert len(timing["adjustments"]) == 2
    assert timing["original"][0]["start"] == .1
    assert timing["adjusted"][0]["start"] == .3


def test_inside_speech_words_are_unchanged():
    words = [Word("inside", .400123, .600123), Word("speech", .600123, .900123)]
    result, timing = clamp_words(words, [(.3, 1.2)])
    assert result == words and timing["adjustments"] == []


def test_edge_pass_preserves_decoder_options_and_uses_bundled_vad(monkeypatch):
    import sys
    from dataclasses import dataclass
    from myzing.study.asr_hygiene import finish_timing
    @dataclass
    class Options:
        min_silence_duration_ms: int = 2000
        speech_pad_ms: int = 400
    original = Options()
    seen = []
    def vad(samples, options, **kwargs):
        seen.append(options)
        return [{"start": 3200, "end": 12800}]
    monkeypatch.setitem(sys.modules, "faster_whisper.audio", SimpleNamespace(decode_audio=lambda *a, **k: [0]))
    monkeypatch.setitem(sys.modules, "faster_whisper.vad", SimpleNamespace(get_speech_timestamps=vad))
    words, timing = finish_timing([Word("hello", 0, 1)], Path("fake.wav"), SimpleNamespace(vad_options=original))
    assert original == Options(2000, 400)
    assert seen == [Options(200, 80)]
    assert timing["decoder_vad_options"]["speech_pad_ms"] == 400
    assert timing["vad_options"]["speech_pad_ms"] == 80
    assert (words[0].start, words[0].end) == (.2, .8)


def test_words_in_silence_and_tiny_intersections_are_not_fabricated():
    words = [Word("silence", 0, .2), Word("short", .9, 1.5)]
    result, timing = clamp_words(words, [(1, 1.05)])
    assert result == words and len(timing["unresolved"]) == 2


def test_single_word_can_shrink_both_edges_without_expansion():
    result, timing = clamp_words([Word("one", 0, 1)], [(.2, .8)])
    assert (result[0].start, result[0].end) == (.2, .8)
    assert timing["adjustments"][0]["method"] == "vad_edge_snap"


def test_small_vad_disagreements_are_tolerated():
    words = [Word("word", .19, .81)]
    assert clamp_words(words, [(.2, .8)])[0] == words


def test_multiple_regions_only_shrink_outer_edges_and_preserve_order():
    words = [Word("one", 0, .6), Word("two", .6, 1.1), Word("three", 1.2, 2)]
    result, _ = clamp_words(words, [(.1, .5), (.8, 1.8)])
    assert all(a.start <= b.start for a, b in zip(result, result[1:]))
    assert all(old.start <= new.start < new.end <= old.end for old, new in zip(words, result))


def test_overlapping_words_keep_start_order_when_last_start_is_protected():
    words = [Word("first", .1, .7), Word("second", .2, .8)]
    result, timing = clamp_words(words, [(.3, 1.2)])
    assert [w.start for w in result] == [.1, .2]
    assert any("reorder" in row["reason"] for row in timing["unresolved"])


@pytest.mark.parametrize("regions", [[(-1, 2)], [(1, 1)], [(0, float("nan"))]])
def test_bad_vad_regions_rejected(regions):
    with pytest.raises(ValueError, match="VAD regions"):
        clamp_words([Word("word", 0, 1)], regions)


def test_study_combines_brief_and_reference_without_network(zing_workspace, monkeypatch):
    from test_study_api import wire_stages, SOURCE
    from myzing.study import api
    from myzing.study.transcribe import TranscribeResult
    wire_stages(monkeypatch)
    received = {}
    def run(path, **kwargs):
        received.update(kwargs)
        return TranscribeResult()
    monkeypatch.setattr(api.transcribe_mod, "transcribe", run)
    result = api.study(SOURCE, vocabulary=["Korky Paul"],
                       brief={"exact_spellings": ["NASA"], "topic": "Space"},
                       reference_metadata={"title": "Tears of Steel"})
    assert received["vocabulary"] == ["Korky Paul", "NASA", "Space", "Tears of Steel"]
    assert result.provenance["asr_vocabulary"]["sources"][-1] == "reference.title"


def test_cli_repeated_vocabulary_reaches_study(zing_workspace, monkeypatch, capsys):
    from test_study_api import wire_stages, SOURCE
    from myzing.study import api, command
    from myzing.study.transcribe import TranscribeResult
    wire_stages(monkeypatch)
    received = {}
    def run(path, **kwargs):
        received.update(kwargs)
        return TranscribeResult()
    monkeypatch.setattr(api.transcribe_mod, "transcribe", run)
    assert command.run([SOURCE, "--vocabulary", "Korky Paul,NASA", "--vocabulary", "Celia"]) == 0
    assert received["vocabulary"] == ["Korky Paul", "NASA", "Celia"]
