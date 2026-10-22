"""Compile selected source spans to Composition v2 and report planned matches."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from statistics import median

from myzing.composition import (
    AssetRef, Composition, CompositionAudio, CompositionCaption, CompositionClip,
    lower_to_v1, lowering_blockers,
)
from myzing.layout.chooser import check_overlap
from myzing.layout.types import EventLayout, Keyframe
from myzing.project.api import hash_file, resolve_path
from myzing.project.models import Rational
from myzing.timing import prepare_words, transform_word

from .models import shortage
from .selection import EPS, first_caption, shot_lengths, tokens

REPORT_PREFIX = "P17 planning evidence: "
STRATEGIES = {
    "A": "Speech-led: rank clean keeper support and complete-word density for the opening.",
    "B": "Visual-led: rank observed shot keyframes and lower speech density for the opening.",
    "C": "Concise: prefer the shortest feasible edit within the target tolerance, retaining every must-keep.",
}


def metric(target, actual, tolerance, reason):
    if target is None:
        status = "unmeasured"
    elif actual is None or abs(actual - target) > tolerance + EPS:
        status = "deviation"
    else:
        status = "honored"
    return {"target": target, "planned": actual, "tolerance": tolerance,
            "status": status, "reason": reason if status != "honored" else "Within the stated planning tolerance."}


def font_choice(recipe, recipe_dir):
    candidates = recipe.approximations.font_candidates
    if not candidates:
        return None, {"family": "Arial", "status": "disclosed default",
                      "reason": "No font substitution candidate supplied; v1 renderer uses Arial bold with system fallback."}
    # Candidate order is the producer's ranking. A family name alone is not a
    # reproducible FontAsset and must not silently become a different font.
    choice = candidates[0]
    if choice.asset is None:
        shortage("font_asset", f"Font candidate {choice.family!r} has no pinned local asset.",
                 "Attach a licensed FontAsset path/SHA-256 to the candidate, or remove it to accept the disclosed default.")
    font = deepcopy(choice.asset)
    font.path = str(resolve_path(font.path, recipe_dir))
    if not Path(font.path).is_file() or hash_file(Path(font.path)) != font.sha256:
        shortage("font_asset", f"Font candidate {choice.family!r} is missing or has a different checksum.",
                 "Restore the licensed font file recorded in the recipe.")
    return font, {"family": choice.family, "status": "substitution", "asset": font.to_dict(),
                  "reason": choice.substitution_evidence, "original_font": "unknown"}


def _layout(caption, template, masks):
    # Reference geometry is reusable; its reference-face safety result is not.
    scale = (caption.end - caption.start) / (template.end - template.start)
    path = [Keyframe(caption.start + (k.time - template.start) * scale, k.box)
            for k in template.path]
    if path:
        path[0] = replace(path[0], time=caption.start)
        path[-1] = replace(path[-1], time=caption.end)
    probe_path = path or [Keyframe(caption.start, template.box), Keyframe(caption.end, template.box)]
    overlap = check_overlap(probe_path, [], masks)
    overlap = replace(overlap, scope="supplied platform masks only; output faces unmeasured")
    warnings = [*template.warnings, "Reference layout geometry retimed; output face safety needs a new layout check."]
    if not overlap.safe:
        warnings.append("Requested geometry overlaps a supplied platform mask.")
    return EventLayout(caption.id, caption.start, caption.end, "recipe-layout-geometry", overlap,
                       box=template.box, path=path, warnings=warnings,
                       fallback=template.fallback, scale=template.scale)


def captions_for(sequence, studies, style, recipe, font, brief):
    lookup = {s.asset_id: s for s in studies}
    groups, cursor = [], 0.0
    for c in sequence:
        window = []
        for word in lookup[c.asset_id].words:
            if not (word.start >= c.start - EPS and word.end <= c.end + EPS):
                continue
            if window and (sum(len(w.text.split()) for w in window) >= style.words_visible
                           or word.start - window[-1].end > .6):
                groups.append((window, cursor - c.start))
                window = []
            window.append(word)
        if window:
            groups.append((window, cursor - c.start))
        cursor += c.duration
    result = []
    caps_count = round(style.all_caps_rate * len(groups))
    layout = recipe.approximations.layout
    for i, (words, offset) in enumerate(groups):
        all_caps = (round((i + 1) * caps_count / len(groups)) > round(i * caps_count / len(groups)))
        mapped = [transform_word(w, w.start + offset, w.end + offset, "timeline_mapping", corrected=False,
                                 offset=offset) for w in words]
        if not all_caps and " ".join(w.text for w in mapped).isupper():
            mapped = [replace(w, text=w.text.lower()) for w in mapped]
        # Only repair spelling case when the exact tokens already agree.
        # Approximate ASR names need human review, never a guessed replacement.
        for spelling in brief.exact_spellings:
            parts = spelling.split()
            for start in range(len(mapped) - len(parts) + 1):
                if tokens(" ".join(w.text for w in mapped[start:start + len(parts)])) == tokens(spelling):
                    for j, part in enumerate(parts):
                        mapped[start + j] = replace(mapped[start + j], text=part)
        if all_caps:
            mapped = [replace(w, text=w.text.upper()) for w in mapped]
        caption = CompositionCaption(
            id=f"caption-{i + 1}", text=" ".join(w.text.strip() for w in mapped),
            start=mapped[0].start, end=mapped[-1].end, words=mapped,
            position=style.position, all_caps=all_caps, word_timed=style.words_visible == 1,
            font=deepcopy(font),
        )
        if layout and layout.events:
            caption.layout = _layout(caption, layout.events[i % len(layout.events)], layout.masks)
        result.append(caption)
    prepare_words([w for c in result for w in c.words], cursor, repair=False)
    return result


def audio_for(brief, manifest, root, duration, first_cut):
    assets, tracks, notes = [], [], []
    for role in ("music", "sfx"):
        choice = getattr(brief, role)
        if choice["source"] != "supplied files":
            continue
        cursor = 0.0 if role == "music" else (first_cut or 0.0)
        for selector in choice["files"]:
            matches = [a for a in manifest.assets if selector in (a.id, a.path)]
            if not matches:
                selected_path = resolve_path(selector, root)
                matches = [a for a in manifest.assets if resolve_path(a.path, root) == selected_path]
            if len(matches) != 1:
                shortage("audio_asset", f"Supplied {role} {selector!r} is not uniquely inventoried.",
                         "Add the file to the clip inventory and run zing project scan.")
            a = matches[0]
            path = resolve_path(a.path, root)
            if (a.state != "ready" or not a.probe or not a.probe.has_audio or not a.probe.duration
                    or not path.is_file() or hash_file(path) != a.sha256):
                shortage("audio_asset", f"Supplied {role} {selector!r} is missing, stale, or has no measured audio.",
                         "Restore the audio asset and run zing project scan.", a.id)
            if cursor >= duration - EPS:
                shortage("audio_placement", f"No timeline room for supplied {role} {selector!r}.",
                         "Supply fewer audio files or lengthen the brief.", a.id)
            length = min(a.probe.duration, duration - cursor)
            assets.append(AssetRef(a.id, str(path), a.sha256, a.probe.duration))
            tracks.append(CompositionAudio(
                id=f"{role}-{len(tracks) + 1}", asset_id=a.id, src=str(path), kind=role, role=role,
                timeline_start=cursor, src_out=length,
                gain_db=-12 if role == "music" else -6,
                duck_under_speech=role == "music", duck_scope="source_speech" if role == "music" else "voiceover",
            ))
            cursor += length
        notes.append(f"Supplied {role} placed sequentially from {'zero' if role == 'music' else 'the first cut'}; "
                     "gain and placement are editorial defaults, not measured reference events.")
    notes.append("Source audio follows each clip. 'none' adds no music/SFX; it does not remove embedded sounds.")
    return assets, tracks, notes


def make_plan(label, sequence, studies, recipe, recipe_dir, style, brief, manifest, root, seed, required, forbidden):
    lookup = {s.asset_id: s for s in studies}
    font, font_report = font_choice(recipe, recipe_dir)
    used = sorted({c.asset_id for c in sequence})
    assets = [AssetRef(k, lookup[k].path, lookup[k].sha256, lookup[k].duration) for k in used]
    clips, cursor = [], 0.0
    color = deepcopy(recipe.approximations.looks[0].color) if recipe.approximations.looks else None
    if color:
        color.lut_path = str(resolve_path(color.lut_path, recipe_dir))
        if not Path(color.lut_path).is_file() or hash_file(Path(color.lut_path)) != color.sha256:
            shortage("color_asset", "Selected LUT is missing or has a different checksum.", "Restore the LUT recorded in the recipe.")
    for i, c in enumerate(sequence):
        clips.append(CompositionClip(id=f"clip-{i + 1}", asset_id=c.asset_id, src=lookup[c.asset_id].path,
                                     src_in=c.start, src_out=c.end, timeline_start=cursor, color=deepcopy(color)))
        cursor += c.duration
    captions = captions_for(sequence, studies, style, recipe, font, brief)
    durations = shot_lengths(sequence, studies)
    first_cut = durations[0] if len(durations) > 1 else None
    audio_assets, audio, audio_notes = audio_for(brief, manifest, root, cursor, first_cut)
    assets = list({a.id: a for a in [*assets, *audio_assets]}.values())
    # Output dimensions follow the brief; 30 CFR is an explicit delivery choice,
    # not an inferred property of the reference or camera.
    width, height = {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080)}[brief.aspect]
    plan = Composition(assets=assets, clips=clips, captions=captions, audio=audio,
                       width=width, height=height, fps=Rational(30, 1), brief=deepcopy(brief))
    numbers = {
        "median_shot_seconds": metric(style.median_shot, median(durations), (style.median_shot or 0) * .1,
                                      "Whole-word cuts, required moments and available shot choices constrain the selected edit."),
        "first_cut_seconds": metric(style.first_cut, first_cut, 2 / 30,
                                    "A word-safe opening with this timing was not selected by the bounded search."),
        "first_caption_seconds": metric(style.first_caption, first_caption(sequence), 1 / 30,
                                        "Caption onset follows complete source words; words are not retimed to fake a match."),
        "words_visible": metric(style.words_visible if style.basis["caption_events"] else None,
                                median([len(c.text.split()) for c in captions]) if captions else None, 0,
                                "Speech gaps and clip endings leave shorter caption groups."),
        "all_caps_rate": metric(style.all_caps_rate if style.basis["caption_events"] else None,
                                sum(c.text.isupper() for c in captions) / len(captions) if captions else None,
                                .5 / len(captions) if captions else 0,
                                "Integer caption-event counts limit the representable rate."),
        "target_length_seconds": metric(brief.target_length_seconds, cursor, 2 / 30,
                                        "The brief supplies the duration; two output frames are allowed."),
    }
    notes = [*recipe.warnings, *audio_notes,
             "30 fps CFR and full-HD aspect dimensions are delivery defaults; framing needs review.",
             "Opening ranks use measured proxies, not semantic hook/visual-salience judgments.",
             "Caption timing validation is not an ASR accuracy measurement; human-labeled 95th-percentile error is unmeasured."]
    if font is None:
        notes.append(font_report["reason"])
    for key in used:
        notes.extend(lookup[key].warnings)
    if recipe.approximations.layout:
        notes.append("Layout positions come from the recipe; output face safety must be checked on each assembled edit.")
    if recipe.approximations.transitions:
        notes.append("Transition approximations are not applied by P17; these plans use hard cuts to preserve word-safe source trims.")
    if brief.caption_language != "original":
        notes.append(f"Requested caption language {brief.caption_language!r}; source transcript retained, translation/language verification unperformed.")
    for spelling in brief.exact_spellings:
        if not any(tokens(spelling) == tokens(c.text) or
                   " ".join(tokens(spelling)) in " ".join(tokens(c.text)) for c in sequence):
            notes.append(f"Exact spelling {spelling!r} was not found verbatim; review ASR names before rendering.")
    report = {
        "version": 1, "draft": label, "seed": seed, "strategy": STRATEGIES[label],
        "opening": {"asset_id": sequence[0].asset_id, "src_in": sequence[0].start,
                    "src_out": sequence[0].end, "words": sequence[0].text,
                    "raw_keeper_support": sequence[0].keeper, "keyframe_available": sequence[0].keyframe},
        "match": numbers, "honored": [key for key, value in numbers.items() if value["status"] == "honored"],
        "deviations": [{"metric": key, **value} for key, value in numbers.items() if value["status"] == "deviation"],
        "pacing_evidence": {"shot_durations_seconds": durations,
                            "cut_positions_seconds": [sum(durations[:i]) for i in range(1, len(durations))],
                            "basis": "Measured internal source cuts plus discontinuous source selections; no artificial adjacent split cuts."},
        "font": font_report, "recipe_unknowns": [u.to_dict() for u in recipe.unknowns],
        "recipe_facts": [f.to_dict() for f in recipe.measured],
        "unmatched_recipe_facts": [f.name for f in recipe.measured if f.name not in
                                   {"shot_durations", "average_shot_duration", "cuts_per_10s"}
                                   and not f.name.startswith("captions[")],
        "source_output_mappings": [{"clip_id": c.id, "asset_id": c.asset_id, "src_in": c.src_in,
                                    "src_out": c.src_out, "output_start": c.timeline_start,
                                    "output_end": c.timeline_end} for c in clips],
        "constraints": {"must_keep_word_safe": required, "forbidden_word_safe": forbidden,
                        "speech_cuts": "validated word endpoints, or measured non-speech boundaries",
                        "repeated_source_ranges": False},
        "scope": "Planned values only. No render, output analysis, semantic quality score or original-style recovery.",
        "reference_match": brief.reference_match, "warnings": list(dict.fromkeys(notes)),
    }
    return plan, report


def attach_report(plan, report):
    plan.warnings = [*report["warnings"], REPORT_PREFIX + json.dumps(report, sort_keys=True, ensure_ascii=False, allow_nan=False)]
    return Composition.from_dict(plan.to_dict())


def render_projection(plan):
    """Explicitly separate P17 evidence for a legacy render derivative.

    The caller retains the full v2 plan and comparison report. No layout, font,
    color, audio policy, or other rendering instruction may be discarded.
    The public lower_to_v1 function stays strict and unchanged.
    """
    if not any(w.startswith(REPORT_PREFIX) for w in plan.warnings):
        raise ValueError("Expected a P17 plan with retained planning evidence.")
    projected = replace(plan, warnings=[], brief=None)
    blockers = lowering_blockers(projected)
    return (None, blockers) if blockers else (lower_to_v1(projected), [])
