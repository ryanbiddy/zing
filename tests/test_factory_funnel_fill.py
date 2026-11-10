from __future__ import annotations

import json
import re

import pytest

from myzing.factory import judge, render
from test_factory_caption_faces import data, scene


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)


@pytest.fixture
def funnel():
    return {"kind": "funnel", "title": "APPLICANT SELECTION", "rows": [
        {"value": 18000, "label": "APPLICANTS", "at": 35},
        {"value": 120, "label": "FIRST ROUND", "at": 36.29},
        {"value": 45, "text": "40-50", "label": "SECOND ROUND", "at": 43.81},
    ]}


def frames(graphic, times, shape="9x16", theme=None):
    source = render.data_path("scene.html").read_text(encoding="utf-8")
    css = dict(re.findall(r"\.(row|bar|num|lab|g-title)\{([^}]+)\}", source))
    value = data(shape=shape, theme=theme, words=[], duration=46, frames=1380,
                 shots=[{"from": 34, "to": 46, "idx": 0, "layout": "graphic", "graphic": graphic}])
    return scene(value, r"""
      const css = CSS;
      const style = text => Object.fromEntries(text.split(';').filter(s => s.includes(':')).map(s => {
        const i = s.indexOf(':');
        return [s.slice(0,i).trim().replace(/-([a-z])/g, (_, c) => c.toUpperCase()), s.slice(i+1).trim()];
      }));
      const root = nodes.gfxIn = element('gfxIn');
      root.querySelectorAll = sel => root.children.filter(e => e.cls === sel.slice(1));
      Object.defineProperty(root, 'innerHTML', {set(html) {
        this.children = [];
        const stack = [this];
        for (const m of html.matchAll(/<div([^>]*)>|<\/div>|([^<]+)/g)) {
          if (m[1] != null) {
            const el = element(), cls = m[1].match(/class="([^"]+)"/)[1];
            el.cls = cls; Object.assign(el.style, style(css[cls] || ''),
              style(m[1].match(/style="([^"]*)"/)?.[1] || ''));
            stack.at(-1).children.push(el); stack.push(el);
          } else if (m[2]) stack.at(-1).textContent += m[2];
          else stack.pop();
        }
      }});
      const states = [];
      for (const t of TIMES) {
        await window.seek(t);
        const title = root.querySelectorAll('.g-title')[0], rows = root.querySelectorAll('.row');
        states.push({area:geometry('graphic').gfx,
          transform:root.style.transform.match(/-?[\d.]+/g).map(Number),
          title:{top:parseFloat(title.style.top), bottom:parseFloat(title.style.top)+48},
          rows:rows.map(row => {
            const [bar, num, lab] = row.children;
            const top = parseFloat(row.style.top) + Number(row.style.transform?.match(/translateY\(([^p]+)px\)/)?.[1] || 0);
            const opacity = Number(row.style.opacity ?? 1);
            const line = parseFloat(lab.style.lineHeight || lab.style.font.match(/\/([\d.]+)px/)[1]);
            return {top, bottom:top+parseFloat(lab.style.top)+line,
              height:parseFloat(bar.style.height), width:parseFloat(bar.style.width),
              opacity:opacity*Number(bar.style.opacity ?? 1), color:bar.style.background,
              text:num.textContent, numberOpacity:opacity*Number(num.style.opacity ?? 1),
              label:lab.textContent, labelOpacity:opacity*Number(lab.style.opacity ?? 1)};
          })});
      }
      console.log(JSON.stringify(states));
    """.replace("CSS", json.dumps(css)).replace("TIMES", json.dumps(times)))


