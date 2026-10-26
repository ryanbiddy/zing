"""Deterministic transcript suggestions. Scores are editorial estimates, not facts.

For each complete clause start, keep the closest complete-clause ending in
0.65..1.0 times target. Require full observed-shot coverage. Reject measured dead air, >=600 ms word gaps,
quarantine and forbidden spans. Rank by 50% timed speech density, 30% length
fit, 10% opening cues, 5% keeper coverage and 5% measured shot coverage.
Opening cues are question punctuation, a numeric token and contrast wording;
each contributes one third of the cue score. Ties use source time. Greedy
non-overlap gives distinct suggestions, so fewer than top may be returned.
No model, decoder, network, or semantic-quality claim.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
import json
from pathlib import Path
import re

from myzing import storage
from myzing.schemas import Breakdown
from myzing.timing import finite, interval_problem
from .continuity import clauses, PAUSE_SECONDS
from .models import ClipStudy


def suggest_moments(clip: ClipStudy, *, target=22., top=3, forbidden=()):
    from .selection import merge, overlaps, subtract
    if not finite(target) or not 0 < target <= 60:
        raise ValueError("target must be finite seconds greater than 0 and at most 60")
    if type(top) is not int or not 1 <= top <= 100:
        raise ValueError("top must be an integer from 1 to 100")
    if clip.status != "ready":
        raise ValueError("A complete usable study is required; run zing study <clip> --raw first")
    speech = clauses(clip.words)
    starts = [w.start for w in clip.words]
    ends = [w.end for w in clip.words]
    cumulative = [0.]
    for word in clip.words:
        cumulative.append(cumulative[-1] + word.end - word.start)
    blocked = [*forbidden, *((d["start"], d["end"]) for d in clip.dead_air),
               *((q["start"], q["end"]) for q in clip.asr_repair.get("quarantined", [])),
               *((r["start"], r["end"]) for r in clip.asr_repair.get("repairs", [])),
               *((a.end, b.start) for a, b in zip(clip.words, clip.words[1:])
                 if b.start - a.end >= PAUSE_SECONDS)]
    keepers = merge([(k["start"], k["end"]) for k in clip.keepers])
    shots = merge([(s.start, s.end) for s in clip.shots])
    ranked = []
    for i, first in enumerate(speech):
        if not first.complete:
            continue
        last = None
        for j in range(i, len(speech)):
            candidate = speech[j]
            if not candidate.complete or candidate.end - first.start > target + 1e-8:
                break
            span = (first.start, candidate.end)
            if subtract([span], shots):
                break  # Same observed-shot coverage rule as selection.add.
            if any(overlaps(span, b) or (b[0] == b[1] and span[0] < b[0] < span[1]) for b in blocked):
                break
            last = candidate
        if last is None or last.end - first.start < .65 * target:
            continue
        start, end = first.start, last.end
        duration = end - start
        left, right = bisect_left(starts, start), bisect_right(ends, end)
        density = min(1., (cumulative[right] - cumulative[left]) / duration)
        reasons = [f"Complete clauses; {duration:.3f}s window for {target:g}s target",
                   f"Timed speech density {density:.1%}; no measured dead air or word gap >=0.6s inside"]
        cues = []
        if "?" in first.text:
            cues.append("question in first clause")
        if re.search(r"\b\d+(?:[.,]\d+)?\b", first.text):
            cues.append("number in first clause")
        if re.search(r"\b(?:but|actually|however|the truth)\b", first.text, re.I):
            cues.append("contrast wording in first clause")
        reasons.extend(f"Opening heuristic: {cue}" for cue in cues)
        def coverage(spans):
            return sum(max(0., min(end, b) - max(start, a)) for a, b in spans) / duration
        keeper, shot = coverage(keepers), coverage(shots)
        reasons += [f"Measured keeper coverage {keeper:.1%}" if clip.keepers else "Keeper evidence unavailable",
                    f"Measured shot coverage {shot:.1%}" if clip.shots else "Shot evidence unavailable"]
        score = .5 * density + .3 * duration / target + .1 * len(cues) / 3 + .05 * keeper + .05 * shot
        ranked.append({"start": start, "end": end, "text": " ".join(w.text for w in clip.words[left:right]),
                       "score": round(score, 6), "label": "Estimated", "reasons": reasons,
                       "must_keep": [{"clip": clip.asset_id, "start": start, "end": end}]})
    chosen = []
    for row in sorted(ranked, key=lambda r: (-r["score"], r["start"], r["end"])):
        if not any(overlaps((row["start"], row["end"]), (r["start"], r["end"])) for r in chosen):
            chosen.append(row)
            if len(chosen) == top:
                break
    return chosen


def load_clip(source: str) -> ClipStudy:
    """Load an explicit study or find one exact cached local-source match."""
    from .asr_repair import repair_words
    from .inventory import _intervals, audio_duration_notes, clip_dead_air
    from myzing.study.source_map import planning_shots
    path = Path(source).expanduser().resolve()
    explicit = path / "breakdown.json" if path.is_dir() else path
    if explicit.suffix.lower() == ".json" and explicit.is_file():
        matches = [explicit]
    else:
        matches = []
        for candidate in sorted(storage.breakdowns_root().glob("*/breakdown.json")):
            try:
                b = Breakdown.from_json(candidate.read_text(encoding="utf-8-sig"))
                media = (candidate.parent / b.meta.media_path).resolve()
                if (candidate.parent.name == source or str(path) == b.meta.source_url or path == media):
                    matches.append(candidate)
            except (OSError, ValueError, TypeError, KeyError):
                continue
    if len(matches) != 1:
        raise ValueError(f"Expected one cached study for {source!r}, found {len(matches)}. "
                         "Run zing study <clip> --raw, use --workspace, or pass its breakdown.json path.")
    study = matches[0]
    status = storage.read_status_at(study.parent)
    if status and status.get("state") != "done":
        raise ValueError("Study is incomplete or superseded; finish zing study before suggesting moments")
    b = Breakdown.from_json(study.read_text(encoding="utf-8-sig"))
    if interval_problem(0, b.meta.duration, b.meta.duration):
        raise ValueError("Study has no valid duration")
    original = Path(b.meta.source_url).expanduser()
    if not original.is_absolute():
        original = study.parent / b.meta.media_path
    selector = str(original.resolve())
    # Match's inventory stores in-project paths relative to the project root.
    # Emit its stable ID so the copied constraint resolves exactly in either
    # an in-project or external clips folder. Standalone studies keep the path.
    from myzing.project.api import load_project, resolve_path
    roots = [storage.workspace_root().resolve(), *study.parents]
    root = next((r for r in roots if (r / "project.json").is_file()), None)
    asset_id = selector
    if root is not None:
        manifest = load_project(root)
        assets = [a for a in manifest.assets if any(
            resolve_path(p, root) == original.resolve()
            for p in [a.path, a.original_path, *a.previous_paths])]
        if len(assets) != 1:
            raise ValueError("Study source does not resolve to one project video; run zing project scan or use the matching --workspace.")
        asset_id = assets[0].id
    words, repair = repair_words(b.words, b.meta.duration)
    raw = b.provenance.get("raw_mode", {})
    clip = ClipStudy(asset_id, selector, b.provenance.get("source_sha256", ""), b.meta.duration, "ready",
                     study_path=str(study), words=words, shots=planning_shots(b),
                     keepers=_intervals(raw.get("keepers", []), b.meta.duration, "keepers"),
                     dead_air=_intervals(raw.get("dead_air", []), b.meta.duration, "dead air"),
                     asr_repair=repair, warnings=list(b.warnings))
    if repair["repairs"] or repair["quarantined"]:
        clip.warnings.append("Repaired or quarantined word timings are excluded from moment suggestions; only measured timings are ranked.")
    audio_path = study.parent / "audio-map.json"
    if audio_path.is_file():
        from myzing.audio.models import AudioMap
        audio = AudioMap.from_dict(json.loads(audio_path.read_text(encoding="utf-8-sig")))
        if audio.truncated:
            raise ValueError("Audio map is truncated; complete its analysis before suggesting moments")
        audio_source = (study.parent / audio.source).resolve()
        if audio_source not in {original.resolve(), (study.parent / b.meta.media_path).resolve()}:
            raise ValueError("audio-map source does not match this study")
        clip.warnings.extend(audio_duration_notes(audio.duration_seconds, clip.duration))
        clip.dead_air = clip_dead_air(clip.dead_air, min(audio.duration_seconds, clip.duration))
        clip.dead_air.extend({"start": s.start, "end": min(s.end, clip.duration)} for s in audio.segments
                             if s.label == "silence" and s.start < clip.duration)
    return clip


def moments(source: str, *, target=22., top=3):
    clip = load_clip(source)
    return {"version": 1, "source": clip.path, "study_path": clip.study_path,
            "target": target, "suggestions": suggest_moments(clip, target=target, top=top),
            "warnings": clip.warnings,
            "basis": "Estimated editorial ranking from measured transcript timings and shot coverage, with optional keeper evidence; semantic quality and ASR accuracy unverified."}


def run(argv):
    parser = argparse.ArgumentParser(prog="zing moments", description="Suggest interview moments from a cached study; no model calls.")
    parser.add_argument("source", metavar="clip-or-study")
    parser.add_argument("--target", type=float, default=22.)
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        with storage.use_workspace(args.workspace or storage.workspace_root()):
            result = {"ok": True, **moments(args.source, target=args.target, top=args.top)}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        result = {"ok": False, "error": str(exc)}
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    elif result["ok"]:
        for row in result["suggestions"]:
            print(f"Estimated {row['start']:.3f}-{row['end']:.3f}s ({row['score']:.3f}): {row['text']}")
            print(json.dumps({"must_keep": row["must_keep"]}))
        if not result["suggestions"]:
            print("No complete windows near the target length; review the transcript or change --target.")
    else:
        print(result["error"])
    return 0 if result["ok"] else 1
