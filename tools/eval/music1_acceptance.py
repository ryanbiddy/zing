"""Offline MUSIC1 replay with pinned tracks, copied V1 clips and cached studies.

No acquisition or ASR. --root holds tracks.json, studies/<clip>.json and clips/.
Source selection is authored to exercise music planning, not a semantic edit.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from myzing.audio import analyze
from myzing.brief.models import Brief
from myzing.director.asr_repair import repair_words
from myzing.director.continuity import clauses
from myzing.director.models import ClipStudy
from myzing.director.plans import make_plan, attach_report
from myzing.director.selection import Candidate, envelope
from myzing.inspect.timeline import inspect_timeline
from myzing.match.caption_fit import fit_captions
from myzing.match.evidence import decode
from myzing.music.advice import check_tracks
from myzing.project.api import hash_file
from myzing.project.models import Asset, Probe, ProjectManifest, Rational, Reference, SourceRecord
from myzing.render.composition import render_composition
from myzing.schemas import Breakdown
from myzing.style_recipe import build_style_recipe


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")


def asset(path, key, source=None):
    raw = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
                         check=True, capture_output=True, text=True, timeout=30)
    data = json.loads(raw.stdout)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), None)
    stat = path.stat()
    probe = Probe(float(data["format"]["duration"]), data["streams"], data["format"], video["width"] if video else None,
                  video["height"] if video else None, 0, Rational(30, 1) if video else None,
                  any(s["codec_type"] == "audio" for s in data["streams"]), "landscape" if video else None)
    return Asset(key, str(path), str(path), hash_file(path), stat.st_size, stat.st_mtime_ns,
                 SourceRecord(str(path)), probe)


def draw_levels(path, measurement, evidence, duration):
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new("RGB", (1400, 500), "#14171b")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(Path(__file__).resolve().parents[2] / "src/myzing/_data/fonts/IBMPlexSans.ttf"), 18)
    draw.text((60, 15), "MUSIC1 / isolated rendered music level (dBFS RMS; not LUFS)", font=font, fill="white")
    x = lambda t: 60 + t / duration * 1280
    y = lambda db: 400 - (max(-70, min(0, db)) + 70) / 70 * 330
    for a, b in evidence["speech_spans"]:
        draw.rectangle((x(a), 70, x(b), 400), fill="#233b35")
    for db in range(-70, 1, 10):
        draw.line((60, y(db), 1340, y(db)), fill="#3a4248")
        draw.text((5, y(db)-8), str(db), font=font, fill="white")
    points = [(x(p["time"]), y(p["music_rms_dbfs"])) for p in measurement["curve"]]
    if len(points) > 1:
        draw.line(points, fill="#88b8e8", width=3)
    for d in evidence["decisions"]:
        if d["kind"] in {"drop_alignment", "moment_alignment"}:
            draw.line((x(d["output_time"]), 70, x(d["output_time"]), 400), fill="#f588db", width=3)
            draw.text((x(d["output_time"])+4, 50), d["kind"], font=font, fill="#f588db")
    for t in range(int(duration)+1):
        draw.text((x(t), 410), str(t), font=font, fill="white")
    draw.text((60, 450), f"Green: speech spans | speech music {measurement['music_speech_lufs']} LUFS | gap music {measurement['music_gap_lufs']} LUFS", font=font, fill="white")
    image.save(path)


def visual_changes(path, fps=30):
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", "scale=32:32",
                          "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"],
                         check=True, capture_output=True, timeout=60).stdout
    pixels = np.frombuffer(raw, np.uint8).reshape(-1, 3072).astype(float)
    change = np.mean(abs(np.diff(pixels, axis=0)), axis=1) / 255
    return {"basis": "Mean absolute RGB change between adjacent decoded output frames at 32x32; includes motion and shot changes, no semantic interpretation",
            "fps": fps, "strongest_frame_changes": [
                {"time": float((i + 1) / fps), "score": float(change[i])}
                for i in np.argsort(change)[-8:][::-1]]}


def run(root):
    root = root.resolve()
    manifest = json.loads((Path(__file__).parent / "real/manifest.json").read_text(encoding="utf-8"))
    clip_records = {c["id"]: c for c in manifest["clips"]}
    names = ["korky", "tos-lab", "nasa-opening", "nasa-montage"]
    inputs, studies, derivatives = {}, {}, []
    for name in names:
        source = root / "clips" / Path(clip_records[name]["file"]).name
        assert hash_file(source) == clip_records[name]["sha256"]
        raw = json.loads((root / "studies" / (name + ".json")).read_text(encoding="utf-8"))
        b = Breakdown.from_dict(raw)
        assert Path(b.meta.source_url).name == source.name and abs(b.meta.duration - clip_records[name]["duration"]) < .05
        words, repair = repair_words(b.words, b.meta.duration)
        path = source
        if name.startswith("nasa"):
            path = root / "silent" / source.name
            path.parent.mkdir(exist_ok=True)
            command = ["ffmpeg", "-v", "error", "-y", "-i", str(source), "-map", "0:v:0", "-c:v", "copy", "-an", str(path)]
            subprocess.run(command, check=True, capture_output=True, timeout=60)
            derivatives.append({"source": str(source), "source_sha256": hash_file(source), "output": str(path), "sha256": hash_file(path), "command": command})
            words = []  # Stream copy explicitly removed source speech and score.
        inputs[name] = asset(path, name)
        studies[name] = ClipStudy(name, str(path), hash_file(path), b.meta.duration, "ready", words=words,
                                 shots=b.shots, asr_repair=repair)
    tracks = json.loads((root / "tracks.json").read_text(encoding="utf-8"))
    music_cache = {}
    for track in tracks:
        path = root / track["file"]
        assert hash_file(path) == track["sha256"]
        inputs[track["id"]] = asset(path, track["id"])
        music_cache[track["sha256"]] = analyze(path)
        write(root / (track["id"] + "-audio.json"), music_cache[track["sha256"]].to_dict())
    write(root / "derivatives.json", derivatives)
    results = {}
    cases = [
        ("montage", "Music-led NASA montage with a reveal at the strongest visual change", "vocals",
         [("nasa-opening", .5, 3.0), ("nasa-opening", 15.0, 16.5), ("nasa-montage", 1.0, 1.9),
          ("nasa-montage", 8.1, 9.35), ("nasa-montage", 15.05, 15.95), ("nasa-montage", 17.0, 17.55)]),
        ("talking", "Talking edit: calm music under complete speech clauses", "calm",
         [("tos-lab", 9.5, 12.7), ("korky", .1, 5.4), ("korky", 5.5, 9.95)]),
    ]
    for name, purpose, track_id, spans in cases:
        folder = root / name
        folder.mkdir(exist_ok=True)
        sequence = []
        for key, start, end in spans:
            study = studies[key]
            words = [w for w in study.words if w.start >= start and w.end <= end]
            # No selected source interval may bisect a rule-derived clause.
            assert all(start <= c.start and c.end <= end for c in clauses(study.words) if min(end,c.end)>max(start,c.start))
            sequence.append(Candidate(key, study.sha256, start, end, 0, len(words), words[0].start if words else None,
                                      " ".join(w.text for w in words), False, True))
        duration = sum(c.duration for c in sequence)
        brief = Brief(purpose=purpose, target_length_seconds=duration, aspect="16:9",
                      music={"source": "supplied files", "files": [t["id"] for t in tracks]})
        write(folder / "brief.json", brief.to_dict())
        source_recipe = Breakdown.from_dict(json.loads((root / "studies" / ("tos-lab.json" if name == "talking" else "nasa-montage.json")).read_text(encoding="utf-8")))
        recipe = build_style_recipe(source_recipe)
        project = ProjectManifest(Reference(str(root / "clips/nasa-montage.mp4"), "file", SourceRecord(str(root / "clips/nasa-montage.mp4"))),
                                  str(root / "clips"), SourceRecord(str(root / "clips")), list(inputs.values()))
        write(folder / "project.json", project.to_dict())
        plan, evidence = make_plan("A", sequence, list(studies.values()), recipe, folder, envelope(recipe), brief, project, folder, 17, {}, {}, music_cache)
        assert evidence["music"]["tracks"][0]["asset_id"] == track_id, "Real candidate ranking selected a different track; review the advice"
        plan = attach_report(plan, evidence)
        plan.width, plan.height = 640, 360
        fit_captions(plan, folder / "caption-fit")
        plan_path = folder / "plan.json"
        write(plan_path, plan.to_dict())
        write(folder / "planning.json", evidence)
        output = folder / "edit.mp4"
        rendered = render_composition(plan, output, work_dir=folder / "render-work")
        verified = decode(output, plan)
        write(folder / "visual-change.json", visual_changes(output))
        inspected = inspect_timeline(output, folder / "contact.png", start=0, end=min(duration, verified["duration"]) - 1e-6, edl=plan_path,
                                     frames=9, width=1800, overwrite=True)
        write(folder / "inspect.json", inspected.to_dict())
        draw_levels(folder / "music-levels.png", rendered.audio_measurements, evidence["music"], duration)
        advice = check_tracks([str(root / t["file"]) for t in tracks], brief=folder / "brief.json", pace=envelope(recipe).median_shot)
        write(folder / "music-check.json", advice)
        results[name] = {"render": verified, "continuity": evidence["continuity"], "music": evidence["music"],
                         "audio_measurements": rendered.audio_measurements, "inspection": str(folder / "contact.png"),
                         "authored_source_selection": spans, "scope": "Cached V1 studies and authored source ranges through MUSIC1 director/render; no fresh ASR or semantic coherence claim."}
        write(folder / "match.json", results[name])
        print(name, {k: v for k, v in rendered.audio_measurements.items() if k not in ("curve", "music_plan")}, flush=True)
    write(root / "results.json", results)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    run(parser.parse_args().root)
