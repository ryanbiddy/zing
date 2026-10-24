"""Local style-card orchestration. The public function is also the Studio seam."""

from __future__ import annotations

import json
import shutil
import tempfile
from fractions import Fraction
from pathlib import Path

from myzing import storage
from myzing.project.api import hash_file
from myzing.urls import is_http_url
from .models import StyleCard
from .sections import build_sections


def _write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+"\n", encoding="utf-8")


def probe_video(path) -> dict:
    """Display geometry and streams, or a ValueError a person can act on.

    Display size applies the rotation flag and pixel aspect ratio, which is what
    a viewer sees and what FFmpeg's default autorotation decodes.
    """
    from myzing.project.probe import parse_probe
    from myzing.study import proc
    name = Path(path).name
    if Path(path).is_file() and Path(path).stat().st_size == 0:
        raise ValueError(f"{name} is empty (0 bytes); supply a complete video file.")
    try:
        result = proc.run(["ffprobe", "-v", "error", "-protocol_whitelist", "file", "-show_streams", "-show_format",
                           "-of", "json", str(path)], timeout=60)
    except proc.MediaError as exc:
        raise ValueError(f"{exc} Install FFmpeg and run zing doctor.") from exc
    if result.returncode:
        raise ValueError(f"Could not read {name} as media; it may be damaged or not a video. FFmpeg said: {proc.tail(result.stderr, 2)}")
    try:
        probe = parse_probe(json.loads(result.stdout))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"Could not read {name} as media: {exc}") from exc
    if "no_video" in probe.flags:
        raise ValueError(f"{name} has no video stream; explain needs pictures (zing music checks audio-only files).")
    if probe.duration is None:
        raise ValueError(f"{name} has no readable duration; re-export or remux it with FFmpeg.")
    video = next(s for s in probe.streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic"))
    sar_text = str(video.get("sample_aspect_ratio") or "1:1")
    try:
        sar = Fraction(*map(int, sar_text.split(":")))
    except (ValueError, ZeroDivisionError, TypeError):
        sar = Fraction(1)
    if sar <= 0:
        sar = Fraction(1)
    width, height = round(probe.width * sar), probe.height
    rotation = (probe.rotation or 0) % 360
    if rotation % 180 == 90:
        width, height = height, width
    return {"stored_width": probe.width, "stored_height": probe.height, "display_width": width, "display_height": height,
            "rotation": rotation, "sample_aspect_ratio": sar_text if sar != 1 else "1:1",
            "has_audio": probe.has_audio, "duration": probe.duration}


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
        from myzing.study.ingest import _acquire_url_media
        with storage.use_workspace(work):
            slug = storage.slug_for(source)
            folder = storage.breakdown_dir(slug)
            folder.mkdir(parents=True, exist_ok=True)
            # Acquisition only. The duration/resolution budget is applied below
            # before ingest normalizes or analyzes any downloaded video.
            media, _, _ = _acquire_url_media(source, slug, folder, None, None, [], {})
            return media
    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise ValueError("Video not found; supply a local file, uoink:<id>, or URL with --allow-download.")
    return path


def _quote(value):
    """Literal shell quoting for display; these commands are never executed here."""
    import os
    return "'" + str(value).replace("'", "''" if os.name == "nt" else "'\"'\"'") + "'"


def get_look_commands(media, recipe_path):
    """The real commands, with this card's reference and recipe paths."""
    ref = _quote(media)
    return [f"zing match {ref} --clips ./my-clips --out ./my-edit --answers '{{}}'",
            f"zing plan drafts ./my-edit --recipe {_quote(recipe_path)} --out ./my-edit/drafts",
            f"zing color match --reference {ref} --clip ./my-clips/clip1.mp4 --out ./my-look",
            "zing color apply --lut ./my-look/look.cube --in ./my-clips/clip1.mp4 --out ./clip1-graded.mp4"]


def _first_line(exc):
    text = str(exc).strip()
    return (text.splitlines()[0] if text else type(exc).__name__)[:300]


def _measure(source, out, *, transitions, allow_download=False, **trim):
    from myzing.study.api import study
    from myzing.style_recipe import build_style_recipe, MeasuredFact, Coverage, FontCandidate
    work = out / "evidence"
    work.mkdir(parents=True)
    media = _resolve(source, work, allow_download=allow_download)
    if out == media.parent or media.parent in out.parents:
        raise ValueError("Resolved media is in the output folder's source tree; choose --out outside the source folder.")
    display = probe_video(media)
    sha = hash_file(media)
    model_workspace = storage.resolve_workspace()
    b = study(str(media), workspace=work, caption_geometry=True, fonts=True,
              detect_transitions=transitions, local_models_only=True, model_workspace=model_workspace,
              analysis_seconds=60, analysis_max_side=960, **trim)
    # Some local ASR runtimes return NumPy float64 timestamps. Load the saved
    # wire form, whose JSON numbers are ordinary Python values, before passing
    # it to the strict StyleRecipe contract. No timing value is repaired here.
    from myzing.schemas import Breakdown
    b = Breakdown.from_dict(json.loads(json.dumps(b.to_dict(), allow_nan=False)))
    from myzing.reference_range import slug as reference_slug
    with storage.use_workspace(work):
        folder = storage.breakdown_dir(reference_slug(str(media), **trim))
        normalized = storage.resolve_relpath(reference_slug(str(media), **trim), b.meta.media_path)
    display["source_duration"] = display["duration"]
    display["duration"] = b.meta.duration
    geometry_path = folder / "caption-geometry.json"
    geometry = json.loads(geometry_path.read_text(encoding="utf-8")) if geometry_path.exists() else {}
    warnings = list(b.warnings)
    if len(warnings) > 100:  # e.g. one font warning per OCR track on long sources
        warnings = warnings[:100] + [f"{len(b.warnings) - 100} more study warnings in the evidence breakdown.json."]
    audio, color, audio_error, color_error = None, None, None, None
    if display["has_audio"]:
        try:
            from myzing.audio.api import analyze
            audio = analyze(normalized, breakdown=b)
            _write(work / "audio-map.json", audio.to_dict())
        except ImportError as exc:
            audio_error = f"install myzing[audio] ({_first_line(exc)})."
        except Exception as exc:
            audio_error = _first_line(exc)
        if audio_error:
            warnings.append(f"Audio map unavailable: {audio_error}")
    try:
        from myzing.color.measure import measure_video
        measurement, _, _ = measure_video(normalized, shots=b.shots)
        color = measurement.to_dict()
        from .palette import lab_hex
        color["swatches"] = [lab_hex(row) for row in measurement.aggregate.palette]
        _write(work / "color.json", color)
    except ImportError as exc:
        color_error = f"install myzing[color] ({_first_line(exc)})."
    except Exception as exc:
        color_error = _first_line(exc)
    if color_error:
        warnings.append(f"Color unavailable: {color_error}")
    from .matte import detect_matte
    try:
        matte = detect_matte(normalized, b.meta.duration, display["display_width"], display["display_height"])
    except Exception as exc:  # an optional observation; never fail the card
        matte = {"version": 1, "status": "unknown", "reason": _first_line(exc)}
    sections = build_sections(b.to_dict(), geometry, audio.to_dict() if audio else None, color,
                              display=display, matte=matte, color_error=color_error, audio_error=audio_error)
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
    from .notices import viewer_notices
    summary = viewer_notices(sections, b.meta.duration, ocr_ran=bool(geometry.get("frames")))
    look_source = normalized if b.provenance.get("reference_range") else media
    card = StyleCard(str(media), sha, b.meta.duration, sections, str(recipe_path), get_look_commands(look_source, recipe_path),
                     summary, warnings,
                     evidence={"breakdown": str(folder / "breakdown.json"), "caption_geometry": str(geometry_path),
                               "audio_map": str(work / "audio-map.json") if audio else None,
                               "color": str(work / "color.json") if color else None,
                               "normalized_media": str(normalized), "offline_models": True,
                               "display": display, "requested_source": source, "reference_range": b.provenance.get("reference_range"),
                               "analysis_budget": {"max_seconds": 60, "max_side": 960}})
    if hash_file(media) != sha:
        raise ValueError("Source changed during measurement; retry after writes finish.")
    return card, normalized


# Written first and removed last: a folder holding it plus only Zing's own
# card files is an interrupted explain (crash, Ctrl-C, power loss) that the
# same --out may replace. Anything else in the folder blocks reuse.
PARTIAL_MARKER = ".zing-explain-incomplete"
OWNED_NAMES = {PARTIAL_MARKER, "evidence", "against", "style-recipe.json", "card.json", "card.md", "card.png"}


def _own_partial(folder):
    names = {p.name for p in folder.iterdir()}
    return PARTIAL_MARKER in names and names <= OWNED_NAMES


def _remove_partial(out, created, preexisting):
    """Remove only what this call wrote, so the same --out can be retried."""
    if created:
        shutil.rmtree(out, ignore_errors=True)
        return
    for child in list(out.iterdir()):
        if child.name in preexisting:
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)


