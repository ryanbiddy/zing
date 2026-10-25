"""Libass preset writer: immutable word slots and metric-based baselines."""

import math
import unicodedata

from myzing.composition import frame_index, frame_time
from myzing.render.font_files import ass_em_scale
from myzing.render.positioned_captions import (
    _color, _dialogue, _n, _rounded_rectangle, caption_frame_timing,
    escape_ass, frame_centisecond,
)

from .metrics import metrics
from .presets import slot_lines


def _rtl(text):
    """Base direction from the first strong character (Unicode bidi rule P2)."""
    for ch in text:
        kind = unicodedata.bidirectional(ch)
        if kind in ("R", "AL"):
            return True
        if kind == "L":
            return False
    return False


def geometry(caption, width, height):
    style, box = caption.style, caption.layout.box
    size = style.size * caption.layout.scale
    font = metrics(caption.font.path, caption.font.sha256)
    pad = style.highlight_box_padding*caption.layout.scale if caption.preset == "box" else 0
    space, line_h = font.width(" ",size), font.line_height(size)
    lines = caption.text.splitlines()
    # The clean rail is the bottom of the font cell, shared by 1 and 2 lines.
    if caption.preset == "clean":
        baseline = box.bottom*height - max(style.outline_width*caption.layout.scale,2) + font.descent*size/font.units
    else:
        baseline = box.center[1]*height + font.cap*size/font.units/2
    slots = []
    for line_index, line in enumerate(slot_lines(caption)):
        advances = [font.width(text,size) for text,_,_ in line]
        gaps = [space if gap else 0 for _,gap,_ in line]
        left = [pad if k == 0 or line[k][1] else 0 for k in range(len(line))]
        right = [pad if k+1 == len(line) or line[k+1][1] else 0 for k in range(len(line))]
        total = sum(advances) + sum(gaps) + sum(left) + sum(right)
        x = box.center[0]*width - total/2
        y = baseline - (len(lines)-1-line_index)*line_h
        order = list(range(len(line)))
        if _rtl(lines[line_index]):
            # Right-to-left lines read from the right: the first word's slot
            # (and so the first highlight) sits at the right end.
            order.reverse()
        placed = {}
        for position, k in enumerate(order):
            if position:
                previous = order[position-1]
                x += gaps[max(k, previous)]
            placed[k] = x
            x += advances[k]+left[k]+right[k]
        for k, (text, _, index) in enumerate(line):
            slots.append({"index":index,"text":text,"x":placed[k]+left[k],"baseline":y,"width":advances[k],
                          "plate_x":placed[k],"plate_y":y-font.cap*size/font.units-size*.08,
                          "plate_width":advances[k]+left[k]+right[k],"plate_height":(font.cap-font.descent)*size/font.units+size*.16})
    slots.sort(key=lambda slot: slot["index"])
    return {"version":1,"anchor_x":box.center[0]*width,"baseline":baseline,
            "font_ascent":font.ass_ascent*size/font.units,"size":size,"slots":slots,
            "line_count":len(lines),"scale":caption.layout.scale}


def _pop(elapsed):
    if elapsed < .08:
        return .8 + .25*max(0,elapsed)/.08
    return 1.05-.05*min(1,(elapsed-.08)/.06)


