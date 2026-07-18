"""Backfill keyframes into already-frozen real-video fixtures (A-Q6).

The wizard-of-oz run showed every visual criterion going `cannot_judge`
because no frames are committed with the frozen baselines. This script
adds them WITHOUT re-measuring anything:

- media is re-fetched with the manifest's exact acquisition settings and
  its SHA-256 is verified against the fixture's frozen provenance — we
  never extract frames from unverified bytes;
- frames are grabbed at the FROZEN breakdown's shot-start timestamps plus
  ~1 fps over the format's hook window (deterministic ffmpeg seeks), so
  the baseline's measurements are untouched;
- frames are downscaled to <=360px height, quality ~7 JPEG ("small,
  license-safe" thumbnails per the A-Q6 decision) — analysis artifacts,
  not redistributable source media;
- breakdown.json gains the relative `Shot.keyframe` paths, and
  provenance.json records the frame artifacts, their hashes, and the
  extraction recipe.

Run (Lane A, local):
    python -m tools.eval.backfill_frames --media-root <dir with <video_id>.mp4>

Ownership note: this file lives in Lane C's tree because that is where the
fixtures live; it was added by Lane A under queue item A-Q6. It never
touches goldens, scoring, or the freezer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
REAL_VIDEOS = HERE / "real_videos"
MANIFEST = REAL_VIDEOS / "manifest.json"

FRAMES_DIR = "frames"
MAX_HEIGHT = 360
JPEG_QUALITY = "7"
LONG_FORM_MAX_SHORT_S = 180.0     # mirror of myzing.study.formats


class BackfillError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(path: Path) -> str:
    """Newline-normalized hash for text artifacts — matches the freezer's
    _text_sha256 so hashes are stable across Windows/Unix checkouts."""
    content = path.read_text(encoding="utf-8")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def hook_seconds(duration: float) -> list[float]:
    window = 3.0 if duration <= LONG_FORM_MAX_SHORT_S else 30.0
    seconds, t = [], 0.0
    while t < min(window, duration):
        seconds.append(t)
        t += 1.0
    return seconds


def frame_plan(breakdown: dict) -> list[tuple[str, float]]:
    """(filename, timestamp) pairs for a frozen breakdown — shot starts
    plus hook-window seconds, exactly like the study engine's keyframes."""
    plan = [
        (f"shot_{shot['index']:03d}.jpg", float(shot["start"]))
        for shot in breakdown.get("shots", [])
    ]
    duration = float(breakdown.get("meta", {}).get("duration", 0.0))
    plan += [
        (f"hook_{s:.0f}s.jpg", s) for s in hook_seconds(duration)
    ]
    return plan


def grab(ffmpeg: str, media: Path, at: float, target: Path) -> None:
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(0.0, at):.3f}", "-i", str(media),
        "-frames:v", "1",
        "-vf", f"scale=-2:'min({MAX_HEIGHT},ih)'",
        "-q:v", JPEG_QUALITY,
        "-y", str(target),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not target.is_file():
        raise BackfillError(
            f"ffmpeg could not grab {target.name} at {at:.3f}s: "
            f"{result.stderr.strip().splitlines()[-1] if result.stderr.strip() else 'no output'}"
        )


