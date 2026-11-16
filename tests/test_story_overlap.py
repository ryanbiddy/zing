"""Timed layout checks use invented actors and measured local page geometry."""
from __future__ import annotations

import json

import pytest

from myzing.factory import tools
from myzing.story import data_path
from myzing.story.contract import check
from myzing.story.layout import HEAD_GEOMETRY, card_box, head_box, panel_overlaps
from test_factory_brand_kit import browser_tools
from test_story_contract import story, timings
from test_story_render import node_page_script, story_folder


def layout(actor=None, card=None):
    value = story()
    value["panels"][0]["actors"] = [{"who": "ada", "x": 540, **(actor or {})}]
    value["panels"][0]["cards"] = [{"kind": "tag", "text": "Ada", "x": 460,
                                    "y": 810, "at": "hook", **(card or {})}]
    return value


def test_card_on_standing_head_has_a_usable_y():
    value = layout()
    errors = check(value)
    problem = next(error for error in errors if "covers ada's head" in error)
    assert problem.startswith("panels[0].cards[0]:")
    assert "at x=" in problem and "about y=" in problem
    clear_y = int(problem.split("above y=", 1)[1].split(" ", 1)[0])
    assert 0 < clear_y < 810
    value["panels"][0]["cards"][0]["y"] = clear_y
    assert check(value) == []


@pytest.mark.parametrize("photo", [False, True])
def test_card_forty_pixels_above_standing_head_passes(photo):
    value = layout()
    if photo:
        value["cast"]["ada"]["photos"] = [{"path": "fixture.png", "credit": "Fixture artist",
                                              "license": "CC0", "source_url": "https://example.org/fixture"}]
    actor, card = value["panels"][0]["actors"][0], value["panels"][0]["cards"][0]
    _, top, _, _ = head_box(actor, photo=photo)
    _, card_top, _, height = card_box(card)
    card["y"] = top - 40 - (card_top + height - card["y"])
    assert check(value) == []


@pytest.mark.parametrize("anim", ["pop", "stamp"])
def test_over_head_is_the_only_head_exemption(anim):
    value = layout(card={"anim": anim})
    assert any("covers ada's head" in problem for problem in check(value))
    value["panels"][0]["cards"][0]["over_head"] = True
    assert check(value) == []
    value["panels"][0]["cards"][0]["over_head"] = "true"
    assert any("over_head: must be a boolean" in problem for problem in check(value))


def test_entry_and_card_windows_do_not_overlap():
    value = layout(actor={"enter": "turn"}, card={"until": "turn"})
    assert check(value) == []
    value["panels"][0]["cards"][0]["until"] = "turn+1"
    assert any("covers ada's head" in problem for problem in check(value))


def test_windows_are_clipped_to_the_panel():
    value = layout(actor={"enter": "turn"})
    value["panels"].append({"from": "first-job"})
    assert check(value) == []


def test_moves_use_current_position_and_detect_a_crossing():
    move = {"at": "hook", "from": 540, "to": 100, "dur": 1}
    value = layout(actor={"moves": [move]}, card={"at": "first-job"})
    assert check(value) == []
    value["panels"][0]["cards"][0]["at"] = "hook"
    assert any("covers ada's head" in problem for problem in check(value))


def test_seated_actor_and_scaled_head():
    value = layout(actor={"pose": "table", "y": 1790}, card={"y": 1120})
    assert any("covers ada's head" in problem for problem in check(value))
    value = layout(actor={"head_scale": 1.4, "scale": .7, "flip": True}, card={"y": 1090})
    assert any("covers ada's head" in problem for problem in check(value))


def test_card_card_sixty_percent_and_disjoint_windows():
    value = layout()
    panel = value["panels"][0]
    panel["actors"] = []
    panel["cards"][0].update(x=100, y=300, text="A paper tag")
    panel["cards"].append({**panel["cards"][0], "x": 110})
    assert any("cards[1]: covers more than 60 percent of cards[0]" in problem for problem in check(value))
    panel["cards"][0]["until"] = "turn"
    panel["cards"][1]["at"] = "turn"
    assert check(value) == []
    panel["cards"][0].pop("until")
    panel["cards"][1]["x"] = 350
    assert check(value) == []


def test_actual_timing_file_resolves_numeric_and_line_cues(tmp_path):
    value = layout(actor={"enter": "turn:0:0.5"}, card={"at": 1, "until": 3})
    times = timings()
    (tmp_path / "timings.json").write_text(json.dumps(times), encoding="utf-8")
    assert check(value, tmp_path) == []
    value["panels"][0]["cards"][0]["until"] = 7
    assert any("covers ada's head" in problem for problem in check(value, tmp_path))
    assert any("covers ada's head" in problem for problem in check(value, timings=times))


