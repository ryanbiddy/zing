"""Local subject evidence, bounded reframing, and caption safety after the crop.

YuNet faces and optional OpenCV DNN subjects precede bundled HOG fallback. A stable compact
contrast component is only a saliency proxy (.25), not a semantic subject claim. Flat or
unavailable imagery uses the center (confidence zero). Nothing is downloaded.
"""

from __future__ import annotations

import math
import re
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path

from myzing.composition.framing import CropBounds, CropKeyframe, Framing
from .crop_planner import select_framing, track_framing
from .chooser import choose_layout, choose_stable, check_overlap
from .detector import LayoutError, YuNetDetector, load_cv2
from .tracking import build_tracks, appearance, stitch_tracks
from .vision import optional_detectors
from .types import (Box, CaptionEvent, Detection, FaceTrack, FrameDetections,
                    Keyframe, Mask, bounds, box_at, union)


def framing_mode(requested, source_width, source_height, output_width, output_height):
    """Candidate mode only; select_framing applies loss, subjects and scale policy."""
    same_aspect = abs(source_width / source_height / (output_width / output_height) - 1) <= .01
    return ("fit" if same_aspect else "reframe") if requested == "auto" else requested


def centered_framing(mode, source_width, source_height, width, height):
    divisor = math.gcd(width, height)
    rw, rh = width // divisor, height // divisor
    multiple = min(source_width // rw, source_height // rh)
    if multiple < 1 and mode not in ("fit", "blurfill", "zoomfill"):
        raise ValueError("source is too small for an integer crop at the output aspect")
    cw, ch = (source_width, source_height) if mode in ("fit", "blurfill", "zoomfill") else (rw * multiple, rh * multiple)
    cx, cy = source_width / 2, source_height / 2
    return Framing(mode, source_width, source_height, CropBounds(0, 0, source_width, source_height),
                   cw, ch, cx, cy, [CropKeyframe(0, cx, cy)] if mode in ("reframe", "zoomfill") else [],
                   max_velocity=min(cw, ch) * .5, method="center-heuristic",
                   warnings=["Center heuristic; no measured subject track. Confidence 0; review the crop."])


def saliency_detection(image, cv2, previous=None):
    """Bright contrast component, bounded away from flat/noisy full-frame masks."""
    import numpy as np

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    threshold = float(np.median(gray)) + 35
    mask = (gray > threshold).astype("uint8")
    count, labels, stats, centers = cv2.connectedComponentsWithStats(mask, 8)
    h, w = gray.shape
    choices = [i for i in range(1, count) if max(8, w * h * .0005) <= stats[i, 4] <= w * h * .35
               and stats[i, 2] * stats[i, 3] <= w * h * .35
               and stats[i, 4] >= .2 * stats[i, 2] * stats[i, 3]]
    previous_gray = cv2.cvtColor(previous, cv2.COLOR_BGR2GRAY) if previous is not None else None
    stable = []
    for i in choices:
        component = labels == i
        area = stats[i, 4] / (w * h)
        brightness = float(gray[component].mean())
        clipped_fraction = float((gray[component] >= 235).mean())
        # Large clipped highlights are not reliable objects even on the first
        # sample. Suppress bright regions that change substantially thereafter.
        # Small compact targets survive this test; brightness alone is not identity.
        changed = (float((cv2.absdiff(gray, previous_gray)[component] > 30).mean())
                   if previous_gray is not None and previous_gray.shape == gray.shape else 0)
        bgr = image[component].mean(axis=0)
        warm = bgr[2] > bgr[0] * 1.4 and bgr[2] > 170
        if (((brightness >= 225 or clipped_fraction >= .25) and area >= .01)
                or (area >= .005 and changed > .45 and (brightness > 190 or warm))):
            continue
        stable.append(i)
    choices = stable
    if not choices:
        return []
    # Stable area ranking with a weak center preference; no object identity.
    index = max(choices, key=lambda i: (stats[i, 4] / (1 + math.dist(centers[i] / (w, h), (.5, .5))), -i))
    x, y, bw, bh, _ = stats[index]
    return [Detection(Box(float(x / w), float(y / h), float(bw / w), float(bh / h)), .25)]


class PeopleDetector:
    """OpenCV's bundled HOG pedestrian SVM; no download or new runtime model."""

    def __init__(self, cv2):
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

    def detect(self, image):
        h, w = image.shape[:2]
        if h < 128 or w < 64:
            return []
        boxes, weights = self.hog.detectMultiScale(image, winStride=(8, 8), padding=(8, 8), scale=1.1)
        result = []
        for (x, y, bw, bh), weight in zip(boxes, weights):
            if float(weight) < .5:
                continue
            box = bounds(max(0, float(x / w)), max(0, float(y / h)),
                         min(1, float((x + bw) / w)), min(1, float((y + bh) / h)))
            result.append(Detection(box, .5))  # SVM score is not a calibrated probability.
        return result


MAX_SAMPLES = 600  # Decoded analysis frames per source, regular plus cut starts.
RANGE_MARGIN = .5  # Seconds sampled around each used trim for smoothing context.


def used_windows(ranges, duration, margin=RANGE_MARGIN):
    """Merge used source trims, widened by margin and clipped to the source."""
    windows = sorted((max(0.0, float(a) - margin), min(float(duration), float(b) + margin))
                     for a, b in ranges if b > a)
    merged = []
    for a, b in windows:
        if merged and a <= merged[-1][1] + 1e-9:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        elif b - a > 1e-6:
            merged.append((a, b))
    return merged


def _sample_window(video, folder, start, end, interval, limit):
    """Seek to start and keep frames at least interval apart, in source seconds.

    Input seeking keeps the clock relative to the container start, the same
    convention as the cut-start samples and the renderer's trims.
    """
    from myzing.study import proc

    folder.mkdir(parents=True, exist_ok=True)
    factor = "min(1,min(640/(iw*sar),640/ih))"
    filters = (f"select='isnan(prev_selected_t)+gte(t-prev_selected_t,{interval:.12f})',"
               f"scale=w='max(1,round(iw*sar*{factor}))':h='max(1,round(ih*{factor}))',setsar=1,showinfo")
    command = ["ffmpeg", "-hide_banner", "-loglevel", "info", "-nostdin", "-y",
               *(["-ss", f"{start:.9f}"] if start > 0 else []), "-t", f"{end - start:.9f}",
               "-protocol_whitelist", "file,pipe", "-i", str(video.resolve()), "-map", "0:v:0", "-vf", filters,
               "-fps_mode", "vfr", "-frames:v", str(limit), "-an", "-sn", str(folder / "frame-%04d.png")]
    try:
        result = proc.run(command, timeout=max(30, (end - start) * 3))
    except subprocess.TimeoutExpired as exc:
        raise LayoutError("FFmpeg sampling timed out; trim or remux the video") from exc
    if result.returncode:
        raise LayoutError(f"FFmpeg sampling failed: {proc.tail(result.stderr)}")
    times = [float(t) for t in re.findall(r"\bn:\s*\d+\s+pts:.*?\bpts_time:([\d.eE+-]+)", result.stderr)]
    files = sorted(folder.glob("frame-*.png"))
    if len(times) != len(files) or any(b <= a for a, b in zip(times, times[1:])):
        raise LayoutError("FFmpeg sample count/PTS mismatch; remux the video and retry")
    return [(start + t, path) for t, path in zip(times, files) if -1e-6 <= t < end - start]


def analyze_subjects(video: Path, duration: float, directory: Path, cut_times=(), ranges=None):
    """Sample the used source ranges (or the whole source) within MAX_SAMPLES.

    ranges are (src_in, src_out) trims; each is widened by RANGE_MARGIN. Long
    spans lower the regular sampling rate instead of failing, so source length
    alone never removes subject evidence.
    """
    from .debug import read_image
    from myzing.study import proc

    warnings = []
    try:
        cv2 = load_cv2()
    except LayoutError as exc:
        return [], [f"Subject analysis unavailable: {exc}; center heuristic, confidence 0."]
    try:
        detector = YuNetDetector(download=False)
    except LayoutError as exc:
        detector = None
        warnings.append(f"Face detector unavailable: {exc}")
    vision, model_notes = optional_detectors()
    warnings.extend(model_notes)
    people_detector = PeopleDetector(cv2) if not vision else None
    if not vision:
        warnings.append("Vision models unavailable: using bundled HOG people (uncalibrated confidence .5) and model-free saliency fallback.")
    directory.mkdir(parents=True, exist_ok=True)
    windows = used_windows([(0.0, duration)] if ranges is None else ranges, duration, 0 if ranges is None else RANGE_MARGIN)
    if not windows:
        return [], ["Subject analysis skipped: no used source range; center heuristic, confidence 0."]
    cuts = sorted({0.0, duration, *(t for t in cut_times if 0 < t < duration)})

    def window_of(time):
        return next((i for i, (a, b) in enumerate(windows) if a - 1e-9 <= time < b + 1e-9), None)

    # A sub-second shot can fall entirely between regular samples. Decode the
    # first frame of every used shot explicitly; never borrow the previous shot.
    def evenly(items, count):
        if count <= 0:
            return []
        if len(items) <= count:
            return list(items)
        return [items[round(j * (len(items) - 1) / max(1, count - 1))] for j in range(count)]

    cut_starts = [(i, t) for i, t in enumerate(cuts[:-1]) if window_of(t) is not None]
    if len(cut_starts) > MAX_SAMPLES // 2:
        keep = MAX_SAMPLES // 2
        warnings.append(f"{len(cut_starts)} used source cuts exceed the explicit cut-sample budget; "
                        f"{keep} evenly spaced cut starts were decoded, the rest rely on regular samples.")
        cut_starts = evenly(cut_starts, keep)
    # Every sampled range costs at least its first frame. Past the budget,
    # keep one frame from evenly spaced ranges rather than failing outright.
    sampled = windows
    if len(windows) > MAX_SAMPLES:
        sampled = evenly(windows, MAX_SAMPLES)
        warnings.append(f"{len(windows)} separate used ranges exceed the {MAX_SAMPLES}-frame analysis budget; "
                        f"one frame each from {MAX_SAMPLES} evenly spaced ranges was analyzed, the rest are unmeasured.")
    if len(cut_starts) + len(sampled) > MAX_SAMPLES:
        cut_starts = evenly(cut_starts, MAX_SAMPLES - len(sampled))
        warnings.append("Too many used ranges for explicit cut-start samples; shots rely on regular samples.")
    span = sum(b - a for a, b in sampled)
    budget = MAX_SAMPLES - len(cut_starts) - len(sampled)
    interval = max(.5, span / max(1, budget))
    if interval > .5 + 1e-9:
        warnings.append(f"Subjects sampled every {interval:.3g}s over {span:.1f}s of used source to stay within "
                        f"the {MAX_SAMPLES}-frame analysis budget; fast motion between samples can be missed.")
    try:
        with tempfile.TemporaryDirectory(prefix="framing-", dir=directory) as temp:
            samples = []
            for i, (a, b) in enumerate(sampled):
                samples += _sample_window(video, Path(temp) / f"window-{i:04d}", a, b, interval,
                                          math.floor((b - a) / interval) + 2)
            times = {t for t, _ in samples}
            for i, time in cut_starts:
                if time in times:
                    continue
                path = Path(temp) / f"cut-{i:04d}.png"
                result = proc.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-ss", f"{time:.9f}",
                                   "-protocol_whitelist", "file,pipe", "-i", str(video.resolve()),
                                   "-frames:v", "1", "-vf",
                                   "scale=w='max(1,round(iw*sar*min(1,min(640/(iw*sar),640/ih))))':h='max(1,round(ih*min(1,min(640/(iw*sar),640/ih))))',setsar=1",
                                   str(path)], timeout=30)
                if result.returncode or not path.exists():
                    raise LayoutError(f"Cannot sample source cut at {time:g}s: {proc.tail(result.stderr)}")
                samples.append((time, path))
            if len(samples) > MAX_SAMPLES:
                raise LayoutError(f"Source cuts plus regular samples exceed the {MAX_SAMPLES}-frame analysis limit")
            samples.sort()
            faces, people, salient = [], [], []
            semantic = {}
            previous, previous_scene = None, None
            last_objects = -math.inf
            for time, path in samples:
                image = read_image(path)
                # Temporal comparison resets at source cuts and between
                # separate used ranges; distant frames are not motion evidence.
                scene = (sum(t <= time for t in cuts) - 1, window_of(time))
                if scene != previous_scene:
                    previous = None
                detections = detector.detect(image) if detector else []
                detections = [replace(d, appearance=appearance(image, d.box), class_name="face", detector="yunet") for d in detections]
                persons = ([replace(d, class_name="person", detector="hog-fallback")
                            for d in people_detector.detect(image)] if people_detector else [])
                recognized = []
                for name, engine in list(vision.items()):
                    # YOLOX runs at source cut/range starts and at most about 1 fps.
                    if name == "objects" and scene == previous_scene and time - last_objects < 1 - 1e-6:
                        continue
                    try:
                        found = engine.detect(image)
                    except LayoutError as exc:
                        warnings.append(f"{name} disabled after inference failure: {exc}; HOG/saliency fallback enabled.")
                        del vision[name]
                        if not vision and people_detector is None:
                            people_detector = PeopleDetector(cv2)
                            persons = [replace(d, class_name="person", detector="hog-fallback")
                                       for d in people_detector.detect(image)]
                        continue
                    if name == "objects":
                        last_objects = time
                    recognized.extend(found)
                    # Separate classes and detectors preserve every raw detection
                    # and cannot join a dog to a nearby chair or suppress a face.
                    for label in set(d.class_name for d in found):
                        key = (name, label)
                        semantic.setdefault(key, []).append(FrameDetections(time, [d for d in found if d.class_name == label]))
                faces.append(FrameDetections(time, detections))
                people.append(FrameDetections(time, persons))
                salient.append(FrameDetections(time, [] if detections or persons or recognized else
                                               [replace(d, class_name="saliency", detector="contrast-fallback")
                                                for d in saliency_detection(image, cv2, previous)]))
                previous, previous_scene = image, scene
    except (LayoutError, OSError) as exc:
        diagnostic = re.sub(r" @ (?:0x)?[0-9a-fA-F]+", "", str(exc))
        return [], [f"Subject analysis failed: {diagnostic}; center heuristic, confidence 0."]
    tracks = []
    # At 2 fps bridge half a second, as before; a lowered budget rate bridges
    # one and a half intervals, but only inside one used range.
    gap = .5 if interval <= .5 + 1e-9 else min(10, interval * 1.5)
    for scene, (start, end) in enumerate(zip(cuts, cuts[1:])):
        # Segment by source shot AND by used range: no linking, smoothing,
        # endpoint hold or interpolation crosses a cut or an unused gap.
        for part, (window_start, window_end) in enumerate(windows):
            low, high = max(start, window_start), min(end, window_end)
            if high <= low:
                continue
            label = f"{scene}" if len(windows) == 1 else f"{scene}.{part}"
            groups = [(faces, "face", .025), (people, "person", .015), (salient, "saliency", .015)]
            groups += [(frames, ("person" if label == "person" else "object") + "-" + label.replace(" ", "_") + "-" + name, .015)
                       for (name, label), frames in sorted(semantic.items())]
            for frames, prefix, margin in groups:
                measured = [frame for frame in frames if low <= frame.time < high]
                if not measured:
                    continue
                track_gap = max(1., gap) if prefix.endswith("-objects") else gap
                fragments = build_tracks(measured, duration=high, smooth_radius=1, margin=margin, max_gap=track_gap)
                if prefix == "face":
                    fragments = stitch_tracks(fragments)
                for track in fragments:
                    a, b = max(low, track.keyframes[0].time), min(high, track.keyframes[-1].time)
                    # Keep the held endpoint on this side of a scene boundary.
                    b = max(a, b - 1e-7 if b == high == end and end < duration else b)
                    keys = [Keyframe(a, box_at(track.keyframes, a))]
                    keys += [k for k in track.keyframes if a < k.time < b]
                    if b > a:
                        keys.append(Keyframe(b, box_at(track.keyframes, b)))
                    tracks.append(replace(track, id=f"{prefix}-{label}-{track.id}", keyframes=keys))
    scope = "the whole source" if ranges is None else f"{len(windows)} used source range(s) plus {RANGE_MARGIN:g}s margins"
    warnings.append(f"Subjects sampled at up to 2 fps over {scope}, plus measured source-cut starts: YuNet faces, available MediaPipe person head regions, YOLOX-S int8 classes at about 1 fps and cut starts; HOG people (confidence .5) when neither model is available, then stable contrast objects; large clipped highlights and bright changing regions are suppressed. Detector scores are uncalibrated. Saliency "
                    "(confidence .25), center for gaps (confidence 0). Saliency is not object recognition; missed subjects remain possible.")
    return tracks, warnings


