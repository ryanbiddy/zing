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
    from myzing.music.ducking import duck_passages, release_gap, weights
    assert release_gap() == pytest.approx(1.3)  # 0.2 attack + 0.8 release + 0.3 s audible plateau
    spans = [[1.0, 3.0], [3.2, 5.2], [5.5, 7.5], [7.9, 9.9], [10.5, 12.5], [13.5, 15.5], [17.0, 19.0]]
    held = duck_passages(spans, 21)
    # Gaps of 0.2-1.0 s join one passage; only the 1.5 s pause is a real pause.
    assert held == [[1.0, 15.5], [17.0, 19.0]]
    w = weights(held, 21, .2, .8)
    assert min(w[1000:15501]) == 1.0  # fully ducked through every held gap, including 1.0 s
    plateau = sum(1 for v in w[15500:17000] if v < 1e-9) / 1000
    assert plateau >= .3 - 1e-9  # the released pause really settles at the recovered level
    assert w[800] < 1e-9 and w[1000] == 1.0 and 0 < w[900] < 1  # pre-duck ends at the first word
    # Raised-cosine ramps: no step larger than the steepest attack slope allows.
    assert max(abs(a - b) for a, b in zip(w, w[1:])) <= math.pi / 2 / 200 + 1e-9


def test_a_sentence_gap_just_over_the_hold_no_longer_pumps():
    # LISTEN1: a 0.84 s gap released under the hold-only rule and lifted the
    # bed 8.4 dB for half a second before the next pre-duck.
    from myzing.music.ducking import duck_passages, passages, weights
    spans = [[4.64, 8.08], [8.92, 12.62]]
    assert len(passages(spans, .8)) == 2  # the old rule
    held = duck_passages(spans, 14)
    assert held == [[4.64, 12.62]]
    assert min(weights(held, 14, .2, .8)[4640:12621]) == 1.0
    # A user can still ask for faster ducking; the plateau rule follows the settings.
    assert len(duck_passages(spans, 14, hold=0, attack=.05, release=.2, plateau=.3)) == 2


def test_the_bed_starts_and_ends_ducked_when_speech_is_close_to_the_edges(tmp_path):
    import array
    import wave
    from myzing.music.ducking import duck_passages, write_envelope
    # First word 0.33 s in (LISTEN1 talking edit): no 0.25 s at pause level first.
    held = duck_passages([[.33, 8.08], [8.92, 12.62]], 12.95)
    assert held == [[0.0, 12.95]]
    path = write_envelope(tmp_path / "duck.wav", held, 12.95, depth_db=9, attack=.2, release=.8)
    with wave.open(str(path)) as w:
        gains = array.array("i", w.readframes(w.getnframes()))
    assert max(gains) == pytest.approx((2 ** 31 - 1) * 10 ** (-9 / 20), rel=1e-6)  # ducked from sample 0 to the end
    # A real intro and outro keep their full-level music.
    assert duck_passages([[1.2, 5.0]], 7.0) == [[1.2, 5.0]]
    assert duck_passages([[.5, 5.0]], 5.9) == [[0.0, 5.9]]


def test_bed_gain_points_ramp_smoothly_and_never_raise_the_bed(tmp_path):
    from myzing.music.ducking import gain_at, gain_curve, write_envelope
    points = [[0, 0], [5.8, 0], [6.2, -14], [12, -14]]
    assert gain_at(points, 3) == 0 and gain_at(points, 6.0) == pytest.approx(-7) and gain_at(points, 9) == -14
    curve = gain_curve(points, 12001)
    assert curve[5800] == 0 and curve[6200] == pytest.approx(-14) and curve[-1] == -14
    assert all(b <= a + 1e-12 for a, b in zip(curve, curve[1:]))
    assert max(abs(a - b) for a, b in zip(curve, curve[1:])) < .06  # 14 dB over 0.4 s, raised cosine
    with pytest.raises(ValueError, match="<= 0 dB"):
        write_envelope(tmp_path / "x.wav", [], 2, depth_db=9, attack=.2, release=.8, gain_points=[[0, 3]])
    with pytest.raises(ValueError, match="bed_gain_points"):
        MusicPlan(bed_gain_points=[[0, 0], [1, 2]])
    assert MusicPlan(bed_gain_points=points).duck()["gain_points"] == points


