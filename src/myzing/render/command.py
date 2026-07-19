"""CLI for ``zing render <edl.json>``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from myzing.schemas import EDL

from .assemble import VoiceoverScript, render_assembled_edl
from .otio_export import OTIOExportError
from .pipeline import RenderError, render_edl
from .tts import TTSGenerationError, TTSUnavailableError, default_tts_provider
from .validation import EDLValidationError


class _UsageError(ValueError):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _UsageError(message)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="zing render")
    parser.add_argument("edl", type=Path, help="EDL JSON file")
    parser.add_argument("-o", "--output", type=Path, help="output MP4 path")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument(
        "--keep-work",
        type=Path,
        help="retain generated ASS and filtergraph in this directory",
    )
    parser.add_argument(
        "--voiceover-script",
        type=Path,
        help="UTF-8 text file to synthesize as a Kokoro voiceover track",
    )
    parser.add_argument(
        "--voiceover-start",
        type=float,
        default=0.0,
        help="voiceover placement on the output timeline in seconds",
    )
    parser.add_argument("--voice", default="af_sarah", help="Kokoro voice ID")
    parser.add_argument(
        "--voice-language",
        default="en-us",
        help="Kokoro language ID",
    )
    parser.add_argument(
        "--voice-speed",
        type=float,
        default=1.0,
        help="positive Kokoro speaking-speed multiplier",
    )
    parser.add_argument(
        "--kokoro-model-dir",
        type=Path,
        help="directory containing kokoro-v1.0.onnx and voices-v1.0.bin",
    )
    parser.add_argument(
        "--otio",
        type=Path,
        help="also export the assembled timeline to this .otio file",
    )
    return parser


def run(argv: list[str]) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except _UsageError as exc:
        print(f"zing render: {exc}", file=sys.stderr)
        print(parser.format_usage().strip(), file=sys.stderr)
        return 2
    except SystemExit as exc:
        return int(exc.code or 0)

    edl_path = args.edl.expanduser().resolve()
    if not edl_path.is_file():
        print(f"zing render: EDL file does not exist: {edl_path}", file=sys.stderr)
        return 2
    try:
        payload = json.loads(edl_path.read_text(encoding="utf-8"))
        edl = EDL.from_dict(payload)
    except (OSError, TypeError, ValueError, KeyError) as exc:
        print(f"zing render: invalid EDL JSON: {exc}", file=sys.stderr)
        return 2

    output = (
        args.output.expanduser().resolve()
        if args.output
        else edl_path.with_suffix(".mp4")
    )
    scripts = []
    provider = None
    if args.voiceover_script is not None:
        script_path = args.voiceover_script.expanduser().resolve()
        if not script_path.is_file():
            print(
                f"zing render: voiceover script does not exist: {script_path}",
                file=sys.stderr,
            )
            return 2
        try:
            script_text = script_path.read_text(encoding="utf-8")
            scripts.append(
                VoiceoverScript(
                    text=script_text,
                    timeline_start=args.voiceover_start,
                    voice=args.voice,
                    speed=args.voice_speed,
                    language=args.voice_language,
                )
            )
        except (OSError, ValueError) as exc:
            print(f"zing render: invalid voiceover script: {exc}", file=sys.stderr)
            return 2
        provider = default_tts_provider(args.kokoro_model_dir)
    elif args.kokoro_model_dir is not None:
        print(
            "zing render: --kokoro-model-dir requires --voiceover-script",
            file=sys.stderr,
        )
        return 2
    otio_path = args.otio.expanduser().resolve() if args.otio else None
    try:
        if scripts or otio_path is not None:
            assembled = render_assembled_edl(
                edl,
                output,
                scripts=scripts,
                provider=provider,
                otio_path=otio_path,
                base_dir=edl_path.parent,
                work_dir=args.keep_work,
                ffmpeg=args.ffmpeg,
                ffprobe=args.ffprobe,
            )
            result = assembled.render
        else:
            assembled = None
            result = render_edl(
                edl,
                output,
                base_dir=edl_path.parent,
                work_dir=args.keep_work,
                ffmpeg=args.ffmpeg,
                ffprobe=args.ffprobe,
            )
    except (
        EDLValidationError,
        OTIOExportError,
        RenderError,
        TTSGenerationError,
        TTSUnavailableError,
    ) as exc:
        print(f"zing render: {exc}", file=sys.stderr)
        return 1

    for warning in result.warnings:
        print(f"zing render: warning: {warning}", file=sys.stderr)
    if assembled is not None:
        for voiceover in assembled.voiceovers:
            print(f"zing render: voiceover: {voiceover.path}", file=sys.stderr)
        if assembled.otio is not None:
            print(
                f"zing render: OpenTimelineIO: {assembled.otio.output_path}",
                file=sys.stderr,
            )
    print(result.output_path)
    return 0
