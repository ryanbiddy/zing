"""The study engine's programmatic seam (binding, critique A#4):

    study(
        source: str,
        workspace: Path | None = None,
        detect_transitions: bool = False,
    ) -> Breakdown

Lane B's MCP `study_video` and Lane C's eval harness call this function;
the CLI is a thin wrapper. It orchestrates ingest -> shots -> keyframes ->
transcription -> caption OCR -> audio, assembles the Breakdown with merged
warnings + provenance, renders breakdown.md, and persists both via
storage. Every skipped or degraded measurement arrives in
``Breakdown.warnings`` — an empty list downstream is never ambiguous.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from myzing import storage
from myzing.schemas import Breakdown

from . import audio as audio_mod
from . import captions as captions_mod
from . import ingest as ingest_mod
from . import raw as raw_mod
from . import keyframes as keyframes_mod
from . import report
from . import shots as shots_mod
from . import transcribe as transcribe_mod
from . import transitions as transitions_mod


def study(
    source: str,
    workspace: Path | None = None,
    phase_callback: Callable[[str], None] | None = None,
    detect_transitions: bool = False,
    raw_mode: bool = False,
    kept_media: Path | str | None = None,
    handoff: dict[str, Any] | None = None,
    caption_geometry: bool = False,
    fonts: bool = False,
    local_models_only: bool = False,
    model_workspace: Path | None = None,
    speech_model: str | None = None,
    shot_min_scene_len_s: float | None = None,
    vocabulary=(),
    brief=None,
    reference_metadata: dict | None = None,
    ref_start=None, ref_end=None, reference_range=None,
    analysis_seconds=None, analysis_max_side=None,
) -> Breakdown:
    """Measure one video (URL or local path) into a persisted Breakdown.

    Raises MediaError/ToolMissing when the video itself cannot be obtained
    or probed — there is no honest Breakdown without media. Every other
    stage degrades to warnings instead of raising.

    ``phase_callback`` (A-Q5), when given, is called with the phase name as
    each stage begins: ingest, shots, keyframes, transcribe, ocr, audio,
    optional transitions, markdown. Callback errors are swallowed —
    status reporting must never
    kill a measurement.

    Transition detection is disabled by default because the v4 detector has
    synthetic precision and recall checks but no measurable real-video
    recall. Successful opt-in runs name that experimental status. A probe
    failure produces no observations, a named warning, and detector
    provenance instead of aborting the rest of the study.

    Workspace threading (F-15, closed): ``workspace`` is pinned via
    storage's ContextVar ``use_workspace`` — thread-safe under concurrent
    MCP jobs, no process-global state. The env-var mutation survives only
    as a fallback for a storage build without it.
    """
    if fonts and not caption_geometry:
        raise ValueError("font candidates require caption_geometry=True (CLI: --caption-geometry --fonts)")
    with _workspace_override(workspace):
        _phase(phase_callback, "ingest")
        ing = ingest_mod.ingest(
            source, kept_media=kept_media, handoff=handoff,
            **{k: v for k, v in dict(ref_start=ref_start, ref_end=ref_end, reference_range=reference_range,
                                     analysis_seconds=analysis_seconds, analysis_max_side=analysis_max_side).items() if v is not None}
        )
        warnings: list[str] = list(ing.warnings)
        # A-S6: ingest provenance (kept-media evidence) merges first so
        # stage provenance never masks how the media was obtained.
        provenance: dict[str, Any] = dict(ing.provenance)

        _phase(phase_callback, "shots")
        shots_r = shots_mod.detect_shots(
            ing.media_path, ing.meta.duration, ing.meta.fps,
            **({"min_scene_len_s": shot_min_scene_len_s} if shot_min_scene_len_s is not None else {}),
        )
        warnings += shots_r.warnings
        provenance.update(shots_r.provenance)

        # Keep public shots/pacing/keyframes stable. Planning consumes a separate
        # versioned map; verification still measures the rendered pixels itself.
        if shots_r.shots and ing.meta.fps > 0:
            from .source_map import build_source_map
            source_map = build_source_map(ing.media_path, ing.meta.duration, ing.meta.fps, shots_r.shots)
            provenance["source_map"] = source_map.to_dict()
            warnings += source_map.warnings

        _phase(phase_callback, "keyframes")
        keyframes_mod.extract_keyframes(
            ing.media_path, ing.breakdown_dir, shots_r.shots,
            ing.meta.duration, warnings,
        )

        from .asr_hygiene import vocabulary_context
        if brief is None:
            brief_file = storage.workspace_root() / "brief.json"
            if brief_file.is_file():
                from myzing.brief.api import load_brief
                brief = load_brief(brief_file)
        metadata = reference_metadata or {}
        if not metadata and handoff and isinstance(handoff.get("metadata"), dict):
            metadata = handoff["metadata"]
        context = vocabulary_context(vocabulary, brief=brief, metadata=metadata)
        _phase(phase_callback, "transcribe")
        with _workspace_override(model_workspace):
            words_r = transcribe_mod.transcribe(
                ing.media_path, duration=ing.meta.duration,
                **({"model_name": speech_model} if speech_model is not None else {}),
                **({"local_files_only": True} if local_models_only else {}),
                **({"vocabulary": context["terms"]} if context["terms"] else {}),
            )
        warnings += words_r.warnings
        provenance.update(words_r.provenance)
        provenance["asr_vocabulary"] = context

        _phase(phase_callback, "ocr")
        if caption_geometry:
            from .caption_geometry import read_geometry, caption_events

            _phase(phase_callback, "caption_geometry")
            # A project may keep measurements in separate reference/output
            # workspaces while sharing explicitly provisioned local model assets.
            with _workspace_override(model_workspace):
                geometry = read_geometry(ing.media_path, ing.meta.duration)
                if fonts:
                    from .font_match import match_geometry, failed_candidates, budget_geometry
                    _phase(phase_callback, "font_candidates")
                    try:
                        font_geometry, budget = budget_geometry(geometry)
                        candidates = match_geometry(ing.media_path, font_geometry)
                        if budget["observations_omitted"]:
                            candidates.provenance["work_budget"] = budget
                            candidates.warnings.append(f"Font comparison sampled {budget['observations_measured']} of {budget['observations_total']} line observations across {budget['tracks_measured']} tracks; remaining fonts are unmeasured.")
                    except Exception as exc:
                        # Optional font matching must never prevent saving the study,
                        # including OpenCV errors and unexpected backend failures.
                        candidates = failed_candidates(ing.media_path, geometry, exc)
                    geometry.font_candidates = candidates.to_dict()
                    geometry.warnings.extend(candidates.warnings)
            caps_r = captions_mod.CaptionsResult(
                captions=caption_events(geometry), warnings=geometry.warnings,
            )
            try:
                geometry.write(ing.breakdown_dir)
            except OSError as exc:
                warnings.append(f"caption geometry sidecar could not be saved: {exc}; check workspace permissions")
            else:
                provenance["caption_geometry"] = geometry.summary()
        else:
            caps_r = captions_mod.read_captions(
                ing.media_path, ing.meta.duration,
                **({"local_models_only": True} if local_models_only else {}),
            )
        warnings += caps_r.warnings
        provenance.update(caps_r.provenance)

        _phase(phase_callback, "audio")
        audio_r = audio_mod.measure_audio(ing.media_path, ing.meta.duration)
        warnings += audio_r.warnings
        provenance.update(audio_r.provenance)

        from myzing.audio.tagging import AudioTags
        tags = AudioTags()
        with _workspace_override(model_workspace):
            from myzing.audio.tag_models import model_paths
            try:
                model_paths()
            except (RuntimeError, OSError) as exc:
                tags.warnings.append(f"Learned audio tagging unavailable; heuristic fallback: {exc}")
            else:
                # 16 kHz decode inside; at most 600 s, the analysis cap.
                from myzing.audio.tagging import tag_file
                tags = tag_file(ing.media_path, speech=[(w.start, w.end) for w in words_r.words])
        provenance["audio_tags"] = tags.to_dict()
        warnings.extend(tags.warnings)

        transitions = []
        if detect_transitions:
            _phase(phase_callback, "transitions")
            try:
                transitions_r = transitions_mod.detect_transitions(
                    ing.media_path
                )
            except transitions_mod.TransitionProbeError as exc:
                warnings.append(
                    f"transition detection skipped: {exc} - transitions[] "
                    "is NOT-MEASURED, not measured-empty; the detector is "
                    "recorded in provenance"
                )
                provenance.update(transitions_mod.detector_provenance())
            else:
                transitions = transitions_r.transitions
                warnings += transitions_r.warnings
                provenance.update(transitions_r.provenance)

        if raw_mode:
            _phase(phase_callback, "raw")
            raw_r = raw_mod.measure_raw(
                words_r.words,
                audio_r.speech_segments,
                ing.meta.duration,
                loudness_curve=audio_r.audio.loudness_curve,
            )
            warnings += raw_r.warnings
            provenance["raw_mode"] = {
                "dead_air_min_s": raw_mod.DEAD_AIR_MIN_S,
                "take_similarity": raw_mod.TAKE_SIMILARITY,
                "dead_air_count": len(raw_r.dead_air),
                "filler_total": sum(raw_r.filler_counts.values()),
                "repeated_take_count": len(raw_r.repeated_takes),
                "keeper_count": len(raw_r.keepers),
                "keepers": [
                    {
                        "start": k.start,
                        "end": k.end,
                        "words": k.word_count,
                        "evidence": k.evidence,
                    }
                    for k in raw_r.keepers
                ],
            }

        provenance["zing_version"] = _zing_version()
        provenance["measured_at"] = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )

        _phase(phase_callback, "markdown")
        breakdown = Breakdown(
            meta=ing.meta,
            shots=shots_r.shots,
            words=words_r.words,
            captions=caps_r.captions,
            audio=audio_r.audio,
            avg_shot_duration=shots_mod.avg_shot_duration(shots_r.shots),
            cuts_per_10s=shots_mod.cuts_per_10s(
                shots_r.shots, ing.meta.duration
            ),
            transitions=transitions,
            warnings=warnings,
            provenance=provenance,
        )
        storage.save_breakdown(
            breakdown,
            slug=ing.slug,
            markdown=report.render_markdown(breakdown),
        )
        return breakdown


def _phase(callback: Callable[[str], None] | None, name: str) -> None:
    if callback is None:
        return
    try:
        callback(name)
    except Exception:
        pass  # status reporting must never kill a measurement


def _zing_version() -> str:
    try:
        from importlib.metadata import version

        return version("myzing")
    except Exception:
        return "unknown"


@contextmanager
def _workspace_override(workspace: Path | None):
    """Point storage at a caller-chosen workspace for the duration of one
    study.

    F-15 closed: storage's ``use_workspace`` (ContextVar-based) pins the
    workspace for this thread/context only — safe under concurrent MCP
    jobs, no process-global state. The env-var mutation below survives
    solely as a fallback for a storage build without ``use_workspace``.
    """
    if workspace is None:
        yield
        return
    if hasattr(storage, "use_workspace"):
        with storage.use_workspace(workspace):
            yield
        return
    prior = os.environ.get(storage.ENV_VAR)
    os.environ[storage.ENV_VAR] = str(workspace)
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop(storage.ENV_VAR, None)
        else:
            os.environ[storage.ENV_VAR] = prior