def test_quiet_clips_get_their_own_bed_level_moved_under_the_louder_voice():
    from myzing.music.planning import clip_offsets, gain_points
    levels = [{"asset_id": "loud", "output_start": 0, "output_end": 6, "speech_lufs": -14.0, "has_speech": True},
              {"asset_id": "broll", "output_start": 6, "output_end": 7, "speech_lufs": None, "has_speech": False},
              {"asset_id": "quiet", "output_start": 7, "output_end": 13, "speech_lufs": -28.0, "has_speech": True}]
    offsets, notes = clip_offsets(levels, -14.0)
    assert offsets == [0.0, 0.0, -14.0] and notes == []  # B-roll follows its neighbour
    spans = [[.5, 5.5], [7.6, 12.0]]
    points = gain_points(levels, offsets, spans, 13)
    # LISTEN1: a 0.4 s, 9 dB ramp in the silent gap at the cut was heard as a
    # swell. The drop now ends at the loud voice's last word (5.5 s), over 1 s.
    assert points == [[0.0, 0.0], [4.5, 0.0], [5.5, -14.0], [13, -14.0]]
    # Quiet to loud: the rise starts at the louder clip's first word (7.6 s).
    assert gain_points(levels[::-1], offsets[::-1], spans, 13) == [[0.0, -14.0], [7.6, -14.0], [8.6, 0.0], [13, 0.0]]
    assert gain_points(levels, [0.0, 0.0, 0.0], spans, 13) == []
    capped, notes = clip_offsets([{**levels[0]}, {**levels[2], "speech_lufs": -44.0}], -14.0)
    assert capped == [0.0, -24.0] and "only 24 dB" in notes[0]
    _, notes = clip_offsets([{**levels[0]}, {**levels[2], "speech_lufs": None}], -14.0)
    assert "below the loudness gate" in notes[0]


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


def test_clauses_under_a_bed_ramp_report_but_do_not_warn_for_a_quieter_bed():
    from myzing.music.ducking import ramp_windows
    from myzing.music.measurement import band_warning, clause_report
    ramps = ramp_windows([[0, -10], [3.44, -10], [4.44, 0], [12, 0]])
    assert ramps == [[3.44, 4.44]]
    spans = [[.33, 1.85], [3.44, 4.12], [4.64, 8.08], [8.92, 9.5]]
    rows, summary, outside = clause_report([-27, -11, -14, -14], [-48, -40, -35, -30], spans, ramps=ramps)
    assert [r["bed_ramp"] for r in rows] == [False, True, False, False]
    assert summary["outside_band"] == 1 and summary["above_band_under_bed_ramp"] == 1 and outside == [rows[3]]  # 29 LU in the ramp is reported, not warned
    assert "16 LU at 8.92-9.50s (the bed sits too close to the speech)" in band_warning(outside, 4, "measure")


def test_quiet_dialogue_is_matched_per_recording_with_a_compressor_only_where_peaks_need_it():
    from myzing.music.dialogue import filters, plan_gains, row_at
    # LISTEN1's talking edit: Tears of Steel at -26.7 LUFS with -4.2 dBFS peaks
    # ("be honest"); two trims of one Korky Paul recording at -12.8 and -14.1 LUFS.
    levels = [{"asset_id": "tos-lab", "output_start": 0, "output_end": 3.2, "speech_lufs": -26.7, "speech_seconds": 1.88},
              {"asset_id": "korky", "output_start": 3.2, "output_end": 8.5, "speech_lufs": -12.8, "speech_seconds": 4.12},
              {"asset_id": "korky", "output_start": 8.5, "output_end": 12.95, "speech_lufs": -14.1, "speech_seconds": 3.7}]
    rows, notes = plan_gains(levels, [-4.2, -3.1, -3.1])
    # One gain per recording: the Korky jump cut gets no +1.3 dB step (heard in LISTEN1).
    [row] = rows
    assert row["asset_id"] == "tos-lab" and row["gain_db"] == pytest.approx(13.33, abs=.02)
    assert row["asset_speech_lufs"] == pytest.approx(-26.7) and row["target_lufs"] == pytest.approx(-13.37, abs=.01)
    assert row["compressor"]["threshold_db"] == pytest.approx(-7.37, abs=.01)
    assert len(notes) == 1 and "raised 13.3 dB" in notes[0] and "pumping" in notes[0]
    assert row_at(rows, 1.0) is row and row_at(rows, 5.0) is None and row_at(rows, 9.0) is None
    chain = filters(row)
    assert chain[0] == "volume=13.330000dB" and chain[1].startswith("acompressor=threshold=0.428")
    assert filters(None) == ()
    # Within 6 LU nothing changes; beyond 18 dB the boost caps and says so.
    assert plan_gains(levels[1:], [-3.1, -3.1]) == ([], [])
    capped, notes = plan_gains([levels[1], {**levels[0], "speech_lufs": -38.8}], [-3.1, -20.0])
    assert capped[0]["gain_db"] == 18 and capped[0]["compressor"] is None and "raised it only 18 dB" in notes[0]
    with pytest.raises(ValueError, match="dialogue_gains"):
        MusicPlan(dialogue_gains=[{"start": 0, "end": 1, "gain_db": 30}])


