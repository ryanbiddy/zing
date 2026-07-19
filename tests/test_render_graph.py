from __future__ import annotations

from pathlib import Path

from myzing.render.graph import DUCK_RATIO, DUCK_THRESHOLD, build_graph
from myzing.render.validation import (
    MediaInfo,
    ResolvedAudioTrack,
    ResolvedClip,
    ValidatedEDL,
)
from myzing.schemas import AudioTrack, CaptionSpec, Clip, EDL, Word


def test_graph_normalizes_every_leg_and_ducks_music_under_voice_only(
    tmp_path: Path,
) -> None:
    clip_one = Clip("first.mp4", 0.0, 1.0, 0.0)
    clip_two = Clip("second.mp4", 1.0, 2.0, 1.0)
    voice = AudioTrack("voice.wav", "voiceover", timeline_start=0.2, gain_db=2.0)
    music = AudioTrack("music.wav", "music", duck_under_speech=True)
    edl = EDL(
        clips=[clip_one, clip_two],
        captions=[
            CaptionSpec(
                "hello",
                0.2,
                0.8,
                words=[Word("hello", 0.2, 0.8)],
            )
        ],
        audio=[voice, music],
    )
    media_av = MediaInfo(5.0, True, True)
    media_audio = MediaInfo(5.0, False, True)
    validated = ValidatedEDL(
        edl,
        (
            ResolvedClip(clip_one, tmp_path / "first.mp4", media_av),
            ResolvedClip(clip_two, tmp_path / "second.mp4", media_av),
        ),
        (
            ResolvedAudioTrack(voice, tmp_path / "voice.wav", media_audio),
            ResolvedAudioTrack(music, tmp_path / "music.wav", media_audio),
        ),
        2.0,
        (),
    )

    plan = build_graph(validated, include_captions=True)

    assert plan.graph.count("scale=1080:1920") == 2
    assert plan.graph.count("fps=30") == 2
    assert plan.graph.count("format=yuv420p") == 2
    assert "concat=n=2:v=1:a=0" in plan.graph
    assert "ass=filename='captions.ass'" in plan.graph
    assert "sidechaincompress=" in plan.graph
    assert f"threshold={DUCK_THRESHOLD}" in plan.graph
    assert f"ratio={DUCK_RATIO}" in plan.graph
    assert "loudnorm" not in plan.graph
    assert "aresample=48000" in plan.graph
    assert "channel_layouts=stereo" in plan.graph
    assert "adelay=1000:all=1,asetpts=PTS-STARTPTS" in plan.graph
    assert "adelay=200:all=1,asetpts=PTS-STARTPTS" in plan.graph
    assert tuple(path.name for path in plan.input_paths) == (
        "first.mp4",
        "second.mp4",
        "voice.wav",
        "music.wav",
    )


def test_graph_creates_silent_track_when_no_audio_inputs(tmp_path: Path) -> None:
    clip = Clip("silent.mp4", 0.0, 1.0, 0.0)
    edl = EDL(clips=[clip])
    validated = ValidatedEDL(
        edl,
        (
            ResolvedClip(
                clip,
                tmp_path / "silent.mp4",
                MediaInfo(1.0, True, False),
            ),
        ),
        (),
        1.0,
        (),
    )

    plan = build_graph(validated, include_captions=False)

    assert "anullsrc=r=48000:cl=stereo:d=1[audio_out]" in plan.graph
    assert "[video_concat]null[video_out]" in plan.graph
