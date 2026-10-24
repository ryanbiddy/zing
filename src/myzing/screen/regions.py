"""Local focus/control and text geometry, without OCR or a DOM.

Flat components find controls; glyph components join into words and lines.
These are pixel bounds, not recognized text. Word boxes guard crop edges.
"""

from __future__ import annotations

import math
import subprocess

from .analysis import input_args


def union(boxes):
    x = min(b[0] for b in boxes)
    y = min(b[1] for b in boxes)
    return [x, y, max(b[0]+b[2] for b in boxes)-x,
            max(b[1]+b[3] for b in boxes)-y]


def intersects(a, b):
    return a[0] < b[0]+b[2] and b[0] < a[0]+a[2] and a[1] < b[1]+b[3] and b[1] < a[1]+a[3]


def contains(outer, inner):
    return (outer[0] <= inner[0] and outer[1] <= inner[1] and
            outer[0]+outer[2] >= inner[0]+inner[2] and outer[1]+outer[3] >= inner[1]+inner[3])


def padded(box, width, height, pad=2):
    x, y, w, h = box
    left, top = max(0,x-pad), max(0,y-pad)
    return [left/width, top/height, (min(width,x+w+pad)-left)/width,
            (min(height,y+h+pad)-top)/height]


def geometry(rgb, width, height):
    """Quantized components plus row/gap grouping, no lexical inference."""
    colors = [(rgb[i]//16, rgb[i+1]//16, rgb[i+2]//16) for i in range(0,len(rgb),3)]
    seen = bytearray(width*height)
    components = []
    for seed in range(width*height):
        if seen[seed]:
            continue
        color, stack = colors[seed], [seed]
        seen[seed] = 1
        left = right = seed % width
        top = bottom = seed // width
        count = 0
        while stack:
            i = stack.pop()
            x,y = i%width, i//width
            count += 1
            left,right = min(left,x),max(right,x)
            top,bottom = min(top,y),max(bottom,y)
            for j in (i-1 if x else -1,i+1 if x+1<width else -1,
                      i-width if y else -1,i+width if y+1<height else -1):
                if j>=0 and not seen[j] and colors[j]==color:
                    seen[j]=1
                    stack.append(j)
        components.append(([left,top,right-left+1,bottom-top+1],count,color))
    controls = [padded(b,width,height) for b,n,c in components
                if b[2]>=width*.035 and b[3]>=height*.045
                and .001 <= b[2]*b[3]/(width*height) <= .6 and n/(b[2]*b[3])>=.45]
    # Merge anti-aliased glyph colors before finding components. Local tile
    # backgrounds handle both light-on-dark labels and dark button text.
    from collections import Counter
    mask = bytearray(width*height)
    tile = 24
    for top in range(0,height,tile):
        for left in range(0,width,tile):
            indices = [y*width+x for y in range(top,min(height,top+tile))
                       for x in range(left,min(width,left+tile))]
            background = Counter(colors[i] for i in indices).most_common(1)[0][0]
            for i in indices:
                if sum((a-b)**2 for a,b in zip(colors[i],background)) >= 20:
                    mask[i]=1
    # Flat controls supply a stronger background estimate than a tile crossing
    # their border. This recovers dark text on colored buttons without joining
    # the glyphs to the button outline.
    flat = [(b,c) for b,n,c in components
            if b[2]>=width*.035 and b[3]>=height*.045
            and .001<=b[2]*b[3]/(width*height)<=.6 and n/(b[2]*b[3])>=.45]
    for (left,top,w,h),background in sorted(flat,key=lambda item:item[0][2]*item[0][3],reverse=True):
        for y in range(top,top+h):
            for x in range(left,left+w):
                i=y*width+x
                mask[i]=int(sum((a-b)**2 for a,b in zip(colors[i],background))>=20)
    glyphs = []
    for seed in range(width*height):
        if not mask[seed]:
            continue
        mask[seed]=0
        stack=[seed]
        left=right=seed%width
        top=bottom=seed//width
        count=0
        while stack:
            i=stack.pop()
            x,y=i%width,i//width
            left,right=min(left,x),max(right,x)
            top,bottom=min(top,y),max(bottom,y)
            count+=1
            for yy in range(max(0,y-1),min(height,y+2)):
                for xx in range(max(0,x-1),min(width,x+2)):
                    j=yy*width+xx
                    if mask[j]:
                        mask[j]=0
                        stack.append(j)
        b=[left,top,right-left+1,bottom-top+1]
        if count>=3 and 3<=b[3]<=height*.065 and 1<=b[2]<=width*.10:
            glyphs.append(b)
    rows = []
    for b in sorted(glyphs,key=lambda b:(b[1]+b[3]/2,b[0])):
        matches = [r for r in rows if abs((r["box"][1]+r["box"][3]/2)-(b[1]+b[3]/2)) <= max(r["box"][3],b[3])*.5]
        if matches:
            r = min(matches,key=lambda r:abs(r["box"][1]-b[1]))
            r["glyphs"].append(b)
            r["box"] = union([r["box"],b])
        else:
            rows.append({"box":b,"glyphs":[b]})
    lines,words = [],[]
    for row in rows:
        line,word = [],[]
        for b in sorted(row["glyphs"],key=lambda b:b[0]):
            gap = b[0]-max((g[0]+g[2] for g in word),default=b[0])
            size = max(b[3], max((g[3] for g in word),default=b[3]))
            if word and gap>max(2,size*.55):
                words.append(padded(union(word),width,height))
                word=[]
            if line and b[0]-max(g[0]+g[2] for g in line)>size*1.8:
                lines.append(padded(union(line),width,height))
                line=[]
            word.append(b)
            line.append(b)
        if word:
            words.append(padded(union(word),width,height))
        if line:
            lines.append(padded(union(line),width,height))
    return controls,lines,words


def focus_region(controls, lines, point, changed=()):
    """A changed line or the smallest clicked control, including its label."""
    if changed:
        touched = [line for line in lines if any(intersects(line,b) for b in changed)]
        widgets = [b for b in controls if b[2]*b[3]<=.08
                   and any(intersects(b,c) for c in changed)]
        return union([*changed,*touched,*widgets]), "changed-lines"
    px,py = point
    enclosing = [b for b in controls if b[0]<=px<=b[0]+b[2] and b[1]<=py<=b[1]+b[3]]
    control = min(enclosing,key=lambda b:b[2]*b[3],default=None)
    if control and control[2]*control[3] <= .08:
        labels = [line for line in lines if intersects(control,line)]
        if not labels and lines:
            nearby = min(lines,key=lambda b:math.hypot(max(b[0]-px,0,px-b[0]-b[2]),max(b[1]-py,0,py-b[1]-b[3])))
            if math.hypot(max(nearby[0]-px,0,px-nearby[0]-nearby[2]),max(nearby[1]-py,0,py-nearby[1]-nearby[3])) < .06:
                labels=[nearby]
        return union([control,*labels]), "control-and-label"
    nearby = [b for b in lines if control is None or intersects(control,b)]
    if nearby:
        line = min(nearby,key=lambda b:math.hypot(max(b[0]-px,0,px-b[0]-b[2]),max(b[1]-py,0,py-b[1]-b[3])))
        if math.hypot(max(line[0]-px,0,px-line[0]-line[2]),max(line[1]-py,0,py-line[1]-line[3])) < .10:
            return line,"pointed-line"
    return control,"enclosing-region" if control else "unknown-full-source"


def enclosing_region(rgb, width, height, point):
    controls,lines,_ = geometry(rgb,width,height)
    return focus_region(controls,lines,point)[0]


def attach_regions(path, zooms, duration, ffmpeg="ffmpeg"):
    """Sample event frames and retain focus and word bounds across each hold."""
    if not zooms:
        return
    width,height,rate = 640,360,4
    wanted = {}
    for i,zoom in enumerate(zooms):
        action = max(zoom.evidence,key=lambda e:e.get("confidence",0))["t"]
        for t in (zoom.start, action+.25, min(zoom.end,duration-.05),
                  *[e["t"]+.25 for e in zoom.evidence],
                  *[zoom.start+j for j in range(1,math.ceil(zoom.end-zoom.start))]):
            index = min(max(0,math.floor((duration-.05)*rate)),max(0,round(t*rate)))
            wanted.setdefault(index,set()).add(i)
    found = {i:[] for i in range(len(zooms))}
    words = {i:[] for i in range(len(zooms))}
    kinds = {i:set() for i in range(len(zooms))}
    proc = subprocess.Popen([ffmpeg,"-v","error","-nostdin",*input_args(path),"-t",str(duration),
                             "-vf",f"fps={rate},scale={width}:{height}","-an","-f","rawvideo","-pix_fmt","rgb24","pipe:1"],
                            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    try:
        for index in range(math.ceil(duration*rate)+3):
            frame = proc.stdout.read(width*height*3)
            if not frame:
                break
            if len(frame)!=width*height*3:
                raise RuntimeError("Incomplete UI-region frame.")
            if index in wanted:
                controls,lines,guards = geometry(frame,width,height)
                for i in wanted[index]:
                    zoom = zooms[i]
                    changed = [e["box"] for e in zoom.evidence if e.get("box")]
                    box,kind = focus_region(controls,lines,(zoom.x,zoom.y),changed)
                    if box:
                        found[i].append(box)
                        kinds[i].add(kind)
                    words[i].extend(guards)
        if proc.wait(timeout=15):
            raise RuntimeError("FFmpeg could not decode UI-region frames.")
    finally:
        proc.stdout.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    for i,zoom in enumerate(zooms):
        zoom.box = union(found[i]) if found[i] else [0.,0.,1.,1.]
        zoom.box_evidence = {"kind":"focus-content" if found[i] else "unknown-full-source",
                             "methods":sorted(kinds[i]),"samples":len(found[i]),
                             "confidence":.65 if found[i] else 0.,
                             "words":[list(b) for b in sorted({tuple(b) for b in words[i]})]}
