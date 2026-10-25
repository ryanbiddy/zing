"""Bounded, local broadcast-stage detection from gray temporal samples.

Unlike a border detector, a composite may contain another moving picture.
Four persistent edges, a dominant stage, one small moving inset and a flat,
structured backdrop must agree. These are geometric observations, not identities.
"""

def _peaks(scores, limit=14):
    chosen = []
    for i in sorted(range(len(scores)), key=lambda i: (-scores[i], i)):
        if scores[i] < .55:
            break
        if all(abs(i-j) > 3 for j in chosen):
            chosen.append(i)
        if len(chosen) == limit:
            break
    return sorted(chosen)


def _motion_tile(active):
    """Largest dense moving component; sparse animated network lines are chrome."""
    import numpy as np
    h, w = active.shape
    integral = np.pad(active.astype(int), ((4,4),(4,4))).cumsum(0).cumsum(1)
    dense = (integral[7:,7:] - integral[:-7,7:] - integral[7:,:-7] + integral[:-7,:-7])[:h,:w] >= 25
    seen, components = set(), []
    for y,x in zip(*np.nonzero(dense)):
        if (y,x) in seen:
            continue
        stack, points = [(y,x)], []
        seen.add((y,x))
        while stack:
            yy,xx = stack.pop()
            points.append((yy,xx))
            for dy,dx in ((-1,0),(1,0),(0,-1),(0,1)):
                p = yy+dy,xx+dx
                if 0 <= p[0] < h and 0 <= p[1] < w and dense[p] and p not in seen:
                    seen.add(p)
                    stack.append(p)
        components.append(points)
    points = max(components, key=len, default=[])
    if len(points) < h*w*.003:
        return None
    yy,xx = zip(*points)
    return tuple(map(int, (max(0,min(xx)-3),max(0,min(yy)-3),min(w,max(xx)+4),min(h,max(yy)+4))))


def _lower_thirds(data, rectangle):
    """Static, thin, closed graphic cards overlapping the stage's bottom edge."""
    import numpy as np
    _,h,w = data.shape
    x,y,r,b = rectangle
    mean, temporal = data.mean(0), data.std(0)
    edge = (np.abs(np.diff(data,axis=1)) > 6).mean(0) >= .8
    sides = (np.abs(np.diff(data,axis=2)) > 6).mean(0) >= .8
    segments = []
    for row in range(max(1,int(y+.72*(b-y))), min(h-1,b+int(h*.12))):
        filled = np.convolve(edge[row-1],np.ones(5),mode='same') >= 3
        changes = np.diff(np.r_[False,filled,False].astype(int))
        for a,z in zip(np.flatnonzero(changes == 1),np.flatnonzero(changes == -1)):
            if .2*w <= z-a <= .65*w:
                segments.append((row,int(a),int(z)))
    candidates = []
    for top,a,z in segments:
        for bottom,c,d in segments:
            left,right = max(a,c),min(z,d)
            if not .03*h <= bottom-top <= .15*h or right-left < .2*w or bottom < b-3:
                continue
            if bottom-top <= 4 or any(max(
                sides[top+2:bottom-2,k-1].mean()
                for k in range(max(1,side-3),min(w-1,side+3)+1)) < .6 for side in (left,right)):
                continue
            region = mean[top:bottom,left:right]
            if (temporal[top:bottom,left:right] <= 3).mean() < .95 or np.median(region) > 70:
                continue
            flat = (np.maximum(np.abs(np.diff(region,axis=0))[:,:-1],np.abs(np.diff(region,axis=1))[:-1]) <= 2).mean()
            if flat < .6:
                continue
            candidates.append(((right-left)*(bottom-top),left,top,right,bottom))
    if not candidates:
        return []
    _,left,top,right,bottom = max(candidates)
    return [{"kind": "lower-third", "bounds_normalized": [left/w,top/h,(right-left)/w,(bottom-top)/h],
             "reason": "persistent thin graphic card overlapping the stage bottom; not recovered text"}]


