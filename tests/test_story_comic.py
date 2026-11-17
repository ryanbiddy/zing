"""One printed page is viewed through a moving camera with fixed captions."""
from __future__ import annotations

import math

import pytest

from myzing.story.contract import check
from test_factory_brand_kit import browser_tools
from test_story_contract import story, timings
from test_story_scrapbook import page_story, run_story_page


@pytest.mark.parametrize("panel_count", [1, 2, 5])
def test_comic_overview_centres_page_with_even_margins(tmp_path, browser_tools, panel_count):
    data = page_story(tmp_path, "comic")
    if panel_count == 5:
        data["story"]["panels"].append({"from": "outro", "set": {}})
    else:
        data["story"]["panels"] = data["story"]["panels"][:panel_count]
    got = run_story_page(tmp_path, data, """
      await window.build(d.story,d.timings,d.base,d.vocabulary);
      const page=document.querySelector('.comic-page'),frames=[...document.querySelectorAll('.comic-frame')];
      const world=document.getElementById('world');
      const sample=(t,index)=>{window.seek(t);const m=new DOMMatrix(getComputedStyle(world).transform);
        return {page:rect(page),frame:rect(frames[index]),state:window.comicAt(t),
          matrix:{a:m.a,b:m.b,c:m.c,d:m.d,e:m.e,f:m.f}};};
      const opening=[0,.4,.5,.75,1,1.25,1.5].map(t=>sample(t,0));
      const rest=frames.map((frame,index)=>sample(index*3+1.5,index));
      return {opening,rest,repeated:sample(0,0)};
""")
    overview = got["opening"][0]["page"]
    assert overview["left"] >= 40 - .05 and overview["right"] <= 1040 + .05
    assert overview["top"] >= 40 - .05 and overview["bottom"] <= 1880 + .05
    assert (overview["left"] + overview["right"]) / 2 == pytest.approx(540, abs=2)
    assert (overview["top"] + overview["bottom"]) / 2 == pytest.approx(960, abs=2)
    assert got["opening"][0] == got["opening"][1] == got["repeated"]
    scales = [frame["state"]["scale"] for frame in got["opening"]]
    assert scales == sorted(scales) and scales[0] < scales[-1]
    assert scales[-1] == pytest.approx(.9)
    for index, frame in enumerate(got["rest"]):
        box, matrix = frame["frame"], frame["matrix"]
        assert (box["left"] + box["right"]) / 2 == pytest.approx(540, abs=.05)
        assert (box["top"] + box["bottom"]) / 2 == pytest.approx(960, abs=.05)
        assert math.hypot(matrix["a"], matrix["b"]) == pytest.approx(.9, abs=.00001)
        assert math.degrees(math.atan2(matrix["b"], matrix["a"])) == pytest.approx(
            1.2 if index % 2 else -1.2, abs=.0001)
    if panel_count == 1:
        for sample in got["opening"]:
            box = sample["frame"]
            assert (box["left"] + box["right"]) / 2 == pytest.approx(540, abs=.05)
            assert (box["top"] + box["bottom"]) / 2 == pytest.approx(960, abs=.05)


