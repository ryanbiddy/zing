"""Pack edits, learned assets and logo timing without a judge or downloads."""
from __future__ import annotations

import json
import os
import shutil

import pytest

from myzing.factory import judge, learn, pipeline, render, source
from test_factory_brand_kit import FONT, clip, kit, node, pack, scene
from test_factory_learn import REF


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(source, "transcribe_moments", lambda media, pieces: [])


@pytest.fixture
def project(tmp_path, monkeypatch):
    kit()
    root = tmp_path / "proj"
    root.mkdir()
    d = clip(root)
    pipeline._write(root / "factory.json", {**pipeline.SETTINGS, "moments": 0, "pack": "acme"})
    pipeline._write(root / "source.json", {"media": str(root / "ep.mp4"), "name": "Show"})
    pipeline._write(root / "moments.json", {"scouted": True, "moments": [
        {"start": 0, "end": .4, "hook": "Hello", "snapped": True}]})
    pipeline._write(d / "words.json", {"duration": .4, "words": [{"w": "Hello", "os": 0, "oe": .4}]})
    pipeline._write(d / "post.json", {"x": "Hello"})
    judge.Judge(root).save("clip01-plan", pipeline._read(d / "plan.json"))
    calls = []

    def rendered(d, shape, name):
        calls.append(shape)
        tag = render.suffix(shape, name)
        pipeline._write(d / f"data{tag}.json", scene(d, name, shape))
        out = d / f"clip{tag}.mp4"
        out.write_bytes(b"rendered")
        stamp = (d / "plan.json").stat().st_mtime + 1
        os.utime(out, (stamp, stamp))
        return out
    monkeypatch.setattr(render, "render", rendered)
    return root, d, calls


def run(root):
    return pipeline.run(root, judge.Judge(root), say=lambda m: None)


@pytest.mark.parametrize("fields", [{"accent": "#123456"}, {"logo": "mark #2.png"},
                                    {"fonts": [{**FONT, "weight": 800}]},
                                    {"logo_pos": "bottom-right"}, {"logo_h": 96}])
def test_pack_edits_render_each_shape_again(project, fields):
    root, d, calls = project
    folder = render.user_packs() / "acme"
    shutil.copyfile(folder / "mark #1.png", folder / "mark #2.png")
    run(root)
    assert calls == ["9x16", "1x1"]
    calls.clear()
    run(root)
    assert calls == []
    stamp = (d / "plan.json").stat().st_mtime_ns
    pack(**{**render.theme("acme"), **fields})
    run(root)
    assert calls == ["9x16", "1x1"]
    assert (d / "plan.json").stat().st_mtime_ns == stamp
    calls.clear()
    run(root)
    assert calls == []


@pytest.mark.parametrize("field", ["theme", "fonts", "logo"])
def test_only_the_shape_with_stale_brand_data_renders(project, field):
    root, d, calls = project
    run(root)
    calls.clear()
    path = d / "data-1x1-acme.json"
    saved = pipeline._read(path)
    if field == "theme":
        saved[field]["accent"] = "#000000"
    elif field == "fonts":
        saved[field][0]["src"] = "file:///old/font.ttf"
    else:
        saved[field]["src"] = "file:///old/logo.png"
    pipeline._write(path, saved)
    run(root)
    assert calls == ["1x1"]
    calls.clear()
    run(root)
    assert calls == []


def test_unrelated_saved_data_does_not_render_again(project):
    root, d, calls = project
    run(root)
    calls.clear()
    for path in d.glob("data*.json"):
        pipeline._write(path, {**pipeline._read(path), "captureFrames": [0], "overlay": True, "duration": 99})
    run(root)
    assert calls == []


@pytest.mark.parametrize("fields", [{}, {"logo": "mark.png"}, {"fonts": [FONT]},
                                    {"fonts": [FONT], "logo": "mark.png", "logo_pos": "bottom-right", "logo_h": 96}])
