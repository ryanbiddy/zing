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
    # A loud pickup 0.4 s earlier must neither hide the quieter kicks after it
    # nor mask the drop as a swell; the drop is not moved onto the pickup.
    assert len(pickup_drops) == 1, pickup.structure.moments
    assert abs(pickup_drops[0].time - 8) <= .25
    assert not [v for v in pickup.structure.moments if v.kind == "swell" and abs(v.time - 8) < 3]
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
    plan = MusicPlan(mode="speech-led", speech_spans=[[2, 5], [7, 10]], tracks=[{"id":"m1"}])
    attach(p, plan)
    from myzing.music.measurement import window_loudness
    # Planning rule: the pause bed sits (21 - depth) LU under gated speech.
    p.audio[0].gain_db = (window_loudness(source, [[2, 5], [7, 10]], 12) - (21 - plan.duck_depth_db)
                          - window_loudness(music, [[4, 7], [9, 12]], 16))
    rendered = render_composition(p, tmp_path / "mix.mp4", work_dir=tmp_path / "work")
    measured = rendered.audio_measurements
    assert measured["music_gap_rms_dbfs"] - measured["music_speech_rms_dbfs"] > 6
    assert measured["duck"]["passages"] == 2
    assert measured["integrated"]["true_peak_dbtp"] <= -1
    assert measured["integrated"]["integrated_lufs"] is not None
    assert measured["music_speech_lufs"] is not None and measured["music_gap_lufs"] is not None
    assert 18 <= measured["speech_to_music_lu"] <= 24
    samples, _ = decode_mono(tmp_path / "work/music-stem.wav")
    def rms(a, b):
        return np.sqrt(np.mean(samples[int(a*SAMPLE_RATE):int(b*SAMPLE_RATE)]**2))
    # The 2 s pause recovers fully between the 0.8 s release and 0.2 s pre-duck.
    assert 20 * np.log10(rms(5.85, 6.75) / rms(3, 4)) == pytest.approx(9, abs=.75)
    assert rms(11.8, 11.95) < rms(10.85, 11.0) * .3  # real fade, source trim applied
    # Known spans drive the envelope; the repeated speech fixture in the pause does not.
    assert "amultiply" in rendered.filtergraph and (tmp_path / "work/music-duck.wav").is_file()
    from myzing.inspect.timeline import inspect_timeline
    result = inspect_timeline(tmp_path / "mix.mp4", tmp_path / "sheet.png", start=0, end=12)
    assert result.audio_measurements["render_sha256"] == hash_file(tmp_path / "mix.mp4")
    assert json.loads((tmp_path / "mix.music.json").read_text())["music_plan"]["speech_spans"] == [[2, 5], [7, 10]]


SR = 44100


def write_pcm(path, samples):
    """Write generated float samples as a 24-bit stereo WAV."""
    import numpy
    y = numpy.asarray(samples, dtype=numpy.float32)
    y = numpy.stack([y, y], axis=1)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "pipe:0",
                    "-c:a", "pcm_s24le", str(path)], input=y.tobytes(), check=True, capture_output=True, timeout=60)
    return path


def synth(np, duration):
    t = np.arange(int(duration * SR)) / SR
    rng = np.random.default_rng(7)

    def tone(f, start=0, end=None, amp=.05):
        return amp * np.sin(2 * np.pi * f * t) * ((t >= start) & (t < (duration if end is None else end)))

    def bursts(times, length, make):
        y = np.zeros_like(t)
        for k in times:
            i = int(k * SR)
            n = min(len(t) - i, int(length * SR))
            if n > 0:
                y[i:i + n] += make(np.arange(n) / SR)
        return y

    def kick(start, end, bpm=128):
        return bursts(np.arange(start, end, 60 / bpm), .25, lambda tt: .8 * np.sin(
            2 * np.pi * np.cumsum(50 + 100 * np.exp(-tt * 30)) / SR) * np.exp(-tt * 12))

    def hats(start, end, amp, division=2, bpm=128):
        step = 60 / bpm / division
        return bursts(np.arange(start + step / 2, end, step), .05,
                      lambda tt: amp * np.diff(np.r_[0, rng.standard_normal(len(tt))]) * np.exp(-tt * 80))

    def stabs(start, end, bpm=128):
        return bursts(np.arange(start, end, 60 / bpm / 2), .12,
                      lambda tt: .3 * np.sign(np.sin(2 * np.pi * 440 * tt)) * np.exp(-tt * 20))

    pad = tone(220) + tone(277) + tone(330)
    return SimpleNamespace(t=t, tone=tone, kick=kick, hats=hats, stabs=stabs, pad=pad)


