"""Caption OCR -> `CaptionEvent[]`: what text is on screen, when, and
roughly how it looks.

Pipeline per R1-A pick 4 (shipping-tool consensus, sources in
handoff/research/R1-lane-a-measurement.md):

- Sample 8 fps in the 0-3s hook window, 4 fps after (binding resolution
  A#9); the schedule is recorded in warnings so downstream knows the
  resolution floor.
- Cheap change-gate before OCR: an unchanged frame reuses the previous
  frame's OCR result instead of re-running inference.
- OCR via rapidocr (PP-OCRv6 models); per-line results below confidence
  0.75 are dropped (the PaddleOCR-family practitioner threshold).
- Temporal clustering into events: consecutive observations merge when one
  is a prefix of the other (word-by-word pop captions grow) or their
  similarity is >= 0.8; the event keeps the LONGEST observed text; short
  OCR flicker gaps (<= 0.5s) don't split an event.

Known blind spots, stated not hidden: emoji cannot be emitted by
dictionary-constrained OCR (dropped/garbled); PP-OCR English models can
merge words ("Thispaper") — word-box-based spacing repair is an S2 item
(rapidocr's return_word_box provides the data). Stylized/animated captions
will produce imperfect text; confidence values keep it honest.

rapidocr + opencv are optional [study] deps, imported lazily; absence is
an honest skip with a warning.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterator

from myzing.schemas import CaptionEvent

CONF_THRESHOLD = 0.75
HOOK_WINDOW_S = 3.0
HOOK_FPS = 8.0
BODY_FPS = 4.0
SIMILARITY = 0.8
MAX_FLICKER_GAP_S = 0.5
SAMPLING_NOTE = (
    f"caption OCR sampled at {HOOK_FPS:.0f} fps in 0-{HOOK_WINDOW_S:.0f}s, "
    f"{BODY_FPS:.0f} fps after; text between samples is unobserved"
)


@dataclass
class Line:
    """One OCR'd text line in one frame."""
    text: str
    score: float
    y_center: float               # 0..1, normalized to frame height


@dataclass
class Observation:
    """Everything seen on screen at one sampled time."""
    t: float
    step: float                   # sampling interval at this time
    lines: list[Line] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(ln.text for ln in sorted(self.lines, key=lambda l: l.y_center))


@dataclass
class CaptionsResult:
    captions: list[CaptionEvent] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def read_captions(media_path: Path, duration: float) -> CaptionsResult:
    result = CaptionsResult(warnings=[SAMPLING_NOTE])
    if duration <= 0:
        result.warnings.append("caption OCR skipped: unknown duration")
        return result
    try:
        engine, version = _engine()
    except ImportError:
        result.warnings = [
            "caption OCR skipped: rapidocr/onnxruntime not installed "
            "(pip install myzing[study])"
        ]
        return result
    except Exception as e:
        result.warnings = [f"caption OCR skipped: backend failed to start: {e}"]
        return result

    observations: list[Observation] = []
    errors = 0
    try:
        prev_frame = None
        prev_lines: list[Line] = []
        for t, step, frame in _iter_frames(media_path, duration):
            if prev_frame is not None and not _changed(prev_frame, frame):
                lines = prev_lines
            else:
                try:
                    lines = _ocr(engine, frame)
                except Exception:
                    errors += 1
                    lines = []
            observations.append(Observation(t=t, step=step, lines=lines))
            prev_frame, prev_lines = frame, lines
    except Exception as e:
        result.warnings.append(f"caption OCR failed while reading frames: {e}")
        return result

    if errors:
        result.warnings.append(
            f"caption OCR: {errors} frame(s) failed to OCR and were treated "
            "as empty"
        )
    result.captions = cluster(observations)
    result.provenance = {
        "ocr_backend": f"rapidocr-{version}",
        "conf_threshold": CONF_THRESHOLD,
        "hook_fps": HOOK_FPS,
        "body_fps": BODY_FPS,
    }
    return result


# -- clustering (pure logic, fully unit-tested) -----------------------------

def _normalize(text: str) -> str:
    return " ".join(text.casefold().split())


def _same_event(a: str, b: str) -> bool:
    """Prefix containment (pop captions grow word by word) or fuzzy match."""
    na, nb = _normalize(a), _normalize(b)
    if not na or not nb:
        return False
    short, long_ = (na, nb) if len(na) <= len(nb) else (nb, na)
    if long_.startswith(short):
        return True
    return SequenceMatcher(None, na, nb).ratio() >= SIMILARITY