def visible_content(framing, output_width, output_height):
    if framing.mode not in ("fit", "blurfill", "zoomfill"):
        return Box(0, 0, 1, 1)
    w, h = framing.foreground_size(output_width, output_height)
    w, h = w / output_width, h / output_height
    if framing.mode == "fit":
        return Box((1 - w) / 2, (1 - h) / 2, w, h)
    x, y = framing.foreground_origin(output_width, output_height)
    return Box(x / output_width, y / output_height, w, h)


def output_box(box, framing, time, output_width, output_height):
    if framing.mode in ("fit", "blurfill"):
        content = visible_content(framing, output_width, output_height)
        if not framing.picture:
            return Box(content.x + box.x * content.width, content.y + box.y * content.height,
                       box.width * content.width, box.height * content.height)
        b = framing.bounds
        left, top = max(b.x, box.x*framing.source_width), max(b.y, box.y*framing.source_height)
        right, bottom = min(b.x+b.width, box.right*framing.source_width), min(b.y+b.height, box.bottom*framing.source_height)
        if right <= left or bottom <= top:
            return None
        return Box(content.x + (left-b.x)/b.width * content.width, content.y + (top-b.y)/b.height * content.height,
                   (right-left)/b.width * content.width, (bottom-top)/b.height * content.height)
    cx, cy = framing.center_at(time)
    x, y = cx - framing.width / 2, cy - framing.height / 2
    left = max(0, (box.x * framing.source_width - x - 2) / framing.width)
    top = max(0, (box.y * framing.source_height - y - 2) / framing.height)
    right = min(1, (box.right * framing.source_width - x + 2) / framing.width)
    bottom = min(1, (box.bottom * framing.source_height - y + 2) / framing.height)
    return _content_box(left, top, right, bottom, framing, output_width, output_height)


