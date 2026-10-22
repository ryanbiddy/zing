"""Capability-checked Composition v2 adapter; the v1 path stays independent."""

from __future__ import annotations

import hashlib
import re
import tempfile
from dataclasses import dataclass, fields, replace
from pathlib import Path

from myzing.composition import Composition, frame_index, load_composition
from myzing.composition.timebase import rate_fraction
from myzing.ffmpeg_capabilities import FFmpegCapabilityError, require_lut3d, require_transitions
from myzing.schemas import AudioTrack, CaptionSpec, Clip, EDL
from myzing.timing import TimingReviewError, prepare_words

from . import pipeline
from .font_files import ass_em_scale, private_font
from .validation import EDLValidationError, output_preset, validate_edl
from .transitions import SUPPORTED_KINDS, timeline_joins, validate_render_windows


def load_render_document(data: dict) -> EDL | Composition:
    """Dispatch by version without upgrading v1 or changing its render bytes."""
    if isinstance(data, dict) and type(data.get("schema_version")) is int and data["schema_version"] == 2:
        return load_composition(data)
    return EDL.from_dict(data)


def unsupported_features(composition: Composition) -> list[str]:
    problems = []
    for clip in composition.clips:
        if clip.speed_map:
            problems.append(f"clip {clip.id}: speed maps")
    for transition in composition.transitions:
        if transition.recipe.kind not in SUPPORTED_KINDS:
            problems.append(f"transition {transition.id} ({transition.outgoing_clip} -> {transition.incoming_clip}, {transition.recipe.duration_seconds:g}s): {transition.recipe.kind}")
    for caption in composition.captions:
        if caption.backend not in {"ass", "hyperframes"}:
            problems.append(f"caption {caption.id}: {caption.backend} caption backend")
    for audio in composition.audio:
        if audio.role not in {"music", "voiceover"} or audio.role != audio.kind:
            problems.append(f"audio {audio.id}: role={audio.role}, kind={audio.kind}")
        if audio.src_in != 0 or audio.src_out is not None:
            problems.append(f"audio {audio.id}: source trims")
        if audio.duck_scope != "voiceover":
            problems.append(f"audio {audio.id}: duck_scope={audio.duck_scope}")
    if composition.loudness_target is not None:
        problems.append("loudness targets")
    if any(c.backend == "ass" for c in composition.captions) and rate_fraction(composition.fps) > 100:
        problems.append("ASS captions above 100 fps (centisecond event precision)")
    return problems


def _path(value: str, base_dir: Path, label: str) -> Path:
    if re.match(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]{1,}:|\\\\|//)", value):
        raise EDLValidationError(f"{label}: use a local file path; network assets are not fetched at render time")
    path = (base_dir / Path(value).expanduser()).resolve()
    if not path.is_file():
        raise EDLValidationError(f"{label}: missing asset {path}; restore it or update its path")
    return path


def _verify(path: Path, digest: str | None, label: str) -> None:
    if digest is None:
        return
    try:
        hasher = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                hasher.update(block)
    except OSError as exc:
        raise EDLValidationError(f"{label}: could not read asset {path}: {exc}") from exc
    if hasher.hexdigest() != digest:
        raise EDLValidationError(f"{label}: SHA-256 mismatch for {path}; restore the expected asset or update its checksum")


@dataclass(frozen=True)
class PreparedComposition:
    composition: Composition
    edl: EDL
    assets: dict[str, Path]
    fonts: dict[str, tuple[str, bytes]]
    input_paths: frozenset[Path]
    warnings: tuple[str, ...]
    luts: dict
    lut_paths: dict[str, Path]


