from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from myzing.render import otio_export
from myzing.render.otio_export import OTIOExportError, export_otio
from myzing.render.validation import MediaInfo
from myzing.schemas import AudioTrack, CaptionSpec, Clip, EDL


class _Node:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)
        self.metadata = dict(kwargs.get("metadata") or {})


class _Timeline(_Node):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.tracks = []


class _Track(_Node):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.children = []
        self.markers = []

    def append(self, child) -> None:
        self.children.append(child)


class _RationalTime:
    def __init__(self, value: float, rate: float) -> None:
        self.value = value
        self.rate = rate


class _TimeRange:
    def __init__(self, start_time, duration) -> None:
        self.start_time = start_time
        self.duration = duration


def fake_otio(record: dict[str, object]):
    def write_to_file(timeline, path: str) -> None:
        record["timeline"] = timeline
        record["path"] = Path(path)
        Path(path).write_text(json.dumps({"OTIO_SCHEMA": "Timeline.1"}))

    return SimpleNamespace(
        schema=SimpleNamespace(
            Timeline=_Timeline,
            Track=_Track,
            TrackKind=SimpleNamespace(Video="Video", Audio="Audio"),
            ExternalReference=_Node,
            Clip=_Node,
            Gap=_Node,
            Marker=_Node,
        ),
        opentime=SimpleNamespace(
            RationalTime=_RationalTime,
            TimeRange=_TimeRange,
        ),
        adapters=SimpleNamespace(write_to_file=write_to_file),
    )


def test_otio_export_preserves_editorial_audio_and_caption_timing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source clip.mp4"
    voice = tmp_path / "voice over.wav"
    music = tmp_path / "music.wav"
    for path in (source, voice, music):
        path.write_bytes(b"fixture")
    edl = EDL(
        clips=[Clip(str(source), 1.0, 3.0, 0.0)],
        captions=[
            CaptionSpec(
                "Show the result",
                0.5,
                1.5,
                word_timed=False,
            )
        ],
        audio=[
            AudioTrack(str(voice), "voiceover", timeline_start=0.25, gain_db=1.5),
            AudioTrack(str(music), "music", duck_under_speech=True),
        ],
        width=1920,
        height=1080,
        fps=30.0,
    )
    record: dict[str, object] = {}
    monkeypatch.setattr(
        otio_export.importlib,
        "import_module",
        lambda name: fake_otio(record),
    )

    result = export_otio(
        edl,
        tmp_path / "draft.otio",
        base_dir=tmp_path,
        probe=lambda path: MediaInfo(
            duration=4.0,
            has_video=path == source,
            has_audio=True,
        ),
    )

    timeline = record["timeline"]
    assert isinstance(timeline, _Timeline)
    assert result.output_path.is_file()
    assert result.track_count == 4
    assert result.duration == 2.0
    assert timeline.metadata["myzing"]["dimensions"] == [1920, 1080]
    assert [track.name for track in timeline.tracks] == [
        "Video 1",
        "Source Audio",
        "Voiceover 1",
        "Music 1",
    ]

    video = timeline.tracks[0]
    video_clip = video.children[0]
    assert video_clip.source_range.start_time.value == 30.0
    assert video_clip.source_range.duration.value == 60.0
    assert video_clip.media_reference.target_url == source.resolve().as_uri()
    assert video.markers[0].name == "Show the result"
    assert video.markers[0].marked_range.start_time.value == 15.0
    assert video.markers[0].marked_range.duration.value == 30.0

    voice_track = timeline.tracks[2]
    assert voice_track.children[0].source_range.duration.value == 7.5
    assert voice_track.children[1].metadata["myzing"]["gain_db"] == 1.5
    music_clip = timeline.tracks[3].children[0]
    assert music_clip.metadata["myzing"]["duck_under_speech"] is True


def test_otio_export_fails_honestly_without_optional_dependency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fixture")
    edl = EDL(clips=[Clip(str(source), 0.0, 1.0, 0.0)])

    def missing(name: str):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(otio_export.importlib, "import_module", missing)

    with pytest.raises(OTIOExportError, match="OpenTimelineIO is required"):
        export_otio(
            edl,
            tmp_path / "draft.otio",
            base_dir=tmp_path,
            probe=lambda path: MediaInfo(1.0, True, False),
        )


def test_real_opentimelineio_adapter_round_trips_native_export(
    tmp_path: Path,
) -> None:
    try:
        real_otio = importlib.import_module("opentimelineio")
    except (ImportError, ModuleNotFoundError):
        if os.environ.get("ZING_REQUIRE_OTIO") == "1":
            pytest.fail("OpenTimelineIO is required by the CI export gate")
        pytest.skip("OpenTimelineIO optional runtime is not installed")

    source = tmp_path / "round trip source.mp4"
    voice = tmp_path / "round trip voice.wav"
    source.write_bytes(b"fixture")
    voice.write_bytes(b"fixture")
    edl = EDL(
        clips=[Clip(str(source), 0.5, 1.5, 0.0)],
        captions=[
            CaptionSpec("Native OTIO", 0.1, 0.6, word_timed=False),
        ],
        audio=[
            AudioTrack(str(voice), "voiceover", timeline_start=0.2),
        ],
        width=1080,
        height=1080,
        fps=24.0,
    )
    output = tmp_path / "native round trip.otio"

    export_otio(
        edl,
        output,
        base_dir=tmp_path,
        probe=lambda path: MediaInfo(
            duration=2.0,
            has_video=path == source,
            has_audio=True,
        ),
    )
    timeline = real_otio.adapters.read_from_file(str(output))

    assert [track.name for track in timeline.tracks] == [
        "Video 1",
        "Source Audio",
        "Voiceover 1",
    ]
    assert timeline.tracks[0][0].source_range.start_time.value == 12.0
    assert timeline.tracks[0][0].source_range.duration.value == 24.0
    assert timeline.tracks[0].markers[0].name == "Native OTIO"
    assert timeline.tracks[2][0].duration().value == pytest.approx(4.8)