def compile_caption(caption, composition, font, data, frame_limit):
    if caption.layout is None or caption.layout.box is None:
        raise ValueError("Caption presets need a shot rail; run place_captions before rendering.")
    geo = geometry(caption,composition.width,composition.height)
    first,last,words,_ = caption_frame_timing(caption,composition.fps,frame_limit)
    # A scheduled 125/30 s start can arrive as 4.166666666666667. Treat
    # numerical dust at a frame boundary as that boundary, not the next frame.
    # Otherwise a 5/6 s Clean cue ending at a cut loses one of its 25 frames.
    first = max(0, frame_index(max(0, caption.start-1e-9), composition.fps, rounding="ceil"))
    # One-frame word minimums must not stretch a cue into the next one: two
    # groups on one rail would overprint. Keep the cue's own frame window.
    own = max(first+1, min(frame_limit, frame_index(max(0, caption.end-1e-9), composition.fps, rounding="ceil")))
    if last > own:
        last = own
        words = [(min(s,last-1), max(min(s,last-1)+1, min(e,last))) for s,e in words]
    # Clean captions retain words for editing, but have no per-word highlight.
    if caption.preset == "clean":
        words = []
    boundaries = {first,last}
    boundaries.update(t for pair in words for t in pair if first < t < last)
    if caption.preset == "punch":
        boundaries.update(range(first,min(last,first+math.ceil(.14*composition.fps.numerator/composition.fps.denominator))+1))
    if caption.preset == "box":
        boundaries.update(range(first,min(last,first+math.ceil(.1*composition.fps.numerator/composition.fps.denominator))+1))
        for start,_ in words[1:]:
            boundaries.update(range(start,min(last,start+math.ceil(.08*composition.fps.numerator/composition.fps.denominator))+1))
    ordered = sorted(boundaries)
    lines = []
    style = caption.style
    for a,b in zip(ordered,ordered[1:]):
        start,end = frame_centisecond(a,composition.fps),frame_centisecond(b,composition.fps)
        now = float(frame_time(a,composition.fps))
        active = max((i for i,(s,e) in enumerate(words) if s <= a),default=None)
        if active is not None and active+1 < len(words):
            # Judge the silence before frame quantization: a 240 ms gap can
            # round to eight frames at 30 fps and must still keep its highlight.
            next_start = caption.words[active+1].start
            word_end = caption.words[active].end
            if next_start-word_end >= .25 and a >= words[active][1]:
                active = None
        pop = _pop(now-float(frame_time(first,composition.fps))) if caption.preset == "punch" else 1.
        ink_layers = []
        for slot in geo["slots"]:
            x = geo["anchor_x"] + (slot["x"]-geo["anchor_x"])*pop
            y = geo["baseline"] + (slot["baseline"]-geo["baseline"]-geo["font_ascent"])*pop
            color = style.color if caption.preset == "box" else style.highlight if active == slot["index"] else style.color
            tags = (rf"\an7\q2\fn{font}\b100\fs{_n(geo['size']*ass_em_scale(data)*pop)}"
                    rf"\bord{_n(style.outline_width*geo['scale']*pop)}\shad0"
                    rf"\1c{_color(color)}\3c{_color(style.outline_color)}\pos({_n(x)},{_n(y)})")
            if caption.preset == "box":
                # Fade only the group's first 100 ms; do not restart at word states.
                alpha = round(255*max(0,1-(now-caption.start)/.1))
                tags += rf"\alpha&H{alpha:02X}&"
            lines.append(_dialogue(start,end,"{"+tags+"}"+escape_ass(slot["text"]),layer=1))
            ink_layers.append((tags, slot["text"]))
        if caption.preset == "box" and active is not None:
            slot = geo["slots"][active]
            rect = [slot[k] for k in ("plate_x","plate_y","plate_width","plate_height")]
            if active > 0:
                elapsed = now-float(frame_time(words[active][0],composition.fps))
                ratio = 1-(1-min(1,max(0,elapsed/.08)))**2
                old = geo["slots"][active-1]
                rect = [old[k]+(v-old[k])*ratio for k,v in zip(("plate_x","plate_y","plate_width","plate_height"),rect)]
            x,y,w,h = rect
            alpha = round(255*(1-style.highlight_box_opacity*min(1,max(0,(now-caption.start)/.1))))
            plate = ("{"+rf"\an7\bord0\shad0\1c{_color(style.highlight_box_color)}\1a&H{alpha:02X}&\p1\pos({_n(x)},{_n(y)})"+"}"
                     + _rounded_rectangle(w,h,style.highlight_box_radius*geo["scale"]))
            lines.append(_dialogue(start,end,plate,layer=0))
            # Identical glyphs clipped to the moving plate: black inside,
            # white outside, including during the glide between words.
            for tags, text in ink_layers:
                clipped = tags + rf"\1c{_color(style.highlight)}\clip({_n(x)},{_n(y)},{_n(x+w)},{_n(y+h)})"
                lines.append(_dialogue(start,end,"{"+clipped+"}"+escape_ass(text),layer=2))
    return lines, {"event_id":caption.id,"start":caption.start,"end":caption.end,**geo}
