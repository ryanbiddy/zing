"""Offline R15 render examples and detector readings from generated sources.

Run: python -m tools.eval.render_transition_fixture --out zing-workspace/r15-transitions
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from myzing.composition import AssetRef, Composition, CompositionClip, SourceRange, Transition, TransitionRecipe
from myzing.project.models import Rational
from myzing.render import render_composition
from myzing.study.transitions import detect_transition_signatures
from tools.eval.transition_corpus import GeneratedCase, generate_case


RECIPES = [("hard_cut", None), ("dissolve", None),
           *(("wipe", d) for d in ("left", "right", "up", "down")),
           ("dip_to_black", None), ("dip_to_white", None), ("zoom_punch", None)]


def run(command: list[str]) -> bytes:
    result = subprocess.run(command, capture_output=True, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace"))
    return result.stdout


def make_sources(directory: Path, *, textures: bool = False) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    corpus = None
    if textures:
        case = GeneratedCase("r15-textures", "held_out", "dissolve", 713, 30, 160, 160, 1.4, .6, duration=3.4)
        corpus = generate_case(case, directory)
    sources = []
    for index, color in enumerate(("red", "blue")):
        path = directory / f"source-{index}.mkv"
        command = ["ffmpeg", "-v", "error", "-y"]
        if textures:
            command += ["-loop", "1", "-framerate", "30", "-i", str(corpus / ("a.pgm", "b.pgm")[index])]
            video_filter = "scale=160:160,format=yuv420p"
        else:
            command += ["-f", "lavfi", "-i", f"color=c={color}:s=160x160:r=30:d=3"]
            # A frame counter in the top strip catches held/skipped boundary
            # frames; the rest of the frame remains an exact color oracle.
            video_filter = ("geq=lum='if(lt(Y,16),if(mod(floor(N/pow(2,floor(X/20))),2),220,32),lum(X,Y))':"
                            "cb='cb(X,Y)':cr='cr(X,Y)'")
        command += ["-f", "lavfi", "-i", f"sine=frequency={440 + 220 * index}:sample_rate=48000:duration=3",
                    "-vf", video_filter, "-t", "3", "-c:v", "ffv1", "-c:a", "pcm_s16le", str(path)]
        run(command)
        sources.append(path)
    return tuple(sources)


def pair_plan(sources: tuple[Path, Path], kind: str, direction: str | None = None,
              *, duration: float = .6, fps: Rational | None = None) -> Composition:
    d = 0 if kind == "hard_cut" else duration
    assets = [AssetRef(f"asset-{i}", str(p), hashlib.sha256(p.read_bytes()).hexdigest()) for i, p in enumerate(sources)]
    clips = [CompositionClip(str(p), .5, 2.5, i * (2 - d), id=f"clip-{i}", asset_id=f"asset-{i}")
             for i, p in enumerate(sources)]
    transition = Transition("transition-0", "clip-0", "clip-1", 2 - d, 2,
                            TransitionRecipe(kind, d, "R15 generated render fidelity fixture", direction),
                            SourceRange(2.5 - d, 2.5) if d else None,
                            SourceRange(.5, .5 + d) if d else None)
    return Composition(assets=assets, clips=clips, transitions=[transition], width=160, height=160,
                       fps=fps or Rational(30, 1))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    directory = args.out.resolve()
    sources = make_sources(directory / "sources", textures=True)
    records = []
    from myzing.inspect.timeline import inspect_timeline
    for kind, direction in RECIPES:
        name = kind + (f"-{direction}" if direction else "")
        c = pair_plan(sources, kind, direction)
        (directory / f"{name}.json").write_text(c.to_json(indent=2) + "\n", encoding="utf-8")
        result = render_composition(c, directory / f"{name}.mp4", work_dir=directory / f"{name}-work")
        inspect_timeline(result.output_path, directory / f"{name}-timeline.png", start=1.2, end=2.2,
                         frames=9, overwrite=True)
        measurement = detect_transition_signatures(result.output_path)
        records.append({"recipe": name, "duration": result.duration, "output": str(result.output_path),
                        "detector_version": 5, "predicted": measurement["predicted"], "events": measurement["events"]})
    (directory / "detector-report.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    c = chain_plan(sources)
    (directory / "all-transitions.json").write_text(c.to_json(indent=2) + "\n", encoding="utf-8")
    result = render_composition(c, directory / "all-transitions.mp4", work_dir=directory / "all-transitions-work")
    inspect_timeline(result.output_path, directory / "all-transitions-timeline.png", frames=12, overwrite=True)
    print(json.dumps(records, indent=2))
    return 0


def chain_plan(sources: tuple[Path, Path]) -> Composition:
    c = pair_plan(sources, "hard_cut")
    c.clips, c.transitions = c.clips[:1], []
    for index, (kind, direction) in enumerate(RECIPES, 1):
        previous = c.clips[-1]
        d = 0 if kind == "hard_cut" else .6
        start = previous.timeline_end - d
        clip = CompositionClip(str(sources[index % 2]), .5, 2.5, start, id=f"clip-{index}", asset_id=f"asset-{index % 2}")
        c.clips.append(clip)
        c.transitions.append(Transition(f"transition-{index}", previous.id, clip.id, start, previous.timeline_end,
                                       TransitionRecipe(kind, d, "R15 generated transition chain", direction),
                                       SourceRange(2.5 - d, 2.5) if d else None,
                                       SourceRange(.5, .5 + d) if d else None))
    return c


if __name__ == "__main__":
    raise SystemExit(main())
