"""Orchestrate existing producers. Each checkpoint owns only its own artifacts."""

from __future__ import annotations

import importlib.util
import os
import tempfile
import time
from copy import deepcopy
from pathlib import Path

from myzing import storage
from myzing.brief.api import load_brief, save_brief
from myzing.brief.models import Brief
from myzing.composition import Composition
from myzing.project import api as projects
from myzing.project.paths import resolve_path
from myzing.project.references import resolve_reference
from myzing.schemas import Breakdown
from myzing.study.api import study
from myzing.study.source_map import METHOD as SOURCE_MAP_METHOD
from myzing.director.selection import ALTERNATIVE
from myzing.style_recipe import StyleRecipe, build_style_recipe
from myzing.urls import is_http_url

from . import evidence
from .state import Checkpoints, StepFailed, read, write


def validate(reference, clips, out, *, brief=None, answers=None, drafts=3, seed=0, resume=False, allow_download=False, studio_options=None, ref_start=None, ref_end=None, reference_range=None, **_):
    if studio_options is not None:
        from myzing.studio.adapters import validate_options
        validate_options(studio_options)
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("Supply a reference URL, local file, or uoink:<id>.")
    if type(drafts) is not int or drafts != 3:
        raise ValueError("This director supports --drafts 3 (A/B/C).")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    if type(resume) is not bool or type(allow_download) is not bool:
        raise ValueError("resume and allow_download must be booleans")
    if not isinstance(clips, (str, Path)) or not str(clips).strip() or not isinstance(out, (str, Path)) or not str(out).strip():
        raise ValueError("Supply nonempty local --clips and --out folders.")
    if brief is not None and answers is not None:
        raise ValueError("Use --brief or --answers, not both.")
    if not Path(clips).expanduser().is_dir():
        raise ValueError("--clips must be an existing local folder.")
    if Path(clips).expanduser().resolve() == Path(out).expanduser().resolve():
        raise ValueError("--out must differ from the clip folder so generated outputs do not become inputs.")
    if not is_http_url(reference) and not reference.startswith("uoink:") and not Path(reference).expanduser().is_file():
        raise ValueError("Reference file does not exist; use a local file, HTTP(S) URL, or uoink:<id>.")
    from myzing.reference_range import parse
    parse(ref_start, ref_end, reference_range)
    if brief is not None:
        load_brief(brief)
    elif answers is not None:
        Brief.from_answers(answers)
    elif not (resume and (Path(out) / "brief.json").is_file()):
        raise ValueError("Noninteractive match needs --brief <file> or --answers '<json>'; use a terminal for the interview.")


def init(reference, clips, root):
    if (root / "project.json").exists():
        manifest = projects.load_project(root)
        expected = reference if is_http_url(reference) or reference.startswith("uoink:") else projects.stored_path(Path(reference), root)
        if manifest.reference.value != expected or resolve_path(manifest.clips_root, root) != Path(clips).expanduser().resolve():
            raise ValueError("This project belongs to different inputs; use a new --out folder.")
        return projects.scan_project(root)
    return projects.init_project(reference, clips, root)


