"""Hook timings and bounded visual comparisons, without inferred story beats."""

import math
from pathlib import Path
from statistics import median

from myzing.profile import api as profile
from myzing.schemas import Breakdown
from myzing.study.transition_models import distance

from .models import HookMetric, Section

FRAME_SIDE = 32
MAX_FRAMES = 7201  # At most 22 MB of RGB bytes, even with unusual frame rates.
SAMPLE_SECONDS = .5
SIMILARITY_THRESHOLD = .98
VISUAL_METHOD = (
    "1 - study.transition_models.distance(first, second) / 255; "
    "mean absolute RGB difference on 32x32 area-scaled frames; similarity must be > 0.98"
)
VISUAL_LIMIT = (
    "Visual similarity is a pixel heuristic: similar backgrounds can match unrelated moments. "
    "It does not establish a narrative flash-forward, matching motion or an audio loop."
)


def _metric(method, basis, value=None, *, status=None, unit=""):
    return HookMetric(method, basis, value, status or ("measured" if value is not None else "unknown"), unit).to_dict()


def visual_unknown(reason, duration):
    # Loops are judged under 60 s; frames are decoded at all only up to 60 s.
    finite = math.isfinite(duration)
    return {
        "loop_seam": _metric(VISUAL_METHOD, "Only clips under 60 s are eligible." if finite and duration >= 60 else reason,
                             status="not_applicable" if finite and duration >= 60 else "unknown"),
        "flash_forward": _metric(VISUAL_METHOD, "Only clips up to 60 s are frame-compared (analysis budget)."
                                 if finite and duration > 60 else reason,
                                 status="not_applicable" if finite and duration > 60 else "unknown"),
    }


def measure_visual(media, duration, fps):
    """Decode only the studied interval, retaining true endpoints before sampling.

    Study ingest supplies the CFR timeline used by its other frame consumers.
    No fps filter can duplicate/drop the endpoint. A hard output cap bounds RAM;
    hitting it abstains rather than treating the cap as the end of the clip.
    """
    if not all(math.isfinite(v) and v > 0 for v in (duration, fps)):
        return visual_unknown("No usable CFR timeline.", duration)
    if duration > 60:
        return visual_unknown("Beyond the 60 s frame-comparison budget.", duration)
    from myzing.inspect.media import Decoder

    decoder = Decoder()
    try:
        data = decoder.run(decoder.input_args(Path(media), 0) + [
            "-map", "0:v:0", "-an", "-sn", "-dn", "-t", f"{duration:.9f}",
            "-vf", f"scale={FRAME_SIDE}:{FRAME_SIDE}:flags=area,setsar=1",
            "-frames:v", str(MAX_FRAMES), "-fps_mode", "passthrough",
            "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1",
        ], "hook frame comparisons")
        size = FRAME_SIDE * FRAME_SIDE * 3
        count, remainder = divmod(len(data), size)
        if remainder or count < 2 or count >= MAX_FRAMES:
            return visual_unknown("Incomplete frames, fewer than two frames, or the hook frame budget was reached.", duration)
        return _compare_frames(data, count, size, duration, fps)
    except (OSError, RuntimeError, ValueError) as exc:
        reason = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        return visual_unknown("Frame comparison unavailable: " + reason[:300], duration)


def _compare_frames(data, count, size, duration, fps):
    frames = memoryview(data)

    def compare(left, right):
        delta = distance(frames[left * size:(left + 1) * size], frames[right * size:(right + 1) * size])
        return {"similarity": 1 - delta / 255, "mean_absolute_rgb_difference": delta,
                "threshold": SIMILARITY_THRESHOLD, "threshold_operator": ">"}

    result = visual_unknown("No disjoint opening and later frame samples.", duration)
    basis = f"Decoded {count} frames from studied media; times = frame index / {fps:g} fps (study CFR timeline)."
    if duration < 60:
        seam = compare(0, count - 1)
        seam.update(first_seconds=0, last_seconds=(count - 1) / fps,
                    loops_cleanly=seam["similarity"] > SIMILARITY_THRESHOLD)
        result["loop_seam"] = _metric(VISUAL_METHOD, basis + " First and last decoded frames; visual seam only.", seam)
    step = max(1, math.ceil(fps * SAMPLE_SECONDS))
    indices = sorted(set(range(0, count, step)) | {count - 1})
    opening_end = min(3, duration / 2)
    opening = [i for i in indices if i / fps < opening_end]
    later = [i for i in indices if duration / 2 < i / fps < duration]
    if opening and later:
        # Stable ties prefer the earliest opening and later frame.
        score, first, match = max((compare(a, b)["similarity"], -a, -b) for a in opening for b in later)
        first, match = -first, -match
        value = compare(first, match)
        matched = score > SIMILARITY_THRESHOLD
        value.update(candidate=matched, opening_seconds=first / fps,
                     matched_seconds=match / fps if matched else None,
                     best_later_seconds=match / fps, opening_end_seconds=opening_end,
                     later_start_exclusive_seconds=duration / 2, sample_step_seconds=step / fps,
                     opening_samples=len(opening), later_samples=len(later))
        result["flash_forward"] = _metric(
            VISUAL_METHOD, basis + " Best sampled frame pair: opening [0, min(3 s, midpoint)) vs strictly after midpoint; "
            "no frame is compared with itself. An unmatched sample search cannot rule out an unsampled repeat.", value)
    return result


