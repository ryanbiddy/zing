"""Real isolated Edge page recording and four screen-demo acceptance deliveries.

Run with UOINK_URL=http://127.0.0.1:1 and an ephemeral playwright install.
No browser profile is opened: launch() + new_context() use fresh temporary data.
"""

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

HTML = r'''<!doctype html><html><meta charset="utf-8"><title>SCREEN1 Local Build Lab</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#101820;color:#e7edf4;font:24px Arial}
header{padding:24px 40px;border-bottom:1px solid #375062}small{color:#9db2c6;font-size:17px}
main{display:flex;gap:32px;padding:38px}section{background:#1b2a38;border:1px solid #375062;border-radius:12px;padding:28px;width:560px}
button{font:24px Arial;padding:16px 22px;background:#69dfbd;color:#10232a;border:0;border-radius:8px;cursor:pointer}
pre{font:22px monospace;line-height:1.65;color:#c5d9ed}h2{font-size:24px;margin:0 0 25px}
#log{background:#0b131b;padding:22px;height:180px;color:#a7ebc7;line-height:1.6}
#pointer{position:fixed;pointer-events:none;width:0;height:0;border-left:12px solid white;border-right:4px solid transparent;border-bottom:20px solid transparent;filter:drop-shadow(1px 1px 2px black);z-index:50}
#flash{display:none;position:fixed;inset:0;background:white;z-index:99}
</style><header>Build Lab <small> / local acceptance fixture · no accounts or network</small></header>
<main><section><h2>1. Configure a build</h2><pre>project: hello-demo
target: local
checks: enabled</pre><button id="run">Run checks</button></section>
<section><h2>2. Review the result</h2><div id="log">Ready to run.</div><p><button id="detail">Show details</button></p></section></main><div id="pointer"></div><div id="flash"></div>
<script>
let start=0, pos={x:310,y:330}, rows=[];
function stamp(){return (performance.now()-start)/1000}
onmousemove=e=>{pos={x:e.clientX,y:e.clientY};pointer.style.left=pos.x+'px';pointer.style.top=pos.y+'px'};
onclick=e=>{if(start)rows.push({type:'click',t:stamp(),x:e.clientX/innerWidth,y:e.clientY/innerHeight,button:'left'})};
run.onclick=()=>{log.textContent='Running 3 local checks…';setTimeout(()=>{log.innerHTML='✓ Syntax passed<br>✓ Types passed<br>✓ Build passed';run.textContent='Checks passed'},750)};
detail.onclick=()=>{log.innerHTML='Build complete<br>3 checks passed<br>0 errors';detail.textContent='Details open'};
function begin(){start=performance.now();flash.style.display='block';setTimeout(()=>flash.style.display='none',300);window.timer=setInterval(()=>rows.push({type:'cursor',t:stamp(),x:pos.x/innerWidth,y:pos.y/innerHeight}),1000/60)}
</script>'''


def capture(root, executable):
    from playwright.sync_api import sync_playwright
    root.mkdir(parents=True,exist_ok=True)
    page_file=root/"local-demo.html"
    page_file.write_text(HTML,encoding="utf-8")
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=executable,headless=True,args=["--disable-background-networking"])
        context=browser.new_context(viewport={"width":1280,"height":720},record_video_dir=str(root/"capture"),record_video_size={"width":1280,"height":720})
        context.route("http://**/*",lambda route:route.abort())
        context.route("https://**/*",lambda route:route.abort())
        page=context.new_page()
        page.goto(page_file.resolve().as_uri())
        page.wait_for_timeout(1000)
        page.mouse.move(310,330)
        wall_start=datetime.now(timezone.utc).isoformat()
        page.evaluate("begin()")
        page.wait_for_timeout(1200)
        run=page.locator("#run").bounding_box()
        page.mouse.move(run['x']+run['width']/2,run['y']+run['height']/2,steps=24)
        page.wait_for_timeout(700)
        page.mouse.click(run['x']+run['width']/2,run['y']+run['height']/2)
        page.wait_for_timeout(1700)
        detail=page.locator("#detail").bounding_box()
        page.mouse.move(detail['x']+detail['width']/2,detail['y']+detail['height']/2,steps=40)
        page.wait_for_timeout(700)
        page.mouse.click(detail['x']+detail['width']/2,detail['y']+detail['height']/2)
        page.wait_for_timeout(3800)
        elapsed=page.evaluate("stamp()")
        rows=page.evaluate("clearInterval(timer); rows")
        video=page.video
        context.close()
        recorded=Path(video.path())
        browser.close()
    # Find the known white sync flash after at least one dark app frame.
    scan=subprocess.run(["ffmpeg","-v","error","-i",str(recorded),"-vf","fps=30,scale=1:1","-f","rawvideo","-pix_fmt","gray","pipe:1"],capture_output=True,check=True)
    dark=False
    flash=None
    for i,level in enumerate(scan.stdout):
        if level<140: dark=True
        if dark and level>235:
            flash=i/30
            break
    if flash is None: raise RuntimeError("Real recording lacks the scripted sync flash")
    source=root/"real-screen.mp4"
    subprocess.run(["ffmpeg","-v","error","-y","-ss",str(flash),"-i",str(recorded),"-t",str(elapsed),
                    "-c:v","libx264","-crf","18","-pix_fmt","yuv420p",str(source)],check=True)
    header={"type":"start","version":1,"t":0,"wall_time":wall_start,"hz":60,"bounds":[0,0,1280,720],
            "sync":"Simulated browser telemetry; real video trimmed at white sync flash. Screencast latency is unmeasured."}
    rows=[header,*sorted(rows,key=lambda e:e['t']),{"type":"stop","t":elapsed,"samples":len(rows)}]
    log=root/"simulated-cursor.jsonl"
    log.write_text("".join(json.dumps(r)+"\n" for r in rows),encoding="utf-8")
    (root/"capture-metadata.json").write_text(json.dumps({"raw_video":str(recorded),"flash_seconds":flash,"duration":elapsed,
        "browser":"fresh isolated Edge context, headless", "telemetry":"scripted browser input positions, not native OS capture"},indent=2),encoding="utf-8")
    return source,log