def prepare_composition(composition: Composition, base_dir: Path) -> PreparedComposition:
    """Validate and hash *all* assets before probes, work files or dispatch.

    Snapshot mutable input so a queued render cannot inherit later edits.
    Null legacy hashes remain explicitly unverified, as specified by v2.
    """
    try:
        composition = Composition.from_dict(composition.to_dict())
    except (ValueError, TypeError) as exc:
        raise EDLValidationError(f"invalid Composition v2: {exc}") from exc
    problems = unsupported_features(composition)
    if problems:
        raise EDLValidationError("not yet supported in this renderer: " + "; ".join(problems))
    validate_render_windows(composition)
    if not composition.clips:
        raise EDLValidationError("composition must contain at least one clip")
    if composition.width % 2 or composition.height % 2:
        raise EDLValidationError("output width and height must be even for yuv420p")
    output_preset(composition.width, composition.height)
    # Validate every cube before media hashes, font inspection or subprocesses.
    # Imports stay lazy so ungraded renders remain stdlib-only (apart from ASS).
    from .color import prepare_lut
    lut_paths, luts = {}, {}
    for clip in composition.clips:
        if clip.color is not None:
            path = _path(clip.color.lut_path, base_dir, f"clip {clip.id} LUT")
            lut_paths[clip.id] = path
            luts[clip.id] = prepare_lut(clip.color, path, clip.id)
    warnings = list(composition.warnings)
    warnings.append("Audio peaks are limited at -2 dBFS with 4x oversampling before AAC; "
                    "loudness is not normalized and encoded true peak still needs measurement.")
    if not timeline_joins(composition):
        warnings.append("Source audio uses up to 5 ms fades at discontinuous cuts and edit edges; "
                        "adjacent source spans stay continuous.")
    frame_limit = frame_index(max(c.timeline_end for c in composition.clips), composition.fps, rounding="nearest")
    for caption in composition.captions:
        layout = caption.layout
        if layout is not None:
            unsafe = (not layout.overlap.safe or layout.reason == "infeasible"
                      or any(w.startswith("infeasible:") for w in layout.warnings))
            if unsafe and caption.id not in composition.accepted_unsafe_layouts:
                raise EDLValidationError(
                    f"caption {caption.id}: unsafe/infeasible layout; review it and explicitly add "
                    "its id to composition.accepted_unsafe_layouts to render it",
                )
            warnings.extend(f"caption {caption.id}: {w}" for w in layout.warnings)
            if unsafe:
                warnings.append(f"caption {caption.id}: unsafe layout explicitly accepted")
            if caption.style is not None and caption.style.size * layout.scale < 1:
                raise EDLValidationError(f"caption {caption.id}: layout scale makes font size smaller than one pixel")
        if caption.words:
            try:
                prepare_words(caption.words, caption.end + 1e-6, repair=False)
            except TimingReviewError as exc:
                raise EDLValidationError(f"caption {caption.id}: {exc}") from exc
        if caption.backend == "ass":
            from .positioned_captions import caption_frame_timing, caption_runs
            caption_runs(caption)  # Reject unmatched words and control characters before IO.
            warnings.extend(caption_frame_timing(caption, composition.fps, frame_limit)[3])
    paths = {}
    for asset in composition.assets:
        paths[asset.id] = _path(asset.path, base_dir, f"asset {asset.id}")
    font_paths = {
        caption.id: _path(caption.font.path, base_dir, f"caption {caption.id} font")
        for caption in composition.captions if caption.font is not None
    }
    for asset in composition.assets:
        _verify(paths[asset.id], asset.sha256, f"asset {asset.id}")
        if asset.sha256 is None:
            warnings.append(f"asset {asset.id}: no SHA-256 supplied; file identity is unverified")
    fonts = {}
    for caption in composition.captions:
        if caption.font is not None:
            path = font_paths[caption.id]
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise EDLValidationError(f"caption {caption.id}: could not read font {path}: {exc}") from exc
            if hashlib.sha256(data).hexdigest() != caption.font.sha256:
                raise EDLValidationError(f"caption {caption.id} font: SHA-256 mismatch for {path}")
            if caption.backend == "ass":
                ass_em_scale(data)
                fonts[caption.id] = private_font(data)
    # V1 structs are only the supported media graph's internal projection.
    # Resolve by asset_id, never by alias or basename (aliases can collide).
    def project(item, cls):
        values = {f.name: getattr(item, f.name) for f in fields(cls)}
        if "src" in values:
            values["src"] = item.asset_id
        return cls(**values)

    edl = EDL(
        clips=[project(c, Clip) for c in composition.clips],
        captions=[project(c, CaptionSpec) for c in composition.captions if c.backend == "ass"],
        audio=[project(a, AudioTrack) for a in composition.audio],
        width=composition.width, height=composition.height, fps=float(rate_fraction(composition.fps)),
    )
    return PreparedComposition(composition, edl, paths, fonts,
                               frozenset([*paths.values(), *font_paths.values(), *lut_paths.values()]),
                               tuple(warnings), luts, lut_paths)


