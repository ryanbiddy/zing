"""Consented cold-home studio acceptance on read-only, licensed V1 fixtures."""

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
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def main():
    if os.environ.get("UOINK_URL") != "http://127.0.0.1:1":
        raise RuntimeError("Acceptance requires disabled Uoink")
    source = Path(sys.argv[1])
    out = ROOT / (sys.argv[2] if len(sys.argv) > 2 else "zing-workspace/onboard1-real")
    home = out / "fresh-home"
    if home.exists():
        raise RuntimeError("Acceptance requires a fresh home; preserve the previous receipt.")
    home.mkdir(parents=True)
    manifest = json.loads((ROOT / "tools/eval/real/manifest.json").read_text())
    media = out / "verified"
    media.mkdir()
    receipts = []
    for item in manifest["clips"]:
        original = source / Path(item["file"]).name
        actual = digest(original)
        if actual != item["sha256"]:
            raise RuntimeError(f"V1 hash mismatch: {original.name}")
        target = media / original.name
        shutil.copyfile(original, target)
        assert digest(target) == actual
        receipts.append({"source": str(original), "copy": str(target), "sha256": actual,
                         "license": item["license"], "attribution": item["attribution"]})
    (out / "media-receipts.json").write_text(json.dumps(receipts, indent=2))
    clips = out / "clips"
    clips.mkdir()
    for name in ("korky.mp4", "tos-lab.mp4", "nasa-opening.mp4"):
        shutil.copyfile(media / name, clips / name)
    env = {**os.environ, "ZING_HOME": str(home), "HF_HOME": str(out / "fresh-hf"),
           "HF_HUB_CACHE": str(out / "fresh-hf/hub"), "HUGGINGFACE_HUB_CACHE": str(out / "fresh-hf/hub")}
    env.pop("ZING_WHISPER_MODEL", None)
    env.pop("HF_HUB_OFFLINE", None)
    answers = ["1", str(media / "nasa-montage.mp4"), str(clips),
               "a short introduction to people making things", "YouTube", "15", "phone", "original",
               "small.en", "yes", "yes"]
    (out / "stdin.txt").write_text("\n".join(answers) + "\n")
    started = time.monotonic()
    first = None
    with (out / "transcript.txt").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-m", "myzing.cli", "studio"], cwd=out, env=env,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace")
        process.stdin.write("\n".join(answers) + "\n")
        process.stdin.close()
        for line in process.stdout:
            elapsed = time.monotonic() - started
            log.write(f"[{elapsed:.3f}s] {line}")
            log.flush()
            print(line.rstrip(), flush=True)
            if first is None and "Playback checked for draft" in line:
                first = elapsed
        code = process.wait()
    result = {"version": 1, "exit_code": code, "seconds_to_first_decoded_draft": first,
              "total_seconds": time.monotonic() - started, "home": str(home),
              "inputs": str(out / "stdin.txt"), "transcript": str(out / "transcript.txt")}
    (out / "timing.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
