from __future__ import annotations

import socket
import urllib.request

import pytest

from myzing.factory import judge, pipeline, provenance, receipt, render, review
from test_factory_caption_faces import data, scene

LABEL = "Lee Sample on Test Show, April 2020"


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(urllib.request, "build_opener", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)


@pytest.fixture
def clip(tmp_path):
    project = tmp_path / "project"
    d = project / "clip01"
    pipeline._write(project / "source.json", {"name": "An engine test", "date": "2020-04-03", "tag": "Test Show, April 2020",
                                             "on_screen_context": LABEL, "rights": "public-domain"})
    pipeline._write(project / "factory.json", {"pack": "zing", "rights": "public-domain"})
    pipeline._write(project / "moments.json", {"moments": [{"hook": "An engine test", "start": 20, "end": 24}]})
    pipeline._write(d / "plan.json", {"hook": "An engine test", "shots": [{"from": 0, "layout": "solo"}], "visuals": {}})
    pipeline._write(d / "words.json", {"duration": 4, "words": [{"w": "Engine.", "os": 0, "oe": 4}]})
    pipeline._write(d / "cams.json", {"frames": 120, "size": [1920, 1080], "cams": []})
    return d


def test_context_reaches_render_receipt_and_review(clip):
    value = render.scene_data(clip, "9x16", "zing", parallax=False, front=False, sharpen=False)
    assert value["sourceTag"] == value["onScreenContext"] == LABEL
    added = receipt.added(clip)
    assert added["on_screen_context"] == LABEL and added["original_date"] == "2020-04-03"
    assert added["rights"] == "public-domain"
    assert added["source_context"] == {"from": 0, "to": added["duration"], "text": LABEL}  # the whole rendered clip
    assert added["share"] == 0  # a source label does not inflate the graphic coverage
    (clip / "clip.mp4").write_bytes(b"test")
    page = review.build(clip.parent).read_text(encoding="utf-8")
    assert LABEL in page and "2020-04-03" in page and "public domain" in page


def test_context_extends_an_existing_credit_without_repeating_show_and_date(clip):
    assert provenance.scene(clip.parent)["sourceTag"] == LABEL
    source = pipeline._read(clip.parent / "source.json")
    pipeline._write(clip.parent / "source.json", {**source, "tag": "Episode 12"})
    assert provenance.scene(clip.parent)["sourceTag"] == "Episode 12 · " + LABEL


@pytest.mark.parametrize("shape", ["9x16", "16x9"])
@pytest.mark.parametrize("theme", [{}, {"cap_y": .02, "tag_ink": "transparent", "tag_bg": "transparent"},
                                  {"cap_y": .02, "cap_style": "kinetic"},
                                  {"panel": {"size": .25}}, {"panel": {"size": .25, "brand": False}}])
def test_context_stays_for_every_frame_and_captions_avoid_it(shape, theme):
    value = data(shape=shape, theme=theme, onScreenContext=LABEL, sourceTag=LABEL)
    value["shots"] = [{"from": 0, "to": 1, "layout": "solo"},
                      {"from": 1, "to": 2, "layout": "graphic", "graphic": {"kind": "title", "text": "Engine"}},
                      {"from": 2, "to": 4, "layout": "split", "visual": "v1"}]
    value["words"] = [{"w": "Engine", "os": 0, "oe": 4}]
    states = scene(value, r'''
      const states = [];
      for (let frame=0; frame<120; frame++) {
        await window.seek(frame/30);
        const tag = $('srctag'), cap = $('cap');
        const stroke = TH0.cap_stroke_w ?? (CAP_DEFAULT ? 7 : 0);
        const pop = +cap.style.transform.match(/scale\(([^)]+)\)/)[1];
        const h = (cap.offsetHeight+stroke*2)*Math.max(1,CAP_SCALE)*pop;
        const center = parseFloat(cap.style.top) + (ASPECT === '9x16' || CAP.y != null ? 0 : cap.offsetHeight/2);
        states.push({text:tag.textContent, display:tag.style.display,
          bottom:parseFloat(tag.style.top)+tag.offsetHeight, top:center-h/2, caption:cap.style.opacity});
      }
      await window.seek(0);
      states.push({text:$('srctag').textContent, display:$('srctag').style.display});
      console.log(JSON.stringify(states));
    ''')
    assert len(states) == 121
    assert all(state["text"] == LABEL and state["display"] != "none" for state in states)
    assert all(state["top"] >= state["bottom"] for state in states[:-1] if state["caption"])


@pytest.mark.parametrize("shape", ["9x16", "16x9"])
def test_quote_moments_keep_the_context(shape):
    states = scene(data(shape=shape, onScreenContext=LABEL, sourceTag=LABEL,
                        quotes=[{"from": 0, "to": 2, "a": 0, "b": 2, "marks": []}]), '''
      const states = [];
      for (const t of [0,.5,1,1.9,2.1,3.9]) {
        await window.seek(t);
        const tag = $('srctag'), quote = $('quote');
        states.push({text:tag.textContent, display:tag.style.display, quote:quote.style.display,
          top:parseFloat(quote.style.top)-quote.offsetHeight/2, bottom:parseFloat(tag.style.top)+tag.offsetHeight});
      }
      console.log(JSON.stringify(states));
    ''')
    assert all(state["text"] == LABEL and state["display"] != "none" for state in states)
    assert all(state["top"] >= state["bottom"] for state in states if state["quote"] != "none")


def test_required_label_has_its_own_readable_style():
    css = render.data_path("scene.html").read_text(encoding="utf-8").split("#srctag.required{", 1)[1].split("}", 1)[0]
    assert "color:#fff" in css and "background:rgba(5,12,36,.88)" in css
    assert "26px/1.25" in css and "overflow-wrap:anywhere" in css and "z-index:21" in css


@pytest.mark.parametrize("tag,want", [("", LABEL), ("Test Show, April 2020", LABEL),
                                    ("Episode 12", "Episode 12 · " + LABEL)])
def test_scene_keeps_the_context_when_extending_a_source_tag(tag, want):
    state = scene(data(onScreenContext=LABEL, sourceTag=tag), '''
      await window.seek(0);
      console.log(JSON.stringify($('srctag').textContent));
    ''')
    assert state == want