def test_learned_pack_drops_base_assets(tmp_path, monkeypatch, fields):
    folder = pack(**fields)
    (folder / "mark.png").write_bytes(b"logo")
    shutil.copyfile(render.data_path("../fonts/ZingCaption-700.ttf"), folder / FONT["file"])
    reference = tmp_path / "reference.mp4"
    reference.touch()
    sample = clip(tmp_path)
    log, trials = [], []

    def rendered(d, shape, pack, **kwargs):
        trials.append(scene(d, pack, shape))
    monkeypatch.setattr(render, "render", rendered)
    monkeypatch.setattr(learn, "measure", lambda *a: REF)
    monkeypatch.setattr(learn, "side_by_side", lambda *a: None)
    result = learn.learn(reference, "learned", sample, base="acme", say=log.append)
    learned = render.theme(result["pack"])
    assert len(trials) == 1
    assert not {"fonts", "logo", "logo_pos", "logo_h"} & learned.keys()
    assert "fonts" not in trials[0] and "logo" not in trials[0]
    assert render.check_pack("learned") == []
    assert render.theme("acme") == {"name": "Acme", **fields}
    assert log.count("learned pack does not carry the base pack's fonts and logo") == bool(fields)


SEEK = r"""
const fs = require('fs'), vm = require('vm');
const data = JSON.parse(fs.readFileSync(0, 'utf8')), nodes = {}, bounds = data.bounds || {};
let decodes = 0;
const get = id => nodes[id] ||= {style:{}, dataset:{}, firstChild:{style:{}},
  naturalWidth:120, naturalHeight:60, offsetHeight:80, classList:{toggle() {}},
  getBoundingClientRect:() => bounds[id] || {left:0, top:0, right:0, bottom:0, width:0, height:0},
  querySelector:sel => get(id+sel), querySelectorAll:() => [],
  decode:async () => { if (id === 'gfxIn.g-logo') { decodes++; if (data.rejectDecode) throw Error('decode'); } }};
const document = {documentElement:{style:{setProperty() {}}, dataset:{}}, body:{style:{}},
  fonts:{add() {}, load:async () => {}}, getElementById:get,
  createRange:() => { let el; return {selectNodeContents:e => { el = e; }, getBoundingClientRect:() => el.getBoundingClientRect()}; }};
const context = {window:{DATA:data}, document, FontFace:class {},
  getComputedStyle:el => ({display:el.style.display || 'block', opacity:el.style.opacity ?? 1})};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1], context);
(async () => {
  const frames = [];
  for (const t of data.samples) {
    await context.window.seek(t);
    frames.push({logo:{...nodes.logo.style}, hook:nodes.hook.style.opacity, pill:nodes.pill.style.opacity,
                 graphic:nodes.gfx.style.display, html:nodes.gfxIn?.innerHTML});
  }
  console.log(JSON.stringify({frames, decodes}));
})().catch(e => { console.error(e); process.exitCode = 1; });
"""


@pytest.mark.parametrize("shape", render.SHAPES)
@pytest.mark.parametrize("reject", [False, True])
def test_endcard_hides_corner_logo_and_survives_decode_error(tmp_path, shape, reject):
    kit()
    data = scene(clip(tmp_path), shape=shape)
    data.update(duration=3, rejectDecode=reject, samples=[.5, 1, 1.5, 2.5, 0], shots=[
        {"from": 0, "to": 1, "idx": 0, "layout": "solo"},
        {"from": 1, "to": 2, "idx": 1, "layout": "graphic", "graphic": {"kind": "endcard", "name": "Acme"}},
        {"from": 2, "to": 3, "idx": 2, "layout": "solo"}])
    got = node(SEEK, render.data_path("scene.html"), data=data)
    assert got.returncode == 0, got.stderr
    result = json.loads(got.stdout)
    assert result["decodes"] == 2
    assert [f["logo"]["display"] for f in result["frames"]] == ["block", "none", "none", "block", "block"]
    for frame in result["frames"][1:3]:
        assert frame["graphic"] == "block"
        assert frame["html"].count('class="g-logo"') == 1


@pytest.mark.parametrize("shape, active", [("9x16", "hook"), ("1x1", "pill")])
@pytest.mark.parametrize("overlap", ["hook", "pill", "cap", "quote"])
def test_hook_overlap_is_stable_from_the_first_frame(tmp_path, shape, active, overlap):
    kit()
    data = scene(clip(tmp_path), shape=shape)
    data.update(hookUntil=1, samples=[0, 1 / data["fps"], 1, 0], bounds={
        overlap: {"left": 900, "top": 20, "right": 1060, "bottom": 150, "width": 160, "height": 130}})
    got = node(SEEK, render.data_path("scene.html"), data=data)
    assert got.returncode == 0, got.stderr
    frames = json.loads(got.stdout)["frames"]
    assert frames[0][active] == 0 and frames[1][active] > 0
    opacity = 0 if active == overlap else 1
    assert [f["logo"]["opacity"] for f in frames] == [opacity, opacity, 1, opacity]