def test_comic_page_frames_camera_and_print_finish(tmp_path, browser_tools):
    data = page_story(tmp_path, "comic")
    data["story"]["panels"].append({"from": "outro", "set": {"wall": "#FFD21F", "floor": "#17161C"},
                                     "cards": [{"kind": "credits", "x": 90, "y": 500, "w": 900,
                                                "lines": ["source: Invented drawing"], "at": "outro"}]})
    got = run_story_page(tmp_path, data, """
      const baseline=structuredClone(d.story);baseline.look='cutout';
      await window.build(baseline,d.timings,d.base,d.vocabulary);window.seek(1.5);
      const fixedBefore={caption:rect(document.getElementById('captions')),bar:rect(document.getElementById('barL'))};
      await window.build(d.story,d.timings,d.base,d.vocabulary);
      const frames=[...document.querySelectorAll('.comic-frame')];
      const world=document.getElementById('world');
      const sample=(t,index)=>{window.seek(t);const m=new DOMMatrix(getComputedStyle(world).transform);
        return {time:t,box:rect(frames[index]),matrix:{a:m.a,b:m.b,c:m.c,d:m.d,e:m.e,f:m.f},state:window.comicAt(t)};};
      window.seek(0);const overview=rect(document.querySelector('.comic-page'));
      const held=sample(.4,0),opening=sample(.8,0);
      const future=frames[2].querySelector('.puppet').getAttribute('transform');
      const futureCard=frames[2].querySelector('.card').getAttribute('style');
      window.seek(1.5);
      const frozen=future===frames[2].querySelector('.puppet').getAttribute('transform')&&
        futureCard===frames[2].querySelector('.card').getAttribute('style');
      const fixedAfter={caption:rect(document.getElementById('captions')),bar:rect(document.getElementById('barL'))};
      const chapter=frames[0].querySelector('.comic-chapter');
      const chapterStyle=getComputedStyle(chapter),frameStyle=getComputedStyle(frames[0]);
      const chapterInfo={text:chapter.textContent,font:chapterStyle.fontFamily,background:chapterStyle.backgroundColor,
        border:chapterStyle.borderTopWidth,box:rect(chapter),pill:getComputedStyle(document.getElementById('chapter')).display};
      const rest=[1.5,4.5,7.5,10.5,13.5].map((t,i)=>sample(t,i));
      const end=sample(14.9,4),credits=rect(frames[4].querySelector('.credits'));
      const layout=frames.map(frame=>({left:frame.offsetLeft,top:frame.offsetTop,width:frame.offsetWidth,height:frame.offsetHeight}));
      const pageStyle=getComputedStyle(document.querySelector('.comic-page'));
      const dots=[...document.querySelectorAll('.comic-dots')].map(el=>{
        const s=getComputedStyle(el);return {background:s.backgroundImage,blend:s.mixBlendMode,opacity:+s.opacity};});
      window.seek(4.51);const step=world.style.transform;
      window.seek(4.55);const stepped=step===world.style.transform;
      return {count:frames.length,panels:document.querySelectorAll('.panel').length,
        puppets:document.querySelectorAll('.puppet').length,heads:[...document.querySelectorAll('.puppet-head image')].map(el=>el.getAttribute('href')),
        overview,held,opening,rest,end,layout,fixedBefore,fixedAfter,chapter:chapterInfo,
        frameBorder:frameStyle.borderTopWidth,frameColor:frameStyle.borderTopColor,
        paper:pageStyle.backgroundColor,dots,grain:+getComputedStyle(document.getElementById('grain')).opacity,
        frozen,stepped,credits};
""")
    assert got["count"] == got["panels"] == len(data["story"]["panels"])
    assert got["puppets"] == 8 and len(got["heads"]) == 4
    assert all(head.endswith("ada-0.png") for head in got["heads"])
    overview = got["overview"]
    assert -.1 <= overview["left"] < overview["right"] <= 1080.1
    assert -.1 <= overview["top"] < overview["bottom"] <= 1920.1
    assert got["held"]["state"]["overview"]
    assert not got["held"]["state"]["travel"]
    assert got["held"]["state"]["scale"] < got["opening"]["state"]["scale"] < .9
    for index, frame in enumerate(got["rest"]):
        box, matrix = frame["box"], frame["matrix"]
        assert (box["left"] + box["right"]) / 2 == pytest.approx(540, abs=.05)
        assert (box["top"] + box["bottom"]) / 2 == pytest.approx(960, abs=.05)
        assert math.hypot(matrix["a"], matrix["b"]) == pytest.approx(.9, abs=.00001)
        tilt = math.degrees(math.atan2(matrix["b"], matrix["a"]))
        assert abs(tilt) == pytest.approx(1.2, abs=.0001)
        if index:
            previous = got["rest"][index - 1]["matrix"]
            assert matrix["b"] * previous["b"] < 0
    assert got["end"]["matrix"] == got["rest"][-1]["matrix"]
    assert 0 <= got["credits"]["left"] < got["credits"]["right"] <= 1080
    assert 0 <= got["credits"]["top"] < got["credits"]["bottom"] <= 1920
    positions = got["layout"]
    assert positions[0]["top"] == positions[1]["top"] < positions[2]["top"] == positions[3]["top"]
    assert positions[1]["left"] > positions[0]["left"] and positions[3]["left"] > positions[2]["left"]
    assert positions[2]["left"] != positions[0]["left"]
    assert positions[1]["left"] > positions[0]["left"] + positions[0]["width"]
    assert got["fixedBefore"] == got["fixedAfter"]
    assert got["fixedAfter"]["caption"]["top"] == 1560
    assert got["fixedAfter"]["caption"]["width"] == 1080
    assert got["fixedAfter"]["caption"]["height"] == 160
    assert got["chapter"]["font"] == "Anton"
    assert got["chapter"]["background"] == "rgb(255, 210, 31)"
    assert float(got["chapter"]["border"].removesuffix("px")) > 0
    assert "A PAPER TOWN" in got["chapter"]["text"] and got["chapter"]["pill"] == "none"
    assert got["chapter"]["box"]["top"] < 450 and got["chapter"]["box"]["left"] < 300
    assert got["frameBorder"] == "10px" and got["frameColor"] == "rgb(23, 22, 28)"
    assert got["paper"] == "rgb(244, 238, 223)"
    assert len(got["dots"]) == got["count"]
    assert all("radial-gradient" in dots["background"] and dots["blend"] == "multiply"
               and 0 < dots["opacity"] < .3 for dots in got["dots"])
    assert got["grain"] > .2 and got["frozen"] and got["stepped"]


