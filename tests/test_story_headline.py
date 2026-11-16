"""Headline page behavior uses local JavaScript, bundled fonts and drawn images."""
from __future__ import annotations

import json

from PIL import Image, ImageDraw

from myzing.factory import tools
from myzing.story import data_path
from test_factory_brand_kit import browser_tools
from test_story_render import node_page_script


def test_headline_page_and_python_share_looks_and_colors(tmp_path):
    result = node_page_script("console.log(JSON.stringify(window.storyVocabulary));", tmp_path)
    vocabulary = json.loads(data_path("vocabulary.json").read_text(encoding="utf-8"))
    assert result["looks"] == vocabulary["looks"] == ["cutout", "headline", "scrapbook", "comic"]
    assert result["headline_colors"] == vocabulary["headline_colors"]


def test_headline_name_and_keyword_matching_uses_whole_words(tmp_path):
    result = node_page_script("""
console.log(JSON.stringify([
  headlineMatch('ADA has paper.','Ada'), headlineMatch('Adam has paper.','Ada'),
  headlineMatch('Mira’s paper.','Mira'), headlineMatch('MIRA VALE!','Mira Vale'),
  headlineMatch('ÉVA has paper.','Éva'), headlineMatch('elephants walk.','elephant',true),
  headlineMatch('elephant walks.','elephants',true), headlineMatch('elephantine paper.','elephant',true)
]));
""", tmp_path)
    assert result == [0, -1, 0, 0, 0, 0, 0, -1]


def test_headline_uses_text_and_orders_people_in_the_line(tmp_path):
    result = node_page_script("""
const story={cast:{ada:{name:'Ada Paper'},bea:{name:'Bea Fold'}},
  images:{paper_elephant:{},'tiny-art':{keywords:['moon']}}};
console.log(JSON.stringify(headlineMentions(story,[
  {text:'Nothing arrives.',say:'Ada holds an elephant.',start:0},
  {text:'Bea hands Ada paper elephants.',start:1},
  {text:'A moon appears.',start:2}
])));
""", tmp_path)
    assert [(row["id"], row["at"]) for row in result["badges"]] == [("bea", 1), ("ada", 1)]
    assert [(row["id"], row["at"]) for row in result["pictures"]] == [("paper_elephant", 1), ("tiny-art", 2)]


def test_headline_last_name_keeps_apostrophes_and_hyphens(tmp_path):
    result = node_page_script("""
const story={cast:{ada:{name:"Ada O'Neill"},bea:{name:'Bea Smith-Jones'}}};
console.log(JSON.stringify(headlineMentions(story,[
  {text:'Neill and Jones wait.',start:0},
  {text:'O’Neill and Smith-Jones arrive.',start:1}
]).badges));
""", tmp_path)
    assert [(row["id"], row["at"]) for row in result] == [("ada", 1), ("bea", 1)]


def test_headline_font_fit_keeps_all_word_slots(tmp_path):
    result = node_page_script("""
const measure=(word,size)=>word.length*size*.5;
const short=headlineFit('12 moons',880,measure);
const long=headlineFit('Every little paper moon moves across the room while all the people watch it rise above the small blue stage',880,measure);
const extreme=headlineFit('W'.repeat(300),880,measure);
console.log(JSON.stringify({short,long,extreme}));
""", tmp_path)
    assert result["short"]["size"] == 336
    assert 96 <= result["long"]["size"] < result["short"]["size"]
    assert result["long"]["height"] <= 880 and result["long"]["width"] <= 952
    assert len(result["long"]["words"]) == 20
    assert result["extreme"]["width"] <= 952


def test_headline_picture_stays_in_place_when_mentioned_again(tmp_path):
    result = node_page_script("""
HEADLINE={images:{paper:{w:400,h:400,cut:'photo'},moon:{w:400,h:400,cut:'sticker'}}};
const beat={index:0,colorName:'ink',colors:HEADLINE_COLORS.ink,areaHeight:880,lines:[],
  mentions:headlineMentions({images:{paper:{},moon:{}}},[
    {text:'Paper folds.',start:0},{text:'Moon behind paper.',start:1},
    {text:'Paper beside moon.',start:2},{text:'Paper folds.',start:3}
  ])};
console.log(JSON.stringify([1,2,3].map(t=>headlineFrame(beat,t).picture)));
""", tmp_path)
    assert [(picture["id"], picture["at"]) for picture in result] == [("paper", 0), ("moon", 2), ("paper", 3)]
    assert result[0]["scale"] == 1