def test_card_shorter_than_one_page_tick_is_never_visible():
    value = layout(card={"at": 1.01, "until": 1.02})
    assert check(value) == []


def test_both_existing_story_fixtures_pass(tmp_path):
    assert check(story()) == []
    story_folder(tmp_path)
    assert check(json.loads((tmp_path / "story.json").read_text(encoding="utf-8")), tmp_path) == []


def test_geometry_constants_match_the_page(tmp_path):
    assert node_page_script("console.log(JSON.stringify(window.headGeometry));", tmp_path) == HEAD_GEOMETRY


def test_page_measured_standing_and_seated_heads_fit_python(tmp_path, browser_tools):
    actors = [
        {"who": "ada", "x": 540, "pose": "idle"},
        {"who": "ada", "x": 540, "pose": "table", "y": 1790},
        {"who": "ada", "x": 540, "pose": "think", "scale": .8, "head_scale": 1.3, "flip": True},
        {"who": "ada", "x": 540, "enter": "walk", "moves": [{"at": 1, "dur": .6, "from": 540, "to": 700}]},
        {"who": "ada", "x": 540, "pose": "table", "y": 1790, "head_scale": .8, "flip": True},
        {"who": "ada", "x": 540, "pose": "idle"},
        {"who": "ada", "x": 540, "enter": 1, "poses": [{"at": 2, "pose": "shrug"}]},
        {"who": "ada", "x": 540, "head_at": [{"at": 2, "head": 1}, {"at": 1, "head": 0}]},
    ]
    cases = [{"actor": actor, "t": t, "photo": index != 4,
              "aspect": [1, 1.3] if index == 7 else 3 if index == 5 else 1.2}
             for index, actor in enumerate(actors) for t in (.25, 1.25, 2.5)]
    script = tmp_path / "head-bounds.cjs"
    script.write_text("""
const fs=require('fs'),{pathToFileURL}=require('url');
const {chromium}=require(require.resolve('playwright-core',{paths:[process.cwd()]}));
(async()=>{
  const cases=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
  const browser=await chromium.launch({executablePath:process.env.ZING_BROWSER_PATH,args:['--allow-file-access-from-files']});
  try {
    const page=await browser.newPage({viewport:{width:1080,height:1920},offline:true});
    await page.goto(pathToFileURL(process.argv[2]).href);
    const boxes=await page.evaluate(async cases=>{
      const layer=svgEl('svg',{width:1080,height:1920},document.getElementById('world'));
      return cases.map(c=>{
        const a=c.actor;
        const heads={},names=[];
        for (const [i,aspect] of (Array.isArray(c.aspect)?c.aspect:[c.aspect]).entries()) {
          const h=300*aspect,name='fixture-'+i;
          heads[name]={url:'data:image/svg+xml,'+encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="300" height="${h}"><rect width="300" height="${h}" fill="#345678"/></svg>`),w:300,h};
          names.push(name);
        }
        const moves=(a.enter==='walk'?[{t:-.45,dur:.95,from:a.x-430,to:a.x}]:[])
          .concat((a.moves||[]).map(m=>({...m,t:m.at})));
        const spec={...a,moves,enterT:typeof a.enter==='number'?a.enter:null,
          poses:(a.poses||[]).map(p=>({...p,t:p.at})),head_at:(a.head_at||[]).map(h=>({...h,t:h.at}))};
        const puppet=Puppet(spec,{ada:{name:'Ada Paper',heads:c.photo?names:[]}},layer,heads);
        puppet.update(c.t);
        const r=puppet.captionBox();
        return r?{x:r.x,y:r.y,width:r.width,height:r.height}:null;
      });
    },cases);
    console.log(JSON.stringify(boxes));
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
""", encoding="utf-8")
    cases_file = tmp_path / "head-cases.json"
    cases_file.write_text(json.dumps(cases), encoding="utf-8")
    node, sidecar = tools.node_sidecar()
    result = tools.run(node, script, data_path("cutout.html"), cases_file, cwd=sidecar,
                       env=tools.sidecar_env(tmp_path / "browser"), capture_output=True,
                       text=True, encoding="utf-8", timeout=30)
    for case, actual in zip(cases, json.loads(result.stdout)):
        estimate = head_box(case["actor"], case["t"], photo=case["photo"], head_aspect=case["aspect"])
        if actual is None:
            assert estimate is None
            continue
        left, top, width, height = estimate
        assert left <= actual["x"] <= left + 8, (case, actual, (left, top, width, height))
        assert top <= actual["y"] <= top + 8
        assert left + width - 8 <= actual["x"] + actual["width"] <= left + width
        assert top + height - 8 <= actual["y"] + actual["height"] <= top + height