def _explain(source, out_dir, *, transitions=True, offline=True, against=None, allow_download=False, ref_start=None, ref_end=None, reference_range=None):
    out, created, preexisting, armed = None, False, set(), False
    try:
        if type(transitions) is not bool or type(offline) is not bool:
            raise ValueError("transitions and offline must be booleans")
        if not isinstance(source, (str, Path)) or not str(source).strip():
            raise ValueError("Supply a video source")
        if out_dir is not None and (not isinstance(out_dir, (str, Path)) or not str(out_dir).strip()):
            raise ValueError("--out must be a nonempty folder path")
        if against is not None and (not isinstance(against, (str, Path)) or not str(against).strip()):
            raise ValueError("against must be a nonempty video path, uoink:<id> or URL")
        source = str(source)
        # Validate consent and inputs before creating any outputs.
        for value in (source, str(against) if against else None):
            if value and is_http_url(value) and not allow_download:
                raise ValueError("URL download needs explicit consent: use --allow-download; models remain local.")
        inputs, local_files = [], []
        for value in (source, str(against) if against else None):
            if value and not is_http_url(value) and not value.startswith("uoink:"):
                source_path = Path(value).expanduser().resolve()
                if not source_path.is_file():
                    raise ValueError(f"Video not found: {value}")
                local_files.append(source_path)
                inputs.append(source_path.parent)
        def safe(folder):
            return not any(folder == parent or parent in folder.parents for parent in inputs)
        if out_dir is not None:
            requested = Path(out_dir).expanduser().resolve()
            if not safe(requested):
                raise ValueError("--out must be outside the source folder; choose a sibling project/workspace folder.")
            if requested.exists() and (not requested.is_dir() or (any(requested.iterdir()) and not _own_partial(requested))):
                raise ValueError("Output folder is not empty; choose a new --out folder to preserve existing cards.")
        for path in local_files:
            # A file explain cannot read fails here, before any output exists
            # and before a long study of the other input.
            probe_video(path)
        if out_dir is None:
            workspace = storage.resolve_workspace()
            # Resolve first: a symlinked cwd or workspace must not slip past the
            # source-folder guard, which compares resolved paths.
            cwd, workspace = Path.cwd().resolve(), workspace.resolve()
            candidates = [cwd / "zing-workspace" / "explain", workspace.with_name(workspace.name + "-explain"),
                          cwd.with_name(cwd.name + "-explain")]
            base = next((p for p in candidates if safe(p)), None)
            if base is None:
                raise ValueError("Choose --out outside the source folders.")
            base.mkdir(parents=True, exist_ok=True)
            out = Path(tempfile.mkdtemp(prefix="card-", dir=base))
            created = True
        else:
            out = requested
            created = not out.exists()
            if not created and _own_partial(out):
                _remove_partial(out, False, set())  # every name is Zing's own (checked above)
            out.mkdir(parents=True, exist_ok=True)
        if not safe(out):
            raise ValueError("--out must be outside the source folder; choose a sibling project/workspace folder.")
        preexisting, armed = {p.name for p in out.iterdir()}, True
        _write(out / PARTIAL_MARKER, {"version": 1, "source": source,
                                      "note": "zing explain did not finish; rerun with the same --out to replace this folder."})
        from myzing.reference_range import parse
        parse(ref_start, ref_end, reference_range)
        trim = {k: v for k, v in dict(ref_start=ref_start, ref_end=ref_end, reference_range=reference_range).items() if v is not None}
        card, media = _measure(source, out, transitions=transitions, allow_download=allow_download, **trim)
        if against:
            other_out = out / "against"
            other_out.mkdir()
            other, other_media = _measure(str(against), other_out, transitions=transitions, allow_download=allow_download)
            from .compare import compare_cards
            card.comparison = compare_cards(card, other)
            _publish(other, other_media, other_out)
        result = _publish(card, media, out)
        (out / PARTIAL_MARKER).unlink(missing_ok=True)
        return result
    except BaseException as exc:
        from myzing.uoink_bridge import redact
        if armed and out is not None and out.is_dir():
            # Only after this call checked the folder was new, empty or its own partial.
            _remove_partial(out, created, preexisting)
        if not isinstance(exc, Exception):
            raise  # Ctrl-C and exits still stop the caller, after cleanup
        return {"ok": False, "error": redact(_first_line(exc) if not str(exc).strip() else str(exc))}


def _publish(card, media, out):
    from .presentation import markdown, render_png
    png = out / "card.png"
    try:
        card.evidence["preview"] = render_png(card, media, png)
    except ImportError as exc:
        # The PNG is optional (Pillow); the measured card is still complete.
        card.evidence["preview"] = None
        card.warnings.append(str(exc))
        png = None
    _write(out / "card.json", card.to_dict())
    (out / "card.md").write_text(markdown(card), encoding="utf-8")
    return {"ok": True, "card_json": str(out / "card.json"), "card_md": str(out / "card.md"),
            "card_png": str(png) if png else None, "summary": card.summary}


def explain_video(source, out_dir, *, transitions=True, offline=True, ref_start=None, ref_end=None, reference_range=None) -> dict:
    """Write a style card. offline=False explicitly consents to URL acquisition.

    Models are ALWAYS local-only; provision them explicitly outside this call.
    Existing/nonempty outputs are refused, and a failed call removes what it
    wrote. Failures use MCP's _err wire shape.
    """
    return _explain(source, out_dir, transitions=transitions, offline=offline, allow_download=not offline, ref_start=ref_start, ref_end=ref_end, reference_range=reference_range)