def speech_source(tmp_path, duration):
    """Video whose audio is continuous speech-like noise; spans say where speech is."""
    path = tmp_path / "talk.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=gray:s=160x90:r=30:d={duration}",
                    "-f", "lavfi", "-i", f"anoisesrc=c=pink:a=0.1:d={duration}:r=48000", "-c:v", "libx264",
                    "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path)], check=True, capture_output=True, timeout=120)
    return path


def ducked_render(tmp_path, duration, spans, hold=None, **duck):
    source = speech_source(tmp_path, duration)
    bed = audio(tmp_path / "bed.wav", ".25*sin(2*PI*300*t)", duration + 2)
    p = Composition(assets=[AssetRef("v", str(source), hash_file(source)), AssetRef("m", str(bed), hash_file(bed))],
        clips=[CompositionClip(str(source), 0, duration, 0, id="v1", asset_id="v")],
        audio=[CompositionAudio(str(bed), "music", gain_db=-6, duck_under_speech=True, id="m1", asset_id="m",
                                role="music", src_in=1, src_out=duration + 1, duck_scope="source_speech")],
        width=160, height=90)
    plan = MusicPlan(mode="speech-led", speech_spans=spans, tracks=[{"id": "m1"}])
    if hold is not None:
        plan.duck_hold_seconds = hold
    for name, value in duck.items():
        setattr(plan, name, value)
    attach(p, plan)
    return render_composition(p, tmp_path / "mix.mp4", work_dir=tmp_path / "work")


def test_known_speech_ducking_holds_clause_gaps_and_recovers_in_pauses(np, tmp_path):
    # Gaps under 1.3 s (attack + release + 0.3 s plateau) stay ducked, including
    # the 0.84 s sentence gap LISTEN1 measured lifting the bed 8.4 dB.
    gaps = [.2, .3, .4, .84, 1.0, 1.6]
    spans, t = [], 1.0
    for gap in gaps:
        spans.append([t, t + 2.0])
        t += 2.0 + gap
    spans.append([t, t + 2.0])
    rendered = ducked_render(tmp_path, 20, spans)
    samples, _ = decode_mono(tmp_path / "work/music-stem.wav")

    def db(a, b):
        x = samples[int(a * SAMPLE_RATE):int(b * SAMPLE_RATE)]
        return 20 * np.log10(np.sqrt(np.mean(x ** 2)))

    ducked = db(1.5, 2.5)
    for (a, b), gap in zip(spans, gaps):
        inside = [db(x, x + .02) for x in np.arange(b, b + gap - .019, .01)]
        if gap < 1.3:  # held: the bed must not swell between clauses
            assert max(abs(v - ducked) for v in inside) <= .5, (gap, inside)
        else:          # a real pause: smooth, full recovery with an audible plateau
            assert max(inside) - ducked >= 8.5, (gap, inside)
            assert sum(v - ducked >= 8 for v in inside) * .01 >= .3, (gap, inside)
    # No step anywhere: 10 ms levels move at most 1 dB (raised-cosine ramps).
    levels = [db(x, x + .01) for x in np.arange(.2, 17.5, .01)]
    assert max(abs(a - b) for a, b in zip(levels, levels[1:])) <= 1.0
    # Every word starts with the bed already down: pre-duck precedes speech.
    for a, _ in spans:
        assert db(a, a + .01) - ducked <= .3
    assert db(.2, .7) - ducked == pytest.approx(9, abs=.5)  # documented depth before speech
    m = rendered.audio_measurements
    assert abs(m["music_held_gap_rms_dbfs"] - m["music_speech_rms_dbfs"]) <= .3
    assert m["duck"]["passages"] == 2 and m["duck"]["hold"] == .8