def test_audio_fades_only_over_speech_free_edges_where_the_source_changes():
    from types import SimpleNamespace
    from myzing.music.dialogue import edge_fades
    clip = lambda asset, start, duration, src_in: SimpleNamespace(asset_id=asset, timeline_start=start, duration=duration,
                                                                  src_in=src_in, src_out=src_in + duration)
    # LISTEN1 talking edit: Tears of Steel's score stopped dead at the 3.2 s cut.
    clips = [clip("tos-lab", 0, 3.2, 9.5), clip("korky", 3.2, 2.0, .1), clip("korky", 5.2, 3.3, 2.1), clip("korky", 8.5, 4.45, 5.5)]
    spans = [[.33, 1.85], [2.29, 2.65], [3.44, 4.12], [4.64, 8.08], [8.92, 12.62]]
    fades = edge_fades(clips, spans)
    assert fades[0] == ("afade=t=out:st=2.900000:d=0.300000",)    # 0.55 s speech-free tail
    assert fades[1] == ("afade=t=in:st=0:d=0.100000",)            # 0.24 s before "Hello"
    assert fades[2] == fades[3] == ()  # 5.4 -> 5.5 s jump cut in one recording: room tone continues (a fade dipped it)
    # A word right at the cut gets no fade.
    assert edge_fades([clip("a", 0, 2, 0), clip("b", 2, 2, 0)], [[.5, 1.99], [2.01, 3]]) == [(), ()]


def _envelope_db(spans, duration, points):
    from myzing.music.ducking import duck_passages, gain_curve, weights
    w = weights(duck_passages(spans, duration), duration, .2, .8)
    return [-9 * a + b for a, b in zip(w, gain_curve(points, len(w)))]


ATTACK_SLOPE = 9 * math.pi / (2 * .2) / 1000  # dB per 1 ms control sample: the default pre-duck's steepest


def test_bed_gain_changes_stay_under_the_louder_voice_and_never_outrun_the_pre_duck():
    from myzing.music.planning import gain_points
    clip = lambda a, b: {"output_start": a, "output_end": b, "asset_id": "x"}
    # Grok: offsets 0/-24/0 on a 1.15 s edit used to squeeze a 24 dB rise into
    # 0.15 s (0.25 dB per sample). No clip has room, so the bed does not move.
    spans = [[.05, .35], [.45, .75], [.85, 1.1]]
    points = gain_points([clip(0, .4), clip(.4, .8), clip(.8, 1.15)], [0.0, -24.0, 0.0], spans, 1.15)
    assert points == [] and MusicPlan(speech_spans=spans, bed_gain_points=points)
    # Twelve 0.7 s clips alternating 0 / -10 dB used to chain ramps late (the
    # bed sat at -8.5 dB under a loud clip and 0 under a quiet one) and pile
    # 10 dB steps at the edit end. Now the bed goes down once and stays down.
    levels = [clip(i * .7, (i + 1) * .7) for i in range(12)]
    spans = [[i * .7 + .1, i * .7 + .6] for i in range(12)]
    points = gain_points(levels, [0.0 if i % 2 == 0 else -10.0 for i in range(12)], spans, 8.4)
    assert points == [[0.0, 0.0], [0.1, 0.0], [0.6, -10.0], [8.4, -10.0]]
    curve = _envelope_db(spans, 8.4, points)
    assert max(abs(a - b) for a, b in zip(curve, curve[1:])) <= ATTACK_SLOPE + 1e-9
    # A drop that ended at the loud voice's last word once overlapped that
    # clause's pre-duck (1.5x the attack slope; 1.08 dB per 10 ms at 24 dB).
    # Ramps now stay inside one held passage; a big drop that cannot fit
    # there goes down under the quieter clip instead.
    spans = [[.5, 1.0], [2.6, 3.0], [6.2, 7.0]]
    for delta, expected in ((6, [2.6, 3.0]), (18, [2.6, 3.0]), (24, [6.2, 7.2])):
        points = gain_points([clip(0, 3.1), clip(3.1, 8)], [0.0, -float(delta)], spans, 8)
        assert [p[0] for p in points[1:3]] == expected, (delta, points)
        curve = _envelope_db(spans, 8, points)
        assert max(abs(a - b) for a, b in zip(curve, curve[1:])) <= ATTACK_SLOPE + 1e-9, delta
    # Hand-edited evidence (the warnings point editors at bed_gain_points)
    # cannot step or zipper the bed.
    with pytest.raises(ValueError, match="so the bed does not click"):
        MusicPlan(bed_gain_points=[[0, 0], [3, 0], [3, -20], [6, -20]])
    with pytest.raises(ValueError, match="allow at least 0.444s"):
        MusicPlan(bed_gain_points=[[0, 0], [3, 0], [3.2, -20]])
    assert MusicPlan(bed_gain_points=[[0, 0], [3, 0], [3.45, -20]])


