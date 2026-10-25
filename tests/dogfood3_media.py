"""Original generated broadcast composite; no real-source pixels or transcripts."""

def composite_frames(*, frozen=False, split=False, ui=False):
    import pytest
    np = pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")
    ImageDraw = pytest.importorskip("PIL.ImageDraw")
    frames = []
    for i in range(12):
        background = np.zeros((180,320,3),dtype=np.uint8)
        background[:,:,0] = np.linspace(4,13,180,dtype=np.uint8)[:,None]
        background[:,:,1] = np.linspace(10,30,180,dtype=np.uint8)[:,None]
        background[:,:,2] = np.linspace(25,62,180,dtype=np.uint8)[:,None]
        image = Image.fromarray(background)
        draw = ImageDraw.Draw(image)
        for x in range(-30,340,47):
            draw.line((x,0,x+90,180),fill=(28,56,75),width=1)
            draw.line((x,180,x+120,0),fill=(18,38,60),width=1)
        def person(rect, phase, main=False):
            x,y,r,b = rect
            draw.rounded_rectangle(rect,radius=4,fill=(142,126,93))
            draw.rectangle((x+5,y+12,r-5,y+20),fill=(65,79,57))
            cx = (x+r)//2 + int(4*np.sin(phase*1.4))
            radius = int((b-y)*.18)
            cy = y+int((b-y)*.35)
            draw.ellipse((cx-radius,cy-radius,cx+radius,cy+radius),fill=(192,145,105))
            draw.rectangle((cx-radius,cy+radius,cx+radius,b-1),fill=(32,43,56))
            draw.rectangle((cx-radius+4,cy-4,cx-radius+7,cy-2),fill=(15,18,20))
            draw.rectangle((cx+radius-7,cy-4,cx+radius-4,cy-2),fill=(15,18,20))
            draw.line((cx-5,cy+10,cx+5,cy+10+phase%3),fill=(55,28,20),width=2)
            # A hand moves independently of the face, like a talking presenter.
            hx = cx+radius+int(7*np.sin(phase*.8))
            draw.ellipse((hx-6,b-28,hx+6,b-10),fill=(192,145,105))
        if split:
            person((3,20,156,160),i,True)
            person((164,20,317,160),i+2,True)
        else:
            person((3,20,250,160),0 if frozen else i,True)
            draw.rounded_rectangle((257,42,317,86),radius=3,fill=(4,6,9))
            draw.ellipse((277,53,297,73),outline=(230,190,80),width=3)
            draw.line((282,68,287,58,292,68),fill=(210,210,210),width=2)
            person((257,90,317,138),i+1)
        if ui:
            # The same large video and webcam inside dark UI are insufficient
            # evidence of removable broadcast chrome without an overlapping card.
            for x in range(20,280,35):
                draw.rectangle((x,5,x+8,11),fill=(180,180,190))
        else:
            draw.rounded_rectangle((10,150,116,170),radius=3,fill=(8,7,17),outline=(112,75,124),width=1)
            draw.text((31,153),"PRESENTER",fill=(240,240,240))
            draw.rectangle((31,165,99,166),fill=(92,83,120))
        frames.append(np.asarray(image))
    return np.asarray(frames)


def gray(frames):
    import numpy as np
    return np.rint(frames @ np.array([.299,.587,.114])).astype(np.uint8)


def write_composite(path):
    import subprocess
    result = subprocess.run(["ffmpeg","-v","error","-y","-f","rawvideo","-pix_fmt","rgb24",
        "-s","320x180","-r","2","-i","pipe:0","-vf","scale=960:540:flags=neighbor",
        "-c:v","libx264","-threads","1","-crf","12","-pix_fmt","yuv420p",str(path)],
        input=composite_frames().tobytes(),capture_output=True,timeout=60)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
