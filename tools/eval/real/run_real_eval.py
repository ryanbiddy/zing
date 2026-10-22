"""Replay the licensed, hash-pinned real-video audit. Network is opt-in.

Run from the checkout: uv run --frozen python tools/eval/real/run_real_eval.py
Use --download for missing media/Whisper assets, --fetch-models for OCR/YuNet,
and --fetch-fonts for the existing OFL/Apache library. No production patches.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inside(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes workspace: {name}")
    return path


def verified(path, digest):
    if not path.is_file():
        return False
    if sha256(path) != digest:
        raise ValueError(f"SHA-256 mismatch: {path}; do not relabel changed media")
    return True


def acquire(url, path, digest, allowed):
    if verified(path, digest):
        return
    if not allowed:
        raise ValueError(f"Missing {path}; use --download explicitly")
    if not url.startswith("https://"):
        raise ValueError("Asset downloads require HTTPS")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (Zing real-video evaluation)"}
        )
        with (
            urllib.request.urlopen(request, timeout=60) as response,
            partial.open("wb") as out,
        ):
            size = 0
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > 1_000_000_000:
                    raise ValueError(f"Asset exceeds 1 GB: {url}")
                out.write(block)
        verified(partial, digest)
        partial.replace(path)
    finally:
        partial.unlink(missing_ok=True)


class Runner:
    def __init__(self, root, output, env, resume=False):
        self.root, self.output, self.env, self.resume = root, output, env, resume
        self.records = []
        output.mkdir(parents=True, exist_ok=True)

    def command(self, name, args, *, timeout=1200):
        receipt = self.output / f"{name}.command.json"
        stdout, stderr = (
            self.output / f"{name}.stdout.txt",
            self.output / f"{name}.stderr.txt",
        )
        if self.resume and receipt.exists():
            result = read_json(receipt)
            if result["argv"] == args and result["returncode"] == 0:
                self.records.append(result)
                return result
        started = time.monotonic()
        print(f"Running {name}", flush=True)
        with (
            stdout.open("w", encoding="utf-8") as out,
            stderr.open("w", encoding="utf-8") as err,
        ):
            try:
                process = subprocess.run(
                    args,
                    cwd=REPO,
                    env=self.env,
                    stdout=out,
                    stderr=err,
                    timeout=timeout,
                    check=False,
                )
                code = process.returncode
            except subprocess.TimeoutExpired:
                code = 124
                err.write(f"\nEvaluation timeout after {timeout}s\n")
        result = {
            "name": name,
            "argv": args,
            "returncode": code,
            "seconds": round(time.monotonic() - started, 3),
            "stdout": str(stdout),
            "stderr": str(stderr),
        }
        write_json(receipt, result)
        self.records.append(result)
        return result

    def zing(self, name, *args):
        return self.command(name, [sys.executable, "-m", "myzing.cli", *map(str, args)])


def prepare(manifest, root, download):
    for source in manifest["sources"]:
        acquire(
            source["url"],
            inside(root, "sources/" + source["file"]),
            source["sha256"],
            download,
        )
    for asset in manifest["whisper"]["files"]:
        acquire(
            asset["url"],
            inside(root, manifest["whisper"]["path"] + "/" + asset["file"]),
            asset["sha256"],
            download,
        )
    for clip in manifest["clips"]:
        target = inside(root, clip["file"])
        if verified(target, clip["sha256"]):
            continue
        source = next(s for s in manifest["sources"] if s["id"] == clip["source_id"])
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(inside(root, "sources/" + source["file"])),
                *clip["derive_args"],
                str(target),
            ],
            check=True,
        )
        if not verified(target, clip["sha256"]):
            raise ValueError(f"Failed to derive {target}")


def verify_runtime_assets(manifest, home):
    """A two-font fallback is a different experiment, so fail visibly."""
    from myzing.fonts.library import inventory

    assets = manifest["runtime_assets"]
    verified(REPO / assets["font_library_manifest"], assets["font_library_sha256"])
    fonts = {row["id"]: row for row in inventory(home)}
    for expected in assets["fonts"]:
        row = fonts.get(expected["id"], {})
        if not row.get("available") or row.get("sha256") != expected["sha256"]:
            raise ValueError(f"Missing pinned font {expected['id']}; use --fetch-fonts")
    for asset in assets["models"]:
        if not verified(inside(home, asset["path"]), asset["sha256"]):
            raise ValueError(
                f"Missing pinned model {asset['path']}; use --fetch-models"
            )


def evaluate(manifest, root, runner, home, labels):
    clips = {c["id"]: c for c in manifest["clips"]}
    results = {}
    for id, clip in clips.items():
        media = inside(root, clip["file"])
        record = runner.zing(
            id + "-study",
            "study",
            media,
            "--workspace",
            home,
            "--transitions",
            "--caption-geometry",
            "--fonts",
            "--json",
        )
        item = {"study": record, "media": str(media), "media_sha256": clip["sha256"]}
        if record["returncode"] == 0:
            # The CLI emits JSON only in --json mode; failure to parse is an error.
            breakdown = read_json(record["stdout"])
            item["breakdown"] = breakdown
            # Paths are obtained from the stored output, never a guessed slug.
            candidates = [
                p
                for p in (home / "breakdowns").glob("*/breakdown.json")
                if read_json(p).get("meta", {}).get("source_url") == str(media)
            ]
            if len(candidates) == 1:
                folder = candidates[0].parent
                item["folder"] = str(folder)
                if (folder / "caption-geometry.json").exists():
                    item["geometry"] = read_json(folder / "caption-geometry.json")
            else:
                item["lookup_error"] = (
                    f"Expected one saved breakdown, got {len(candidates)}"
                )
        audio_args = ["audio", "analyze", media, "--json"]
        if item.get("folder"):
            audio_args += [
                "--breakdown",
                Path(item["folder"]).name,
                "--workspace",
                home,
            ]
        audio = runner.zing(id + "-audio", *audio_args)
        item["audio_command"] = audio
        if audio["returncode"] == 0:
            item["audio"] = read_json(audio["stdout"])
        # A planning probe, not an assertion these new captions existed in the source.
        events = [
            {
                "id": "probe",
                "start": 0,
                "end": min(10, clip["duration"]),
                "width": 0.65,
                "height": 0.12,
                "preferred_anchor": "lower-third",
            }
        ]
        event_path = runner.output / f"{id}-events.json"
        write_json(event_path, {"version": 1, "events": events})
        layout_path = runner.output / f"{id}-layout.json"
        layout = runner.zing(
            id + "-layout",
            "layout",
            "captions",
            "--video",
            media,
            "--events",
            event_path,
            "--out",
            layout_path,
            "--workspace",
            home,
        )
        item["layout_command"] = layout
        if layout["returncode"] == 0:
            item["layout"] = read_json(layout_path)
        runner.zing(
            id + "-timeline",
            "inspect",
            "timeline",
            media,
            "--start",
            0,
            "--end",
            clip["duration"],
            "--frames",
            15,
            "--out",
            runner.output / f"{id}-timeline.png",
            "--overwrite",
        )
        results[id] = item
        write_json(
            runner.output / "observations.json", {"version": 1, "clips": results}
        )
    colors = []
    for reference, target in manifest["color_pairs"]:
        name = f"color-{reference}-{target}"
        # The product requires a new folder. Each fresh evaluation gets its own output.
        result = runner.zing(
            name,
            "color",
            "match",
            "--reference",
            inside(root, clips[reference]["file"]),
            "--clip",
            inside(root, clips[target]["file"]),
            "--out",
            runner.output / name,
            "--json",
        )
        entry = {
            "reference": reference,
            "clip": target,
            "command": result,
            "result": read_json(result["stdout"])
            if result["returncode"] == 0
            else None,
        }
        if result["returncode"] == 0:
            rendered = runner.output / name / "matched.mp4"
            applied = runner.zing(
                name + "-apply",
                "color",
                "apply",
                "--lut",
                runner.output / name / "look.cube",
                "--in",
                inside(root, clips[target]["file"]),
                "--out",
                rendered,
                "--json",
            )
            entry["apply_command"] = applied
            if applied["returncode"] == 0:
                entry["visual_check"] = color_evidence(
                    inside(root, clips[reference]["file"]),
                    inside(root, clips[target]["file"]),
                    rendered,
                    runner.output / name,
                    reference == target,
                    runner.env,
                )
        colors.append(entry)
    match = manifest["match"]
    runner.zing(
        "match",
        "match",
        "--reference",
        inside(root, clips[match["reference"]]["file"]),
        "--clips",
        *[inside(root, clips[id]["file"]) for id in match["clips"]],
    )
    observations = {"version": 1, "clips": results, "colors": colors}
    write_json(runner.output / "observations.json", observations)
    caption_evidence(manifest, labels, observations, root, runner.output, runner.env)
    return observations


def caption_evidence(manifest, labels, observations, root, output, env):
    import io

    from PIL import Image, ImageDraw

    for clip in manifest["clips"]:
        id = clip["id"]
        truth = labels["clips"][id]
        frames = truth.get("caption_frames", []) + truth.get("diagnostic_frames", [])
        samples = observations["clips"][id].get("geometry", {}).get("frames", [])
        for frame in frames:
            t = frame["t"]
            png = subprocess.check_output(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-i",
                    str(inside(root, clip["file"])),
                    "-ss",
                    str(t),
                    "-frames:v",
                    "1",
                    "-f",
                    "image2pipe",
                    "-vcodec",
                    "png",
                    "pipe:1",
                ],
                env=env,
            )
            im = Image.open(io.BytesIO(png)).convert("RGB")
            drawing = ImageDraw.Draw(im)

            def box(bounds, color, drawing=drawing, width=im.width, height=im.height):
                drawing.rectangle(
                    [
                        bounds[0] * width,
                        bounds[1] * height,
                        bounds[2] * width,
                        bounds[3] * height,
                    ],
                    outline=color,
                    width=2,
                )

            for line in frame.get("lines", []):
                box(line["box"], "lime")
            sample = min(samples, key=lambda s: abs(s["t"] - t)) if samples else None
            if sample and abs(sample["t"] - t) <= 0.01:
                for detection in sample["detections"]:
                    box(
                        detection["box"],
                        "magenta"
                        if (detection.get("confidence") or 0) >= 0.75
                        else "yellow",
                    )
            canvas = Image.new("RGB", (max(im.width, 500), im.height + 28), "black")
            canvas.paste(im, (0, 28))
            ImageDraw.Draw(canvas).text(
                (4, 4),
                "Green: label | Magenta: OCR >= .75 | Yellow: below gate",
                fill="white",
            )
            canvas.save(output / f"{id}-captions-{t}.png")


def color_evidence(reference, source, rendered, folder, identity, env):
    """Identity pixel error is valid; unrelated scenes get previews only."""
    import io

    from PIL import Image, ImageDraw

    images = []
    for label, video in [
        ("reference", reference),
        ("input", source),
        ("matched", rendered),
    ]:
        png = subprocess.check_output(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(video),
                "-ss",
                "6",
                "-frames:v",
                "1",
                "-f",
                "image2pipe",
                "-vcodec",
                "png",
                "pipe:1",
            ],
            env=env,
        )
        image = Image.open(io.BytesIO(png)).convert("RGB")
        image.save(folder / f"{label}-at-6.png")
        images.append((label, image))
    sheet = Image.new("RGB", (900, 240), "#202020")
    draw = ImageDraw.Draw(sheet)
    for i, (label, image) in enumerate(images):
        thumbnail = image.copy()
        thumbnail.thumbnail((300, 210))
        sheet.paste(thumbnail, (i * 300, 25))
        draw.text((i * 300 + 4, 4), label, fill="white")
    sheet.save(folder / "comparison.png")
    result = {
        "preview": str(folder / "comparison.png"),
        "time": 6,
        "identity": identity,
    }
    if identity:
        a, b = images[1][1], images[2][1]
        if a.size != b.size:
            raise ValueError("Identity color render changed dimensions")
        errors = sorted(abs(x - y) for x, y in zip(a.tobytes(), b.tobytes()))
        result.update(
            mean_absolute_rgb8_error=sum(errors) / len(errors),
            p99_absolute_rgb8_error=errors[int(0.99 * (len(errors) - 1))],
            max_absolute_rgb8_error=errors[-1],
        )
    return result


def review_evidence(manifest, labels, root, runner):
    """Recreate the exact-frame grids and unannotated native PNG label evidence."""
    review = root / "review"
    review.mkdir(exist_ok=True)
    for clip in manifest["clips"]:
        id = clip["id"]
        truth = labels["clips"][id]
        media = inside(root, clip["file"])
        page = 0
        for a, b in truth.get("transition_windows", []):
            first, last = round(a * clip["fps"]), round(b * clip["fps"])
            for start in range(first, last, 80):
                end = min(start + 79, last - 1)
                filters = (
                    f"select='between(n,{start},{end})',scale=144:-1,"
                    "drawtext=fontfile=src/myzing/_data/fonts/Anton-Regular.ttf:"
                    "text='%{pts\\:flt}':x=2:y=2:fontsize=12:fontcolor=yellow:box=1:boxcolor=black,tile=8x10"
                )
                runner.command(
                    f"{id}-frames-{page}",
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-y",
                        "-i",
                        str(media),
                        "-vf",
                        filters,
                        "-frames:v",
                        "1",
                        str(review / f"{id}-frames-{page}.png"),
                    ],
                )
                page += 1
        times = {
            f["t"]
            for key in ("face_frames", "caption_frames", "diagnostic_frames")
            for f in truth.get(key, [])
        }
        for t in sorted(times):
            runner.command(
                f"{id}-at-{t}",
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(media),
                    "-ss",
                    str(t),
                    "-frames:v",
                    "1",
                    str(review / f"{id}-at-{t}.png"),
                ],
            )
        for n, event in enumerate(truth.get("transition_events", [])):
            center = (event["start_seconds"] + event["end_seconds"]) / 2
            radius = max(
                3 / clip["fps"],
                (event["end_seconds"] - event["start_seconds"]) / 2 + 0.15,
            )
            runner.zing(
                f"{id}-boundary-{n}",
                "inspect",
                "timeline",
                media,
                "--around",
                center,
                "--radius",
                radius,
                "--frames",
                7,
                "--out",
                review / f"{id}-boundary-{n}.png",
                "--overwrite",
            )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=HERE / "manifest.json")
    parser.add_argument("--labels", type=Path, default=HERE / "labels.json")
    parser.add_argument("--root", type=Path, default=REPO / "zing-workspace/real-eval")
    parser.add_argument(
        "--out",
        type=Path,
        help="new output directory; defaults to a timestamped run under root",
    )
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--fetch-models", action="store_true")
    parser.add_argument("--fetch-fonts", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--score-only", action="store_true")
    parser.add_argument(
        "--review-only",
        action="store_true",
        help="recreate frame grids, native PNGs and boundary timeline PNGs from labels",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="reuse successful command receipts in --out",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    output = (args.out or root / "runs" / time.strftime("%Y%m%d-%H%M%S")).resolve()
    if (
        output.exists()
        and any(output.iterdir())
        and not (args.resume or args.score_only)
    ):
        parser.error("--out must be empty, or explicitly use --resume / --score-only")
    manifest = read_json(args.manifest)
    if manifest.get("version") != 1:
        parser.error("unsupported manifest version")
    env = os.environ.copy()
    home = Path(env.get("ZING_HOME", root / "home")).resolve()
    env.update(
        ZING_HOME=str(home),
        HF_HUB_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",
        ZING_WHISPER_MODEL=str(root / manifest["whisper"]["path"]),
        PYTHONIOENCODING="utf-8",
    )
    runner = Runner(root, output, env, args.resume)
    try:
        prepare(manifest, root, args.download)
        if args.fetch_models:
            runner.command(
                "fetch-ocr",
                [sys.executable, "-m", "myzing.study.caption_models", "--fetch"],
            )
            runner.zing("fetch-yunet", "layout", "fetch-model", "--workspace", home)
        if args.fetch_fonts:
            runner.zing("fetch-fonts", "fonts", "fetch", "--all", "--workspace", home)
        if args.prepare_only:
            print("All source, clip and Whisper hashes verified.")
            return 0
        labels = (
            read_json(args.labels)
            if args.labels.exists()
            else {"version": 1, "clips": {}}
        )
        if args.review_only:
            review_evidence(manifest, labels, root, runner)
            write_json(output / "commands.json", runner.records)
            return 1 if any(r["returncode"] for r in runner.records) else 0
        if args.score_only:
            observations = read_json(output / "observations.json")
        else:
            verify_runtime_assets(manifest, home)
            observations = evaluate(manifest, root, runner, home, labels)
            write_json(output / "commands.json", runner.records)
            versions = {
                "python": sys.version,
                "commit": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
                ).strip(),
                "ffmpeg": subprocess.check_output(
                    ["ffmpeg", "-version"], text=True
                ).splitlines()[0],
                "manifest_sha256": sha256(args.manifest),
                "labels_sha256": sha256(args.labels) if args.labels.exists() else None,
                "whisper_path": env["ZING_WHISPER_MODEL"],
                "seams": [],
                "network_at_study": "HF offline; pinned OCR/YuNet paths; local fonts",
            }
            write_json(output / "provenance.json", versions)
        if __package__:
            from .scoring import score
        else:
            from scoring import score
        metrics = score(manifest, labels, observations)
        write_json(output / "metrics.json", metrics)
        write_json(
            output / "scoring-provenance.json",
            {
                "version": 1,
                "manifest_sha256": sha256(args.manifest),
                "labels_sha256": sha256(args.labels),
                "observations_sha256": sha256(output / "observations.json"),
                "scoring_sha256": sha256(HERE / "scoring.py"),
            },
        )
        print(f"Metrics: {output / 'metrics.json'}")
        # Command failures remain failures even when anticipated by the report.
        commands = (
            runner.records
            if not args.score_only
            else read_json(output / "commands.json")
        )
        return 1 if any(r["returncode"] for r in commands) else 0
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"real evaluation: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
