"""Hand picks timed against a supplied transcript move with it when the sync check shifts it."""
from __future__ import annotations

import pytest

from myzing.factory import pipeline, transcript_sync
from myzing.factory.tools import FactoryError


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "p"
    pipeline._write(root / "transcript.json", [{"s": float(i), "e": i + 1.0, "text": f"w{i}"} for i in range(0, 4000, 2)])
    pipeline._write(root / "factory.json", {"transcript_sync": {"status": "pending"}, "transcript_offset": 0.0})
    pipeline._write(root / "source.json", {"media": str(tmp_path / "ep.mp4")})
    return root


def test_transcript_basis_waits_for_the_sync_offset_and_moves_once(project, monkeypatch):
    pipeline.add_clip(project, 1373.36, 1452.96, basis="transcript")
    pipeline.add_clip(project, 100, 140)                       # a video-time pick never moves
    moments = pipeline.load_moments(project)["moments"]
    assert moments[0]["basis"] == "transcript" and "basis" not in moments[1]
    monkeypatch.setattr(transcript_sync, "check", lambda *a, **k: {"status": "matched", "method": "probes", "probes": [{}, {}], "offset": 322.917})
    monkeypatch.setattr(pipeline, "_shift_transcript", lambda project, media, offset: pipeline._read(project / "transcript.json"))
    cfg = pipeline._read(project / "factory.json")
    pipeline._sync_transcript(project, project / "ep.mp4", cfg, pipeline._read(project / "transcript.json"), lambda m: None)
    moments = pipeline.load_moments(project)["moments"]
    assert (moments[0]["start"], moments[0]["end"]) == (1696.277, 1775.877) and "basis" not in moments[0]
    assert (moments[1]["start"], moments[1]["end"]) == (100, 140)
    pipeline._rebase_moments(project, 322.917)                 # a second pass finds nothing left to move
    assert pipeline.load_moments(project)["moments"][0]["start"] == 1696.277


def test_transcript_basis_after_the_check_uses_the_saved_offset(project):
    cfg = pipeline._read(project / "factory.json")
    pipeline._write(project / "factory.json", {**cfg, "transcript_sync": {"status": "matched"}, "transcript_offset": 30.0})
    pipeline.add_clip(project, 100, 140, basis="transcript")
    m = pipeline.load_moments(project)["moments"][0]
    assert (m["start"], m["end"]) == (130, 170) and "basis" not in m


def test_skipped_check_keeps_transcript_times(project, monkeypatch):
    pipeline.add_clip(project, 100, 140, basis="transcript")
    monkeypatch.setattr(transcript_sync, "check", lambda *a, **k: {"status": "skipped", "method": "no_cached_model"})
    cfg = pipeline._read(project / "factory.json")
    pipeline._sync_transcript(project, project / "ep.mp4", cfg, [], lambda m: None)
    m = pipeline.load_moments(project)["moments"][0]
    assert (m["start"], m["end"]) == (100, 140) and "basis" not in m


def test_unknown_basis_is_refused(project):
    with pytest.raises(FactoryError):
        pipeline.add_clip(project, 100, 140, basis="audio")


def test_a_full_run_keeps_the_moved_pick(project, monkeypatch):
    """_moments loads moments.json before the sync check; it must not write the old times back."""
    pipeline.add_clip(project, 1373.36, 1452.96, basis="transcript")
    monkeypatch.setattr(transcript_sync, "check", lambda *a, **k: {"status": "matched", "method": "probes", "probes": [{}, {}], "offset": 322.917})
    monkeypatch.setattr(pipeline, "_shift_transcript", lambda project, media, offset: pipeline._read(project / "transcript.json"))
    monkeypatch.setattr(pipeline, "_transcript", lambda project, media, say, vocab=None: pipeline._read(project / "transcript.json"))
    words = [{"w": f"w{i}", "s": float(i), "e": i + .5} for i in range(1600, 1900)]
    pipeline._write(project / "words.json", words)
    cfg = {**pipeline._read(project / "factory.json"), "moments": 0}
    moments = pipeline._moments(project, None, project / "ep.mp4", cfg, lambda m: None)
    assert 1690 <= moments[0]["start"] <= 1700 and moments[0]["end"] > 1770
    assert pipeline.load_moments(project)["moments"][0]["start"] == moments[0]["start"]