def _content_box(left, top, right, bottom, framing, width, height):
    if left >= right or top >= bottom:
        return None
    content = visible_content(framing, width, height)
    return Box(content.x + left * content.width, content.y + top * content.height,
               (right - left) * content.width, (bottom - top) * content.height)


def swept_output_box(box, framing, times, output_width, output_height):
    if framing.mode in ("fit", "blurfill"):
        return output_box(box, framing, times[0], output_width, output_height)
    centers = [framing.center_at(t) for t in times]
    # Bound before clipping: both endpoint boxes can be outside opposite edges
    # while the subject crosses the visible frame between them.
    left = max(0, (box.x * framing.source_width - max(x for x, _ in centers) + framing.width / 2 - 2) / framing.width)
    right = min(1, (box.right * framing.source_width - min(x for x, _ in centers) + framing.width / 2 + 2) / framing.width)
    top = max(0, (box.y * framing.source_height - max(y for _, y in centers) + framing.height / 2 - 2) / framing.height)
    bottom = min(1, (box.bottom * framing.source_height - min(y for _, y in centers) + framing.height / 2 + 2) / framing.height)
    return _content_box(left, top, right, bottom, framing, output_width, output_height)


DEFAULT_POP_SCALE = 1.18  # v1 word-timed captions pop each word to 118% (ASS fscx/fscy 118).


