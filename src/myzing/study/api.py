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

    Transition detection is disabled by default because the v2 detector is
    calibrated only on synthetic precision fixtures. When enabled, a probe
    failure produces no observations, a named warning, and detector
    provenance instead of aborting the rest of the study.

    Workspace threading (F-15, closed): ``workspace`` is pinned via
    storage's ContextVar ``use_workspace`` — thread-safe under concurrent
    MCP jobs, no process-global state. The env-var mutation survives only
    as a fallback for a storage build without it.
    """
    with _workspace_override(workspace):
        _phase(phase_callback, "ingest")
        ing = ingest_mod.ingest(source)
        warnings: list[str] = list(ing.warnings)
        provenance: dict[str, Any] = {}

        _phase(phase_callback, "shots")
        shots_r = shots_mod.detect_shots(
            ing.media_path, ing.meta.duration, ing.meta.fps
        )
        warnings += shots_r.warnings
        provenance.update(shots_r.provenance)

        _phase(phase_callback, "keyframes")
        keyframes_mod.extract_keyframes(
            ing.media_path, ing.breakdown_dir, shots_r.shots,
            ing.meta.duration, warnings,
        )

        _phase(phase_callback, "transcribe")
        words_r = transcribe_mod.transcribe(
            ing.media_path, duration=ing.meta.duration
        )
        warnings += words_r.warnings
        provenance.update(words_r.provenance)

        _phase(phase_callback, "ocr")
        caps_r = captions_mod.read_captions(ing.media_path, ing.meta.duration)
        warnings += caps_r.warnings
        provenance.update(caps_r.provenance)

        _phase(phase_callback, "audio")
        audio_r = audio_mod.measure_audio(ing.media_path, ing.meta.duration)
        warnings += audio_r.warnings
        provenance.update(audio_r.provenance)

        transitions = []
        if detect_transitions:
            _phase(phase_callback, "transitions")
            try:
                transitions_r = transitions_mod.detect_transitions(
                    ing.media_path
                )
            except transitions_mod.TransitionProbeError as exc:
                warnings.append(f"transition detection skipped: {exc}")
                provenance.update(transitions_mod.detector_provenance())
            else:
                transitions = transitions_r.transitions
                warnings += transitions_r.warnings
                provenance.update(transitions_r.provenance)

        if raw_mode:
            _phase(phase_callback, "raw")
            raw_r = raw_mod.measure_raw(
                words_r.words, audio_r.speech_segments, ing.meta.duration
            )
            warnings += raw_r.warnings
            provenance["raw_mode"] = {
                "dead_air_min_s": raw_mod.DEAD_AIR_MIN_S,
                "take_similarity": raw_mod.TAKE_SIMILARITY,
                "dead_air_count": len(raw_r.dead_air),
                "filler_total": sum(raw_r.filler_counts.values()),
                "repeated_take_count": len(raw_r.repeated_takes),
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