def detect_stage(data, *, content_bounds=None):
    import numpy as np
    _, h, w = data.shape
    mean, temporal = data.mean(axis=0), data.std(axis=0)
    moving = temporal > 3
    # Three-pixel contrast tolerates area averaging, low-contrast edges and
    # rounded corners. The same edge must exist in at least 80% of samples.
    horizontal = np.zeros((h, w), dtype=bool)
    vertical = np.zeros((h, w), dtype=bool)
    horizontal[2:-1] = (np.abs(data[:, 3:] - data[:, :-3]) > 3).mean(axis=0) >= .8
    vertical[:, 2:-1] = (np.abs(data[:, :, 3:] - data[:, :, :-3]) > 3).mean(axis=0) >= .8
    # Near-edge stages may start within two sample pixels of the source edge.
    vertical[:, 1] = (np.abs(data[:, :, 2] - data[:, :, 0]) > 3).mean(axis=0) >= .8
    horizontal[1] = (np.abs(data[:, 2] - data[:, 0]) > 3).mean(axis=0) >= .8
    rows = _peaks([np.convolve(row, np.ones(max(1, int(w*.55))), 'valid').max() / int(w*.55)
                   for row in horizontal])
    cols = _peaks([np.convolve(col, np.ones(max(1, int(h*.45))), 'valid').max() / int(h*.45)
                   for col in vertical.T])
    hp = np.pad(horizontal.cumsum(axis=1), ((0, 0), (1, 0)))
    vp = np.pad(vertical.cumsum(axis=0), ((1, 0), (0, 0)))
    proposals = []
    for x in cols:
        for r in cols:
            if r-x < w*.55:
                continue
            for y in rows:
                for b in rows:
                    area = (r-x)*(b-y)/(w*h)
                    if b-y < h*.45 or not .4 <= area <= .86:
                        continue
                    # Ignore rounded corners; an overlapping card may obscure
                    # part of one edge, but the other edges must corroborate it.
                    dx, dy = max(2, int((r-x)*.025)), max(2, int((b-y)*.025))
                    edges = [(hp[k, r-dx]-hp[k, x+dx])/(r-x-2*dx) for k in (y,b)]
                    edges += [(vp[b-dy, k]-vp[y+dy, k])/(b-y-2*dy) for k in (x,r)]
                    if min(edges) >= .55 and np.mean(edges) >= .8:
                        proposals.append((area, float(np.mean(edges)), (x,y,r,b), edges))
    ambiguous = None
    for area, border, (x,y,r,b), edges in sorted(proposals, key=lambda p: (p[0]*p[1],p[0]), reverse=True):
        # Locate the sharp edge within the broad contrast band before cropping.
        sharp_h = (np.abs(np.diff(data,axis=1)) > 3).mean(axis=0) >= .8
        sharp_v = (np.abs(np.diff(data,axis=2)) > 3).mean(axis=0) >= .8
        y,b = [max(range(max(1,k-2),min(h-1,k+2)+1),
                   key=lambda p: sharp_h[p-1,x+3:r-3].mean()) for k in (y,b)]
        x,r = [max(range(max(1,k-2),min(w-1,k+2)+1),
                   key=lambda p: sharp_v[y+3:b-3,p-1].mean()) for k in (x,r)]
        area = (r-x)*(b-y)/(w*h)
        outside = np.ones((h,w), dtype=bool)
        outside[max(0,y-3):min(h,b+3), max(0,x-3):min(w,r+3)] = False
        active = moving & outside
        tile = _motion_tile(active)
        if tile is None:
            continue  # No second moving tile: leave the matte/scenery/UI guards to picture.py.
        tx,ty,tr,tb = tile
        tile_area = (tr-tx)*(tb-ty)/(w*h)
        overlap = max(0,min(r,tr)-max(x,tx))*max(0,min(b,tb)-max(y,ty))/(w*h)
        if not .01 <= tile_area <= .35*area or overlap > tile_area*.1:
            continue  # Equal speakers, distributed scenery motion or a wide second stage.
        backdrop = outside.copy()
        backdrop[max(0,ty-4):min(h,tb+4),max(0,tx-4):min(w,tr+4)] = False
        if content_bounds is not None:
            # Established outer chrome cannot supply evidence that a region
            # inside the live picture is itself a broadcast stage. In
            # particular, colored test bars inside an ordinary bordered video
            # must not borrow its dark padding as their composite backdrop.
            cx,cy,cw,ch = content_bounds
            content = np.zeros((h,w),dtype=bool)
            content[round(cy*h):round((cy+ch)*h),round(cx*w):round((cx+cw)*w)] = True
            backdrop &= content
        if backdrop.sum() < h*w*.01:
            continue
        static = float((temporal[backdrop] <= 3).mean())
        gx, gy = np.zeros_like(mean), np.zeros_like(mean)
        gx[:,1:], gy[1:] = np.abs(np.diff(mean,axis=1)), np.abs(np.diff(mean,axis=0))
        flat = float((np.maximum(gx,gy)[backdrop] <= 2).mean())
        std, level = float(mean[backdrop].std()), float(np.median(mean[backdrop]))
        motion = float(moving[y:b,x:r].mean())
        activity = (np.abs(np.diff(data[:,y:b,x:r],axis=0)) > 3).mean(axis=(1,2))
        sustained = float((activity >= .01).mean())
        # Patterned graphics may vary spatially; scenery has dense texture.
        # A uniform matte is not evidence of a broadcast composite.
        if static < .75 or flat < .75 or std < 6 or level > 70 or motion < .03 or sustained < .8:
            continue
        cards = _lower_thirds(data,(x,y,r,b))
        if not cards:
            ambiguous = {"version": 1, "kind": "unknown", "confident": False, "confidence": 0.,
                         "reason": "moving video panels without an overlapping broadcast card; possible dark-mode UI"}
            continue  # Video panels and a webcam alone can also be dark-mode UI.
        confidence = min(border, sustained)
        return {"version": 1, "kind": "broadcast-composite", "confident": True,
                "confidence": confidence, "geometric_confidence": border,
                "bounds_normalized": [x/w,y/h,(r-x)/w,(b-y)/h],
                "sample_count": len(data), "border_support": [float(v) for v in edges],
                "retained_area": area, "live_moving_fraction": motion,
                "sustained_motion_fraction": sustained, "minimum_pair_motion": float(activity.min()),
                "static_backdrop_fraction": static, "secondary_area_ratio": tile_area/area,
                "backdrop_scope": "inside bordered picture" if content_bounds is not None else "full source",
                "secondary_bounds_normalized": [float(tx/w),float(ty/h),float((tr-tx)/w),float((tb-ty)/h)],
                "chrome_regions": cards,
                "surround": {"kind": "chrome", "flat_fraction": flat, "spatial_std": std, "median_luma": level},
                "reason": "dominant four-edge stage with sustained motion; small separate moving tile, overlapping graphic card and static patterned backdrop",
                "thresholds": {"edge_persistence": .8, "minimum_edge_support": .55, "mean_edge_support": .8,
                               "minimum_stage_area": .4, "maximum_secondary_stage_ratio": .35,
                               "minimum_static_backdrop": .75, "minimum_flat_backdrop": .75,
                               "minimum_sustained_motion": .8, "requires_overlapping_graphic_card": True}}
    return ambiguous
