"""Generate exact-by-construction media fixtures with FFmpeg."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Sequence


HERE = Path(__file__).resolve().parent
DEFAULT_OUTPUT = HERE / "goldens"
SPEECH_FIXTURE = HERE / "fixtures" / "speech" / "ripe-figs-spoken.wav"

CASES: tuple[dict[str, Any], ...] = (
    {
        "fixture_id": "primary",
        "directory": "01 primary",
        "colors": ["red", "green", "blue"],
        "caption": {"text": "HELLO ZING", "start": 0.2, "end": 1.8},
        "audio": ["signal", "silence", "signal"],
    },
    {
        "fixture_id": "quick-cuts",
        "directory": "02 quick cuts",
        "colors": ["yellow", "magenta", "cyan"],
        "caption": {"text": "QUICK CUTS", "start": 0.8, "end": 2.2},
        "audio": ["silence", "signal", "signal"],
    },
    {
        "fixture_id": "creator-sample",
        "directory": "03 creator's sample",
        "colors": ["black", "white", "orange"],
        "caption": {"text": "CREATOR TEST", "start": 1.1, "end": 2.8},
        "audio": ["signal", "signal", "silence"],
    },
)


class GoldenGenerationError(RuntimeError):
    """FFmpeg could not generate a requested golden."""


def _drawtext_value(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace(":", "\\:")
        .replace("%", "\\%")
    )


def _graph_for(case: dict[str, Any]) -> str:
    colors = case["colors"]
    audio_pattern = case["audio"]
    video_legs = [
        f"[{index}:v]setpts=PTS-STARTPTS,format=yuv420p[v{index}]"
        for index in range(len(colors))
    ]
    video_inputs = "".join(f"[v{index}]" for index in range(len(colors)))
    caption = case["caption"]
    video_legs.append(
        f"{video_inputs}concat=n={len(colors)}:v=1:a=0,"
        "drawtext=font=Sans:"
        f"text='{_drawtext_value(caption['text'])}':"
        "fontcolor=white:fontsize=36:borderw=2:bordercolor=black:"
        "x=(w-text_w)/2:y=(h-text_h)/2:"
        f"enable='between(t,{caption['start']},{caption['end']})'[v]"
    )

    first_audio = len(colors)
    audio_legs = [
        (
            f"[{first_audio + index}:a]"
            "aformat=sample_fmts=fltp:sample_rates=48000:"
            f"channel_layouts=mono[a{index}]"
        )
        for index in range(len(audio_pattern))
    ]
    audio_inputs = "".join(f"[a{index}]" for index in range(len(audio_pattern)))
    audio_legs.append(
        f"{audio_inputs}concat=n={len(audio_pattern)}:v=0:a=1[a]"
    )
    return ";\n".join(video_legs + audio_legs) + "\n"


def _command_for(
    ffmpeg: str,
    case: dict[str, Any],
    graph_path: Path,
    output_path: Path,
) -> list[str]:
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for color in case["colors"]:
        command.extend(
            [
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s=320x568:r=30:d=1",
            ]
        )
    for window in case["audio"]:
        if window == "signal":
            command.extend(["-i", str(SPEECH_FIXTURE)])
        else:
            command.extend(
                ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono:d=1"]
            )
    command.extend(
        [
            "-filter_complex_script",
            str(graph_path),
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            "-shortest",
            str(output_path),
        ]
    )
    return command


def generate_goldens(output: Path = DEFAULT_OUTPUT, ffmpeg: str = "ffmpeg") -> list[Path]:
    """Generate all media and truth files, returning the case directories."""
    if shutil.which(ffmpeg) is None:
        raise GoldenGenerationError(f"ffmpeg executable not found: {ffmpeg}")
    if not SPEECH_FIXTURE.is_file():
        raise GoldenGenerationError(
            f"spoken fixture not found: {SPEECH_FIXTURE}"
        )

    case_directories = []
    for case in CASES:
        case_directory = output / case["directory"]
        case_directory.mkdir(parents=True, exist_ok=True)
        graph_path = case_directory / "filter graph.txt"
        media_path = case_directory / "golden video.mp4"
        graph_path.write_text(_graph_for(case), encoding="utf-8")
        result = subprocess.run(
            _command_for(ffmpeg, case, graph_path, media_path),
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise GoldenGenerationError(
                f"ffmpeg failed for {case['fixture_id']}: {result.stderr.strip()}"
            )

        truth = {
            "schema_version": 1,
            "fixture_id": case["fixture_id"],
            "media": media_path.name,
            "duration": 3.0,
            "video": {"width": 320, "height": 568, "fps": 30.0},
            "cuts": [1.0, 2.0],
            "captions": [case["caption"]],
            "audio": {
                "windows": case["audio"],
                "speech_ratio": round(
                    case["audio"].count("signal") / len(case["audio"]),
                    3,
                ),
            },
        }
        (case_directory / "truth.json").write_text(
            json.dumps(truth, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        case_directories.append(case_directory)
    return case_directories


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args(argv)
    try:
        directories = generate_goldens(args.output, args.ffmpeg)
    except GoldenGenerationError as exc:
        parser.exit(2, f"error: {exc}\n")
    for directory in directories:
        print(directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
