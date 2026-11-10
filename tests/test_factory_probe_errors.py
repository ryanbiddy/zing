"""A failed decoder is never reported as a silent sync probe."""
import pytest

from myzing.factory import judge, pipeline, source, transcript_sync
from myzing.study import transcribe
from test_factory_transcript_sync import episode, offline, project

ERROR = "transcription failed: open() got an unexpected keyword argument 'metadata_errors'"


@pytest.fixture
def speech(monkeypatch):
    monkeypatch.setattr(transcript_sync, "model", lambda: "small")
    monkeypatch.setattr(source, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(source, "run", lambda *a, **kw: None)
    monkeypatch.setattr(source, "_speech", transcribe_source)


transcribe_source = source._speech


@pytest.mark.parametrize("warnings,method", [([], "too_little_speech"), ([ERROR], "probe_error"),
                                           (["transcription failed: decoder read past the end of its buffer"], "probe_error"),
                                           (["transcription skipped: model unavailable"], "probe_error")])
def test_wrapped_speech_result_keeps_crash_separate_from_silence(monkeypatch, episode, speech, warnings, method):
    monkeypatch.setattr(transcribe, "transcribe", lambda *a, **kw: transcribe.TranscribeResult(warnings=warnings))
    result = transcript_sync.check(episode[0], [{"s": 0, "e": 10, "text": "some words"}])
    assert result["method"] == method
    if warnings:
        assert warnings[0] in result["error"]
        assert all("error" in p and "note" not in p for p in result["probes"])
    else:
        assert all(p["note"] == "No speech heard." for p in result["probes"])


def test_run_prints_the_real_probe_error(monkeypatch, tmp_path, episode, speech):
    monkeypatch.setattr(transcribe, "transcribe", lambda *a, **kw: transcribe.TranscribeResult(warnings=[ERROR]))
    root = project(tmp_path, episode)
    said = []
    result = pipeline.run(root, judge.Judge(root), say=said.append)
    assert result["settings"]["transcript_sync"]["method"] == "probe_error"
    assert any(ERROR in text for text in said)
    assert not any("too little speech" in text for text in said)