def test_comic_caption_guard_checks_screen_boxes_during_travel_and_rest(tmp_path, browser_tools):
    data = page_story(tmp_path, "comic")
    # All four panels carry speech, including the move between the first two rows.
    for beat in data["timings"]["beats"]:
        beat["lines"][0]["end"] = beat["start"] + 3
        beat["end"] = beat["start"] + 3
    got = run_story_page(tmp_path, data, """
      await window.build(d.story,d.timings,d.base,d.vocabulary);
      const errors=[];
      for(let tick=0;tick<12*12;tick++){
        try{window.seek(tick/12);}catch(error){errors.push({time:tick/12,error:error.message});}
      }
      const clipAt=t=>{window.seek(t);return [...document.querySelectorAll('.comic-viewport,#world,.comic-page,.comic-frame')]
        .map(el=>({className:el.className,clip:getComputedStyle(el).clipPath})).filter(row=>row.clip!=='none');};
      const traveling=clipAt(6),resting=clipAt(7.5),overview=clipAt(0);
      const broken=structuredClone(d.story);
      broken.panels[0].actors=[{who:'ada',x:540,y:1900,scale:.3}];
      let refused='';
      try{await window.build(broken,d.timings,d.base,d.vocabulary);window.seek(1.5);}
      catch(error){refused=error.message;}
      const lowered=structuredClone(d.story);
      lowered.panels[0].actors=[];
      lowered.panels[0].cards=[{kind:'tag',text:'Too low',x:100,y:1650,at:0}];
      let cardRefused='';
      try{await window.build(lowered,d.timings,d.base,d.vocabulary);window.seek(1.5);}
      catch(error){cardRefused=error.message;}
      return {errors,traveling,resting,overview,refused,cardRefused};
""")
    assert got["errors"] == []
    # Art is never cut away behind the captions, moving or settled.
    assert got["traveling"] == got["overview"] == got["resting"] == []
    assert "puppet head overlaps caption band" in got["refused"]
    assert "overlaps caption band" in got["cardRefused"]


def test_cutout_python_layout_checks_remain_in_panel_coordinates_for_comic():
    value = story()
    before = check(value, timings=timings())
    assert before == []
    value["look"] = "comic"
    assert check(value, timings=timings()) == before
    value["panels"][0]["cards"][0]["y"] = 1580
    comic_errors = check(value, timings=timings())
    value["look"] = "cutout"
    assert check(value, timings=timings()) == comic_errors
    assert any("card box overlaps the caption band" in error for error in comic_errors)
