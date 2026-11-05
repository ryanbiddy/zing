"""Pack assets, strict font checks and logos without a judge or downloads."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from myzing.factory import command, judge, render, source, tools
from myzing.factory.tools import FactoryError

RUN = subprocess.run
FONT = {"family": "Brand Sans", "file": "Brand Sans.ttf", "weight": 700, "style": "normal"}


@pytest.fixture(autouse=True)
def offline(monkeypatch, zing_workspace):
    def refuse(*args, **kwargs):
        raise AssertionError("unmocked external operation")
    monkeypatch.setattr(judge.subprocess, "run", refuse)
    monkeypatch.setattr(source, "transcribe_moments", lambda media, pieces: [])


def pack(**fields):
    root = render.user_packs()
    root.mkdir(parents=True, exist_ok=True)
    folder = root / "acme"
    folder.mkdir(exist_ok=True)
    (root / "acme.json").write_text(json.dumps({"name": "Acme", **fields}), encoding="utf-8")
    return folder


def kit(**fields):
    Image = pytest.importorskip("PIL.Image")
    folder = pack(fonts=[FONT], logo="mark #1.png", cap_font="Brand Sans", **fields)
    shutil.copyfile(render.data_path("../fonts/ZingCaption-700.ttf"), folder / FONT["file"])
    Image.new("RGB", (120, 60), (250, 20, 80)).save(folder / "mark #1.png")
    return folder


def clip(tmp_path):
    d = tmp_path / "clip01"
    d.mkdir()
    for file, data in (("plan", {"hook": "Hello", "hook_until": 0, "shots": [{"from": 0, "layout": "solo"}]}),
                       ("words", {"words": [], "duration": .4}),
                       ("cams", {"frames": 1, "size": [120, 120], "cams": [{"from": 0, "to": 1, "mode": "wide"}]})):
        (d / f"{file}.json").write_text(json.dumps(data), encoding="utf-8")
    return d


def scene(d, name="acme", shape="9x16"):
    return render.scene_data(d, shape, name, parallax=False, front=False, sharpen=False)


def node(program, *args, data=None):
    executable = shutil.which("node")
    if not executable:
        pytest.skip("node is needed to run the page's JavaScript")
    return RUN([executable, "-e", program, *map(str, args)], input=json.dumps(data),
               capture_output=True, text=True, encoding="utf-8", timeout=30)


@pytest.mark.parametrize("settings", [{}, {"logo_pos": "bottom-right", "logo_h": 96}])
def test_scene_resolves_fonts_and_logo_without_changing_the_pack(tmp_path, settings):
    folder = kit(**settings)
    original = render.theme("acme")
    data = scene(clip(tmp_path))
    assert data["theme"] == original == render.theme("acme")
    assert data["fonts"] == [{**FONT, "src": (folder / FONT["file"]).resolve().as_uri()}]
    assert data["logo"] == {"file": "mark #1.png", "src": (folder / "mark #1.png").resolve().as_uri(),
                            "pos": settings.get("logo_pos", "top-right"), "h": settings.get("logo_h", 72)}
    assert "%20" in data["fonts"][0]["src"] and "%23" in data["logo"]["src"]
    assert render.check_pack("acme") == []


def test_builtins_and_inline_trials_keep_working(tmp_path):
    d = clip(tmp_path)
    for name in render.themes():
        assert render.check_pack(name) == []
        data = scene(d, name)
        assert data["theme"] == render.theme(name)
        assert "fonts" not in data and "logo" not in data
    assert scene(d, {"cap_font": "Anton"})["theme"] == {"cap_font": "Anton"}


def test_assets_follow_the_selected_pack_folder(tmp_path, monkeypatch):
    folder = kit()
    bundled = tmp_path / "themes"
    bundled.mkdir()
    shutil.copytree(folder, bundled / "acme")
    shutil.copyfile(folder.with_suffix(".json"), bundled / "acme.json")
    original = render.data_path
    monkeypatch.setattr(render, "data_path", lambda *p: bundled.joinpath(*p[1:]) if p[0] == "themes" else original(*p))
    d = clip(tmp_path)
    assert scene(d)["fonts"][0]["src"] == (folder / FONT["file"]).resolve().as_uri()
    folder.with_suffix(".json").unlink()
    assert scene(d)["fonts"][0]["src"] == (bundled / "acme" / FONT["file"]).resolve().as_uri()


@pytest.mark.parametrize("file", ["../outside.ttf", "sub/../../outside.ttf", r"..\outside.ttf",
                                   "/outside.ttf", r"C:\outside.ttf", r"C:outside.ttf", r"\\host\share\outside.ttf"])
@pytest.mark.parametrize("kind", ["font", "logo"])
def test_paths_must_stay_in_the_pack_folder(tmp_path, file, kind):
    fields = {"fonts": [{**FONT, "file": file}]} if kind == "font" else {"logo": file.replace(".ttf", ".png")}
    pack(**fields)
    with pytest.raises(FactoryError, match="must stay inside the pack folder"):
        scene(clip(tmp_path))


@pytest.mark.parametrize("kind", ["font", "logo"])
def test_resolved_symlink_escape_is_rejected(tmp_path, monkeypatch, kind):
    folder = kit()
    linked = folder / (FONT["file"] if kind == "font" else "mark #1.png")
    outside = tmp_path / linked.name
    outside.write_bytes(linked.read_bytes())
    resolve = Path.resolve
    monkeypatch.setattr(Path, "resolve", lambda p, *a, **kw: resolve(outside if p == linked else p, *a, **kw))
    with pytest.raises(FactoryError, match="must stay inside the pack folder"):
        scene(clip(tmp_path))


@pytest.mark.parametrize("fields", [{"fonts": [{**FONT, "file": "font.js"}]}, {"logo": "logo.jpg"}])
def test_bad_extension_is_rejected(tmp_path, fields):
    pack(**fields)
    with pytest.raises(FactoryError, match="bad extension"):
        scene(clip(tmp_path))


@pytest.mark.parametrize("field", ["cap_font", "pill_font", "hook_font", "gfx_font", "quote_font", "panel.font"])
def test_lint_rejects_unknown_families(field):
    fields = {"panel": {"font": "Missing Face"}} if field == "panel.font" else {field: "Missing Face"}
    pack(**fields)
    assert render.check_pack("acme") == [f"{field} uses unknown font family 'Missing Face'"]
    for face in ("Inter", "Anton", "IBM Plex Sans", "Instrument Serif"):
        pack(**({"panel": {"font": face}} if field == "panel.font" else {field: face}))
        assert render.check_pack("acme") == []


@pytest.mark.parametrize("fields", [{"fonts": "face.ttf"}, {"fonts": [{}]}, {"fonts": [{**FONT, "weight": "bold"}]},
                                    {"fonts": [{**FONT, "style": "missing"}]}, {"logo_pos": "middle"},
                                    {"logo_h": 0}, {"logo_h": True}, {"logo_h": float("nan")}])
def test_invalid_brand_settings_fail_lint(fields):
    pack(**fields)
    assert render.check_pack("acme")


def test_check_cli_reports_all_errors_and_exit_codes(capsys):
    pack(fonts=[FONT], logo="missing.png", cap_font="Typo")
    assert command.run(["packs", "--check", "acme"]) == 1
    report = json.loads(capsys.readouterr().out)["acme"]
    assert not report["ok"] and len(report["errors"]) == 3
    assert any("Brand Sans" in e and FONT["file"] in e and "missing" in e for e in report["errors"])
    assert any("logo" in e and "missing.png" in e for e in report["errors"])
    assert any("cap_font" in e and "Typo" in e for e in report["errors"])
    for name in ("no-such-pack", "../acme"):
        assert command.run(["packs", "--check", name]) == 1
        assert json.loads(capsys.readouterr().out)[name]["errors"]
    kit()
    assert command.run(["packs", "--check", "acme"]) == 0
    assert json.loads(capsys.readouterr().out) == {"acme": {"ok": True, "errors": []}}
    assert command.run(["packs"]) == 0
    assert json.loads(capsys.readouterr().out)["acme"] == "Acme"


def test_invalid_json_is_a_check_failure(capsys):
    folder = pack()
    folder.with_suffix(".json").write_text("{", encoding="utf-8")
    assert command.run(["packs", "--check", "acme"]) == 1
    assert not json.loads(capsys.readouterr().out)["acme"]["ok"]


def test_render_checks_pack_before_reading_clip_or_running_tools(tmp_path):
    pack(fonts=[FONT])
    with pytest.raises(FactoryError, match="Brand Sans.*Brand Sans.ttf.*missing"):
        render.render(tmp_path / "not-prepared", pack="acme")
    pack(quote_font="Missing Face")
    with pytest.raises(FactoryError, match="quote_font.*Missing Face"):
        render.render(tmp_path / "not-prepared", pack="acme")


@pytest.mark.parametrize("shape", render.SHAPES)
@pytest.mark.parametrize("position", ["top-left", "top-right", "bottom-right"])
def test_scene_logo_clears_source_and_captions(tmp_path, shape, position):
    kit(logo_pos=position)
    data = scene(clip(tmp_path), shape=shape)
    program = r"""