def test_headline_real_page_builds_without_panels_and_keeps_media_clear(tmp_path, browser_tools):
    (tmp_path / "heads").mkdir()
    portrait = Image.new("RGB", (600, 600), "#1F8A8A")
    draw = ImageDraw.Draw(portrait)
    draw.ellipse((150, 100, 450, 450), fill="#FBF4E4")
    portrait.save(tmp_path / "heads/ada-0-portrait.jpg")
    Image.new("RGB", (400, 400), "#E8452C").save(tmp_path / "drawing.png")
    Image.new("RGBA", (10, 1000), "#FFD21F").save(tmp_path / "tall.png")
    story = {
        "look": "headline", "topic": "paper shapes", "captions": True, "handle": "@paper",
        "cast": {"ada": {"name": "Ada Cutwell", "portraits": ["ada-0-portrait.jpg"]}, "bea": {"name": "Bea Fold"}},
        "images": {"elephant-drawing": {"prepared": "drawing.png"}, "tall": {"prepared": "tall.png", "cut": "sticker"}},
        "headline_credits": ["narration is an AI voice", "source: Drawn example", "photo: Test artist · CC0"],
        "headline_outro_cast": "ada",
        "beats": [
            {"id": "intro", "chapter": "THE PAPER", "lines": [
                {"text": "A blank starts.", "say": "Ada arrives."},
                {"text": "Ada has 12 paper elephants."}, {"text": "Bea said go."}]},
            {"id": "short", "chapter": "THE TURN", "lines": [{"text": "One moon."}]},
            {"id": "long", "color": "teal", "chapter": "THE SKY", "lines": [{"text": "Every little paper moon moves across the room while all the people watch it rise above the small blue stage"}]},
            {"id": "cream", "lines": [{"text": "Tall paper rises."}]},
            {"id": "teal", "lines": [{"text": "Ada folds paper."}]},
            {"id": "blue", "lines": [{"text": "The paper rests."}]},
        ],
    }
    timings = {"duration": 12, "outro_start": 11, "beats": []}
    starts = [0, 4, 5, 7, 8, 9]
    for index, beat in enumerate(story["beats"]):
        start = starts[index]
        lines = [{"text": line["text"], "start": start + j, "end": start + j + .8}
                 for j, line in enumerate(beat["lines"])]
        timings["beats"].append({"id": beat["id"], "start": start, "end": lines[-1]["end"], "lines": lines})
    data_file = tmp_path / "data.json"
    data_file.write_text(json.dumps({"story": story, "timings": timings, "base": tmp_path.as_uri() + "/"}), encoding="utf-8")
    script = tmp_path / "headline-page.cjs"
    script.write_text("""
const fs=require('fs'),{pathToFileURL}=require('url');
const {chromium}=require(require.resolve('playwright-core',{paths:[process.cwd()]}));
(async()=>{
  const data=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
  const browser=await chromium.launch({executablePath:process.env.ZING_BROWSER_PATH,args:['--allow-file-access-from-files','--disable-background-networking']});
  try {
    const page=await browser.newPage({viewport:{width:1080,height:1920},offline:true});
    await page.goto(pathToFileURL(process.argv[2]).href);
    const result=await page.evaluate(async d=>{
      await window.build(d.story,d.timings,d.base);
      const read=t=>{window.seek(t);return window.headlineAt(t);};
      const before=read(.5),first=read(1),later=read(1.5),held=read(1.9),pair=read(2.5);
      const type=document.querySelector('.headline-type');
      const chapter=document.querySelector('.headline-chapter').textContent;
      const hiddenWords=read(1).words.filter(word=>!word.visible).length;
      const hiddenNodes=[...document.querySelectorAll('.headline-word')].filter(node=>node.style.visibility==='hidden').length;
      const lineElements=[...document.querySelectorAll('.headline-type')].map(el=>el.style.display);
      const next=read(4.5),short=read(4.5),long=read(5.5),tall=read(7.5),outro=read(11.5);
      const colors=[0,4.5,5.5,7.5,8.5,9.5,11.5].map(t=>read(t).colorName);
      read(4.1);const transition=[...document.querySelectorAll('.headline-block')].slice(0,2).map(el=>el.style.transform);
      const caption=!!document.getElementById('captions'),className=document.getElementById('stage').className;
      read(11.5);const creditWidth=document.querySelector('.credits').getBoundingClientRect().width;
      const portraitCount=document.querySelectorAll('.headline-face img').length;
      const blank=document.querySelectorAll('.headline-face small')[0].textContent;
      const progress=document.getElementById('headline-progress').style;
      const progressInfo={top:progress.top,height:progress.height};
      read(2.5);const firstBuild=document.querySelector('.headline-block').innerHTML;
      await window.build(d.story,d.timings,d.base);read(2.5);
      const rebuilt=firstBuild===document.querySelector('.headline-block').innerHTML;
      const progressCount=document.querySelectorAll('#headline-progress').length;
      const stepped=JSON.stringify(read(1.51))===JSON.stringify(read(1.55));
      const longNames=structuredClone(d.story);
      longNames.cast.ada.name='Ada '+'Cutwell'.repeat(8);longNames.cast.bea.name='Bea '+'Fold'.repeat(14);
      longNames.panels=[{from:'outro',cards:[{kind:'not-a-card'}]}];
      await window.build(longNames,d.timings,d.base);read(2.5);
      const tags=[...document.querySelector('.headline-block').querySelectorAll('.headline-name')].map(el=>{
        const box=el.getBoundingClientRect();return {left:box.left,right:box.right,bottom:box.bottom};
      });
      return {before,first,later,held,pair,next,short,long,tall,outro,colors,caption,className,chapter,hiddenWords,hiddenNodes,lineElements,
        creditWidth,portraitCount,blank,progressInfo,rebuilt,progressCount,transition,stepped,tags,
        worldTransform:document.getElementById('world').style.transform};
    },data);
    await page.screenshot({path:process.argv[4],type:'jpeg'});
    console.log(JSON.stringify(result));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
""", encoding="utf-8")
    node, sidecar = tools.node_sidecar()
    run = tools.run(node, script, data_path("cutout.html"), data_file, tmp_path / "headline.jpg",
                    cwd=sidecar, env=tools.sidecar_env(tmp_path / "browser"), capture_output=True,
                    text=True, encoding="utf-8", timeout=40)
    got = json.loads(run.stdout)
    assert not got["caption"] and got["className"] == "look-headline"
    assert got["worldTransform"] == "none" and got["rebuilt"] and got["progressCount"] == 1
    assert got["chapter"] == "01  THE PAPER"
    assert not got["before"]["badges"] and got["first"]["badges"][0]["id"] == "ada"
    assert got["first"]["visibleWords"] == ["ADA"]
    assert got["hiddenNodes"] >= got["hiddenWords"] == 4
    assert got["first"]["words"][1]["box"] == got["later"]["words"][1]["box"]
    assert got["first"]["words"][0]["scale"] == 1.2 and got["later"]["words"][0]["scale"] == 1
    assert got["later"]["words"][2]["text"] == "12" and got["later"]["words"][2]["color"] == "#FFD21F"
    assert got["held"]["visibleWords"] == ["ADA", "HAS", "12", "PAPER", "ELEPHANTS."]
    assert [badge["id"] for badge in got["pair"]["badges"]] == ["ada", "bea"]
    assert [badge["box"]["width"] for badge in got["pair"]["badges"]] == [220, 400]
    for state in (got["first"], got["pair"]):
        assert state["picture"]["id"] == "elephant-drawing"
        assert state["boxes"]["picture"]["top"] >= 1200
        assert all(state["boxes"]["picture"]["right"] + 23.99 <= box["left"] for box in state["boxes"]["badges"])
    assert got["next"]["badges"] == [] and got["next"]["picture"] is None
    assert 96 <= got["long"]["fontSize"] < got["short"]["fontSize"] == 336
    assert got["long"]["typeScale"] == 1
    assert got["long"]["boxes"]["type"]["bottom"] <= 1500
    assert got["long"]["boxes"]["type"]["right"] <= 1016
    assert got["tall"]["picture"]["width"] < 48 and got["tall"]["picture"]["box"]["top"] >= 1200
    assert got["colors"] == ["ink", "yellow", "teal", "cream", "teal", "blue", "ink"]
    assert got["outro"]["badges"][0]["id"] == "ada" and got["creditWidth"] == 900
    assert got["portraitCount"] == 3 and got["blank"] == "no photo"
    assert got["stepped"]
    assert got["transition"][0].startswith("translateY(-")
    assert got["transition"][1].startswith("translateY(") and not got["transition"][1].startswith("translateY(-")
    assert got["tags"][0]["right"] < got["tags"][1]["left"]
    assert all(tag["bottom"] < 1900 for tag in got["tags"])
