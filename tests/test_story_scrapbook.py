"""Paper photos use the directed story, local drawings and measured page boxes."""
from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from myzing.factory import tools
from myzing.story import data_path, render
from myzing.story.contract import check
from test_factory_brand_kit import browser_tools
from test_story_contract import story, timings
from test_story_render import node_page_script, story_folder


def run_story_page(tmp_path: Path, data: dict, body: str) -> dict:
    data_file = tmp_path / "page-input.json"
    data_file.write_text(json.dumps(data), encoding="utf-8")
    script = tmp_path / "inspect-story.cjs"
    script.write_text("""
const fs=require('fs'),{pathToFileURL}=require('url');
const {chromium}=require(require.resolve('playwright-core',{paths:[process.cwd()]}));
(async()=>{
  const data=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
  const browser=await chromium.launch({executablePath:process.env.ZING_BROWSER_PATH,
    args:['--allow-file-access-from-files','--disable-background-networking']});
  try {
    const page=await browser.newPage({viewport:{width:1080,height:1920},offline:true,serviceWorkers:'block'});
    const external=[];
    await page.route('**/*',route=>{
      const url=route.request().url();
      if(url.startsWith('file:')||url.startsWith('data:'))return route.continue();
      external.push(url);return route.abort();
    });
    await page.goto(pathToFileURL(process.argv[2]).href);
    const result=await page.evaluate(async d=>{
      const rect=el=>{const b=el.getBoundingClientRect();return {x:b.x,y:b.y,width:b.width,height:b.height,
        left:b.left,top:b.top,right:b.right,bottom:b.bottom};};
""" + body + """
    },data);
    console.log(JSON.stringify({result,external}));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
""", encoding="utf-8")
    node, sidecar = tools.node_sidecar()
    process = tools.run(node, script, data_path("cutout.html"), data_file,
                        cwd=sidecar, env=tools.sidecar_env(tmp_path / "browser"),
                        capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    assert result["external"] == []
    return result["result"]


def drawn_cast(tmp_path: Path) -> dict:
    heads = tmp_path / "heads"
    heads.mkdir(exist_ok=True)
    portrait = Image.new("RGB", (300, 300), "#1F8A8A")
    drawing = ImageDraw.Draw(portrait)
    drawing.ellipse((70, 30, 230, 245), fill="#FBF4E4")
    drawing.ellipse((105, 100, 120, 115), fill="#17161C")
    drawing.ellipse((180, 100, 195, 115), fill="#17161C")
    drawing.arc((115, 130, 185, 200), 0, 180, fill="#17161C", width=6)
    portrait.save(heads / "ada-0-portrait.jpg")
    head = Image.new("RGBA", (300, 380))
    ImageDraw.Draw(head).ellipse((15, 10, 285, 370), fill="#FBF4E4", outline="#17161C", width=6)
    head.save(heads / "ada-0.png")
    return {"ada": {"name": "Ada Paper", "portraits": ["ada-0-portrait.jpg"], "heads": ["ada-0.png"]},
            "bea": {"name": "Bea Fold"}}


def page_story(tmp_path: Path, look: str) -> dict:
    value = story()
    value.update(look=look, cast=drawn_cast(tmp_path), handle="@paper")
    value["panels"] = [{"from": beat["id"],
                        "set": {"wall": "#FFD21F", "floor": "#1F8A8A", "pattern": "stripes"},
                        "actors": [{"who": "ada", "x": 300}, {"who": "bea", "x": 780}],
                        "props": [{"prop": "star", "x": 880, "y": 400, "still": True}],
                        "cards": [{"kind": "tag", "text": f"PAGE {i + 1}", "x": 80, "y": 230,
                                   "at": beat["id"]}]}
                       for i, beat in enumerate(value["beats"])]
    clock = {"duration": 15, "outro_start": 12, "provider": "lines", "beats": []}
    for i, beat in enumerate(value["beats"]):
        clock["beats"].append({"id": beat["id"], "start": i * 3, "end": i * 3 + 2.75,
                               "lines": [{"text": beat["lines"][0]["text"],
                                          "start": i * 3, "end": i * 3 + 2.5}]})
    return {"story": value, "timings": clock, "base": tmp_path.as_uri() + "/",
            "vocabulary": json.loads(data_path("vocabulary.json").read_text(encoding="utf-8"))}


def test_scrapbook_picture_geometry_matches_page_vocabulary(tmp_path):
    from myzing.story.layout import PICTURE_GEOMETRY

    actual = node_page_script("console.log(JSON.stringify(window.pictureGeometry));", tmp_path)
    vocabulary = json.loads(data_path("vocabulary.json").read_text(encoding="utf-8"))
    assert actual == vocabulary["picture_geometry"] == PICTURE_GEOMETRY
    assert actual["width"] == 250 and actual["height"] == 310 and actual["fps"] == 12


def test_scrapbook_page_uses_portraits_and_vertical_camera(tmp_path, browser_tools):
    data = page_story(tmp_path, "scrapbook")
    # A broken head asset must not matter to a portrait-only look.
    data["story"]["cast"]["ada"]["heads"] = ["missing-cut-head.png"]
    got = run_story_page(tmp_path, data, """
      await window.build(d.story,d.timings,d.base,d.vocabulary);window.seek(1.5);
      const errors=[];
      for(let tick=0;tick<12*12;tick++){
        try{window.seek(tick/12);}catch(error){errors.push({time:tick/12,error:error.message});}
      }
      window.seek(3);const traveling=getComputedStyle(document.querySelector('.scrapbook-viewport')).clipPath;
      window.seek(1.5);const resting=getComputedStyle(document.querySelector('.scrapbook-viewport')).clipPath;
      const pictures=[...document.querySelectorAll('.picture-card')];
      const first=document.querySelector('.picture-card');
      const paper=first.querySelector('.picture-paper'),photo=first.querySelector('image');
      const firstPanel=document.querySelector('.panel');
      const before=firstPanel.innerHTML;
      const states=[1.5,3,4.5].map(t=>{window.seek(t);const m=new DOMMatrix(getComputedStyle(document.getElementById('world')).transform);
        return {x:m.e,y:m.f};});
      window.seek(1.51);const one=first.getAttribute('transform');
      window.seek(1.55);const two=first.getAttribute('transform');
      window.seek(1.5);const initial=first.getAttribute('transform');
      const names=pictures.map(p=>p.querySelector('.picture-name').textContent);
      const placeholders=[...document.querySelectorAll('.picture-initials')].map(p=>p.textContent);
      const labelStyle=getComputedStyle(first.querySelector('.picture-name'));
      const label={font:labelStyle.fontFamily,style:labelStyle.fontStyle,size:labelStyle.fontSize};
      const photoSize={width:+photo.getAttribute('width'),height:+photo.getAttribute('height'),
        insetX:+photo.getAttribute('x')- +paper.getAttribute('x'),insetY:+photo.getAttribute('y')- +paper.getAttribute('y')};
      const torn=firstPanel.querySelector('.scrapbook-floor');
      const tear=torn?torn.getAttribute('d'):null;
      const puppets=document.querySelectorAll('.puppet,.puppet-head').length;
      await window.build(d.story,d.timings,d.base,d.vocabulary);window.seek(1.5);
      return {count:pictures.length,names,placeholders,puppets,
        paper:{width:+paper.getAttribute('width'),height:+paper.getAttribute('height')},photoSize,
        href:photo.getAttribute('href'),label,
        states,stepped:one===two,stable:initial===document.querySelector('.picture-card').getAttribute('transform'),
        rebuilt:before===document.querySelector('.panel').innerHTML,tear,errors,traveling,resting,
        noPhoto:document.querySelectorAll('.picture-card')[1].textContent.includes('no photo')};
""")
    assert got["puppets"] == 0
    assert got["count"] == sum(len(panel["actors"]) for panel in data["story"]["panels"])
    assert got["paper"] == {"width": 250, "height": 310}
    assert got["photoSize"] == {"width": 222, "height": 222, "insetX": 14, "insetY": 14}
    assert got["href"].endswith("ada-0-portrait.jpg")
    assert got["names"] == ["Ada Paper", "Bea Fold"] * 4
    assert got["placeholders"] == ["BF"] * 4 and got["noPhoto"]
    # Quoting distinguishes the bundled face from the generic serif fallback.
    assert got["label"] == {"font": '"Serif"', "style": "italic", "size": "30px"}
    assert [state["x"] for state in got["states"]] == [0, 0, 0]
    assert got["states"][0]["y"] == 0
    assert -1920 < got["states"][1]["y"] < 0
    assert got["states"][2]["y"] == -1920
    assert got["stepped"] and got["stable"] and got["rebuilt"]
    assert got["tear"] and len(set(got["tear"].split())) > 12
    assert got["errors"] == []
    assert got["traveling"] == got["resting"] == "none"  # art is never cut away behind captions


def test_scrapbook_measured_picture_boxes_match_python(tmp_path, browser_tools):
    from myzing.story.layout import picture_box

    data = page_story(tmp_path, "scrapbook")
    data["story"]["captions"] = False
    data["story"]["panels"] = [{"from": "hook", "set": {}}]
    actors = [{"who": "ada", "x": 540},
              {"who": "bea", "x": 540, "pose": "table", "y": 1790},
              {"who": "ada", "x": 540, "scale": .7, "head_scale": 2.5, "flip": True},
              {"who": "ada", "x": 540, "scale": 1.3, "pose": "think"},
              {"who": "ada", "x": 540, "enter": "walk",
               "moves": [{"at": "hook+1", "dur": .6, "from": 540, "to": 700}]},
              {"who": "ada", "x": 540, "enter": "hook+1",
               "poses": [{"at": "hook+2", "pose": "shrug"}]}]
    actors += [{"who": "ada", "x": 540, "poses": [{"at": 1, "pose": pose}]}
               for pose in ("point", "present", "think", "shrug", "up", "cheer", "wave")]
    data["cases"] = [{"actor": actor, "time": t} for actor in actors for t in (.25, 1, 1.25, 2.5)]
    got = run_story_page(tmp_path, data, """
      const boxes=[];
      for(const item of d.cases){
        const story=structuredClone(d.story);story.panels[0].actors=[item.actor];
        await window.build(story,d.timings,d.base,d.vocabulary);window.seek(item.time);
        const root=document.querySelector('.picture-card');
        const m=root.transform.baseVal.consolidate()?.matrix;
        boxes.push({box:getComputedStyle(root).visibility==='hidden'?null:rect(root.querySelector('.picture-paper')),
          matrix:m?{a:m.a,b:m.b,e:m.e,f:m.f}:null});
      }
      return boxes;
""")
    for case, frame in zip(data["cases"], got):
        actual = frame["box"]
        expected = picture_box(case["actor"], case["time"], timings=data["timings"], panel_start=0)
        if actual is None:
            assert expected is None, case
            continue
        assert expected is not None, case
        left, top, width, height = expected
        for want, measured in ((left, actual["left"]), (top, actual["top"]),
                               (left + width, actual["right"]), (top + height, actual["bottom"])):
            assert measured == pytest.approx(want, abs=4), (case, actual, expected)
    # Mirroring puppet limbs must not mirror or tilt a person's photograph.
    base = actors[0]
    assert picture_box(base, 1.25) == picture_box({**base, "flip": True}, 1.25)
    samples = (.25, 1, 1.25, 2.5)

    def matrix(actor_index, time):
        return got[actor_index * len(samples) + samples.index(time)]["matrix"]

    def angle(m):
        return math.degrees(math.atan2(m["b"], m["a"]))

    resting = matrix(0, 2.5)
    assert -4.45 <= angle(resting) <= 4.45 and resting["f"] == 1030
    # Point and present lean one way; think leans the other way.
    for index, lean in ((6, 5), (7, 5), (8, -5)):
        assert angle(matrix(index, 2.5)) - angle(resting) == pytest.approx(lean, abs=.0001)
    # A shrug returns to the resting tilt after one rock.
    assert angle(matrix(9, 1.25)) - angle(matrix(0, 1.25)) == pytest.approx(2.5, abs=.0001)
    assert angle(matrix(9, 2.5)) == pytest.approx(angle(resting), abs=.0001)
    for index in (10, 11, 12):
        assert matrix(index, 1)["f"] == 1006
        assert matrix(index, 2.5)["f"] == 1030
    assert matrix(4, .25)["e"] < 540 and matrix(4, 2.5)["e"] == 700
    assert got[5 * len(samples)]["box"] is None
    assert matrix(5, 1)["f"] == 910 and matrix(5, 2.5)["f"] == 1030


def test_cutout_fixture_check_also_passes_as_scrapbook(tmp_path):
    from myzing.story import command

    value = story()
    assert check(value, timings=timings()) == []
    path = tmp_path / "story.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    (tmp_path / "timings.json").write_text(json.dumps(timings()), encoding="utf-8")
    before = path.read_bytes()
    assert command.check(tmp_path, look="scrapbook") == []
    assert path.read_bytes() == before


@pytest.mark.parametrize("look", ["scrapbook", "comic"])
def test_new_look_real_short_render(tmp_path, browser_tools, look):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg not installed")
    directory = story_folder(tmp_path)
    before = (directory / "story.json").read_bytes()
    output = render.render(directory, look=look)
    assert (directory / "story.json").read_bytes() == before
    probe = json.loads(tools.run(tools.ffprobe(), "-v", "error", "-show_streams", "-show_format",
                                 "-of", "json", output, capture_output=True, text=True).stdout)
    video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
    assert (video["width"], video["height"], video["r_frame_rate"]) == (1080, 1920, "30/1")
    assert any(stream["codec_type"] == "audio" for stream in probe["streams"])
    assert float(probe["format"]["duration"]) == pytest.approx(1.5, abs=1 / 30)
    assert 0 < output.stat().st_size and float(probe["format"]["duration"]) < 3