@pytest.mark.parametrize("t", [34, 35, 35.5, 36.28, 40, 43.8])
def test_unspoken_rows_have_dim_full_width_bars_and_no_numbers(funnel, t):
    early, final = frames(funnel, [t, 45])
    assert len(early["rows"]) == 3
    for row, lit, cue in zip(early["rows"], final["rows"], funnel["rows"]):
        if t >= cue["at"]:
            continue
        assert 0 < row["opacity"] <= .4
        assert row["width"] == pytest.approx(lit["width"])
        assert row["width"] > 0 and row["color"] != "var(--yel)"
        assert row["color"] == lit["color"] or lit["color"] == "var(--yel)"
        assert row["text"] == ""
        assert row["label"] == cue["label"] and 0 < row["labelOpacity"] <= .4


@pytest.mark.parametrize("index", [0, 1, 2])
def test_rows_light_and_count_only_at_their_cue(funnel, index):
    at = funnel["rows"][index]["at"]
    before, start, during, final = [s["rows"][index] for s in frames(funnel, [at-.001, at, at+.1, at+.8])]
    assert before["text"] == ""
    assert start["text"] != "" and during["numberOpacity"] > 0
    assert before["opacity"] < during["opacity"] < final["opacity"] == 1
    assert during["width"] != final["width"]
    assert final["text"] == ["18,000", "120", "40-50"][index]
    if index < 2:
        assert 0 < int(during["text"].replace(",", "")) < funnel["rows"][index]["value"]
    else:
        assert final["color"] == "var(--yel)"


@pytest.mark.parametrize("shape", ["9x16", "1x1", "16x9"])
@pytest.mark.parametrize("n", [2, 3, 5])
def test_stack_is_centered_and_clears_the_title(funnel, shape, n):
    funnel["rows"] = [{"value": 1000/(i+1), "label": f"ROUND {i+1}", "at": 35+i}
                      for i in range(n)]
    early, final = frames(funnel, [35, 45], shape)
    for state in [early, final]:
        rows, area = state["rows"], state["area"]
        x, y, scale = state["transform"]
        center = y + (rows[0]["top"] + rows[-1]["bottom"])*scale/2
        assert center == pytest.approx(area["h"]/2, abs=8)
        assert state["title"]["bottom"] + 16 <= rows[0]["top"]
        assert y + state["title"]["top"]*scale >= 0
        assert y + rows[-1]["bottom"]*scale <= area["h"]
        assert all(a["bottom"] + 12 <= b["top"] for a, b in zip(rows, rows[1:]))
        if n <= 3:
            assert all(row["height"] > 80 for row in rows)
    assert [(r["top"], r["bottom"]) for r in early["rows"]] == [
        (r["top"], r["bottom"]) for r in final["rows"]]


def test_seeking_back_restores_placeholders_and_pack_colors(funnel):
    theme = {"funnel": ["#123456", "#654321"]}
    times = [34, 35, 35.1, 36.29, 37, 43.81, 45]
    forward = frames(funnel, times, theme=theme)
    assert forward == frames(funnel, times[::-1], theme=theme)[::-1]
    assert [r["color"] for r in forward[0]["rows"]] == ["#123456", "#654321", "#123456"]
    assert [r["color"] for r in forward[-1]["rows"]] == ["#123456", "#654321", "var(--yel)"]


@pytest.mark.parametrize("n", [2, 3, 4, 8])
def test_bar_weight_fits_the_row_count(funnel, n):
    funnel["rows"] = [{"value": 1000/(i+1), "label": f"ROUND {i+1}"} for i in range(n)]
    rows = frames(funnel, [45])[0]["rows"]
    assert all(a["bottom"] < b["top"] for a, b in zip(rows, rows[1:]))
    if n <= 3:
        assert all(100 <= row["height"] <= 140 for row in rows)


def test_rows_without_cues_keep_the_half_second_stagger(funnel):
    for row in funnel["rows"]:
        row.pop("at")
    states = frames(funnel, [34, 34.5, 35, 36])
    for i, state in enumerate(states[:3]):
        assert all(r["text"] for r in state["rows"][:i+1])
        assert all(r["text"] == "" for r in state["rows"][i+1:])
    assert [r["text"] for r in states[-1]["rows"]] == ["18,000", "120", "40-50"]
