"""Caption timing and safe-band checks use generated fixtures and local JavaScript."""
import json

import pytest

from myzing.story.contract import CAPTION_BAND, check
from test_story_contract import story
from test_story_render import node_page_script


def test_caption_band_matches_page(tmp_path):
    result = node_page_script("console.log(JSON.stringify(window.captionBand));", tmp_path)
    assert result == CAPTION_BAND == {"x": 0, "y": 1560, "width": 1080, "height": 160}


def test_words_are_evenly_spread_and_only_show_during_speech(tmp_path):
    lines = [{"text": "One two three four five six.", "start": 1, "end": 7}]
    result = node_page_script(
        f"const lines={json.dumps(lines)}; console.log(JSON.stringify([0,1,2,4.999,5,6.9,7]"
        ".map(t=>window.captionAt(lines,t))));", tmp_path)
    assert result[0] is None and result[-1] is None
    assert result[1] == {"words": ["One", "two", "three", "four"], "current": 0}
    assert result[2]["current"] == 1 and result[3]["current"] == 3
    assert result[4] == {"words": ["five", "six."], "current": 0}
    assert result[5]["current"] == 1


def test_captions_false_removes_strip_on_rebuild(tmp_path):
    result = node_page_script("""
const stage={children:[],appendChild(el){this.children.push(el);}};
global.document={getElementById(){return stage;},createElement(){return {
  style:{},remove(){stage.children=stage.children.filter(c=>c!==this);}
};}};
window.buildCaptions({}, {beats:[{lines:[]}]});
const first=stage.children.map(c=>({id:c.id,style:c.style}));
window.buildCaptions({captions:false}, {beats:[]});
const disabled=stage.children.length;
window.buildCaptions({}, {beats:[]});
window.buildCaptions({}, {beats:[]});
console.log(JSON.stringify({first,disabled,rebuilt:stage.children.length}));
""", tmp_path)
    assert result["first"][0]["id"] == "captions"
    assert result["first"][0]["style"]["top"] == "1560px"
    assert result["disabled"] == 0 and result["rebuilt"] == 1


@pytest.mark.parametrize("kind,text", [("note", "A fact"), ("sticker", "A fact"), ("stamp", "A fact")])
def test_card_box_in_band_is_a_check_error(kind, text):
    value = story()
    value["panels"][0]["cards"] = [{"kind": kind, "text": text, "x": 80, "y": 1570, "at": "hook"}]
    assert any("panels[0].cards[0]: card box overlaps the caption band" in e for e in check(value))
    value["captions"] = False
    assert check(value) == []


def test_card_with_top_above_band_but_bottom_inside_is_rejected():
    value = story()
    value["panels"][0]["cards"][0].update(y=1500)
    assert any("card box overlaps" in e for e in check(value))


def test_small_low_puppet_head_is_refused():
    value = story()
    value["panels"][0]["actors"][0].update(y=1800, scale=.3)
    assert any("puppet head overlaps" in e for e in check(value))


@pytest.mark.parametrize("flag", ["captions", "sfx"])
def test_feature_flags_must_be_booleans(flag):
    value = story()
    value[flag] = "false"
    assert any(e.startswith(flag + ": must be a boolean") for e in check(value))


@pytest.mark.parametrize("field,value", [("kind", {}), ("kind", []), ("size", 1e308),
                                         ("w", -1e308), ("rot", 1e308)])
def test_bad_card_fields_report_problems_without_crashing(field, value):
    script = story()
    script["panels"][0]["cards"][0][field] = value
    assert check(script)


@pytest.mark.parametrize("kind,y", [("note", 1355), ("doc", 1230)])
def test_wrapped_card_heading_is_included_in_caption_clearance(kind, y):
    script = story()
    script["panels"][0]["cards"][0].update(kind=kind, y=y, text="Hi", k=" ".join(["A"] * 20))
    assert any("card box overlaps" in error for error in check(script))
