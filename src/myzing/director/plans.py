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
from myzing.style_ranges import timing_band, timing_distance

from .models import shortage
from .selection import ALTERNATIVE, EPS, band_distance, first_caption, reference_band, shot_lengths, tokens
from .continuity import clauses, score

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


def captions_for(sequence, studies, style, recipe, font, brief, *, phone=False):
    lookup = {s.asset_id: s for s in studies}
    groups, cursor = [], 0.0
    for c in sequence:
        source_clauses = clauses(lookup[c.asset_id].words)
        clause_ends = {s.end for s in source_clauses}
        window = []
        for word in lookup[c.asset_id].words:
            if not (word.start >= c.start - EPS and word.end <= c.end + EPS):
                continue
            if window and window[-1].end in clause_ends:
                groups.append((window, cursor - c.start))
                window = []
            window.append(word)
        if window:
            groups.append((window, cursor - c.start))
        cursor += c.duration
    if phone:
        # Balanced groups of up to four words; no one-word flashes.
        from myzing.layout.readability import phone_word_groups
        groups = [(part, offset) for window, offset in groups for part in phone_word_groups(window)]
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
            font=None if phone else deepcopy(font),
        )
        if phone:
            from myzing.composition import CaptionStyle
            caption.style = CaptionStyle(60, outline_width=4, box_color="#111111")
        if getattr(brief, "caption_options", None):
            from myzing.composition import CaptionStyle
            caption.style = CaptionStyle.from_dict({**(caption.style or CaptionStyle(60)).to_dict(), **brief.caption_options})
            if caption.style.highlight_box_color:
                caption.word_timed = True
        if not phone and layout and layout.events:
            caption.layout = _layout(caption, layout.events[i % len(layout.events)], layout.masks)
        result.append(caption)
    if phone and result:
        from myzing.layout.readability import hold_short_events
        hold_short_events(result, cursor)
    prepare_words([w for c in result for w in c.words], cursor, repair=False)
    return result


def audio_for(brief, manifest, root, duration, first_cut, *, include_music=True):
    assets, tracks, notes = [], [], []
    for role in ("music", "sfx"):
        if role == "music" and not include_music:
            continue
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


