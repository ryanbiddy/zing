"""Backward compatibility and offline-facing music contracts."""
import json
import math
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


def test_known_speech_envelope_holds_clause_gaps_with_smooth_ramps():
    from myzing.music.ducking import passages, weights
    spans = [[1.0, 3.0], [3.2, 5.2], [5.5, 7.5], [7.9, 9.9], [10.5, 12.5], [13.5, 15.5]]
    held = passages(spans, .8)
    # Gaps of 0.2-0.6 s join one passage; the 1.0 s pause stays a real pause.
    assert held == [[1.0, 12.5], [13.5, 15.5]]
    w = weights(held, 17, .2, .8)
    assert min(w[1000:12501]) == 1.0  # fully ducked through every held clause gap
    assert min(w[12500:13500]) < .01  # recovered inside the 1.0 s pause
    assert w[800] < 1e-9 and w[1000] == 1.0 and 0 < w[900] < 1  # pre-duck ends at the first word
    # Raised-cosine ramps: no step larger than the steepest attack slope allows.
    assert max(abs(a - b) for a, b in zip(w, w[1:])) <= math.pi / 2 / 200 + 1e-9


def test_span_count_is_validated_with_a_clear_message():
    from myzing.music.ducking import MAX_SPANS
    spans = [[i, i + .5] for i in range(MAX_SPANS + 1)]
    with pytest.raises(ValueError, match=f"{MAX_SPANS}-span limit"):
        MusicPlan(speech_spans=spans)
    assert len(MusicPlan(speech_spans=spans[:MAX_SPANS]).speech_spans) == MAX_SPANS


def test_pause_windows_of_a_legal_plan_pass_the_window_limit(monkeypatch):
    # The complement of MAX_SPANS separated spans has MAX_SPANS + 1 windows.
    from myzing.music import measurement
    from myzing.music.ducking import MAX_SPANS
    spans = [[i + .5, i + 1] for i in range(MAX_SPANS)]
    pauses = measurement.complement(spans, MAX_SPANS + 1)
    assert len(pauses) == MAX_SPANS + 1

    class Reached(Exception):
        pass

    def stop(path):
        raise Reached
    monkeypatch.setattr(measurement, "local_file", stop)
    with pytest.raises(Reached):
        measurement.window_loudness("music.wav", pauses, MAX_SPANS + 1)
    with pytest.raises(ValueError, match="span limit"):
        measurement.window_loudness("music.wav", [[i, i + .5] for i in range(MAX_SPANS + 2)], MAX_SPANS + 3)


def test_balanced_span_expression_stays_shallow():
    from myzing.music.ducking import span_expression
    expr = span_expression([[i, i + .5] for i in range(512)])
    depth = deepest = 0
    for ch in expr:
        depth += ch == "("
        depth -= ch == ")"
        deepest = max(deepest, depth)
    assert expr.count("between(") == 512 and deepest <= 11


def _structure_map(duration=600, truncated=True, moments=()):
    from myzing.audio.structure import Structure
    energy = [{"time": t * .25, "rms_dbfs": -20.0, "low_db": -30.0, "flux": 0.0,
               "onsets_per_second": 0.0, "attacks_per_second": 0.0} for t in range(int(min(duration, 60) * 4))]
    return AudioMap("long.wav", duration, 22050, 600, truncated, Tempo(), [], [], [], Loudness(-20, 2, -5),
                    structure=Structure(energy=energy, moments=list(moments), vocals={"status": "not_detected"}))


def test_advice_reports_true_track_length_not_the_analysis_cap():
    from myzing.music.advice import rate
    reason = next(r["reason"] for r in rate(_structure_map(), length=30, source_duration=900).reasons
                  if r["topic"] == "duration")
    assert reason.startswith("900.00s available (analysis covers the first 600s)")
    unknown = next(r["reason"] for r in rate(_structure_map(), length=30).reasons if r["topic"] == "duration")
    assert unknown.startswith("More than 600s available")


def _plan_inputs(tmp_path, m, sequence, studies):
    from types import SimpleNamespace
    from myzing.brief.models import Brief
    from myzing.project.api import hash_file
    path = tmp_path / "music.wav"
    path.write_bytes(b"cached analysis; no decoder invoked")
    m.source = str(path)
    asset = SimpleNamespace(id="m", path=str(path), state="ready", sha256=hash_file(path),
                            probe=SimpleNamespace(has_audio=True, duration=m.duration_seconds))
    return (sequence, studies, Brief(music={"source": "supplied files", "files": ["m"]}),
            SimpleNamespace(assets=[asset]), tmp_path, 2, {}, {}, {asset.sha256: m})


