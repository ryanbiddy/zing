"""Local style-card orchestration. The public function is also the Studio seam."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from myzing import storage
from myzing.project.api import hash_file
from myzing.urls import is_http_url
from .models import StyleCard
from .sections import build_sections


def _write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+"\n", encoding="utf-8")


def _resolve(source, work, *, allow_download):
    if source.startswith("uoink:"):
        from myzing.project.api import init_project
        from myzing.project.references import resolve_reference
        empty = work / "resolver-clips"
        empty.mkdir()
        project = work / "resolver"
        init_project(source, empty, project)
        result = resolve_reference(project)
        if result.state != "resolved":
            raise ValueError(result.reason)
        return Path(result.path)
    if is_http_url(source):
        if not allow_download:
            raise ValueError("URL download needs explicit consent: use --allow-download; models remain local.")
        from myzing.study.ingest import ingest
        with storage.use_workspace(work):
            return ingest(source).media_path
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise ValueError("Video not found; supply a local file, uoink:<id>, or URL with --allow-download.")
    return path


def _measure(source, out, *, transitions, allow_download=False):
    from myzing.study.api import study
    from myzing.style_recipe import build_style_recipe, MeasuredFact, Coverage, FontCandidate
    work = out / "evidence"
    work.mkdir(parents=True)
    media = _resolve(source, work, allow_download=allow_download)
    if out == media.parent or media.parent in out.parents:
        raise ValueError("Resolved media is in the output folder's source tree; choose --out outside the source folder.")
    sha = hash_file(media)
    model_workspace = storage.resolve_workspace()
    b = study(str(media), workspace=work, caption_geometry=True, fonts=True,
              detect_transitions=transitions, local_models_only=True, model_workspace=model_workspace)
    # Some local ASR runtimes return NumPy float64 timestamps. Load the saved
    # wire form, whose JSON numbers are ordinary Python values, before passing
    # it to the strict StyleRecipe contract. No timing value is repaired here.
    from myzing.schemas import Breakdown
    b = Breakdown.from_dict(json.loads(json.dumps(b.to_dict(), allow_nan=False)))
    with storage.use_workspace(work):
        folder = storage.breakdown_dir(storage.slug_for(str(media)))
        normalized = storage.resolve_relpath(storage.slug_for(str(media)), b.meta.media_path)
    geometry_path = folder / "caption-geometry.json"
    geometry = json.loads(geometry_path.read_text(encoding="utf-8")) if geometry_path.exists() else {}
    warnings = list(b.warnings)
    audio, color = None, None
    try:
        from myzing.audio.api import analyze
        audio = analyze(normalized, breakdown=b)
        _write(work / "audio-map.json", audio.to_dict())
    except Exception as exc:
        warnings.append(f"Audio map unavailable: {exc}; check myzing[audio] and the source stream.")
    try:
        from myzing.color.measure import measure_video
        measurement, _, _ = measure_video(normalized, shots=b.shots)
        color = measurement.to_dict()
        from .palette import lab_hex
        color["swatches"] = [lab_hex(row) for row in measurement.aggregate.palette]
        _write(work / "color.json", color)
    except Exception as exc:
        warnings.append(f"Color unavailable: {exc}; check myzing[color] and SDR input tags.")
    sections = build_sections(b.to_dict(), geometry, audio.to_dict() if audio else None, color)
    from myzing.study.text_roles import classify_text, caption_geometry
    from myzing.composition.models import FontAsset
    roles = classify_text(b, geometry)
    filtered = caption_geometry(geometry, roles)
    font_results = filtered.get("font_candidates") or {}
    available = {f["id"]: f for f in font_results.get("available_fonts", [])}
    font_choices = []
    for track in font_results.get("tracks", []):
        if track.get("candidates"):
            candidate = track["candidates"][0]
            asset = available.get(candidate["font_id"])
            if asset:
                font_choices.append(FontCandidate(asset["family"],
                    [f"Sampled similarity {candidate['score']:.3f}; substitute, original font unknown."],
                    FontAsset(asset["path"], asset["sha256"], asset["license"])))
    recipe = build_style_recipe(b, reference_sha256=sha, audio=audio, text_roles=roles, font_candidates=font_choices)
    stats = sections["captions"].facts.get("caption_geometry_summary")
    if stats:
        recipe.measured.append(MeasuredFact("caption_geometry.summary", stats, "normalized frame edges",
                                           Coverage(stats["samples"], None, "sampled tracks; gaps unknown"), None, recipe.reference))
        recipe.unknowns = [u for u in recipe.unknowns if u.subject != "caption_geometry"]
    if color:
        for name in ("luma_percentiles", "contrast", "saturation", "ab_mean", "palette"):
            recipe.measured.append(MeasuredFact("color."+name, color["aggregate"][name],
                                               "encoded Rec.709" if name == "luma_percentiles" else "CIELAB D65",
                                               Coverage(len(color["samples"]), None, "sparse requested seeks"), color["confidence"], recipe.reference,
                                               confidence_kind="heuristic"))
    recipe_path = out / "style-recipe.json"
    _write(recipe_path, recipe.to_dict())
    # These commands use the host shell's literal quoting, never interpolate them
    # into a subprocess. They are instructions for the user.
    def quote(value):
        import os
        return "'" + str(value).replace("'", "''" if os.name == "nt" else "'\"'\"'") + "'"
    ref = quote(str(media))
    commands = [f"zing match {ref} --clips ./clips --out ./project --answers '{{}}'",
                f"zing color match --reference {ref} --clip ./clips/input.mp4 --out ./look",
                "zing color apply --lut ./look/look.cube --in ./clips/input.mp4 --out ./graded.mp4"]
    summary = [(s.lines or [s.unknowns[0]])[0].replace("\n", " ") for s in sections.values()][:6]
    card = StyleCard(str(media), sha, b.meta.duration, sections, str(recipe_path), commands, summary, warnings,
                     evidence={"breakdown": str(folder / "breakdown.json"), "caption_geometry": str(geometry_path),
                               "audio_map": str(work / "audio-map.json") if audio else None,
                               "color": str(work / "color.json") if color else None,
                               "normalized_media": str(normalized), "offline_models": True,
                               "requested_source": source})
    if hash_file(media) != sha:
        raise ValueError("Source changed during measurement; retry after writes finish.")
    return card, normalized


def _explain(source, out_dir, *, transitions=True, offline=True, against=None, allow_download=False):
    try:
        if type(transitions) is not bool or type(offline) is not bool:
            raise ValueError("transitions and offline must be booleans")
        if not isinstance(source, (str, Path)) or not str(source).strip():
            raise ValueError("Supply a video source")
        source = str(source)
        # Validate consent and inputs before creating any outputs.
        for value in (source, str(against) if against else None):
            if value and is_http_url(value) and not allow_download:
                raise ValueError("URL download needs explicit consent: use --allow-download; models remain local.")
        inputs = []
        for value in (source, str(against) if against else None):
            if value and not is_http_url(value) and not value.startswith("uoink:"):
                source_path = Path(value).expanduser().resolve()
                if not source_path.is_file():
                    raise ValueError(f"Video not found: {value}")
                inputs.append(source_path.parent)
        def safe(folder):
            return not any(folder == parent or parent in folder.parents for parent in inputs)
        if out_dir is None:
            workspace = storage.resolve_workspace()
            candidates = [Path.cwd() / "zing-workspace" / "explain",
                          workspace.with_name(workspace.name + "-explain"),
                          Path.cwd().with_name(Path.cwd().name + "-explain")]
            base = next((p for p in candidates if safe(p)), None)
            if base is None:
                raise ValueError("Choose --out outside the source folders.")
            base.mkdir(parents=True, exist_ok=True)
            out = Path(tempfile.mkdtemp(prefix="card-", dir=base))
        else:
            out = Path(out_dir).expanduser().resolve()
        if not safe(out):
            raise ValueError("--out must be outside the source folder; choose a sibling project/workspace folder.")
        if out.exists() and any(out.iterdir()):
            raise ValueError("Output folder is not empty; choose a new --out folder to preserve existing cards.")
        out.mkdir(parents=True, exist_ok=True)
        card, media = _measure(source, out, transitions=transitions, allow_download=allow_download)
        if against:
            other_out = out / "against"
            other_out.mkdir()
            other, other_media = _measure(str(against), other_out, transitions=transitions, allow_download=allow_download)
            from .compare import compare_cards
            card.comparison = compare_cards(card, other)
            _publish(other, other_media, other_out)
        return _publish(card, media, out)
    except Exception as exc:
        from myzing.uoink_bridge import redact
        return {"ok": False, "error": redact(str(exc))}


def _publish(card, media, out):
    from .presentation import markdown, render_png
    card.evidence["preview"] = render_png(card, media, out / "card.png")
    _write(out / "card.json", card.to_dict())
    (out / "card.md").write_text(markdown(card), encoding="utf-8")
    return {"ok": True, "card_json": str(out / "card.json"), "card_md": str(out / "card.md"),
            "card_png": str(out / "card.png"), "summary": card.summary}


def explain_video(source, out_dir, *, transitions=True, offline=True) -> dict:
    """Write a style card. offline=False explicitly consents to URL acquisition.

    Models are ALWAYS local-only; provision them explicitly outside this call.
    Existing/nonempty outputs are refused. Failures use MCP's _err wire shape.
    """
    return _explain(source, out_dir, transitions=transitions, offline=offline, allow_download=not offline)