def make_plan(label, sequence, studies, recipe, recipe_dir, style, brief, manifest, root, seed, required, forbidden,
              subject_evidence=None, music_cache=None, timing_selection=None, caption_mode=None, picture_evidence=None):
    caption_mode = caption_mode or brief.caption_mode
    if caption_mode == "phone":
        brief = replace(brief, caption_mode="phone")
    from myzing.music.planning import plan_music
    from myzing.audio.media import AudioError
    try:
        sequence, music_assets, music_tracks, music_evidence = plan_music(
            sequence, studies, brief, manifest, root, style.median_shot, required, forbidden, music_cache,
            timing_bands={"first_cut": reference_band(style.first_cut, style),
                          "shot_pace": reference_band(style.median_shot, style)})
    except AudioError as exc:
        shortage("music_analysis", str(exc), "Check the local track and zing doctor; install myzing[audio] for music analysis.")
    lookup = {s.asset_id: s for s in studies}
    if caption_mode == "phone":
        font, font_report = None, {"family": "Arial", "status": "studio preference",
                                  "reason": "Phone captions use the renderer's default Arial bold with system fallback; original font unknown."}
    else:
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
    captions = [] if caption_mode == "none" else captions_for(sequence, studies, style, recipe, font, brief,
                                                              phone=caption_mode == "phone")
    durations = shot_lengths(sequence, studies)
    first_cut = durations[0] if len(durations) > 1 else None
    audio_assets, audio, audio_notes = audio_for(brief, manifest, root, cursor, first_cut, include_music=False)
    audio_assets += music_assets
    audio += music_tracks
    assets = list({a.id: a for a in [*assets, *audio_assets]}.values())
    # Output dimensions follow the brief's aspect and short side (1080 by
    # default); 30 CFR is an explicit delivery choice, not inferred.
    from myzing.composition.aspects import dimensions
    from myzing.layout.framing import select_framing, place_captions
    from myzing.layout.resolution import (auto_gain, chosen_short_side, mark_auto_declined, mark_auto_selected,
                                          resolution_advice)
    from myzing.render.framing import display_dimensions
    source_dimensions, square_pixels, probe_notes = {}, set(), []
    subject_evidence = subject_evidence or {}
    picture_evidence = picture_evidence or {}
    from myzing.layout.picture import select_picture_framing
    for clip in clips:
        probe = next(a.probe for a in manifest.assets if a.id == clip.asset_id)
        if probe is None or not probe.width or not probe.height:
            if brief.framing not in ("auto", "fit"):
                shortage("framing_dimensions", "Source dimensions are missing.", "Run zing project scan before framing.", clip.asset_id)
            probe_notes.append(f"clip {clip.id}: source dimensions missing; retaining fit, framing unmeasured.")
            continue
        stream = next((s for s in probe.streams if s.get("codec_type") == "video"), {})
        sw, sh = display_dimensions({"width": probe.width, "height": probe.height,
                                    "tags": {"rotate": probe.rotation}, **stream})
        source_dimensions[clip.asset_id] = (sw, sh)
        if display_dimensions({"width": probe.width, "height": probe.height, "tags": {"rotate": probe.rotation},
                               **stream, "sample_aspect_ratio": "1:1"}) == (sw, sh):
            square_pixels.add(clip.asset_id)

    def frame(width, height):
        """Clips framed (and split at shots) for one delivery size."""
        framed, framing_notes = [], list(probe_notes)
        for clip in clips:
            framing = None
            if clip.asset_id in source_dimensions:
                tracks, notes = subject_evidence.get(clip.asset_id, ([], []))
                framing = select_picture_framing(brief.framing, *source_dimensions[clip.asset_id], width, height, clip,
                                         tracks, max_upscale=brief.framing_max_upscale,
                                         picture=picture_evidence.get(clip.asset_id), policy=brief.picture_crop)
                framing_notes.extend([*notes, *framing.warnings, *framing.upscale_warning(width, height)])
            framed.append(replace(clip, framing=framing))
        split_clips = []
        for clip in framed:
            f = clip.framing
            cuts = [clip.src_in]
            if f is not None and f.mode != "fit" and brief.framing in ("auto", "reframe", "zoomfill"):
                for shot in lookup[clip.asset_id].shots:
                    if shot.start - cuts[-1] >= 1 / 30 and clip.src_out - shot.start >= 1 / 30:
                        cuts.append(shot.start)
            cuts.append(clip.src_out)
            for i, (start, end) in enumerate(zip(cuts, cuts[1:])):
                part = replace(clip, id=clip.id if len(cuts) == 2 else f"{clip.id}-shot-{i + 1}",
                               src_in=start, src_out=end, timeline_start=clip.timeline_start + start - clip.src_in,
                               framing=None)
                if f is not None:
                    part.framing = select_picture_framing(brief.framing, f.source_width, f.source_height, width, height,
                                                  part, subject_evidence.get(clip.asset_id, ([], []))[0],
                                                  max_upscale=brief.framing_max_upscale,
                                                  picture=picture_evidence.get(clip.asset_id), policy=brief.picture_crop)
                split_clips.append(part)
        advice = resolution_advice(split_clips, source_dimensions, width, height,
                                   max_upscale=brief.framing_max_upscale,
                                   command=f"zing render plan-{label}.json --aspect {brief.aspect}")
        for clip in split_clips:
            # A square-pixel full-picture fit renders identically with framing
            # absent (the default fit graph; FFmpeg applies display rotation).
            # Omitting it keeps such plans representable as v1 EDLs.
            if clip.framing is not None and clip.framing.mode == "fit" and not clip.framing.picture and clip.asset_id in square_pixels:
                clip.framing = None
        return split_clips, framing_notes, advice

    requested_side = brief.short_side
    width, height = dimensions(brief.aspect, 1080 if requested_side == "auto" else requested_side)
    clips, framing_notes, resolution = frame(width, height)
    if requested_side == "auto" and chosen_short_side(resolution, "auto") != min(width, height):
        # The brief asked Zing to lower the delivery size when a source is too
        # small. Re-plan at the recommended size and keep it only when the
        # planned picture improves: subject evidence can hold a crop wider at
        # any size, and then a smaller delivery only loses pixels.
        first, trial = resolution, dimensions(brief.aspect, chosen_short_side(resolution, "auto"))
        lowered = frame(*trial)
        if auto_gain(first, lowered[2]):
            (width, height), (clips, framing_notes, resolution) = trial, lowered
            mark_auto_selected(resolution, first)
        else:
            mark_auto_declined(resolution, lowered[2])
    plan = Composition(assets=assets, clips=clips, captions=captions, audio=audio,
                       width=width, height=height, fps=Rational(30, 1), brief=deepcopy(brief))
    if source_dimensions:
        place_captions(plan, {key: value[0] for key, value in subject_evidence.items()}, source_dimensions,
                       keep_safe_defaults=True)
    if music_tracks:
        from myzing.music.models import attach
        attach(plan, music_evidence)
    numbers = {
        "median_shot_seconds": metric(style.median_shot, median(durations), timing_band(style.median_shot, style.basis.get("shot_durations", []))["tolerance"],
                                      "Whole-word cuts, required moments and available shot choices constrain the selected edit."),
        "first_cut_seconds": metric(style.first_cut, first_cut, timing_band(style.first_cut, style.basis.get("shot_durations", []))["tolerance"],
                                    "A word-safe opening with this timing was not selected by the bounded search."),
        "first_caption_seconds": metric(style.first_caption, first_caption(sequence), 1 / 30,
                                        "Caption onset follows complete source words; words are not retimed to fake a match."),
        "words_visible": metric(style.words_visible if style.basis["caption_events"] else None,
                                median([len(c.text.split()) for c in captions]) if captions else None, 0,
                                "Complete clauses override reference caption-group width; typography may differ."),
        "all_caps_rate": metric(style.all_caps_rate if style.basis["caption_events"] else None,
                                sum(c.text.isupper() for c in captions) / len(captions) if captions else None,
                                .5 / len(captions) if captions else 0,
                                "Integer caption-event counts limit the representable rate."),
        "target_length_seconds": metric(brief.target_length_seconds, cursor, 2 / 30,
                                        "The brief supplies the duration; two output frames are allowed."),
    }
    if timing_selection:
        # Selection evidence was captured before music snapping, which can move
        # a join toward or away from a band. Describe the final edit only.
        from .selection import selection_timing_evidence
        timing_selection = selection_timing_evidence(
            sequence, studies, reference_band(style.first_cut, style), reference_band(style.median_shot, style),
            next(iter(timing_selection.values()))["search"],
            selected={key: value["planned"] for key, value in timing_selection.items()})
    for key in ("median_shot_seconds", "first_cut_seconds"):
        item = numbers[key]
        item["band"] = reference_band(item["target"], style)
        if item["band"]["lower"] is None:
            continue  # Unmeasured, or a studio preference: there is no reference band to cite.
        if timing_selection and key in timing_selection:
            item["selection"] = timing_selection[key]
            item["reason"] = timing_selection[key]["reason"]
        item["reason"] = timing_distance(item["planned"], item["band"]) + " " + item["reason"]
    resolution_note = []
    if resolution["limited"] or resolution.get("auto_selected"):
        resolution_note = [resolution["summary"]]
    notes = [*resolution_note, *recipe.warnings, *audio_notes, *framing_notes,
             f"30 fps CFR and {width}x{height} ({brief.aspect}, short side {min(width, height)}) are delivery "
             "choices; framing needs review.",
             "Opening ranks use measured proxies, not semantic hook/visual-salience judgments.",
             "Caption timing validation is not an ASR accuracy measurement; human-labeled 95th-percentile error is unmeasured."]
    if caption_mode == "phone":
        notes.append("Studio phone captions use up to four timed words and the renderer's default font. Portrait em size is at least 8% of visible picture width and 7% of output width; square/wide use 6.5% of min(picture width, output height). Infeasible phone layouts require shorter phrases or different framing. This is a readability preference, not recovered typography.")
    if music_tracks:
        notes.extend(music_evidence.warnings)
    continuity = score(sequence, studies, allow_reordering="[allow source reordering]" in brief.purpose.casefold())
    if continuity["status"] == "flagged":
        notes.append("Continuity flagged: no better complete-clause trio found within the bounded search; review dangling source speech.")
    elif continuity["status"] == "not_applicable":
        notes.append("Continuity not applicable: this draft selects no transcribed speech.")
    if numbers["median_shot_seconds"]["status"] == "deviation":
        notes.append("Pacing unmet: the selected complete-clause draft misses the reference envelope, including internal source cuts. The bounded search did not select a matching alternative.")
    relaxed = next(iter(timing_selection.values()))["search"].get("distinctness_relaxed") if timing_selection else None
    alternative = None
    if relaxed and label in relaxed["alternatives"]:
        # Name the final, rendered timing values; never present this as a pass.
        outside = [f"{name.replace('_seconds', '').replace('_', ' ')} "
                   + ("missing" if item["planned"] is None else f"{item['planned']:.3f} s")
                   + f" is outside the {item['band']['lower']:.3f}-{item['band']['upper']:.3f} s reference band"
                   for name, item in (("first_cut_seconds", numbers["first_cut_seconds"]),
                                      ("median_shot_seconds", numbers["median_shot_seconds"]))
                   if item.get("band", {}).get("lower") is not None
                   and band_distance(item["planned"], item["band"]) > EPS]
        count = relaxed["distinct_in_band_edits"]
        why = "; ".join(outside or ["selected after every in-band edit was used"])
        alternative = {"outside_reference_timing": True, "label": ALTERNATIVE,
                       "reason": f"{why}; only {count} distinct completed edit{'s' if count != 1 else ''} "
                                 "fit both timing bands"}
        notes.insert(0, f"{label}: {ALTERNATIVE}: {alternative['reason']}.")
    if relaxed and (label in relaxed["alternatives"] or any(label in pair for pair in relaxed["similar_pairs"])):
        notes.append(relaxed["reason"])
    if font is None:
        notes.append(font_report["reason"])
    for key in used:
        notes.extend(lookup[key].warnings)
    if recipe.approximations.layout and caption_mode != "phone":
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
        "music": music_evidence.to_dict() if music_tracks else None,
        "continuity": continuity,
        "opening": {"asset_id": sequence[0].asset_id, "src_in": sequence[0].start,
                    "src_out": sequence[0].end, "words": sequence[0].text,
                    "raw_keeper_support": sequence[0].keeper, "keyframe_available": sequence[0].keyframe},
        "match": numbers, "honored": [key for key, value in numbers.items() if value["status"] == "honored"],
        "deviations": [{"metric": key, **value} for key, value in numbers.items() if value["status"] == "deviation"],
        "pacing_evidence": {"shot_durations_seconds": durations,
                            "status": "unmet" if numbers["median_shot_seconds"]["status"] == "deviation" else numbers["median_shot_seconds"]["status"],
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
        "framing": [{"clip_id": c.id, "framing": c.framing.to_dict()} for c in clips if c.framing is not None],
        "resolution": resolution,
        "constraints": {"must_keep_word_safe": required, "forbidden_word_safe": forbidden,
                        "speech_cuts": "whole rule-derived clauses, or measured non-speech boundaries",
                        "repeated_source_ranges": False},
        "scope": "Planned values and structural continuity rules only. No semantic quality certification or original-style recovery.",
        "reference_match": brief.reference_match, "warnings": list(dict.fromkeys(notes)),
        **({"alternative": alternative} if alternative else {}),
    }
    return plan, report