def test_hundreds_of_speech_spans_render_and_measure(np, tmp_path):
    # 300 short clauses, beyond FFmpeg 8's flat-expression limit (~98 terms);
    # hold 0 with fast ramps and no plateau keeps every clause a separate passage.
    spans = [[round(.2 + i * .2, 3), round(.3 + i * .2, 3)] for i in range(300)]
    rendered = ducked_render(tmp_path, 61, spans, hold=0.0, duck_attack_seconds=.02, duck_release_seconds=.05,
                             duck_plateau_seconds=0.0)
    m = rendered.audio_measurements
    assert m["duck"]["passages"] == 300
    assert m["source_speech_lufs"] is not None and m["music_speech_lufs"] is not None
    assert m["speech_to_music_lu"] is not None
    from myzing.music.measurement import window_loudness
    assert window_loudness(tmp_path / "work/music-stem.wav", spans, 61) is not None


def test_plain_music_bed_renders_without_numpy(tmp_path, monkeypatch):
    import myzing.audio.media as media
    source = video(tmp_path / "v.mp4", duration=3)
    bed = audio(tmp_path / "bed.wav", ".1*sin(2*PI*440*t)", 4)

    def missing():
        raise media.AudioError('Audio analysis needs NumPy; install: python -m pip install "myzing[audio]"')
    monkeypatch.setattr(media, "numpy", missing)

    def plan(**evidence):
        p = Composition(assets=[AssetRef("v", str(source), hash_file(source)), AssetRef("m", str(bed), hash_file(bed))],
            clips=[CompositionClip(str(source), 0, 3, 0, id="v1", asset_id="v")],
            audio=[CompositionAudio(str(bed), "music", gain_db=-12, id="m1", asset_id="m", role="music")], width=160, height=90)
        if evidence:
            attach(p, MusicPlan(**evidence))
        return p

    plain = render_composition(plan(), tmp_path / "plain.mp4", work_dir=tmp_path / "plain")
    assert plain.audio_measurements is None and not (tmp_path / "plain.music.json").exists()
    assert not any("measurement skipped" in w for w in plain.warnings)
    assert not (tmp_path / "plain/source-stem.wav").exists() and not (tmp_path / "plain/music-stem.wav").exists()
    planned = render_composition(plan(tracks=[{"id": "m1"}]), tmp_path / "planned.mp4", work_dir=tmp_path / "planned")
    assert planned.output_path.is_file() and planned.audio_measurements is None
    assert any("measurement skipped" in w and "myzing[audio]" in w for w in planned.warnings)


def test_voiceover_only_render_writes_no_stems(tmp_path):
    source = video(tmp_path / "v.mp4", duration=3)
    voice = audio(tmp_path / "vo.wav", ".1*sin(2*PI*220*t)", 3)
    p = Composition(assets=[AssetRef("v", str(source), hash_file(source)), AssetRef("o", str(voice), hash_file(voice))],
        clips=[CompositionClip(str(source), 0, 3, 0, id="v1", asset_id="v")],
        audio=[CompositionAudio(str(voice), "voiceover", id="o1", asset_id="o", role="voiceover")], width=160, height=90)
    render_composition(p, tmp_path / "vo.mp4", work_dir=tmp_path / "work")
    assert not list((tmp_path / "work").glob("*-stem.wav"))


def test_steady_pad_scores_steady_and_reasons_match_their_numbers(np, tmp_path):
    s = synth(np, 40)
    pad = analyze(write_pcm(tmp_path / "pad.wav", s.pad))
    def attacks(e):
        return e.get("attacks_per_second", e["onsets_per_second"])
    assert max(attacks(e) for e in pad.structure.energy) == 0
    noise = analyze(audio(tmp_path / "noise.wav", ".05*(random(0)-.5)", 40))
    assert np.mean([attacks(e) for e in noise.structure.energy]) < .2
    tracks = [pad, noise, analyze(drop_track(tmp_path / "drop.wav")), analyze(audio(tmp_path / "pulse.wav", pulse(), 40)),
              analyze(write_pcm(tmp_path / "busy.wav", s.pad + s.hats(0, 40, .2, division=4)))]
    advice = rate(pad, length=30, speech=True)
    energy = next(r for r in advice.reasons if r["topic"] == "energy")
    assert energy["points"] == energy["weight"] and "steadier" not in energy["reason"]
    for track in tracks:
        for length in (8, 16, 30):
            a = rate(track, length=length, speech=True)
            spread = a.measurements["scoring"]["spread_db"]
            text = next(r["reason"] for r in a.reasons if r["topic"] == "energy")
            assert ("steadier" in text) == (spread is not None and spread > 6), (track.source, text)
            if "compete with speech" in text:
                assert float(text.split(" with ")[1].split(" ")[0]) > 1.5
    busy = rate(tracks[-1], length=30, speech=True)
    assert "compete with speech" in next(r["reason"] for r in busy.reasons if r["topic"] == "energy")


