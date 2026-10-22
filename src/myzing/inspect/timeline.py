"""Filmstrip, waveform and timed text on one pixel/time coordinate system.

Layout concept: browser-use/video-use's MIT timeline_view (see docs/INSPECT.md).
Implemented natively; no upstream code or NumPy dependency is included.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from myzing import storage
from myzing.schemas import EDL, Word
from . import InspectionError
from .media import Decoder
from .timing import (build_time_map, cut_points, finite, output_to_source,
                     source_words_to_output, validate_words)

MAX_FRAMES = 60
MAX_ROWS = 12
MAX_RANGE = 120
MAX_TOTAL_SECONDS = 600
MAX_PIXELS = 12_000_000
ROW_HEIGHT = 430
MARGIN = 40
BG = "#14171b"
FG = "#f0f2f4"
DIM = "#abb3bd"
WAVE = "#88b8e8"
CUT = "#ffb45c"
WORD = "#a8dfc4"


@dataclass(frozen=True)
class InspectionResult:
    path: str
    width: int
    height: int
    video: str
    duration: float
    rows: list[dict]
    mapping: list[dict]
    cuts: list[dict]
    warnings: list[str]
    transcript_origin: str
    version: int = 1
    audio_measurements: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> InspectionResult:
        if data.get("version", 1) != 1:
            raise InspectionError("Unsupported inspection result version; expected 1.")
        return cls(**data)


def _pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise InspectionError('Timeline images need Pillow; install with pip install "myzing[memes]".') from exc
    return Image, ImageDraw, ImageFont


def _local_file(raw: str | Path, label: str) -> Path:
    if not str(raw).strip() or "://" in str(raw):
        raise InspectionError(f"{label} must be a local file path; download it explicitly first.")
    path = Path(raw).expanduser().resolve()
    if not path.is_file():
        raise InspectionError(f"{label} not found: {path}. Restore it or supply its current path.")
    return path


def _load_edl(path: Path) -> EDL:
    if path.stat().st_size > 10_000_000:
        raise InspectionError("EDL exceeds the 10 MB inspection limit; split the input.")
    try:
        from myzing.render.composition import load_render_document
        from myzing.composition import Composition
        from myzing.schemas import Clip, CaptionSpec
        document = load_render_document(json.loads(path.read_text(encoding="utf-8")))
        if isinstance(document, Composition):
            if any(c.speed_map for c in document.clips) or any(t.end > t.start for t in document.transitions):
                raise InspectionError("Timeline inspection does not yet support speed maps or overlapping transitions")
            return EDL(clips=[Clip(**{f.name: getattr(c, f.name) for f in fields(Clip)}) for c in document.clips],
                       captions=[CaptionSpec(**{f.name: getattr(c, f.name) for f in fields(CaptionSpec)}) for c in document.captions],
                       width=document.width, height=document.height, fps=document.fps.numerator / document.fps.denominator)
        return document
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise InspectionError(f"Invalid EDL JSON: {exc}") from exc


def _transcript(edl, spans, breakdown, video, duration):
    warnings = []
    words = []
    origin = "none"
    if breakdown:
        try:
            b = storage.load_breakdown(breakdown)
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise InspectionError(f"Invalid breakdown: {exc}") from exc
        validate_words(b.words, finite(b.meta.duration, "breakdown duration"))
        candidates = set()
        if b.meta.media_path:
            candidates.add(storage.resolve_relpath(breakdown, b.meta.media_path).resolve())
        if b.meta.platform == "file" and b.meta.source_url and "://" not in b.meta.source_url:
            candidates.add(Path(b.meta.source_url).expanduser().resolve())
        if video in candidates or not spans:
            words = b.words
            origin = f"breakdown:{breakdown}:video-time"
        else:
            matches = {Path(span.source) for span in spans} & candidates
            if len(matches) != 1:
                raise InspectionError("Breakdown media does not identify one EDL source or the rendered video; use its matching breakdown or EDL captions.")
            words = source_words_to_output(b.words, matches.pop(), spans)
            origin = f"breakdown:{breakdown}:source-to-output"
            warnings.append("Source transcript intervals are clipped to kept spans; repeated clips repeat their words.")
        if edl and edl.captions:
            warnings.append("The explicit breakdown supplies transcript text; EDL captions are not overlaid as a second transcript.")
    elif edl:
        for caption in edl.captions:
            if caption.word_timed:
                if not caption.words:
                    raise InspectionError("A word-timed EDL caption has no words; supply timings or mark it word_timed=false.")
                validate_words(caption.words, duration)
                validate_words([Word(caption.text, caption.start, caption.end)], duration)
                if any(w.start < caption.start or w.end > caption.end for w in caption.words):
                    raise InspectionError("EDL word timing falls outside its caption interval; correct the caption.")
                words.extend(caption.words)
            else:
                words.append(Word(caption.text, caption.start, caption.end))
                warnings.append("Untimed caption text is shown as one phrase interval; no word timing was inferred.")
        origin = "edl:output-time" if words else "none"
    validate_words(words, duration)
    if not words:
        warnings.append("No transcript supplied or no words retained; no transcription was run.")
    return sorted(words, key=lambda w: (w.start, w.end)), origin, warnings


def plan_ranges(duration, cuts, *, start=None, end=None, around=None, radius=1.0, frames=5, width=1600):
    """Fail before decoding if the requested job would exceed any work/image cap."""
    if isinstance(frames, bool) or not isinstance(frames, int) or not 1 <= frames <= 15:
        raise InspectionError("frames must be an integer from 1 to 15 per row.")
    if isinstance(width, bool) or not isinstance(width, int) or not 960 <= width <= 2400:
        raise InspectionError("width must be an integer from 960 to 2400 pixels.")
    if (width - 2 * MARGIN) / frames < 100:
        raise InspectionError("Frames would be too narrow for timestamps; reduce frames or increase width.")
    radius = finite(radius, "radius")
    if not 0 < radius <= MAX_RANGE / 2:
        raise InspectionError("radius must be greater than 0 and at most 60 seconds.")
    centered = around is not None or (start is None and end is None and bool(cuts))
    if around is not None and (start is not None or end is not None):
        raise InspectionError("Use --around or --start/--end, not both.")
    if centered:
        if frames < 3 or frames % 2 == 0:
            raise InspectionError("Centered inspection needs an odd frames count from 3 to 15.")
        centers = [finite(around, "around")] if around is not None else [c["output_time"] for c in cuts]
        ranges = []
        for center in centers:
            if not 0 < center < duration:
                raise InspectionError("A centered time must be inside the video; use --start/--end at its edges.")
            half = min(radius, center, duration - center)
            ranges.append({"start": center - half, "end": center + half, "center": center})
    else:
        a = 0.0 if start is None else finite(start, "start")
        b = duration if end is None else finite(end, "end")
        if not 0 <= a < b <= duration:
            raise InspectionError(f"Range must satisfy 0 <= start < end <= video duration ({duration:.6f}s).")
        ranges = [{"start": a, "end": b, "center": None}]
    if len(ranges) > MAX_ROWS or len(ranges) * frames > MAX_FRAMES:
        raise InspectionError("Inspection is capped at 12 rows and 60 total frames; select --start/--end or --around.")
    lengths = [r["end"] - r["start"] for r in ranges]
    if max(lengths) > MAX_RANGE or sum(lengths) > MAX_TOTAL_SECONDS:
        raise InspectionError("Inspection is capped at 120 seconds per row and 600 total seconds; choose a shorter range.")
    height = 80 + ROW_HEIGHT * len(ranges)
    if width * height > MAX_PIXELS:
        raise InspectionError("Inspection exceeds 12 megapixels; reduce width or select fewer cuts.")
    return ranges, height


def time_to_x(time: float, start: float, end: float, x0: int, x1: int) -> int:
    return round(x0 + (time - start) / (end - start) * (x1 - x0))


def _fit_text(draw, text, font, width):
    text = " ".join(text.split())
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "...", font=font) > width:
        text = text[:-1]
    return text + "..."


def _draw_row(canvas, draw, fonts, decoder, video, row, cuts, spans, words, frames, y, has_audio):
    Image, _, _ = _pillow()
    label_font, small_font = fonts
    width = canvas.width
    x0, x1 = MARGIN, width - MARGIN
    start, end = row["start"], row["end"]
    x = lambda t: time_to_x(t, start, end, x0, x1)
    row.update({"axis": {"x0": x0, "x1": x1}, "frames": [], "words": [], "cuts": []})
    title = f"OUTPUT {start:.3f} - {end:.3f}s"
    if row["center"] is not None:
        title += f"   |   CENTER {row['center']:.3f}s"
    draw.text((x0, y), title, fill=FG, font=label_font)
    cell = (x1 - x0) / frames
    frame_width, frame_height = 2 * ((int(cell) - 4) // 2), 142
    for i in range(frames):
        # Bin midpoints put every thumbnail CENTER on the same axis as the audio.
        t = start + (i + .5) / frames * (end - start)
        cx = x(t)
        left, top = round(cx - frame_width / 2), y + 30
        raw = decoder.frame(video, t, frame_width, frame_height)
        canvas.paste(Image.frombytes("RGB", (frame_width, frame_height), raw), (left, top))
        mapped = output_to_source(spans, t) if spans else None
        frame = {"output_time": t, "x": cx, "rect": [left, top, frame_width, frame_height], "source": mapped}
        row["frames"].append(frame)
        draw.text((cx, y + 176), f"out {t:.3f}s", fill=FG, font=small_font, anchor="mt")
        if mapped:
            draw.text((cx, y + 193), f"src {mapped['source_time']:.3f}s", fill=DIM, font=small_font, anchor="mt")
    wave_top, wave_bottom = y + 220, y + 278
    row["waveform"] = {"rect": [x0, wave_top, x1 - x0, wave_bottom - wave_top],
                       "has_audio": has_audio, "scale": "linear RMS / full scale"}
    draw.rectangle((x0, wave_top, x1, wave_bottom), fill="#22272e")
    mid = (wave_top + wave_bottom) // 2
    draw.line((x0, mid, x1, mid), fill=DIM)
    if has_audio:
        env = decoder.envelope(video, start, end, x1 - x0)
        row["waveform"]["peak_rms"] = max(env, default=0)
        for i, amplitude in enumerate(env):
            h = min((wave_bottom - wave_top) // 2 - 2, round(amplitude * 27))
            draw.line((x0 + i, mid - h, x0 + i, mid + h), fill=WAVE)
    else:
        draw.text((x0 + 8, wave_top + 5), "No audio stream", fill=DIM, font=small_font)
    for i in range(5):
        t = start + i / 4 * (end - start)
        draw.text((x(t), wave_bottom + 4), f"{t:.3f}s", fill=DIM, font=small_font, anchor="mt")
    visible_cuts = [c for c in cuts if start <= c["output_time"] <= end]
    for c in visible_cuts:
        cx = x(c["output_time"])
        draw.line((cx, y + 27, cx, wave_bottom), fill=CUT, width=2)
        row["cuts"].append({**c, "x": cx})
    lanes = [-1] * 4
    for word in words:
        if word.end <= start or word.start >= end:
            continue
        a, b = max(start, word.start), min(end, word.end)
        xa, xb, cx = x(a), x(b), x((a + b) / 2)
        text = " ".join(word.text.split())
        text_width = round(draw.textlength(text, font=small_font))
        if text_width > x1 - x0:
            raise InspectionError("Transcript label is wider than the image; shorten the caption or increase width.")
        left = min(max(x0, cx - text_width // 2), x1 - text_width)
        lane = next((i for i, edge in enumerate(lanes) if edge + 6 <= left), None)
        if lane is None:
            raise InspectionError("Transcript is too dense for four label lanes; inspect a shorter range or increase width.")
        lanes[lane] = left + text_width
        top = y + 311 + lane * 25
        draw.line((xa, top, xb, top), fill=WORD, width=2)
        draw.line((cx, top, cx, top + 4), fill=WORD)
        draw.text((left, top + 4), text, fill=FG, font=small_font)
        row["words"].append({"text": word.text, "start": word.start, "end": word.end,
                             "visible_start": a, "visible_end": b, "x_start": xa, "x_end": xb,
                             "x_center": cx, "lane": lane, "bar_y": top,
                             "text_box": [left, top + 4, text_width, 18]})
    if not row["words"]:
        draw.text((x0, y + 315), "No transcript words in this range", fill=DIM, font=small_font)
    draw.line((x0, y + ROW_HEIGHT - 7, x1, y + ROW_HEIGHT - 7), fill="#363e48")


def _publish(canvas, out: Path, overwrite: bool) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=".zing-inspect-", suffix=".png", dir=out.parent)
    staged = Path(raw)
    try:
        with os.fdopen(fd, "wb") as stream:
            canvas.save(stream, format="PNG")
        if overwrite:
            os.replace(staged, out)
        else:
            # Atomic create-if-absent, even if another writer wins after validation.
            os.link(staged, out)
    except FileExistsError as exc:
        raise InspectionError(f"Output already exists: {out}. Use --overwrite to replace it.") from exc
    finally:
        staged.unlink(missing_ok=True)


def inspect_timeline(video: str | Path, out: str | Path, *, start: float | None = None,
                     end: float | None = None, around: float | None = None,
                     edl: str | Path | None = None, breakdown: str | None = None,
                     frames: int = 5, width: int = 1600, radius: float = 1.0,
                     overwrite: bool = False) -> InspectionResult:
    """Inspect video in its output coordinates; never render an EDL or run ASR."""
    Image, ImageDraw, ImageFont = _pillow()
    video = _local_file(video, "Video")
    if not str(out).strip() or "://" in str(out):
        raise InspectionError("out must be a local PNG path.")
    out = Path(out).expanduser().resolve()
    if out.suffix.lower() != ".png":
        raise InspectionError("Inspection output must have a .png extension.")
    edl_path = _local_file(edl, "EDL") if edl is not None else None
    plan = _load_edl(edl_path) if edl_path else None
    spans = build_time_map(plan, edl_path.parent) if plan else []
    protected = {video, edl_path} | {Path(s.source) for s in spans}
    if breakdown:
        protected.add(storage.breakdown_dir(breakdown).resolve() / "breakdown.json")
    if out in protected:
        raise InspectionError("Output must not replace an input video, EDL, source asset or breakdown.")
    if out.exists() and not overwrite:
        raise InspectionError(f"Output already exists: {out}. Use --overwrite to replace it.")
    decoder = Decoder()
    info = decoder.probe(video)
    duration = info["duration"]
    if spans and abs(spans[-1].output_end - duration) > max(1 / info["fps"], .05):
        raise InspectionError("Video duration does not match this EDL; supply the rendered edit that belongs to the EDL.")
    # A codec's last frame can extend beyond the nominal edit. Keep mapping inside it.
    extent = min(duration, spans[-1].output_end) if spans else duration
    cuts = cut_points(spans)
    rows, height = plan_ranges(extent, cuts, start=start, end=end, around=around,
                               radius=radius, frames=frames, width=width)
    words, origin, warnings = _transcript(plan, spans, breakdown, video, extent)
    measurements = None
    sidecar = video.with_suffix(".music.json")
    if sidecar.is_file() and sidecar.stat().st_size < 10_000_000:
        from myzing.project.api import hash_file
        try:
            candidate = json.loads(sidecar.read_text(encoding="utf-8"))
            if candidate.get("render_sha256") == hash_file(video):
                measurements = candidate
            else:
                warnings.append("Music measurements are stale: render SHA-256 differs.")
        except (ValueError, OSError):
            warnings.append("Music measurement sidecar is unreadable.")
    if spans:
        warnings.append("Cut markers use the EDL plan; frames show the supplied video. This is not automatic cut detection or proof of EDL/video identity.")
        warnings.append("Frame seeks select the first decoded frame at or after the labeled time; allow one video frame for sampling/rounding.")
    # Extra source legend rows remain bounded by the same image cap.
    visible_cuts = [c for c in cuts if any(r["start"] <= c["output_time"] <= r["end"] for r in rows)]
    if len(visible_cuts) > 60:
        raise InspectionError("More than 60 cut labels in this range; inspect a shorter range.")
    height += 52 * len(visible_cuts)
    if width * height > MAX_PIXELS:
        raise InspectionError("Cut legends exceed the 12 megapixel limit; select fewer cuts.")
    canvas = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(canvas)
    font_path = Path(__file__).resolve().parents[1] / "_data" / "fonts" / "IBMPlexSans.ttf"
    label_font = ImageFont.truetype(str(font_path), 20)
    small_font = ImageFont.truetype(str(font_path), 15)
    draw.text((MARGIN, 12), _fit_text(draw, f"ZING / INSPECT   {video.name}", label_font, width - 80), fill=FG, font=label_font)
    draw.text((MARGIN, 42), "Seconds in supplied video | amber: planned cuts | blue: RMS audio | green: timed text", fill=DIM, font=small_font)
    for i, row in enumerate(rows):
        _draw_row(canvas, draw, (label_font, small_font), decoder, video, row, cuts,
                  spans, words, frames, 74 + i * ROW_HEIGHT, info["has_audio"])
        if measurements:
            moments = [m for t in (measurements.get("music_plan") or {}).get("tracks", []) for m in t.get("moments", [])]
            row["music_moments"] = []
            for m in moments:
                t = m["output_time"]
                if row["start"] <= t <= row["end"]:
                    x = time_to_x(t, row["start"], row["end"], MARGIN, width - MARGIN)
                    y = 74 + i * ROW_HEIGHT
                    draw.line((x, y + 30, x, y + 278), fill="#f588db", width=2)
                    draw.text((x + 3, y + 205), m["kind"], fill="#f588db", font=small_font)
                    row["music_moments"].append(m)
    y = 80 + len(rows) * ROW_HEIGHT
    for c in visible_cuts:
        left, right = c["left"], c["right"]
        draw.text((MARGIN, y), f"CUT / out {c['output_time']:.3f}s   |   src {left['source_time']:.3f}s -> {right['source_time']:.3f}s", fill=CUT, font=label_font)
        source_names = f"#{left['clip_index']} {Path(left['source']).name} -> #{right['clip_index']} {Path(right['source']).name}"
        draw.text((MARGIN, y + 25), _fit_text(draw, source_names, small_font, width - 80), fill=DIM, font=small_font)
        y += 52
    _publish(canvas, out, overwrite)
    return InspectionResult(str(out), width, height, str(video), duration, rows,
                            [s.to_dict() for s in spans], cuts, list(dict.fromkeys(warnings)), origin,
                            audio_measurements=measurements)
