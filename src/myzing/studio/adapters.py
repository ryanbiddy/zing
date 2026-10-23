"""Small integration seams: existing producers own measurement and rendering."""

from __future__ import annotations

from pathlib import Path

from .models import read_json, write_json


def validate_options(value):
    if not isinstance(value, dict) or set(value) - {"captions", "music", "tone", "no_reference"}:
        raise ValueError("studio_options must contain only captions, music, tone and no_reference")
    if "captions" in value and value["captions"] not in {"none", "phone"}:
        raise ValueError("studio_options.captions: choose none or phone")
    if "no_reference" in value and type(value["no_reference"]) is not bool:
        raise ValueError("studio_options.no_reference must be boolean")
    if value.get("no_reference") and value.get("tone") not in {"natural", "calm", "energetic"}:
        raise ValueError("studio_options.tone: choose natural, calm or energetic")
    if "music" in value:
        from .flow import normalize
        normalize("music", value["music"])


def explain_video(source, out_dir, *, progress=None, fallback=True):
    """EXPLAIN integration point. Only a missing module invokes the fallback."""
    try:
        from myzing.explain.api import explain_video as explain
    except ImportError:
        if not fallback:
            return None
        from myzing import storage
        from myzing.study.api import study
        from myzing.inspect.timeline import inspect_timeline

        root = Path(out_dir)
        note = "Style-card module unavailable; using existing study + inspect outputs."
        if progress:
            progress(note)
        b = study(source, workspace=root, local_models_only=True, detect_transitions=True,
                  caption_geometry=True, model_workspace=storage.resolve_workspace(), phase_callback=progress)
        with storage.use_workspace(root):
            folder = storage.breakdown_dir(storage.slug_for(source))
        png = root / "timeline.png"
        warnings = [note, *b.warnings,
                    "Fallback has no dedicated color-look or music-arrangement card; those details remain unmeasured. Original font, LUT and presets remain unknown."]
        try:
            inspected = inspect_timeline(source, str(png), start=0, end=min(b.meta.duration, 30))
            warnings.extend(inspected.warnings)
        except (ValueError, OSError, RuntimeError, ImportError) as exc:
            warnings.append(f"Timeline inspection unavailable: {exc}")
        return {"ok": True, "fallback": True, "card_json": str(folder / "breakdown.json"),
                "card_md": str(folder / "breakdown.md"), "card_png": str(png) if png.is_file() else None,
                "summary": [note, f"{len(b.shots)} observed shots; {len(b.words)} transcript words; {len(b.captions)} sampled text events."],
                "warnings": warnings}
    if progress:
        progress("Reading the video and making its style card...")
    return explain(source, str(out_dir), transitions=True, offline=True)


def register_music(root, tracks):
    """Inventory explicitly supplied audio with the existing probe/hash contract.

    The folder scanner is video-oriented. Studio owns these additional entries;
    each new run rescans and re-verifies them. No source file is copied or edited.
    """
    from myzing.project import api
    from myzing.project.models import Asset, SourceRecord
    from myzing.project.probe import probe_file
    from myzing.project.locking import project_lock
    import hashlib

    if not isinstance(tracks, list):
        return
    with project_lock(root):
        manifest = api.load_project(root)
        for track in tracks:
            path = Path(track).resolve()
            stored = api.stored_path(path, root)
            before = path.stat()
            digest = api.hash_file(path)
            probe = probe_file(path)
            if not probe.has_audio or not probe.duration:
                raise ValueError(f"Supplied music has no measured audio/duration: {path}")
            stat = path.stat()
            if (before.st_size, before.st_mtime_ns) != (stat.st_size, stat.st_mtime_ns):
                raise ValueError(f"Supplied music changed during inventory: {path}; retry after writes finish.")
            existing = next((a for a in manifest.assets if api.resolve_path(a.path, root) == path), None)
            if existing:
                existing.probe, existing.sha256 = probe, digest
                existing.state, existing.error = "ready", None
                existing.size, existing.mtime_ns = stat.st_size, stat.st_mtime_ns
            else:
                manifest.assets.append(Asset(
                    id="studio_music_" + hashlib.sha256(stored.encode()).hexdigest()[:24],
                    path=stored, original_path=stored, sha256=digest, size=stat.st_size,
                    mtime_ns=stat.st_mtime_ns, source=SourceRecord(stored, "user", "user-supplied; rights unverified"),
                    probe=probe, state="ready"))
        api._save(root, manifest)


def style_envelope(style, studio_options):
    """Chosen search targets are preferences, never fake MeasuredFacts."""
    from dataclasses import replace

    tone = studio_options.get("tone")
    if not studio_options.get("no_reference"):
        return style
    pace = {"calm": 4.0, "natural": 2.0, "energetic": 1.0}[tone]
    return replace(style, median_shot=pace, first_cut=None,
                   basis={**style.basis, "pacing": f"Studio brief preference: {tone}, {pace:g}s search target; not a measurement"})


def load_edit(source):
    from myzing.composition.compatibility import load_composition
    from myzing.composition import Composition, AssetRef, CompositionClip
    from myzing.project.api import hash_file
    from myzing.project.probe import probe_file

    path = Path(source)
    if path.suffix.lower() == ".json":
        return load_composition(read_json(path))
    probe = probe_file(path)
    if not probe.duration or not probe.width or not probe.height:
        raise ValueError("Existing edit needs a video stream and a known duration.")
    return Composition(assets=[AssetRef("edit", str(path), hash_file(path), probe.duration)],
                       clips=[CompositionClip(id="edit", asset_id="edit", src=str(path), src_in=0,
                                              src_out=probe.duration, timeline_start=0)],
                       width=probe.width, height=probe.height,
                       warnings=["Flattened input: existing captions, color, music and cuts remain baked in."])


def deliver(source, output, aspects, *, delivery_options=None):
    from myzing.render.deliveries import render_deliveries
    from myzing.composition import Composition
    from myzing.match.evidence import decode

    plan = load_edit(source)
    if delivery_options:
        from myzing.delivery_options import apply_plan
        apply_plan(plan, delivery_options)
    fallback = None
    try:
        result = render_deliveries(plan, output, aspects=aspects,
                                   base_dir=Path(source).parent, inputs=(Path(source),))
    except ValueError as exc:
        # A measured V1 re-delivery exposed a rejected auto-motion candidate.
        # Keep the renderer's bound intact and retry its full-picture policy.
        # This narrow fallback belongs to studio; ordinary render is unchanged.
        if str(exc) != "reframe keyframes exceed max_velocity":
            raise
        fallback = "Auto framing could not satisfy its crop-motion bound; studio used full-picture blurfill for this delivery."
        result = render_deliveries(plan, output, aspects=aspects, framing="blurfill",
                                   base_dir=Path(source).parent, inputs=(Path(source),))
        result["warnings"] = [fallback, *result.get("warnings", [])]
        report = read_json(result["report"])
        report["warnings"] = [fallback, *report.get("warnings", [])]
        write_json(result["report"], report)
    for row in result["deliveries"].values():
        receipt = decode(Path(row["video"]), Composition.from_dict(read_json(row["plan"])))
        receipt_path = Path(row["video"]).with_suffix(".decode.json")
        write_json(receipt_path, receipt)
        row["decode"] = str(receipt_path)
    return result
