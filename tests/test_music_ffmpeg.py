"""Generated lavfi musical evidence and actual rendered stems; no downloads."""
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing.audio import analyze
from myzing.audio.media import decode_mono, SAMPLE_RATE
from myzing.composition import AssetRef, Composition, CompositionAudio, CompositionClip
from myzing.director.models import ClipStudy
from myzing.director.selection import Candidate
from myzing.music.advice import rate
from myzing.music.models import MusicPlan, attach
from myzing.music.planning import plan_music, retime
from myzing.project.api import hash_file
from myzing.render.composition import render_composition
from myzing.schemas import Shot, Word

pytestmark = pytest.mark.ffmpeg


@pytest.fixture
def np():
    return pytest.importorskip("numpy")


def audio(path, expr, duration=24):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"aevalsrc='{expr}':s=44100:d={duration}", "-c:a", "pcm_f32le", str(path)],
                   check=True, capture_output=True, timeout=60)
    return path


def video(path, color="red", duration=12):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color={color}:s=320x180:r=30:d={duration}",
                    "-f", "lavfi", "-i", f"sine=frequency=700:duration={duration}:sample_rate=48000", "-c:v", "libx264",
                    "-c:a", "aac", "-shortest", str(path)], check=True, capture_output=True, timeout=60)
    return path


def pulse(offset=.173, accented=True):
    accent = "if(lt(mod(t-%.6f,2),.08),.8,.25)" % offset if accented else ".4"
    return f"gte(t,{offset})*{accent}*exp(-100*mod(t-{offset},.5))*sin(2*PI*1000*t)"


def drop_track(path, *, pickup=False):
    # Build in the mids, a low-energy break at 6-8s, then sustained bass and
    # midrange energy from exactly 8s. A separate kick pulse supplies a grid.
    lead = "+if(between(t,7.6,7.82),.5*sin(2*PI*1800*t),0)" if pickup else ""
    return audio(path, f"({pulse()})*.25+if(lt(t,6),(.005+.002*t)*sin(2*PI*500*t),if(lt(t,8),.004*sin(2*PI*500*t),.3*sin(2*PI*70*t)+.18*sin(2*PI*500*t)))" + lead)


@pytest.mark.parametrize("offset", [.173, .25])
def test_accented_downbeats_and_metric_phrases(np, tmp_path, offset):
    m = analyze(audio(tmp_path / "accent.wav", pulse(offset), duration=40))
    assert abs(m.tempo.bpm - 120) < 1
    assert m.tempo.downbeat_status == "supported"
    assert m.structure.meter == 4
    expected = np.arange(offset, 40, 2)
    assert len(m.structure.bars) == len(expected)
    assert np.max(np.abs(np.array(m.structure.bars) - expected)) < 1 / 30
    assert {p["bars"] for p in m.structure.phrases} == {4, 8, 16}


def test_ambiguous_equal_accents_do_not_invent_meter(np, tmp_path):
    m = analyze(audio(tmp_path / "equal.wav", pulse(accented=False)))
    assert m.tempo.status == "steady"
    assert m.tempo.downbeat_status == "unknown"
    assert m.structure.bars == m.structure.phrases == []
    drone = analyze(audio(tmp_path / "drone.wav", ".1*sin(2*PI*100*t)"))
    assert not drone.beats and not drone.structure.bars
    assert not [m for m in drone.structure.moments if m.kind == "drop"]


def test_build_break_drop_is_sustained_and_localized(np, tmp_path):
    m = analyze(drop_track(tmp_path / "drop.wav"))
    drops = [v for v in m.structure.moments if v.kind == "drop"]
    assert len(drops) == 1, drops
    assert abs(drops[0].time - 8) <= .25
    assert drops[0].confidence >= .7
    assert abs(m.structure.intro_seconds - 8) <= .25
    pickup = analyze(drop_track(tmp_path / "pickup.wav", pickup=True))
    pickup_drops = [v for v in pickup.structure.moments if v.kind == "drop"]
    # A dominant pickup may hide the quieter pulse evidence. Unknown is safe;
    # assigning the later bass return to that earlier attack is not.
    assert all(abs(v.time - 8) <= .25 for v in pickup_drops)
    # An isolated attack must not become a drop.
    hit = analyze(audio(tmp_path / "hit.wav", ".01*sin(2*PI*500*t)+if(between(t,8,8.05),.8*sin(2*PI*60*t),0)"))
    assert not [v for v in hit.structure.moments if v.kind == "drop"]