def cluster(observations: list[Observation]) -> list[CaptionEvent]:
    events: list[CaptionEvent] = []
    current: list[Observation] = []
    last_hit_t = 0.0

    def close() -> None:
        if current:
            events.append(_build_event(current))
            current.clear()

    for obs in observations:
        if not obs.text.strip():
            if current and obs.t - last_hit_t > MAX_FLICKER_GAP_S:
                close()
            continue
        if current and not _same_event(_longest_text(current), obs.text):
            close()
        if current and obs.t - last_hit_t > MAX_FLICKER_GAP_S:
            close()
        current.append(obs)
        last_hit_t = obs.t
    close()
    return events


def _longest_text(observations: list[Observation]) -> str:
    return max((o.text for o in observations), key=len)


def _build_event(observations: list[Observation]) -> CaptionEvent:
    last = observations[-1]
    text = _longest_text(observations)
    all_lines = [ln for o in observations for ln in o.lines]
    word_counts = sorted(len(o.text.split()) for o in observations)
    positions = Counter(
        _position_bucket(ln.y_center) for ln in all_lines
    )
    letters = [c for c in text if c.isalpha()]
    return CaptionEvent(
        text=text,
        start=round(observations[0].t, 3),
        end=round(last.t + last.step, 3),
        position=positions.most_common(1)[0][0] if positions else "center",
        all_caps=bool(letters) and sum(c.isupper() for c in letters) / len(letters) > 0.9,
        words_visible=max(1, word_counts[len(word_counts) // 2]),
        confidence=round(
            sum(ln.score for ln in all_lines) / len(all_lines), 3
        ) if all_lines else 0.0,
    )


def _position_bucket(y_center: float) -> str:
    if y_center < 0.25:
        return "top"
    if y_center < 0.5:
        return "center"
    if y_center < 0.78:
        return "lower"
    return "bottom"


def sample_schedule(duration: float) -> list[tuple[float, float]]:
    """(time, step) pairs: dense over the hook window, sparser after."""
    times: list[tuple[float, float]] = []
    t = 0.0
    while t < duration:
        step = 1.0 / HOOK_FPS if t < HOOK_WINDOW_S else 1.0 / BODY_FPS
        times.append((round(t, 3), step))
        t += step
    return times


# -- seams that touch heavy deps (tests mock these) -------------------------

def _engine():
    from importlib.metadata import version as pkg_version

    from rapidocr import RapidOCR

    return RapidOCR(), pkg_version("rapidocr")


def _iter_frames(
    media_path: Path, duration: float
) -> Iterator[tuple[float, float, Any]]:
    """Decode once, yield (time, step, frame) at the sampling schedule.
    Sequential read (CFR guaranteed by ingest), no per-frame seeking."""
    import cv2

    cap = cv2.VideoCapture(str(media_path))
    if not cap.isOpened():
        raise RuntimeError(f"could not open {media_path.name} for frame reads")
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        schedule = sample_schedule(duration)
        want = 0
        frame_index = 0
        while want < len(schedule):
            got, frame = cap.read()
            if not got:
                break
            t = frame_index / fps
            frame_index += 1
            if t + 1e-9 >= schedule[want][0]:
                yield schedule[want][0], schedule[want][1], frame
                want += 1
    finally:
        cap.release()


def _changed(prev, cur) -> bool:
    """Cheap gate: has the frame changed enough to re-OCR? (videocr-family
    pattern: count pixels whose delta exceeds a threshold)."""
    import cv2
    import numpy as np

    a = cv2.cvtColor(cv2.resize(prev, (135, 240)), cv2.COLOR_BGR2GRAY)
    b = cv2.cvtColor(cv2.resize(cur, (135, 240)), cv2.COLOR_BGR2GRAY)
    delta = cv2.absdiff(a, b)
    return int(np.count_nonzero(delta > 25)) > 60


def _ocr(engine, frame) -> list[Line]:
    """Run rapidocr on one frame -> confident Lines with normalized y."""
    out = engine(frame)
    boxes = getattr(out, "boxes", None)
    txts = getattr(out, "txts", None)
    scores = getattr(out, "scores", None)
    if boxes is None or txts is None:
        return []
    height = frame.shape[0] or 1
    lines: list[Line] = []
    for box, txt, score in zip(boxes, txts, scores or [0.0] * len(txts)):
        score = float(score)
        text = str(txt).strip()
        if not text or score < CONF_THRESHOLD:
            continue
        ys = [pt[1] for pt in box]
        lines.append(
            Line(text=text, score=score, y_center=(min(ys) + max(ys)) / 2 / height)
        )
    return lines