def test_midrange_drop_after_pad_only_break(np, tmp_path):
    s = synth(np, 32)
    y = s.pad + s.hats(0, 12, .05) + (s.t >= 16) * (s.stabs(16, 32) + s.hats(16, 32, .2, division=4))
    m = analyze(write_pcm(tmp_path / "mid.wav", y / np.abs(y).max() * .9))
    drops = [v for v in m.structure.moments if v.kind == "drop"]
    assert len(drops) == 1 and abs(drops[0].time - 16) <= .25, m.structure.moments


def test_regional_tempo_supports_pace_for_any_excerpt_length(np, tmp_path):
    s = synth(np, 40)
    bass = s.tone(55, 0, 12, .25) + s.tone(55, 20, 40, .25)
    y = s.kick(0, 12) + s.hats(0, 12, .15) + s.pad + s.kick(20, 40) + s.hats(20, 40, .15) + bass
    m = analyze(write_pcm(tmp_path / "breakdown.wav", y / np.abs(y).max() * .9))
    assert m.tempo.status != "steady"  # the case under test: only local regions agree
    assert {round(r["bpm"]) for r in m.structure.rhythm_regions} == {128}
    reasons = [next(r for r in rate(m, length=length, pace=60 / 128 * 2, purpose="montage").reasons
                    if r["topic"] == "pace") for length in (12, 16, 20, 24, 30)]
    assert all(r["points"] == r["weight"] for r in reasons), reasons
    assert all("agreeing local rhythm regions" in r["reason"] for r in reasons)
    calm = analyze(write_pcm(tmp_path / "calm.wav", s.pad))
    pace = next(r["reason"] for r in rate(calm, length=20, pace=.5).reasons if r["topic"] == "pace")
    assert "Supply" not in pace and "0.5s reference pace cannot be matched" in pace


def test_source_speech_ducking_rejects_a_changed_clip_timeline(tmp_path):
    from myzing.music.models import timeline_of
    source = speech_source(tmp_path, 6)
    bed = audio(tmp_path / "bed.wav", ".1*sin(2*PI*300*t)", 8)
    p = Composition(assets=[AssetRef("v", str(source), hash_file(source)), AssetRef("m", str(bed), hash_file(bed))],
        clips=[CompositionClip(str(source), 0, 6, 0, id="v1", asset_id="v")],
        audio=[CompositionAudio(str(bed), "music", duck_under_speech=True, id="m1", asset_id="m",
                                role="music", src_in=0, src_out=6, duck_scope="source_speech")],
        width=160, height=90)
    planned = [CompositionClip(str(source), 0, 5, 0, id="v1", asset_id="v")]  # trimmed after planning
    attach(p, MusicPlan(mode="speech-led", speech_spans=[[1, 2]], tracks=[{"id": "m1"}], timeline=timeline_of(planned)))
    with pytest.raises(ValueError, match="re-run zing plan drafts"):
        render_composition(p, tmp_path / "stale.mp4", work_dir=tmp_path / "work")


