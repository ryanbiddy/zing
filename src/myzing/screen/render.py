"""Oversampled crop/zoompan camera, balanced expressions, FFmpeg 6 through 9."""

from __future__ import annotations

import json
import math
import subprocess
import tempfile
from pathlib import Path

from .analysis import input_args
from .models import ScreenPlan
from .planner import camera, crop_window, dimensions, output_time


def expression(keys, field, variable="t"):
    """Balanced binary search: FFmpeg 8 rejects long flat sums/nested chains."""
    def build(a, b):
        if b-a == 1:
            left, right = keys[a], keys[a+1]
            delta = right[field]-left[field]
            if abs(delta) < 1e-9:
                return f"{left[field]:.9f}"
            return f"({left[field]:.9f}+{delta:.9f}*clip(({variable}-{left['t']:.9f})/{max(1e-9,right['t']-left['t']):.9f},0,1))"
        m = (a+b)//2
        return f"if(lt({variable},{keys[m]['t']:.9f}),{build(a,m)},{build(m,b)})"
    return build(0,len(keys)-1) if len(keys)>1 else f"{keys[0][field]:.9f}"


def _captions(plan, cam, width, height, work, ffmpeg):
    if not plan.words or plan.caption_preset == "none":
        return "", []
    from myzing.composition import Composition, CompositionClip, CompositionCaption, AssetRef
    from myzing.schemas import Word
    from myzing.captions.presets import apply_preset
    from myzing.layout.framing import place_captions
    from myzing.layout.types import FaceTrack, Keyframe, Box
    from myzing.render.font_files import private_font
    from myzing.render.positioned_captions import generate_positioned_ass
    from myzing.ffmpeg_capabilities import caption_filter
    words = [Word(w["text"], output_time(cam["time_map"], w["start"]), output_time(cam["time_map"],w["end"])) for w in plan.words]
    composition = Composition(width=width, height=height,
        assets=[AssetRef("screen",plan.source,plan.sha256,cam["duration"])],
        clips=[CompositionClip(plan.source,0,cam["duration"],0,id="screen",asset_id="screen")],
        captions=[CompositionCaption(" ".join(w.text for w in words),words[0].start,words[-1].end,id="speech",words=words,all_caps=False)])
    apply_preset(composition,plan.caption_preset,vad=False)
    targets = []
    scenes = [(output_time(cam["time_map"],z.start),output_time(cam["time_map"],z.end),z) for z in plan.zooms]
    target = (plan.zooms[0].x,plan.zooms[0].y) if plan.zooms else (.5,.5)
    for k in cam["keys"]:
        x,y,w,h = crop_window(plan,cam,k)
        active = next((z for a,b,z in scenes if a <= k["t"] < b),None)
        if active:
            target = (active.x,active.y)
        focus_x = min(.85,max(.15,(target[0]*plan.width-x)/w))
        focus_y = min(.85,max(.15,(target[1]*plan.height-y)/h))
        targets.append(Keyframe(k["t"],Box(focus_x-.15,focus_y-.12,.30,.24)))
    focus = FaceTrack("ui-focus",targets,1.)
    place_captions(composition,{"screen":[focus]},{"screen":(width,height)})
    if any(c.layout and not c.layout.overlap.safe for c in composition.captions):
        raise ValueError("No safe caption rail clears the zoomed UI focus. Shorten the supplied caption phrases or use --caption-preset none.")
    fonts = {c.id: private_font(Path(c.font.path).read_bytes()) for c in composition.captions}
    filter_name = caption_filter(ffmpeg)
    generate_positioned_ass(composition,fonts,work,ffmpeg,filter_name)
    (work/"caption-plan.json").write_text(json.dumps(composition.to_dict(),indent=2),encoding="utf-8")
    return f",{filter_name}=filename=captions.ass:fontsdir=fonts", composition.warnings