def test_duck_boundaries_follow_one_at_least_rule():
    from myzing.music.ducking import duck_passages
    # A pause of at least 1.3 s releases (3.8 - 2.5 is 1.2999999999999998 in floats); shorter is held.
    assert len(duck_passages([[1, 2.5], [3.8, 5]], 7)) == 2
    assert len(duck_passages([[1, 2.5], [2.5 + 1.3, 5]], 7)) == 2
    assert len(duck_passages([[1, 2.5], [3.79, 5]], 7)) == 1
    # A lead-in of at least max(hold, attack + plateau) = 0.8 s plays at pause level.
    assert duck_passages([[.8, 2]], 5)[0][0] == .8 and duck_passages([[2.3 - 1.5, 2]], 5)[0][0] == pytest.approx(.8)
    assert duck_passages([[.79, 2]], 5)[0][0] == 0.0
    # A tail of at least max(hold, release + plateau) = 1.1 s recovers.
    assert duck_passages([[1, 2.9]], 4)[-1][1] == 2.9 and duck_passages([[1, 2.91]], 4)[-1][1] == 4


def test_capped_bed_and_hot_dialogue_messages_and_limits():
    from myzing.music.dialogue import plan_gains
    from myzing.music.planning import clip_offsets
    # Grok: 30 LU under with a 24 dB cap leaves 6 LU, not 54.
    _, notes = clip_offsets([{"asset_id": "loud", "output_start": 0, "output_end": 6, "speech_lufs": -14.0, "has_speech": True},
                             {"asset_id": "quiet", "output_start": 6, "output_end": 12, "speech_lufs": -44.0, "has_speech": True}], -14.0)
    assert "speaks 30.0 LU below" in notes[0] and "sit 6.0 LU closer" in notes[0]
    # Grok: loudest speech at -4 LUFS put the compressor threshold at +2 dBFS and failed validation.
    levels = [{"asset_id": "hot", "output_start": 0, "output_end": 3, "speech_lufs": -4.0, "speech_seconds": 2},
              {"asset_id": "quiet", "output_start": 3, "output_end": 6, "speech_lufs": -20.0, "speech_seconds": 2}]
    rows, notes = plan_gains(levels, [-.5, -6.0])
    assert rows[0]["compressor"]["threshold_db"] == -2.0 and "above -2.0 dBFS" in notes[0]
    assert MusicPlan(speech_spans=[[0, 1]], dialogue_gains=rows).dialogue_gains == rows


def test_speech_free_trims_of_a_raised_recording_count_toward_its_peak():
    from types import SimpleNamespace
    from myzing.music.dialogue import clip_peaks, plan_gains
    # A quiet recording whose speech peaks at -24.8 dBFS and whose speech-free
    # trim holds a -3 dBFS slam: measuring only the speech clips left the
    # +15 dB gain uncompressed and put the slam 12.5 dB into the final limiter.
    levels = [{"asset_id": "loud", "output_start": 0, "output_end": 6, "speech_lufs": -12.9, "speech_seconds": 4},
              {"asset_id": "quiet", "output_start": 6, "output_end": 12, "speech_lufs": -27.9, "speech_seconds": 4},
              {"asset_id": "quiet", "output_start": 12, "output_end": 14.5, "speech_lufs": None, "speech_seconds": 0}]
    sequence = [SimpleNamespace(asset_id=v["asset_id"], start=i) for i, v in enumerate(levels)]
    measured = []
    peaks = clip_peaks(sequence, levels, lambda c: measured.append(c.start) or [-3.5, -24.8, -3.0][c.start])
    assert measured == [0, 1, 2] and peaks == [-3.5, -24.8, -3.0]
    rows, notes = plan_gains(levels, peaks)
    assert [r["peak_dbfs"] for r in rows] == [-3.0, -3.0] and all(r["compressor"] for r in rows)
    assert "can still meet the final limiter with up to about 14 dB" in notes[0]
    # Within 6 LU nothing is decoded at all.
    assert clip_peaks(sequence[:1], levels[:1], lambda c: 1 / 0) == [None]


def test_the_default_bed_sits_at_the_loud_end_of_the_band():
    # Ryan's call after LISTEN1 (the 21 LU bed was heard as buried): the
    # loudest bed that keeps every talking acceptance clause >= 18 LU under
    # its speech. One default feeds the plan, the clause report and match.
    from myzing.music.ducking import DEFAULT_SPEECH_TO_MUSIC_LU
    from myzing.music.measurement import CLAUSE_BAND_LU, CLAUSE_TARGET_LU
    assert MusicPlan().speech_to_music_lu == DEFAULT_SPEECH_TO_MUSIC_LU == CLAUSE_TARGET_LU == 19.2
    assert CLAUSE_BAND_LU == (18.0, 24.0)