def test_piano_like_swell_without_texture_return_is_not_a_drop(np, tmp_path):
    harmonics = "+".join(f"{1/k}*sin(2*PI*{220*k}*t)" for k in range(1, 9))
    envelope = "(.006+.09*clip((t-4)/6,0,1))*(.65+.35*exp(-3*mod(t,1)))"
    m = analyze(audio(tmp_path / "piano-swell.wav", f"({harmonics})*{envelope}"))
    assert max(e["rms_dbfs"] for e in m.structure.energy) - min(e["rms_dbfs"] for e in m.structure.energy) > 15
    assert not [v for v in m.structure.moments if v.kind == "drop"]
    assert any(v.kind == "swell" for v in m.structure.moments)


def test_brief_reverses_drop_and_calm_track_ranking(np, tmp_path):
    drop = analyze(drop_track(tmp_path / "drop.wav"))
    calm = analyze(audio(tmp_path / "calm.wav", ".04*sin(2*PI*260*t)", 32))
    montage = [rate(m, length=16, pace=.5, purpose="Music-led montage with a reveal") for m in (drop, calm)]
    talking = [rate(m, length=16, pace=.5, speech=True, purpose="Talking interview") for m in (drop, calm)]
    assert montage[0].score > montage[1].score + 20
    assert talking[1].score > talking[0].score + 10
    assert montage[0].measurements["scoring"]["weights"] == {"pace": 25, "moment": 25, "energy": 25, "intro": 10}
    assert talking[1].rating == "good"


def test_vowel_like_harmonics_advice_and_phase(np, tmp_path):
    calm = analyze(audio(tmp_path / "calm.wav", ".04*sin(2*PI*260*t)", 32))
    # Several harmonics emphasized near the first two vowel formants.
    vowel = "+".join(f"{.06 if k in (3,4,7,8) else .015}*sin(2*PI*{140*k}*t)" for k in range(1, 15))
    voice = analyze(audio(tmp_path / "vowel.wav", vowel, 8))
    assert voice.structure.vocals["status"] == "possible", voice.structure.vocals
    good, bad = rate(calm, speech=True, length=24), rate(voice, speech=True, length=24)
    assert good.rating == "good" and bad.rating == "bad"
    assert good.score > bad.score and "Licensing unknown" in good.licensing
    phase = analyze(audio(tmp_path / "phase.wav", ".1*sin(2*PI*200*t)|-.1*sin(2*PI*200*t)", 24))
    assert phase.structure.quality["mono_loss_db"] < -30
    assert rate(phase, length=24).rating == "bad"
    clipped = analyze(audio(tmp_path / "clipped.wav", "clip(2*sin(2*PI*200*t),-1,1)", 8))
    assert clipped.structure.quality["clipping_suspected"]


def test_drop_offset_and_montage_cut_snapping(np, tmp_path):
    from myzing.brief.models import Brief
    red, blue = video(tmp_path / "red.mp4"), video(tmp_path / "blue.mp4", "blue")
    music = drop_track(tmp_path / "drop.wav")
    studies = [ClipStudy(k, str(p), hash_file(p), 12, "ready", shots=[Shot(0, 0, 12)]) for k, p in (("a", red), ("b", blue))]
    sequence = [Candidate("a", studies[0].sha256, 0, 3, 0, 0, None, "", False, True),
                Candidate("b", studies[1].sha256, 0, 5, 0, 0, None, "", False, True)]
    asset = SimpleNamespace(id="m", path=str(music), state="ready", probe=SimpleNamespace(has_audio=True, duration=24), sha256=hash_file(music))
    seq, _, tracks, evidence = plan_music(sequence, studies, Brief(target_length_seconds=8, music={"source":"supplied files", "files":["m"]}),
                                          SimpleNamespace(assets=[asset]), tmp_path, 2, {}, {})
    d = next(d for d in evidence.decisions if d["kind"] == "drop_alignment")
    assert abs(tracks[0].src_in - 5) < .25
    assert abs(d["evidence_time"] - tracks[0].src_in - seq[0].duration) < 1e-6
    assert evidence.cut_summary == {"total": 1, "snapped": 0, "already_aligned": 0, "moment_locked": 1, "kept": 0}
    snapped, decisions = retime(sequence, studies, [3.1, 3.4], [], 0, speech=False, required={}, forbidden={})
    assert snapped[0].duration == pytest.approx(3.1)
    assert sum(c.duration for c in snapped) == 8
    assert decisions[0]["evidence_time"] == 3.1