const fs = require('fs'), vm = require('vm');
const data = JSON.parse(fs.readFileSync(0, 'utf8')), nodes = {}, props = {};
const bounds = {srctag: {left:22, top:20, right:420, bottom:60, width:398, height:40},
                cap: {left:0, top:data.H-110, right:data.W, bottom:data.H-20, width:data.W, height:90}};
const get = id => nodes[id] ||= {style:{}, naturalWidth:120, naturalHeight:60, getBoundingClientRect:() => bounds[id]};
const document = {documentElement:{style:{setProperty:(k,v) => props[k]=v}, dataset:{}}, body:{style:{}},
  fonts:{add() {}, load() {return Promise.resolve();}}, getElementById:get,
  createRange:() => { let el; return {selectNodeContents:e => { el = e; }, getBoundingClientRect:() => el.getBoundingClientRect() || {}}; }};
const context = {window:{DATA:data}, document, FontFace:class {},
  getComputedStyle: el => ({display:Object.keys(bounds).some(id => nodes[id] === el) ? 'block' : 'none', opacity:1})};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1]
  + '\nplaceLogo();', context);
console.log(JSON.stringify({style:nodes.logo.style, props}));
"""
    got = node(program, render.data_path("scene.html"), data=data)
    assert got.returncode == 0, got.stderr
    result = json.loads(got.stdout)
    style = result["style"]
    x, y, w, h = [float(style[k].removesuffix("px")) for k in ("left", "top", "width", "height")]
    assert style["display"] == "block" and h == pytest.approx(72 * data["W"] / 1080)
    assert 0 <= x < x + w <= data["W"] and 0 <= y < y + h <= data["H"]
    assert x >= 420 or y >= 60                                  # the source tag is fixed, so the logo steps past it
    assert y + h <= data["H"] - 110 or style["opacity"] == 0    # a caption under the logo hides it, never moves it
    assert result["props"]["--cap-font"].startswith('"Brand Sans"')


@pytest.mark.parametrize("failure", ["load", "status", "check", "logo", None])
def test_sidecar_verifies_assets_before_capture(tmp_path, failure):
    kit()
    data = scene(clip(tmp_path))
    data["duration"] = 1 / data["fps"]
    data["failure"] = failure
    file = tmp_path / "data.json"
    file.write_text(json.dumps(data), encoding="utf-8")
    program = r"""
