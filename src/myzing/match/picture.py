"""Sharp output picture rectangles from the same geometry used by the renderer."""

import math

MATTE_INSET = 2


def picture_regions(plan):
    from myzing.render.framing import probe_dimensions

    regions, sizes = [], {}
    fps = plan.fps.numerator / plan.fps.denominator
    for clip in plan.clips:
        f = clip.framing
        if f is None:
            if clip.src not in sizes:
                sizes[clip.src] = probe_dimensions(clip.src)
            sw, sh = sizes[clip.src]
            scale = min(plan.width / sw, plan.height / sh)
            w, h = max(2, math.floor(sw * scale / 2) * 2), max(2, math.floor(sh * scale / 2) * 2)
            x, y = (plan.width - w) // 4 * 2, (plan.height - h) // 4 * 2
        elif f.mode in ("fit", "blurfill", "zoomfill"):
            w, h = f.foreground_size(plan.width, plan.height)
            x, y = f.foreground_origin(plan.width, plan.height)
            if f.mode != "zoomfill" and not f.picture:
                # A fit/blurfill foreground retains the whole source. Its
                # measured bounds may exclude baked-in letter/pillarboxing.
                b = f.bounds
                # Scaling and 4:2:0 chroma blend a matte edge into the next
                # output row/column pair, so step two pixels inside each one.
                left = math.ceil(x + b.x * w / f.source_width) + (MATTE_INSET if b.x > 0 else 0)
                top = math.ceil(y + b.y * h / f.source_height) + (MATTE_INSET if b.y > 0 else 0)
                right = math.floor(x + (b.x + b.width) * w / f.source_width) - (
                    MATTE_INSET if b.x + b.width < f.source_width else 0)
                bottom = math.floor(y + (b.y + b.height) * h / f.source_height) - (
                    MATTE_INSET if b.y + b.height < f.source_height else 0)
                x, y, w, h = left, top, right - left, bottom - top
        else:
            x, y, w, h = 0, 0, plan.width, plan.height
        regions.append({"start": round(clip.timeline_start * fps) / fps,
                        "end": round(clip.timeline_end * fps) / fps,
                        "rect": [x, y, w, h], "clip_id": clip.id})
    return regions


def region_at(regions, timestamp):
    active = [r["rect"] for r in regions if r["start"] <= timestamp < r["end"]]
    if not active:
        return None
    # During an overlap, only the common sharp area is uncontaminated by
    # either layer's fill. An empty intersection is an explicit sample gap.
    x, y = max(r[0] for r in active), max(r[1] for r in active)
    right, bottom = min(r[0] + r[2] for r in active), min(r[1] + r[3] for r in active)
    return (x, y, right - x, bottom - y) if right > x and bottom > y else None


def measure_output_color(video, plan, *, count=6):
    from myzing.color import ColorError
    from myzing.color.measure import measure_video

    regions = picture_regions(plan)
    basis = "Sharp picture only, cropped before downsampling from framing-plan geometry."
    requested = []

    def lookup(timestamp):
        requested.append(timestamp)
        return region_at(regions, timestamp)

    try:
        measurement, _, _ = measure_video(video, count=count, region_at=lookup)
    except ColorError:
        if len(requested) < count or any(region_at(regions, t) is not None for t in requested):
            raise  # Probe, color-space or decode failure: a real error.
        # Every sample was a gap (no common sharp area). That is a measurement
        # limit, not a failed render: color stays unmeasured and says why.
        return {"version": 1, "status": "unmeasured", "path": str(video), "samples": [], "aggregate": None,
                "warnings": ["No sample had a usable sharp picture area; color is unmeasured, not passed."],
                "picture_area": {"version": 1, "basis": basis, "regions": regions,
                                 "samples": [{"timestamp": t, "rect": region_at(regions, t)} for t in requested]}}
    result = measurement.to_dict()
    result["picture_area"] = {"version": 1, "basis": basis, "regions": regions,
                              "samples": [{"timestamp": s.timestamp, "rect": region_at(regions, s.timestamp)}
                                          for s in measurement.samples]}
    return result