def capabilities():
    def present(module):
        return importlib.util.find_spec(module) is not None
    from myzing.layout.detector import model_path, verified_model
    from importlib.metadata import PackageNotFoundError, version
    versions = {}
    for package in ("myzing", "numpy", "Pillow", "opencv-python-headless", "faster-whisper", "rapidocr", "scenedetect", "pysubs2", "sherpa-onnx"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = None
    from myzing.study.caption_models import model_paths
    try:
        ocr = {k: projects.hash_file(p) for k, p in model_paths().items()}
    except (ImportError, RuntimeError, OSError):
        ocr = None
    from myzing.fonts.library import inventory
    font_files = [{k: row[k] for k in ("id", "sha256", "available")} for row in inventory()]
    model = os.environ.get("ZING_WHISPER_MODEL", "large-v2")
    cache = Path(os.environ.get("HF_HUB_CACHE", os.environ.get("HUGGINGFACE_HUB_CACHE",
                 str(Path(os.environ.get("HF_HOME", str(Path.home() / ".cache/huggingface"))) / "hub"))))
    cached = [Path(model) / "model.bin"] if Path(model).is_dir() else list(cache.glob(f"models--*faster-whisper-{model}/snapshots/*/model.bin"))
    whisper = [(str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in cached if p.is_file()]
    from myzing.audio.tag_models import model_paths, REVISION
    from myzing.audio.tagging import ALGORITHM as TAG_ALGORITHM
    try:
        tag_assets = {name: str(path) for name, path in model_paths().items()}
    except (RuntimeError, OSError):
        tag_assets = {}
    return {"audio_tagging": {"revision": REVISION, "algorithm": TAG_ALGORITHM, "verified_assets": tag_assets},
            "asr_hygiene": "vad-edge-snap-v2+prompt-tokens-v1+recall-guard-v1",
            "fonts": present("PIL") and present("cv2"), "color": present("numpy"),
            "audio": present("numpy"), "layout": present("cv2") and verified_model(model_path()),
            "versions": versions, "ocr_models": ocr, "font_files": font_files, "whisper_model": model,
            "whisper_cache": whisper}


def _study(source, workspace, *, raw=False, fonts=False, max_seconds=None, verification=False, vocabulary=(), speech_model=None, ref_start=None, ref_end=None, reference_range=None):
    from myzing.reference_range import validate_duration, slug as reference_slug
    if max_seconds:
        from myzing.project.probe import probe_file
        validate_duration(probe_file(Path(source)).duration, ref_start, ref_end, reference_range, limit=max_seconds)
    before = projects.hash_file(Path(source))
    b = study(str(source), workspace=workspace, raw_mode=raw, caption_geometry=True,
              **{k: v for k, v in dict(ref_start=ref_start, ref_end=ref_end, reference_range=reference_range).items() if v is not None},
              fonts=fonts, detect_transitions=not raw, local_models_only=True,
              model_workspace=storage.resolve_workspace(),
              **({"vocabulary": vocabulary} if vocabulary else {}),
              **({"shot_min_scene_len_s": 0.0} if verification else {}),
              **({"speech_model": speech_model} if speech_model is not None else {}))
    if projects.hash_file(Path(source)) != before:
        raise ValueError("Source changed during study; wait for writes to finish and --resume.")
    # A half-open 60s selection at fractional fps can contain a final frame
    # whose exposure ends just beyond 60s. The requested interval was checked
    # before study; allow only that one-frame quantization at this late guard.
    frame_slack = 1 / b.meta.fps if b.meta.fps and b.meta.fps > 0 else 0
    if max_seconds and b.meta.duration > max_seconds + frame_slack + 1e-6:
        raise ValueError("Reference exceeds v0.1's 60-second limit; trim it and use a new project.")
    b.provenance["source_sha256"] = before
    with storage.use_workspace(workspace):
        slug = reference_slug(str(source), ref_start, ref_end, reference_range)
        storage.save_breakdown(b, slug=slug)
        folder = storage.breakdown_dir(slug)
        media = storage.resolve_relpath(slug, b.meta.media_path)
    files = [folder / "breakdown.json", media, *folder.rglob("*.jpg"), *folder.rglob("*.png")]
    geometry = folder / "caption-geometry.json"
    if geometry.is_file():
        files.append(geometry)
    # The content hash keys later steps (director, inspection): a restudy that
    # changes evidence, such as a new source map, must not reuse old plans.
    return {"path": str(folder / "breakdown.json"), "sha256": projects.hash_file(folder / "breakdown.json"),
            "media": str(media), "slug": slug, "geometry": str(geometry) if geometry.is_file() else None,
            "warnings": b.warnings, "outputs": list(map(str, files))}


def _audio(studied, enabled):
    if not enabled:
        return {"outputs": [], "warnings": ['Audio map unavailable; install "myzing[audio]".']}
    from myzing.audio.api import analyze
    from myzing.study.ingest import probe
    if not any(s["codec_type"] == "audio" for s in probe(Path(studied["media"]))["streams"]):
        return {"outputs": [], "warnings": ["No audio stream; audio map unavailable."]}
    b = Breakdown.from_dict(read(studied["path"]))
    # The study tagged this same media file; reuse its windows instead of a second CED pass.
    mapped = analyze(studied["media"], breakdown=b, tags=b.provenance.get("audio_tags"))
    path = Path(studied["path"]).parent / "audio-map.json"
    write(path, mapped.to_dict())
    return {"outputs": [str(path)], "path": str(path), "warnings": mapped.warnings}


def _inspect(video, timeline, studied, workspace, duration):
    from myzing.inspect import InspectionError
    from myzing.inspect.timeline import inspect_timeline
    from myzing.inspect.timing import validate_words

    b = Breakdown.from_dict(read(studied["path"]))
    slug, warnings = studied["slug"], []
    try:
        validate_words(b.words, b.meta.duration)
    except InspectionError as exc:
        # Re-ASR is optional review evidence, not the caption render contract.
        # Keep the raw study intact and omit its entire transcript, explicitly.
        slug = None
        warnings.append(f"Rendered ASR transcript omitted from timeline: {exc} "
                        "Raw words remain in the rendered study; speech/caption sync needs review.")
    with storage.use_workspace(workspace):
        result = inspect_timeline(video, timeline, breakdown=slug, start=0,
                                  end=duration, overwrite=True)
    result.warnings.extend(warnings)
    return {"outputs": [str(timeline)], "inspection": result.to_dict(), "warnings": warnings}


def _color(reference, clip, directory):
    from myzing.color.api import match_video
    # The producer refuses existing LUT outputs. Keep incomplete attempts for
    # diagnosis and publish a fresh recipe, never remove an unknown directory.
    directory.mkdir(parents=True, exist_ok=True)
    attempt = Path(tempfile.mkdtemp(prefix="attempt-", dir=directory))
    recipe = match_video(reference, clip, attempt, samples=6)
    return {"path": str(attempt / "recipe.json"), "warnings": recipe.warnings,
            "outputs": [str(attempt / "recipe.json"), recipe.cube_path, recipe.preview_path]}


def _recipe(studied, audio, colors, path):
    from myzing.audio.models import AudioMap
    from myzing.color.models import Recipe as ColorRecipe
    from myzing.composition.models import FontAsset
    from myzing.style_recipe import Coverage, FontCandidate, MeasuredFact
    b = Breakdown.from_dict(read(studied["path"]))
    geometry = read(studied["geometry"]) if studied["geometry"] else {}
    from myzing.study.text_roles import classify_text, caption_geometry
    roles = classify_text(b, geometry)
    geometry = caption_geometry(geometry, roles)
    fonts = geometry.get("font_candidates", {})
    available = {r["id"]: r for r in fonts.get("available_fonts", [])}
    candidates = []
    for track in fonts.get("tracks", []):
        if track["kind"] != "caption" or not track.get("candidates"):
            continue
        row = available.get(track["candidates"][0]["font_id"])
        if row:
            candidates.append(FontCandidate(row["family"], [track["reason"], "Substitution ranked from sampled glyphs; original font unknown."],
                                            FontAsset(row["path"], row["sha256"], row["license"])))
            break
    color = ColorRecipe.from_dict(read(next(iter(colors.values()))["path"])) if colors else None
    recipe = build_style_recipe(
        b, reference_sha256=b.provenance["source_sha256"], font_candidates=candidates, text_roles=roles,
        audio=AudioMap.from_dict(read(audio["path"])) if audio.get("path") else None, color=color,
    )
    # Clip-fitted corrections are not a reusable LUT for arbitrary footage.
    recipe.approximations.looks = []
    if color is not None:
        # Per-sample reference statistics let the color report tell shot-to-shot
        # scene variation from a grade difference. No faces are measured here:
        # the reference's people are never a target for the draft's skin.
        from dataclasses import replace
        from .color import sample_stats
        main = next(f for f in recipe.measured if f.name == "color.lightness_percentiles")
        recipe.measured.append(replace(main, name="color.sample_stats", value=sample_stats(color.reference),
                                       unit="per-sample CIELAB L* percentiles, a*/b* mean, chroma, contrast, tone_ab"))
    stats = evidence.geometry_stats(geometry)
    if stats:
        recipe.measured.append(MeasuredFact("caption_geometry.summary", stats, "normalized frame edges",
                                           Coverage(stats["samples"], None, "sampled caption tracks; temporal gaps unobserved"),
                                           None, recipe.reference))
        recipe.unknowns = [u for u in recipe.unknowns if u.subject != "caption_geometry"]
    recipe.warnings += audio.get("warnings", [])
    if not candidates:
        recipe.warnings.append("No pinned font candidate available; using the director's disclosed system font default.")
    write(path, recipe.to_dict())
    return {"path": str(path), "outputs": [str(path)], "warnings": recipe.warnings}


def _prepare_plan(source, destination, colors, recipe, caps):
    from myzing.composition.models import ColorTransform
    from myzing.color.models import Recipe as ColorRecipe
    from myzing.render.composition import unsupported_features
    plan = Composition.from_dict(read(source))
    for clip in plan.clips:
        clip.color = ColorTransform.from_recipe(ColorRecipe.from_dict(read(colors[clip.asset_id]["path"]))) if clip.asset_id in colors else None
    unsupported = unsupported_features(plan)
    transitions = [s for s in unsupported if s.startswith("transition ")]
    if transitions:
        # P17 currently emits only cuts. A future producer with overlapping
        # transitions needs an explicit timing conversion; do not drop overlaps.
        raise ValueError("Renderer cannot represent planned transition overlaps: " + "; ".join(transitions))
    if any(f.name.startswith(("transitions[", "legacy_transitions[")) for f in recipe.measured) and not plan.transitions:
        plan.warnings.append("Reference transition observations are experimental. Director/renderer use cuts; effects were not reconstructed.")
    if any(c.framing is not None for c in plan.clips) or any(c.layout is not None for c in plan.captions):
        # Director has already measured source subjects and placed captions in
        # the cropped output (captions it left at their default position were
        # checked clear). Do not replace that safety with face-only layout.
        folder = destination.parent / destination.stem
        write(folder / "layout.json", {"version": 1, "events": [c.layout.to_dict() for c in plan.captions if c.layout],
                                       "framing": [c.framing.to_dict() for c in plan.clips if c.framing]})
    elif not plan.captions:
        pass  # Nothing to place; no face-layout warning applies.
    elif caps["layout"]:
        _layout(plan, destination.parent / destination.stem, recipe)
    else:
        plan.warnings.append("Face layout unavailable: using disclosed caption-position defaults; face avoidance is unmeasured. "
                             'Install "myzing[layout]" and explicitly run zing layout fetch-model to enable it.')
    unsupported = unsupported_features(plan)
    if unsupported:
        raise ValueError("Renderer does not support these planned features: " + "; ".join(unsupported))
    from .caption_fit import fit_captions
    fit_captions(plan, destination.parent / destination.stem)
    write(destination, plan.to_dict())
    sidecar = destination.parent / destination.stem / "layout.json"
    return {"path": str(destination), "outputs": [str(destination), *([str(sidecar)] if sidecar.is_file() else [])],
            "warnings": evidence.user_warnings(plan.warnings)}


def _layout(plan, folder, recipe):
    from myzing.layout import CaptionEvent, FrameDetections, build_tracks, choose_layout, platform_masks
    from myzing.layout.debug import read_image
    from myzing.layout.detector import YuNetDetector, MODEL_SHA256
    from myzing.layout.media import sample_frames
    from myzing.render.composition import render_composition
    folder.mkdir(parents=True, exist_ok=True)
    detector = YuNetDetector(download=False)
    # Measure in output coordinates, after the renderer's resize/padding, and
    # without captions occluding faces. Do not map raw boxes through guessed crops.
    clean = deepcopy(plan)
    clean.captions = []
    preview = folder / "layout-footage.mp4"
    render_composition(clean, preview, base_dir=folder)
    duration = max(c.timeline_end for c in plan.clips)
    with tempfile.TemporaryDirectory(dir=folder) as temp:
        samples = sample_frames(preview, Path(temp), duration=duration, sample_rate=2)
        detections = [FrameDetections(t, detector.detect(read_image(p))) for t, p in samples]
    tracks = build_tracks(detections, duration=duration, margin=.04, max_gap=1.5)
    facts = {f.name: f.value for f in recipe.measured}
    box = facts.get("caption_geometry.summary", {}).get("box")
    # The reference's glyph width does not bound different draft words. Reserve
    # a conservative envelope and let the public renderer verify actual ink fit.
    # This can sacrifice placement fidelity; it cannot certify an undersized box.
    width, height = (.8, .2) if not box else (max(.8, box[2] - box[0]), max(.2, box[3] - box[1]))
    anchor = "lower-third" if not box else [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2]
    events = [CaptionEvent(c.id, c.start, c.end, width, height, anchor) for c in plan.captions]
    layout = choose_layout(events, tracks, platform_masks("none"))
    layout.provenance.update(video_sha256=projects.hash_file(preview), model_sha256=MODEL_SHA256,
                             sample_times=[t for t, _ in samples], coordinates="rendered output; normalized display frame")
    layout.warnings.append("Faces sampled at 2 fps; missed faces and motion between samples remain unknown. "
                           "Conservative caption envelopes reserve at least 80% width and 20% height around the reference/default anchor; "
                           "the renderer validates ink fit. Box size and typography are approximations.")
    write(folder / "layout.json", layout.to_dict())
    for caption, event in zip(plan.captions, layout.events):
        caption.layout = event
    plan.warnings.extend(layout.warnings)
    # Unsafe events are left unsafe. The public renderer requires explicit review.


def match(reference, clips, out, *, brief=None, answers=None, drafts=3, seed=0,
          resume=False, allow_download=False, progress=None, run_id=None, repair_asr=True, studio_options=None, ref_start=None, ref_end=None, reference_range=None):
    """Synchronous worker API. CLI/MCP run this inside an owned process tree."""
    validate(reference, clips, out, brief=brief, answers=answers, drafts=drafts, seed=seed, resume=resume, allow_download=allow_download,
             **({"studio_options": studio_options} if studio_options is not None else {}))
    if type(repair_asr) is not bool:
        raise ValueError("repair_asr must be a boolean")
    from myzing.reference_range import parse
    parse(ref_start, ref_end, reference_range)
    trim = {k: v for k, v in dict(ref_start=ref_start, ref_end=ref_end, reference_range=reference_range).items() if v is not None}
    started = time.monotonic()
    root = Path(out).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not (root / "match-state.json").exists() and any((root / n).exists() for n in ("comparison.json", "comparison.md", "recipe.json")):
        raise ValueError("Output contains artifacts not owned by match; use a new --out folder.")
    checkpoints = Checkpoints(root, resume, progress)
    checkpoints.data["run_id"] = run_id
    write(checkpoints.path, checkpoints.data)
    summary = {"version": 1, "project": str(root), "requested": drafts, "ready": 0, "drafts": {},
               "shortages": [], "failures": [], "warnings": [], "status": "failed", "run_id": run_id}
    try:
        # The scan already reuses unchanged probes. Always check the live folder
        # before accepting downstream hashes, including additions/removals.
        def scan():
            manifest = init(reference, clips, root)
            return {"manifest": manifest.to_dict(), "outputs": []}
        checkpoints.step("project-scan", {"run": time.time()}, scan)
        if studio_options is not None:
            from myzing.studio.adapters import register_music
            register_music(root, studio_options.get("music"))
        manifest = projects.load_project(root)
        from myzing.project.probe import STILL_EXTENSIONS, skipped_stills_notice
        stills = {a.id for a in manifest.assets if a.state != "missing" and Path(a.path).suffix.lower() in STILL_EXTENSIONS}
        if stills:
            summary["warnings"].append(skipped_stills_notice(len(stills)))
        caps = capabilities()
        local = not is_http_url(reference) and not reference.startswith("uoink:")
        ref_key = {"reference": reference, "sha256": projects.hash_file(Path(reference)) if local else None}

        def resolve():
            if is_http_url(reference):
                if not allow_download:
                    raise ValueError("URL acquisition requires explicit --allow-download consent. Supply a local reference instead.")
                from myzing.explain.api import _resolve
                from myzing.project.probe import probe_file
                from myzing.reference_range import validate_duration
                acquired = _resolve(reference, root / "acquisition", allow_download=True)
                validate_duration(probe_file(acquired).duration, **trim, limit=60)
                resolution = resolve_reference(root, file=acquired)
            else:
                resolution = resolve_reference(root)
            if resolution.state != "resolved":
                raise ValueError(resolution.reason)
            return {"path": resolution.path, "sha256": resolution.sha256, "title": resolution.title, "outputs": [resolution.path]}

        def get_brief():
            selected = load_brief(brief) if brief else Brief.from_answers(answers) if answers is not None else load_brief(root / "brief.json")
            save_brief(root, selected)
            return {"outputs": [str(root / "brief.json")]}
        checkpoints.step("brief", {"brief": projects.hash_file(Path(brief)) if brief else None, "answers": answers,
                                   "saved": projects.hash_file(root / "brief.json") if brief is None and answers is None else None}, get_brief)
        from myzing.study.asr_hygiene import vocabulary_context
        context = vocabulary_context(brief=load_brief(root / "brief.json"))
        terms = context["terms"]
        speech = {"speech_model": studio_options["speech_model"]} if studio_options and "speech_model" in studio_options else {}
        if speech:
            from myzing.study.speech_models import local_path
            name = speech["speech_model"]
            local = local_path(name) if name != "skip" else None
            caps["studio_speech"] = {"model": name, "path": str(local) if local else None}
        resolved = checkpoints.step("reference-resolve", [ref_key, trim, "acquire-before-study-v2"], resolve)
        reference_terms = vocabulary_context(terms, metadata={"title": resolved.get("title") or ""})["terms"]
        ref_study = checkpoints.step("reference-study", [resolved["sha256"], caps, reference_terms, trim],
                                     lambda: _study(resolved["path"], root / "reference", fonts=caps["fonts"], max_seconds=60, **trim,
                                                    **({"vocabulary": reference_terms} if reference_terms else {}), **speech))
        # Keep the existing brief recommendation and reference contracts useful.
        from myzing.project.locking import project_lock
        with project_lock(root):
            manifest = projects.load_project(root)
            manifest.reference.study = {"state": "done", "breakdown_path": projects.stored_path(Path(ref_study["path"]), root),
                                        "sha256": projects.hash_file(Path(ref_study["path"])), "reference_sha256": resolved["sha256"]}
            projects._save(root, manifest)

        clips_studied, colors, audio_maps = {}, {}, {}
        for asset in manifest.assets:
            if asset.id in stills:
                continue  # Retain source inventory records, but never study stills as video.
            if asset.state != "ready" or not asset.probe or not any(s["codec_type"] == "video" for s in asset.probe.streams):
                summary["warnings"].append(f"Inventory {asset.id}: {asset.state}; {asset.error or 'not a usable video clip'}")
                continue
            source = resolve_path(asset.path, root)
            sha = projects.hash_file(source)
            # The source-map method keys the study: a changed fine pass restudies.
            clips_studied[asset.id] = checkpoints.step("study-" + asset.id, [sha, caps, context["cache_key"], "source-map-" + SOURCE_MAP_METHOD],
                                                      lambda source=source: _study(str(source), root, raw=True, **({"vocabulary": terms} if terms else {}), **speech))
            audio_maps[asset.id] = checkpoints.step("audio-" + asset.id, [sha, projects.hash_file(Path(clips_studied[asset.id]["path"])), caps, "audio-2.4"],
                                                    lambda a=asset.id: _audio(clips_studied[a], caps["audio"]))
            if caps["color"]:
                colors[asset.id] = checkpoints.step("color-" + asset.id, [sha, resolved["sha256"], caps, "sdr-matrix-v1"],
                                                    lambda source=source, a=asset.id: _color(ref_study["media"], source, root / "color" / a))
        if not caps["color"]:
            summary["warnings"].append('Color extra unavailable; footage is ungraded and color is unmeasured. Install "myzing[color]".')
        ref_audio = checkpoints.step("reference-audio", [resolved["sha256"], projects.hash_file(Path(ref_study["path"])), caps, "audio-2.4"],
                                     lambda: _audio(ref_study, caps["audio"]))
        recipe_result = checkpoints.step("style-recipe", [ref_study, ref_audio, colors, caps, "text-roles-v2-color2-samples"],
                                          lambda: _recipe(ref_study, ref_audio, colors, root / "recipe.json"))
        recipe = StyleRecipe.from_dict(read(recipe_result["path"]))
        summary["recipe"] = recipe_result["path"]
        summary["reference_text_roles"] = next((f.value for f in recipe.measured if f.name == "text_roles"), None)
        from myzing.director.api import plan_drafts
        def direct():
            result = plan_drafts(root, root / "recipe.json", root / "director", seed=seed, repair_asr=repair_asr,
                                 **({"studio_options": studio_options} if studio_options is not None else {}))
            return {**result, "outputs": [result["comparison_path"], *result["plans"].values()]}
        planned = checkpoints.step("director", [projects.hash_file(root / "recipe.json"), projects.hash_file(root / "brief.json"),
                                                 clips_studied, audio_maps, seed, [a.to_dict() for a in manifest.assets],
                                                 "continuity-v5-speechless-target", repair_asr, "aspect-stage-common-measurements-v15", caps["layout"],
                                                 "music1-review-v3", "reference-timing-constraints-v4", "in-band-before-distinctness-v2", *([studio_options, "studio-phone-groups-v1"] if studio_options is not None else [])], direct)
        summary["shortages"] = planned["summary"]["shortages"]
        if planned["summary"].get("target_length"):
            summary["target_length"] = planned["summary"]["target_length"]
        summary["warnings"].extend(planned["summary"].get("warnings", []))
        summary["source_asr"] = planned["summary"].get("source_asr", [])
        summary["director_comparison"] = planned["comparison_path"]
        # An alternative outside the reference timing is labeled on every row
        # and never counts as a pass; undelivered drafts are named, not copied.
        alternatives = planned.get("alternatives") or {}
        summary["alternatives"] = alternatives
        if planned.get("missing_drafts"):
            summary["missing_drafts"] = planned["missing_drafts"]
        if planned["plans"]:
            summary["requested"] = len(planned["plans"])
        plans_to_render = dict(planned["plans"])
        delivery_aspects = load_brief(root / "brief.json").aspects
        if delivery_aspects:
            from myzing.render.composition import _path
            from myzing.render.deliveries import delivery_plans, measure_sources
            plans_to_render = {}
            summary["requested"] = (len(planned["plans"]) or drafts) * len(delivery_aspects)
            shared = {}

            def measurements():
                # One subject/cut analysis per source over the union of the
                # trims every draft uses, shared by A/B/C (computed lazily so
                # resumed runs with cached deliveries decode nothing).
                if not shared:
                    sources, rate = {}, 30.0
                    for path in planned["plans"].values():
                        draft = Composition.from_dict(read(path))
                        rate = draft.fps.numerator / draft.fps.denominator
                        located = {a.id: _path(a.path, Path(path).parent, f"asset {a.id}") for a in draft.assets}
                        for clip in draft.clips:
                            sources.setdefault(located[clip.asset_id], []).append((clip.src_in, clip.src_out))
                    shared.update(measure_sources(sources, root / "aspect-plans" / "analysis", fps=rate))
                return shared

            all_plans = sorted(projects.hash_file(Path(p)) for p in planned["plans"].values())
            for label, plan_path in planned["plans"].items():
                def adapt(source=plan_path, label=label):
                    directory = root / "aspect-plans" / label
                    adapted, analysis = delivery_plans(Composition.from_dict(read(source)), delivery_aspects,
                                                       directory, base_dir=Path(source).parent,
                                                       measured=measurements(), continue_on_error=True)
                    outputs = {}
                    for aspect, plan in adapted.items():
                        name = label + "." + aspect.replace(":", "x")
                        path = directory / f"plan-{name}.json"
                        write(path, plan.to_dict())
                        outputs[name] = str(path)
                    evidence_path = directory / "analysis.json"
                    write(evidence_path, analysis)
                    return {"plans": outputs, "failures": analysis.get("failures", {}),
                            "outputs": [*outputs.values(), str(evidence_path)]}
                adapted = checkpoints.step("aspects-" + label, [projects.hash_file(Path(plan_path)), all_plans, delivery_aspects,
                                                               caps, "aspect-delivery-v8-common-measurements"], adapt)
                plans_to_render.update(adapted["plans"])
                for aspect,failure in adapted.get("failures", {}).items():
                    name = label + "." + aspect.replace(":", "x")
                    summary["drafts"][name] = failure
                    summary["failures"].append({**failure,"step":"aspects-"+name})
        for label, plan_path in plans_to_render.items():
            video = root / "drafts" / f"draft-{label}.mp4"
            row = {"status": "failed", "video": str(video)}
            if label.split(".")[0] in alternatives:
                row["alternative"] = {"outside_reference_timing": True, "label": ALTERNATIVE,
                                      "reason": alternatives[label.split(".")[0]]}
            summary["drafts"][label] = row
            try:
                prepared = checkpoints.step("plan-" + label, [projects.hash_file(Path(plan_path)), colors, caps, "clause-fit-v1", "aspect-safe-layout-v3"],
                    lambda p=plan_path, label=label: _prepare_plan(p, root / "drafts" / f"plan-{label}.json", colors, recipe, caps))
                summary["warnings"].extend(prepared["warnings"])
                row["plan"] = prepared["path"]
                plan = Composition.from_dict(read(prepared["path"]))
                video = root / "drafts" / f"draft-{label}.mp4"
                def render():
                    from myzing.render.composition import render_composition
                    result = render_composition(plan, video, base_dir=root / "drafts", work_dir=root / "render-work" / label)
                    outputs = [str(video)]
                    if result.audio_measurements is not None:
                        outputs.append(str(video.with_suffix(".music.json")))
                    if getattr(result, "delivery_measurements", None) is not None:
                        outputs.append(str(video.with_suffix(".encoding.json")))
                    return {"outputs": outputs, "warnings": list(result.warnings), "audio_measurements": result.audio_measurements,
                            "delivery_measurements": getattr(result, "delivery_measurements", None)}
                rendered_result = checkpoints.step("render-" + label, [projects.hash_file(Path(prepared["path"])), caps, "frame-clock-audio-headroom-v2", "music1-duck-envelope-v2", "numeric-unit-per-line-v3"], render)
                rendered_result = {**rendered_result, "warnings": evidence.user_warnings(rendered_result["warnings"])}
                summary["warnings"].extend(rendered_result["warnings"])
                def verify():
                    result = evidence.decode(video, plan)
                    path = video.with_suffix(".decode.json")
                    write(path, result)
                    return {"path": str(path), "outputs": [str(path)], "verification": result}
                verified = checkpoints.step("decode-" + label, projects.hash_file(video), verify)
                output_study = checkpoints.step("restudy-" + label, [projects.hash_file(video), caps,
                                                                    "confirmed-cut-verification-" + SOURCE_MAP_METHOD],
                                                lambda: _study(str(video), root / "verification", verification=True, **speech))
                timeline = video.with_suffix(".png")
                inspected = checkpoints.step("inspect-" + label, [projects.hash_file(video), output_study, "transcript-review-v1"],
                    lambda: _inspect(video, timeline, output_study, root / "verification", verified["verification"]["duration"]))
                summary["warnings"].extend(inspected["warnings"])
                def measure_color():
                    if not caps["color"]:
                        return {"outputs": [], "measurement": None}
                    from .picture import measure_output_color
                    measured = measure_output_color(video, plan)
                    path = video.with_suffix(".color.json")
                    write(path, measured)
                    return {"outputs": [str(path)], "measurement": measured}
                output_color = checkpoints.step("color-report-" + label, [projects.hash_file(video), projects.hash_file(Path(prepared["path"])), caps, "sharp-picture-color2-v2"], measure_color)
                def measure_skin():
                    # Each face against the same clip's ungraded source, before and
                    # after its own LUT. Never against the reference's people.
                    if not caps["color"]:
                        return {"outputs": [], "skin": None}
                    from .skin import measure_plan
                    measured = measure_plan(plan)
                    if measured is None:
                        return {"outputs": [], "skin": None}
                    path = video.with_suffix(".skin.json")
                    write(path, measured)
                    return {"outputs": [str(path)], "skin": measured}
                skin = checkpoints.step("skin-report-" + label, [projects.hash_file(Path(prepared["path"])), caps, "skin-preservation-picture-v2"], measure_skin)
                report_path = video.with_suffix(".match.json")
                def report():
                    result = evidence.report(recipe, Breakdown.from_dict(read(output_study["path"])),
                                             read(output_study["geometry"]) if output_study["geometry"] else {},
                                             output_color["measurement"], verified["verification"], plan, rendered_result.get("audio_measurements"),
                                             skin=skin["skin"])
                    result.update(recipe={"path": str(root / "recipe.json"), "sha256": projects.hash_file(root / "recipe.json")},
                                  plan={"path": prepared["path"], "sha256": projects.hash_file(Path(prepared["path"]))})
                    if rendered_result.get("delivery_measurements") is not None:
                        result["delivery_encoding"] = rendered_result["delivery_measurements"]
                    result["warnings"] = evidence.user_warnings([*result["warnings"], *rendered_result["warnings"], *inspected["warnings"]])
                    write(report_path, result)
                    return {"outputs": [str(report_path)], "dimensions": result["dimensions"],
                            "music": result["music"], "audio_measurements": result["audio_measurements"]}
                matched = checkpoints.step("report-" + label, [recipe.to_dict(), output_study, output_color, skin, verified, prepared, rendered_result, inspected, "honest-ranges-color2-v3"], report)
                row.update(status="ready", video=str(video), plan=prepared["path"], timeline=str(timeline),
                           report=str(report_path), sha256=projects.hash_file(video), dimensions=matched["dimensions"],
                           music=matched.get("music"), audio_measurements=matched.get("audio_measurements"))
                if rendered_result.get("delivery_measurements") is not None:
                    row["encoding"] = rendered_result["delivery_measurements"]
            except StepFailed as exc:
                from myzing.render.deliveries import delivery_failure, quarantine_failed_delivery
                row.update(delivery_failure(label.split(".")[-1].replace("x", ":"),exc))
                quarantine_failed_delivery(row)
    except (StepFailed, ValueError, OSError) as exc:
        summary["error"] = str(exc)
        if not checkpoints.failures():
            log = root / "logs" / "match.log"
            log.write_text(str(exc) + "\n", encoding="utf-8")
            summary["failures"].append({"step": "match", "error": str(exc), "log": str(log)})
    summary["failures"].extend(checkpoints.failures())
    summary["ready"] = sum(r["status"] == "ready" for r in summary["drafts"].values())
    summary["status"] = "ready" if summary["ready"] == summary["requested"] else "shortage" if summary["shortages"] else "partial" if summary["ready"] else "failed"
    for row in summary["drafts"].values():
        row["render_status"] = "render complete" if row["status"] == "ready" else row["status"]
        row["failed_style_dimensions"] = [k for k, v in row.get("dimensions", {}).items() if v["status"] == "miss"]
        row["unverified_style_dimensions"] = [k for k, v in row.get("dimensions", {}).items() if v["status"] == "approximate"]
        from .timing import dimension_notes
        row["not_applicable_style_dimensions"] = [k for k, v in row.get("dimensions", {}).items() if v["status"] == "not_applicable"]
        row["detector_disagreements"] = [k for k, v in row.get("dimensions", {}).items() if v["status"] == "detector_disagreement"]
        row["style_notes"] = dimension_notes(row.get("dimensions", {}))
        row["unverified_style_dimensions"].extend(row["detector_disagreements"])
        row["style_match"] = "failed" if row["failed_style_dimensions"] else "unverified"
        if row.get("alternative"):
            row["style_match"] = ALTERNATIVE
    summary["summary"] = f"{summary['ready']} of {summary['requested']} render complete"
    details = [f"{label}: " + (r["style_match"] if r.get("alternative") else f"style match {r['style_match']}") +
               (" (" + ", ".join(r["failed_style_dimensions"]) + ")" if r["failed_style_dimensions"] else "")
               for label, r in summary["drafts"].items()]
    if details:
        summary["summary"] += "; " + "; ".join(details)
    if summary.get("missing_drafts"):
        summary["summary"] += "; " + ", ".join(summary["missing_drafts"]["drafts"]) + " not delivered: no further distinct edit"
    summary["reused_steps"] = checkpoints.reused
    summary["seconds"] = round(time.monotonic() - started, 3)
    summary["warnings"] = evidence.user_warnings(summary["warnings"])
    summary["comparison"] = str(root / "comparison.md")
    write(root / "comparison.json", summary)
    (root / "comparison.md").write_text(evidence.markdown(summary), encoding="utf-8")
    checkpoints.finish(summary["status"])
    return summary
