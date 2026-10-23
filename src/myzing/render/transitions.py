"""Compile the v2 contract's already-placed overlaps, without retiming the plan."""

from __future__ import annotations

from fractions import Fraction

from myzing.composition import Composition, Transition
from myzing.composition.timebase import frame_index, rate_fraction
from myzing.project.models import Rational

from .validation import EDLValidationError


SUPPORTED_KINDS = frozenset({"hard_cut", "dissolve", "wipe", "dip_to_black", "dip_to_white", "zoom_punch"})
SAMPLE_RATE = 48000


def validate_render_windows(composition: Composition) -> None:
    """Reject windows that the output frame/sample clocks cannot represent."""
    rate = rate_fraction(composition.fps)
    for transition in composition.transitions:
        if transition.recipe.kind == "hard_cut":
            continue
        label = f"transition {transition.id} ({transition.outgoing_clip} -> {transition.incoming_clip})"
        frames = (frame_index(transition.end, composition.fps, rounding="nearest")
                  - frame_index(transition.start, composition.fps, rounding="nearest"))
        if frames < 1 or sample_span(transition.start, transition.end) < 1:
            raise EDLValidationError(f"{label}: overlap must span at least one output frame and one audio sample")
        if transition.recipe.duration_seconds > 60 or frames / rate > 60:
            raise EDLValidationError(f"{label}: xfade supports at most 60 seconds; shorten the overlap")
    for clip in composition.clips:
        if (frame_index(clip.timeline_end, composition.fps, rounding="nearest")
                <= frame_index(clip.timeline_start, composition.fps, rounding="nearest")):
            raise EDLValidationError(f"clip {clip.id}: trim must span at least one output frame")


def timeline_joins(composition: Composition) -> tuple[Transition | None, ...]:
    """One entry per boundary. Cut-only plans keep the frozen legacy graph."""
    if not any(t.recipe.kind != "hard_cut" for t in composition.transitions):
        return ()
    ordered = sorted(composition.clips, key=lambda c: c.timeline_start)
    pairs = {(t.outgoing_clip, t.incoming_clip): t for t in composition.transitions}
    return tuple(pairs.get((a.id, b.id)) for a, b in zip(ordered, ordered[1:]))


def sample_span(start: float, end: float) -> int:
    # Subtract rounded absolute endpoints, so repeated joins cannot accumulate
    # fractional-sample drift. MR1's placed tracks use the same 48 kHz clock.
    return round(end * SAMPLE_RATE) - round(start * SAMPLE_RATE)


def normalize_video(rate: str) -> str:
    # xfade negotiates planar 4:4:4. Explicitly normalize *both* its clip inputs
    # and the result of concat (which otherwise changes the timebase).
    return f"fps={rate},setsar=1,format=yuv444p,settb=AVTB,setpts=N/({rate}*TB)"


def video_frame(seconds: float, rate: str) -> int:
    value = Fraction(rate)
    return frame_index(seconds, Rational(value.numerator, value.denominator), rounding="nearest")


def video_edge(clip, following: Transition | None, width: int, height: int, rate: str) -> str:
    frames = video_frame(clip.timeline_start + clip.src_out - clip.src_in, rate) - video_frame(clip.timeline_start, rate)
    filters = ""
    if following is not None and following.recipe.kind == "zoom_punch":
        start = following.start - clip.timeline_start
        duration = following.recipe.duration_seconds
        # A bounded centered scale-up on the outgoing tail, dissolved into B.
        # d=1 preserves each decoded moving frame; no still-image duplication.
        filters += (f",zoompan=z='1+0.35*clip((on/({rate})-{start:.9f})/{duration:.9f},0,1)'"
                    f":x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={width}x{height}:fps={rate}")
    return filters + f",{normalize_video(rate)},trim=end_frame={frames}"


def clip_audio(index: int, resolved, label: str, extra: tuple[str, ...] = ()) -> str:
    clip = resolved.spec
    count = sample_span(clip.timeline_start, clip.timeline_start + clip.src_out - clip.src_in)
    if resolved.media.has_audio:
        source = (f"[{index}:a:0]atrim=start={clip.src_in:.9f}:end={clip.src_out:.9f},"
                  "asetpts=PTS-STARTPTS,aresample=48000,"
                  "aformat=sample_fmts=fltp:channel_layouts=stereo" + "".join("," + f for f in extra))
    else:
        source = "anullsrc=r=48000:cl=stereo,aformat=sample_fmts=fltp"
    return f"{source},asetpts=N/SR/TB,apad=whole_len={count},atrim=end_sample={count}[{label}]"


def join_streams(lines: list[str], joins: tuple[Transition | None, ...], rate: str, duration: float) -> None:
    fps = float(Fraction(rate))
    video, audio = "clipv0", "clipa0"
    for index, transition in enumerate(joins, 1):
        vout, aout = f"joinv{index}", f"joina{index}"
        if transition is not None and transition.recipe.kind != "hard_cut":
            recipe = transition.recipe
            effect = {"dissolve": "fade", "wipe": f"wipe{recipe.direction}",
                      "dip_to_black": "fadeblack", "dip_to_white": "fadewhite", "zoom_punch": "fade"}[recipe.kind]
            # Quantize absolute endpoints, keeping every boundary within one
            # frame even on fractional-rate or long multi-transition plans.
            start = video_frame(transition.start, rate) / fps
            end = video_frame(transition.end, rate) / fps
            lines.append(f"[{video}][clipv{index}]xfade=transition={effect}:"
                         f"duration={end - start:.9f}:offset={start:.9f}[{vout}]")
            samples = sample_span(transition.start, transition.end)
            lines.append(f"[{audio}][clipa{index}]acrossfade=ns={samples}:c1=qsin:c2=qsin,"
                         f"asetpts=N/SR/TB[{aout}]")
        else:
            lines.append(f"[{video}][clipv{index}]concat=n=2:v=1:a=0,{normalize_video(rate)}[{vout}]")
            lines.append(f"[{audio}][clipa{index}]concat=n=2:v=0:a=1,asetpts=N/SR/TB[{aout}]")
        video, audio = vout, aout
    lines.append(f"[{video}]trim=end_frame={video_frame(duration, rate)},format=yuv420p[video_concat]")
    lines.append(f"[{audio}]atrim=end_sample={round(duration * SAMPLE_RATE)}[clip_audio]")