def graph(plan, cam, width, height, has_audio, caption_filter=""):
    segments = cam["time_map"]
    lines = []
    # Split once; preserve continuous audio with atempo on the same time map.
    n = len(segments)
    lines.append(f"[0:v]split={n}"+"".join(f"[v{i}]" for i in range(n)))
    if has_audio:
        lines.append(f"[0:a]asplit={n}"+"".join(f"[a{i}]" for i in range(n)))
    for i,s in enumerate(segments):
        lines.append(f"[v{i}]trim=start={s['start']:.9f}:end={s['end']:.9f},setpts=(PTS-STARTPTS)/{s['speed']}[p{i}]")
        if has_audio:
            speed, tempo = s["speed"], []
            while speed > 2:
                tempo.append("atempo=2")
                speed /= 2
            tempo.append(f"atempo={speed}")
            lines.append(f"[a{i}]atrim=start={s['start']:.9f}:end={s['end']:.9f},asetpts=PTS-STARTPTS,"+",".join(tempo)+f"[q{i}]")
    labels = "".join(f"[p{i}]"+(f"[q{i}]" if has_audio else "") for i in range(n))
    lines.append(labels+f"concat=n={n}:v=1:a={int(has_audio)}[timed]"+("[audio]" if has_audio else ""))
    # Oversampling and 4:4:4 eliminate the two-source-pixel chroma crop steps.
    # A fixed aspect crop pans first; zoompan then does the fractional zoom.
    factor = 4 if plan.width <= 1920 else 2
    sw, sh = plan.width*factor, plan.height*factor
    bw, bh = round(cam["base_width"]*factor), round(cam["base_height"]*factor)
    keys = []
    for k in cam["keys"]:
        left,top,w,h = crop_window(plan,cam,k)
        center_x,center_y = left+w/2,top+h/2
        base_x = max(0,min(plan.width-cam["base_width"],center_x-cam["base_width"]/2))
        base_y = max(0,min(plan.height-cam["base_height"],center_y-cam["base_height"]/2))
        keys.append({**k,"bx":base_x*factor,"by":base_y*factor,
                     "zx":(left-base_x)*factor,"zy":(top-base_y)*factor})
    # Sample the spring at output frame times. Expressions select only a single
    # interval, so graph depth grows logarithmically with recording duration.
    bx,by = (expression(keys,k) for k in ("bx","by"))
    z,zx,zy = (expression(keys,k,f"on/{plan.fps}") for k in ("zoom","zx","zy"))
    highlights = ""
    if plan.click_highlights:
        for e in plan.clicks:
            start = output_time(segments,e["t"])
            px,py = round(e["x"]*plan.width)-10,round(e["y"]*plan.height)-10
            highlights += f",drawbox=x={px}:y={py}:w=20:h=20:color=0xFFD23F@0.8:t=3:enable='between(t,{start:.6f},{start+.28:.6f})'"
    lines.append(f"[timed]fps={plan.fps},setsar=1{highlights},format=yuv444p,"
                 f"scale={sw}:{sh}:flags=bicubic:in_color_matrix=bt709:out_color_matrix=bt709:out_range=tv,"
                 f"crop={bw}:{bh}:x='{bx}':y='{by}':exact=1,"
                 f"zoompan=z='{z}':x='{zx}':y='{zy}':d=1:s={width}x{height}:fps={plan.fps},"
                 f"setsar=1{caption_filter},format=yuv420p[video]")
    return ";\n".join(lines)


def render_screen(plan, output, *, aspect="16:9", short_side=720, ffmpeg="ffmpeg", ffprobe="ffprobe", work_dir=None):
    from myzing.project.api import hash_file
    from myzing.render.pipeline import probe_media, filter_script_args, _publish_output
    from myzing.render.framing import probe_dimensions
    plan = ScreenPlan.from_dict(plan.to_dict())
    source = Path(plan.source).resolve()
    output = Path(output).expanduser().resolve()
    if output == source or output == Path(plan.sync.get("cursor_file", source)).resolve():
        raise ValueError("Screen render output would replace an input; choose another path.")
    if hash_file(source) != plan.sha256:
        raise ValueError("Screen source changed after planning; run zing plan screen again.")
    info = probe_media(source, ffprobe)
    if probe_dimensions(source,ffprobe) != (plan.width,plan.height) or abs(info.duration-plan.duration) > .1:
        raise ValueError("Screen plan dimensions/duration differ from the source; replan.")
    width,height = dimensions(aspect,short_side)
    cam = camera(plan,width,height)
    output.parent.mkdir(parents=True,exist_ok=True)
    work = Path(work_dir).resolve() if work_dir else Path(tempfile.mkdtemp(prefix="screen-work-",dir=output.parent))
    work.mkdir(parents=True,exist_ok=True)
    captions,caption_notes = _captions(plan,cam,width,height,work,ffmpeg)
    script = work/"camera.ffscript"
    script.write_text(graph(plan,cam,width,height,info.has_audio,captions),encoding="utf-8")
    staging = Path(tempfile.mkdtemp(prefix="output-",dir=work))
    staged = staging/"render.mp4"
    command = [ffmpeg,"-hide_banner","-v","error","-nostdin","-y",*input_args(source),
               "-filter_complex_threads","1",*filter_script_args(ffmpeg,script),"-map","[video]"]
    if info.has_audio:
        command += ["-map","[audio]","-c:a","aac","-b:a","160k"]
    command += ["-c:v","libx264","-preset","fast","-crf","18","-threads","2","-pix_fmt","yuv420p",
                "-color_primaries","bt709","-color_trc","bt709","-colorspace","bt709","-color_range","tv",
                "-t",f"{cam['duration']:.9f}","-movflags","+faststart",str(staged)]
    run = subprocess.run(command,cwd=work,capture_output=True,timeout=max(120,plan.duration*40))
    if run.returncode:
        raise RuntimeError("Screen render failed: "+run.stderr.decode(errors="replace")[-2500:])
    checked = probe_media(staged,ffprobe)
    if abs(checked.duration-cam["duration"]) > 2/plan.fps+.03:
        raise RuntimeError("Screen render duration differs from the source/output map.")
    _publish_output(staged,output)
    staging.rmdir()
    evidence = work/"camera.json"
    evidence.write_text(json.dumps(cam,indent=2,allow_nan=False),encoding="utf-8")
    return {"video":str(output),"camera":str(evidence),"filtergraph":str(script),"duration":checked.duration,
            "width":width,"height":height,"warnings":[*plan.warnings,*cam["warnings"],*caption_notes]}
