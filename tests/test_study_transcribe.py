"""Offline tests for transcription: faster-whisper mocked at the two seams
(_load_model / _run_model); no model download, no audio decode."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from myzing.schemas import Word
from myzing.study import transcribe


def fake_load(monkeypatch, name_seen: list | None = None):
    def load(name):
        if name_seen is not None:
            name_seen.append(name)
        return "MODEL", "auto", "int8_float16", "1.2.1"
    monkeypatch.setattr(transcribe, "_load_model", load)


def fake_run(monkeypatch, words, language="en", prob=0.98):
    def run(model, media_path):
        return words, language, prob
    monkeypatch.setattr(transcribe, "_run_model", run)


def test_transcribe_returns_words_and_provenance(monkeypatch):
    fake_load(monkeypatch)
    fake_run(monkeypatch, [Word("stop", 0.1, 0.32, 0.995), Word("scrolling", 0.32, 0.8, 0.71)])

    result = transcribe.transcribe(Path("media.mp4"))

    assert [w.text for w in result.words] == ["stop", "scrolling"]
    assert result.words[1].confidence == 0.71
    assert result.warnings == []
    p = result.provenance
    assert p["whisper_model"] == transcribe.DEFAULT_MODEL
    assert p["language"] == "en"
    assert p["vad_filter"] is True
    assert p["condition_on_previous_text"] is False


def test_model_env_override(monkeypatch):
    seen: list = []
    fake_load(monkeypatch, seen)
    fake_run(monkeypatch, [])
    monkeypatch.setenv(transcribe.ENV_MODEL, "large-v3-turbo")

    transcribe.transcribe(Path("m.mp4"))

    assert seen == ["large-v3-turbo"]


def test_missing_faster_whisper_is_honest_skip(monkeypatch):
    def load(name):
        raise ImportError("No module named 'faster_whisper'")
    monkeypatch.setattr(transcribe, "_load_model", load)

    result = transcribe.transcribe(Path("m.mp4"))

    assert result.words == []
    assert any("faster-whisper not installed" in w for w in result.warnings)
    assert any("myzing[study]" in w for w in result.warnings)


def test_model_load_failure_is_honest_skip(monkeypatch):
    def load(name):
        raise RuntimeError("download failed: connection reset")
    monkeypatch.setattr(transcribe, "_load_model", load)

    result = transcribe.transcribe(Path("m.mp4"))

    assert result.words == []
    assert any("could not be loaded" in w and "large-v2" in w for w in result.warnings)


def test_transcription_crash_is_honest_skip(monkeypatch):
    fake_load(monkeypatch)

    def run(model, media_path):
        raise RuntimeError("cuda out of memory")
    monkeypatch.setattr(transcribe, "_run_model", run)

    result = transcribe.transcribe(Path("m.mp4"))

    assert result.words == []
    assert any("transcription failed" in w for w in result.warnings)


def test_long_form_routes_to_batched_pipeline(monkeypatch):
    fake_load(monkeypatch)
    called = {}

    def batched(model, path):
        called["batched"] = True
        return [Word("hi", 0.0, 0.2, 0.9)], "en", 0.99
    monkeypatch.setattr(transcribe, "_run_model_batched", batched)
    monkeypatch.setattr(
        transcribe, "_run_model",
        lambda m, p: (_ for _ in ()).throw(AssertionError("sequential used")),
    )

    result = transcribe.transcribe(Path("long.mp4"), duration=600.0)

    assert called.get("batched")
    assert result.provenance["pipeline"] == "batched(batch_size=8)"
    assert result.warnings == []


def test_short_form_stays_sequential(monkeypatch):
    fake_load(monkeypatch)
    fake_run(monkeypatch, [])
    monkeypatch.setattr(
        transcribe, "_run_model_batched",
        lambda m, p: (_ for _ in ()).throw(AssertionError("batched used")),
    )

    result = transcribe.transcribe(Path("short.mp4"), duration=45.0)

    assert result.provenance["pipeline"] == "sequential"


def test_batched_failure_falls_back_to_sequential(monkeypatch):
    fake_load(monkeypatch)
    fake_run(monkeypatch, [Word("ok", 0.0, 0.2, 0.9)])

    def boom(model, path):
        raise RuntimeError("batch collation error")
    monkeypatch.setattr(transcribe, "_run_model_batched", boom)

    result = transcribe.transcribe(Path("long.mp4"), duration=600.0)

    assert [w.text for w in result.words] == ["ok"]
    assert result.provenance["pipeline"] == "sequential"
    assert any("fell back to sequential" in w for w in result.warnings)


def test_run_model_extracts_and_strips_words(monkeypatch):
    """_run_model's own parsing logic, driven with faux segment objects."""
    seg = SimpleNamespace(words=[
        SimpleNamespace(word=" stop", start=0.1, end=0.32, probability=0.9951),
        SimpleNamespace(word=" ", start=0.32, end=0.33, probability=0.5),
        SimpleNamespace(word=" scrolling!", start=0.33, end=0.8, probability=0.71),
    ])
    empty_seg = SimpleNamespace(words=None)
    info = SimpleNamespace(language="en", language_probability=0.98)

    class Model:
        def transcribe(self, path, **kw):
            assert kw["word_timestamps"] is True
            assert kw["vad_filter"] is True
            assert kw["condition_on_previous_text"] is False
            return iter([seg, empty_seg]), info

    words, language, prob = transcribe._run_model(Model(), Path("m.mp4"))

    assert [w.text for w in words] == ["stop", "scrolling!"]  # blank dropped
    assert words[0].confidence == 0.995  # rounded to 3
    assert (language, prob) == ("en", 0.98)


def test_batched_seam_overlap_is_normalized_to_monotonic_order():
    """SW-4: batched-pipeline segment seams can overlap by a fraction of
    a second, emitting out-of-order word starts (seen live: 2 inversions
    in 10,088 words on a 62-min study). Collection sorts by whisper's
    own timestamps — normalization, not fabrication."""
    seam_a = SimpleNamespace(words=[
        SimpleNamespace(word=" the", start=498.9, end=499.3, probability=0.9),
        SimpleNamespace(word=" military.", start=499.77, end=499.79, probability=0.9),
    ])
    seam_b = SimpleNamespace(words=[
        SimpleNamespace(word=" the", start=499.35, end=499.6, probability=0.9),
        SimpleNamespace(word=" army", start=499.6, end=500.0, probability=0.9),
    ])

    words = transcribe._collect_words([seam_a, seam_b])

    starts = [w.start for w in words]
    assert starts == sorted(starts)
    assert [w.text for w in words] == ["the", "the", "army", "military."]


def test_model_load_failure_points_at_doctor(monkeypatch):
    """Same consistency rule as shots: the missing-package path names
    pip, so the installed-but-broken path must name a next step too."""
    def load(name):
        raise RuntimeError("connection reset while downloading")
    monkeypatch.setattr(transcribe, "_load_model", load)

    result = transcribe.transcribe(Path("m.mp4"))

    (warning,) = result.warnings
    assert "could not be loaded" in warning and "zing doctor" in warning
