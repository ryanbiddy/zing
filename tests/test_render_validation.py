from __future__ import annotations

from pathlib import Path

import pytest

from myzing.render.validation import EDLValidationError, MediaInfo, validate_edl
from myzing.schemas import AudioTrack, CaptionSpec, Clip, EDL, Word


def media_file(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(b"fixture")
    return path


def probe(path: Path) -> MediaInfo:
    return MediaInfo(
        duration=10.0,
        has_video=path.suffix == ".mp4",
        has_audio=True,
    )


def valid_edl(tmp_path: Path) -> EDL:
    first = media_file(tmp_path, "first clip.mp4")
    second = media_file(tmp_path, "creator's second clip.mp4")
    return EDL(
        clips=[
            Clip(str(second), 1.0, 2.0, 1.0),
            Clip(str(first), 0.0, 1.0, 0.0),
        ],
        captions=[
            CaptionSpec(
                text="hello zing",
                start=0.2,
                end=1.4,
                words=[
                    Word("hello", 0.2, 0.7),
                    Word("zing", 0.8, 1.3),
                ],
            )
        ],
    )


def test_validation_sorts_a_contiguous_timeline_and_resolves_paths(
    tmp_path: Path,
) -> None:
    edl = valid_edl(tmp_path)

    validated = validate_edl(edl, tmp_path, probe)

    assert validated.duration == 2.0
    assert [clip.spec.timeline_start for clip in validated.clips] == [0.0, 1.0]
    assert all(clip.path.is_absolute() for clip in validated.clips)
    assert validated.warnings == ()


@pytest.mark.parametrize(
    ("timeline_start", "message"),
    [
        (0.9, "overlaps"),
        (1.1, "gap"),
    ],
)
def test_validation_rejects_overlap_and_gap(
    tmp_path: Path, timeline_start: float, message: str
) -> None:
    edl = valid_edl(tmp_path)
    edl.clips[0].timeline_start = timeline_start

    with pytest.raises(EDLValidationError, match=message):
        validate_edl(edl, tmp_path, probe)


def test_validation_rejects_missing_source(tmp_path: Path) -> None:
    edl = valid_edl(tmp_path)
    edl.clips[0].src = "missing file.mp4"

    with pytest.raises(EDLValidationError, match="does not exist"):
        validate_edl(edl, tmp_path, probe)


def test_validation_rejects_source_trim_past_media_end(tmp_path: Path) -> None:
    edl = valid_edl(tmp_path)
    edl.clips[0].src_out = 20.0

    with pytest.raises(EDLValidationError, match="exceeds source duration"):
        validate_edl(edl, tmp_path, probe)


def test_validation_rejects_word_outside_caption_window(tmp_path: Path) -> None:
    edl = valid_edl(tmp_path)
    edl.captions[0].words[1].end = 1.5

    with pytest.raises(EDLValidationError, match="outside its caption window"):
        validate_edl(edl, tmp_path, probe)


def test_validation_rejects_word_timed_caption_without_words(
    tmp_path: Path,
) -> None:
    edl = valid_edl(tmp_path)
    edl.captions[0].words.clear()

    with pytest.raises(EDLValidationError, match="no word timings"):
        validate_edl(edl, tmp_path, probe)


def test_caption_limits_warn_but_do_not_fail(tmp_path: Path) -> None:
    edl = valid_edl(tmp_path)
    edl.captions = [
        CaptionSpec(
            text=("x" * 43) + "\nsecond\nthird",
            start=0.0,
            end=1.0,
            word_timed=False,
        )
    ]

    validated = validate_edl(edl, tmp_path, probe)

    assert any("3 lines" in warning for warning in validated.warnings)
    assert any("43 characters" in warning for warning in validated.warnings)
    assert any("characters/second" in warning for warning in validated.warnings)


def test_duck_request_without_voiceover_warns(tmp_path: Path) -> None:
    edl = valid_edl(tmp_path)
    music = media_file(tmp_path, "music.wav")
    edl.audio = [
        AudioTrack(
            str(music),
            "music",
            duck_under_speech=True,
        )
    ]

    validated = validate_edl(edl, tmp_path, probe)

    assert any("no voiceover" in warning for warning in validated.warnings)


def test_duck_flag_is_invalid_on_voiceover(tmp_path: Path) -> None:
    edl = valid_edl(tmp_path)
    voice = media_file(tmp_path, "voice.wav")
    edl.audio = [
        AudioTrack(
            str(voice),
            "voiceover",
            duck_under_speech=True,
        )
    ]

    with pytest.raises(EDLValidationError, match="only valid for music"):
        validate_edl(edl, tmp_path, probe)


@pytest.mark.parametrize(("width", "height"), [(0, 1920), (1081, 1920)])
def test_output_dimensions_must_be_positive_and_even(
    tmp_path: Path, width: int, height: int
) -> None:
    edl = valid_edl(tmp_path)
    edl.width = width
    edl.height = height

    with pytest.raises(EDLValidationError, match="width and height"):
        validate_edl(edl, tmp_path, probe)


def test_schema_values_do_not_accept_stringified_numbers(tmp_path: Path) -> None:
    edl = valid_edl(tmp_path)
    edl.clips[0].src_in = "1.0"  # type: ignore[assignment]

    with pytest.raises(EDLValidationError, match="must be a number"):
        validate_edl(edl, tmp_path, probe)