def test_track_shorter_than_edit_warns_instead_of_ending_silently(tmp_path, monkeypatch):
    from myzing.director.models import ClipStudy
    from myzing.director.selection import Candidate
    from myzing.music import planning, measurement
    monkeypatch.setattr(measurement, "window_loudness", lambda *args: -20)
    m = _structure_map(6, False)
    sequence = [Candidate("a", "a", 0, 9, 0, 0, None, "", False, True)]
    _, _, tracks, evidence = planning.plan_music(*_plan_inputs(tmp_path, m, sequence, [ClipStudy("a", "a.mp4", "a", 9, "ready")]))
    assert tracks[0].src_out == 6
    assert any("supplies 6.00s for a 9.00s edit" in w and "does not loop" in w for w in evidence.warnings)
    end = next(d for d in evidence.decisions if d["kind"] == "music_end")
    assert "track ends before the edit" in end["reason"]


def test_unmeasurable_visual_change_does_not_claim_an_alignment(tmp_path, monkeypatch):
    from myzing.audio.structure import Moment
    from myzing.director.models import ClipStudy
    from myzing.director.selection import Candidate
    from myzing.music import planning, measurement
    from myzing.schemas import Shot
    monkeypatch.setattr(measurement, "window_loudness", lambda *args: -20)
    monkeypatch.setattr(planning, "visual_changes", lambda *args: [0.0])
    m = _structure_map(40, False, [Moment(12.0, .9, "drop", .8, "test drop")])
    studies = [ClipStudy(k, f"{k}.mp4", k, 12, "ready", shots=[Shot(0, 0, 12)]) for k in "ab"]
    sequence = [Candidate("a", "a", 0, 3, 0, 0, None, "", False, True), Candidate("b", "b", 0, 5, 0, 0, None, "", False, True)]
    _, _, tracks, evidence = planning.plan_music(*_plan_inputs(tmp_path, m, sequence, studies))
    kinds = [d["kind"] for d in evidence.decisions]
    assert "moment_alignment_skipped" in kinds and "drop_alignment" not in kinds
    assert not any("Largest measured" in d.get("reason", "") for d in evidence.decisions)
    assert tracks[0].src_in == 0


def test_music_spans_are_tied_to_the_planned_clip_timeline():
    from types import SimpleNamespace
    from myzing.music.models import stale_timeline, timeline_of
    clips = [SimpleNamespace(asset_id="a", src_in=0, src_out=3, timeline_start=0),
             SimpleNamespace(asset_id="b", src_in=2, src_out=6, timeline_start=3)]
    plan = MusicPlan(speech_spans=[[0, 1]], timeline=timeline_of(clips))
    assert stale_timeline(plan, clips) is None
    clips[1].timeline_start = 2.5  # e.g. an overlapping transition pulled the clip earlier
    assert "re-run zing plan drafts" in stale_timeline(plan, clips)
    assert stale_timeline(MusicPlan(speech_spans=[[0, 1]]), clips) is None


def test_framing_splits_keep_the_planned_speech_timeline():
    from types import SimpleNamespace
    from myzing.director.selection import Candidate
    from myzing.music.models import stale_timeline, timeline_of
    # The director plans speech spans on its candidate sequence; reframe then
    # splits clips at shot boundaries (director and per-aspect deliveries).
    sequence = [Candidate("a", "a", 1.0, 4.0, 0, 0, None, "", False, True),
                Candidate("b", "b", 2.0, 5.0, 0, 0, None, "", False, True)]
    plan = MusicPlan(speech_spans=[[0, 1]], timeline=timeline_of(sequence))
    split = [SimpleNamespace(asset_id="a", src_in=1.0, src_out=2.5, timeline_start=0.0),
             SimpleNamespace(asset_id="a", src_in=2.5, src_out=4.0, timeline_start=1.5),
             SimpleNamespace(asset_id="b", src_in=2.0, src_out=3.0, timeline_start=3.0),
             SimpleNamespace(asset_id="b", src_in=3.0, src_out=5.0, timeline_start=4.0)]
    assert stale_timeline(plan, split) is None
    assert stale_timeline(plan, list(reversed(split))) is None  # composition order is by timeline
    split[3].src_in, split[3].src_out = 3.2, 5.2  # a retrimmed piece is a different timeline
    assert stale_timeline(plan, split) is not None
