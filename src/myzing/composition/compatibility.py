"""Explicit, non-rendering migration between the two EDL contracts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import fields
from fractions import Fraction
from hashlib import sha256
from typing import Any

from myzing.audio.models import AudioMap, Segment
from myzing.contracts import typed
from myzing.project.models import ProjectManifest, Rational
from myzing.schemas import EDL, AudioTrack, CaptionSpec, Clip
from .models import AssetRef, Composition, CompositionAudio, CompositionCaption, CompositionClip
from .timebase import rate_fraction


def _legacy(item, cls) -> dict:
    return {f.name: deepcopy(getattr(item, f.name)) for f in fields(cls)}


def _ordered_timing(value: Any, path: str, order: dict[str, list[str]], *, capture: bool = False):
    if isinstance(value, dict):
        if capture:
            order[path] = list(value)
        keys = [k for k in order.get(path, []) if k in value]
        keys += [k for k in value if k not in keys]
        return {k: _ordered_timing(value[k], path + "/" + k.replace("~", "~0").replace("/", "~1"),
                                   order, capture=capture) for k in keys}
    if isinstance(value, list):
        return [_ordered_timing(v, path + f"/{i}", order, capture=capture) for i, v in enumerate(value)]
    return value


def upgrade_edl(edl: EDL, *, manifest: ProjectManifest | None = None) -> Composition:
    """Pure upgrade: preserve seconds, number spelling and Word.timing.

    Exact manifest IDs/paths/aliases are matched without basename guesses or IO.
    Without inventory evidence the SHA is null, never a digest of the path.
    """
    if type(edl.schema_version) is not int or edl.schema_version != 1:
        raise ValueError("upgrade_edl expects EDL schema_version 1")
    typed(edl.fps, float, "fps")
    if edl.fps <= 0:
        raise ValueError("fps must be positive")
    rate = Fraction(str(edl.fps))
    timing_order = {}
    for i, caption in enumerate(edl.captions):
        for j, word in enumerate(caption.words):
            _ordered_timing(word.timing, f"/{i}/{j}", timing_order, capture=True)
    assets: dict[str, AssetRef] = {}
    by_source: dict[str, AssetRef] = {}
    for source in dict.fromkeys(item.src for item in [*edl.clips, *edl.audio]):
        matches = [a for a in manifest.assets
                   if source in [a.id, a.path, a.original_path, *a.previous_paths]] if manifest else []
        if len(matches) > 1:
            raise ValueError(f"ambiguous inventory source {source!r}; use a stable asset ID")
        if matches:
            item = matches[0]
            asset = assets.setdefault(item.id, AssetRef(
                item.id, item.path, item.sha256,
                item.probe.duration if item.probe else None,
            ))
            if source != asset.path and source not in asset.aliases:
                asset.aliases.append(source)
        else:
            identity = "legacy-" + sha256(source.encode("utf-8")).hexdigest()
            asset = assets.setdefault(identity, AssetRef(identity, source, None))
        by_source[source] = asset
    return Composition(
        assets=list(assets.values()),
        clips=[CompositionClip(**_legacy(c, Clip), id=f"clip-{i + 1}", asset_id=by_source[c.src].id)
               for i, c in enumerate(edl.clips)],
        captions=[CompositionCaption(**_legacy(c, CaptionSpec), id=f"caption-{i + 1}")
                  for i, c in enumerate(edl.captions)],
        audio=[CompositionAudio(**_legacy(a, AudioTrack), id=f"audio-{i + 1}",
                                asset_id=by_source[a.src].id, role=a.kind)
               for i, a in enumerate(edl.audio)],
        width=edl.width, height=edl.height, fps=Rational(rate.numerator, rate.denominator),
        legacy_fps=edl.fps, legacy_timing_order=timing_order,
    )


def lowering_blockers(composition: Composition) -> list[str]:
    """Every discarded v2 instruction/evidence is named, in stable order."""
    composition.to_dict()  # Revalidate mutable nested records before conversion.
    problems = []
    if composition.delivery is not None:
        problems.append("delivery encoding")
    if composition.speech_words:
        problems.append("speech_words")
    rate = rate_fraction(composition.fps)
    if composition.legacy_fps is not None:
        if Fraction(str(composition.legacy_fps)) != rate:
            problems.append("fps differs from legacy_fps")
    elif Fraction(str(float(rate))) != rate:
        problems.append("rational fps cannot be represented exactly by v1")
    for index, clip in enumerate(composition.clips):
        if clip.speed_map:
            problems.append(f"clips[{index}].speed_map")
        if clip.color is not None:
            problems.append(f"clips[{index}].color")
        if clip.framing is not None:
            problems.append(f"clips[{index}].framing")
    if composition.transitions:
        problems.append("transitions")
    if composition.graphics:
        problems.append("graphics")
    for index, caption in enumerate(composition.captions):
        if caption.alignment != "center":
            problems.append(f"captions[{index}].alignment={caption.alignment}")
        for field in ("layout", "font", "style", "template", "preset"):
            if getattr(caption, field) is not None:
                problems.append(f"captions[{index}].{field}")
        if caption.backend != "ass":
            problems.append(f"captions[{index}].backend={caption.backend}")
    for index, audio in enumerate(composition.audio):
        if audio.role != audio.kind or audio.kind not in {"music", "voiceover"}:
            problems.append(f"audio[{index}].role={audio.role}")
        if audio.role_evidence is not None:
            problems.append(f"audio[{index}].role_evidence")
        if audio.src_in != 0 or audio.src_out is not None:
            problems.append(f"audio[{index}].source_trim")
        if audio.duck_scope != "voiceover":
            problems.append(f"audio[{index}].duck_scope={audio.duck_scope}")
    if composition.loudness_target is not None:
        problems.append("loudness_target")
    if composition.warnings:
        problems.append("warnings")
    if composition.accepted_unsafe_layouts:
        problems.append("accepted_unsafe_layouts")
    if composition.brief is not None:
        problems.append("brief")
    return problems


def lower_to_v1(composition: Composition) -> EDL:
    problems = lowering_blockers(composition)
    if problems:
        raise ValueError("Cannot lower Composition v2 to EDL v1; blocking features: " + "; ".join(problems))
    fps = (composition.legacy_fps if composition.legacy_fps is not None
           else float(rate_fraction(composition.fps)))
    result = EDL(
        clips=[Clip(**_legacy(c, Clip)) for c in composition.clips],
        captions=[CaptionSpec(**_legacy(c, CaptionSpec)) for c in composition.captions],
        audio=[AudioTrack(**_legacy(a, AudioTrack)) for a in composition.audio],
        width=composition.width, height=composition.height, fps=fps,
    )
    for i, caption in enumerate(result.captions):
        for j, word in enumerate(caption.words):
            word.timing = _ordered_timing(word.timing, f"/{i}/{j}", composition.legacy_timing_order)
    return result


def audio_from_map(audio_map: AudioMap, segment_index: int, *, id: str, asset: AssetRef,
                   timeline_start: float = 0, gain_db: float = 0,
                   duck_under_speech: bool = False) -> CompositionAudio:
    """Place a selected measured segment; uncertain/silence remain those roles.

    There is no onset-to-SFX or speech-to-voiceover inference.
    """
    if audio_map.source not in [asset.path, *asset.aliases]:
        raise ValueError("AudioMap source must match the asset path or alias")
    if type(segment_index) is not int or not 0 <= segment_index < len(audio_map.segments):
        raise ValueError("AudioMap segment_index is outside the segments array")
    segment = Segment.from_dict(audio_map.segments[segment_index].to_dict())
    return CompositionAudio(
        src=asset.path, kind=segment.label, id=id, asset_id=asset.id, role=segment.label,
        timeline_start=timeline_start, gain_db=gain_db, duck_under_speech=duck_under_speech,
        src_in=segment.start, src_out=segment.end, role_evidence=segment,
    )


def load_composition(data: dict, *, manifest: ProjectManifest | None = None) -> Composition:
    """Read v2, or explicitly upgrade a v1 input without performing media IO."""
    version = data.get("schema_version", 1) if isinstance(data, dict) else None
    if type(version) is int and version == 1:
        return upgrade_edl(EDL.from_dict(data), manifest=manifest)
    if type(version) is int and version == 2:
        return Composition.from_dict(data)
    raise ValueError(f"unsupported EDL schema_version {version!r}; expected 1 or 2")
