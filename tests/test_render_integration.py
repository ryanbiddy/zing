from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from myzing.render.assemble import VoiceoverScript, render_assembled_edl
from myzing.render.captions import caption_anchor
from myzing.render.pipeline import render_edl
from myzing.render.tts import SynthesisResult
from myzing.schemas import AudioTrack, CaptionSpec, Clip, EDL, Word


# Skip/fail behavior lives in tests/conftest.py: skips honestly when
# ffmpeg is absent, fails hard under ZING_REQUIRE_FFMPEG=1 (CI gates).
pytestmark = pytest.mark.ffmpeg


def run_ffmpeg(*arguments: str) -> None:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def make_color_video(
    path: Path,
    color: str,
    duration: float = 1.0,
    *,
    tone_hz: int | None = None,
    size: str = "180x320",
) -> None:
    arguments = [
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s={size}:r=30:d={duration}",
    ]
    if tone_hz is not None:
        arguments.extend(
            [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={tone_hz}:sample_rate=48000:duration={duration}",
                "-shortest",
            ]
        )
    arguments.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
        ]
    )
    if tone_hz is None:
        arguments.append("-an")
    else:
        arguments.extend(["-c:a", "aac", "-ar", "48000", "-ac", "2"])
    arguments.append(str(path))
    run_ffmpeg(*arguments)


def make_tone(path: Path, frequency: int, duration: float, volume: float = 1.0) -> None:
    run_ffmpeg(
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={frequency}:sample_rate=48000:duration={duration}",
        "-af",
        f"volume={volume}",
        "-c:a",
        "pcm_s16le",
        str(path),
    )


def probe(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-show_entries",
            "stream=codec_type,width,height,r_frame_rate,pix_fmt,sample_rate,channels",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def pixel(path: Path, timestamp: float, x: int, y: int) -> tuple[int, int, int]:
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-ss",
            str(timestamp),
            "-vf",
            f"crop=1:1:{x}:{y}:exact=1,format=rgb24",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    return tuple(result.stdout[:3])


def gray_region(
    path: Path,
    timestamp: float,
    x: int,
    y: int,
    width: int,
    height: int,
) -> bytes:
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-ss",
            str(timestamp),
            "-vf",
            f"crop={width}:{height}:{x}:{y},format=gray",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    return result.stdout


def mean_volume(
    path: Path,
    start: float = 0.0,
    duration: float | None = None,
    band_hz: int | None = None,
) -> float:
    command = ["ffmpeg", "-hide_banner", "-i", str(path)]
    filters = []
    if start or duration is not None:
        trim = f"atrim=start={start}"
        if duration is not None:
            trim += f":duration={duration}"
        filters.extend([trim, "asetpts=PTS-STARTPTS"])
    if band_hz is not None:
        filters.append(f"bandpass=f={band_hz}:width_type=h:width=40")
    filters.append("volumedetect")
    command.extend(["-vn", "-af", ",".join(filters), "-f", "null", "-"])
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?) dB", result.stderr)
    assert match, result.stderr
    return float(match.group(1))


def test_golden_edl_renders_with_content_probes_and_ducking(
    tmp_path: Path,
) -> None:
    root = tmp_path / "creator's render fixtures"
    root.mkdir()
    first = root / "first clip.mp4"
    second = root / "second clip.mp4"
    music = root / "music bed.wav"
    voice = root / "voice over.wav"
    make_color_video(first, "red")
    make_color_video(second, "blue")
    make_tone(music, 120, 2.0, 0.8)
    make_tone(voice, 3000, 1.0)

    edl = EDL(
        clips=[
            Clip(str(first), 0.0, 1.0, 0.0),
            Clip(str(second), 0.0, 1.0, 1.0),
        ],
        captions=[
            CaptionSpec(
                text="hello zing",
                start=0.3,
                end=1.3,
                position="lower",
                words=[
                    Word("hello", 0.3, 0.8),
                    Word("zing", 0.8, 1.3),
                ],
            )
        ],
        audio=[
            AudioTrack(str(voice), "voiceover", timeline_start=0.5),
            AudioTrack(str(music), "music", duck_under_speech=True),
        ],
        width=360,
        height=640,
        fps=30.0,
    )
    output = root / "rendered output.mp4"
    work = root / "kept work"

    result = render_edl(edl, output, base_dir=root, work_dir=work)

    metadata = probe(output)
    assert float(metadata["format"]["duration"]) == pytest.approx(2.0, abs=0.05)
    video = next(
        stream for stream in metadata["streams"] if stream["codec_type"] == "video"
    )
    audio = next(
        stream for stream in metadata["streams"] if stream["codec_type"] == "audio"
    )
    assert (video["width"], video["height"]) == (360, 640)
    assert video["r_frame_rate"] == "30/1"
    assert video["pix_fmt"] == "yuv420p"
    assert (audio["sample_rate"], audio["channels"]) == ("48000", 2)
    assert pixel(output, 0.2, 20, 20)[0] > 150
    assert pixel(output, 1.7, 20, 20)[2] > 150

    anchor_x, anchor_y = caption_anchor("lower", 360, 640)
    off = gray_region(output, 0.2, anchor_x - 80, anchor_y - 35, 160, 70)
    on = gray_region(output, 0.5, anchor_x - 80, anchor_y - 35, 160, 70)
    assert len(off) == len(on) == 160 * 70
    assert sum(abs(left - right) for left, right in zip(off, on)) > 10_000
    ass_text = (work / "captions.ass").read_text(encoding="utf-8-sig")
    assert r"\kf50" in ass_text
    assert r"\t(" in ass_text
    assert "-filter_complex_script" in result.command

    music_without_voice = mean_volume(output, 0.1, 0.3, band_hz=120)
    music_under_voice = mean_volume(output, 0.8, 0.3, band_hz=120)
    duck_depth = music_without_voice - music_under_voice
    assert 6.0 <= duck_depth <= 12.0


