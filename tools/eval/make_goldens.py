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
TRANSITION_OUTPUT = HERE / "transition_goldens"

PATTERN_A = (
    "color=c=0x2040c0:s={size}:r={fps}:d={duration},"
    "drawbox=x=8:y=8:w=22:h=72:c=white:t=fill,"
    "drawbox=x=52:y=18:w=34:h=28:c=yellow:t=fill,"
    "drawbox=x=45:y=62:w=42:h=20:c=0x20d080:t=fill"
)
PATTERN_B = (
    "color=c=0xc03020:s={size}:r={fps}:d={duration},"
    "drawbox=x=10:y=12:w=70:h=18:c=0x20e0e0:t=fill,"
    "drawbox=x=16:y=48:w=28:h=38:c=white:t=fill,"
    "drawbox=x=58:y=52:w=26:h=30:c=0x202020:t=fill"
)

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

TRANSITION_CASES: tuple[dict[str, Any], ...] = (
    {
        "fixture_id": "hard-cut",
        "directory": "01 hard cut",
        "kind": "hard_cut",
        "start": 1.2,
        "end": 1.2,
        "signatures": ["hard_cut"],
    },
    {
        "fixture_id": "dissolve",
        "directory": "02 dissolve",
        "kind": "dissolve",
        "start": 0.9,
        "end": 1.5,
        "signatures": ["dissolve"],
    },
    {
        "fixture_id": "wipe",
        "directory": "03 wipe",
        "kind": "wipe",
        "start": 0.9,
        "end": 1.5,
        "signatures": ["wipe"],
    },
    {
        "fixture_id": "zoom-punch",
        "directory": "04 zoom punch",
        "kind": "zoom_punch",
        "start": 1.0,
        "end": 1.4,
        "signatures": ["zoom_punch"],
    },
    {
        "fixture_id": "audio-aligned-cut",
        "directory": "05 audio-aligned cut",
        "kind": "audio_aligned_cut",
        "start": 1.2,
        "end": 1.2,
        "signatures": ["hard_cut", "audio_aligned_cut"],
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


def _transition_command(
    ffmpeg: str,
    case: dict[str, Any],
    output_path: Path,
) -> list[str]:
    fps = 30
    duration = 2.4
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    kind = case["kind"]
    if kind == "zoom_punch":
        source = PATTERN_A.format(size="128x128", fps=fps, duration=duration)
        command.extend(["-f", "lavfi", "-i", source])
        command.extend(
            [
                "-f",
                "lavfi",
                "-i",
                f"anullsrc=r=48000:cl=mono:d={duration}",
                "-filter_complex",
                (
                    "[0:v]zoompan="
                    "z='if(lt(on,30),1,if(lt(on,42),"
                    "1+(on-30)*0.033333,1.4))':"
                    "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                    "d=1:s=96x96:fps=30,format=yuv420p[v]"
                ),
                "-map",
                "[v]",
                "-map",
                "1:a:0",
            ]
        )
    else:
        source_a = PATTERN_A.format(size="96x96", fps=fps, duration=1.5)
        source_b = PATTERN_B.format(size="96x96", fps=fps, duration=1.5)
        command.extend(["-f", "lavfi", "-i", source_a])
        command.extend(["-f", "lavfi", "-i", source_b])
        if kind == "audio_aligned_cut":
            command.extend(
                ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono:d=1.2"]
            )
            command.extend(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=880:sample_rate=48000:duration=1.2",
                ]
            )
            audio_graph = "[2:a][3:a]concat=n=2:v=0:a=1[a]"
        else:
            command.extend(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    f"anullsrc=r=48000:cl=mono:d={duration}",
                ]
            )
            audio_graph = "[2:a]anull[a]"

        if kind in {"hard_cut", "audio_aligned_cut"}:
            video_graph = (
                "[0:v]trim=duration=1.2,setpts=PTS-STARTPTS[a];"
                "[1:v]trim=duration=1.2,setpts=PTS-STARTPTS[b];"
                "[a][b]concat=n=2:v=1:a=0,format=yuv420p[v]"
            )
        else:
            transition = "dissolve" if kind == "dissolve" else "wipeleft"
            video_graph = (
                f"[0:v][1:v]xfade=transition={transition}:"
                "duration=0.6:offset=0.9,format=yuv420p[v]"
            )
        command.extend(
            [
                "-filter_complex",
                video_graph + ";" + audio_graph,
                "-map",
                "[v]",
                "-map",
                "[a]",
            ]
        )

    command.extend(
        [
            "-t",
            str(duration),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "12",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "1",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    return command


def generate_transition_goldens(
    output: Path = TRANSITION_OUTPUT,
    ffmpeg: str = "ffmpeg",
) -> list[Path]:
    """Generate exact transition fixtures and their signature truth."""
    if shutil.which(ffmpeg) is None:
        raise GoldenGenerationError(f"ffmpeg executable not found: {ffmpeg}")
    directories = []
    for case in TRANSITION_CASES:
        directory = output / case["directory"]
        directory.mkdir(parents=True, exist_ok=True)
        media_path = directory / "transition.mp4"
        result = subprocess.run(
            _transition_command(ffmpeg, case, media_path),
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
            "duration": 2.4,
            "video": {"width": 96, "height": 96, "fps": 30.0},
            "transition": {
                "start": case["start"],
                "end": case["end"],
                "signatures": case["signatures"],
            },
        }
        (directory / "transition-truth.json").write_text(
            json.dumps(truth, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        directories.append(directory)
    return directories


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
    parser.add_argument(
        "--transitions",
        action="store_true",
        help="generate the transition-prototype goldens instead",
    )
    args = parser.parse_args(argv)
    try:
        if args.transitions:
            directories = generate_transition_goldens(args.output, args.ffmpeg)
        else:
            directories = generate_goldens(args.output, args.ffmpeg)
    except GoldenGenerationError as exc:
        parser.exit(2, f"error: {exc}\n")
    for directory in directories:
        print(directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
