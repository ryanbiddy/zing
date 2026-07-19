"""Assemble an EDL with synthesized voiceover and optional NLE export."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Sequence

from myzing.schemas import AudioTrack, EDL

from .otio_export import OTIOExportResult, export_otio
from .pipeline import RenderResult, render_edl
from .tts import (
    DEFAULT_LANGUAGE,
    DEFAULT_VOICE,
    SynthesisRequest,
    SynthesisResult,
    TTSGenerationError,
    TTSProvider,
    default_tts_provider,
)


@dataclass(frozen=True)
class VoiceoverScript:
    text: str
    timeline_start: float = 0.0
    gain_db: float = 0.0
    voice: str = DEFAULT_VOICE
    speed: float = 1.0
    language: str = DEFAULT_LANGUAGE

    def __post_init__(self) -> None:
        SynthesisRequest(
            text=self.text,
            voice=self.voice,
            speed=self.speed,
            language=self.language,
        )
        for value, label in (
            (self.timeline_start, "voiceover timeline_start"),
            (self.gain_db, "voiceover gain_db"),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
            ):
                raise ValueError(f"{label} must be a finite number")
        if self.timeline_start < 0:
            raise ValueError("voiceover timeline_start must be non-negative")


@dataclass(frozen=True)
class AssembleResult:
    render: RenderResult
    voiceovers: tuple[SynthesisResult, ...]
    otio: OTIOExportResult | None


def render_assembled_edl(
    edl: EDL,
    output_path: Path,
    *,
    scripts: Sequence[VoiceoverScript] = (),
    provider: TTSProvider | None = None,
    voiceover_dir: Path | None = None,
    otio_path: Path | None = None,
    base_dir: Path | None = None,
    work_dir: Path | None = None,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> AssembleResult:
    """Synthesize scripts, render the augmented EDL, then export its timeline."""
    output_path = output_path.expanduser().resolve()
    base_dir = (base_dir or Path.cwd()).resolve()
    scripts = tuple(scripts)
    if scripts and provider is None:
        provider = default_tts_provider()
    asset_dir = (
        voiceover_dir.expanduser().resolve()
        if voiceover_dir is not None
        else output_path.parent / f"{output_path.stem}-assets"
    )
    asset_dir_existed = asset_dir.exists()
    if scripts:
        try:
            asset_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise TTSGenerationError(
                f"could not create voiceover asset directory: {exc}"
            ) from exc

    synthesized: list[SynthesisResult] = []
    augmented_audio = list(edl.audio)
    try:
        for index, script in enumerate(scripts, start=1):
            if provider is None:
                raise TTSGenerationError("no TTS provider is available")
            request = SynthesisRequest(
                text=script.text,
                voice=script.voice,
                speed=script.speed,
                language=script.language,
            )
            result = provider.synthesize(
                request,
                asset_dir / f"voiceover-{index:02d}.wav",
            )
            if not result.path.is_file():
                raise TTSGenerationError(
                    f"TTS provider {result.provider!r} reported success without "
                    f"creating {result.path}"
                )
            synthesized.append(result)
            augmented_audio.append(
                AudioTrack(
                    src=str(result.path),
                    kind="voiceover",
                    timeline_start=script.timeline_start,
                    gain_db=script.gain_db,
                )
            )
    except Exception:
        if scripts and not asset_dir_existed:
            try:
                asset_dir.rmdir()
            except OSError:
                pass
        raise

    augmented = replace(edl, audio=augmented_audio)
    render_result = render_edl(
        augmented,
        output_path,
        base_dir=base_dir,
        work_dir=work_dir,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
    )
    otio_result = None
    if otio_path is not None:
        otio_result = export_otio(
            augmented,
            otio_path.expanduser().resolve(),
            base_dir=base_dir,
            ffprobe=ffprobe,
        )
    return AssembleResult(
        render=render_result,
        voiceovers=tuple(synthesized),
        otio=otio_result,
    )