def test_unknown_aspect_frame_contains_a_very_tall_prepared_head():
    actor = {"x": 540, "scale": .9, "head_scale": 1.2, "flip": True}
    for t in (.25, 1.25, 2.5):
        x, y, w, h = head_box(actor, t)
        left, top, width, height = head_box(actor, t, head_aspect=3)
        assert x <= left and y <= top and x + w >= left + width and y + h >= top + height


def test_prepared_head_dimensions_are_used_without_image_tools(tmp_path):
    import struct

    value = layout(card={"y": 700})
    value["cast"]["ada"]["photos"] = [{"path": "fixture.png", "credit": "Fixture artist",
                                          "license": "CC0", "source_url": "https://example.org/fixture"}]
    panel = value["panels"][0]
    assert panel_overlaps(panel, timings(), cast=value["cast"])
    (tmp_path / "heads").mkdir()
    (tmp_path / "heads" / "ada-0.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 8 + struct.pack(">II", 300, 300))
    assert panel_overlaps(panel, timings(), cast=value["cast"], directory=tmp_path) == []


def test_real_entry_and_subtitle_boxes_cover_heads(tmp_path, browser_tools):
    """Wide subtitles count toward the settled box; entry travel does not.

    A card that brushes a face on its way in is allowed. The page check below
    still proves the full animated box, which the caption band relies on.
    """
    cards = [{"kind": "tag", "text": "Stamp test", "x": 750, "y": 810,
              "anim": animation, "at": 1, "until": 2} for animation in ("stamp", "slide")]
    for card in cards:
        value = layout(card=card)
        assert check(value) == []
        value["panels"][0]["cards"][0]["anim"] = "pop"
        assert check(value) == []
    cards.extend([
        {"kind": "tag", "text": "Ada", "sub": "An inventor who builds tiny paper boats for show",
         "x": 80, "y": 810, "at": 1, "until": 2},
        {"kind": "sign", "text": "Ada", "sub": "An inventor who makes tiny paper boats",
         "x": 80, "y": 810, "at": 1, "until": 2},
    ])
    for card in cards[2:]:
        assert any("covers ada's head" in problem for problem in check(layout(card=card)))
    script = tmp_path / "card-entry.cjs"
    script.write_text("""
const fs=require('fs'),{pathToFileURL}=require('url');
const {chromium}=require(require.resolve('playwright-core',{paths:[process.cwd()]}));
(async()=>{
  const cards=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
  const browser=await chromium.launch({executablePath:process.env.ZING_BROWSER_PATH,args:['--allow-file-access-from-files']});
  try {
    const page=await browser.newPage({viewport:{width:1080,height:1920},offline:true});
    await page.goto(pathToFileURL(process.argv[2]).href);
    const result=await page.evaluate(async cards=>{
      const panel=document.createElement('div');panel.className='panel';document.getElementById('world').appendChild(panel);
      const layer=svgEl('svg',{class:'layer',viewBox:'0 0 1080 1920'},panel);
      const puppet=Puppet({who:'ada',x:540},{ada:{name:'Ada Paper'}},layer,{});
      const parts=cards.map((c,i)=>Card({...c,t:c.at},panel,i));
      await document.fonts.ready;
      parts.forEach(p=>p.fit());
      return parts.map((p,i)=>{
        const t=i<2?1+1/12:1.5;puppet.update(t);p.update(t);
        const head=puppet.captionBox();
        const card=p.captionBox();
        return {overlap:Math.max(0,Math.min(head.right,card.right)-Math.max(head.left,card.left))*Math.max(0,Math.min(head.bottom,card.bottom)-Math.max(head.top,card.top)),
          box:{x:card.x,y:card.y,width:card.width,height:card.height}};
      });
    },cards);
    console.log(JSON.stringify(result));
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
""", encoding="utf-8")
    cards_file = tmp_path / "entry-cards.json"
    cards_file.write_text(json.dumps(cards), encoding="utf-8")
    node, sidecar = tools.node_sidecar()
    result = tools.run(node, script, data_path("cutout.html"), cards_file, cwd=sidecar,
                       env=tools.sidecar_env(tmp_path / "browser"), capture_output=True,
                       text=True, encoding="utf-8", timeout=30)
    for card, actual in zip(cards, json.loads(result.stdout)):
        assert actual["overlap"] > 1000
        x, y, w, h = card_box(card)
        box = actual["box"]
        assert x <= box["x"] and y <= box["y"]
        assert x + w >= box["x"] + box["width"]
        assert y + h >= box["y"] + box["height"]