def test_talking_clause_integrity_and_tolerance(np, tmp_path):
    path = video(tmp_path / "talk.mp4")
    words = [Word("A", 0, 1), Word("complete", 1, 2), Word("clause.", 2, 3)]
    studies = [ClipStudy("a", str(path), "a", 12, "ready", words=words, shots=[Shot(0, 0, 12)]),
               ClipStudy("b", str(path), "b", 12, "ready", shots=[Shot(0, 0, 12)])]
    sequence = [Candidate("a", "a", 0, 3, 0, 3, 0, "A complete clause.", False, True),
                Candidate("b", "b", 0, 4, 0, 0, None, "", False, True)]
    rejected, reasons = retime(sequence, studies, [2.95, 3.1], [], 0, speech=True, required={}, forbidden={})
    assert rejected == sequence  # .05 early slices a clause; .10 late exceeds tolerance.
    assert "complete clause" in reasons[0]["reason"]
    assert reasons[0]["candidate_attempts"][0]["evidence_time"] == 2.95
    accepted, decisions = retime(sequence, studies, [3.05], [], 0, speech=True, required={}, forbidden={})
    assert accepted[0].end == pytest.approx(3.05)
    assert decisions[0]["tolerance_seconds"] == .08
    assert all(accepted[0].start <= w.start < w.end <= accepted[0].end for w in words)


def test_source_speech_ducking_measured_stems_trims_and_peak(np, tmp_path):
    silent = video(tmp_path / "base.mp4")
    source = tmp_path / "talk.mp4"
    speech_dir = Path(__file__).resolve().parents[1] / "tools/eval/fixtures/speech"
    provenance = json.loads((speech_dir / "provenance.json").read_text())
    spoken = speech_dir / provenance["artifact"]["path"]
    assert hash_file(spoken) == provenance["artifact"]["sha256"]
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(silent), "-stream_loop", "-1", "-i", str(spoken),
                    "-map", "0:v", "-map", "1:a", "-t", "12", "-c:v", "copy", "-c:a", "aac", str(source)],
                   check=True, capture_output=True, timeout=60)
    music = audio(tmp_path / "bed.wav", "if(lt(t,2),.8*sin(2*PI*80*t),.12*sin(2*PI*300*t))", 16)
    p = Composition(assets=[AssetRef("v", str(source), hash_file(source)), AssetRef("m", str(music), hash_file(music))],
        clips=[CompositionClip(str(source), 0, 12, 0, id="v1", asset_id="v")],
        audio=[CompositionAudio(str(music), "music", gain_db=-6, duck_under_speech=True, id="m1", asset_id="m", role="music", src_in=2, src_out=14, duck_scope="source_speech")], width=320, height=180)
    attach(p, MusicPlan(mode="speech-led", speech_spans=[[2, 5], [7, 10]], tracks=[{"id":"m1"}]))
    from myzing.music.measurement import window_loudness
    p.audio[0].gain_db = window_loudness(source, [[2, 5], [7, 10]], 12) - 6 - window_loudness(music, [[2, 14]], 16)
    rendered = render_composition(p, tmp_path / "mix.mp4", work_dir=tmp_path / "work")
    measured = rendered.audio_measurements
    assert measured["music_gap_rms_dbfs"] - measured["music_speech_rms_dbfs"] > 12
    assert measured["integrated"]["true_peak_dbtp"] <= -1
    assert measured["integrated"]["integrated_lufs"] is not None
    assert measured["music_speech_lufs"] is not None and measured["music_gap_lufs"] is not None
    assert 18 <= measured["speech_to_music_lu"] <= 24
    samples, _ = decode_mono(tmp_path / "work/music-stem.wav")
    def rms(a, b):
        return np.sqrt(np.mean(samples[int(a*SAMPLE_RATE):int(b*SAMPLE_RATE)]**2))
    assert rms(3, 4) < rms(5.7, 6.7) * .22
    assert rms(11.8, 11.95) < rms(10.6, 10.8) * .3  # real fade, source trim applied
    # Known-span gating ignores the same repeated speech fixture in the gap.
    assert "between(t,2,5)" in rendered.filtergraph
    from myzing.inspect.timeline import inspect_timeline
    result = inspect_timeline(tmp_path / "mix.mp4", tmp_path / "sheet.png", start=0, end=12)
    assert result.audio_measurements["render_sha256"] == hash_file(tmp_path / "mix.mp4")
    assert json.loads((tmp_path / "mix.music.json").read_text())["music_plan"]["speech_spans"] == [[2, 5], [7, 10]]