def test_clip_audio_is_retained_at_unity(tmp_path: Path) -> None:
    source = tmp_path / "clip with audio.mp4"
    make_color_video(source, "green", tone_hz=330)
    output = tmp_path / "retained audio.mp4"
    edl = EDL(
        clips=[Clip(str(source), 0.0, 1.0, 0.0)],
        width=180,
        height=320,
    )

    render_edl(edl, output, base_dir=tmp_path)

    assert abs(mean_volume(source) - mean_volume(output)) <= 1.0


def test_landscape_preset_renders_centered_captions(
    tmp_path: Path,
) -> None:
    source = tmp_path / "landscape source.mp4"
    make_color_video(source, "navy", size="320x180")
    output = tmp_path / "landscape output.mp4"
    edl = EDL(
        clips=[Clip(str(source), 0.0, 1.0, 0.0)],
        captions=[
            CaptionSpec(
                text="long form",
                start=0.25,
                end=0.75,
                position="bottom",
                word_timed=False,
            )
        ],
        width=320,
        height=180,
    )

    render_edl(edl, output, base_dir=tmp_path)

    metadata = probe(output)
    video = next(
        stream for stream in metadata["streams"] if stream["codec_type"] == "video"
    )
    assert (video["width"], video["height"]) == (320, 180)
    anchor_x, anchor_y = caption_anchor("bottom", 320, 180)
    assert anchor_x == 160
    off = gray_region(output, 0.1, anchor_x - 75, anchor_y - 25, 150, 40)
    on = gray_region(output, 0.5, anchor_x - 75, anchor_y - 25, 150, 40)
    assert len(off) == len(on) == 150 * 40
    assert sum(abs(left - right) for left, right in zip(off, on)) > 5_000


def test_no_audio_inputs_still_produce_silent_track(tmp_path: Path) -> None:
    source = tmp_path / "silent clip.mp4"
    make_color_video(source, "black")
    output = tmp_path / "silent output.mp4"
    edl = EDL(
        clips=[Clip(str(source), 0.0, 1.0, 0.0)],
        width=180,
        height=320,
    )

    render_edl(edl, output, base_dir=tmp_path)

    metadata = probe(output)
    assert any(
        stream["codec_type"] == "audio" for stream in metadata["streams"]
    )
    assert mean_volume(output) < -80.0


def test_zing_render_command_dispatches_end_to_end(tmp_path: Path) -> None:
    source = tmp_path / "relative source.mp4"
    make_color_video(source, "purple", duration=0.8)
    edl_path = tmp_path / "edit.json"
    edl_path.write_text(
        EDL(
            clips=[Clip(source.name, 0.0, 0.8, 0.0)],
            width=180,
            height=320,
        ).to_json(indent=2),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-m", "myzing.cli", "render", str(edl_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    output = edl_path.with_suffix(".mp4")
    assert result.returncode == 0, result.stderr
    assert str(output) in result.stdout
    assert output.stat().st_size > 0


def test_scripted_voiceover_is_audible_in_rendered_output(tmp_path: Path) -> None:
    source = tmp_path / "silent source.mp4"
    make_color_video(source, "teal", duration=1.5)
    output = tmp_path / "scripted draft.mp4"

    class ToneVoiceProvider:
        name = "constructed-tone"

        def synthesize(self, request, output_path: Path) -> SynthesisResult:
            make_tone(output_path, 3_000, 0.6)
            return SynthesisResult(
                path=output_path.resolve(),
                provider=self.name,
                voice=request.voice,
                sample_rate=48_000,
                duration=0.6,
            )

    result = render_assembled_edl(
        EDL(
            clips=[Clip(str(source), 0.0, 1.5, 0.0)],
            captions=[
                CaptionSpec(
                    "Result first",
                    0.4,
                    1.0,
                    word_timed=False,
                )
            ],
            width=180,
            height=320,
        ),
        output,
        scripts=[VoiceoverScript("The result comes first.", timeline_start=0.4)],
        provider=ToneVoiceProvider(),
        base_dir=tmp_path,
    )

    before_voice = mean_volume(output, 0.05, 0.2, band_hz=3_000)
    during_voice = mean_volume(output, 0.55, 0.2, band_hz=3_000)
    assert during_voice - before_voice >= 30.0
    anchor_x, anchor_y = caption_anchor("lower", 180, 320)
    caption_off = gray_region(
        output,
        0.1,
        anchor_x - 70,
        anchor_y - 25,
        140,
        50,
    )
    caption_on = gray_region(
        output,
        0.7,
        anchor_x - 70,
        anchor_y - 25,
        140,
        50,
    )
    assert sum(
        abs(left - right) for left, right in zip(caption_off, caption_on)
    ) > 5_000
    assert result.voiceovers[0].path.name == "voiceover-01.wav"
