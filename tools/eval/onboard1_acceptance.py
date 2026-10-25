"""Consented cold-home studio acceptance on read-only, licensed V1 fixtures."""

import hashlib
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def digest(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def main():
    if os.environ.get("UOINK_URL") != "http://127.0.0.1:1":
        raise RuntimeError("Acceptance requires disabled Uoink")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="?")
    parser.add_argument("out", type=Path, nargs="?", default=Path("zing-workspace/onboard1-real"))
    parser.add_argument("--generated", action="store_true", help="Generate silent media; exercise cold-home editing without model downloads")
    args = parser.parse_args()
    if not args.generated and args.source is None:
        parser.error("supply the pinned V1 source folder or --generated")
    source = args.source
    out = (ROOT / args.out).resolve()
    home = out / "fresh-home"
    if home.exists():
        raise RuntimeError("Acceptance requires a fresh home; preserve the previous receipt.")
    home.mkdir(parents=True)
    manifest = json.loads((ROOT / "tools/eval/real/manifest.json").read_text())
    media = out / "verified"
    media.mkdir()
    receipts = []
    for item in ([] if args.generated else manifest["clips"]):
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
    if args.generated:
        from tools.eval.studio_generated import prepare
        prepare(out)
    else:
        for name in ("korky.mp4", "tos-lab.mp4", "nasa-opening.mp4"):
            shutil.copyfile(media / name, clips / name)
    env = {**os.environ, "ZING_HOME": str(home), "HF_HOME": str(out / "fresh-hf"),
           "HF_HUB_CACHE": str(out / "fresh-hf/hub"), "HUGGINGFACE_HUB_CACHE": str(out / "fresh-hf/hub")}
    env.pop("ZING_WHISPER_MODEL", None)
    env.pop("HF_HUB_OFFLINE", None)
    from tools.eval.studio_generated import match_answers
    answers = match_answers(media / "nasa-montage.mp4", clips, generated=args.generated, speech="download small.en")
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
    state = json.loads((out / "zing-workspace/studio/studio-session.json").read_text(encoding="utf-8"))
    if code == 0 and state["status"] != "ready":
        code = 1
    result = {"version": 1, "exit_code": code, "seconds_to_first_decoded_draft": first,
              "total_seconds": time.monotonic() - started, "home": str(home),
              "status": state["status"], "questions_asked": state["questions_asked"],
              "inputs": str(out / "stdin.txt"), "transcript": str(out / "transcript.txt")}
    (out / "timing.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
