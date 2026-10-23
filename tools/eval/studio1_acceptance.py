"""Local creator transcripts against SHA-pinned licensed V1 clips. No downloads.

Run prepare, a, f, c in order. Originals are read only; outputs stay ignored.
The elapsed time includes the interview's read-only probes. ASR is real/local.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(out, source):
    manifest = json.loads((ROOT / "tools/eval/real/manifest.json").read_text(encoding="utf-8"))
    verified = out / "verified"
    verified.mkdir(parents=True, exist_ok=True)
    receipts = []
    for item in manifest["clips"]:
        original = source / Path(item["file"]).name
        actual = digest(original)
        if actual != item["sha256"]:
            raise ValueError(f"V1 media hash mismatch: {original}")
        target = verified / original.name
        if not target.exists():
            shutil.copyfile(original, target)
        if digest(target) != actual:
            raise ValueError(f"Copied media hash mismatch: {target}")
        receipts.append({"source": str(original), "copy": str(target), "sha256": actual,
                         "license": item["license"], "attribution": item["attribution"]})
    clips = out / "clips"
    clips.mkdir(exist_ok=True)
    for name in ("korky.mp4", "tos-lab.mp4", "nasa-opening.mp4"):
        target = clips / name
        if not target.exists():
            shutil.copyfile(verified / name, target)
    # Reuse only pinned local assets; never fetch a missing asset.
    model_from = source.parent / manifest["whisper"]["path"]
    model_to = ROOT / "zing-workspace/models/tiny.en"
    model_to.mkdir(parents=True, exist_ok=True)
    for item in manifest["whisper"]["files"]:
        original = model_from / item["file"]
        if digest(original) != item["sha256"]:
            raise ValueError(f"Cached model hash mismatch: {original}")
        shutil.copyfile(original, model_to / item["file"])
    peer_workspace = source.parent.parent
    for item in manifest["runtime_assets"]["models"]:
        original = peer_workspace / "home" / item["path"]
        if not original.is_file():
            continue
        if digest(original) != item["sha256"]:
            raise ValueError(f"Cached runtime asset hash mismatch: {original}")
        target = ROOT / "zing-workspace/home" / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
    (out / "provenance.json").write_text(json.dumps(receipts, indent=2), encoding="utf-8")
    photos = out / "photos"
    photos.mkdir(exist_ok=True)
    for name, second in [("korky", 3), ("tos-lab", 10), ("nasa-opening", 8)]:
        target = photos / f"{name}.png"
        if not target.exists():
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-n", "-ss", str(second),
                            "-i", str(verified / f"{name}.mp4"), "-frames:v", "1", str(target)], check=True)
    print(f"Verified and copied {len(receipts)} licensed clips; extracted 3 photos. No downloads.")


def transcript(stage, out):
    project = out / ("match" if stage == "a" else "square" if stage == "f" else "memes")
    if stage == "a":
        lines = ["a", str(project), "file", str(out / "verified/nasa-montage.mp4"), str(out / "clips"),
                 "a short introduction to people making things", "all", "", "8", "natural", "phone", "original", "yes"]
    elif stage == "f":
        result = json.loads((out / "match/studio-result.json").read_text(encoding="utf-8"))
        drafts = result["result"]["drafts"]
        selected = next((r["plan"] for key, r in drafts.items() if key.startswith("A.") and r["status"] == "ready"), None)
        if not selected:
            raise ValueError("No completed A draft to re-deliver. Read the match result first.")
        lines = ["f", str(project), selected, "square", "", "yes"]
    else:
        lines = ["c", str(project), str(out / "photos"), "when the build finally passes", "square", "", "yes"]
    script = "\n".join(lines) + "\n"
    (out / f"{stage}-stdin.txt").write_text(script, encoding="utf-8")
    started = time.monotonic()
    first = None
    env = {**os.environ, "UOINK_URL": "http://127.0.0.1:1", "PYTHONIOENCODING": "utf-8",
           "ZING_WHISPER_MODEL": str(ROOT / "zing-workspace/models/tiny.en"),
           "HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1"}
    with (out / f"{stage}-transcript.txt").open("w", encoding="utf-8") as log:
        log.write("Command: zing studio\nScripted first-time-creator answers (empty lines accept recommendations):\n" + script + "\nTerminal output:\n")
        process = subprocess.Popen([sys.executable, "-m", "myzing.cli", "studio"], cwd=ROOT, env=env,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace")
        process.stdin.write(script)
        process.stdin.close()
        for line in process.stdout:
            elapsed = time.monotonic() - started
            log.write(line)
            log.flush()
            print(line, end="", flush=True)
            if first is None and (("decode-" in line and ": done" in line) or "Working: Export " in line or line.startswith("Output:")):
                first = round(elapsed, 3)
        code = process.wait()
    state = json.loads((project / "studio-session.json").read_text(encoding="utf-8"))
    metrics = {"stage": stage, "exit_code": code, "questions_asked": state["questions_asked"],
               "confirmation_questions": 1, "seconds": round(time.monotonic() - started, 3),
               "time_to_first_output_seconds": first,
               "first_output_basis": "First decoded match draft, completed meme contact sheet, or reported delivery path; read-only probes included.",
               "status": state["status"], "project": str(project)}
    (out / f"{stage}-metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics))
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "a", "f", "c"])
    parser.add_argument("--source", type=Path, default=Path("E:/AI/projects/zing/worktrees/v1-realeval/zing-workspace/real-eval/clips"))
    parser.add_argument("--out", type=Path, default=ROOT / "zing-workspace/studio1-real")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.stage == "prepare":
        prepare(args.out.resolve(), args.source)
        return 0
    return transcript(args.stage, args.out.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
