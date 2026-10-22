"""Join every project clip to local study evidence, never by basename."""

from __future__ import annotations

import json
from pathlib import Path

from myzing import storage
from myzing.audio.models import AudioMap
from myzing.contracts import json_value
from myzing.project.api import hash_file, load_project, project_status, resolve_path
from myzing.schemas import Breakdown
from myzing.timing import interval_problem

from .models import ClipStudy
from .asr_repair import repair_words


def _intervals(items, duration, label):
    if not isinstance(items, list):
        raise ValueError(f"{label} must be an array")
    for item in items:
        problem = interval_problem(item["start"], item["end"], duration)
        if problem:
            raise ValueError(f"{label}: {problem}")
    return items


def _study_files(project: Path):
    roots = {project / "breakdowns", storage.resolve_workspace() / "breakdowns"}
    return sorted({p.resolve() for root in roots for p in root.glob("*/breakdown.json")}, key=str)


def inventory(project: str | Path, *, repair_asr: bool = True) -> tuple[list[ClipStudy], list[str]]:
    """No model, decoder, or network. Studies may live in the project or ZING_HOME.

    Path matches use the study's original source URL/path, or its resolved media
    path. A recorded source_sha256 can also match renamed footage. Staged media
    checksums are not confused with original-source checksums after normalization.
    """
    root = Path(project).expanduser().resolve()
    manifest = load_project(root)
    live = {a["id"]: a for a in project_status(root)["assets"]}
    studies, notes = [], []
    for path in _study_files(root):
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            # Malformed word times belong to the derived repair boundary;
            # all other study fields remain strict JSON values.
            json_value({**data, "words": []})
            b = Breakdown.from_dict(data)
            if type(b.schema_version) is not int or b.schema_version != 1:
                raise ValueError("study schema_version must be 1")
            if not isinstance(b.meta.source_url, str) or not isinstance(b.meta.media_path, str):
                raise ValueError("study source and media path must be strings")
            if not isinstance(b.provenance, dict):
                raise ValueError("study provenance must be an object")
            status = storage.read_status_at(path.parent)
            studies.append((path, b, status))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            notes.append(f"Unreadable study {path}: {exc}; run zing study again.")
    result = []
    for asset in sorted(manifest.assets, key=lambda a: a.id):
        if not asset.probe or not any(s.get("codec_type") == "video" and not
                                     s.get("disposition", {}).get("attached_pic")
                                     for s in asset.probe.streams):
            continue
        source = resolve_path(asset.path, root)
        item = ClipStudy(asset.id, str(source), asset.sha256,
                         asset.probe.duration or 0, "needs_study")
        result.append(item)
        row = live[asset.id]
        if asset.state != "ready" or row["state"] in {"missing", "unsupported"} or row["needs_scan"]:
            item.status = "needs_scan"
            item.warnings.append(f"{asset.id}: missing, changed, or unsupported media; run zing project scan.")
            continue
        if hash_file(source) != asset.sha256:
            item.status = "needs_scan"
            item.warnings.append(f"{asset.id}: content differs from inventory; run zing project scan.")
            continue
        paths = {str(resolve_path(p, root)) for p in
                 [asset.path, asset.original_path, *asset.previous_paths]}
        exact, by_hash = [], []
        for path, b, status in studies:
            measured_path = Path(b.meta.media_path)
            if not measured_path.is_absolute():
                measured_path = path.parent / measured_path
            source_hash = b.provenance.get("source_sha256")
            if b.meta.source_url in paths or str(measured_path.resolve()) in paths:
                exact.append((path, b, status))
            elif source_hash == asset.sha256:
                by_hash.append((path, b, status))
        matches = exact or by_hash
        if len(matches) != 1:
            why = "no matching study" if not matches else "multiple matching studies; keep one authoritative study"
            item.warnings.append(f'{asset.id}: {why}. Run zing study "{source}" --raw --workspace "{root}".')
            continue
        path, b, status = matches[0]
        item.study_path = str(path)
        try:
            if status and status.get("state") != "done":
                raise ValueError(f"study state is {status.get('state')!r}; do not use a superseded snapshot")
            if b.provenance.get("source_sha256", asset.sha256) != asset.sha256:
                raise ValueError("study's source checksum is stale")
            if interval_problem(0, b.meta.duration, b.meta.duration):
                raise ValueError("study has no valid duration")
            if abs(b.meta.duration - item.duration) > .05:
                raise ValueError("study duration differs from project probe; rescan and restudy")
            item.duration = min(item.duration, b.meta.duration)
            item.words, item.asr_repair = repair_words(b.words, item.duration, enabled=repair_asr)
            if item.asr_repair["repairs"]:
                item.warnings.append(f"ASR repair {source.name}: {len(item.asr_repair['repairs'])} word timings "
                                     "interpolated within 2s windows; originals and per-word repairs retained in inventory.asr_repair.")
            if item.asr_repair["quarantined"]:
                item.warnings.append(f"ASR quarantine {source.name}: {len(item.asr_repair['quarantined'])} spans "
                                     "excluded; other measured spans remain available. See inventory.asr_repair.")
            if asset.probe.has_audio and not item.words and not item.asr_repair["quarantined"] and not (
                b.provenance.get("vad") and b.audio.speech_ratio == 0
            ):
                raise ValueError("audio has no validated words or measured absence of speech")
            if not b.shots:
                raise ValueError("no measured shots")
            previous = 0.0
            for shot in b.shots:
                problem = interval_problem(shot.start, shot.end, item.duration)
                if problem or shot.start < previous:
                    raise ValueError(f"invalid shot intervals: {problem or 'overlap/order'}")
                previous = shot.end
            item.shots = b.shots
            raw = b.provenance.get("raw_mode", {})
            if not isinstance(raw, dict):
                raise ValueError("raw_mode must be an object")
            item.keepers = _intervals(raw.get("keepers", []), item.duration, "raw keepers")
            item.dead_air = _intervals(raw.get("dead_air", []), item.duration, "dead air")
            if "keepers" not in raw:
                item.warnings.append("No raw keeper evidence; selection uses measured shots and words.")
            if raw.get("dead_air_count") and not item.dead_air:
                item.warnings.append("Study reports a dead-air count without intervals; no silence spans inferred.")
            # Optional user-saved map beside a study, in that source's coordinates.
            audio_path = path.parent / "audio-map.json"
            if audio_path.is_file():
                audio = AudioMap.from_dict(json.loads(audio_path.read_text(encoding="utf-8-sig")))
                audio_source = Path(audio.source)
                if not audio_source.is_absolute():
                    audio_source = audio_path.parent / audio_source
                if (str(audio_source.resolve()) not in paths | {str((path.parent / b.meta.media_path).resolve())}
                        or abs(audio.duration_seconds - item.duration) > .05 or audio.truncated):
                    raise ValueError("audio-map source/duration does not match this complete study")
                silence = []
                for segment in audio.segments:
                    if segment.label != "silence" or segment.start >= item.duration:
                        continue
                    row = segment.to_dict()
                    if segment.end > item.duration:
                        # AudioMap duration was checked within 50 ms above.
                        # AAC's decoded tail may exceed the video clock; keep
                        # that raw evidence and clip only the derived silence.
                        row.update(end=item.duration, original={"start": segment.start, "end": segment.end},
                                   method="clip_audio_tail_to_video")
                        item.warnings.append("Audio-map silence clipped to the video duration; decoded audio tail and original interval retained in provenance.")
                    silence.append(row)
                item.dead_air += _intervals(silence, item.duration, "audio-map silence")
            if "source_sha256" not in b.provenance:
                item.warnings.append("Study matched by exact source path and duration; historical source checksum unreported.")
            item.warnings.extend(b.warnings)
            item.status = "ready"
        except (ValueError, TypeError, KeyError, OSError) as exc:
            item.words, item.shots, item.keepers, item.dead_air = [], [], [], []
            item.warnings.append(f'{asset.id}: {exc}. Review timestamps or run zing study "{source}" --raw.')
    return result, notes
