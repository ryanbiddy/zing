"""Local subject evidence, bounded reframing, and caption safety after the crop.

YuNet faces take priority, followed by bundled HOG people. A stable compact
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
from .chooser import choose_layout, check_overlap
from .detector import LayoutError, YuNetDetector, load_cv2
from .tracking import build_tracks
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
    if multiple < 1 and mode not in ("fit", "blurfill"):
        raise ValueError("source is too small for an integer crop at the output aspect")
    cw, ch = (source_width, source_height) if mode in ("fit", "blurfill") else (rw * multiple, rh * multiple)
    cx, cy = source_width / 2, source_height / 2
    return Framing(mode, source_width, source_height, CropBounds(0, 0, source_width, source_height),
                   cw, ch, cx, cy, [CropKeyframe(0, cx, cy)] if mode == "reframe" else [],
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
    people_detector = PeopleDetector(cv2)
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
            previous, previous_scene = None, None
            for time, path in samples:
                image = read_image(path)
                # Temporal comparison resets at source cuts and between
                # separate used ranges; distant frames are not motion evidence.
                scene = (sum(t <= time for t in cuts) - 1, window_of(time))
                if scene != previous_scene:
                    previous = None
                detections = detector.detect(image) if detector else []
                persons = people_detector.detect(image)
                faces.append(FrameDetections(time, detections))
                people.append(FrameDetections(time, persons))
                salient.append(FrameDetections(time, [] if detections or persons else saliency_detection(image, cv2, previous)))
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
            for frames, prefix, margin in ((faces, "face", .025), (people, "person", .015), (salient, "saliency", .015)):
                measured = [frame for frame in frames if low <= frame.time < high]
                if not measured:
                    continue
                for track in build_tracks(measured, duration=high, smooth_radius=1, margin=margin, max_gap=gap):
                    a, b = max(low, track.keyframes[0].time), min(high, track.keyframes[-1].time)
                    # Keep the held endpoint on this side of a scene boundary.
                    b = max(a, b - 1e-7 if b == high == end and end < duration else b)
                    keys = [Keyframe(a, box_at(track.keyframes, a))]
                    keys += [k for k in track.keyframes if a < k.time < b]
                    if b > a:
                        keys.append(Keyframe(b, box_at(track.keyframes, b)))
                    tracks.append(replace(track, id=f"{prefix}-{label}-{track.id}", keyframes=keys))
    scope = "the whole source" if ranges is None else f"{len(windows)} used source range(s) plus {RANGE_MARGIN:g}s margins"
    warnings.append(f"Subjects sampled at up to 2 fps over {scope}, plus measured source-cut starts: YuNet faces, bundled HOG people (confidence .5), then stable contrast objects; large clipped highlights and bright changing regions are suppressed. Saliency "
                    "(confidence .25), center for gaps (confidence 0). Saliency is not object recognition; missed subjects remain possible.")
    return tracks, warnings


def track_framing(framing, clip, tracks):
    if framing.mode != "reframe":
        return framing
    # Keep a single face while available. Detector confidence measures whether
    # it is a face, not editorial prominence: prefer area with a center bias.
    times = sorted({0.0, clip.duration, *[k.time - clip.src_in for t in tracks for k in t.keyframes
                                       if clip.src_in < k.time < clip.src_out]})
    if len(times) > 256:
        times = [clip.duration * i / 255 for i in range(256)]
    targets, confidences, methods = [], [], set()
    previous_id = None
    for time in times:
        source_time = min(clip.src_out - 1e-7, clip.source_at(clip.timeline_start + time))
        active = [t for t in tracks if t.keyframes[0].time <= source_time <= t.keyframes[-1].time]
        faces = [t for t in active if not t.id.startswith(("saliency-", "person-"))]
        people = [t for t in active if t.id.startswith("person-")]
        choices = faces or people or active
        selected = next((t for t in choices if t.id == previous_id), None)
        if selected is None and choices:
            def prominence(track):
                box = box_at(track.keyframes, source_time)
                return (box.width * box.height * (.5 + track.confidence) /
                        (1 + math.dist(box.center, (.5, .5))), track.id)
            selected = max(choices, key=prominence)
        if selected:
            x, y = box_at(selected.keyframes, source_time).center
            x, y = x * framing.source_width, y * framing.source_height
            previous_id = selected.id
            confidences.append(selected.confidence)
            methods.add("saliency" if selected.id.startswith("saliency-") else
                        "people-hog" if selected.id.startswith("person-") else "yunet")
        else:
            x, y = targets[-1] if targets else (framing.source_width / 2, framing.source_height / 2)
            confidences.append(0.0)
            methods.add("center/hold")
        b = framing.bounds
        targets.append((min(b.x + b.width - framing.width / 2, max(b.x + framing.width / 2, x)),
                        min(b.y + b.height - framing.height / 2, max(b.y + framing.height / 2, y))))
    # Centered three-sample mean suppresses detector jitter; clamp each step so
    # the smoothstep curve's peak Euclidean velocity respects the contract.
    smooth = [targets[i] if i in (0, len(targets) - 1) else
              tuple(sum(p[axis] for p in targets[i - 1:i + 2]) / 3 for axis in (0, 1))
              for i in range(len(targets))]
    keys = []
    for time, (x, y) in zip(times, smooth):
        if keys:
            previous = keys[-1]
            distance = math.hypot(x - previous.center_x, y - previous.center_y)
            limit = framing.max_velocity * (time - previous.time) / 1.5
            factor = min(1, limit / distance) if distance else 1
            x, y = previous.center_x + (x - previous.center_x) * factor, previous.center_y + (y - previous.center_y) * factor
        keys.append(CropKeyframe(time, x, y))
    warnings = ["Crop follows sampled geometric evidence; 2 fps sampling, smoothing and velocity limiting can lag fast motion."]
    if not methods <= {"yunet", "people-hog"}:
        warnings.append("Saliency/center fallback used with lower confidence; subject identity and complete visibility are unverified.")
    return replace(framing, center_x=keys[0].center_x, center_y=keys[0].center_y,
                   keyframes=keys, confidence=min(confidences), method="+".join(sorted(methods)), warnings=warnings)


def visible_content(framing, output_width, output_height):
    if framing.mode not in ("fit", "blurfill"):
        return Box(0, 0, 1, 1)
    scale = min(output_width / framing.source_width, output_height / framing.source_height)
    # Same force_divisible_by=2 floor as the fit graph.
    w = max(2, math.floor(framing.source_width * scale / 2) * 2) / output_width
    h = max(2, math.floor(framing.source_height * scale / 2) * 2) / output_height
    return Box((1 - w) / 2, (1 - h) / 2, w, h)


def select_framing(requested, sw, sh, width, height, clip, tracks, *, max_upscale=2.5, fps=30):
    """Auto: <=2.5x, >=30% area, >=60% height, >=90% tracked coverage.

    Full subject coverage is checked on every output frame against supplied
    tracks, not against ground truth. Missing evidence permits only <=10% loss.
    """
    mode = framing_mode(requested, sw, sh, width, height)
    if mode in ("fit", "blurfill"):
        return replace(centered_framing(mode, sw, sh, width, height), max_upscale=max_upscale,
                       method="aspect-match" if requested == "auto" else "user-specified",
                       warnings=["Entire source picture retained; subject detection still limits caption safety."])
    try:
        candidate = replace(centered_framing(mode, sw, sh, width, height), max_upscale=max_upscale)
    except ValueError:
        if requested != "auto":
            raise
        return replace(centered_framing("blurfill", sw, sh, width, height), max_upscale=max_upscale,
                       warnings=["Auto selected blurfill: source too small for an integer crop at this aspect."])
    candidate = track_framing(candidate, clip, tracks)
    if requested != "auto":
        return candidate
    area = candidate.width * candidate.height / (sw * sh)
    height_fraction = candidate.height / sh
    upscale = max(width / candidate.width, height / candidate.height)
    reasons = []
    if upscale > max_upscale + 1e-9:
        reasons.append(f"crop enlargement {upscale:.3f}x exceeds {max_upscale:g}x")
    if area < .30:
        reasons.append(f"retained area {area:.1%} is below 30%")
    if height_fraction < .60:
        reasons.append(f"retained source height {height_fraction:.1%} is below 60%")
    coverage, missing = 1.0, False
    # Pixel-window evaluation on the actual CFR clock; subpixel rounding gets
    # the same two-source-pixel allowance used by caption envelopes.
    for frame in range(max(1, math.ceil(clip.duration * fps))):
        local = min(clip.duration - 1e-7, frame / fps)
        source_time = clip.source_at(clip.timeline_start + local)
        active = [t for t in tracks if t.keyframes[0].time <= source_time <= t.keyframes[-1].time]
        people = [t for t in active if not t.id.startswith("saliency-")]
        active = people or active
        if not active:
            missing = True
            continue
        cx, cy = candidate.center_at(local)
        left, top = cx - candidate.width / 2 + 2, cy - candidate.height / 2 + 2
        right, bottom = cx + candidate.width / 2 - 2, cy + candidate.height / 2 - 2
        for track in active:
            b = box_at(track.keyframes, source_time)
            iw = max(0, min(right, b.right * sw) - max(left, b.x * sw))
            ih = max(0, min(bottom, b.bottom * sh) - max(top, b.y * sh))
            coverage = min(coverage, iw * ih / (b.width * sw * b.height * sh))
    if coverage < .90:
        reasons.append(f"tracked-subject coverage {coverage:.1%} is below 90%")
    if missing and area < .90:
        reasons.append("subject evidence has gaps while crop loss exceeds 10%")
    decision = (f"Auto crop assessment: retained area {area:.1%}, height {height_fraction:.1%}, "
                f"tracked coverage {coverage:.1%}, enlargement {upscale:.3f}x; detector recall unverified.")
    if reasons:
        return replace(centered_framing("blurfill", sw, sh, width, height), max_upscale=max_upscale,
                       method="auto-blurfill", confidence=candidate.confidence,
                       warnings=["Auto selected blurfill: " + "; ".join(reasons) + ".", decision])
    return replace(candidate, warnings=[*candidate.warnings, "Auto selected reframe. " + decision])


def output_box(box, framing, time, output_width, output_height):
    if framing.mode in ("fit", "blurfill"):
        content = visible_content(framing, output_width, output_height)
        return Box(content.x + box.x * content.width, content.y + box.y * content.height,
                   box.width * content.width, box.height * content.height)
    cx, cy = framing.center_at(time)
    x, y = cx - framing.width / 2, cy - framing.height / 2
    left = max(0, (box.x * framing.source_width - x - 2) / framing.width)
    top = max(0, (box.y * framing.source_height - y - 2) / framing.height)
    right = min(1, (box.right * framing.source_width - x + 2) / framing.width)
    bottom = min(1, (box.bottom * framing.source_height - y + 2) / framing.height)
    return bounds(left, top, right, bottom) if left < right and top < bottom else None


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
    return bounds(left, top, right, bottom) if left < right and top < bottom else None


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


def place_captions(plan, subjects, source_dimensions=None, *, keep_safe_defaults=False):
    """Static caption boxes avoid swept subject envelopes on the output clock.

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
    layouts = []
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
        masks = []
        # Include a small output edge inset as well as every padding bar.
        left, top = max(inset_left, content.x), max(inset_top, content.y)
        right, bottom = min(1 - inset_right, content.right), min(1 - inset_bottom, content.bottom)
        for name, box in [("left", Box(0, 0, left, 1)), ("right", Box(right, 0, 1 - right, 1)),
                          ("top", Box(0, 0, 1, top)), ("bottom", Box(0, bottom, 1, 1 - bottom))]:
            masks.append(Mask(name, box))
        if (keep_safe_defaults and caption.layout is None and caption.style is None and caption.font is None
                and caption.template is None and caption.backend == "ass" and caption.alignment == "center"):
            # Decide on measured libass ink at the largest rendered size, never
            # an estimate: neither renderer re-checks an unplaced caption.
            try:
                ink = measure_default_ink(caption, plan.width, plan.height)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                ink = None  # Unmeasurable: place it explicitly below.
            default = default_caption_box(caption, plan.width, plan.height, ink) if ink else None
            if default is not None and check_overlap([Keyframe(caption.start, default), Keyframe(caption.end, default)],
                                                     obstacles, masks).safe:
                continue
        if caption.style is None:
            caption.style = CaptionStyle(max(1, min(plan.width, plan.height) / 18),
                                         outline_width=min(plan.width, plan.height) / 540)
        max_width, max_height = min(.84, (right - left) * .94), min(.16, (bottom - top) * .8)
        # Reserve the text's estimated extent, not 84% of the frame for every
        # word. Oversized empty boxes make otherwise safe close-ups infeasible.
        line_width = max(1, int(max_width * plan.width / (caption.style.size * .8)))
        caption.text = "\n".join(textwrap.wrap(" ".join(caption.text.split()), width=line_width,
                                             break_long_words=False, break_on_hyphens=False))
        lines = caption.text.splitlines()
        def extent():
            padding = caption.style.outline_width * 2 + 6
            return (max(len(line) for line in lines) * caption.style.size * .8 + padding,
                    len(lines) * caption.style.size * 1.4 + padding)
        ink_width, ink_height = extent()
        shrink = max(1, ink_width / (max_width * plan.width), ink_height / (max_height * plan.height))
        if shrink > 1:
            caption.style = replace(caption.style, size=max(1, caption.style.size / shrink),
                                    outline_width=caption.style.outline_width / shrink)
            ink_width, ink_height = extent()
        event = CaptionEvent(caption.id, caption.start, caption.end,
                             min(max_width, ink_width / plan.width), min(max_height, ink_height / plan.height), "lower-third")
        prior = caption.layout
        checked = check_overlap(prior.as_path(), obstacles, masks) if prior else None
        if prior and checked.safe:
            layout = replace(prior, overlap=checked)
            boxes = [key.box for key in prior.as_path()]
            event = replace(event, width=min(b.width for b in boxes), height=min(b.height for b in boxes))
        else:
            layout = choose_layout([event], obstacles, masks, allow_motion=False).events[0]
        if not layout.overlap.safe:
            # A long single line can block a usable side gap on a close-up.
            # Reflow into narrower boxes before declaring the layout infeasible.
            # Every alternative still receives the same continuous safety check.
            original_text, original_style = caption.text, caption.style
            for fraction in (.7, .5, .35):
                trial_width = max_width * fraction
                trial_height = min(.32, (bottom - top) * .8)
                caption.style = original_style
                columns = max(1, int(trial_width * plan.width / (caption.style.size * .8)))
                caption.text = "\n".join(textwrap.wrap(" ".join(original_text.split()), width=columns,
                                                     break_long_words=False, break_on_hyphens=False))
                lines = caption.text.splitlines()
                ink_width, ink_height = extent()
                shrink = max(1, ink_width / (trial_width * plan.width), ink_height / (trial_height * plan.height))
                caption.style = replace(caption.style, size=max(1, caption.style.size / shrink),
                                        outline_width=caption.style.outline_width / shrink)
                ink_width, ink_height = extent()
                trial = replace(event, width=min(trial_width, ink_width / plan.width),
                                height=min(trial_height, ink_height / plan.height))
                alternative = choose_layout([trial], obstacles, masks, allow_motion=False).events[0]
                if alternative.overlap.safe:
                    layout = alternative
                    break
            else:
                caption.text, caption.style = original_text, original_style
        scope = "output crop; aspect UI insets, swept supplied subject tracks and visible-content bounds; detector recall unverified"
        if not obstacles:
            scope += "; faces unmeasured in this interval"
        layout = replace(layout, overlap=replace(layout.overlap, scope=scope))
        caption.layout = layout
        layouts.append(layout.to_dict())
    return layouts
