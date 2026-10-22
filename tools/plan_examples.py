"""Offline P17 known-answer project; optional generated media uses no models.

Run: uv run python -m tools.plan_examples --out zing-workspace/p17-sample
Words are authored interval labels, not ASR or human speech measurements.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from myzing.brief.models import Brief
from myzing.director import plan_drafts
from myzing.project.api import hash_file
from myzing.project.models import Asset, Probe, ProjectManifest, Rational, Reference, SourceRecord
from myzing.schemas import Breakdown, CaptionEvent, Shot, VideoMeta, Word
from myzing.style_recipe import build_style_recipe


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def example_project(root: Path, *, media: bool = False):
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    assets, studies = [], []
    colors = ("red", "blue", "green", "yellow")
    sentences = (("Here", "is", "our", "hook"), ("Watch", "the", "blue", "detail"),
                 ("Keep", "this", "clear", "ending"), ("Another", "view", "shows", "why"))
    for index in range(3):
        path = root / "clips" / f"take-{index}.mp4"
        path.parent.mkdir(exist_ok=True)
        if media:
            command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
            for color in colors:
                command += ["-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=30:d=2"]
            command += ["-f", "lavfi", "-i", f"sine=frequency={330 + 110 * index}:duration=8:sample_rate=48000"]
            # Clip identity is visibly labeled; shot boundaries are exact at 2/4/6s.
            graph = ("[0:v][1:v][2:v][3:v]concat=n=4:v=1:a=0,"
                     f"drawtext=text='TAKE {index}':fontsize=28:fontcolor=white:x=10:y=10[v]")
            command += ["-filter_complex", graph, "-map", "[v]", "-map", "4:a", "-c:v", "libx264",
                        "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "8", str(path)]
            subprocess.run(command, check=True, capture_output=True, timeout=60)
        else:
            # Unit tests need only the inventory boundary, never a media decoder.
            path.write_bytes(f"P17 unique fixture {index}".encode())
        words = [Word(text, 2 * shot + .25 + .5 * n, 2 * shot + .5 + .5 * n, .95)
                 for shot, sentence in enumerate(sentences) for n, text in enumerate(sentence)]
        if index == 1:
            words = [w for w in words if w.start >= 2]
        sha = hash_file(path)
        b = Breakdown(VideoMeta(str(path), "file", duration=8, width=320, height=180, fps=30,
                                media_path=str(path)),
                      shots=[Shot(n, n * 2, n * 2 + 2, f"frame-{n}.jpg") for n in range(4)],
                      words=words,
                      provenance={"source_sha256": sha, "fixture": "authored words; no ASR accuracy claim",
                                  "raw_mode": {"keepers": [{"start": 0, "end": 8, "words": len(words),
                                                            "evidence": ["authored clean-take fixture"]}],
                                               "dead_air": [], "dead_air_count": 0}})
        study_path = root / "breakdowns" / f"take-{index}" / "breakdown.json"
        write_json(study_path, b.to_dict())
        studies.append(b)
        stat = path.stat()
        assets.append(Asset(f"take-{index}", path.relative_to(root).as_posix(), path.relative_to(root).as_posix(),
                            sha, stat.st_size, stat.st_mtime_ns, SourceRecord(path.relative_to(root).as_posix()),
                            Probe(8, [{"codec_type": "video"}, {"codec_type": "audio"}], {},
                                  320, 180, 0, Rational(30, 1), True, "landscape")))
    manifest = ProjectManifest(Reference("fixture:style", "uoink", SourceRecord("fixture:style")),
                               "clips", SourceRecord("clips"), assets)
    write_json(root / "project.json", manifest.to_dict())
    brief = Brief(purpose="Compare three ways into the same explanation", platform="YouTube", aspect="16:9",
                  target_length_seconds=6, must_keep=[{"clip": "take-0", "start": 4.25, "end": 5}],
                  forbidden=[{"clip": "take-1", "start": 6, "end": 8}])
    write_json(root / "brief.json", brief.to_dict())
    reference = Breakdown(VideoMeta("fixture:style", "file", duration=6, width=320, height=180, fps=30),
                          shots=[Shot(n, n * 2, n * 2 + 2) for n in range(3)],
                          captions=[CaptionEvent("two words", .25 + n, .75 + n, "lower", n % 2 == 0, 2)
                                    for n in range(6)])
    recipe = build_style_recipe(reference)
    write_json(root / "recipe.json", recipe.to_dict())
    return root, studies, recipe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    project, _, _ = example_project(args.out / "project", media=True)
    result = plan_drafts(project, project / "recipe.json", args.out / "plans", seed=17)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