def test_every_aspect_delivery_carries_the_same_music_plan_and_mix(np, tmp_path, monkeypatch):
    import myzing.render.deliveries as deliveries
    from myzing.composition.aspects import ASPECTS, dimensions
    from myzing.music.models import extract, timeline_of
    from myzing.render.framing import probe_dimensions
    source = tmp_path / "talk.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=6",
                    "-f", "lavfi", "-i", "anoisesrc=c=pink:a=0.1:d=6:r=48000", "-c:v", "libx264",
                    "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source)],
                   check=True, capture_output=True, timeout=120)
    bed = audio(tmp_path / "bed.wav", ".25*sin(2*PI*300*t)", 8)
    p = Composition(assets=[AssetRef("v", str(source), hash_file(source)), AssetRef("m", str(bed), hash_file(bed))],
        clips=[CompositionClip(str(source), 0, 6, 0, id="v1", asset_id="v")],
        audio=[CompositionAudio(str(bed), "music", gain_db=-6, duck_under_speech=True, id="m1", asset_id="m",
                                role="music", src_in=1, src_out=7, duck_scope="source_speech")],
        width=320, height=180)
    spans = [[.5, 2.0], [3.5, 5.0]]
    attach(p, MusicPlan(mode="speech-led", speech_spans=spans, tracks=[{"id": "m1"}], timeline=timeline_of(p.clips)))
    # A detected cut at 2.5 s splits every adapted clip (per-aspect reframing);
    # the pieces must still match the timeline the speech spans were planned for.
    monkeypatch.setattr(deliveries, "detect_shots", lambda *a, **k: SimpleNamespace(
        shots=[SimpleNamespace(start=0.0), SimpleNamespace(start=2.5)], warnings=[]))
    monkeypatch.setattr(deliveries, "analyze_subjects", lambda *a, **k: ([], []))
    result = deliveries.render_deliveries(p, tmp_path / "edit.mp4", aspects="all", short_side=180, base_dir=tmp_path)
    rows = result["deliveries"]
    assert set(rows) == set(ASPECTS)
    measured = {}
    for aspect, row in rows.items():
        assert probe_dimensions(Path(row["video"])) == dimensions(aspect, 180)
        adapted = Composition.from_json(Path(row["plan"]).read_text(encoding="utf-8"))
        assert [(c.src_in, c.src_out) for c in adapted.clips] == [(0, 2.5), (2.5, 6)]
        assert extract(adapted) == extract(p)  # the same music plan, spans and duck settings
        assert [(a.src_in, a.src_out, a.gain_db, a.duck_scope) for a in adapted.audio] == [(1, 7, -6, "source_speech")]
        measured[aspect] = json.loads(Path(row["music"]).read_text(encoding="utf-8"))
    first = measured[ASPECTS[0]]
    for aspect, m in measured.items():
        assert m["duck"]["passages"] == 2 and m["music_plan"]["speech_spans"] == spans
        for key in ("music_speech_lufs", "music_gap_lufs", "source_speech_lufs", "speech_to_music_lu",
                    "music_speech_rms_dbfs", "music_gap_rms_dbfs"):
            assert m[key] is not None and m[key] == pytest.approx(first[key], abs=.2), (aspect, key)
        assert m["integrated"]["integrated_lufs"] == pytest.approx(first["integrated"]["integrated_lufs"], abs=.2)