def default_ink_margin(width, height):
    """Output pixels added on every side of a measured default caption."""
    return max(4, min(width, height) / 180)


def measure_default_ink(caption, width, height, ffmpeg="ffmpeg"):
    """libass ink+outline extent of an unstyled caption at its largest render.

    Uses the positioned renderer's own measurement (Arial bold, short side/12,
    outline short side/270, the defaults both renderers draw) with size and
    outline scaled by DEFAULT_POP_SCALE, which bounds the v1 word pop and the
    100% full-text draw. Returns (left, top, right, bottom) offsets in output
    pixels from the anchor. Raises if FFmpeg/libass or the caption cannot be
    measured; callers then place the caption explicitly.
    """
    from myzing.composition import CaptionStyle
    from myzing.ffmpeg_capabilities import caption_filter
    from myzing.render.positioned_captions import _measure, caption_runs

    if caption.font is not None:
        raise ValueError("default measurement covers the unstyled default font only")
    short = min(width, height)
    style = CaptionStyle(max(24, round(short / 12)) * DEFAULT_POP_SCALE,
                         outline_width=max(2, round(short / 270)) * DEFAULT_POP_SCALE)
    renderer = caption_filter(ffmpeg)
    with tempfile.TemporaryDirectory(prefix="zing-caption-ink-") as temporary:
        directory = Path(temporary)
        (directory / "fonts").mkdir()
        return _measure(caption, style, "Arial", caption_runs(caption), width, height,
                        directory, ffmpeg, renderer, 1.0)


def default_caption_box(caption, width, height, ink):
    """Measured box of an unstyled caption at its preset anchor, plus margin.

    ink is measure_default_ink's anchor-relative extent. None when the
    widened box leaves the frame (the default would need layout to fit).
    """
    from myzing.render.captions import caption_anchor

    x, y = caption_anchor(caption.position, width, height)
    margin = default_ink_margin(width, height)
    left, top = (x + ink[0] - margin) / width, (y + ink[1] - margin) / height
    right, bottom = (x + ink[2] + margin) / width, (y + ink[3] + margin) / height
    if left < 0 or top < 0 or right > 1 or bottom > 1:
        return None
    return Box(left, top, right - left, bottom - top)


