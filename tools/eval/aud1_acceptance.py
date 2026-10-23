"""Replay AUD1 on licensed local copies; no acquisition or model download.

python -m tools.eval.aud1_acceptance --v1-clips <clips> --music1 <acceptance>
    --whisper <complete-local-tiny-model> --out zing-workspace/acceptance
Provision CED separately with zing audio fetch-model --consent first.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path


def write(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1-clips", type=Path, required=True)
    parser.add_argument("--music1", type=Path, required=True)
    parser.add_argument("--whisper", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    root = args.out.resolve()
    if any(root == p.resolve() or p.resolve() in root.parents for p in (args.v1_clips, args.music1)):
        raise ValueError("Acceptance output must be separate from the read-only source folders")
    root.mkdir(parents=True, exist_ok=True)
    repo = Path(__file__).resolve().parents[2]
    manifest = json.loads((repo / "tools/eval/real/manifest.json").read_text(encoding="utf-8"))
    tracks = json.loads((args.music1 / "tracks.json").read_text(encoding="utf-8"))
    copies = []
    for rows, source in ((manifest["clips"], args.v1_clips), (tracks, args.music1)):
        for row in rows:
            name = Path(row["file"]).name
            original, target = source / name, root / name
            digest = hashlib.sha256(original.read_bytes()).hexdigest()
            if digest != row["sha256"]:
                raise ValueError(f"Licensed fixture hash mismatch: {name}")
            if not target.exists():
                shutil.copyfile(original, target)
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError(f"Acceptance copy hash mismatch: {name}")
            copies.append({**row, "copy": str(target), "verified_sha256": digest})
    write(root / "verified-media.json", copies)

    from myzing.audio import analyze
    from myzing.music.advice import rate
    from myzing.study.transcribe import transcribe, _load_model, _collect_words
    for name, filename in [(r["id"], Path(r["file"]).name) for r in copies
                           if r["id"] in {"electric", "calm", "vocals", "tos-dialogue", "tos-lab", "tos-memory", "duck-titles", "korky"}]:
        start = time.perf_counter()
        audio = analyze(root / filename)
        data = audio.to_dict()
        if audio.tags.status != "measured":
            raise RuntimeError(str(audio.tags.warnings))
        data["acceptance_seconds"] = time.perf_counter() - start
        data["advice"] = rate(audio, length=20, speech=True, pace=2, purpose="talking interview").to_dict()
        write(root / f"{name}-audio.json", data)
        print(name, audio.structure.vocals["status"], audio.structure.vocals["confidence"], flush=True)

    for name, hint in (("korky", False), ("korky", True), ("nasa-opening", False), ("tos-dialogue", False)):
        start = time.perf_counter()
        result = transcribe(root / f"{name}.mp4", model_name=str(args.whisper.resolve()),
                            local_files_only=True, vocabulary=["Korky Paul"] if hint else [])
        if not result.words or result.provenance.get("timing", {}).get("status") == "unavailable":
            raise RuntimeError(str(result.warnings))
        data = {"words": [vars(w) for w in result.words], "provenance": result.provenance,
                "warnings": result.warnings, "elapsed_seconds": time.perf_counter() - start}
        write(root / f"{name}-{'hint' if hint else 'plain'}-asr.json", data)
        print(name, "hint" if hint else "plain", " ".join(w.text for w in result.words), flush=True)

    model, device, compute, version = _load_model(str(args.whisper.resolve()), local_files_only=True)
    segments, _ = model.transcribe(str(root / "korky.mp4"), word_timestamps=True,
                                    vad_filter=True, condition_on_previous_text=False)
    words = _collect_words(segments)
    write(root / "korky-legacy-asr.json", {"words": [vars(w) for w in words],
        "device": device, "compute_type": compute, "faster_whisper": version,
        "description": "Pre-AUD1 decoder options; default VAD, no hints or edge clamp"})


if __name__ == "__main__":
    main()