def talker(path, amplitude, duration=6):
    """A clip whose audio is steady pink 'speech' at a chosen level."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=gray:s=160x90:r=30:d={duration}",
                    "-f", "lavfi", "-i", f"anoisesrc=c=pink:a={amplitude}:d={duration}:r=48000:s=7", "-c:v", "libx264",
                    "-preset", "ultrafast", "-c:a", "aac", "-b:a", "192k", "-shortest", str(path)],
                   check=True, capture_output=True, timeout=120)
    return path


def two_talkers(tmp_path, quiet_amplitude):
    """Plan a loud and a quiet generated talker (two clauses each) over a steady bed."""
    from myzing.brief.models import Brief
    loud, quiet = talker(tmp_path / "loud.mp4", .2), talker(tmp_path / "quiet.mp4", quiet_amplitude)
    words = [Word("First", .5, 1.5), Word("clause.", 1.5, 2.5), Word("Second", 3.5, 4.5), Word("clause.", 4.5, 5.5)]
    studies = [ClipStudy(k, str(p), hash_file(p), 6, "ready", words=words, shots=[Shot(0, 0, 6)])
               for k, p in (("loud", loud), ("quiet", quiet))]
    sequence = [Candidate(s.asset_id, s.sha256, 0, 6, 0, 4, .5, "First clause. Second clause.", False, True) for s in studies]
    bed = audio(tmp_path / "bed.wav", ".25*sin(2*PI*300*t)", 20)
    asset = SimpleNamespace(id="m", path=str(bed), state="ready", sha256=hash_file(bed),
                            probe=SimpleNamespace(has_audio=True, duration=20))
    brief = Brief(purpose="Talking edit", target_length_seconds=12, music={"source": "supplied files", "files": ["m"]})
    _, _, tracks, evidence = plan_music(sequence, studies, brief, SimpleNamespace(assets=[asset]), tmp_path, 2, {}, {})

    def render(name, plan):
        p = Composition(assets=[AssetRef(s.asset_id, s.path, s.sha256) for s in studies] + [AssetRef("m", str(bed), asset.sha256)],
            clips=[CompositionClip(s.path, 0, 6, 6 * i, id=f"c{i}", asset_id=s.asset_id) for i, s in enumerate(studies)],
            audio=tracks, width=160, height=90)
        attach(p, plan)
        return render_composition(p, tmp_path / f"{name}.mp4", work_dir=tmp_path / name)
    return evidence, render


def test_clips_14_lu_apart_get_matched_dialogue_and_one_bed(np, tmp_path):
    # LISTEN1: Gemini heard the quiet opening clip "brokenly quiet" next to
    # the next speaker (13.9 LU apart); a bed that follows each clip added a
    # second jump. The voices are matched first, so one bed level serves both.
    evidence, render = two_talkers(tmp_path, .04)  # 20*log10(5) = 14 dB quieter
    levels = {v["asset_id"]: v for v in evidence.clip_levels}
    assert levels["loud"]["speech_lufs"] - levels["quiet"]["source_speech_lufs"] == pytest.approx(14, abs=1)
    [row] = evidence.dialogue_gains
    assert row["asset_id"] == "quiet" and row["gain_db"] == pytest.approx(14, abs=1) and (row["start"], row["end"]) == (6, 12)
    assert evidence.bed_gain_points == []  # voices within 6 LU after matching: one bed gain
    assert all(c["in_band"] for c in evidence.clauses), evidence.clauses
    rendered = render("matched", evidence)
    legs = {line.strip()[:7]: line for line in rendered.filtergraph.split(";") if line.strip().startswith(("[0:a:0]", "[1:a:0]"))}
    assert "volume=" not in legs["[0:a:0]"] and f"volume={row['gain_db']:.6f}dB" in legs["[1:a:0]"]
    # The source changes at the 6 s cut: speech-free edges fade (0.3 s out, 0.1 s in).
    assert "afade=t=out:st=5.700000:d=0.300000" in legs["[0:a:0]"] and "afade=t=in:st=0:d=0.100000" in legs["[1:a:0]"]
    rows = rendered.audio_measurements["clauses"]
    assert all(18 <= r["separation_lu"] <= 24 for r in rows), rows
    speech = [r["speech_lufs"] for r in rows]
    assert abs((speech[0] + speech[1]) / 2 - (speech[2] + speech[3]) / 2) <= 1.5  # the jump is gone
    assert rendered.audio_measurements["warnings"] == []


def test_a_capped_dialogue_match_leaves_the_rest_to_a_per_clip_bed(np, tmp_path):
    evidence, render = two_talkers(tmp_path, .01)  # 26 dB quieter: boost caps at 18 dB
    [row] = evidence.dialogue_gains
    assert row["gain_db"] == 18 and any("raised it only 18 dB" in w for w in evidence.warnings)
    # The remaining ~8 LU go to the bed, ramped over the loud voice's last second.
    points = evidence.bed_gain_points
    assert [p[0] for p in points] == [0, 4.5, 5.5, 12] and points[0][1] == points[1][1] == 0
    assert points[2][1] == points[3][1] == pytest.approx(-8, abs=1.5)
    assert next(d for d in evidence.decisions if d["kind"] == "bed_clip_gain")["clip_spread_lu"] > 6
    assert all(c["in_band"] or c["bed_ramp"] for c in evidence.clauses), evidence.clauses
    m = render("per-clip", evidence).audio_measurements
    assert all(18 <= r["separation_lu"] <= 24 or (r["bed_ramp"] and r["separation_lu"] > 24) for r in m["clauses"]), m["clauses"]
    assert m["clause_separation"]["outside_band"] == 0 and m["warnings"] == []
    assert m["duck"]["gain_points"] == points
    # One bed gain for both clips leaves the quiet clauses ~8 LU too close, and the sidecar says so.
    flat = render("single-gain", MusicPlan.from_dict({**evidence.to_dict(), "bed_gain_points": []}))
    rows = flat.audio_measurements["clauses"]
    assert all(r["separation_lu"] < 16 for r in rows[2:]), rows
    assert flat.audio_measurements["clause_separation"]["outside_band"] >= 2
    assert any("clauses measure outside the 18-24 LU" in w for w in flat.warnings)
