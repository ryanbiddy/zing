"""Photo placement in CSS pixels, shared by preflight and browser capture."""
SIZES = {"wide": (1920, 1080), "tall": (1080, 1920),
         "square": (1080, 1080), "portrait": (1080, 1350)}

# Top and bottom of the opening and the start of the torn edge.
TEAR = {"wide": (.415, .665, .2), "tall": (.3, .52, .13),
        "square": (.35, .6, .16), "portrait": (.31, .55, .15)}


def placement(frame, style: str, size: str) -> dict:
    w, h = SIZES[size]
    wide, tall = size == "wide", size == "tall"
    cx, cy, fh = frame.face.cx, frame.face.cy, frame.face.fh
    bw, bh = w, h
    if style == "clipping":
        top, bottom, start = TEAR[size]
        fx, fy = w * (start + (1 - start) * .47), h * (top + bottom) / 2
        desired = h * (bottom - top) / .74
        cy -= .1 * fh
    elif style == "plate":
        bh = h * (.73 if tall else 1)
        fx, fy = w * (.72 if wide else .5), bh * (.44 if wide else .4 if tall else .56)
        desired = (h if wide else w) * .5
    elif style == "number":
        bw = w * (.44 if wide else .84)
        bh = h * (.8 if wide else .4 if tall else .42)
        fx, fy, desired = bw * .5, bh * .42, bh * .48
    else:
        print_w = w * (.3 if wide else .66)
        print_h = h * .62 if wide else print_w * (.9 if tall else .5 if size == "square" else .62)
        bw, bh = print_w * .93, print_h - print_w * .07
        fx, fy, desired = bw * .5, bh * .45, bh * .5
    zoom = desired / (fh * frame.h)
    if style != "clipping":
        zoom = max(zoom, fx / (cx * frame.w), (bw - fx) / ((1 - cx) * frame.w),
                   fy / (cy * frame.h), (bh - fy) / ((1 - cy) * frame.h))
    width, height = frame.w * zoom, frame.h * zoom
    return {"zoom": zoom, "w": width, "h": height, "x": fx - cx * width,
            "y": fy - cy * height, "tear": TEAR[size]}
