"""Conservative removal of thin, baked-in black source borders for full crops."""

from functools import lru_cache
import subprocess


def thin_border_bounds(frames):
    """Require a <=2% black edge in every sample and a brighter inner boundary."""
    import numpy as np
    data = np.asarray(frames)
    if data.ndim != 3 or len(data) < 3:
        return None
    _, h, w = data.shape
    edges = []
    for axis, reverse, extent in ((2,False,h),(2,True,h),(1,False,w),(1,True,w)):
        profiles = np.percentile(data,95,axis=axis)
        if reverse:
            profiles = profiles[:,::-1]
        counts = []
        for profile in profiles:
            count = 0
            while count < len(profile) and profile[count] < 24:
                count += 1
            # A fade/dark frame or substantial matte is outside this repair.
            if not 1 <= count <= extent*.02 or profile[count:count+3].mean() < 40:
                count = 0
            counts.append(count)
        edge = min(counts) if min(counts) > 0 and max(counts)-min(counts) <= 1 else 0
        # Crop whole even pixels without removing picture: an odd run rounds
        # down unless the next pixel is a dark antialiased edge in every sample.
        if edge % 2:
            edge += 1 if all(p[edge] < 40 for p in profiles) else -1
        edges.append(int(edge))
    top,bottom,left,right = edges
    if not any(edges):
        return None
    return left,top,w-left-right,h-top-bottom


@lru_cache(maxsize=96)
def sample_border_bounds(source, start, end, sw, sh):
    import numpy as np
    frames = []
    try:
        for fraction in (.1,.5,.9):
            result = subprocess.run(['ffmpeg','-v','error','-nostdin','-ss',str(start+(end-start)*fraction),
                '-protocol_whitelist','file,pipe','-i',source,'-vf',f'scale={sw}:{sh},format=gray',
                '-frames:v','1','-f','rawvideo','-pix_fmt','gray','pipe:1'],
                capture_output=True,timeout=30,check=False)
            if result.returncode or len(result.stdout) != sw*sh:
                return None
            frames.append(np.frombuffer(result.stdout,dtype=np.uint8).reshape(sh,sw))
        return thin_border_bounds(frames)
    except (OSError,subprocess.SubprocessError):
        return None