def attach_report(plan, report):
    from myzing.music.models import PREFIX
    music = [w for w in plan.warnings if w.startswith(PREFIX)]
    plan.warnings = [*report["warnings"], *music, REPORT_PREFIX + json.dumps(report, sort_keys=True, ensure_ascii=False, allow_nan=False)]
    return Composition.from_dict(plan.to_dict())


MUSIC_SIDECAR = "zing.music_sidecar"
MUSIC_CANNOT_CARRY = [
    "the music track itself: EDL v1 plays each audio file from its first sample, so a source trim is impossible",
    "ducking under source speech: EDL v1 ducks music only under voiceover tracks",
    "the duck envelope (including per-clip bed gain points) and music fades",
    "per-clip dialogue gain, its peak compressor and the speech-free audio fades at source changes: EDL v1 "
    "plays each clip's audio unchanged (the sidecar lists them under dialogue)",
    "MUSIC1 evidence: track choice, drop/moment alignment, cut snapping and their reasons",
    "the v2 renderer's music measurement sidecar and final -2 dBFS peak limiter",
]


def _duck_envelope(passages, duration, depth, attack, release, gain_points=()):
    """Gain keyframes (seconds, dB) at every ramp start/end, in timeline time.

    Zing renders raised-cosine ramps (myzing.music.ducking); straight lines
    between these keyframes approximate them, exactly at each keyframe. Bed
    gain points (per-clip bed level) add to the duck at their own keyframes.
    """
    import math

    from myzing.music.ducking import gain_at

    def weight(t):
        best = 0.0
        for a, b in passages:
            if a <= t <= b:
                return 1.0
            if attack > 0 and a - attack <= t < a:
                best = max(best, (1 - math.cos(math.pi * (t - (a - attack)) / attack)) / 2)
            if release > 0 and b < t <= b + release:
                best = max(best, (1 + math.cos(math.pi * (t - b) / release)) / 2)
        return best

    times = sorted({0.0, duration, *(max(0.0, min(duration, t)) for a, b in passages
                                     for t in (a - attack, a, b, b + release)),
                    *(max(0.0, min(duration, float(t))) for t, _ in gain_points)})
    return [[round(t, 6), round(-depth * weight(t) + gain_at(gain_points, t), 3) + 0.0] for t in times]


