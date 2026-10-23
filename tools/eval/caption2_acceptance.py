"""Render the hash-verified V1 caption packet; media remains in zing-workspace.

Run with UOINK_URL=http://127.0.0.1:1. --baseline-src loads the unmodified
e8c231e source exported by git archive, using the same repaired transcript.
"""

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-src",type=Path)
    parser.add_argument("--version",default="8.1.2")
    args=parser.parse_args()
    if args.baseline_src:
        sys.path.insert(0,str(args.baseline_src.resolve()))
    from myzing.brief.models import Brief
    from myzing.composition import AssetRef,CaptionStyle,Composition,CompositionCaption,CompositionClip
    from myzing.layout.framing import centered_framing,place_captions
    from myzing.layout.readability import hold_short_events,phone_word_groups
    from myzing.layout.types import FaceTrack
    from myzing.render.composition import render_composition
    from myzing.schemas import Word
    from PIL import Image,ImageDraw

    root=Path("zing-workspace/caption2").resolve()
    manifest=json.loads(Path("tools/eval/real/manifest.json").read_text())
    results=[]
    for name in ("korky","tos-dialogue"):
        source=root/"clips"/(name+".mp4")
        entry=next(c for c in manifest["clips"] if c["id"]==name)
        assert hashlib.sha256(source.read_bytes()).hexdigest()==entry["sha256"]
        data=json.loads((root/(name+"-breakdown.json")).read_text())
        transcript=json.loads((root/(name+"-words.json")).read_text())
        words=[Word(**w) for w in transcript["words"]]
        tracks=[FaceTrack.from_dict(t) for t in json.loads((root/(name+"-layout.json")).read_text())["tracks"]]
        for aspect,w,h in (("9x16",360,640),("16x9",640,360)):
            for preset in (("before",) if args.baseline_src else ("punch","box","clean")):
                folder=root/args.version/f"{name}-{aspect}-{preset}"
                folder.mkdir(parents=True,exist_ok=True)
                metadata=folder/"metrics.json"
                if metadata.exists():
                    results.append(json.loads(metadata.read_text()))
                    continue
                clips=[]
                for i,shot in enumerate(data["shots"]):
                    c=CompositionClip(str(source),shot["start"],shot["end"],shot["start"],id=f"shot-{i}",asset_id="media")
                    c.framing=centered_framing("blurfill",entry["width"],entry["height"],w,h)
                    clips.append(c)
                p=Composition(assets=[AssetRef("media",str(source),entry["sha256"],entry["duration"])],
                    clips=clips,width=w,height=h,brief=Brief(caption_mode="phone" if preset=="before" else preset),
                    captions=[CompositionCaption(" ".join(x.text for x in words),words[0].start,words[-1].end,id="source",words=words,all_caps=False)])
                if preset=="before":
                    from myzing.director.continuity import clauses
                    groups=[g for clause in clauses(words) for g in phone_word_groups([word for word in words if word.start>=clause.start and word.end<=clause.end])]
                    p.captions=[CompositionCaption(" ".join(x.text for x in group),group[0].start,group[-1].end,
                        id=f"phone-{i}",words=group,all_caps=False,word_timed=True,
                        style=CaptionStyle(60,outline_width=4,box_color="#111111")) for i,group in enumerate(groups)]
                    hold_short_events(p.captions,entry["duration"])
                else:
                    from myzing.captions.presets import apply_preset
                    apply_preset(p,preset)
                place_captions(p,{"media":tracks},{"media":(entry["width"],entry["height"])})
                # The packet must expose infeasible layouts for visual review.
                unsafe=[c.id for c in p.captions if not c.layout.overlap.safe]
                p.accepted_unsafe_layouts=unsafe
                (folder/"plan.json").write_text(p.to_json(),encoding="utf-8")
                output=folder/"render.mp4"
                if not output.exists():
                    render_composition(p,output,work_dir=folder/"render-work")
                ass=(folder/"render-work/captions.ass").read_text(encoding="utf-8")
                if preset!="before":
                    from myzing.captions.render import geometry
                    geometry_rows=[geometry(c,w,h) for c in p.captions]
                    anchors=[(row["anchor_x"],row["baseline"]) for row in geometry_rows]
                else:
                    # Legacy \\an5 positions share the same font cell; their
                    # y offsets measure the old per-string ink centering.
                    text_rows=[line for line in ass.splitlines() if line.startswith("Dialogue: 1,")]
                    def stamp(value):
                        hh,mm,ss=map(float,value.split(":")); return hh*3600+mm*60+ss
                    anchors=[]
                    for c in p.captions:
                        line=next(line for line in text_rows if abs(stamp(line.split(",")[1])-c.start)<.05)
                        anchors.append(tuple(map(float,re.search(r"\\(?:pos|move)\(([^,]+),([^,\)]+)",line).groups())))
                movements=[]
                flips=0
                for i in range(1,len(p.captions)):
                    a,b=p.captions[i-1:i+1]
                    if any(c.timeline_start<=a.start<=b.start<c.timeline_end for c in clips):
                        movements.append([abs(anchors[i][j]-anchors[i-1][j]) for j in (0,1)])
                        flips+=len(a.text.splitlines())!=len(b.text.splitlines())
                rows=[]
                for i,c in enumerate(p.captions):
                    duration=c.end-c.start
                    rows.append({"id":c.id,"text":c.text,"start":c.start,"end":c.end,"duration":duration,
                                 "cps":len(c.text.replace("\n"," "))/duration,"lines":len(c.text.splitlines()),"anchor":anchors[i]})
                metrics={"source":name,"aspect":aspect,"preset":preset,"ffmpeg":args.version,
                    "events":len(rows),"movement_max_px":[max((d[j] for d in movements),default=0) for j in (0,1)],
                    "line_flips":flips,"max_lines":max(r["lines"] for r in rows),
                    "min_on_screen_s":min(r["duration"] for r in rows),"over_20_cps":sum(r["cps"]>20.01 for r in rows),
                    "under_083_s":sum(r["duration"]<5/6-1e-6 for r in rows),"orphans":sum(len(c.words)==1 for c in p.captions),
                    "unsafe_layouts":unsafe,"warnings":p.warnings,"transcript_notes":transcript["notes"],"per_event":rows}
                metadata.write_text(json.dumps(metrics,indent=2),encoding="utf-8")
                selected=sorted({0,len(rows)//3,len(rows)*2//3,len(rows)-1})
                tile_h=round(h*400/w)
                sheet=Image.new("RGB",(400,(tile_h+28)*len(selected)),"#161616")
                draw=ImageDraw.Draw(sheet)
                for index,event in enumerate(selected):
                    c=p.captions[event]
                    time=min(c.end-.04,c.start+max(.18,(c.end-c.start)*.5))
                    frame=folder/f"frame-{index}.png"
                    subprocess.run(["ffmpeg","-v","error","-y","-ss",str(time),"-i",str(output),"-frames:v","1",str(frame)],check=True,capture_output=True)
                    image=Image.open(frame).convert("RGB").resize((400,tile_h),Image.Resampling.LANCZOS)
                    sheet.paste(image,(0,index*(tile_h+28)+28))
                    draw.text((8,index*(tile_h+28)+6),f"{preset} | {time:.2f}s | {c.end-c.start:.2f}s hold",fill="white")
                sheet.save(folder/"phone-contact.png")
                results.append(metrics)
                print(name,aspect,preset,metrics["events"],metrics["movement_max_px"],"unsafe",len(unsafe),flush=True)
    (root/f"metrics-{args.version}-{'before' if args.baseline_src else 'after'}.json").write_text(json.dumps(results,indent=2),encoding="utf-8")


if __name__=="__main__":
    main()