def backfill_case(
    case_dir: Path,
    media: Path,
    ffmpeg: str,
    manifest_sha: str,
    truth_sha: str | None,
    truth_text: str | None,
    truth_section: str | None,
) -> dict:
    breakdown_path = case_dir / "breakdown.json"
    provenance_path = case_dir / "provenance.json"
    breakdown = json.loads(breakdown_path.read_text(encoding="utf-8"))
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))

    if (
        truth_section is not None
        and truth_text is not None
        and truth_section not in truth_text
    ):
        raise BackfillError(
            f"{case_dir.name}: truth section '{truth_section}' no longer "
            "exists in the human-truth doc — fixture linkage is broken, "
            "fix the doc or the manifest before re-recording hashes"
        )

    recorded = provenance["source_media"]["sha256"]
    actual = sha256_file(media)
    if actual != recorded:
        raise BackfillError(
            f"{case_dir.name}: media SHA-256 mismatch — refusing to extract "
            f"frames from unverified bytes (recorded {recorded[:12]}…, "
            f"got {actual[:12]}…). Refetch per manifest source_acquisition."
        )

    frames_dir = case_dir / FRAMES_DIR
    frames_dir.mkdir(exist_ok=True)
    plan = frame_plan(breakdown)
    for filename, at in plan:
        grab(ffmpeg, media, at, frames_dir / filename)

    for shot in breakdown.get("shots", []):
        shot["keyframe"] = f"{FRAMES_DIR}/shot_{shot['index']:03d}.jpg"
    breakdown_path.write_text(
        json.dumps(breakdown, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    frame_artifacts = {
        f"{FRAMES_DIR}/{name}": sha256_file(frames_dir / name)
        for name, _ in plan
    }
    provenance["derived_frames"] = {
        "committed": True,
        "decision": "Small analysis thumbnails ship with baselines so "
                    "visual judgment criteria are scoreable; source media "
                    "remains uncommitted.",
        "recipe": {
            "source": "sha256-verified source media (see source_media)",
            "timestamps": "frozen shot starts + 1 fps over the hook window",
            "scale": f"height<={MAX_HEIGHT}",
            "jpeg_quality": JPEG_QUALITY,
        },
        "count": len(plan),
    }
    backfill_note = (
        "Backfilled shot keyframe paths and committed downscaled analysis "
        "thumbnails (A-Q6); frames grabbed from SHA-verified source media "
        "at frozen timestamps — measurements untouched."
    )
    kept = [
        note for note in provenance.get("normalizations", [])
        if "Cleared shot keyframe paths" not in note
    ]
    if backfill_note not in kept:
        kept.append(backfill_note)
    provenance["normalizations"] = kept

    provenance["manifest"]["sha256"] = manifest_sha
    if truth_section is not None and truth_sha is not None:
        provenance["human_truth"]["section"] = truth_section
        if provenance["human_truth"]["sha256"] != truth_sha:
            provenance["human_truth"]["sha256"] = truth_sha
            provenance["human_truth"]["note"] = (
                "hash re-recorded after the human-truth doc was corrected "
                "post-freeze (D-Q4/F-16); fixture measurements unchanged, "
                "truth section verified present"
            )

    artifacts = provenance.get("artifacts", {})
    artifacts.update(frame_artifacts)
    artifacts["breakdown.json"] = sha256_text(breakdown_path)
    provenance["artifacts"] = artifacts
    provenance_path.write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"fixture": case_dir.name, "frames": len(plan)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--media-root", type=Path, required=True,
                        help="directory containing <video_id>.mp4 files")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args(argv)

    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Manifest is updated FIRST so every fixture's provenance records the
    # hash of the manifest as committed, not a stale one.
    manifest["media_policy"]["derived_frames_committed"] = True
    manifest["media_policy"].setdefault(
        "derived_frames_reason",
        (
            "A-Q6: small downscaled analysis thumbnails (<=360px JPEG) are "
            "committed so visual judgment criteria are scoreable; source "
            "media itself stays uncommitted."
        ),
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest_sha = sha256_text(manifest_path)

    results = []
    for case in manifest["cases"]:
        human_truth = case.get("human_truth")
        if human_truth is not None and not human_truth["available"]:
            truth_text = None
            truth_sha = None
            truth_section = None
        else:
            truth_path = HERE.parents[1] / (
                human_truth["path"]
                if human_truth is not None
                else manifest["human_truth"]
            )
            truth_text = truth_path.read_text(encoding="utf-8")
            truth_sha = sha256_text(truth_path)
            truth_section = (
                human_truth["section"]
                if human_truth is not None
                else case["truth_section"]
            )
        case_dir = REAL_VIDEOS / case["fixture_id"]
        if not case_dir.is_dir():
            raise BackfillError(f"fixture missing: {case_dir}")
        media = args.media_root / case["media_filename"]
        if not media.is_file():
            raise BackfillError(f"media missing: {media}")
        results.append(backfill_case(
            case_dir, media, args.ffmpeg,
            manifest_sha, truth_sha, truth_text, truth_section,
        ))

    for result in results:
        print(f"{result['fixture']}: {result['frames']} frames committed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