def fit_measured_ink(caption, layout, width, height, ffmpeg="ffmpeg", attempts=6):
    """Shrink a placed default-font caption until its measured ink fits the box.

    Measures exactly what generate_positioned_ass checks before drawing: libass
    ink+outline of the wrapped text at the style times layout.scale, plus the
    plate's 4 px-per-side padding. The box (already clear of masks and swept
    subjects) is never moved or enlarged. Returns the fitted extent, or None
    (style restored) if it cannot fit. Raises ValueError for a caption it cannot
    measure (custom font, template, non-ASS backend) and RuntimeError/OSError
    when FFmpeg/libass is missing.
    """
    from myzing.ffmpeg_capabilities import caption_filter
    from myzing.render.positioned_captions import _measure, caption_runs

    if caption.font is not None or caption.template is not None or caption.backend != "ass" or caption.style is None:
        raise ValueError("measured fitting covers styled default-font ASS captions only")
    boxes = [key.box for key in layout.as_path()]
    box_width, box_height = min(b.width for b in boxes) * width, min(b.height for b in boxes) * height
    renderer = caption_filter(ffmpeg)
    original = caption.style
    with tempfile.TemporaryDirectory(prefix="zing-caption-fit-") as temporary:
        directory = Path(temporary)
        (directory / "fonts").mkdir()
        for _ in range(attempts):
            scale = layout.scale
            style = replace(caption.style, size=caption.style.size * scale,
                            outline_width=caption.style.outline_width * scale)
            ink = _measure(caption, style, "Arial", caption_runs(caption), width, height,
                           directory, ffmpeg, renderer, 1.0)
            padding = max(4 * scale if style.box_color is not None else 0,
                          style.highlight_box_padding * scale if style.highlight_box_color else 0)
            ink_width, ink_height = ink[2] - ink[0], ink[3] - ink[1]
            if ink_width + 2 * padding <= box_width + 1 and ink_height + 2 * padding <= box_height + 1:
                return ink
            factor = .98 * min((box_width + 1 - 2 * padding) / ink_width, (box_height + 1 - 2 * padding) / ink_height, 1)
            if factor <= 0:
                break
            caption.style = replace(caption.style, size=max(1, caption.style.size * factor),
                                    outline_width=caption.style.outline_width * factor)
    caption.style = original
    return None


def measure_styled_ink(caption, width, height):
    """Measure a phone phrase before placement, using its actual font/shaping."""
    from myzing.ffmpeg_capabilities import caption_filter
    from myzing.render.positioned_captions import _measure, caption_runs
    from myzing.render.font_files import private_font, ass_em_scale
    with tempfile.TemporaryDirectory(prefix="zing-phone-ink-") as temporary:
        directory = Path(temporary)
        (directory / "fonts").mkdir()
        name, em = "Arial", 1.
        if caption.font:
            data = Path(caption.font.path).read_bytes()
            name, payload = private_font(data)
            em = ass_em_scale(data)
            (directory / "fonts" / f"{name}.ttf").write_bytes(payload)
        return _measure(caption, caption.style, name, caption_runs(caption), width, height,
                        directory, "ffmpeg", caption_filter("ffmpeg"), em)


HOME_BOTTOM = .75  # Baseline (share of output height) when no survey anchor exists.


def _vertical_style(style, plan, minimum_size=0):
    """The style place_captions gives a vertical caption, without mutating it."""
    from myzing.composition import CaptionStyle
    short = min(plan.width, plan.height)
    style = style or CaptionStyle(max(1, short / 18))
    style = replace(style, outline_width=max(style.outline_width, min(20, short / 270)),
                    box_color=style.box_color or "#111111")
    return replace(style, size=max(style.size, minimum_size)) if minimum_size else style


def _band_requirement(lines, style, plan):
    """Estimated band height share for a complete wrapped event, outline and plates."""
    plate = max(14, 2 * style.highlight_box_padding + 6 if style.highlight_box_color else 0)
    return (max(1, len(lines)) * style.size * 1.4 + style.outline_width * 2 + plate) / plan.height / .8


def _plate_padding(style):
    return style.outline_width * 2 + max(14 if style.box_color else 6,
                                         2 * style.highlight_box_padding + 6 if style.highlight_box_color else 0)


def _styled_ink(caption, text, style, plan, cache):
    key = (text, style.size, style.outline_width, str(caption.font), caption.all_caps)
    if key not in cache:
        try:
            cache[key] = measure_styled_ink(replace(caption, text=text, style=style), plan.width, plan.height)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
            cache[key] = None
    return cache[key]


def _wrap(caption, style, plan, max_width, cache=None):
    """Wrap words for a box max_width wide (share of output width).

    With a measurement cache (phone captions), try fuller lines and keep them
    when the libass ink plus plate fits, then balance the line lengths. Without
    one, or when ink is unmeasurable (no FFmpeg), keep the conservative
    0.8 em-per-character estimate.
    """
    import textwrap
    words = " ".join(caption.text.split())

    def at(columns):
        return textwrap.wrap(words, width=max(1, columns), break_long_words=False, break_on_hyphens=False)

    if cache is not None:
        for factor in (.55, .65):
            lines = at(int(max_width * plan.width / (style.size * factor)))
            ink = _styled_ink(caption, "\n".join(lines), style, plan, cache)
            if ink is None:
                break
            if ink[2] - ink[0] + _plate_padding(style) <= max_width * plan.width:
                columns = max(len(line) for line in lines)
                while columns > 1 and len(at(columns - 1)) == len(lines):
                    columns -= 1
                return at(columns)
    return at(int(max_width * plan.width / (style.size * .8)))


def raise_for_lower_band(plan, insets, source_dimensions=None, cache=None):
    """Raise a vertical blurfill/zoomfill sharp picture to open its lower caption band.

    The lower blur band below a centered picture mostly sits inside the bottom
    platform-UI reserve. When every caption shown over a clip would fit the
    band after lifting the picture by the smallest even amount, and the
    picture top stays below the top reserve, lift it; otherwise leave it.
    """
    from .readability import phone_minimum
    phone = plan.brief is not None and plan.brief.caption_mode == "phone"
    inset_left, inset_top, inset_right, inset_bottom = insets
    band_width = min(.84, (1 - inset_left - inset_right) * .94)
    cache = {} if cache is None else cache

    def requirement(caption):
        style = _vertical_style(caption.style, plan, phone_minimum(plan, caption, source_dimensions) if phone else 0)
        return _band_requirement(_wrap(caption, style, plan, band_width, cache if phone else None), style, plan)

    for clip in plan.clips:
        f = clip.framing
        if f is None or f.mode not in ("blurfill", "zoomfill") or f.foreground_top is not None:
            continue
        w, h = f.foreground_size(plan.width, plan.height)
        captions = [c for c in plan.captions if c.start < clip.timeline_end and c.end > clip.timeline_start]
        if w < plan.width * .99 or not captions:
            continue
        need = max(requirement(c) for c in captions)
        _, y = f.foreground_origin(plan.width, plan.height)
        band = 1 - inset_bottom - (y + h) / plan.height
        if band >= need:
            continue
        lift = math.ceil((need - band) * plan.height / 2) * 2
        if y - lift < math.ceil(inset_top * plan.height / 2) * 2:
            continue
        clip.framing = replace(f, foreground_top=(y - lift) / plan.height, warnings=[
            *f.warnings, f"Sharp picture raised {lift}px so complete captions fit the lower blur band "
            f"above the {inset_bottom:.0%} bottom UI reserve."])