def payoff_spacing(b):
    method = "Median and min/max of consecutive start-to-start gaps in stored judgment.beats labeled payoff"
    beats = b.judgment.get("beats")
    if not isinstance(beats, list):
        return _metric(method, "No stored payoff beat annotations; no payoff detector is run.", unit="seconds")
    payoffs = [beat for beat in beats if isinstance(beat, dict) and beat.get("label") == "payoff"]
    for beat in payoffs:
        start, end = beat.get("start"), beat.get("end")
        if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (start, end))
                or not 0 <= start < end <= b.meta.duration or not isinstance(beat.get("evidence"), str)
                or not beat["evidence"].strip()):
            return _metric(method, "Stored payoff annotations have invalid spans or missing evidence.", unit="seconds")
    payoffs.sort(key=lambda beat: beat["start"])
    if any(a["end"] > z["start"] for a, z in zip(payoffs, payoffs[1:])):
        return _metric(method, "Stored payoff spans overlap; spacing is unknown.", unit="seconds")
    if len(payoffs) < 2:
        return _metric(method, f"Only {len(payoffs)} stored payoff beat(s); spacing needs at least two.", unit="seconds")
    gaps = [z["start"] - a["start"] for a, z in zip(payoffs, payoffs[1:])]
    return _metric(method, "Arithmetic over supplied story judgments, not measured payoff detection. Annotations remain in breakdown.json.",
                   {"median": median(gaps), "min": min(gaps), "max": max(gaps), "gap_count": len(gaps)},
                   status="judgment", unit="seconds")


def hook(b, pacing, visual=None):
    """Each fact has its own basis, including abstentions and supplied judgments."""
    b = Breakdown.from_dict(b)
    facts = {}
    sources = (
        ("time_to_first_word", profile._first_word, "Minimum stored word start", "Timed words in breakdown.words; no words means unknown."),
        ("time_to_first_cut", profile._first_cut, "Start of the second detected shot", "Detected boundaries in breakdown.shots; no detected cut means unknown."),
        ("time_to_first_caption", profile._first_caption, "Minimum stored caption-event start", "OCR caption events in breakdown.captions; sampled onset, not exact ink appearance or confirmed speech captions."),
    )
    for key, helper, method, basis in sources:
        value = helper(b)
        if key == "time_to_first_cut" and not pacing.facts:
            value, basis = None, "Shot detection unavailable; no supported cut timing."
        facts[key] = _metric(method + f" (profile.api.{helper.__name__})", basis, value, unit="seconds")
    duration = b.meta.duration
    window = min(3, duration * .1)
    rate_method = "Detected cut count * 10 / interval seconds; opening [0, min(3 s, 10% of duration)), rest [opening end, duration)"
    rate = None
    basis = "Shot detection or a positive duration is unavailable."
    if duration > 0 and pacing.facts:
        cuts = pacing.facts["cut_times"]
        opening = sum(0 <= t < window for t in cuts)
        rest = sum(window <= t < duration for t in cuts)
        rate = {"opening_end_seconds": window, "opening_cuts": opening, "rest_cuts": rest,
                "opening_cuts_per_10s": opening * 10 / window, "rest_cuts_per_10s": rest * 10 / (duration - window)}
        basis = "Shot starts after the first shot; a boundary exactly at the opening end belongs to the rest."
    if pacing.facts.get("v6_additional_cut_times"):
        basis += " Shot and transition detectors disagree; these rates may undercount cuts."
        facts["time_to_first_cut"]["basis"] += " Transition evidence reports additional cuts; first-cut timing may be late."
    facts["opening_cut_rate"] = _metric(rate_method, basis, rate, unit="cuts per 10 seconds")
    facts.update(visual or visual_unknown("Frame comparison was not run.", duration))
    facts["payoff_spacing"] = payoff_spacing(b)
    from .plain import hook_lines
    return Section("Hook and loop", facts, {"kind": "Per-value methods and bases; visual scores are heuristics, payoff labels are supplied judgments."},
                   [VISUAL_LIMIT, "All times are relative to the studied interval; its source range and unmeasured remainder are in card evidence.",
                    *[f"{k}: {v['basis']}" for k, v in facts.items() if v["status"] == "unknown"]],
                   hook_lines(facts), not_knowable="whether an opening keeps viewers watching, or repeated imagery is an intentional flash-forward.")
