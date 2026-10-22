"""Backward compatibility and offline-facing music contracts."""
import json
import pytest
from myzing.audio import AudioMap, Loudness, Tempo
from myzing.music.models import MusicPlan
from myzing.music import command


def test_old_audio_maps_still_load_without_inventing_structure():
    old = AudioMap("old.wav", 10, 22050, 600, False, Tempo(), [], [], [], Loudness(None, None, None)).to_dict()
    old["version"] = 1
    old.pop("structure")
    loaded = AudioMap.from_dict(old)
    assert loaded.version == 1 and loaded.structure is None
    assert AudioMap.from_dict(loaded.to_dict()) == loaded


def test_music_evidence_rejects_invalid_times_and_roundtrips():
    p = MusicPlan(speech_spans=[[1, 2]])
    assert MusicPlan.from_dict(json.loads(p.to_json())) == p
    for span in ([2, 1], [-1, 2], [0, float("nan")]):
        with pytest.raises(ValueError):
            MusicPlan(speech_spans=[span])


def test_music_cli_and_mcp_have_actionable_missing_file_error(capsys):
    assert command.run(["check", "does-not-exist.wav", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False
    from myzing.mcp_server import h_music_check
    assert h_music_check(["does-not-exist.wav"])["ok"] is False


def test_metric_phrase_preferred_without_slicing_speech():
    from myzing.music.planning import retime
    from myzing.director.models import ClipStudy
    from myzing.director.selection import Candidate
    from myzing.schemas import Shot, Word
    studies = [ClipStudy("a", "a.mp4", "a", 12, "ready", shots=[Shot(0, 0, 12)],
                         words=[Word("Complete.", 1, 3)]),
               ClipStudy("b", "b.mp4", "b", 12, "ready", shots=[Shot(0, 0, 12)])]
    sequence = [Candidate("a", "a", 0, 3, 0, 1, 1, "Complete.", False, True),
                Candidate("b", "b", 0, 4, 0, 0, None, "", False, True)]
    selected, decisions = retime(sequence, studies, [3.01], [3.06], 0,
                                speech=True, required={}, forbidden={})
    assert selected[0].end == pytest.approx(3.06)
    assert decisions[0]["basis"] == "phrase"
    assert selected[0].end >= studies[0].words[-1].end


def test_music_ends_at_supported_phrase_with_fade(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from myzing.audio.structure import Structure
    from myzing.brief.models import Brief
    from myzing.director.models import ClipStudy
    from myzing.director.selection import Candidate
    from myzing.music import planning, measurement
    from myzing.project.api import hash_file
    path = tmp_path / "music.wav"
    path.write_bytes(b"cached analysis; no decoder invoked")
    m = AudioMap(str(path), 12, 22050, 600, False, Tempo(), [], [], [], Loudness(-20, 2, -5),
                 structure=Structure(phrases=[{"time": 8., "bars": 4}], vocals={"status": "unknown"}))
    asset = SimpleNamespace(id="m", path=str(path), state="ready", sha256=hash_file(path),
                            probe=SimpleNamespace(has_audio=True, duration=12))
    sequence = [Candidate("a", "a", 0, 9, 0, 0, None, "", False, True)]
    monkeypatch.setattr(measurement, "window_loudness", lambda *args: -20)
    result, _, tracks, evidence = planning.plan_music(sequence,
        [ClipStudy("a", "a.mp4", "a", 9, "ready")],
        Brief(music={"source": "supplied files", "files": ["m"]}),
        SimpleNamespace(assets=[asset]), tmp_path, 2, {}, {}, {asset.sha256: m})
    assert result == sequence  # Music may end early; footage retains its duration.
    assert tracks[0].src_out == 8
    end = next(d for d in evidence.decisions if d["kind"] == "music_end")
    assert end["evidence_time"] == 8 and end["fade_seconds"] == 1