def deliver(root,source,log):
    from myzing.screen.api import plan_screen,save_plan
    from myzing.screen.render import render_screen
    from myzing.screen.planner import output_time,crop_window
    results=[]
    raw=[json.loads(s) for s in log.read_text().splitlines()]
    clicks=[r for r in raw if r['type']=='click']
    # Explicitly authored guide captions for this fixture, not ASR or key text.
    words=[]
    for click, text in zip(clicks, ('Run the local checks', 'Review the build result')):
        for i, word in enumerate(text.split()):
            start=max(0,click['t']-.4)+i*.4
            words.append({'text':word,'start':start,'end':start+.4})
    (root/'authored-caption-words.json').write_text(json.dumps(words,indent=2),encoding='utf-8')
    for telemetry in (True,False):
        name="telemetry" if telemetry else "activity"
        plan=plan_screen(source,cursor=log if telemetry else None,ui_text_px=24,click_highlights=telemetry,words=words)
        save_plan(plan,root/(name+"-plan.json"))
        for aspect in ("16:9","9:16"):
            label=name+"-"+aspect.replace(":","x")
            result=render_screen(plan,root/(label+".mp4"),aspect=aspect,short_side=720)
            cam=json.loads(Path(result['camera']).read_text())
            clicks=[]
            raw=[json.loads(s) for s in log.read_text().splitlines()]
            for e in [e for e in raw if e['type']=='click']:
                t=output_time(cam['time_map'],e['t'])
                k=min(cam['keys'],key=lambda k:abs(k['t']-t))
                x,y,w,h=crop_window(plan,cam,k)
                clicks.append(x+.05*w<=e['x']*plan.width<=x+.95*w and y+.05*h<=e['y']*plan.height<=y+.95*h)
            duration=cam['duration']
            # Each cell is a 400px-wide phone presentation, not a huge overview.
            times=[min(duration-.1,t) for t in (.4,1.8,3.0,4.5,6.0,duration-.2)]
            pngs=[]
            for i,t in enumerate(times):
                dest=root/f"{label}-{i}.png"
                subprocess.run(["ffmpeg","-v","error","-y","-ss",str(t),"-i",result['video'],"-frames:v","1","-vf","scale=400:-2",str(dest)],check=True)
                pngs.append(dest)
            from PIL import Image,ImageDraw
            images=[Image.open(p).convert('RGB') for p in pngs]
            cell_h=images[0].height+28
            sheet=Image.new('RGB',(1200,cell_h*2),'#101820')
            draw=ImageDraw.Draw(sheet)
            for i,img in enumerate(images):
                x,y=(i%3)*400,(i//3)*cell_h
                sheet.paste(img,(x,y+28));draw.text((x+8,y+6),f"{label}  {times[i]:.2f}s",fill='white')
            contact=root/(label+"-phone.png");sheet.save(contact)
            velocities={}
            for axis in ('x','y','zoom'):
                v=[(b[axis]-a[axis])*30 for a,b in zip(cam['keys'],cam['keys'][1:]) if not b.get("cut")]
                velocities[axis]={'velocity':max(map(abs,v)),'acceleration':max(abs(b-a)*30 for a,b in zip(v,v[1:]))}
            edges={axis:{'velocity':0.,'acceleration':0.} for axis in ('left','top','right','bottom')}
            for shot in cam['shots']:
                for axis,values in zip(edges,zip(*[(x/plan.width,y/plan.height,(x+w)/plan.width,(y+h)/plan.height)
                        for k in shot['keys'] for x,y,w,h in [k['window']]])):
                    v=[(b-a)*plan.fps for a,b in zip(values,values[1:])]
                    edges[axis]['velocity']=max(edges[axis]['velocity'],max(map(abs,v),default=0.))
                    edges[axis]['acceleration']=max(edges[axis]['acceleration'],max((abs(b-a)*plan.fps for a,b in zip(v,v[1:])),default=0.))
            results.append({**result,"contact_sheet":str(contact),"click_coverage":clicks,"motion":velocities,
                            "visible_edge_motion_within_shots":edges,
                            "source_duration":plan.duration,"zoom_count":len(plan.zooms),"idle":plan.idle,
                            "cuts":cam['cuts'], "caption_source":"explicitly authored fixture guide",
                            "element_fit":all(
                                x <= s['box'][0]*plan.width and y <= s['box'][1]*plan.height and
                                x+w >= (s['box'][0]+s['box'][2])*plan.width and
                                y+h >= (s['box'][1]+s['box'][3])*plan.height
                                for s in cam['shots'] for k in s['keys'] for x,y,w,h in [k['window']])})
            (root/(label+'-verification.json')).write_text(json.dumps(results[-1],indent=2),encoding='utf-8')
    (root/'acceptance.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    return results


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--out',type=Path,default=Path('zing-workspace/screen1-real'))
    p.add_argument('--edge',default=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
    p.add_argument('--reuse',action='store_true')
    a=p.parse_args()
    a.out=a.out.resolve()
    source,log=(a.out/'real-screen.mp4',a.out/'simulated-cursor.jsonl') if a.reuse else capture(a.out,a.edge)
    print(json.dumps(deliver(a.out,source,log),indent=2))
