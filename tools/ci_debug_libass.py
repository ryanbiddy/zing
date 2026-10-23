"""TEMPORARY libass literal-text probe (remove before merge).

Renders each probe string through Zing's v2 ASS path and through an
independent drawtext render of the same font, then reports ink widths,
libass font-selection logs and PNGs under the output directory.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from myzing.composition import AssetRef, CaptionStyle, Composition, CompositionCaption, CompositionClip, FontAsset  # noqa: E402
from myzing.layout.types import Box, EventLayout, OverlapCheck  # noqa: E402
from myzing.project.models import Rational  # noqa: E402
from myzing.render import positioned_captions, render_composition  # noqa: E402

FONT = ROOT / "src/myzing/_data/fonts/Anton-Regular.ttf"
PROBES = {
    "braces": "{}",
    "bsN": "\\N",
    "bsn": "\\n",
    "bsh": "\\h",
    "pos": "{\\pos(0,0)}",
    "bs": "\\",
    "AbsB": "A\\B",
    "AspB": "A B",
    "end": "END \\\\",
    "line1": "{} \\N \\n \\h {\\pos(0,0)}",
    "full": "{} \\N \\n \\h {\\pos(0,0)}\nEND \\\\",
}
JOINERS = {"wj": "⁠", "zwsp": "​", "zwnj": "‌", "none": ""}


def ffmpeg(*args, cwd=None, loglevel="error"):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", loglevel, "-y", *map(str, args)],
                       cwd=cwd, capture_output=True, timeout=120)
    if r.returncode:
        raise RuntimeError(r.stderr.decode("utf-8", "replace"))
    return r


def ink(mask):
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return None
    return int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)


def line_widths(mask):
    rows = np.flatnonzero(mask.any(axis=1))
    if not len(rows):
        return []
    breaks = np.where(np.diff(rows) > 3)[0]
    out = []
    for part in np.split(rows, breaks + 1):
        b = ink(mask[part[0]:part[-1] + 1])
        out.append([b[2] - b[0], b[3] - b[1]])
    return out


def column_runs(mask):
    """Ink column runs (glyph-ish blobs) of a single-line mask: [start, end)."""
    cols = mask.any(axis=0)
    runs, start = [], None
    for x, on in enumerate(cols):
        if on and start is None:
            start = x
        elif not on and start is not None:
            runs.append([start, x]); start = None
    if start is not None:
        runs.append([start, len(cols)])
    return runs


def main(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    src = out / "black.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=black:s=640x360:r=30:d=1", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", src)
    (out / "original.ttf").write_bytes(FONT.read_bytes())
    font = FontAsset(str(FONT), hashlib.sha256(FONT.read_bytes()).hexdigest(), "OFL-1.1")
    original = positioned_captions.escape_ass
    report = {"ffmpeg": ffmpeg("-version").stdout.decode().splitlines()[0], "probes": {}}
    for jname, joiner in JOINERS.items():
        def escape(text, joiner=joiner):
            return (text.replace("\r\n", "\n").replace("\r", "\n")
                    .replace("\\", "\\" + joiner).replace("{", r"\{").replace("}", r"\}")
                    .replace("\n", r"\N"))
        positioned_captions.escape_ass = escape
        for name, text in PROBES.items():
            key = f"{jname}-{name}"
            work = out / key
            cap = CompositionCaption(text=text, start=0, end=1, id="caption", word_timed=False, all_caps=False,
                                     font=font, style=CaptionStyle(28, outline_width=0),
                                     layout=EventLayout("caption", 0, 1, "fixture", OverlapCheck(True), box=Box(.05, .15, .9, .7)))
            comp = Composition(assets=[AssetRef("video", str(src), hashlib.sha256(src.read_bytes()).hexdigest(), aliases=["s"])],
                               clips=[CompositionClip("s", 0, 1, 0, id="clip", asset_id="video")],
                               captions=[cap], width=640, height=360, fps=Rational(30, 1))
            entry = {}
            try:
                result = render_composition(comp, work / "out.mp4", work_dir=work)
                raw = ffmpeg("-i", result.output_path, "-vf", "select=eq(n\\,15)", "-frames:v", "1",
                             "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1").stdout
                mask = np.frombuffer(raw, dtype=np.uint8).reshape(360, 640, 3).min(axis=2) > 150
                ffmpeg("-i", result.output_path, "-vf", "select=eq(n\\,15)", "-frames:v", "1", out / f"{key}-ass.png")
                entry["ass_lines"] = line_widths(mask)
                b = ink(mask)
                entry["ass_runs"] = column_runs(mask[b[1]:b[3]]) if b else []
                ass_text = (work / "captions.ass").read_text(encoding="utf-8")
                entry["ass_dialogue"] = [l for l in ass_text.splitlines() if l.startswith("Dialogue")][:1]
                # Re-run the same ASS through the filter with libass INFO logs.
                log = ffmpeg("-f", "lavfi", "-i", "color=black:s=640x360:r=1:d=1", "-vf",
                             "ass=filename='captions.ass':fontsdir='fonts'", "-frames:v", "1", "-f", "null", "-",
                             cwd=work, loglevel="info").stderr.decode("utf-8", "replace")
                entry["libass_log"] = [l for l in log.splitlines() if "ass" in l.lower() or "glyph" in l.lower() or "font" in l.lower()][:40]
            except Exception as exc:  # report and continue
                entry["error"] = str(exc)[-2000:]
            if jname == "wj":
                (out / "literal.txt").write_text(text, encoding="utf-8", newline="\n")
                for flags in ("default", "no_hinting", "force_autohint", "no_autohint"):
                    vf = ("drawtext=fontfile='original.ttf':textfile='literal.txt':expansion=none:fontsize=28:"
                          f"fontcolor=white:x=10:y=10:ft_load_flags={flags}")
                    raw = ffmpeg("-f", "lavfi", "-i", "color=black:s=640x360:r=1:d=1", "-vf", vf,
                                 "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1", cwd=out).stdout
                    dmask = np.frombuffer(raw, dtype=np.uint8).reshape(360, 640, 3).min(axis=2) > 150
                    suffix = "" if flags == "default" else "_" + flags
                    entry["drawtext_lines" + suffix] = line_widths(dmask)
                    b = ink(dmask)
                    entry["drawtext_runs" + suffix] = column_runs(dmask[b[1]:b[3]]) if b else []
                    ffmpeg("-f", "lavfi", "-i", "color=black:s=640x360:r=1:d=1", "-vf", vf,
                           "-frames:v", "1", f"{key}-drawtext{suffix}.png", cwd=out)
            report["probes"][key] = entry
            print(key, json.dumps({k: v for k, v in entry.items() if k.endswith("_lines") or k.endswith("lines_no_hinting") or k == "error" or "lines_" in k}), flush=True)
    positioned_captions.escape_ass = original
    (out / "report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