def render_composition(
    composition: Composition, output: Path, *, base_dir: Path | None = None,
    work_dir: Path | None = None, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe",
) -> pipeline.RenderResult:
    """Render supported v2 instructions locally, publishing only a finished MP4."""
    base_dir = (base_dir or Path.cwd()).expanduser().resolve()
    prepared = prepare_composition(composition, base_dir)
    c = prepared.composition
    joins = timeline_joins(c)
    output = Path(output).expanduser().resolve()
    if output in prepared.input_paths:
        raise pipeline.RenderError("output path must not overwrite an input media, font or LUT file")
    hf_plan = None
    if any(event.backend == "hyperframes" for event in c.captions):
        from . import hyperframes_adapter as hf
        from .hyperframes_v2 import captions_to_plan
        try:
            # Same read-only Node/pin/browser check used by zing doctor. Even a
            # cached overlay requires the requested backend to be available.
            hf.check_install(ffmpeg=ffmpeg, ffprobe=ffprobe)
            hf_plan = captions_to_plan(c.captions, width=c.width, height=c.height,
                                      fps=c.fps, duration=max(clip.timeline_end for clip in c.clips),
                                      base_dir=base_dir)
        except hf.HyperframesError as exc:
            raise pipeline.RenderError(str(exc)) from exc
    if prepared.luts:
        try:
            require_lut3d(ffmpeg)
        except FFmpegCapabilityError as exc:
            raise pipeline.RenderError(str(exc)) from exc
    caption_filter = pipeline.preflight_captions(prepared.edl, ffmpeg)
    if joins:
        try:
            require_transitions(ffmpeg, zoom=any(t is not None and t.recipe.kind == "zoom_punch" for t in joins))
        except FFmpegCapabilityError as exc:
            raise pipeline.RenderError(str(exc)) from exc
    validated = validate_edl(prepared.edl, base_dir, lambda path: pipeline.probe_media(path, ffprobe, include_color=True),
                             resolved_assets=prepared.assets,
                             overlaps=(0.0, *(t.recipe.duration_seconds if t else 0 for t in joins)) if joins else (),
                             clip_ids=tuple(
                                 clip.id + "".join(f"; transition {t.id} ({t.outgoing_clip} -> {t.incoming_clip})"
                                                   for t in c.transitions if clip.id in (t.outgoing_clip, t.incoming_clip))
                                 for clip in c.clips) if joins else ())
    from .color import validate_source_colors, write_luts
    validated = replace(validated, warnings=prepared.warnings + validated.warnings + validate_source_colors(validated))

    def render(directory: Path):
        from .positioned_captions import generate_positioned_ass

        # Internal filenames must never overwrite inputs, including in --keep-work.
        reserved = {directory / name for name in ("captions.ass", "caption-probe.ass", "caption-fonts.json", "filter graph.txt", "rendered.mp4")}
        owned_dirs = [directory / "fonts"]
        if hf_plan is not None:
            owned_dirs.extend((directory / "hyperframes-overlays", directory / "hyperframes"))
        if prepared.luts:
            reserved.add(directory / "color-transforms.json")
            owned_dirs.append(directory / "luts")
        if reserved & prepared.input_paths or any(d in p.parents for p in prepared.input_paths for d in owned_dirs):
            raise pipeline.RenderError("render work directory would overwrite an input; choose a separate --keep-work directory")
        caption_overlay = None
        if hf_plan is not None:
            from .hyperframes_cache import cached_overlay
            try:
                caption_overlay = cached_overlay(hf_plan, directory, ffmpeg=ffmpeg, ffprobe=ffprobe)
            except hf.HyperframesError as exc:
                raise pipeline.RenderError(str(exc)) from exc
        clip_luts = ()
        if prepared.luts:
            try:
                clip_luts = write_luts(c, prepared.luts, prepared.lut_paths, directory)
            except OSError as exc:
                raise pipeline.RenderError(f"could not prepare composition LUTs: {exc}") from exc
        return pipeline._render_in_directory(
            validated, output, directory, ffmpeg, caption_filter,
            caption_writer=(lambda d: generate_positioned_ass(
                replace(c, captions=[event for event in c.captions if event.backend == "ass"],
                        accepted_unsafe_layouts=[event.id for event in c.captions
                            if event.backend == "ass" and event.id in c.accepted_unsafe_layouts]),
                prepared.fonts, d, ffmpeg, caption_filter)) if prepared.edl.captions else None,
            fps_rate=f"{c.fps.numerator}/{c.fps.denominator}",
            clip_luts=clip_luts,
            transitions=joins,
            caption_overlay=caption_overlay,
        )

    if work_dir is not None:
        return render(work_dir.expanduser().resolve())
    pipeline._create_directory(output.parent, f"could not create output directory {output.parent}")
    with tempfile.TemporaryDirectory(prefix=f".{output.stem}-render-", dir=output.parent) as temporary:
        result = render(Path(temporary))
    return replace(result, work_dir=None)
