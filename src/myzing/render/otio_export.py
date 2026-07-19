"""One-way EDL export through OpenTimelineIO's native ``.otio`` adapter."""

from __future__ import annotations

import importlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from myzing.schemas import EDL

from .pipeline import probe_media
from .validation import Probe, ValidatedEDL, validate_edl


class OTIOExportError(RuntimeError):
    """The EDL could not be represented or serialized as OpenTimelineIO."""


@dataclass(frozen=True)
class OTIOExportResult:
    output_path: Path
    track_count: int
    duration: float


def _time(otio: Any, seconds: float, rate: float) -> Any:
    return otio.opentime.RationalTime(seconds * rate, rate)


def _range(
    otio: Any,
    start_seconds: float,
    duration_seconds: float,
    rate: float,
) -> Any:
    return otio.opentime.TimeRange(
        _time(otio, start_seconds, rate),
        _time(otio, duration_seconds, rate),
    )


def _media_reference(
    otio: Any,
    path: Path,
    duration: float,
    rate: float,
) -> Any:
    return otio.schema.ExternalReference(
        target_url=path.resolve().as_uri(),
        available_range=_range(otio, 0.0, duration, rate),
        metadata={"myzing": {"source_path": str(path.resolve())}},
    )


def _clip(
    otio: Any,
    *,
    name: str,
    path: Path,
    media_duration: float,
    source_start: float,
    duration: float,
    rate: float,
    metadata: dict[str, object],
) -> Any:
    return otio.schema.Clip(
        name=name,
        media_reference=_media_reference(
            otio,
            path,
            media_duration,
            rate,
        ),
        source_range=_range(otio, source_start, duration, rate),
        metadata={"myzing": metadata},
    )


def _gap(otio: Any, duration: float, rate: float) -> Any:
    return otio.schema.Gap(
        source_range=_range(otio, 0.0, duration, rate),
    )


def _timeline_from_validated(otio: Any, validated: ValidatedEDL, name: str) -> Any:
    edl = validated.edl
    rate = float(edl.fps)
    timeline = otio.schema.Timeline(
        name=name,
        metadata={
            "myzing": {
                "edl_schema_version": edl.schema_version,
                "dimensions": [edl.width, edl.height],
                "fps": rate,
                "duration": validated.duration,
                "output_preset": validated.output_preset,
            }
        },
    )

    video_track = otio.schema.Track(
        name="Video 1",
        kind=otio.schema.TrackKind.Video,
        metadata={"myzing": {"role": "picture"}},
    )
    for index, resolved in enumerate(validated.clips, start=1):
        clip = resolved.spec
        video_track.append(
            _clip(
                otio,
                name=f"{index:03d} · {resolved.path.name}",
                path=resolved.path,
                media_duration=resolved.media.duration,
                source_start=clip.src_in,
                duration=clip.src_out - clip.src_in,
                rate=rate,
                metadata={
                    "role": "picture",
                    "timeline_start": clip.timeline_start,
                },
            )
        )
    for caption in edl.captions:
        video_track.markers.append(
            otio.schema.Marker(
                name=caption.text,
                marked_range=_range(
                    otio,
                    caption.start,
                    caption.end - caption.start,
                    rate,
                ),
                metadata={
                    "myzing": {
                        "role": "caption",
                        "position": caption.position,
                        "all_caps": caption.all_caps,
                        "word_timed": caption.word_timed,
                    }
                },
            )
        )
    timeline.tracks.append(video_track)

    if any(resolved.media.has_audio for resolved in validated.clips):
        source_audio = otio.schema.Track(
            name="Source Audio",
            kind=otio.schema.TrackKind.Audio,
            metadata={"myzing": {"role": "source_audio"}},
        )
        for index, resolved in enumerate(validated.clips, start=1):
            clip = resolved.spec
            duration = clip.src_out - clip.src_in
            if resolved.media.has_audio:
                source_audio.append(
                    _clip(
                        otio,
                        name=f"{index:03d} · {resolved.path.name}",
                        path=resolved.path,
                        media_duration=resolved.media.duration,
                        source_start=clip.src_in,
                        duration=duration,
                        rate=rate,
                        metadata={
                            "role": "source_audio",
                            "timeline_start": clip.timeline_start,
                        },
                    )
                )
            else:
                source_audio.append(_gap(otio, duration, rate))
        timeline.tracks.append(source_audio)

    kind_counts = {"voiceover": 0, "music": 0}
    for resolved in validated.audio_tracks:
        spec = resolved.spec
        kind_counts[spec.kind] += 1
        title = "Voiceover" if spec.kind == "voiceover" else "Music"
        audio_track = otio.schema.Track(
            name=f"{title} {kind_counts[spec.kind]}",
            kind=otio.schema.TrackKind.Audio,
            metadata={"myzing": {"role": spec.kind}},
        )
        if spec.timeline_start > 0:
            audio_track.append(_gap(otio, spec.timeline_start, rate))
        audible_duration = max(
            0.0,
            min(
                resolved.media.duration,
                validated.duration - spec.timeline_start,
            ),
        )
        if audible_duration > 0:
            audio_track.append(
                _clip(
                    otio,
                    name=resolved.path.name,
                    path=resolved.path,
                    media_duration=resolved.media.duration,
                    source_start=0.0,
                    duration=audible_duration,
                    rate=rate,
                    metadata={
                        "role": spec.kind,
                        "timeline_start": spec.timeline_start,
                        "gain_db": spec.gain_db,
                        "duck_under_speech": spec.duck_under_speech,
                    },
                )
            )
        timeline.tracks.append(audio_track)
    return timeline


def _load_otio() -> Any:
    try:
        return importlib.import_module("opentimelineio")
    except (ImportError, ModuleNotFoundError) as exc:
        raise OTIOExportError(
            "OpenTimelineIO is required for .otio export; install the "
            "Apache-2.0 `OpenTimelineIO` package in the render environment."
        ) from exc


def export_otio(
    edl: EDL,
    output_path: Path,
    *,
    base_dir: Path | None = None,
    ffprobe: str = "ffprobe",
    probe: Probe | None = None,
) -> OTIOExportResult:
    """Validate an EDL and atomically write an NLE-ready native OTIO file."""
    output_path = output_path.expanduser().resolve()
    if output_path.suffix.lower() != ".otio":
        raise OTIOExportError("OpenTimelineIO output must use the .otio extension")
    base_dir = (base_dir or Path.cwd()).resolve()
    validated = validate_edl(
        edl,
        base_dir,
        probe or (lambda path: probe_media(path, ffprobe)),
    )
    otio = _load_otio()
    timeline = _timeline_from_validated(otio, validated, output_path.stem)

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{output_path.stem}-",
            suffix=".otio",
            dir=output_path.parent,
        )
        os.close(handle)
    except OSError as exc:
        raise OTIOExportError(f"could not create OTIO output directory: {exc}") from exc
    temporary_path = Path(temporary_name)
    try:
        otio.adapters.write_to_file(timeline, str(temporary_path))
        if not temporary_path.is_file() or temporary_path.stat().st_size == 0:
            raise OTIOExportError(
                "OpenTimelineIO reported success but produced no output"
            )
        os.replace(temporary_path, output_path)
    except OTIOExportError:
        temporary_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        temporary_path.unlink(missing_ok=True)
        raise OTIOExportError(f"OpenTimelineIO export failed: {exc}") from exc
    return OTIOExportResult(
        output_path=output_path,
        track_count=len(timeline.tracks),
        duration=validated.duration,
    )