const Module = require('module'), assert = require('assert');
const resolve = Module._resolveFilename, load = Module._load;
global.window = {};
let ready = false;
global.document = {fonts:{load:async () => {}, get ready() {ready=true; return Promise.resolve();}},
  createElement:() => ({getContext:() => ({font:'', measureText() {    // the face is in use when it changes the width
    assert(ready && this.font.includes('700'));
    return {width:this.font.includes('Brand Sans') && window.DATA.failure !== 'check' ? 120 : 100}; }})}),
  getElementById:() => ({decode:async () => {}, naturalWidth:window.DATA.failure === 'logo' ? 0 : 120})};
const page = {route:async () => {}, on() {}, addInitScript:async (fn,d) => fn(d),
  goto:async () => { window.packFonts = [{status:window.DATA.failure === 'status' ? 'error' : 'loaded',
    load:async () => {if (window.DATA.failure === 'load') throw Error('decode');}}]; window.seek=() => {}; },
  evaluate:async (fn, arg) => fn(arg), screenshot:async () => {assert(ready); console.log('captured');}};
const playwright = {chromium:{launch:async () => ({close:async () => {}, newPage:async opts => {
  assert(opts.offline && opts.serviceWorkers === 'block'); return page; }})}};
Module._resolveFilename = (s,...rest) => s === 'playwright-core' ? 'brand-playwright' : resolve(s,...rest);
Module._load = (s,...rest) => s === 'brand-playwright' ? playwright : load(s,...rest);
require(process.argv[1]);
"""
    got = node(program, render.data_path("render.cjs"), render.data_path("scene.html"), file, tmp_path / "frames")
    if failure:
        assert got.returncode != 0 and "captured" not in got.stdout
        assert ("mark #1.png" if failure == "logo" else "Brand Sans") in got.stderr
        assert ("mark #1.png" if failure == "logo" else FONT["file"]) in got.stderr
    else:
        assert got.returncode == 0, got.stderr
        assert "captured" in got.stdout


@pytest.fixture
def browser_tools(monkeypatch):
    if not shutil.which("node"):
        pytest.skip("node is needed to run the page's JavaScript")
    if not (tools.sidecar_directory() / "node_modules/playwright-core/package.json").is_file():
        pytest.skip("factory render needs the sidecar and a local browser")
    try:
        tools.browser()
    except FactoryError:
        pytest.skip("factory render needs the sidecar and a local browser")
    allowed = {Path(shutil.which(name)).resolve() for name in ("node", "ffmpeg", "ffprobe") if shutil.which(name)}
    def run(argv, **kwargs):
        assert Path(argv[0]).resolve() in allowed
        return RUN(argv, **kwargs)
    monkeypatch.setattr(subprocess, "run", run)


@pytest.mark.parametrize("bad", ["font", "logo"])
def test_real_capture_rejects_corrupt_assets(tmp_path, browser_tools, bad):
    folder = kit()
    (folder / (FONT["file"] if bad == "font" else "mark #1.png")).write_bytes(b"corrupt")
    d = clip(tmp_path)
    with pytest.raises(FactoryError, match="Brand Sans" if bad == "font" else "mark #1.png"):
        render.render(d, pack="acme", parallax=False, front=False, sharpen=False)
    assert not list(d.glob("out*/*.jpg")) and not list(d.glob("clip*.mp4"))


def test_real_render_with_custom_font_and_logo(tmp_path, browser_tools):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg not installed")
    Image = pytest.importorskip("PIL.Image")
    kit(gfx_font="Brand Sans", cap_weight=700)
    d = clip(tmp_path)
    (d / "words.json").write_text(json.dumps({"words": [{"w": "Brand", "os": 0, "oe": .1}]}), encoding="utf-8")
    (d / "frames").mkdir()
    Image.new("RGB", (120, 120), (10, 10, 10)).save(d / "frames/00001.jpg")
    tools.run(tools.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
              "-t", .4, "-c:a", "aac", d / "cut.mp4", capture_output=True)
    out = render.render(d, "1x1", "acme", parallax=False, front=False, sharpen=False)
    assert out.is_file() and out.stat().st_size > 0
    data = scene(d, shape="1x1")
    data["shots"] = [{"from": 0, "to": 1, "idx": 0, "layout": "graphic",
                      "graphic": {"kind": "endcard", "name": "Acme"}}]
    render.capture(data, d / "endcard.json", d / "endcard", samples=[10])
    with Image.open(d / "endcard/00011.png") as img:
        assert img.size == (1080, 1080)
        assert img.getpixel((1000, 50))[:3] != (250, 20, 80)    # the end card shows the logo once, centered
        assert img.getpixel((540, 215))[:3] == (250, 20, 80)
