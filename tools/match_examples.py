"""Generated P18 example. ASR text and OCR recognition are explicit test doubles.

No speech accuracy claim: audio is amplitude-modulated harmonic tones. OCR boxes
come from white caption pixels in actual decoded frames; the text is a fixture
label. Cuts, grading, planning, rendering, decoding and inspection use real APIs.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from myzing.match.state import read, write
from myzing.schemas import Word
from myzing.study.transcribe import TranscribeResult


def generate(root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    clips = root / "clips"
    clips.mkdir(exist_ok=True)
    font = Path(__file__).resolve().parents[1] / "src/myzing/_data/fonts/Anton-Regular.ttf"
    shutil.copyfile(font, root / "fixture.ttf")
    for i in range(4):
        reference = i == 3
        duration = 6 if reference else 8
        output = root / "reference.mp4" if reference else clips / f"take-{i}.mp4"
        if output.is_file():
            continue
        colors = ["0x863d33", "0x2c527d", "0x437b53", "0x7b6530"]
        colors = colors[i % 3:] + colors[:i % 3] if not reference else colors
        command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
        for color in colors[:duration // 2]:
            command += ["-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=30:d=2"]
        sound = "(0.16*sin(2*PI*140*t)+0.08*sin(2*PI*280*t)+0.04*sin(2*PI*700*t))*(0.35+0.65*abs(sin(2*PI*3*t)))"
        command += ["-f", "lavfi", "-i", f"aevalsrc='{sound}':s=48000:d={duration}"]
        graph = "".join(f"[{n}:v]" for n in range(duration // 2)) + f"concat=n={duration // 2}:v=1:a=0"
        if reference:
            for n in range(duration):
                graph += (f",drawtext=fontfile=fixture.ttf:text='WORD {n}':fontsize=20:fontcolor=white:"
                          f"x=(w-tw)/2:y=h*0.77:enable='between(t,{n + .25},{n + .95})'")
        else:
            graph += f",drawtext=fontfile=fixture.ttf:text='TAKE {i}':fontsize=18:fontcolor=white:x=10:y=10"
        graph += "[v]"
        command += ["-filter_complex", graph, "-map", "[v]", "-map", f"{duration // 2}:a", "-t", str(duration),
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(output)]
        subprocess.run(command, cwd=root, check=True, capture_output=True, timeout=60)
    return root / "reference.mp4", clips


@contextmanager
def fixture_measurements():
    calls = []
    def transcribe(path, model_name=None, duration=0, **options):
        assert options.get("local_files_only") is True
        calls.append(str(path))
        words = [Word(text, shot * 2 + .25 + .5 * n, shot * 2 + .5 + .5 * n, .95)
                 for shot in range(int(duration // 2)) for n, text in enumerate(("Make", "this", "style", "work"))]
        return TranscribeResult(words, {"fixture": "Authored words over synthetic audio; no ASR accuracy evidence."},
                                ["Fixture ASR: authored words, not measured speech."])

    def engine():
        import numpy as np
        def recognize(frame):
            h, w = frame.shape[:2]
            # Ignore the top-left source identity label. White/yellow caption
            # glyph pixels are measured after actual output compositing.
            mask = (frame[:, :, 1] > 190) & (frame[:, :, 2] > 190)
            mask[:h // 2] = False
            ys, xs = np.nonzero(mask)
            if len(xs) < 8:
                return SimpleNamespace(boxes=[], txts=[], scores=[])
            left, top, right, bottom = int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)
            return SimpleNamespace(boxes=[[[left, top], [right, top], [right, bottom], [left, bottom]]],
                                   txts=["fixture caption"], scores=[.99])
        return recognize, "fixture-recognition; geometry measured from decoded pixels"
    with ExitStack() as stack:
        stack.enter_context(patch("myzing.study.transcribe.transcribe", transcribe))
        stack.enter_context(patch("myzing.study.caption_models.engine", engine))
        yield calls


ANSWERS = {"purpose": "Compare three openings using measured reference pace", "aspect": "16:9", "target_length_seconds": 6}


def fixture_worker(trace, fail_render=False):
    """Test driver around the real worker, using only existing analysis seams."""
    from myzing.match.worker import main as worker_main
    attempts = []
    def offline(*args, **kwargs):
        attempts.append("network")
        raise AssertionError("Fixture worker attempted network access")
    with fixture_measurements() as calls, ExitStack() as stack:
        for target in ("socket.socket.connect", "socket.create_connection", "socket.getaddrinfo"):
            stack.enter_context(patch(target, offline))
        if fail_render:
            from myzing.render.composition import render_composition
            def render(plan, output, **kwargs):
                if Path(output).name == "draft-B.mp4":
                    raise RuntimeError("forced B encoder failure")
                return render_composition(plan, output, **kwargs)
            stack.enter_context(patch("myzing.render.composition.render_composition", render))
        try:
            return worker_main()
        finally:
            previous = read(trace) if trace.exists() else {"calls": [], "network_attempts": []}
            write(trace, {"version": 1, "calls": previous["calls"] + calls,
                          "network_attempts": previous["network_attempts"] + attempts})


def main():
    if sys.argv[1:2] == ["--worker"]:
        return fixture_worker(Path(sys.argv[2]), "--fail-render" in sys.argv)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    reference, clips = generate(args.out / "inputs")
    from myzing.match import jobs
    trace = (args.out / "fixture-trace.json").resolve()
    with patch.object(jobs, "worker_command", lambda: [sys.executable, "-m", "tools.match_examples", "--worker", str(trace)]):
        result = jobs.execute(dict(reference=str(reference), clips=str(clips), out=str(args.out / "project"),
                                   answers=ANSWERS, seed=18, resume=True), progress=lambda line: print(line, flush=True))
    write(args.out / "fixture-provenance.json", {"version": 1, "license": "CC0 generated media; bundled font OFL-1.1",
          "disclosure": __doc__, "trace": read(trace)})
    print(json.dumps({"summary": result["summary"], "comparison": result["comparison"], "seconds": result["seconds"]}, indent=2))
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