def _anchor(box, region):
    """(center x, edge y): the top edge hangs in the lower band, else the baseline."""
    return box.center[0], box.y if region == "lower blur band" else box.bottom


def place_captions(plan, subjects, source_dimensions=None, *, keep_safe_defaults=False, _survey=False):
    """Static caption boxes avoid swept subject envelopes on the output clock.

    Captions keep one alignment, and one anchor per shot and placement region:
    the median of where each event would sit on its own (nearest free space to
    the lower third), or the lower band's top edge. An event moves off it only
    when a subject or reserve would be covered, and then by the smallest move.

    Conservative source envelopes plus crop extrema enclose motion continuously,
    including between samples; this checks supplied tracks, not detector recall.

    keep_safe_defaults leaves an unstyled, unplaced default-font caption
    untouched when its measured default box (libass ink at the 118% word-pop
    size plus default_ink_margin) passes the same subject, content and
    output-reserve checks. Layout is then attached only where it changes
    placement, which keeps such plans representable as v1 EDLs. Without
    FFmpeg/libass the caption is placed.
    """
    from myzing.composition.timebase import frame_index, frame_time
    from myzing.render.positioned_captions import caption_frame_timing
    from myzing.composition.aspects import aspect_for, SAFE_INSETS
    from myzing.composition import CaptionStyle
    import textwrap
    inset_left, inset_top, inset_right, inset_bottom = SAFE_INSETS[aspect_for(plan.width, plan.height)]
    frame_limit = frame_index(max(c.timeline_end for c in plan.clips), plan.fps, rounding="nearest")
    source_dimensions = source_dimensions or {}
    if len({c.alignment for c in plan.captions}) > 1:
        # Snapping between left and centered phrases reads as jitter.
        for caption in plan.captions:
            caption.alignment = "center"
        plan.warnings.append("Mixed caption alignments were centered so every event shares one anchor.")

    def shot(caption):
        return next((i for i, c in enumerate(plan.clips) if c.timeline_start <= caption.start < c.timeline_end),
                    len(plan.clips) - 1)

    homes = {}
    if not _survey and len(plan.captions) > 1:
        # Survey pass: place each event independently on a copy, then anchor
        # every event at the typical free position instead of a fixed point.
        from copy import deepcopy
        from statistics import median
        survey = deepcopy(plan)
        points = {}
        try:
            place_captions(survey, subjects, source_dimensions, keep_safe_defaults=keep_safe_defaults, _survey=True)
        except ValueError:
            survey.captions = []  # The stable pass below reports the problem.
        for caption in survey.captions:
            if caption.layout is not None and caption.layout.overlap.safe and caption.layout.box is not None:
                region = caption.layout.overlap.scope.split("; ")[1]
                points.setdefault((shot(caption), region), []).append(_anchor(caption.layout.box, region))
        homes = {region: (median(x for x, _ in values), median(y for _, y in values))
                 for region, values in points.items()}
    stable = not _survey
    layouts = []
    ink_cache = {}
    vertical = plan.height > plan.width
    insets = (inset_left, inset_top, inset_right, inset_bottom)
    if vertical:
        raise_for_lower_band(plan, insets, source_dimensions, ink_cache)
    previous_anchor, previous_key = None, None

    def reserve(region):
        # Include a small output edge inset as well as every padding bar.
        edges = (max(inset_left, region.x), max(inset_top, region.y),
                 min(1 - inset_right, region.right), min(1 - inset_bottom, region.bottom))
        left, top, right, bottom = edges
        return edges, [Mask(name, box) for name, box in
                       [("left", Box(0, 0, left, 1)), ("right", Box(right, 0, 1 - right, 1)),
                        ("top", Box(0, 0, 1, top)), ("bottom", Box(0, bottom, 1, 1 - bottom))]]

    for caption in plan.captions:
        first, last, _, _ = caption_frame_timing(caption, plan.fps, frame_limit)
        visible_start, visible_end = float(frame_time(first, plan.fps)), float(frame_time(last, plan.fps))
        obstacles, contents = [], []
        for clip in plan.clips:
            actual_start = float(frame_time(frame_index(clip.timeline_start, plan.fps, rounding="nearest"), plan.fps))
            actual_end = float(frame_time(frame_index(clip.timeline_end, plan.fps, rounding="nearest"), plan.fps))
            start, end = max(visible_start, actual_start), min(visible_end, actual_end)
            if end <= start:
                continue
            f = clip.framing
            if f is None:
                if clip.asset_id not in source_dimensions:
                    continue
                f = centered_framing("fit", *source_dimensions[clip.asset_id], plan.width, plan.height)
            contents.append(visible_content(f, plan.width, plan.height))
            local_start, local_end = start - actual_start, end - actual_start
            crop_times = [local_start, local_end, *[k.time for k in f.keyframes if local_start < k.time < local_end]]
            for track in subjects.get(clip.asset_id, []):
                a = max(clip.source_at(clip.timeline_start + min(clip.duration, local_start)), track.keyframes[0].time)
                b = min(clip.source_at(clip.timeline_start + min(clip.duration, local_end)), track.keyframes[-1].time)
                if a >= b:
                    continue
                source_box = union([box_at(track.keyframes, a), box_at(track.keyframes, b),
                                    *[k.box for k in track.keyframes if a < k.time < b]])
                box = swept_output_box(source_box, f, crop_times, plan.width, plan.height)
                if box is not None:
                    obstacles.append(FaceTrack(f"{clip.id}-{track.id}", [Keyframe(caption.start, box),
                                              Keyframe(caption.end, box)], track.confidence))
        content = bounds(max((b.x for b in contents), default=0), max((b.y for b in contents), default=0),
                         min((b.right for b in contents), default=1), min((b.bottom for b in contents), default=1))
        (left, top, right, bottom), masks = reserve(content)
        if (keep_safe_defaults and caption.layout is None and caption.style is None and caption.font is None
                and caption.template is None and caption.backend == "ass" and caption.alignment == "center"):
            # Decide on measured libass ink at the largest rendered size, never
            # an estimate: neither renderer re-checks an unplaced caption. This
            # runs before vertical restyling, so a safe 9:16 default stays v1.
            try:
                ink = measure_default_ink(caption, plan.width, plan.height)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                ink = None  # Unmeasurable: place it explicitly below.
            default = default_caption_box(caption, plan.width, plan.height, ink) if ink else None
            if default is not None and check_overlap([Keyframe(caption.start, default), Keyframe(caption.end, default)],
                                                     obstacles, masks).safe:
                continue
        if vertical:
            caption.style = _vertical_style(caption.style, plan)
        phone = plan.brief is not None and plan.brief.caption_mode == "phone"
        minimum_size = 0
        if phone:
            from .readability import phone_minimum
            minimum_size = phone_minimum(plan, caption, source_dimensions)
            style = caption.style or CaptionStyle(minimum_size, outline_width=2, box_color="#111111")
            caption.style = replace(style, size=max(style.size, minimum_size))
        placement_region = "sharp picture"
        if vertical and contents and all(b.width > .99 for b in contents):
            # Prefer a band only when the entire static caption can fit there
            # throughout its event. A caption spanning differently framed shots
            # uses the intersection of their bands, never crosses the seam.
            band_width = min(.84, (1 - inset_left - inset_right) * .94)
            required = _band_requirement(_wrap(caption, caption.style, plan, band_width, ink_cache if phone else None),
                                         caption.style, plan)
            bands = [(max(b.bottom for b in contents), 1 - inset_bottom, "lower blur band"),
                     (inset_top, min(b.y for b in contents), "upper blur band")]
            if phone:
                # A one-word group should not jump above the speaker while its
                # neighbouring two-line group sits below. Keep the lower band
                # preference, then use the face-safe sharp-picture search.
                bands = bands[:1]
            # Fit's black padding remains outside content; only blurred modes
            # invite a caption into the surrounding picture.
            blurred = all(c.framing and c.framing.mode in ("blurfill", "zoomfill")
                          for c in plan.clips if c.timeline_start < visible_end and c.timeline_end > visible_start)
            if blurred:
                for band_top, band_bottom, name in bands:
                    if band_bottom - band_top >= required:
                        (left, top, right, bottom), masks = reserve(bounds(0, band_top, 1, band_bottom))
                        placement_region = name
                        break
        if caption.style is None:
            caption.style = CaptionStyle(max(1, min(plan.width, plan.height) / 18),
                                         outline_width=min(plan.width, plan.height) / 540)
        max_width, max_height = min(.84, (right - left) * .94), min(.26 if phone else .16, (bottom - top) * .8)
        # Reserve the text's estimated extent, not 84% of the frame for every
        # word. Oversized empty boxes make otherwise safe close-ups infeasible.
        words = " ".join(caption.text.split())

        def wrap(style):
            return _wrap(caption, style, plan, max_width, ink_cache if phone else None)

        def extent(lines, style):
            padding = _plate_padding(style)
            if phone:
                ink = _styled_ink(caption, "\n".join(lines), style, plan, ink_cache)
                if ink:
                    return ink[2]-ink[0]+padding, ink[3]-ink[1]+padding
            return (max(len(line) for line in lines) * style.size * .8 + padding,
                    len(lines) * style.size * 1.4 + padding)

        base = caption.style
        lines = wrap(base)
        ink_width, ink_height = extent(lines, base)
        shrink = max(1, ink_width / (max_width * plan.width), ink_height / (max_height * plan.height))
        if shrink > 1:
            # Shrinking a narrow wrap on both axes can leave a tall clause far
            # below readable size (a 9:16 source fit into 16:9). Re-wrap each
            # smaller size and keep the largest whose estimated extent fits;
            # the plain proportional shrink remains the floor.
            scale = 1 / shrink
            for step in range(1, 80):
                candidate = .97 ** step
                if candidate <= scale:
                    break
                style = replace(base, size=max(1, base.size * candidate), outline_width=base.outline_width * candidate)
                trial = wrap(style)
                trial_width, trial_height = extent(trial, style)
                if trial_width <= max_width * plan.width and trial_height <= max_height * plan.height:
                    scale, lines = candidate, trial
                    break
            caption.style = replace(base, size=max(1, base.size * scale), outline_width=base.outline_width * scale)
            ink_width, ink_height = extent(lines, caption.style)
        caption.text = "\n".join(lines)
        event = CaptionEvent(caption.id, caption.start, caption.end,
                             min(max_width, ink_width / plan.width), min(max_height, ink_height / plan.height), "lower-third")
        prior = caption.layout
        checked = check_overlap(prior.as_path(), obstacles, masks) if prior else None
        # A stable anchor: centered in the region, hanging below the picture
        # in the lower band, else on one baseline. Move only when a face or
        # reserve would be covered, and then by the smallest move.
        edge = "top" if placement_region == "lower blur band" else "bottom"
        home = ((left + right) / 2, top if edge == "top" else min(bottom, max(top, HOME_BOTTOM)))
        key = (shot(caption), placement_region)
        if edge == "bottom" and key in homes:
            home = homes[key]
        previous = previous_anchor if previous_key == key else None

        def choose(event):
            scales = tuple(s for s in (.85, .7, .55) if not phone or caption.style.size*s >= minimum_size)
            chosen = choose_stable(event, obstacles, masks, home=home, previous=previous, edge=edge,
                                   aspect=plan.height / plan.width, shrink_scales=scales,
                                   shrink_penalty=min(plan.width, plan.height) / plan.width) if stable else None
            return chosen or choose_layout([event], obstacles, masks, allow_motion=False, shrink_scales=scales).events[0]
        if prior and checked.safe:
            layout = replace(prior, overlap=checked)
            boxes = [key.box for key in prior.as_path()]
            event = replace(event, width=min(b.width for b in boxes), height=min(b.height for b in boxes))
        else:
            layout = choose(event)
        def moved(candidate):
            """Distance from where the caption is (or home), in output-width units."""
            if candidate.box is None:
                return math.inf
            point = previous or home
            y = candidate.box.y if edge == "top" else candidate.box.bottom
            return math.hypot(candidate.box.center[0] - point[0], (y - point[1]) * plan.height / plan.width)

        # A move larger than a 15%-smaller box is worth (see choose_stable)
        # first tries narrower reflows that may fit beside the subject.
        far = .15 * min(plan.width, plan.height) / plan.width
        if not layout.overlap.safe or (stable and moved(layout) > far):
            # A long single line can block a usable side gap on a close-up.
            # Reflow into narrower boxes before declaring the layout infeasible
            # or jumping across the frame. Every alternative still receives the
            # same continuous safety check.
            original_text, original_style = caption.text, caption.style
            best = (layout, original_text, original_style) if layout.overlap.safe else None
            for fraction in (.7, .5, .35):
                trial_width = max_width * fraction
                trial_height = min(.32, (bottom - top) * .8)
                caption.style = original_style
                columns = max(1, int(trial_width * plan.width / (caption.style.size * .8)))
                caption.text = "\n".join(textwrap.wrap(" ".join(original_text.split()), width=columns,
                                                     break_long_words=False, break_on_hyphens=False))
                lines = caption.text.splitlines()
                ink_width, ink_height = extent(lines, caption.style)
                shrink = max(1, ink_width / (trial_width * plan.width), ink_height / (trial_height * plan.height))
                caption.style = replace(caption.style, size=max(1, caption.style.size / shrink),
                                        outline_width=caption.style.outline_width / shrink)
                if phone and caption.style.size < minimum_size:
                    continue
                ink_width, ink_height = extent(lines, caption.style)
                trial = replace(event, width=min(trial_width, ink_width / plan.width),
                                height=min(trial_height, ink_height / plan.height))
                alternative = choose(trial)
                # A safe layout is only traded for a closer one that stays
                # readable: at most three lines and no deeper than one shrink step.
                readable = best is None or (alternative.scale >= .85 - 1e-9 and len(lines) <= 3
                                            and caption.style.size >= original_style.size * .85 - 1e-9)
                if alternative.overlap.safe and readable and (best is None or moved(alternative) < moved(best[0]) - 1e-9):
                    best = (alternative, caption.text, caption.style)
                    if moved(alternative) <= far:
                        break
            if best is None:
                caption.text, caption.style = original_text, original_style
            else:
                layout, caption.text, caption.style = best
        # Full-body detections can leave no text-sized gap in the sharp
        # picture. Reuse an existing padding band before declaring failure;
        # keep the source/crop unchanged and never waive the overlap check.
        semantic = any(o.detector in ("yolox-s-int8", "mediapipe-person-head")
                       for tracks in subjects.values() for t in tracks for o in t.observations)
        if not layout.overlap.safe and semantic and contents and all(b.width > .99 for b in contents):
            for band_top, band_bottom, name in (
                (max(b.bottom for b in contents), 1 - inset_bottom, "lower padding band"),
                (inset_top, min(b.y for b in contents), "upper padding band"),
            ):
                if band_bottom <= band_top:
                    continue
                edges, band_masks = reserve(bounds(0, band_top, 1, band_bottom))
                scales = tuple(s for s in (.85, .7, .55) if not phone or caption.style.size*s >= minimum_size)
                alternative = choose_stable(event, obstacles, band_masks,
                                            home=((edges[0] + edges[2])/2, edges[3]),
                                            edge="bottom", aspect=plan.height/plan.width,
                                            shrink_scales=scales)
                if alternative is not None and alternative.overlap.safe:
                    layout, masks, placement_region = alternative, band_masks, name
                    layout = replace(layout, warnings=[*layout.warnings,
                        "Detected subjects block the sharp picture; caption moved to an existing padding band."])
                    break
        scope = (f"output crop; {placement_region}; aspect UI insets, swept supplied subject tracks and "
                 "visible-content bounds; detector recall unverified")
        if not obstacles:
            scope += "; faces unmeasured in this interval"
        if vertical or (caption.style and caption.style.highlight_box_color):
            # Vertical bands are tight and the plate adds padding: verify the
            # positioned renderer's own libass measurement fits the placed box
            # (and so its masks), shrinking the text if the estimate was short.
            try:
                if fit_measured_ink(caption, layout, plan.width, plan.height) is not None:
                    scope += "; measured libass ink+plate fits the box"
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                pass  # Unmeasurable here (custom font, no FFmpeg/libass): the renderer still measures.
        layout = replace(layout, overlap=replace(layout.overlap, scope=scope))
        caption.layout = layout
        if layout.overlap.safe and layout.box is not None:
            previous_anchor = (layout.box.center[0], layout.box.y if edge == "top" else layout.box.bottom)
            previous_key = key
        if phone and caption.style.size * layout.scale < minimum_size - .01:
            raise ValueError(f"Phone captions need review: {caption.id} cannot fit safely at the minimum "
                             f"{minimum_size:.1f}px ({minimum_size/plan.width:.1%} of output width). "
                             "Shorten the phrase or choose framing with more caption space.")
        layouts.append(layout.to_dict())
    return layouts