def music_sidecar(plan, label: str) -> dict:
    """Everything a human editor needs to rebuild the plan's music bed."""
    from myzing.music.dialogue import edge_fade_seconds, row_at
    from myzing.music.ducking import duck_passages, release_gap
    from myzing.music.models import extract

    evidence = extract(plan)
    duration = max((c.timeline_end for c in plan.clips), default=0.0)
    tracks = []
    for audio in (a for a in plan.audio if a.role == "music"):
        source_out = audio.src_out
        length = (source_out - audio.src_in) if source_out is not None else None
        planned = next((t for t in evidence.tracks if t["id"] == audio.id), None)
        fades = ({"fade_in_seconds": round(min(.15, length / 4), 6), "fade_out_seconds": round(min(1.0, length / 4), 6)}
                 if planned is not None and length else {"fade_in_seconds": 0.0, "fade_out_seconds": 0.0})
        duck = None
        if audio.duck_under_speech and audio.duck_scope == "source_speech":
            # The renderer's passages: gaps shorter than the release gap and
            # close edit edges stay ducked (myzing.music.ducking.duck_passages).
            held = duck_passages(evidence.speech_spans, duration, hold=evidence.duck_hold_seconds,
                                 attack=evidence.duck_attack_seconds, release=evidence.duck_release_seconds,
                                 plateau=evidence.duck_plateau_seconds)
            duck = {"scope": "source_speech", "depth_db": evidence.duck_depth_db,
                    "attack_seconds": evidence.duck_attack_seconds,
                    "release_seconds": evidence.duck_release_seconds,
                    "hold_seconds": evidence.duck_hold_seconds,
                    "plateau_seconds": evidence.duck_plateau_seconds,
                    "release_gap_seconds": release_gap(evidence.duck_hold_seconds, evidence.duck_attack_seconds,
                                                       evidence.duck_release_seconds, evidence.duck_plateau_seconds),
                    "speech_to_music_target_lu": evidence.speech_to_music_lu,
                    "speech_spans": evidence.speech_spans, "passages": held,
                    "bed_gain_points": [list(p) for p in evidence.bed_gain_points],
                    "envelope_db": _duck_envelope(held, duration, evidence.duck_depth_db,
                                                  evidence.duck_attack_seconds, evidence.duck_release_seconds,
                                                  evidence.bed_gain_points),
                    "envelope_note": ("Timeline seconds and gain in dB relative to the track gain, per-clip bed "
                                      "gain points included; Zing renders raised-cosine ramps between these "
                                      "keyframes.")}
        elif audio.duck_under_speech:
            duck = {"scope": audio.duck_scope, "note": "Ducks under voiceover; EDL v1 can carry this track."}
        tracks.append({
            "id": audio.id, "asset_id": audio.asset_id, "path": audio.src,
            "sha256": next((a.sha256 for a in plan.assets if a.id == audio.asset_id), None),
            "timeline_start": audio.timeline_start,
            "timeline_end": round(audio.timeline_start + length, 6) if length is not None else None,
            "source_in": audio.src_in, "source_out": source_out, "gain_db": audio.gain_db, **fades, "duck": duck,
            "reason": planned.get("reason") if planned else None})
    # Dialogue matching and source-change fades act on the clips' own audio,
    # which the v1 EDL plays unchanged; list them per clip for an editor.
    ordered = sorted(plan.clips, key=lambda c: c.timeline_start)
    scoped = any(a.role == "music" and a.duck_under_speech and a.duck_scope == "source_speech" for a in plan.audio)
    fades = edge_fade_seconds(ordered, evidence.speech_spans) if scoped else [(0.0, 0.0)] * len(ordered)
    dialogue = []
    for clip, (fade_in, fade_out) in zip(ordered, fades):
        row = row_at(evidence.dialogue_gains, clip.timeline_start + clip.duration / 2, clip.asset_id)
        if row or fade_in or fade_out:
            dialogue.append({"clip_id": clip.id, "asset_id": clip.asset_id, "timeline_start": clip.timeline_start,
                             "timeline_end": clip.timeline_end, "gain_db": row["gain_db"] if row else 0.0,
                             "compressor": row.get("compressor") if row else None,
                             "fade_in_seconds": round(fade_in, 6), "fade_out_seconds": round(fade_out, 6)})
    return {"version": 1, "kind": MUSIC_SIDECAR, "plan": f"plan-{label}.json", "edl": f"plan-{label}.edl.json",
            "fps": [plan.fps.numerator, plan.fps.denominator], "timeline_duration": round(duration, 6),
            "tracks": tracks, "dialogue": dialogue, "cannot_carry": MUSIC_CANNOT_CARRY,
            "rebuild": ("Import the EDL's picture and dialogue, apply each dialogue entry's clip gain, compressor "
                        "(threshold dBFS, ratio, attack and release ms, knee dB) and fades to that clip's audio, "
                        "then place each track at timeline_start using source_in..source_out of the file, apply "
                        "gain_db, the fades, and the duck envelope keyframes. Rendering plan-" + label + ".json "
                        "with zing render reproduces the full mix.")}


def music_projection(plan, label: str):
    """For a music plan: (picture-and-dialogue v1 EDL, music sidecar, blockers).

    Music is the only thing separated, and only when it is the sole reason
    lowering fails; every other v2 feature still blocks the derivative.
    """
    if not any(w.startswith(REPORT_PREFIX) for w in plan.warnings):
        raise ValueError("Expected a P17 plan with retained planning evidence.")
    if not any(a.role == "music" for a in plan.audio):
        return None, None, []
    projected = replace(plan, warnings=[], brief=None, audio=[a for a in plan.audio if a.role != "music"])
    blockers = lowering_blockers(projected)
    if blockers:
        return None, None, blockers
    return lower_to_v1(projected), music_sidecar(plan, label), []


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
