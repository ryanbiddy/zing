"""Capture a checked cover set, then publish the images and their receipt together."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from myzing.factory.tools import node_sidecar, run, sidecar_env
from myzing.project.locking import project_lock
from myzing.render.hyperframes_publish import atomic_publish

from . import CoverError, data_path
from .contract import STYLES, displayed_highlight, load, messages
from .frame import inside
from .geometry import SIZES, placement

FONTS = {"Anton": ("Anton-Regular.ttf", "Anton-OFL.txt"),
         "Instrument Serif": ("InstrumentSerif-Regular.ttf", "InstrumentSerif-OFL.txt"),
         "Zing Caption": ("ZingCaption-800.ttf", "ZingCaption-OFL.txt"),
         "Plex": ("IBMPlexSans.ttf", "IBMPlexSans-OFL.txt")}


def selection(value, choices, option):
    if value == "all":
        return list(choices)
    names = [name.strip() for name in value.split(",")] if isinstance(value, str) else []
    if not names or any(name not in choices for name in names):
        raise CoverError(f"Choose {option} all or a comma-separated list from {', '.join(choices)}.")
    return list(dict.fromkeys(names))


def _publish(directory, scratch, files):
    target = directory / "out"
    if target.resolve() != target:
        raise CoverError("Use a local out directory inside the cover directory.")
    target.mkdir(exist_ok=True)
    backups = scratch / "previous"
    backups.mkdir()
    applied = []
    try:
        for name in files:
            dest = target / name
            if dest.is_symlink() or dest.exists() and not dest.is_file():
                raise CoverError(f"Move {dest} aside before rendering.")
            if dest.exists():
                shutil.copyfile(dest, backups / name)
            # Stage on the destination so Windows exports inherit the output
            # directory's permissions, rather than a private browser temp ACL.
            atomic_publish(scratch / "out" / name, dest, overwrite=True)
            applied.append(name)
    except (OSError, CoverError):
        for name in reversed(applied):
            backup = backups / name
            if backup.exists():
                atomic_publish(backup, target / name, overwrite=True)
            else:
                (target / name).unlink()
        raise


def render(directory: Path, *, style="all", size="all", scale=1, format="jpg") -> dict:
    directory = directory.expanduser().resolve()
    styles = selection(style, STYLES, "--style") if style != "all" else None
    sizes = selection(size, SIZES, "--size")
    if type(scale) is not int or scale not in (1, 2) or format not in ("jpg", "png"):
        raise CoverError("Use --scale 1 or 2 and --format jpg or png.")
    cover, report = load(directory, styles=styles, sizes=sizes, scale=scale)
    if not cover:
        raise CoverError(messages(report))
    spec = cover.to_dict()
    if cover.quote:
        spec["quote"]["highlight"] = displayed_highlight(cover.quote.text, cover.quote.highlight)
    styles = styles or [name for name in STYLES if name in spec]
    source = inside(directory, cover.frame.src)
    node, sidecar = node_sidecar()
    with tempfile.TemporaryDirectory(prefix=".cover-render-", dir=directory, ignore_cleanup_errors=True) as tmp:
        scratch = Path(tmp)
        output = scratch / "out"
        output.mkdir()
        frame = scratch / ("frame" + source.suffix.lower())
        shutil.copyfile(source, frame)
        spec["frame"]["src"] = frame.as_uri()
        items = [{"style": st, "size": sz, "w": SIZES[sz][0], "h": SIZES[sz][1],
                  "placement": placement(cover.frame, st, sz)} for st in styles for sz in sizes]
        job = {"spec": spec, "items": items, "sizes": sizes, "scale": scale, "format": format,
               "fonts": [file for file, _ in FONTS.values()]}
        job_file = scratch / "job.json"
        job_file.write_text(json.dumps(job), encoding="utf-8")
        try:
            result = run(node, data_path("render.cjs"), data_path("cover.html"), job_file, output,
                         env=sidecar_env(scratch / "browser"), cwd=sidecar, capture_output=True,
                         encoding="utf-8", errors="replace", timeout=90 + 20 * len(items))
        except subprocess.TimeoutExpired as exc:
            raise CoverError("Cover capture timed out. Check that the local browser can launch.") from exc
        except subprocess.CalledProcessError as exc:
            raise CoverError(exc.stderr.strip() or "Cover capture failed. Check your sidecar and browser.") from exc
        capture = json.loads(result.stdout)
        used = {"Plex"}  # Contact sheet labels.
        for item in capture["files"]:
            used.update(box["font"] for box in item["layout"]["boxes"])
        receipt = {"version": 1, "seed": cover.seed, "scale": scale, **capture,
                   "frame": {"file": cover.frame.src, "sha256": hashlib.sha256(frame.read_bytes()).hexdigest(),
                             **spec["source"], "url": cover.source.url, "timestamp": cover.source.timestamp},
                   "checks": {**report["checks"], "text_fit": "passed", "local_requests_only": "passed",
                              "wide_jpeg_bytes": "passed" if format == "jpg" and "wide" in sizes else "skipped"},
                   "warnings": report["warnings"],
                   "fonts": [{"file": FONTS[k][0], "license": "OFL-1.1", "license_file": FONTS[k][1]} for k in sorted(used)],
                   "note": "No image was generated or fetched. Each cover uses the supplied local frame."}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        filenames = [f["file"] for f in capture["files"]]
        publish = [*filenames, "sheet.jpg", "receipt.json"]
        if any(source == (directory / "out" / name).resolve() for name in publish):
            raise CoverError("Move the source frame outside the output filenames before rendering.")
        with project_lock(directory):
            _publish(directory, scratch, publish)
    out = directory / "out"
    return {"files": [str(out / name) for name in filenames], "sheet": str(out / "sheet.jpg"),
            "receipt": str(out / "receipt.json"), "warnings": report["warnings"]}
